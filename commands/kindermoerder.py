# kindermoerder_cog.py
# -*- coding: utf-8 -*-
"""
Slash-Command-Port für discord.py 2.x
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.logging_helper import log_event

# Erwartete Konfiguration:
globalPfad = os.environ["globalPfad"]
KINDERMOERDER_CAPTION = "RAUL CRUISEHAUSEN KINDERMÖRDER"

logger = logging.getLogger("ZicklaaBotRewrite.Kindermoerder")
logger.setLevel(logging.INFO)

# Fallback, falls in config kein Caption-Text definiert ist
DEFAULT_CAPTION = "GIF-Post"

# Relativer Pfad zum GIF (wie zuvor): globalPfad + "static/raul.gif"
GIF_RELATIVE_PATH = Path("static/raul.gif")

# Optional: Cooldown-Einstellungen (pro Nutzer)
USER_COOLDOWN_SECONDS = 5.0


def _resolve_gif_path() -> Path:
    """Ermittelt den absoluten Pfad zur GIF-Datei anhand von config.globalPfad."""
    base = Path(globalPfad)
    return (base / GIF_RELATIVE_PATH).resolve()


def _safe_caption() -> str:
    """Lese den Caption-Text aus der config, fallback auf DEFAULT_CAPTION."""
    try:
        text = str(KINDERMOERDER_CAPTION).strip()
        return text or DEFAULT_CAPTION
    except Exception:
        return DEFAULT_CAPTION


class Kindermoerder(commands.Cog):
    """Slash-Befehle zum Posten eines lokalen GIFs bzw. einer festen Raul-URL."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- Slash: /kindermoerder -----------------------------------------
    @app_commands.command(
        name="kindermoerder",
        description="Postet das konfigurierte GIF mit Caption-Text aus der config.",
    )
    async def kindermoerder(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=False)

        gif_path = _resolve_gif_path()
        if not gif_path.exists():
            msg = f"Datei nicht gefunden: `{gif_path}` – bitte Pfad prüfen."
            await interaction.followup.send(msg)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "GIF missing",
                interaction.user,
                interaction.user.id,
                command="/kindermoerder",
                path=gif_path,
            )
            return

        try:
            file = discord.File(gif_path, filename=gif_path.name)
            caption = _safe_caption()

            sent = await interaction.followup.send(content=caption, file=file)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "GIF sent",
                interaction.user,
                interaction.user.id,
                command="/kindermoerder",
                guild=getattr(interaction.guild, "name", None),
                channel=getattr(interaction.channel, "id", None),
                file=gif_path,
            )
        except Exception as e:
            await interaction.followup.send(
                "Da hakt was. Prüf bitte den GIF-Pfad und meine Sende-Rechte."
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "GIF send failed",
                interaction.user,
                interaction.user.id,
                command="/kindermoerder",
                file=gif_path,
                error=e,
                exc_info=True,
            )

    # ---- Slash: /raul ---------------------------------------------------
    @app_commands.command(
        name="raul",
        description="Postet das Raul-GIF aus der festen URL.",
    )
    async def raul(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=False)

        url = (
            "https://cdn.discordapp.com/attachments/122739462210846721/873703041889607720/raul2.gif"
        )
        try:
            await interaction.followup.send(url)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Raul URL sent",
                interaction.user,
                interaction.user.id,
                command="/raul",
                guild=getattr(interaction.guild, "name", None),
                channel=getattr(interaction.channel, "id", None),
            )
        except Exception as e:
            await interaction.followup.send("Senden fehlgeschlagen.")
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Raul URL failed",
                interaction.user,
                interaction.user.id,
                command="/raul",
                error=e,
                exc_info=True,
            )


# -------- Extension Setup (discord.py 2.x) -------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Kindermoerder(bot))
