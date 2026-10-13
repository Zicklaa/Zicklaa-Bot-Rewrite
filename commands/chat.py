"""KI-Commands (nur im Spam-/Test-Channel): /chat, /hmchat, /image …, /tts."""

import os
from datetime import datetime
from io import BytesIO

import discord
import fal_client
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI

from utils.base import BaseCog, BaseView, UserError, in_channels
from utils.helpers import NO_MENTIONS, split_text, truncate
from utils.settings import SPAM_CHANNEL_ID, TEST_CHANNEL_ID

# -------------------- Konfiguration --------------------

allowed_channels = in_channels(SPAM_CHANNEL_ID, TEST_CHANNEL_ID)

CHAT_MODEL = "gpt-5-mini"
TTS_MODEL = "tts-1-hd"
TTS_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")

# Bildmodelle (fal.ai) je Qualitätsstufe: (Modell, zusätzliche Argumente)
IMAGE_MODELS = {
    # FLUX 1.1 Pro: sehr schnell, gutes Preis-Leistungs-Verhältnis
    "fast": ("fal-ai/flux-pro/v1.1", {"aspect_ratio": "1:1"}),
    # FLUX 1.1 Pro Ultra: High-End; raw=True gäbe natürlichere Fotos ohne "AI-Look"
    "hd": ("fal-ai/flux-pro/v1.1-ultra", {"aspect_ratio": "16:9", "raw": False}),
}

CHAT_SYSTEM_PROMPT = (
    "Du bist ein hilfreicher Assistent."
    "Antworte direkt, präzise und ohne unnötige Meta-Kommentare. "
    "Gib keine Gegenfragen sondern beantworte direkt nach deinem besten Wissen. "
)
HIVEMIND_SYSTEM_PROMPT = (
    "Du bist Discordnutzer von >Bens Haus der Enten<. "
    "Antwort locker mit SUPER EXTREM VIELEN Gen-Z/Gen-Alpha-Slang & Emojis. "
    "Sei dabei auch sehr nonchalant, immer am viben usw. "
    "Benutz keine förmliche Sprache und wenig bis garkeine Punktierung und Groß/Kleinschreibung. "
    "Bau auch eventuell common Abkürzungen und Tippfehler ein bei Gelegenheit."
    "Nie sagen, dass du KI bist."
)
IMAGE_PROMPT_OPTIMIZER = (
    "You are a prompt optimizer for image generation. "
    "Given a short user idea, produce ONE concise yet vivid English prompt "
    "that fully captures the scene, subjects, background, lighting, colors, "
    "textures, camera/composition, mood/emotion, and relevant style keywords. "
    "Be specific but not verbose; avoid lists and meta-commentary. "
    "Return ONLY the final prompt text in English."
)

# Discord-Limits für Embeds
EMBED_TOTAL = 6000
EMBED_DESC = 4096
EMBED_FIELD_VALUE = 1024

# -------------------- Paginierte Antwort --------------------


def build_paginated_embeds(title: str, prompt: str, answer: str, footer_extra: str) -> list[discord.Embed]:
    """Verteilt eine lange Antwort auf mehrere Embeds.

    Die Antwort steht in der Beschreibung (max. 4096 Zeichen pro Seite),
    Titel und Prompt nur auf Seite 1, im Footer „Seite X/Y“.
    """
    pages = split_text(answer, EMBED_DESC) or ["—"]
    embeds = []
    for i, page in enumerate(pages, start=1):
        embed = discord.Embed(description=page, color=0x00FF00)
        embed.set_author(name="ChatGPT")
        embed.set_footer(text=truncate(f"Seite {i}/{len(pages)} • {footer_extra}", 2048))
        if i == 1:
            embed.title = truncate(title, 256)
            if prompt.strip():
                embed.add_field(name="Prompt", value=truncate(prompt, EMBED_FIELD_VALUE), inline=False)

        # Failsafe: ein Embed darf insgesamt höchstens 6000 Zeichen haben
        overflow = len(embed) - EMBED_TOTAL
        if overflow > 0:
            embed.description = truncate(page, len(page) - overflow)
        embeds.append(embed)
    return embeds


class PagedEmbedView(BaseView):
    """Blätter-View für eine Liste von Embeds."""

    def __init__(self, embeds: list[discord.Embed]):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev.disabled = self.index <= 0
        self.next.disabled = self.index >= len(self.embeds) - 1

    async def _show(self, interaction: discord.Interaction, index: int):
        self.index = max(0, min(index, len(self.embeds) - 1))
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, self.index - 1)

    @discord.ui.button(label="Weiter ➡️", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, self.index + 1)


# -------------------- Cog --------------------


class Chat(BaseCog):
    """Cog: Chat, Hivemind-Chat, Bildgenerierung und Text-to-Speech."""

    image = app_commands.Group(name="image", description="Bilder generieren")

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # fal_client liest FAL_KEY selbst aus der Umgebung; hier nur früh prüfen, dass er gesetzt ist
        if not os.environ.get("FAL_KEY"):
            raise RuntimeError("FAL_KEY nicht gesetzt.")
        self.oai = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # ---------- Helper ----------

    async def _complete(self, system: str, user: str) -> tuple[str, int | None]:
        """Chat-Completion; gibt (Antworttext, verbrauchte Tokens) zurück."""
        completion = await self.oai.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = (completion.choices[0].message.content or "").strip()
        return text, getattr(completion.usage, "total_tokens", None)

    async def _send_answer(
        self, interaction: discord.Interaction, *, title: str, prompt: str, answer: str, tokens: int | None
    ):
        """Schickt die Antwort als blätterbares Embed (Footer: Uhrzeit + Kosten)."""
        footer = f"{datetime.now():%H:%M:%S} Uhr"
        if tokens is not None:
            footer += f" • Kosten: {tokens} Tokens = {round(tokens * 0.000125, 8)} Cent"

        embeds = build_paginated_embeds(title, prompt, answer, footer)
        await interaction.followup.send(
            embed=embeds[0], view=PagedEmbedView(embeds), allowed_mentions=NO_MENTIONS
        )

    async def _send_image(self, interaction: discord.Interaction, prompt: str, *, quality: str, nsfw: bool):
        """Generiert ein Bild über fal.ai und schickt es als Datei (NSFW als Spoiler)."""
        model, arguments = IMAGE_MODELS[quality]
        result = await fal_client.subscribe_async(
            model,
            # safety_tolerance: 1 = am strengsten, 6 = uncensored/NSFW erlaubt
            arguments={"prompt": prompt, "safety_tolerance": "6" if nsfw else "2", **arguments},
        )
        async with self.bot.session.get(result["images"][0]["url"]) as resp:
            resp.raise_for_status()
            image = await resp.read()

        filename = ("SPOILER_" if nsfw else "") + "image.jpg"
        await interaction.followup.send(
            file=discord.File(BytesIO(image), filename), allowed_mentions=NO_MENTIONS
        )
        self.log("Image generated", interaction, quality=quality, nsfw=nsfw)

    # ---------- Chat ----------

    @app_commands.command(
        name="chat", description="Frag die Bot Bot.", extras={"error": "Fehler bei der Anfrage. 🤷"}
    )
    @app_commands.describe(
        text="Deine Frage / dein Prompt",
        websearch="Nutze eingebaute Websuche (aus = Standard)",
    )
    @allowed_channels
    async def chat(self, interaction: discord.Interaction, text: str, websearch: bool = False):
        await interaction.response.defer(thinking=True)
        self.log("Chat command", interaction, websearch=websearch)

        resp = await self.oai.responses.create(
            model=CHAT_MODEL,
            input=[
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            **({"tools": [{"type": "web_search"}]} if websearch else {}),
        )
        usage = getattr(resp, "usage", None)

        await self._send_answer(
            interaction,
            title="Antwort von ChatGPT: ",
            prompt=text + ("\n\n[Websuche: aktiviert]" if websearch else ""),
            answer=resp.output_text or "—",
            tokens=getattr(usage, "total_tokens", None),
        )

    @app_commands.command(
        name="hmchat", description="Antwortet im Hivemind-Stil.", extras={"error": "Fehler bei HMChat. 🤷"}
    )
    @allowed_channels
    async def hmchat(self, interaction: discord.Interaction):
        """Lässt ChatGPT auf einen zufälligen Hivemind-Satz antworten."""
        await interaction.response.defer(thinking=True)

        seed = self.bot.hivemind_sentence(max_overlap_ratio=0.65)
        answer, tokens = await self._complete(HIVEMIND_SYSTEM_PROMPT, seed)

        # Erst den Hivemind-Satz posten, dann die Antwort darauf
        await interaction.followup.send(seed, allowed_mentions=NO_MENTIONS)
        await self._send_answer(
            interaction, title="Antwort (Hivemind)", prompt=seed, answer=answer or "—", tokens=tokens
        )
        self.log("HMChat sent", interaction)

    # ---------- Bilder ----------

    @image.command(
        name="pipeline",
        description="HD Bild mit optimiertem Prompt (NSFW, automatisch Spoiler).",
        extras={"error": "Fehler in /image pipeline. 🤷"},
    )
    @app_commands.describe(text="Dein kurzer Input (deutsch ok, ich optimiere ihn).")
    @allowed_channels
    async def image_pipeline(self, interaction: discord.Interaction, text: str):
        """Baut aus kurzem Input einen präzisen englischen Bildprompt und generiert ein HD-NSFW-Bild."""
        await interaction.response.defer(thinking=True)

        optimized_prompt, _ = await self._complete(IMAGE_PROMPT_OPTIMIZER, text)
        if not optimized_prompt:
            raise UserError(
                "Konnte keinen gültigen Bild-Prompt bauen. Versuch es bitte nochmal mit einer anderen Beschreibung."
            )
        await self._send_image(interaction, optimized_prompt, quality="hd", nsfw=True)

    @image.command(name="fast", description="Schnelles Bild (safe).")
    @app_commands.describe(prompt="Bildbeschreibung")
    @allowed_channels
    async def image_fast(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        await self._send_image(interaction, prompt, quality="fast", nsfw=False)

    @image.command(name="hd", description="HD Bild (safe).")
    @app_commands.describe(prompt="Bildbeschreibung")
    @allowed_channels
    async def image_hd(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        await self._send_image(interaction, prompt, quality="hd", nsfw=False)

    @image.command(name="nsfw", description="Schnelles Bild (NSFW, automatisch Spoiler).")
    @app_commands.describe(prompt="Bildbeschreibung")
    @allowed_channels
    async def image_nsfw(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        await self._send_image(interaction, prompt, quality="fast", nsfw=True)

    @image.command(name="hdnsfw", description="HD Bild (NSFW, automatisch Spoiler).")
    @app_commands.describe(prompt="Bildbeschreibung")
    @allowed_channels
    async def image_hdnsfw(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        await self._send_image(interaction, prompt, quality="hd", nsfw=True)

    # ---------- Text-to-Speech ----------

    @app_commands.command(name="tts", description="Text zu Sprache.", extras={"error": "Fehler bei TTS. 🤷"})
    @app_commands.describe(text="Text zum Vorlesen", voice="Stimme")
    @app_commands.choices(voice=[app_commands.Choice(name=v, value=v) for v in TTS_VOICES])
    @allowed_channels
    async def tts(self, interaction: discord.Interaction, text: str, voice: str = "onyx"):
        await interaction.response.defer(thinking=True)

        speech = await self.oai.audio.speech.create(model=TTS_MODEL, voice=voice, input=text)
        await interaction.followup.send(
            file=discord.File(BytesIO(speech.content), "tts.mp3"), allowed_mentions=NO_MENTIONS
        )
        self.log("TTS sent", interaction, voice=voice)


async def setup(bot: commands.Bot):
    await bot.add_cog(Chat(bot))
