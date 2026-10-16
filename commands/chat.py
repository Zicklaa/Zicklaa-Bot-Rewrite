"""KI-Commands (nur im Spam-/Test-Channel): /chat, /hmchat, /image …, /tts."""

import os
from datetime import datetime
from io import BytesIO

import discord
import fal_client
from discord import app_commands
from discord.ext import commands
import openai
from openai import AsyncOpenAI

from utils.base import BaseCog, BaseView, UserError, in_channels
from utils.helpers import NO_MENTIONS, split_text, truncate
from utils.settings import SPAM_CHANNEL_ID, TEST_CHANNEL_ID

# -------------------- Konfiguration --------------------

allowed_channels = in_channels(SPAM_CHANNEL_ID, TEST_CHANNEL_ID)

CHAT_MODEL = "gpt-6-luna"
# Denkaufwand je Zweck: weniger Reasoning = schneller und billiger.
# Erlaubt: none, low, medium (Standard), high, xhigh, max ("minimal" gibt es bei GPT-6 nicht mehr).
EFFORT_CHAT = "low"
EFFORT_SIMPLE = "none"  # /hmchat und Bild-Prompt-Optimierung
# Websuche mit Standort Deutschland -> deutsche Quellen und Ortsbezug
WEB_SEARCH_TOOL = {
    "type": "web_search",
    "user_location": {"type": "approximate", "country": "DE", "timezone": "Europe/Berlin"},
}
# Preise für CHAT_MODEL in US-Dollar pro 1 Mio. Tokens (Stand 10/2026, developers.openai.com/api/docs/pricing)
# Gelten bis 272K Input-Tokens; darüber wird es teurer, kommt bei Discord-Prompts aber nicht vor.
PRICE_INPUT = 0.10
PRICE_CACHED_INPUT = 0.01
PRICE_OUTPUT = 0.50
# Websuche: 10 $ pro 1.000 Aufrufe; die Suchergebnisse zählen als normale Input-Tokens
PRICE_WEB_SEARCH = 0.01
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICES = (
    "alloy", "ash", "ballad", "cedar", "coral", "echo", "fable",
    "marin", "nova", "onyx", "sage", "shimmer", "verse",
)
TTS_MAX_CHARS = 4096  # API-Limit pro Anfrage

# Bildmodelle (fal.ai) je Qualitätsstufe: (Modell, zusätzliche Argumente)
IMAGE_MODELS = {
    # FLUX 1.1 Pro: sehr schnell, gutes Preis-Leistungs-Verhältnis
    "fast": ("fal-ai/flux-pro/v1.1", {"aspect_ratio": "1:1"}),
    # FLUX 1.1 Pro Ultra: High-End; raw=True gäbe natürlichere Fotos ohne "AI-Look"
    "hd": ("fal-ai/flux-pro/v1.1-ultra", {"aspect_ratio": "16:9", "raw": False}),
}

CHAT_SYSTEM_PROMPT = (
    "Du bist ein hilfreicher Assistent. "
    "Antworte direkt, präzise und ohne unnötige Meta-Kommentare. "
    "Gib keine Gegenfragen sondern beantworte direkt nach deinem besten Wissen. "
)
HIVEMIND_SYSTEM_PROMPT = (
    "Du bist Discordnutzer von >Bens Haus der Enten<. "
    "Antwort locker mit SUPER EXTREM VIELEN Gen-Z/Gen-Alpha-Slang & Emojis. "
    "Sei dabei auch sehr nonchalant, immer am viben usw. "
    "Benutz keine förmliche Sprache und wenig bis garkeine Punktierung und Groß/Kleinschreibung. "
    "Bau auch eventuell common Abkürzungen und Tippfehler ein bei Gelegenheit. "
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


def format_cost(usage, web_searches: int = 0) -> str | None:
    """Kosten einer Anfrage (Responses-API) für den Footer, z. B. „1.234 Tokens ≈ 0,1825 US-Cent“.

    Reasoning-Tokens stecken im Output und werden wie Output berechnet.
    """
    if usage is None:
        return None
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    cached = getattr(usage.input_tokens_details, "cached_tokens", 0) or 0

    dollars = (
        (input_tokens - cached) * PRICE_INPUT
        + cached * PRICE_CACHED_INPUT
        + output_tokens * PRICE_OUTPUT
    ) / 1_000_000 + web_searches * PRICE_WEB_SEARCH
    cents = f"{dollars * 100:.4f}".replace(".", ",")
    tokens = f"{input_tokens + output_tokens:,}".replace(",", ".")
    searches = f" + {web_searches} Websuche{'n' if web_searches != 1 else ''}" if web_searches else ""
    return f"Kosten: {tokens} Tokens{searches} ≈ {cents} US-Cent"


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

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Bekannte OpenAI-Fehler als verständliche Meldung statt des generischen Fehlertexts."""
        original = getattr(error, "original", error)
        if isinstance(original, openai.RateLimitError):
            if getattr(original, "code", None) in ("insufficient_quota", "credit_balance_exhausted"):
                error = UserError("💸 Das OpenAI-Guthaben ist aufgebraucht. Erst wieder aufladen, dann klappt's.")
            else:
                error = UserError("⏳ OpenAI ist gerade überlastet, probier's gleich nochmal.")
        elif isinstance(original, (openai.APIConnectionError, openai.InternalServerError)):
            error = UserError("📡 OpenAI ist gerade nicht erreichbar, probier's später nochmal.")
        await super().cog_app_command_error(interaction, error)

    # ---------- Helper ----------

    async def _ask(self, instructions: str, text: str, *, effort: str, websearch: bool = False):
        """Eine Anfrage über die Responses-API (store=False: nichts bleibt bei OpenAI gespeichert)."""
        return await self.oai.responses.create(
            model=CHAT_MODEL,
            instructions=instructions,
            input=text,
            reasoning={"effort": effort},
            store=False,
            **({"tools": [WEB_SEARCH_TOOL]} if websearch else {}),
        )

    async def _send_answer(
        self, interaction: discord.Interaction, *, title: str, prompt: str, answer: str, cost: str | None
    ):
        """Schickt die Antwort als blätterbares Embed (Footer: Uhrzeit + Kosten)."""
        footer = f"{datetime.now():%H:%M:%S} Uhr"
        if cost:
            footer += f" • {cost}"

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

        resp = await self._ask(CHAT_SYSTEM_PROMPT, text, effort=EFFORT_CHAT, websearch=websearch)
        searches = sum(1 for item in resp.output if item.type == "web_search_call")

        await self._send_answer(
            interaction,
            title="Antwort von ChatGPT",
            prompt=text + ("\n\n[Websuche: aktiviert]" if websearch else ""),
            answer=resp.output_text or "—",
            cost=format_cost(resp.usage, searches),
        )

    @app_commands.command(
        name="hmchat", description="Antwortet im Hivemind-Stil.", extras={"error": "Fehler bei HMChat. 🤷"}
    )
    @allowed_channels
    async def hmchat(self, interaction: discord.Interaction):
        """Lässt ChatGPT auf einen zufälligen Hivemind-Satz antworten."""
        await interaction.response.defer(thinking=True)

        seed = self.bot.hivemind_sentence(max_overlap_ratio=0.65)
        resp = await self._ask(HIVEMIND_SYSTEM_PROMPT, seed, effort=EFFORT_SIMPLE)

        # Erst den Hivemind-Satz posten, dann die Antwort darauf
        await interaction.followup.send(seed, allowed_mentions=NO_MENTIONS)
        await self._send_answer(
            interaction, title="Antwort (Hivemind)", prompt=seed, answer=resp.output_text.strip() or "—",
            cost=format_cost(resp.usage),
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

        optimized_prompt = (await self._ask(IMAGE_PROMPT_OPTIMIZER, text, effort=EFFORT_SIMPLE)).output_text.strip()
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
        if len(text) > TTS_MAX_CHARS:
            raise UserError(f"❌ Zu lang: maximal {TTS_MAX_CHARS} Zeichen.")
        await interaction.response.defer(thinking=True)

        speech = await self.oai.audio.speech.create(model=TTS_MODEL, voice=voice, input=text)
        await interaction.followup.send(
            file=discord.File(BytesIO(speech.content), "tts.mp3"), allowed_mentions=NO_MENTIONS
        )
        self.log("TTS sent", interaction, voice=voice)


async def setup(bot: commands.Bot):
    await bot.add_cog(Chat(bot))
