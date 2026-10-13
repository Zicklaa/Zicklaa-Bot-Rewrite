"""+wdm – per DM einen Text anonym in den Wichtel-Channel posten.

Bewusst ohne Logging des Absenders, damit die Nachricht wirklich anonym bleibt.
"""

import discord
from discord.ext import commands

from utils.base import BaseCog
from utils.helpers import NO_MENTIONS, fetch_channel, split_text

TARGET_CHANNEL_ID = 1320467815177916527
WICHTEL_ICON = "https://www.shutterstock.com/image-vector/unknown-male-user-secret-identity-260nw-2055592583.jpg"


class WichtelDM(BaseCog):
    """Cog: +WichtelDM / +wdm (nur per DM)."""

    @commands.command(
        name="WichtelDM",
        aliases=["wichteldm", "wdm"],
        help="Schicke mir per DM einen Text: ich poste ihn anonym in den Ziel-Channel.",
    )
    @commands.dm_only()
    async def wichtel_dm(self, ctx: commands.Context, *, text: str | None = None):
        async def answer(message: str):
            await ctx.reply(message, mention_author=False)

        if not text or not text.strip():
            return await answer("Bitte hänge Text an, z. B.:\n`+wdm Das ist meine anonyme Nachricht.`")

        try:
            channel = await fetch_channel(self.bot, TARGET_CHANNEL_ID)
        except discord.HTTPException:
            return await answer("Ich finde den Ziel-Channel nicht. Prüfe ID und meine Berechtigungen.")
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await answer("Der konfigurierte Ziel-Channel ist kein Text-Channel/Thread.")

        # Lange Texte auf mehrere Embeds verteilen
        chunks = split_text(text, 2000)
        try:
            for i, chunk in enumerate(chunks, start=1):
                suffix = f" (Teil {i}/{len(chunks)})" if len(chunks) > 1 else ""
                embed = discord.Embed(description=chunk + suffix, color=discord.Color.blurple())
                embed.set_author(name="Der geheimnisvolle Wichtel", icon_url=WICHTEL_ICON)
                await channel.send(embed=embed, allowed_mentions=NO_MENTIONS)
            await answer("✅ Dein Text wurde anonym gepostet.")
        except discord.Forbidden:
            await answer("Ich habe keine Schreibrechte im Ziel-Channel. Bitte prüfe meine Rollen/Rechte.")
        except Exception:
            await answer("Es gab ein Problem beim Posten. Bitte prüfe die Konfiguration und versuche es erneut.")


async def setup(bot: commands.Bot):
    await bot.add_cog(WichtelDM(bot))
