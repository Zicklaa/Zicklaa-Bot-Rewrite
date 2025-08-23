import logging
import os
import random
import discord
from discord.ext import commands
from discord import app_commands

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.LustigeBildchen")

# Pfad zu den Bildern
globalPfad = os.environ["globalPfad"]
DIR = os.path.join(globalPfad, "LustigeBildchen/")


class LustigeBildchen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Slash Command ---
    @app_commands.command(name="ltb", description="Postet ein zufälliges lustiges Bildchen.")
    async def ltb(self, interaction: discord.Interaction):
        try:
            # Datei wählen
            file_name = random.choice(os.listdir(DIR))
            file_path = os.path.join(DIR, file_name)

            # Bild senden
            await interaction.response.send_message(file=discord.File(file_path))

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Image sent",
                interaction.user,
                interaction.user.id,
                command="/ltb",
                file=file_name,
            )

        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Image send failed",
                interaction.user,
                interaction.user.id,
                command="/ltb",
                file=file_name if 'file_name' in locals() else None,
                error=e,
                exc_info=True,
            )


# Setup für Cog
async def setup(bot):
    await bot.add_cog(LustigeBildchen(bot))
