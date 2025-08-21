import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ZicklaaBotRewrite.Git")

# Optional: Falls du den Link später zentral ändern möchtest
REPO_URL = "https://github.com/Zicklaa/Zicklaa-Bot-Rewrite"


class Git(commands.Cog):
    """Cog für den Befehl /git – gibt den GitHub-Link des Bots aus."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="git",
        description="Zeigt den GitHub-Link des Bots an."
    )
    async def git(self, interaction: discord.Interaction):
        """
        Slash-Befehl: /git
        Antwortet mit dem Repository-Link. Mentions werden unterdrückt.
        """
        try:
            await interaction.response.send_message(
                REPO_URL,
                allowed_mentions=discord.AllowedMentions.none()
            )
            logger.info(
                "Git-Link an %s (ID: %s) gesendet.",
                interaction.user, interaction.user.id
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: git_gud()",
                ephemeral=True
            )
            logger.error(
                "Fehler bei /git von %s (ID: %s): %s",
                interaction.user, interaction.user.id, e
            )


# Standard-Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(Git(bot))
