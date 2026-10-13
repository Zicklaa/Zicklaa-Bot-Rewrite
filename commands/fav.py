"""Favoriten: Nachrichten per Reaktion speichern und später wieder abrufen.

- 🦶 auf eine Nachricht: Bot fragt per DM nach einem Namen und speichert den Fav
- 🗑️ auf einen geposteten Fav: löscht ihn (nur der Besitzer)
- /fav [name], /rfav, /allfavs (auch als Prefix-Commands: +fav, +rfav, +allfavs)
"""

import asyncio
import logging
from io import BytesIO

import discord
from discord.ext import commands

from utils.base import BaseCog
from utils.helpers import fetch_message, format_local
from utils.settings import OWNER_ID

SAVE_EMOJI = "🦶"
DELETE_EMOJI = "🗑️"
MAX_NAME_LEN = 250
NAME_TIMEOUT = 3600  # Sekunden, die der Bot auf den Fav-Namen wartet

# Der alte Bot („Der Gelbfus Cowboy“) darf keine Favs löschen
IGNORED_DELETE_USER_ID = 571051961256902671


class Fav(BaseCog):
    """Cog: Favoriten."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.db = bot.db

    # -------------------- Hilfsmethoden --------------------

    @staticmethod
    def _footer(fav: tuple, message: discord.Message, owner: str) -> str:
        """Fußzeile eines Favs; die ID steht vorne, damit 🗑️ sie wiederfindet."""
        return f"{fav[0]} | {format_local(message.created_at)} | #{message.channel.name} | by: {owner} | Name: {fav[3]}"

    def _build_embed(self, message: discord.Message, footer: str) -> discord.Embed:
        embed = discord.Embed(
            description=message.content or "Kein Text in der Originalnachricht!",
            color=0x00FF00,
        )
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        embed.set_author(
            name=message.author.name,
            icon_url=message.author.display_avatar.url,
            url=message.jump_url,
        )
        embed.set_footer(text=footer)
        return embed

    async def _not_found(self, ctx: commands.Context):
        """Kein Fav gefunden: als Slash-Command per Text, sonst per Reaktion."""
        if ctx.interaction:
            await ctx.send("⛔🔍 Nix gefunden.", ephemeral=True)
        else:
            await ctx.message.add_reaction("⛔")
            await ctx.message.add_reaction("🔍")

    # -------------------- Reaktionen --------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        emoji = str(payload.emoji)
        try:
            if emoji == DELETE_EMOJI:
                await self._delete_fav(payload)
            elif emoji == SAVE_EMOJI:
                await self._save_fav(payload)
        except Exception as e:
            self.log("Fav reaction failed", user_id=payload.user_id, emoji=emoji, message_id=payload.message_id, error=e)

    async def _delete_fav(self, payload: discord.RawReactionActionEvent):
        """🗑️ auf einem Fav-Embed: löscht den Fav, wenn er dem Reagierenden gehört."""
        if payload.user_id == IGNORED_DELETE_USER_ID:
            return
        message = await fetch_message(self.bot, payload.channel_id, payload.message_id)
        if not message.embeds or not message.embeds[0].footer.text:
            return

        # Die Fav-ID ist das erste Wort der Fußzeile
        fav_id = message.embeds[0].footer.text.split()[0]
        if not fav_id.isdigit():
            return
        deleted = self.db.execute(
            "DELETE FROM favs WHERE id=? AND user_id=?", (fav_id, payload.user_id)
        ).rowcount
        self.db.commit()
        if deleted:
            self.log("Fav deleted", user_id=payload.user_id, fav_id=fav_id, message_id=payload.message_id)

    async def _save_fav(self, payload: discord.RawReactionActionEvent):
        """🦶 auf einer Nachricht: fragt per DM nach dem Namen und speichert den Fav."""
        user = self.bot.get_user(payload.user_id) or await self.bot.fetch_user(payload.user_id)
        dm_channel = await user.create_dm()
        await dm_channel.send("Antworte bitte mit dem gewünschten Namen für den Fav.")
        self.log("DM sent for fav name", user)

        try:
            response = await self.bot.wait_for(
                "message",
                check=lambda m: m.channel == dm_channel and not m.author.bot,
                timeout=NAME_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return

        name = response.content
        if len(name) >= MAX_NAME_LEN:
            await response.reply(f"Zu lang. Bidde unter {MAX_NAME_LEN}chars")
            self.log("Fav name too long", user, level=logging.WARNING, fav_name=name)
            return

        self.db.execute(
            "INSERT INTO favs (user_id, message_id, name, channel_id) VALUES (?, ?, ?, ?)",
            (payload.user_id, payload.message_id, name, payload.channel_id),
        )
        self.db.commit()
        await response.add_reaction("👍")
        self.log("Fav created", user, fav_name=name, message_id=payload.message_id)

    # -------------------- Commands --------------------

    @commands.hybrid_command(description="Hole dir einen gespeicherten Fav.")
    async def fav(self, ctx: commands.Context, *, name: str = None):
        """Eigener Fav: zufällig oder per Namens-Suche."""
        if name:
            query, params = "user_id=? AND name LIKE ?", (ctx.author.id, f"%{name}%")
        else:
            query, params = "user_id=?", (ctx.author.id,)
        fav = self.db.execute(f"SELECT * FROM favs WHERE {query} ORDER BY RANDOM()", params).fetchone()
        if not fav:
            return await self._not_found(ctx)

        await ctx.defer()  # Nachricht laden kann länger als 3 s dauern
        message = await fetch_message(self.bot, fav[4], fav[2])
        await ctx.send(embed=self._build_embed(message, self._footer(fav, message, ctx.author.name)))
        self.log("Fav posted", ctx, fav_id=fav[0], channel_id=fav[4])

    @commands.hybrid_command(description="Zeige einen zufälligen Fav von allen Usern.")
    async def rfav(self, ctx: commands.Context):
        """Zufälliger Fav irgendeines Users."""
        fav = self.db.execute("SELECT * FROM favs ORDER BY RANDOM()").fetchone()
        if not fav:
            return await self._not_found(ctx)

        await ctx.defer()
        try:
            message = await fetch_message(self.bot, fav[4], fav[2])
        except discord.HTTPException as e:
            self.log("Random fav failed", ctx, fav_id=fav[0], error=e)
            return await ctx.reply(
                f"Klappt nit lol 🤷 Eventuell existiert der originale Kommentar nichtmehr. ID: {fav[0]} <@{OWNER_ID}>"
            )

        footer = f"{format_local(message.created_at)} | #{message.channel.name} | Randomized by: {ctx.author.name}"
        await ctx.send(embed=self._build_embed(message, footer))
        self.log("Random fav posted", ctx, fav_id=fav[0], channel_id=fav[4])

    @commands.hybrid_command(description="Exportiere alle deine Favs als Textdatei.")
    async def allfavs(self, ctx: commands.Context):
        """Schickt alle eigenen Favs als Textdatei per DM."""
        favs = self.db.execute("SELECT * FROM favs WHERE user_id=?", (ctx.author.id,)).fetchall()
        if not favs:
            return await self._not_found(ctx)

        # Slash: ephemer bestätigen; Prefix: den Aufruf aus dem Channel entfernen
        if ctx.interaction:
            await ctx.send("📬 Ich schick dir deine Favs per DM.", ephemeral=True)
        else:
            await ctx.message.delete()

        dm_channel = await ctx.author.create_dm()
        await dm_channel.send("Moin 👋 Ich sammele alle deine Favs für dich...")
        self.log("DM sent for allfavs", ctx)

        entries = []
        for fav in favs:
            try:
                message = await fetch_message(self.bot, fav[4], fav[2])
            except Exception as e:
                self.log("Allfavs fetch failed", ctx, fav_id=fav[0], error=e)
                continue
            # Pro Fav: Autor, Text, Anhang-Link (jeweils falls vorhanden), Fußzeile
            lines = [
                message.author.name,
                message.content,
                message.attachments[0].url if message.attachments else "",
                self._footer(fav, message, ctx.author.name),
            ]
            entries.append("\n".join(line for line in lines if line))

        export = BytesIO(("\n\n".join(entries) + "\n\n").encode("utf-8"))
        await dm_channel.send(file=discord.File(export, f"{ctx.author.id}.txt"))
        self.log("Allfavs DM sent", ctx, favs=len(entries))


async def setup(bot: commands.Bot):
    await bot.add_cog(Fav(bot))
