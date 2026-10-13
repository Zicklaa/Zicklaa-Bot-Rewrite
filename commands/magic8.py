"""/magic8 – beantwortet eine Frage mit einer zufälligen Antwort."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError
from utils.helpers import NO_MENTIONS

MAGIC8_ANSWERS: tuple[str, ...] = (
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
)


class Magic8(BaseCog):
    """Cog: /magic8 – die magische 8-Ball."""

    @app_commands.command(
        name="magic8",
        description="Stelle eine Frage – die magische 8-Ball antwortet zufällig.",
        extras={"error": "❌ Klappt nit lol 🤷"},
    )
    @app_commands.describe(
        frage="Deine Frage an die magische 8-Ball (z. B. 'Besteht morgen die Sonne?')."
    )
    async def magic8(self, interaction: discord.Interaction, frage: str | None = None):
        if not frage or not frage.strip():
            raise UserError("🤔 Stell mir eine Frage, damit ich sie beantworten kann!")

        antwort = random.choice(MAGIC8_ANSWERS)
        await interaction.response.send_message(
            f"🎱 **Frage:** {frage}\n**Antwort:** {antwort}", allowed_mentions=NO_MENTIONS
        )
        self.log("Answer sent", interaction, question=frage, answer=antwort)


async def setup(bot: commands.Bot):
    await bot.add_cog(Magic8(bot))
