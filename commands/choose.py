"""/choose – wählt zufällig eine Option aus einer vom Nutzer angegebenen Liste."""

import csv
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError

MAX_OPTIONS = 10          # maximale Anzahl geparster Optionen
MIN_OPTIONS_REQUIRED = 2  # mindestens 2 Optionen notwendig


def parse_options(raw: str) -> list[str]:
    """Wandelt die Options-Zeichenkette in eine bereinigte Liste um.

    - Trenner: Komma, Semikolon, Pipe; Anführungszeichen halten Optionen zusammen (CSV-Parsing)
    - entfernt Leereinträge und Duplikate (ohne Groß-/Kleinschreibung, Reihenfolge bleibt)
    """
    normalized = (raw or "").replace(";", ",").replace("|", ",")
    unique: dict[str, str] = {}
    for row in csv.reader(normalized.splitlines(), skipinitialspace=True):
        for item in row:
            if item.strip():
                # setdefault behält das erste Vorkommen (und dessen Schreibweise)
                unique.setdefault(item.strip().lower(), item.strip())
    return list(unique.values())[:MAX_OPTIONS]


class Choose(BaseCog):
    """Cog: /choose – zufällige Auswahl."""

    @app_commands.command(name="choose", description="Wählt zufällig eine Option aus einer Liste.")
    @app_commands.describe(
        options="Optionen getrennt durch Komma/Semikolon/Pipe oder in Anführungszeichen. z. B.: Pizza, Döner; Burger | \"Nudeln mit Soße\"",
    )
    async def choose(self, interaction: discord.Interaction, options: str):
        items = parse_options(options)
        if len(items) < MIN_OPTIONS_REQUIRED:
            raise UserError(
                f"❌ Gib mindestens {MIN_OPTIONS_REQUIRED} Optionen an, z. B.: `Pizza, Döner, Burger`."
            )

        pick = random.choice(items)
        await interaction.response.send_message(
            f"🎱 Oh magische Miesmuschel! Wie lautet deine Antwort?\n**{pick}**"
        )
        self.log("Option chosen", interaction, options=len(items), result=pick)


async def setup(bot: commands.Bot):
    await bot.add_cog(Choose(bot))
