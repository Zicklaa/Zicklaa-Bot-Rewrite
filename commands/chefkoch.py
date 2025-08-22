# chefkoch_cog.py
# -*- coding: utf-8 -*-
"""
Chefkoch-Cog (discord.py 2.x, Slash-Commands)
- /chefkoch suchen <zutaten>  : Sucht Rezepte auf Chefkoch und gibt 1 zufälligen Treffer zurück
- /chefkoch rotd              : "Recipe of the Day"
"""

from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

# Externes Modul (deins)
from get_chefkoch import Recipe, Search  # type: ignore

logger = logging.getLogger("ZicklaaBotRewrite.Chefkoch")

# Konfiguration
MAX_QUERY_LEN = 100        # Zeichenlimit für Suchstring
MAX_RESULTS_PICK = 5       # wir ziehen max. aus den ersten 5 Treffern zufällig eins


class Chefkoch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------- Slash-Befehle als Command-Group --------
    chefkoch = app_commands.Group(
        name="chefkoch",
        description="Chefkoch-Helfer: Rezepte suchen oder das Recipe of the Day holen.",
        guild_only=False,  # falls nur im Server gewünscht -> True und zusätzlich @app_commands.guild_only() je Subcommand
    )

    # /chefkoch suchen
    @chefkoch.command(name="suchen", description="Suche nach einem Rezept (z. B. 'nudeln lachs spinat').")
    @app_commands.describe(zutaten="Wörter oder Zutaten, z. B.: 'nudeln lachs spinat'")
    async def suchen(self, interaction: discord.Interaction, zutaten: str):
        """Sucht Chefkoch nach Rezepten und gibt einen zufälligen Link zurück."""
        try:
            query = (zutaten or "").strip().lower()

            if not query:
                await interaction.response.send_message(
                    "⚠️ Bitte gib mindestens **eine** Zutat/ein Stichwort an.",
                    ephemeral=True,
                )
                logger.info("Chefkoch suchen: leere Eingabe von %s (%s)", interaction.user, interaction.user.id)
                return

            if len(query) > MAX_QUERY_LEN:
                await interaction.response.send_message(
                    f"⚠️ Deine Eingabe ist zu lang (>{MAX_QUERY_LEN} Zeichen). Kürze sie bitte.",
                    ephemeral=True,
                )
                logger.info("Chefkoch suchen: zu lang (%d Zeichen) von %s", len(query), interaction.user)
                return

            await interaction.response.defer(thinking=True)  # falls API mal langsamer ist

            suche = Search(query)
            results: list[Recipe] = list(suche.recipes(limit=MAX_RESULTS_PICK))  # type: ignore

            if not results:
                await interaction.followup.send("😕 Keine Rezepte gefunden. Versuch andere Begriffe.")
                logger.info("Chefkoch suchen: 0 Treffer für '%s' von %s", query, interaction.user)
                return

            url = random.choice(results)._url
            
            if not url:
                await interaction.followup.send("😕 Unerwartetes Ergebnisformat. Probier es später nochmal.")
                logger.warning("Chefkoch suchen: Ergebnis ohne URL für '%s' von %s", query, interaction.user)
                return
            
            await interaction.followup.send(f"{url}\n**SCHMEEECKT :DDD**")
            logger.info("Chefkoch suchen: '%s' → %s (User: %s)", query, url, interaction.user)

        except Exception as e:
            logger.exception("Chefkoch suchen: Fehler bei '%s' von %s: %s", zutaten, interaction.user, e)
            # Fallback-Antwort je nach Response-Status
            if interaction.response.is_done():
                await interaction.followup.send("❌ Da ist was schiefgelaufen. Versuch's gleich nochmal.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Da ist was schiefgelaufen. Versuch's gleich nochmal.", ephemeral=True)

    # /chefkoch rotd
    @chefkoch.command(name="rotd", description="Hol das 'Recipe of the Day' von Chefkoch.")
    async def rotd(self, interaction: discord.Interaction):
        """Recipe of the Day (Chefkoch)."""
        try:
            await interaction.response.defer(thinking=True)

            recipe: Recipe = Search().recipeOfTheDay() 
            url = recipe._url

            if not url:
                await interaction.followup.send("😕 Konnte das Rezept des Tages nicht abrufen.")
                logger.warning("Chefkoch rotd: Ergebnis ohne ID (User: %s)", interaction.user)
                return

            await interaction.followup.send(f"**Recipe of the Day** 🍽️\n{url}\n**SCHMEEECKT :DDD**")
            logger.info("Chefkoch rotd: %s (User: %s)", url, interaction.user)

        except Exception as e:
            logger.exception("Chefkoch rotd: Fehler bei %s: %s", interaction.user, e)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Da ist was schiefgelaufen. Versuch's gleich nochmal.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Da ist was schiefgelaufen. Versuch's gleich nochmal.", ephemeral=True)


# --------- Setup (discord.py 2.x) ---------
async def setup(bot: commands.Bot):
    await bot.add_cog(Chefkoch(bot))
