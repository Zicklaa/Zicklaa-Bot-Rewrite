# commands/wichtelDM.py
# discord.py 2.7.x

from __future__ import annotations
import os
from typing import List
import discord
from discord.ext import commands

TARGET_CHANNEL_ID = 1320467815177916527


def _split_chunks(text: str, limit: int = 2000) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    cur, cur_len = [], 0
    for para in text.split("\n"):
        add = (("\n" if cur else "") + para)
        if cur_len + len(add) <= limit:
            cur.append(para)
            cur_len += len(add)
        else:
            if cur:
                parts.append("\n".join(cur))
                cur, cur_len = [], 0
            while len(para) > limit:
                parts.append(para[:limit])
                para = para[limit:]
            if para:
                cur = [para]
                cur_len = len(para)
    if cur:
        parts.append("\n".join(cur))
    return parts


class WichtelDM(commands.Cog):
    """DM-only: per Prefix-Befehl Text anonym in einen Ziel-Channel posten (als Embed, anonym, kein Logging)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(
        name="WichtelDM",
        aliases=["wichteldm", "wdm"],
        help="Schicke mir per DM einen Text: ich poste ihn anonym in den Ziel-Channel.",
    )
    @commands.dm_only()
    async def wichtel_dm(self, ctx: commands.Context, *, text: str | None = None):
        if ctx.guild is not None:
            return  # Absicherung

        if not TARGET_CHANNEL_ID:
            return await ctx.reply(
                "⚠️ Ziel-Channel nicht konfiguriert. Setze `WICHTEL_CHANNEL_ID` oder passe `TARGET_CHANNEL_ID` im Code an.",
                mention_author=False,
            )

        if not text or not text.strip():
            return await ctx.reply(
                "Bitte hänge Text an, z. B.:\n`+wdm Das ist meine anonyme Nachricht.`",
                mention_author=False,
            )

        # Ziel-Channel auflösen
        channel = self.bot.get_channel(TARGET_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(TARGET_CHANNEL_ID)
            except Exception:
                return await ctx.reply(
                    "Ich finde den Ziel-Channel nicht. Prüfe ID und meine Berechtigungen.",
                    mention_author=False,
                )

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await ctx.reply(
                "Der konfigurierte Ziel-Channel ist kein Text-Channel/Thread.",
                mention_author=False,
            )

        allowed = discord.AllowedMentions.none()
        chunks = _split_chunks(text, 2000)

        try:
            for i, chunk in enumerate(chunks, start=1):
                suffix = f" (Teil {i}/{len(chunks)})" if len(chunks) > 1 else ""

                embed = discord.Embed(
                    description=chunk + suffix,
                    color=discord.Color.blurple(),
                )
                embed.set_author(
                    name="Der geheimnisvolle Wichtel",
                    icon_url="https://www.shutterstock.com/image-vector/unknown-male-user-secret-identity-260nw-2055592583.jpg",  # Fragezeichen-Icon
                )

                await channel.send(embed=embed, allowed_mentions=allowed)

            await ctx.reply("✅ Dein Text wurde anonym gepostet.", mention_author=False)
        except discord.Forbidden:
            await ctx.reply(
                "Ich habe keine Schreibrechte im Ziel-Channel. Bitte prüfe meine Rollen/Rechte.",
                mention_author=False,
            )
        except Exception:
            await ctx.reply(
                "Es gab ein Problem beim Posten. Bitte prüfe die Konfiguration und versuche es erneut.",
                mention_author=False,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(WichtelDM(bot))
