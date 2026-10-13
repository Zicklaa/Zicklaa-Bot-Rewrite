"""/quote – zitiert eine Nachricht anhand ihres Links als Embed.

Andere Cogs können ``build_quote_embed(message)`` mitbenutzen (z. B. /rezept).
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError
from utils.helpers import fetch_message, format_local, parse_message_link, truncate

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def first_image_url(message: discord.Message) -> str | None:
    """Liefert die URL des ersten Bildes aus Attachments/Embeds, falls vorhanden."""
    for a in message.attachments:
        # content_type ist nicht immer gesetzt -> Dateiendung als Fallback
        if (a.content_type or "").startswith("image/") or a.filename.lower().endswith(IMAGE_EXTENSIONS):
            return a.url
    # Embeds (z. B. Link-Previews)
    for e in message.embeds:
        url = (e.image and e.image.url) or (e.thumbnail and e.thumbnail.url)
        if url:
            return url
    return None


class Quote(BaseCog):
    """Cog: /quote."""

    # -------------------- Öffentliche Helper-API --------------------

    def build_quote_embed(self, message: discord.Message) -> discord.Embed:
        """Baut ein Zitat-Embed mit Text, klickbarem Autor, erstem Bild und Footer."""
        # Beschreibung beschneiden, damit wir sicher unter dem Embed-Limit bleiben
        content = truncate(message.content, 3500)
        if not content and not message.attachments and not message.embeds:
            content = "*— kein Text —*"

        embed = discord.Embed(
            description=content,
            color=discord.Color.green(),
            timestamp=message.created_at,
        )
        # Autorzeile -> klickbar auf die Originalnachricht
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
            url=message.jump_url,
        )
        image = first_image_url(message)
        if image:
            embed.set_image(url=image)

        is_text_channel = isinstance(message.channel, discord.TextChannel)
        where = f"#{message.channel.name}" if is_text_channel else str(message.channel)
        embed.set_footer(text=f"{format_local(message.created_at)} • {where}")
        return embed

    async def build_quote_embed_from_link(self, link: str) -> discord.Embed:
        """Lädt die verlinkte Nachricht und baut daraus das Zitat-Embed.

        Raises:
            ValueError bei ungültigem Link, discord.HTTPException bei Zugriffsproblemen.
        """
        _, channel_id, message_id = parse_message_link(link)
        return self.build_quote_embed(await fetch_message(self.bot, channel_id, message_id))

    # -------------------- Slash-Command --------------------

    @app_commands.command(
        name="quote",
        description="Zitiert eine Nachricht anhand ihres Links.",
        extras={"error": "❌ Fehler beim Ausführen 🤷"},
    )
    @app_commands.describe(link="Nachrichtenlink (Rechtsklick auf eine Nachricht → Link kopieren)")
    async def quote(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer(thinking=True)
        try:
            embed = await self.build_quote_embed_from_link(link)
        except (ValueError, discord.HTTPException) as e:
            # Kein Nachrichtenlink bzw. Nachricht gelöscht / kein Zugriff
            raise UserError("❌ Konnte den Link nicht verarbeiten 🤷") from e

        await interaction.followup.send(embed=embed)
        self.log("Quote sent", interaction, link=link)


async def setup(bot: commands.Bot):
    await bot.add_cog(Quote(bot))
