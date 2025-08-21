import logging
import os
import urllib.request
import requests
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

logger = logging.getLogger("ZicklaaBotRewrite.Wetter")

# Pfad für Wetter-Datei
globalPfad = os.environ["globalPfad"]
WETTER_FILE = Path(globalPfad) / "static" / "wetter.png"


class Wetter(commands.Cog):
    """Cog: /wetter & /asciiwetter – Holt Wetterdaten von wttr.in."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------- /wetter --------------------
    @app_commands.command(
        name="wetter",
        description="Zeigt das Wetter für einen Ort als Bild."
    )
    @app_commands.describe(location="Der gewünschte Ort, z.B. Stuttgart")
    async def wetter(self, interaction: discord.Interaction, location: str):
        """
        Slash: /wetter <Ort>
        - Holt das PNG von wttr.in
        - Sendet es als Bildnachricht
        """
        try:
            await interaction.response.defer()  # Bot "denkt nach" anzeigen

            url_png = f"https://de.wttr.in/{location}_m.png"
            urllib.request.urlretrieve(url_png, WETTER_FILE)

            await interaction.followup.send(
                file=discord.File(WETTER_FILE)
            )
            logger.info("Wetter gepostet für %s (ID: %s), Ort: %s",
                        interaction.user, interaction.user.id, location)

        except Exception as e:
            await interaction.followup.send(
                "Wetter schmetter, sag ich schon immer.", ephemeral=True
            )
            logger.error("Fehler bei /wetter von %s (ID: %s): %s",
                         interaction.user, interaction.user.id, e)

    # -------------------- /asciiwetter --------------------
    @app_commands.command(
        name="asciiwetter",
        description="Zeigt das Wetter für einen Ort als ASCII-Art."
    )
    @app_commands.describe(location="Der gewünschte Ort, z.B. Berlin")
    async def asciiwetter(self, interaction: discord.Interaction, location: str):
        """
        Slash: /asciiwetter <Ort>
        - Holt die Textversion von wttr.in
        - Antwortet als Codeblock
        """
        try:
            await interaction.response.defer(thinking=True)

            url = f"https://wttr.in/{location}?n&T&2&lang=de"
            res = requests.get(url, timeout=10)

            # Entferne nervigen Hinweis aus der API
            text = res.text.replace(
                "Folgen Sie https://twitter.com/igor_chubin für wttr.in Updates", ""
            )

            await interaction.followup.send(
                f"```\n{text}\n```"
            )
            logger.info("Ascii Wetter gepostet für %s (ID: %s), Ort: %s",
                        interaction.user, interaction.user.id, location)

        except Exception as e:
            await interaction.followup.send(
                "Wetter schmetter, sag ich schon immer.", ephemeral=True
            )
            logger.error("Fehler bei /asciiwetter von %s (ID: %s): %s",
                         interaction.user, interaction.user.id, e)


# Standard-Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(Wetter(bot))
