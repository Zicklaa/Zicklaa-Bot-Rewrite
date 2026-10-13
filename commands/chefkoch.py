"""/chefkoch suchen|rotd – Rezepte von Chefkoch."""

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands
from get_chefkoch import Search  # type: ignore

from utils.base import BaseCog, UserError

MAX_QUERY_LEN = 100   # Zeichenlimit für den Suchstring
MAX_RESULTS_PICK = 5  # aus den ersten 5 Treffern wird zufällig einer gewählt

ERROR_TEXT = "❌ Da ist was schiefgelaufen. Versuch's gleich nochmal."


class Chefkoch(BaseCog):
    """Cog: /chefkoch."""

    chefkoch = app_commands.Group(
        name="chefkoch",
        description="Chefkoch-Helfer: Rezepte suchen oder das Recipe of the Day holen.",
    )

    @chefkoch.command(
        name="suchen",
        description="Suche nach einem Rezept (z. B. 'nudeln lachs spinat').",
        extras={"error": ERROR_TEXT},
    )
    @app_commands.describe(zutaten="Wörter oder Zutaten, z. B.: 'nudeln lachs spinat'")
    async def suchen(self, interaction: discord.Interaction, zutaten: str):
        """Sucht auf Chefkoch und gibt einen zufälligen der ersten Treffer zurück."""
        query = zutaten.strip().lower()
        if not query:
            raise UserError("⚠️ Bitte gib mindestens **eine** Zutat/ein Stichwort an.")
        if len(query) > MAX_QUERY_LEN:
            raise UserError(f"⚠️ Deine Eingabe ist zu lang (>{MAX_QUERY_LEN} Zeichen). Kürze sie bitte.")

        await interaction.response.defer(thinking=True)

        # get_chefkoch arbeitet synchron -> in einen Thread auslagern
        results = await asyncio.to_thread(lambda: list(Search(query).recipes(limit=MAX_RESULTS_PICK)))
        if not results:
            raise UserError("😕 Keine Rezepte gefunden. Versuch andere Begriffe.")

        url = random.choice(results)._url
        if not url:
            raise UserError("😕 Unerwartetes Ergebnisformat. Probier es später nochmal.")

        await interaction.followup.send(f"{url}\n**SCHMEEECKT :DDD**")
        self.log("Recipe link sent", interaction, query=query, url=url)

    @chefkoch.command(
        name="rotd",
        description="Hol das 'Recipe of the Day' von Chefkoch.",
        extras={"error": ERROR_TEXT},
    )
    async def rotd(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        recipe = await asyncio.to_thread(lambda: Search().recipeOfTheDay())
        if not recipe._url:
            raise UserError("😕 Konnte das Rezept des Tages nicht abrufen.")

        await interaction.followup.send(f"**Recipe of the Day** 🍽️\n{recipe._url}\n**SCHMEEECKT :DDD**")
        self.log("Recipe of the day sent", interaction, url=recipe._url)


async def setup(bot: commands.Bot):
    await bot.add_cog(Chefkoch(bot))
