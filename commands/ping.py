import discord
from discord import app_commands
from discord.ext import commands


class Ping(commands.Cog):
    """Cog for the /ping command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Antwortet mit Pong und Latenz."
    )
    async def ping(self, interaction: discord.Interaction) -> None:
        """
        Responds with 'Pong!' and the bot's latency in milliseconds.
        """
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"Pong! 🏓 {latency_ms} ms",
            ephemeral=True  # Only the user sees the response
        )


async def setup(bot: commands.Bot) -> None:
    """
    Registers the Ping cog with the bot.
    """
    await bot.add_cog(Ping(bot))
