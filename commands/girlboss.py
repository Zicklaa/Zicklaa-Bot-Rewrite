"""/girlboss – postet eine zufällige motivierende Girlboss-Nachricht (nur für ausgewählte User)."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError

GIRLBOSS_MESSAGES: list[str] = [
    "You go Girl!",
    "Du schaffst das!",
    "Ich glaub an dich!",
    "Halte durch!",
    "Slay Queen!",
    "Gaslight, Gatekeep, Girlboss!",
    "Du bist eine starke und eigenständige Frau!",
    "Ich bin so stolz auf deine Erfolge und Fortschritte!",
    "#BossQueen",
    "Wer kämpft, kann verlieren. Wer nicht kämpft, hat schon verloren.",
    "Es ist immer zu früh, um aufzugeben.",
    "Jede schwierige Situation, die du jetzt meisterst, bleibt dir in der Zukunft erspart.",
    "Wenn Du etwas gesagt haben willst frage einen Mann; wenn Du etwas getan haben willst frage eine Frau.",
    "Das Leben ist hart, aber das bist du auch.",
    "Hab keine Angst, für dich selbst einzutreten. Kämpfe weiter für deine Träume!",
    "Vergiss niemals deinen eigenen Wert!",
    "Jeder Tag ist dein Tag!",
    "Alles ist möglich, wenn du nur wirklich willst!",
    "Queens fix each other’s crowns. 👑",
    "Dein Future Self dankt dir jetzt schon.",
    "Nicht perfekt, aber **unstoppbar**.",
    "Erst träumen, dann tun. Jetzt.",
    "Kleine Schritte, große Wirkung.",
    "Deine Power ist ansteckend.",
    "Heute: Grenzen sprengen, Erwartungen toppen.",
    "Mehr Boss, weniger Stress.",
    "Du bist das ganze Paket – mit Expressversand.",
    "Nochmal versuchen > Aufgeben.",
    "Mut > Angst. Immer.",
    "Was du heute startest, feierst du morgen.",
    "Wenn nicht du – wer dann?",
    "Skalier deine Standards, nicht deine Zweifel.",
    "Du bist nicht 'zu viel' – die Welt ist nur 'zu leise'.",
    "Ausstrahlung: unbezahlbar. Einstellung: unbesiegbar.",
    "Dein Hustle spricht für sich.",
    "Focus. Finish. Flex.",
    "Nicht warten bis es leichter wird – **du** wirst stärker.",
    "Reminder: Du bist die Hauptfigur. 🎬",
]

# User, die /girlboss ausführen dürfen
GIRLBOSSES: tuple[int, ...] = (
    200009451292459011,
    134574105109331968,
    288413759117066241,
    191119825353965568,
)


class Girlboss(BaseCog):
    """Cog: /girlboss."""

    @app_commands.command(
        name="girlboss",
        description="Schenkt dir eine zufällige Girlboss-Power-Message ✨",
        extras={"error": "Heute kein Girlbossen :/"},
    )
    async def girlboss(self, interaction: discord.Interaction):
        if interaction.user.id not in GIRLBOSSES:
            raise UserError("🚫 Dieser Befehl ist aktuell nur für ausgewählte Queens aktiviert.")

        await interaction.response.send_message(random.choice(GIRLBOSS_MESSAGES))
        self.log("Message sent", interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Girlboss(bot))
