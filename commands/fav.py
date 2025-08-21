import logging
from collections.abc import Sequence
import os

import discord
import pytz
from dateutil import tz
from discord.ext import commands
from discord.raw_models import RawReactionActionEvent

logger = logging.getLogger("ZicklaaBotRewrite.Fav")


class Fav(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.cursor = db.cursor()

    # ------------------------------------------------------
    # Reaction Event Listener
    # ------------------------------------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        message_id, channel_id, emoji, user_id = self.parse_raw_reaction_event(payload)

        # 🗑️ = Delete Fav
        if str(emoji) == "🗑️":
            try:
                if user_id != 571051961256902671:
                    channel = self.bot.get_channel(channel_id)
                    msg = await channel.fetch_message(message_id)
                    if msg.embeds:
                        embedFromMessage = msg.embeds[0]
                        footer = embedFromMessage.footer.text

                        split_footer = footer.split()
                        fav_id = split_footer[0]
                        fav = self.cursor.execute(
                            "SELECT * FROM favs WHERE id=?", (fav_id,)
                        ).fetchone()
                        if fav and fav[1] == user_id:
                            self.cursor.execute("DELETE FROM favs WHERE id=?", (fav_id,))
                            self.db.commit()
                            logger.info(f"Fav gelöscht: {fav_id}")
            except Exception as e:
                logger.error(f"Fav Delete ERROR: {e}")

        # 🦶 = Save Fav
        if str(emoji) == "🦶":
            try:
                user = await self.bot.fetch_user(payload.user_id)
                dm_channel = await user.create_dm()
                await dm_channel.send("Antworte bitte mit dem gewünschten Namen für den Fav.")
                logger.info(f"DM gesendet an {user.name} (ID: {user.id})")

                response = await self.bot.wait_for("message", check=message_check(channel=dm_channel))
                name = response.content
                if len(name) < 250:
                    sql = "INSERT INTO favs (user_id, message_id, name, channel_id) VALUES (?, ?, ?, ?)"
                    val = (user_id, message_id, name, channel_id)
                    self.cursor.execute(sql, val)
                    self.db.commit()
                    await response.add_reaction("👍")
                    logger.info(f"Neuer Fav angelegt für: {response.author.name} (ID: {response.author.id})")
                else:
                    await response.reply("Zu lang. Bidde unter 250chars")
                    logger.info(f"Fav-Name zu lang von {response.author.name} (ID: {response.author.id})")
            except Exception as e:
                logger.error(f"Lustiges Bilchen ERROR von {user_id}: {e}")

    # ------------------------------------------------------
    # /fav -> eigenen Fav abrufen
    # ------------------------------------------------------
    @commands.hybrid_command(description="Hole dir einen gespeicherten Fav.")
    async def fav(self, ctx, *, name: str = None):
        try:
            if name:
                name = f"%{name}%"
                fav = self.cursor.execute(
                    "SELECT * FROM favs WHERE user_id=? AND name LIKE ? ORDER BY RANDOM()",
                    (ctx.author.id, name),
                ).fetchone()
            else:
                fav = self.cursor.execute(
                    "SELECT * FROM favs WHERE user_id=? ORDER BY RANDOM()",
                    (ctx.author.id,),
                ).fetchone()

            if fav:
                try:
                    channel = self.bot.get_channel(fav[4])
                    fav_message = await channel.fetch_message(fav[2])

                    current_time = fav_message.created_at.astimezone(tz.tzlocal()).strftime("%d.%m.%Y, %H:%M:%S")

                    content = fav_message.content
                    if not content:
                        content = "Kein Text in der Originalnachricht!"

                    embed = discord.Embed(
                        title="",
                        description=content,
                        color=0x00FF00
)
                    if fav_message.attachments:
                        embed.set_image(url=str(fav_message.attachments[0].url))

                    embed.set_author(
                        name=fav_message.author.name,
                        icon_url=fav_message.author.display_avatar.url,
                        url=fav_message.jump_url,
                    )
                    embed.set_footer(
                        text=f"{fav[0]} | {current_time} | #{fav_message.channel.name} | by: {ctx.author.name} | Name: {fav[3]}"
                    )
                    await ctx.send(embed=embed)
                    logger.info(f"Fav gepostet für {ctx.author.name} (ID: {ctx.author.id})")
                except Exception as e:
                    await ctx.reply("Klappt nit lol 🤷")
                    logger.error(f"Fav ERROR von {ctx.author.name}: {e}")
            else:
                await ctx.message.add_reaction("⛔")
                await ctx.message.add_reaction("🔍")
        except Exception as e:
            await ctx.reply("Klappt nit lol 🤷")
            logger.error(f"Fav ERROR von {ctx.author.name}: {e}")

    # ------------------------------------------------------
    # /rfav -> Random Fav von allen Usern
    # ------------------------------------------------------
    @commands.hybrid_command(description="Zeige einen zufälligen Fav von allen Usern.")
    async def rfav(self, ctx):
        try:
            fav = self.cursor.execute("SELECT * FROM favs ORDER BY RANDOM()").fetchone()
            if fav:
                try:
                    channel = self.bot.get_channel(fav[4])
                    fav_message = await channel.fetch_message(fav[2])

                    current_time = fav_message.created_at.astimezone(tz.tzlocal()).strftime("%d.%m.%Y, %H:%M:%S")

                    embed = discord.Embed(
                        title="", description=fav_message.content, color=0x00FF00
                    )
                    if fav_message.attachments:
                        embed.set_image(url=str(fav_message.attachments[0].url))

                    embed.set_author(
                        name=fav_message.author.name,
                        icon_url=fav_message.author.display_avatar.url,
                        url=fav_message.jump_url,
                    )
                    embed.set_footer(
                        text=f"{current_time} | #{fav_message.channel.name} | Randomized by: {ctx.author.name}"
                    )
                    await ctx.send(embed=embed)
                    logger.info(f"Random Fav gepostet für {ctx.author.name} (ID: {ctx.author.id})")
                except Exception as e:
                    await ctx.reply(
                        f"Klappt nit lol 🤷 Eventuell existiert der originale Kommentar nichtmehr. ID: {fav[0]} <@288413759117066241>"
                    )
                    logger.error(f"Fav ERROR von {ctx.author.name}: {e}")
        except Exception as e:
            await ctx.reply("Klappt nit lol 🤷")
            logger.error(f"Fav ERROR von {ctx.author.name}: {e}")

    # ------------------------------------------------------
    # /allfavs -> Export als TXT per DM
    # ------------------------------------------------------
    @commands.hybrid_command(description="Exportiere alle deine Favs als Textdatei.")
    async def allfavs(self, ctx):
        try:
            all_favs = self.cursor.execute(
                "SELECT * FROM favs WHERE user_id=?", (ctx.author.id,)
            )
            if all_favs:
                dm_channel = await ctx.author.create_dm()
                await ctx.message.delete()
                await dm_channel.send("Moin 👋 Ich sammele alle deine Favs für dich...")
                logger.info(f"DM gesendet an {ctx.author.name} (ID: {ctx.author.id}) für allfavs")

                path = f"allfavs/{ctx.author.id}.txt"

                try:
                    os.remove(path)
                except OSError:
                    pass

                whole_message = ""
                for fav in all_favs:
                    try:
                        channel = self.bot.get_channel(fav[4])
                        fav_message = await channel.fetch_message(fav[2])

                        current_time = fav_message.created_at.astimezone(tz.tzlocal()).strftime("%d.%m.%Y, %H:%M:%S")
                        author = fav_message.author.name
                        text = fav_message.content
                        bottom_text = (
                            f"{fav[0]} | {current_time} | #{fav_message.channel.name} | by: {ctx.author.name} | Name: {fav[3]}"
                        )

                        if fav_message.content:
                            if fav_message.attachments:
                                url = str(fav_message.attachments[0].url)
                                message = f"{author}\n{text}\n{url}\n{bottom_text}\n\n"
                            else:
                                message = f"{author}\n{text}\n{bottom_text}\n\n"
                        else:
                            if fav_message.attachments:
                                url = str(fav_message.attachments[0].url)
                                message = f"{author}\n{url}\n{bottom_text}\n\n"
                            else:
                                message = f"{author}\n{bottom_text}\n\n"

                        whole_message += message
                    except Exception as e:
                        logger.error(f"Allfavs ERROR von {ctx.author.name}: {e}")

                with open(path, "w", encoding="utf-8") as f:
                    f.write(whole_message)

                await dm_channel.send(file=discord.File(path))
                logger.info(f"DM mit Allfavs-Export gesendet an {ctx.author.name} (ID: {ctx.author.id})")
            else:
                await ctx.message.add_reaction("⛔")
                await ctx.message.add_reaction("🔍")
        except Exception as e:
            await ctx.reply("Klappt nit lol 🤷")
            logger.error(f"Allfav ERROR von {ctx.author.name}: {e}")

    # ------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------
    def parse_raw_reaction_event(self, payload: RawReactionActionEvent):
        return payload.message_id, payload.channel_id, payload.emoji, payload.user_id


async def setup(bot):
    await bot.add_cog(Fav(bot, bot.db))


def make_sequence(seq):
    if seq is None:
        return ()
    if isinstance(seq, Sequence) and not isinstance(seq, str):
        return seq
    else:
        return (seq,)


def message_check(channel=None, author=None, content=None, ignore_bot=True, lower=True):
    channel = make_sequence(channel)
    author = make_sequence(author)
    content = make_sequence(content)
    if lower:
        content = tuple(c.lower() for c in content)

    def check(message):
        if ignore_bot and message.author.bot:
            return False
        if channel and message.channel not in channel:
            return False
        if author and message.author not in author:
            return False
        actual_content = message.content.lower() if lower else message.content
        if content and actual_content not in content:
            return False
        return True

    return check
