# commands/chat.py
from io import BytesIO
import logging
import os
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands

import requests
import fal_client
from openai import OpenAI  # offizielles OpenAI SDK (v1)

logger = logging.getLogger("ZicklaaBot.Chat")

# ---- Konfiguration ----
ALLOWED_CHANNELS = {528742785935998979, 567411189336768532}

ALLOWED_MENTIONS = discord.AllowedMentions(
    users=False,
    everyone=False,
    roles=False,
    replied_user=False,
)

TTS_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
MAX_TOKENS = 500  # immer maximale Länge für Antworten


def _format_cost(total_tokens: int) -> str:
    return f"{round(total_tokens * 0.00000015, 8)} Cent"


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

        self.oai = OpenAI(api_key=self.openai_api_key)

    # ========= Helper =========

    def _now_hhmmss(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    async def _ensure_allowed(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id in ALLOWED_CHANNELS:
            return True
        await interaction.response.send_message("Spam woanders, Moruk 🤷", ephemeral=True)
        logger.info(
            f"Command in falschem Channel: {interaction.user} @ {interaction.channel_id}")
        return False

    async def _send_chat_embed(
        self,
        interaction: discord.Interaction,
        title: str,
        prompt: str,
        answer: str,
        tokens: int,
    ):
        time_txt = self._now_hhmmss()
        cost_txt = _format_cost(tokens)
        embed = discord.Embed(
            title=title,
            description=f"Prompt: {prompt}" if len(answer) <= 1023 else answer,
            color=0x00FF00,
        )
        embed.set_author(
            name="ChatGPT",
            icon_url="https://upload.wikimedia.org/wikipedia/commons/thumb/0/04/ChatGPT_logo.svg/1024px-ChatGPT_logo.svg.png",
        )
        if len(answer) <= 1023:
            embed.add_field(name="Antwort", value=answer, inline=False)
        embed.set_footer(
            text=f"{time_txt} Uhr | Kosten: {tokens} Tokens = {cost_txt}")
        await interaction.followup.send(embed=embed, allowed_mentions=ALLOWED_MENTIONS)

    async def _get_image_and_send(
        self,
        interaction: discord.Interaction,
        prompt: str,
        *,
        quality: str,   # "fast" oder "hd"
        nsfw: bool,     # True/False
    ):
        # Qualität -> Modell
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

        # Spoiler nur bei NSFW automatisch
        filename = ("SPOILER_" if nsfw else "") + "image.jpg"

        await interaction.followup.send(
            file=discord.File(BytesIO(resp.content), filename),
            allowed_mentions=ALLOWED_MENTIONS,
        )
        logger.info(f"Bild gesendet ({quality}, nsfw={nsfw})")

    # ========= Slash Commands =========

    @app_commands.command(name="chat", description="Frag die KI (immer gpt-4o, max Tokens).")
    @app_commands.describe(text="Deine Frage / dein Prompt")
    async def chat(self, interaction: discord.Interaction, text: str):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)
        logger.info(f"/chat von {interaction.user}")

        try:
            completion = self.oai.chat.completions.create(
                model="gpt-4o",
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": text}],
            )
            answer = completion.choices[0].message.content or "—"
            tokens = getattr(completion.usage, "total_tokens", 0)
            await self._send_chat_embed(interaction, "Antwort von ChatGPT", text, answer, tokens)
        except Exception as e:
            await interaction.followup.send("Fehler bei der Anfrage. 🤷", ephemeral=True)
            logger.error(f"/chat Error ({interaction.user}): {e}")

    @app_commands.command(name="hmchat", description="Antwortet im Hivemind-Stil (immer gpt-4o, max Tokens).")
    async def hmchat(self, interaction: discord.Interaction):
        if not await self._ensure_allowed(interaction):
            return
        await interaction.response.defer(thinking=True)

        base_text = None
        for _ in range(10):
            s = self.json_model.make_sentence(max_overlap_ratio=0.65)
            if s:
                base_text = s
                break
        if not base_text:
            await interaction.followup.send("Konnte grad nix Gescheites generieren. 😅", ephemeral=True)
            return

        try:
            preprompt = (
                "Du bist Discordnutzer von >Bens Haus der Enten<. "
                "Antwort locker mit Gen-Z und Gen Alpha Slang & Emojis. "
                "Nie sagen, dass du KI bist. "
                "Hier der Text:\n\n"
            )
            completion = self.oai.chat.completions.create(
                model="gpt-4o",
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": preprompt + base_text}],
            )
            answer = completion.choices[0].message.content or "—"
            tokens = getattr(completion.usage, "total_tokens", 0)

            await interaction.followup.send(base_text, allowed_mentions=ALLOWED_MENTIONS)
            await self._send_chat_embed(interaction, "Antwort (Hivemind)", base_text, answer, tokens)
        except Exception as e:
            await interaction.followup.send("Fehler bei HMChat. 🤷", ephemeral=True)
            logger.error(f"/hmchat Error: {e}")

    # ==== Image Commands ====

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
        logger.info(f"/tts von {interaction.user}: voice={voice}")

        try:
            completion = self.oai.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=text,
            )
            mp3_file = BytesIO(completion.content)
            mp3_file.seek(0)
            await interaction.followup.send(
                file=discord.File(mp3_file, "tts.mp3"), allowed_mentions=ALLOWED_MENTIONS
            )
            logger.info("TTS gesendet.")
        except Exception as e:
            await interaction.followup.send("Fehler bei TTS. 🤷", ephemeral=True)
            logger.error(f"/tts Error: {e}")


async def setup(bot):
    await bot.add_cog(Chat(bot, bot.json_model))
