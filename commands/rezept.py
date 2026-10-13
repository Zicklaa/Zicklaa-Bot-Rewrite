"""/rezept – zitiert ein zufälliges gepinntes Rezept aus dem Rezepte-Kanal."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError, in_channels
from utils.helpers import fetch_channel
from utils.settings import TEST_CHANNEL_ID

# Aus diesem Kanal kommen die gepinnten Rezepte
RECIPE_CHANNEL_ID = 860154286141997056  # #durst-auf-wurst

# In diesen Channels (und deren Threads) darf der Command ausgeführt werden
ALLOWED_CHANNEL_IDS = (RECIPE_CHANNEL_ID, TEST_CHANNEL_ID)


class Rezept(BaseCog):
    """Cog: /rezept."""

    @app_commands.command(
        name="rezept",
        description="Schickt einen Link zu einem zufälligen gepinnten Rezept.",
        extras={"error": "❌ Klappt nit lol 🤷"},
    )
    @in_channels(
        *ALLOWED_CHANNEL_IDS,
        message=f"🚫 Bitte nutze diesen Befehl in {', '.join(f'<#{cid}>' for cid in ALLOWED_CHANNEL_IDS)}.",
    )
    async def rezept(self, interaction: discord.Interaction):
        if interaction.guild is None:
            raise UserError("❌ Dieser Befehl funktioniert nur auf einem Server.")

        await interaction.response.defer(thinking=True)

        try:
            channel = await fetch_channel(self.bot, RECIPE_CHANNEL_ID)
            pins = [message async for message in channel.pins()]
        except discord.NotFound:
            raise UserError("❌ Konnte den Rezepte-Kanal nicht finden.")
        except discord.Forbidden:
            raise UserError("❌ Mir fehlen Berechtigungen, um Pins in diesem Kanal zu lesen.")
        if not pins:
            raise UserError(f"ℹ️ In {channel.mention} sind keine Pins vorhanden.")

        message = random.choice(pins)

        # Schön als Zitat-Embed, falls das Quote-Cog geladen ist – sonst nur der Link
        quote_cog = self.bot.get_cog("Quote")
        if quote_cog:
            await interaction.followup.send(embed=quote_cog.build_quote_embed(message))
        else:
            await interaction.followup.send(message.jump_url)
        self.log("Recipe link sent", interaction, url=message.jump_url)


async def setup(bot: commands.Bot):
    await bot.add_cog(Rezept(bot))
