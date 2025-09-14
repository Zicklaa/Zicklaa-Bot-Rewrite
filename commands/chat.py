# commands/chat.py
from io import BytesIO
import logging
import os
from datetime import datetime
import asyncio
import re
from typing import List, Tuple

import discord
from discord.ext import commands
from discord import app_commands

import requests
import fal_client
from openai import AsyncOpenAI

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Chat")

# ---- Konfiguration ----
ALLOWED_CHANNELS = {528742785935998979, 567411189336768532}

ALLOWED_MENTIONS = discord.AllowedMentions(
    users=False,
    everyone=False,
    roles=False,
    replied_user=False,
)

TTS_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")

# ---- Discord Embed Limits ----
EMBED_LIMITS = {
    "TOTAL": 6000,
    "TITLE": 256,
    "DESC": 4096,
    "FIELD_NAME": 256,
    "FIELD_VALUE": 1024,
    "FIELDS_MAX": 25,
    "FOOTER": 2048,
    "AUTHOR": 256,
}
ELLIPSIS = "…"


def _format_cost(total_tokens: int) -> str:
    return f"{round(total_tokens * 0.000125, 8)} Cent"


def clamp(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    t = text.strip()
    if len(t) <= max_len:
        return t
    cut = t[: max(0, max_len - len(ELLIPSIS))]
    space = cut.rfind(" ")
    if space >= int(max_len * 0.6):
        cut = cut[:space]
    return (cut.rstrip() + ELLIPSIS) if cut else t[:max_len]


def soft_chunks(text: str, max_len: int) -> List[str]:
    """Teile Text bevorzugt an Absätzen/Zeilen/Satzenden; überschreite nie max_len."""
    text = (text or "").strip()
    if not text:
        return ["—"]
    if len(text) <= max_len:
        return [text]

    parts = re.split(r"(\n\n|\n|(?<=[.!?])\s+)", text)
    chunks, buf = [], ""
    for piece in parts:
        if len(buf) + len(piece) <= max_len:
            buf += piece
        else:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            while len(piece) > max_len:
                chunks.append(piece[:max_len])
                piece = piece[max_len:]
            buf = piece
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def count_embed_len(title="", description="", fields: Tuple[Tuple[str, str, bool], ...] = (), footer_text="", author_name=""):
    total = len(title or "") + len(description or "") + \
        len(footer_text or "") + len(author_name or "")
    for name, value, _ in fields:
        total += len(name or "") + len(value or "")
    return total


def build_paginated_embeds(
    *,
    title: str | None,
    prompt_label: str,
    prompt_text: str,
    answer_text: str,
    footer_extra: str | None,
    author_name: str | None,
    color: int | None = None,
) -> List[discord.Embed]:
    """
    Baut seitenweise Embeds:
    - Antwort läuft in description und wird auf 4096-Limit gesplittet.
    - Prompt als Feld nur auf Seite 1.
    - Footer mit Seite X/Y (+ optional extra Info).
    - Letzter Failsafe fürs 6000-Zeichen-Gesamtbudget.
    """
    title = clamp(title, EMBED_LIMITS["TITLE"])
    author_name = clamp(author_name, EMBED_LIMITS["AUTHOR"])
    footer_extra = clamp(footer_extra, EMBED_LIMITS["FOOTER"])
    prompt_name = clamp(prompt_label, EMBED_LIMITS["FIELD_NAME"]) or "Prompt"
    prompt_val = clamp(prompt_text, EMBED_LIMITS["FIELD_VALUE"])

    desc_pages = soft_chunks(answer_text, EMBED_LIMITS["DESC"])
    total_pages = len(desc_pages)

    embeds: List[discord.Embed] = []
    for i, page in enumerate(desc_pages, start=1):
        e = discord.Embed(description=page)
        if color is not None:
            e.colour = color
        if i == 1 and title:
            e.title = title
        if author_name:
            e.set_author(name=author_name)
        if i == 1 and prompt_val:
            e.add_field(name=prompt_name, value=prompt_val, inline=False)

        page_tag = f"Seite {i}/{total_pages}"
        footer_txt = page_tag if not footer_extra else f"{page_tag} • {footer_extra}"
        e.set_footer(text=clamp(footer_txt, EMBED_LIMITS["FOOTER"]))

        # Failsafe: 6000 Gesamtbudget
        total_len = count_embed_len(
            title=e.title or "",
            description=e.description or "",
            fields=tuple((f.name, f.value, f.inline) for f in e.fields),
            footer_text=e.footer.text if e.footer else "",
            author_name=e.author.name if e.author else "",
        )
        if total_len > EMBED_LIMITS["TOTAL"]:
            overflow = total_len - EMBED_LIMITS["TOTAL"]
            target = max(0, len(e.description) - overflow - len(ELLIPSIS))
            e.description = clamp(e.description, target)

        embeds.append(e)

    return embeds


class PagedEmbedView(discord.ui.View):
    """Blätter-View für eine Liste von Embeds. Prev/Next mit Zustandslogik."""

    def __init__(self, embeds: List[discord.Embed]):
        super().__init__(timeout=180)  # optional: Auto-Timeout nach 3 Minuten
        self.embeds = embeds
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self):
        # Buttons anhand Position aktivieren/deaktivieren
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "prev":
                    item.disabled = self.index <= 0
                elif item.custom_id == "next":
                    item.disabled = self.index >= len(self.embeds) - 1

    async def _update(self, interaction: discord.Interaction):
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
        await self._update(interaction)

    @discord.ui.button(label="Weiter ➡️", style=discord.ButtonStyle.primary, custom_id="next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index < len(self.embeds) - 1:
            self.index += 1
        await self._update(interaction)


class Chat(commands.Cog):
    """Slash-Commands: Chat, Hivemind, Image, TTS"""

    image = app_commands.Group(name="image", description="Bilder generieren")

    def __init__(self, bot: commands.Bot, json_model):
        self.bot = bot
        self.json_model = json_model

        # Keys aus ENV
        self.openai_api_key = os.environ["OPENAI_API_KEY"]
        self.fal_key = os.environ["FAL_KEY"]
        os.environ["FAL_KEY"] = self.fal_key

        # Asynchroner OpenAI Client (blockiert den Event-Loop nicht)
        self.oai = AsyncOpenAI(api_key=self.openai_api_key)

    # ========= Helper =========

    def _now_hhmmss(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    async def _ensure_allowed(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id in ALLOWED_CHANNELS:
            return True
        await interaction.response.send_message("Spam woanders, Moruk 🤷", ephemeral=True)
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "Wrong channel",
            interaction.user,
            interaction.user.id,
            channel_id=interaction.channel_id,
        )
        return False

    async def _send_paginated_embed(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        prompt: str,
        answer: str,
        tokens: int | None = None,
    ):
        time_txt = self._now_hhmmss()
        footer_extra = f"{time_txt} Uhr"
        if tokens is not None:
            cost_txt = _format_cost(tokens)
            footer_extra = f"{footer_extra} • Kosten: {tokens} Tokens = {cost_txt}"

        embeds = build_paginated_embeds(
            title=title,
            prompt_label="Prompt",
            prompt_text=prompt,
            answer_text=answer,
            footer_extra=footer_extra,
            author_name="ChatGPT",
            color=0x00FF00,
        )
        view = PagedEmbedView(embeds)

        # starte mit Seite 1 (Index 0)
        await interaction.followup.send(
            embed=embeds[0],
            view=view,
            allowed_mentions=ALLOWED_MENTIONS,
        )

    async def _get_image_and_send(
        self,
        interaction: discord.Interaction,
        prompt: str,
        *,
        quality: str,   # "fast" oder "hd"
        nsfw: bool,     # True/False
    ):
        # fal_client ist sync; in Thread auslagern
        def _work():
            if quality == "fast":
                model = "schnell"
                num_inference_steps = 2
            else:
                model = "dev"
                num_inference_steps = 28

            handler = fal_client.submit(
                f"fal-ai/flux/{model}",
                arguments={
                    "prompt": prompt,
                    "num_inference_steps": num_inference_steps,
                    "enable_safety_checker": not nsfw,
                },
            )
            result = handler.get()
            image_url = result["images"][0]["url"]
            resp = requests.get(image_url, timeout=60)
            resp.raise_for_status()
            return resp.content

        content = await asyncio.to_thread(_work)

        filename = ("SPOILER_" if nsfw else "") + "image.jpg"
        await interaction.followup.send(
            file=discord.File(BytesIO(content), filename),
            allowed_mentions=ALLOWED_MENTIONS,
        )
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "Image generated",
            interaction.user,
            interaction.user.id,
            quality=quality,
            nsfw=nsfw,
        )

    # ========= Slash Commands =========

    @app_commands.command(name="chat", description="Frag die Bot Bot.")
    @app_commands.describe(
        text="Deine Frage / dein Prompt",
        websearch="Nutze eingebaute Websuche (aus = Standard)"
    )
    async def chat(self, interaction: discord.Interaction, text: str, websearch: bool = False):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "Chat command",
            interaction.user,
            interaction.user.id,
            command="/chat",
            websearch=websearch,
        )

        # ---- Responses API Call in Thread (blockiert den Event-Loop nicht) ----
        def _responses_work(prompt_text: str, use_web: bool):
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_api_key)

            tools = [{"type": "web_search"}] if use_web else []

            inputs = [
                {
                    "role": "system",
                    "content": (
                        "Du bist ein hilfreicher Assistent."
                        "Antworte direkt, präzise und ohne unnötige Meta-Kommentare. "
                        "Gib keine Gegenfragen sondern beantworte direkt nach deinem besten Wissen. "
                    ),
                },
                {"role": "user", "content": prompt_text},
            ]

            resp = client.responses.create(
                model="gpt-5-mini",
                input=inputs,
                tools=tools or None,
            )
            return resp

        try:
            resp = await asyncio.to_thread(_responses_work, text, websearch)

            # ---- Text extrahieren ----
            answer_text = getattr(resp, "output_text", None)
            if not answer_text:
                chunks = []
                for item in getattr(resp, "output", []) or []:
                    for c in getattr(item, "content", []) or []:
                        if getattr(c, "type", "") in ("output_text", "text"):
                            chunks.append(getattr(c, "text", "")
                                          or getattr(c, "value", ""))
                answer_text = (
                    "\n".join([t for t in chunks if t])).strip() or "—"

            # ---- Usage / Tokens (falls vorhanden) ----
            tokens = None
            try:
                usage = getattr(resp, "usage", None)
                if usage and getattr(usage, "total_tokens", None) is not None:
                    tokens = usage.total_tokens
            except Exception:
                tokens = None

            # ---- Antwort als paginiertes Embed ----
            title = f"Antwort von ChatGPT: "
            await self._send_paginated_embed(
                interaction,
                title=title,
                prompt=text +
                ("" if not websearch else "\n\n[Websuche: aktiviert]"),
                answer=answer_text,
                tokens=tokens,
            )

        except Exception as e:
            await interaction.followup.send("Fehler bei der Anfrage. 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Chat command failed",
                interaction.user,
                interaction.user.id,
                command="/chat",
                websearch=websearch,
                error=e,
                exc_info=True,
            )

    @app_commands.command(name="hmchat", description="Antwortet im Hivemind-Stil.")
    async def hmchat(self, interaction: discord.Interaction):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)

        text = None
        for _ in range(10):
            s = self.json_model.make_sentence(max_overlap_ratio=0.65)
            if s:
                text = s
                break
        if not text:
            await interaction.followup.send("Konnte grad nix Gescheites generieren. 😅", ephemeral=True)
            return

        try:
            completion = await self.oai.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Du bist Discordnutzer von >Bens Haus der Enten<. "
                            "Antwort locker mit SUPER EXTREM VIELEN Gen-Z/Gen-Alpha-Slang & Emojis. "
                            "Sei dabei auch sehr nonchalant, immer am viben usw. "
                            "Benutz keine förmliche Sprache und wenig bis garkeine Punktierung und Groß/Kleinschreibung. "
                            "Bau auch eventuell common Abkürzungen und Tippfehler ein bei Gelegenheit."
                            "Nie sagen, dass du KI bist."
                        )
                    },
                    {"role": "user", "content": text}
                ],
            )
            answer = completion.choices[0].message.content or "—"
            tokens = getattr(completion.usage, "total_tokens", None)

            # Seed-Text einmal posten
            await interaction.followup.send(text, allowed_mentions=ALLOWED_MENTIONS)
            # Antwort als paginiertes Embed mit Buttons
            await self._send_paginated_embed(
                interaction,
                title="Antwort (Hivemind)",
                prompt=text,
                answer=answer,
                tokens=tokens,
            )

        except Exception as e:
            await interaction.followup.send("Fehler bei HMChat. 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "HMChat failed",
                interaction.user,
                interaction.user.id,
                command="/hmchat",
                error=e,
                exc_info=True,
            )

    # ==== Image Commands ====

    @image.command(name="pipeline", description="HD Bild mit optimiertem Prompt (NSFW, automatisch Spoiler).")
    @app_commands.describe(text="Dein kurzer Input (deutsch ok, ich optimiere ihn).")
    async def image_pipeline(self, interaction: discord.Interaction, text: str):
        """
        Nimmt kurzen User-Input, baut daraus einen kompakten, präzisen EN-Bildprompt
        und generiert ein HD-NSFW Bild (automatisch mit Spoiler-Tag).
        """
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)

        # Prompt-Optimierung (kompakt, englisch, bildgenerator-freundlich)
        system_preprompt = (
            "You are a prompt optimizer for image generation. "
            "Given a short user idea, produce ONE concise yet vivid English prompt "
            "that fully captures the scene, subjects, background, lighting, colors, "
            "textures, camera/composition, mood/emotion, and relevant style keywords. "
            "Be specific but not verbose; avoid lists and meta-commentary. "
            "Return ONLY the final prompt text in English."
        )

        try:
            completion = await self.oai.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": system_preprompt},
                    {"role": "user", "content": text},
                ],
            )
            optimized_prompt = (
                completion.choices[0].message.content or "").strip()

            if not optimized_prompt:
                await interaction.followup.send(
                    "Konnte keinen gültigen Bild-Prompt bauen. Versuch es bitte nochmal mit einer anderen Beschreibung.",
                    ephemeral=True,
                )
                log_event(
                    logger,
                    logging.WARNING,
                    self.__class__.__name__,
                    "Pipeline prompt empty",
                    interaction.user,
                    interaction.user.id,
                    command="/image pipeline",
                    raw_input=text,
                )
                return

            # Bild erzeugen: HD + NSFW (=> Spoiler-Dateiname in _get_image_and_send)
            await self._get_image_and_send(
                interaction,
                optimized_prompt,
                quality="hd",
                nsfw=True,
            )

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Pipeline image generated",
                interaction.user,
                interaction.user.id,
                command="/image pipeline",
                optimized_prompt_len=len(optimized_prompt),
            )

        except Exception as e:
            await interaction.followup.send("Fehler in /image pipeline. 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Pipeline failed",
                interaction.user,
                interaction.user.id,
                command="/image pipeline",
                error=e,
                exc_info=True,
            )

    @image.command(name="fast", description="Schnelles Bild (safe).")
    @app_commands.describe(prompt="Bildbeschreibung")
    async def image_fast(self, interaction: discord.Interaction, prompt: str):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        await self._get_image_and_send(interaction, prompt, quality="fast", nsfw=False)

    @image.command(name="hd", description="HD Bild (safe).")
    @app_commands.describe(prompt="Bildbeschreibung")
    async def image_hd(self, interaction: discord.Interaction, prompt: str):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        await self._get_image_and_send(interaction, prompt, quality="hd", nsfw=False)

    @image.command(name="nsfw", description="Schnelles Bild (NSFW, automatisch Spoiler).")
    @app_commands.describe(prompt="Bildbeschreibung")
    async def image_nsfw(self, interaction: discord.Interaction, prompt: str):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        await self._get_image_and_send(interaction, prompt, quality="fast", nsfw=True)

    @image.command(name="hdnsfw", description="HD Bild (NSFW, automatisch Spoiler).")
    @app_commands.describe(prompt="Bildbeschreibung")
    async def image_hdnsfw(self, interaction: discord.Interaction, prompt: str):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        await self._get_image_and_send(interaction, prompt, quality="hd", nsfw=True)

    # ==== TTS Command ====

    @app_commands.command(name="tts", description="Text zu Sprache.")
    @app_commands.describe(text="Text zum Vorlesen", voice="Stimme")
    @app_commands.choices(voice=[app_commands.Choice(name=v, value=v) for v in TTS_VOICES])
    async def tts(self, interaction: discord.Interaction, text: str, voice: str = "onyx"):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "TTS command",
            interaction.user,
            interaction.user.id,
            command="/tts",
            voice=voice,
        )

        # sync-TTS in Thread verschieben
        def _tts_work():
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_api_key)
            completion = client.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=text,
            )
            return completion.content

        try:
            audio_bytes = await asyncio.to_thread(_tts_work)
            mp3_file = BytesIO(audio_bytes)
            mp3_file.seek(0)
            await interaction.followup.send(
                file=discord.File(mp3_file, "tts.mp3"), allowed_mentions=ALLOWED_MENTIONS
            )
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "TTS sent",
                interaction.user,
                interaction.user.id,
                command="/tts",
                voice=voice,
            )
        except Exception as e:
            await interaction.followup.send("Fehler bei TTS. 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "TTS failed",
                interaction.user,
                interaction.user.id,
                command="/tts",
                voice=voice,
                error=e,
                exc_info=True,
            )


async def setup(bot):
    await bot.add_cog(Chat(bot, bot.json_model))
