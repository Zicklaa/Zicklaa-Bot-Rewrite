"""/hm & /hmm – zufällige Sätze aus dem Hivemind (Markov-Modell)."""

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, in_channels
from utils.helpers import NO_MENTIONS
from utils.settings import SPAM_CHANNEL_ID


class Hivemind(BaseCog):
    """Cog: /hm (ein Satz) & /hmm (fünf Sätze, nur im Spam-Channel)."""

    @app_commands.command(name="hm", description="Generiert einen zufälligen Satz aus dem Hivemind.")
    async def hm(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            self.bot.hivemind_sentence(), allowed_mentions=NO_MENTIONS
        )
        self.log("Sentence sent", interaction)

    @app_commands.command(name="hmm", description="Generiert 5 zufällige Sätze (nur im Spam-Channel).")
    @in_channels(SPAM_CHANNEL_ID)
    async def hmm(self, interaction: discord.Interaction):
        # Die Sätze kommen als eigene Nachrichten; die "denkt nach"-Antwort wird danach gelöscht
        await interaction.response.defer(thinking=True)
        for _ in range(5):
            await interaction.channel.send(self.bot.hivemind_sentence(), allowed_mentions=NO_MENTIONS)

        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
        self.log("HMM executed", interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Hivemind(bot))
