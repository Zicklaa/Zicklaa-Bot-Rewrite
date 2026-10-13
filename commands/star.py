"""Sternbrett (Starboard): Nachrichten mit genug ⭐ landen im Sternbrett-Channel.

- ⭐-Reaktionen: ab THRESHOLD Sternen wird die Nachricht automatisch gepostet
- /star <link>: manuelles Posten (nur Bot-Owner)
- Anhänge werden zusätzlich in LustigeBildchen/ gespeichert (Futter für /ltb)
"""

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError, owner_only
from utils.helpers import fetch_message, format_local, parse_message_link
from utils.settings import BILDCHEN_DIR

# -------------------- Konfiguration --------------------

POST_CHANNEL_ID = 981543834129428560  # Mainchannel
# POST_CHANNEL_ID = 567411189336768532  # Testchannel

THRESHOLD = 5  # Mindestanzahl an ⭐ für einen Post

# Videos und Audio werden nur verlinkt, Bilder direkt eingebettet
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "heic", "svg"}
VIDEO_EXTENSIONS = {
    "mp4", "mov", "avi", "mkv", "flv", "wmv", "webm", "mpeg", "mpg",
    "3gp", "3g2", "m4v", "ogv", "asf", "amv",
}
AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "flac", "aac", "m4a", "wma", "opus", "mid", "midi"}


class Star(BaseCog):
    """Cog: Sternbrett."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.db = bot.db

    # -------------------- Hilfsmethoden --------------------

    def is_posted(self, message_id: int) -> bool:
        """Steht die Nachricht schon im Sternbrett?"""
        row = self.db.execute("SELECT 1 FROM stars WHERE message_id=?", (message_id,)).fetchone()
        return row is not None

    def build_star_embed(self, message: discord.Message) -> discord.Embed:
        """Erstellt das Embed für eine Stern-Nachricht."""
        embed = discord.Embed(description=message.content, color=0xFFEA00)

        # Erster Anhang: Bild einbetten, Video/Audio nur verlinken
        if message.attachments:
            att = message.attachments[0]
            ext = Path(att.filename).suffix.lower().lstrip(".")
            if ext in VIDEO_EXTENSIONS:
                embed.add_field(name="Link zum Video:", value=f"[Video]({att.url})", inline=True)
            elif ext in AUDIO_EXTENSIONS:
                embed.add_field(name="Link zur Audiodatei:", value=f"[Audio]({att.url})", inline=True)
            elif ext in IMAGE_EXTENSIONS:
                embed.set_image(url=att.url)

        embed.add_field(name="Link zur Nachricht:", value=f"[Nachricht]({message.jump_url})", inline=True)
        embed.set_author(
            name=message.author.name,
            icon_url=message.author.display_avatar.url,
            url=message.jump_url,
        )
        embed.set_footer(text=f"{format_local(message.created_at)} | #{message.channel.name}")
        return embed

    async def save_attachments(self, message: discord.Message):
        """Speichert alle Anhänge lokal in LustigeBildchen/ (Spoiler bleiben Spoiler)."""
        for i, attachment in enumerate(message.attachments):
            ext = Path(attachment.filename).suffix.lower()
            prefix = "SPOILER_" if attachment.is_spoiler() else ""
            try:
                await attachment.save(BILDCHEN_DIR / f"{prefix}STERNBRETT_{message.id}_{i}{ext}")
            except Exception as e:
                self.log("attachment_save_failed", message.author, file=attachment.filename, error=e)

    async def post_star(self, message: discord.Message):
        """Postet die Nachricht ins Sternbrett und merkt sie sich in der DB."""
        embed = self.build_star_embed(message)
        await self.save_attachments(message)

        star_message = await self.bot.get_channel(POST_CHANNEL_ID).send(embed=embed)
        await star_message.add_reaction("⭐")

        self.db.execute("INSERT INTO stars (message_id) VALUES (?)", (message.id,))
        self.db.commit()
        self.log("star_posted", message.author, message_id=message.id)

    # -------------------- Event Listener --------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Postet eine Nachricht, sobald sie genau THRESHOLD ⭐ erreicht."""
        if str(payload.emoji) != "⭐" or payload.channel_id == POST_CHANNEL_ID:
            return

        try:
            # Nur Nachrichten aus dem Cache -> uralte Nachrichten landen nicht im Sternbrett
            message = discord.utils.get(self.bot.cached_messages, id=payload.message_id)
            if not message:
                return

            stars = next((r.count for r in message.reactions if str(r.emoji) == "⭐"), 0)
            if stars == THRESHOLD and not self.is_posted(message.id):
                await self.post_star(message)
        except Exception as e:
            self.log("reaction_event_failed", message_id=payload.message_id, user_id=payload.user_id, error=e)

    # -------------------- Slash-Command --------------------

    @app_commands.command(
        name="star",
        description="Postet manuell eine Nachricht ins Sternbrett (nur Admin).",
        extras={"error": "Fehler beim Posten 🤷"},
    )
    @owner_only("Das ist VERBOTEN!!")
    async def star(self, interaction: discord.Interaction, link: str):
        try:
            _, channel_id, message_id = parse_message_link(link)
        except ValueError:
            raise UserError("Ungültiger Link.")
        if self.is_posted(message_id):
            raise UserError("Die Nachricht ist schon im Sternbrett.")

        # Anhänge speichern kann dauern -> erst deferren
        await interaction.response.defer(ephemeral=True)
        await self.post_star(await fetch_message(self.bot, channel_id, message_id))
        await interaction.followup.send("Star erfolgreich gepostet ✅", ephemeral=True)
        self.log("star_command_success", interaction, message_id=message_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Star(bot))
