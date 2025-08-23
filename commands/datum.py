import logging
import datetime
import locale
import discord
from discord.ext import commands
from discord import app_commands

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Datum")

# --- Locale einmalig (best effort) auf Deutsch setzen ---
# Achtung: Je nach System heißt die Locale anders. Wir versuchen mehrere Varianten.
_LOCALE_SET = False
for loc in ("de_DE.utf8", "de_DE.UTF-8", "de_DE", "deu_deu", "German_Germany"):
    try:
        locale.setlocale(locale.LC_ALL, loc)
        _LOCALE_SET = True
        break
    except Exception:
        continue

# Fallback-Maps, falls Locale nicht gesetzt werden konnte
WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch",
               "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember"
]


def format_date_de(d: datetime.date) -> tuple[str, str]:
    """
    Gibt (Wochentag, Datum) in deutscher Schreibweise zurück.
    Bevorzugt locale.strftime, fällt sonst auf manuelle Maps zurück.
    Beispiele:
      ("Dienstag", "21. August 2025")
    """
    if _LOCALE_SET:
        try:
            tag = d.strftime("%A")             # z.B. Dienstag
            datum = d.strftime("%d. %B %Y")    # z.B. 21. August 2025
            return tag, datum
        except Exception:
            pass

    # Fallback ohne gesetzte Locale
    weekday = WEEKDAYS_DE[d.weekday()]
    month = MONTHS_DE[d.month - 1]
    datum = f"{d.day:02d}. {month} {d.year}"
    return weekday, datum


class Datum(commands.Cog):
    """Cog: Gibt das heutige Datum als hübsch formatierten Text aus."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="datum", description="Zeigt das heutige Datum an (deutsch formatiert).")
    async def datum(self, interaction: discord.Interaction):
        """
        Slash-Command: /datum
        Antwort-Beispiel: 'Heute ist **Dienstag**, der **21. August 2025**.'
        """
        try:
            today = datetime.date.today()
            tag, datum = format_date_de(today)

            text = f"Heute ist **{tag}**, der **{datum}**."
            await interaction.response.send_message(text)

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Date sent",
                interaction.user,
                interaction.user.id,
                command="/datum",
                message=text,
            )
        except Exception as e:
            # Fehler sauber an den Nutzer melden (ephemeral)
            await interaction.response.send_message("Puh, schwierig 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Date error",
                interaction.user,
                interaction.user.id,
                command="/datum",
                error=e,
                exc_info=True,
            )


# --- Cog-Setup (discord.py 2.x) ---
async def setup(bot: commands.Bot):
    await bot.add_cog(Datum(bot))
