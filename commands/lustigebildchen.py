import logging
import os
import random
import discord
from discord.ext import commands
from discord import app_commands

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

            logger.info(
                f"Lustiges Bildchen gepostet für {interaction.user} (ID: {interaction.user.id})"
            )

        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            logger.error(
                f"Lustiges Bildchen ERROR von {interaction.user} (ID: {interaction.user.id}): {e}"
            )


# Setup für Cog
async def setup(bot):
    await bot.add_cog(LustigeBildchen(bot))
