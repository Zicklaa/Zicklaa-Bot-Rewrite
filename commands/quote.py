import logging
import discord
import pytz
from discord import app_commands
from discord.ext import commands
from dateutil import tz

logger = logging.getLogger("ZicklaaBotRewrite.Quote")


class Quote(commands.Cog):
    """Cog für den Befehl /quote – zitiert eine Nachricht als Embed."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="quote",
        description="Zitiert eine Nachricht anhand ihres Links."
    )
    @app_commands.describe(
        link="Nachrichtenlink (Rechtsklick auf eine Nachricht → Link kopieren)"
    )
    async def quote(self, interaction: discord.Interaction, link: str):
        """
        Slash-Befehl: /quote link:<Nachrichten-URL>
        - Holt eine Nachricht anhand des Links
        - Erstellt daraus ein Embed mit Text, Anhang und Metadaten
        """
        try:
            if not link:
                await interaction.response.send_message(
                    "❌ Bitte gib einen Nachrichtenlink an!", ephemeral=True
                )
                logger.info(
                    "/quote ohne Link von %s (ID: %s)",
                    interaction.user, interaction.user.id
                )
                return

            try:
                # Link aufsplitten: https://discord.com/channels/<guild>/<channel>/<message>
                parts = link.split("/")
                guild_id = int(parts[4])
                channel_id = int(parts[5])
                msg_id = int(parts[6])

                guild = self.bot.get_guild(guild_id)
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    await interaction.response.send_message(
                        "❌ Kanal nicht gefunden.", ephemeral=True
                    )
                    return

                message = await channel.fetch_message(msg_id)

                # Embed bauen
                embed = discord.Embed(
                    description=message.content or "",
                    color=0x00FF00
                )

                # Zeit lokalisieren (Discord liefert schon UTC-aware datetime)
                created = message.created_at.astimezone(tz.tzlocal())
                time_str = created.strftime("%d.%m.%Y, %H:%M:%S")

                # Erstes Attachment als Bild anzeigen
                if message.attachments:
                    embed.set_image(url=str(message.attachments[0].url))

                # Autor + Footer
                embed.set_author(
                    name=message.author.display_name,
                    icon_url=message.author.display_avatar.url,
                    url=message.jump_url,
                )
                embed.set_footer(
                    text=f"{time_str} | #{message.channel.name} | Quoted by {interaction.user.display_name}"
                )

                await interaction.response.send_message(embed=embed)
                logger.info(
                    "/quote von %s (ID: %s) – Nachricht %s erfolgreich zitiert",
                    interaction.user, interaction.user.id, msg_id
                )

            except Exception as e:
                await interaction.response.send_message(
                    "❌ Konnte den Link nicht verarbeiten 🤷", ephemeral=True
                )
                logger.error(
                    "Fehler bei /quote von %s (ID: %s): %s",
                    interaction.user, interaction.user.id, e
                )

        except Exception as e:
            await interaction.response.send_message("❌ Fehler beim Ausführen 🤷", ephemeral=True)
            logger.error(
                "Unerwarteter Fehler bei /quote von %s (ID: %s): %s",
                interaction.user, interaction.user.id, e
            )


# Standard Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(Quote(bot))
