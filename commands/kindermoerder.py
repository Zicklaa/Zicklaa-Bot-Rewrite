"""/kindermoerder & /raul – posten das Raul-GIF (lokale Datei bzw. feste URL)."""

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError
from utils.settings import STATIC_DIR

GIF_PATH = STATIC_DIR / "raul.gif"
CAPTION = "RAUL CRUISEHAUSEN KINDERMÖRDER"
RAUL_URL = "https://cdn.discordapp.com/attachments/122739462210846721/873703041889607720/raul2.gif"


class Kindermoerder(BaseCog):
    """Cog: /kindermoerder & /raul."""

    @app_commands.command(
        name="kindermoerder",
        description="Postet das konfigurierte GIF mit Caption-Text aus der config.",
        extras={"error": "Da hakt was. Prüf bitte den GIF-Pfad und meine Sende-Rechte."},
    )
    async def kindermoerder(self, interaction: discord.Interaction):
        if not GIF_PATH.exists():
            raise UserError(f"Datei nicht gefunden: `{GIF_PATH}` – bitte Pfad prüfen.")

        # Upload kann dauern -> erst "denkt nach" anzeigen
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(content=CAPTION, file=discord.File(GIF_PATH))
        self.log("GIF sent", interaction, channel=interaction.channel_id)

    @app_commands.command(
        name="raul",
        description="Postet das Raul-GIF aus der festen URL.",
        extras={"error": "Senden fehlgeschlagen."},
    )
    async def raul(self, interaction: discord.Interaction):
        await interaction.response.send_message(RAUL_URL)
        self.log("Raul URL sent", interaction, channel=interaction.channel_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Kindermoerder(bot))
