import logging
import discord
from discord import app_commands
from discord.ext import commands
from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Ping")


class Ping(commands.Cog):
    """Cog for the /ping command with enhanced visuals and latency details."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Zeigt die aktuelle Latenz des Bots.",
    )
    async def ping(self, interaction: discord.Interaction) -> None:
        """
        Responds with an embed showing WebSocket and API latency.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            ws_latency = round(self.bot.latency * 1000)

            embed = discord.Embed(
                title="🏓 Pong!",
                description=f"Die aktuelle Latenz beträgt **{ws_latency} ms**.",
                color=discord.Color.green() if ws_latency < 150 else (discord.Color.yellow() if ws_latency < 300 else discord.Color.red()),
                timestamp=interaction.created_at
            )
            
            embed.set_footer(
                text=f"Geprüft von {interaction.user}",
                icon_url=interaction.user.display_avatar.url
            )

            await interaction.edit_original_response(embeds=[embed])

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Command executed",
                interaction.user,
                interaction.user.id,
                command="/ping",
                latency=ws_latency,
            )

        except Exception as e:
            await interaction.followup.send("❌ Konnte Ping-Status nicht abrufen.", ephemeral=True)
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
