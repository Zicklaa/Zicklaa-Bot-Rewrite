import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ZicklaaBot.Admin")

# deine Discord User-ID hier eintragen
OWNER_ID = 288413759117066241  


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="reload", description="Lädt ein Cog neu (nur für Bot-Owner)."
    )
    @app_commands.describe(extension="Name des Cogs (z.B. fav, chat, remindme)")
    async def reload(self, interaction: discord.Interaction, extension: str):
        # check ob richtiger User
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ Du bist nicht berechtigt, diesen Befehl zu nutzen.", ephemeral=True
            )
            logger.warning(
                f"Unbefugter Reload-Versuch von User {interaction.user} ({interaction.user.id})"
            )
            return

        try:
            self.bot.reload_extension(f"commands.{extension}")
            await interaction.response.send_message(
                f"✅ Cog `{extension}` wurde erfolgreich neu geladen.",
                ephemeral=True
            )
            logger.info(f"Cog {extension} neu geladen von {interaction.user} ({interaction.user.id})")
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Reload von `{extension}`: {e}", ephemeral=True
            )
            logger.error(f"Fehler beim Reload von {extension}: {e}")


async def setup(bot):
    await bot.add_cog(Admin(bot))
