"""/ltb – postet ein zufälliges lustiges Bildchen aus dem Bilder-Ordner."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog
from utils.settings import BILDCHEN_DIR


class LustigeBildchen(BaseCog):
    """Cog: /ltb – zufällige Datei aus LustigeBildchen/."""

    @app_commands.command(name="ltb", description="Postet ein zufälliges lustiges Bildchen.")
    async def ltb(self, interaction: discord.Interaction):
        # Nur Dateien direkt im Ordner, keine Unterordner
        file = random.choice([f for f in BILDCHEN_DIR.iterdir() if f.is_file()])
        await interaction.response.send_message(file=discord.File(file))
        self.log("Image sent", interaction, file=file.name)


async def setup(bot: commands.Bot):
    await bot.add_cog(LustigeBildchen(bot))
