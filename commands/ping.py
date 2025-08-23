import logging
import discord
from discord import app_commands
from discord.ext import commands
from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Ping")


class Ping(commands.Cog):
    """Cog for the /ping command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Antwortet mit Pong und Latenz.",
    )
    async def ping(self, interaction: discord.Interaction) -> None:
        """
        Responds with 'Pong!' and the bot's latency in milliseconds.
        """
        try:
            latency_ms = round(self.bot.latency * 1000)
            await interaction.response.send_message(
                f"Pong! 🏓 {latency_ms} ms",
                ephemeral=True
            )
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Command executed",
                interaction.user,
                interaction.user.id,
                command="/ping",
                latency=latency_ms,
            )
        except Exception as e:
            await interaction.response.send_message("❌ Konnte Ping nicht senden.", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Command failed",
                interaction.user,
                interaction.user.id,
                command="/ping",
                error=e,
                exc_info=True,
            )


async def setup(bot: commands.Bot) -> None:
    """
    Registers the Ping cog with the bot.
    """
    await bot.add_cog(Ping(bot))
