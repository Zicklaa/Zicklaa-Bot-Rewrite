"""/datum – zeigt das heutige Datum in deutscher Schreibweise."""

import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog

WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def format_date_de(d: datetime.date) -> tuple[str, str]:
    """Gibt (Wochentag, Datum) zurück, z. B. ``("Dienstag", "21. August 2025")``."""
    return WEEKDAYS_DE[d.weekday()], f"{d.day:02d}. {MONTHS_DE[d.month - 1]} {d.year}"


class Datum(BaseCog):
    """Cog: /datum – heutiges Datum als Text."""

    @app_commands.command(
        name="datum",
        description="Zeigt das heutige Datum an (deutsch formatiert).",
        extras={"error": "Puh, schwierig 🤷"},
    )
    async def datum(self, interaction: discord.Interaction):
        tag, datum = format_date_de(datetime.date.today())
        text = f"Heute ist **{tag}**, der **{datum}**."
        await interaction.response.send_message(text)
        self.log("Date sent", interaction, message=text)


async def setup(bot: commands.Bot):
    await bot.add_cog(Datum(bot))
