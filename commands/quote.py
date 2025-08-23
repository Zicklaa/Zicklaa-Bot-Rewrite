# quote_cog.py
# -*- coding: utf-8 -*-
"""
Quote-Cog (discord.py 2.x)
- /quote <link> : erstellt ein Zitat-Embed aus einem Nachrichtenlink
- Öffentliche Helper-Methode für andere Cogs:
    await cog.build_quote_embed_from_link(link) -> discord.Embed
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from dateutil import tz

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Quote")


def _first_image_url(message: discord.Message) -> Optional[str]:
    """Liefert die URL des ersten Bildes aus Attachments/Embeds, falls vorhanden."""
    # Attachments
    for a in message.attachments:
        # content_type ist nicht immer gesetzt → Dateiendungen als Fallback
        if (a.content_type and a.content_type.startswith("image/")) or a.filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ):
            return a.url
    # Embeds (z. B. Link-Previews)
    for e in message.embeds:
        if e.image and e.image.url:
            return e.image.url
        if e.thumbnail and e.thumbnail.url:
            return e.thumbnail.url
    return None


class Quote(commands.Cog):
    """Cog für den Befehl /quote – zitiert eine Nachricht als Embed."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------- Öffentliche Helper-API --------------------

    async def build_quote_embed_from_link(self, link: str) -> discord.Embed:
        """
        Baut aus einem Nachrichtenlink ein hübsches Quote-Embed.
        - parst Link,
        - lädt die Nachricht,
        - baut ein Embed mit Text, Autor (klickbar), Bild & Footer.
        Raises:
            ValueError / RuntimeError bei fehlerhaften Links oder Zugriffsproblemen.
        """
        guild_id, channel_id, msg_id = self._parse_message_link(link)
        channel = self._resolve_channel(guild_id, channel_id)
        if channel is None:
            # Notfalls hart fetchen (falls nicht im Cache / andere Guild)
            # kann Forbidden werfen
            channel = await self.bot.fetch_channel(channel_id)
        assert isinstance(channel, (discord.TextChannel, discord.Thread)
                          ), "Nur Textkanäle/Threads werden unterstützt."

        # kann NotFound/Forbidden werfen
        message = await channel.fetch_message(msg_id)

        # Beschreibung beschneiden, damit wir nie über 4096 kommen
        content = (message.content or "").strip()
        MAX_DESC = 3500
        if len(content) > MAX_DESC:
            content = content[: MAX_DESC - 1].rstrip() + "…"
        if not content and not message.attachments and not message.embeds:
            content = "*— kein Text —*"

        embed = discord.Embed(
            title="",
            description=content,
            color=discord.Color.green(),
            timestamp=message.created_at,  # zeigt Zeit rechts unten
        )

        # Autorzeile → klickbar auf Originalnachricht
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
            url=message.jump_url,
        )

        # Erstes Bild anheften
        img = _first_image_url(message)
        if img:
            embed.set_image(url=img)

        # Footer (Kanal + Uhrzeit lokal formatiert)
        created_local = message.created_at.astimezone(tz.tzlocal())
        time_str = created_local.strftime("%d.%m.%Y, %H:%M:%S")
        where = (
            f"#{message.channel.name}"
            if isinstance(message.channel, discord.TextChannel)
            else str(message.channel)
        )
        embed.set_footer(text=f"{time_str} • {where}")

        return embed

    # -------------------- Slash-Command --------------------

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
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "Missing link",
                    interaction.user,
                    interaction.user.id,
                    command="/quote",
                )
                return

            await interaction.response.defer(thinking=True)

            try:
                embed = await self.build_quote_embed_from_link(link)
                await interaction.followup.send(embed=embed)
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "Quote sent",
                    interaction.user,
                    interaction.user.id,
                    command="/quote",
                    link=link,
                )
            except Exception as e:
                # Fehler beim Verarbeiten des Links / Fetch
                await interaction.followup.send(
                    "❌ Konnte den Link nicht verarbeiten 🤷",
                    ephemeral=True,
                )
                log_event(
                    logger,
                    logging.ERROR,
                    self.__class__.__name__,
                    "Processing error",
                    interaction.user,
                    interaction.user.id,
                    command="/quote",
                    link=link,
                    error=e,
                    exc_info=True,
                )

        except Exception as e:
            # Falls aus irgendeinem Grund noch keine Antwort raus ist:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Fehler beim Ausführen 🤷", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Fehler beim Ausführen 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Unexpected failure",
                interaction.user,
                interaction.user.id,
                command="/quote",
                link=link,
                error=e,
                exc_info=True,
            )

    # -------------------- interne Helfer --------------------

    def _parse_message_link(self, link: str) -> tuple[int, int, int]:
        """
        Erwartet Links wie:
          - https://discord.com/channels/<guild_id>/<channel_id>/<message_id>
          - https://ptb.discord.com/channels/...
          - https://canary.discord.com/channels/...
        """
        try:
            p = urlparse(link)
            if not p.netloc.endswith("discord.com"):
                # viele Clients nutzen auch ptb/canary Subdomains → zulassen
                if not (p.netloc.endswith("ptb.discord.com") or p.netloc.endswith("canary.discord.com")):
                    raise ValueError("Kein Discord-Link.")

            parts = [x for x in p.path.split("/") if x]
            # erwartet: ["channels", guild, channel, message]
            if len(parts) < 4 or parts[0] != "channels":
                raise ValueError("Ungültiges Linkformat.")

            guild_id = int(parts[1])
            channel_id = int(parts[2])
            message_id = int(parts[3])
            return guild_id, channel_id, message_id
        except Exception as e:
            raise ValueError(f"Ungültiger Nachrichtenlink: {link}") from e

    def _resolve_channel(self, guild_id: int, channel_id: int) -> Optional[discord.abc.GuildChannel]:
        """Versucht Channel aus dem Cache zu holen (schnell & rate-limit-schonend)."""
        guild = self.bot.get_guild(guild_id)
        if guild:
            ch = guild.get_channel(channel_id)
            if ch:
                return ch
        # kein Treffer → None (der Aufrufer kann fetch_channel probieren)
        return None


# -------------------- Setup --------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Quote(bot))
