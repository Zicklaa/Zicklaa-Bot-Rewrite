import logging
import random
import csv
import io
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ZicklaaBotRewrite.Choose")

# Sinnvolle Grenzen
MAX_OPTIONS = 10          # maximale Anzahl geparster Optionen
MIN_OPTIONS_REQUIRED = 2   # mindestens 2 Optionen notwendig


def _parse_options(raw: str) -> list[str]:
    """
    Wandelt eine vom Nutzer übergebene Options-Zeichenkette in eine bereinigte Liste um.
    - Akzeptiert Trenner: Komma, Semikolon, Pipe
    - Beachtet Anführungszeichen (über CSV-Parsing)
    - Trimmt Leerzeichen, entfernt Leereinträge und Duplikate (Reihenfolge bleibt erhalten)
    """
    if not raw:
        return []

    # Trenner für das CSV-Parsing vereinheitlichen
    normalized = raw.replace(";", ",").replace("|", ",")

    # CSV-Reader respektiert Anführungszeichen, z. B.: "ja bitte, mit Soße", nein, vielleicht
    reader = csv.reader(io.StringIO(normalized))
    parsed = []
    for row in reader:
        for item in row:
            item = item.strip()
            if item:
                parsed.append(item)

    # Duplikate entfernen (reihenfolgentreu)
    seen = set()
    deduped = []
    for opt in parsed:
        key = opt.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(opt)

    # Auf MAX_OPTIONS kappen
    return deduped[:MAX_OPTIONS]


class Choose(commands.Cog):
    """Cog: /choose – wählt zufällig eine Option aus einer vom Nutzer angegebenen Liste."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="choose",
        description="Wählt zufällig eine Option aus einer Liste."
    )
    @app_commands.describe(
        options="Optionen getrennt durch Komma/Semikolon/Pipe oder in Anführungszeichen. z. B.: Pizza, Döner; Burger | \"Nudeln mit Soße\""
    )
    async def choose(self, interaction: discord.Interaction, options: str):
        """
        Slash: /choose options:<string>
        - Robustes Parsing (Komma/Semikolon/Pipe/Anführungszeichen)
        """
        try:
            items = _parse_options(options)

            if len(items) < MIN_OPTIONS_REQUIRED:
                await interaction.response.send_message(
                    f"❌ Gib mindestens {MIN_OPTIONS_REQUIRED} Optionen an, z. B.: `Pizza, Döner, Burger`.",
                    ephemeral=True
                )
                logger.warning(
                    "Zu wenige Optionen bei /choose von %s (ID: %s). Eingabe: %r",
                    interaction.user, interaction.user.id, options
                )
                return

            pick = random.choice(items)

            # Antwort ohne Nutzer-/Rollen-Pings senden
            await interaction.response.send_message(
                f"🎱 Oh magische Miesmuschel! Wie lautet deine Antwort?\n**{pick}**"
            )

            logger.info(
                "Antwort für /choose an %s (ID: %s). Kandidaten: %d, Gewählt: %r",
                interaction.user, interaction.user.id, len(items), pick
            )

        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            logger.error(
                "Fehler bei /choose von %s (ID: %s): %s",
                interaction.user, interaction.user.id, e
            )


# Standard-Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(Choose(bot))
