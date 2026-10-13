"""/jamesh – postet den ikonischen Satz zu James Hoffmann Videos."""

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog
from utils.helpers import NO_MENTIONS


class JamesH(BaseCog):
    """Cog: /jamesh – fester Text."""

    @app_commands.command(
        name="jamesh",
        description="Postet den berühmten James Hoffmann Satz.",
        extras={"error": "Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: JamesH()"},
    )
    async def jamesh(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Da gibt es ein James Hoffmann Video dazu.", allowed_mentions=NO_MENTIONS
        )
        self.log("Command executed", interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(JamesH(bot))
