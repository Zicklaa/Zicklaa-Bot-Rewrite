"""/git – gibt den GitHub-Link des Bots aus."""

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog
from utils.helpers import NO_MENTIONS

REPO_URL = "https://github.com/Zicklaa/Zicklaa-Bot-Rewrite"


class Git(BaseCog):
    """Cog: /git – Link zum Repository."""

    @app_commands.command(
        name="git",
        description="Zeigt den GitHub-Link des Bots an.",
        extras={"error": "❌ Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: git_gud()"},
    )
    async def git(self, interaction: discord.Interaction):
        await interaction.response.send_message(REPO_URL, allowed_mentions=NO_MENTIONS)
        self.log("Command executed", interaction, url=REPO_URL)


async def setup(bot: commands.Bot):
    await bot.add_cog(Git(bot))
