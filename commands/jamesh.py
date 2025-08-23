import logging
import discord
from discord import app_commands
from discord.ext import commands
from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.JamesH")


class JamesH(commands.Cog):
    """Cog: /jamesh – postet den ikonischen Satz zu James Hoffmann Videos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="jamesh",
        description="Postet den berühmten James Hoffmann Satz.",
    )
    async def jamesh(self, interaction: discord.Interaction):
        """
        Slash: /jamesh
        - Antwortet mit festem Text: "Da gibt es ein James Hoffmann Video dazu."
        """
        try:
            await interaction.response.send_message(
                "Da gibt es ein James Hoffmann Video dazu.",
                allowed_mentions=discord.AllowedMentions.none()
            )
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Command executed",
                interaction.user,
                interaction.user.id,
                command="/jamesh",
            )
        except Exception as e:
            await interaction.response.send_message(
                "Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: JamesH()",
                ephemeral=True
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Command failed",
                interaction.user,
                interaction.user.id,
                command="/jamesh",
                error=e,
                exc_info=True,
            )


# Standard Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(JamesH(bot))
