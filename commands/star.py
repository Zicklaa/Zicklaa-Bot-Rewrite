import logging
import os
import discord
import pytz
from discord.ext import commands
from discord import app_commands
from discord.raw_models import RawReactionActionEvent
from dateutil import tz

# -------------------- Konfiguration & Logger --------------------

globalPfad = os.environ["globalPfad"]
logger = logging.getLogger("ZicklaaBot.Star")

POST_CHANNEL_ID = 981543834129428560  # Mainchannel
# POST_CHANNEL_ID = 567411189336768532  # Testchannel

THRESHOLD = 5  # Mindestanzahl an ⭐ für ein Post
ADMIN_ID = 288413759117066241  # dein User für Sonderrechte
EXT_LIST = [
    "3g2", "3gp", "amv", "asf", "avi", "gifv", "m4p", "m4v",
    "mov", "mp2", "mp4", "mpeg", "mpg", "webm",
]
SAVE_PATH = os.path.join(globalPfad, "LustigeBildchen/")

# -------------------- Cog-Klasse --------------------


class Star(commands.Cog):
    """Cog für das Sternbrett (Starboard)."""

    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.cursor = db.cursor()

    # --- Hilfsmethoden ---

    def parse_raw_reaction_event(self, payload: RawReactionActionEvent):
        """Extrahiert Infos aus Reaction-Events."""
        return payload.message_id, payload.channel_id, payload.emoji, payload.user_id

    async def build_star_embed(self, message: discord.Message) -> discord.Embed:
        """Erstellt das Embed für eine Stern-Nachricht."""
        embed = discord.Embed(
            title="",
            description=message.content,
            color=0xFFEA00
        )

        # Zeit umformatieren
        local_time = message.created_at.astimezone(tz.tzlocal())
        time_str = local_time.strftime("%d.%m.%Y, %H:%M:%S")

        # Attachments speichern / darstellen
        if message.attachments:
            att = message.attachments[0]
            if any(ext in att.url for ext in EXT_LIST):
                embed.add_field(
                    name="Link zum Video:",
                    value=f"[Video]({att.url})",
                    inline=True,
                )
                file_ext = ".mp4"
            else:
                embed.set_image(url=str(att.url))
                file_ext = ".png"

            # Dateien auch lokal speichern
            for i, attachment in enumerate(message.attachments):
                filename = os.path.join(
                    SAVE_PATH, f"STERNBRETT_{message.id}_{i}{file_ext}"
                )
                try:
                    await attachment.save(filename)
                except Exception as e:
                    logger.error(f"Star Fehler beim Speichern: {e}")

        # Restliche Infos
        embed.add_field(
            name="Link zur Nachricht:",
            value=f"[Nachricht]({message.jump_url})",
            inline=True,
        )
        embed.set_author(
            name=message.author.name,
            icon_url=message.author.display_avatar.url,
            url=message.jump_url,
        )
        embed.set_footer(text=f"{time_str} | #{message.channel.name}")

        return embed

    async def post_star(self, message: discord.Message):
        """Postet die Stern-Nachricht ins Sternbrett + DB-Eintrag."""
        embed = await self.build_star_embed(message)
        star_channel = self.bot.get_channel(POST_CHANNEL_ID)
        star_message = await star_channel.send(embed=embed)
        await star_message.add_reaction("⭐")

        # DB speichern
        try:
            sql = "INSERT INTO stars (message_id) VALUES (?)"
            val = (int(message.id),)
            self.cursor.execute(sql, val)
            self.db.commit()
        except Exception as e:
            logger.error(f"Star Error beim DB Pushen: {e}")

        logger.info(
            f"Star gepostet von {message.author} (ID: {message.author.id})")

    # --- Event Listener ---

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        """Listener für ⭐-Reaktionen."""
        message_id, channel_id, emoji, user_id = self.parse_raw_reaction_event(
            payload)

        if str(emoji) == "⭐" and int(channel_id) != POST_CHANNEL_ID:
            try:
                cache_msg = discord.utils.get(
                    self.bot.cached_messages, id=message_id)
                if not cache_msg:
                    return

                reactions = cache_msg.reactions
                star_dict = {
                    reaction.emoji: reaction.count for reaction in reactions}

                # Nur wenn genau unser Threshold erreicht ist
                if star_dict.get("⭐", 0) == THRESHOLD:
                    # DB check: wurde schon gepostet?
                    self.cursor.row_factory = lambda cursor, row: row[0]
                    posted_stars = self.cursor.execute(
                        "SELECT message_id FROM stars"
                    ).fetchall()

                    if message_id not in posted_stars:
                        channel = self.bot.get_channel(channel_id)
                        message = await channel.fetch_message(message_id)
                        await self.post_star(message)

            except Exception as e:
                logger.error(f"Star Event Error: {e}")

    # --- Slash Commands ---

    @app_commands.command(name="star", description="Postet manuell eine Nachricht ins Sternbrett (nur Admin).")
    async def star(self, interaction: discord.Interaction, link: str):
        """Manuelles Posten ins Sternbrett (nur Admin)."""
        try:
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("Das ist VERBOTEN!!", ephemeral=True)
                logger.info(
                    f"/star von Nicht-Admin {interaction.user} (ID: {interaction.user.id}) blockiert")
                return

            if not link:
                await interaction.response.send_message("Du musst einen Link angeben!", ephemeral=True)
                logger.info(
                    f"/star ohne Link von {interaction.user} (ID: {interaction.user.id})")
                return

            # Link parsen
            try:
                link_parts = link.split("/")
                channel_id = int(link_parts[5])
                msg_id = int(link_parts[6])
            except Exception:
                await interaction.response.send_message("Ungültiger Link.", ephemeral=True)
                logger.info(
                    f"/star ungültiger Link von {interaction.user} (ID: {interaction.user.id})")
                return

            channel = self.bot.get_channel(channel_id)
            message = await channel.fetch_message(msg_id)

            # DB check
            self.cursor.row_factory = lambda cursor, row: row[0]
            posted_stars = self.cursor.execute(
                "SELECT message_id FROM stars"
            ).fetchall()

            if msg_id in posted_stars:
                await interaction.response.send_message("Die Nachricht ist schon im Sternbrett.", ephemeral=True)
                logger.info(
                    f"/star bereits gepostet von {interaction.user} (ID: {interaction.user.id})")
                return

            await self.post_star(message)
            await interaction.response.send_message("Star erfolgreich gepostet ✅", ephemeral=True)
            logger.info(
                f"/star erfolgreich von {interaction.user} (ID: {interaction.user.id})")

        except Exception as e:
            await interaction.response.send_message("Fehler beim Posten 🤷", ephemeral=True)
            logger.error(
                f"/star Fehler von {interaction.user} (ID: {interaction.user.id}): {e}")

# -------------------- Cog-Setup --------------------


async def setup(bot):
    """Fügt das Star-Cog dem Bot hinzu."""
    await bot.add_cog(Star(bot, bot.db))
