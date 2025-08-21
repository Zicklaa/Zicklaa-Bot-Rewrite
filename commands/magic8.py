import logging
import random
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ZicklaaBotRewrite.Magic8")

# Feste Antworten der Magic-8-Ball-Logik
MAGIC8_ANSWERS: list[str] = [
    "Zu 100% Ja!",
    "Es ist so entschieden, Ja.",
    "Ja :3 OwO",
    "Ohne Zweifel, Ja.",
    "Definitiv, Ja.",
    "Kannst dich drauf verlassen, Digga.",
    "So wie ich des seh, scho, Ja.",
    "Denk scho, Ja.",
    "Ja.",
    "Mein Fisch hat Analkrebs",
    "Ich hab Dieter um rat gefragt, er sagt Ja.",
    "Merkur ist rückläufig, also Ja.",
    "Digga, bin hier grad Ballsdeep in etwas, frag später.",
    "Du würdest die Wahrheit nicht verkraften.",
    "Weiß nich, lol.",
    "Ich schwöre ich hab keine Ahnung von was du redest.",
    "Musst du Dieter fragen.",
    "Jesse, von was zum Fick redest du??",
    "Nein.",
    "Nein, lol.",
    "Get fucked Digga, als ob ich dazu Ja sag.",
    "Du literarischer Untermensch, was stellst du mir so eine kernbehinderte Frage???",
    "Sieht nicht so aus.",
    "Würd ich ned drauf wetten.",
    "Niemals, Kollege.",
    "Dieter hat Nein gesagt :///",
    "Ich weiß nicht, aber wie wärs mit Megges?",
    "Nein, du HUNDT.",
    "Geht dich nen scheißdreck an, Mois.",
    "H̶͕̦̬̮̖̼̠͈̗͈̤̥̣̣̋̂̐̆̈́̊͋́͠͝i̵̢̥̻̹͉̰̟̤͔̰̾͛ͅn̴̹͈̬̝̦͇̤͍͒̅ͅť̷̨̙̣̘̗͙̞͔̳͗̆͂̑e̸̢̫̝̭̗̰̙̲̟̼̝̺͇̥͜͝r̷̛̭̣͔͚̳͑̿̈́̄͋̂̊̾͗̉̾̿͜͝͝ ̸̨̬̖̦͉͍̯̜͕͔̪̭̜͚̒d̷̟̼̯̺͔̯̱̞̊̐̆̽̑̎̚͜ĭ̵̡͙̓̏͗̈̒͐͋̐̄͝ͅr̶̭̱̫͍͙͙̻̩͓̱̍̿̾́̓̈̆̔͂̂͒̏̽͝.",
    "Nur wenn KOSCHDELOS is.",
    "Teile dieser Antwort könnte die User verunsichern.",
]


class Magic8(commands.Cog):
    """Cog für den Befehl /magic8 – beantwortet eine Frage zufällig."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="magic8",
        description="Stelle eine Frage – die magische 8-Ball antwortet zufällig."
    )
    @app_commands.describe(
        frage="Deine Frage an die magische 8-Ball (z. B. 'Besteht morgen die Sonne?')."
    )
    async def magic8(self, interaction: discord.Interaction, frage: str | None = None):
        """
        Slash-Befehl: /magic8 [frage]
        - Wenn eine Frage angegeben ist, gibt der Bot eine zufällige Antwort zurück.
        - Wenn keine Frage angegeben ist, fordert er freundlich dazu auf.
        """
        try:
            if not frage or not frage.strip():
                await interaction.response.send_message(
                    "🤔 Stell mir eine Frage, damit ich sie beantworten kann!",
                    ephemeral=True
                )
                logger.info(
                    " /magic8 ohne Frage von %s (ID: %s)",
                    interaction.user, interaction.user.id
                )
                return

            antwort = random.choice(MAGIC8_ANSWERS)

            await interaction.response.send_message(
                f"🎱 **Frage:** {frage}\n**Antwort:** {antwort}",
                allowed_mentions=discord.AllowedMentions.none()
            )
            logger.info(
                " /magic8 Antwort an %s (ID: %s) – Frage: %r, Antwort: %r",
                interaction.user, interaction.user.id, frage, antwort
            )

        except Exception as e:
            await interaction.response.send_message(
                "❌ Klappt nit lol 🤷", ephemeral=True
            )
            logger.error(
                "Fehler bei /magic8 von %s (ID: %s): %s",
                interaction.user, interaction.user.id, e
            )


# Standard-Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(Magic8(bot))
