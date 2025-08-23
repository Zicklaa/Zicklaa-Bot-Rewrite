import logging
import os
import discord
import pytz
from discord.ext import commands
from discord import app_commands
from discord.raw_models import RawReactionActionEvent
from dateutil import tz
from utils.logging_helper import log_event

# -------------------- Konfiguration & Logger --------------------

globalPfad = os.environ["globalPfad"]
logger = logging.getLogger("ZicklaaBotRewrite.Star")

POST_CHANNEL_ID = 981543834129428560  # Mainchannel
# POST_CHANNEL_ID = 567411189336768532  # Testchannel

THRESHOLD = 5  # Mindestanzahl an ⭐ für ein Post
ADMIN_ID = 288413759117066241  # dein User für Sonderrechte

# Erlaubte Dateiendungen für das Sternbrett (Bilder, Videos, Audio)
EXT_LIST = [
    # Bilder
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "heic", "svg",
    # Videos
    "mp4", "mov", "avi", "mkv", "flv", "wmv", "webm", "mpeg", "mpg",
    "3gp", "3g2", "m4v", "ogv", "asf", "amv",
    # Audio
    "mp3", "wav", "ogg", "flac", "aac", "m4a", "wma", "opus", "mid", "midi",
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

            # Dateiendung extrahieren
            _, ext = os.path.splitext(att.filename)
            ext = ext.lower().lstrip(".")

            if ext in EXT_LIST:
                # Video → nur Link
                if ext in ["mp4", "mov", "avi", "mkv", "flv", "wmv", "webm",
                           "mpeg", "mpg", "3gp", "3g2", "m4v", "ogv", "asf", "amv"]:
                    embed.add_field(
                        name="Link zum Video:",
                        value=f"[Video]({att.url})",
                        inline=True,
                    )
                # Audio → nur Link
                elif ext in ["mp3", "wav", "ogg", "flac", "aac", "m4a", "wma", "opus", "mid", "midi"]:
                    embed.add_field(
                        name="Link zur Audiodatei:",
                        value=f"[Audio]({att.url})",
                        inline=True,
                    )
                # Bild → einbetten
                else:
                    embed.set_image(url=str(att.url))

            # Dateien lokal speichern (mit Spoiler-Handling)
            for i, attachment in enumerate(message.attachments):
                _, orig_ext = os.path.splitext(attachment.filename)

                # Spoiler-Handling
                filename_base = f"STERNBRETT_{message.id}_{i}{orig_ext.lower()}"
                if attachment.is_spoiler():
                    filename_base = f"SPOILER_{filename_base}"

                filename = os.path.join(SAVE_PATH, filename_base)

                try:
                    await attachment.save(filename)
                except Exception as e:
                    log_event(
                        logger,
                        logging.ERROR,
                        self.__class__.__name__,
                        "attachment_save_failed",
                        message.author,
                        message.author.id,
                        file=attachment.filename,
                        error=e,
                        exc_info=True,
                    )

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
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "db_insert_star_failed",
                message.author,
                message.author.id,
                message_id=message.id,
                error=e,
                exc_info=True,
            )

        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "star_posted",
            message.author,
            message.author.id,
            message_id=message.id,
        )

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
                    reaction.emoji: reaction.count for reaction in reactions
                }

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
                log_event(
                    logger,
                    logging.ERROR,
                    self.__class__.__name__,
                    "reaction_event_failed",
                    user=None,
                    user_id=user_id,
                    message_id=message_id,
                    error=e,
                    exc_info=True,
                )

    # --- Slash Commands ---

    @app_commands.command(
        name="star",
        description="Postet manuell eine Nachricht ins Sternbrett (nur Admin)."
    )
    async def star(self, interaction: discord.Interaction, link: str):
        """Manuelles Posten ins Sternbrett (nur Admin)."""
        try:
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("Das ist VERBOTEN!!", ephemeral=True)
                log_event(
                    logger,
                    logging.WARNING,
                    self.__class__.__name__,
                    "star_denied_non_admin",
                    interaction.user,
                    interaction.user.id,
                    link=link,
                )
                return
            if not link:
                await interaction.response.send_message("Du musst einen Link angeben!", ephemeral=True)
                log_event(
                    logger,
                    logging.WARNING,
                    self.__class__.__name__,
                    "star_missing_link",
                    interaction.user,
                    interaction.user.id,
                )
                return
            # Link parsen
            try:
                link_parts = link.split("/")
                channel_id = int(link_parts[5])
                msg_id = int(link_parts[6])
            except Exception:
                await interaction.response.send_message("Ungültiger Link.", ephemeral=True)
                log_event(
                    logger,
                    logging.WARNING,
                    self.__class__.__name__,
                    "star_invalid_link",
                    interaction.user,
                    interaction.user.id,
                    link=link,
                )
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
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "star_already_posted",
                    interaction.user,
                    interaction.user.id,
                    message_id=msg_id,
                )
                return
            await self.post_star(message)
            await interaction.response.send_message("Star erfolgreich gepostet ✅", ephemeral=True)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "star_command_success",
                interaction.user,
                interaction.user.id,
                message_id=msg_id,
            )
        except Exception as e:
            await interaction.response.send_message("Fehler beim Posten 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "star_command_failed",
                interaction.user,
                interaction.user.id,
                link=link,
                error=e,
                exc_info=True,
            )

# -------------------- Cog-Setup --------------------


async def setup(bot):
    """Fügt das Star-Cog dem Bot hinzu."""
    await bot.add_cog(Star(bot, bot.db))
