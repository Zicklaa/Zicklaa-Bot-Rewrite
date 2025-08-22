# rezept_cog.py
# -*- coding: utf-8 -*-
"""
Rezept-Cog (discord.py 2.x, Slash-Command)
- /rezept [channel] : schickt einen Link zu einem zufälligen gepinnten Rezept
- Nur in bestimmten Channels nutzbar (ALLOWED_CHANNEL_IDS)
"""

from __future__ import annotations

import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ZicklaaBotRewrite.Rezept")

# In diesen Channels darf der Command ausgeführt werden:
ALLOWED_CHANNEL_IDS: list[int] = [
    860154286141997056,   # #durst-auf-wurst
    567411189336768532,  # testchannel (Dev-Channel)
]

# Fallback-Standardkanal, wenn kein channel-Parameter übergeben wurde
DEFAULT_RECIPE_CHANNEL_ID = 860154286141997056


class Rezept(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------- Slash-Command --------------------

    @app_commands.command(name="rezept", description="Schickt einen Link zu einem zufälligen gepinnten Rezept.")
    async def rezept(self, interaction: discord.Interaction):
        """
        Holt die Pins aus dem angegebenen (oder Default-)Kanal und postet
        einen Link zu einer zufälligen gepinnten Nachricht.
        """
        # Nur in Guilds sinnvoll
        if interaction.guild is None:
            await interaction.response.send_message("❌ Dieser Befehl funktioniert nur auf einem Server.", ephemeral=True)
            return

        # Channel-Gate: nur in erlaubten Channels (inkl. deren Threads)
        ch = interaction.channel
        parent_id = ch.parent_id if isinstance(
            ch, (discord.Thread, discord.ForumChannel)) else None
        if (interaction.channel_id not in ALLOWED_CHANNEL_IDS) and (parent_id not in ALLOWED_CHANNEL_IDS):
            allowed_mentions = ", ".join(
                f"<#{cid}>" for cid in ALLOWED_CHANNEL_IDS)
            await interaction.response.send_message(
                f"🚫 Bitte nutze diesen Befehl in {allowed_mentions}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            cached = interaction.guild.get_channel(DEFAULT_RECIPE_CHANNEL_ID)
            if isinstance(cached, discord.TextChannel):
                target_channel = cached
            else:
                fetched = await self.bot.fetch_channel(DEFAULT_RECIPE_CHANNEL_ID)
                target_channel = fetched if isinstance(
                    fetched, discord.TextChannel) else None

            if target_channel is None:
                await interaction.followup.send("❌ Konnte den Rezepte-Kanal nicht finden.", ephemeral=True)
                logger.warning(
                    "Rezept: Zielkanal nicht gefunden (guild=%s, channel_id=%s)",
                    interaction.guild.id, DEFAULT_RECIPE_CHANNEL_ID
                )
                return

            # Pins laden
            pins = await target_channel.pins()
            if not pins:
                await interaction.followup.send(
                    f"ℹ️ In {target_channel.mention} sind keine Pins vorhanden.",
                    ephemeral=True,
                )
                logger.info("Rezept: Keine Pins in #%s (%s)",
                            target_channel.name, target_channel.id)
                return

            # Zufällige gepinnte Nachricht wählen
            message = random.choice(pins)

            # Öffentlich antworten (Link ist für alle sichtbar)

            quote_cog = self.bot.get_cog("Quote")
            if not quote_cog:
                await interaction.followup.send(message.jump_url)
                logger.info(
                    "Rezept: Link gesendet (%s) von %s in guild %s",
                    message.jump_url, interaction.user, interaction.guild.id
                )
                return

            embed = await quote_cog.build_quote_embed_from_link(message.jump_url)
            await interaction.followup.send(embed=embed)

            logger.info(
                "Rezept: Link gesendet (%s) von %s in guild %s",
                message.jump_url, interaction.user, interaction.guild.id
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Mir fehlen Berechtigungen, um Pins in diesem Kanal zu lesen.",
                ephemeral=True,
            )
            logger.exception("Rezept: Missing permissions in channel")
        except Exception as e:
            await interaction.followup.send("❌ Klappt nit lol 🤷", ephemeral=True)
            logger.exception("Rezept: Unerwarteter Fehler: %s", e)


# -------------------- Setup --------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Rezept(bot))
