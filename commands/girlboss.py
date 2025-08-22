# girlboss_cog.py
# -*- coding: utf-8 -*-
"""
Girlboss-Cog (discord.py 2.x, Slash-Command)
- /girlboss : postet eine zufällige motivierende Girlboss-Nachricht und pingt die/den Ausführenden
- Nur bestimmte User dürfen den Command nutzen (siehe GIRLBOSSES)
"""
from __future__ import annotations

import logging
import random
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ZicklaaBotRewrite.Girlboss")

# -------------------- Daten --------------------

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

# -------------------- Cog --------------------

class Girlboss(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="girlboss", description="Schenkt dir eine zufällige Girlboss-Power-Message ✨")
    async def girlboss(self, interaction: discord.Interaction):
        """
        Postet eine motivierende Girlboss-Nachricht und pingt die Person,
        die den Command ausgeführt hat – nur für freigeschaltete User.
        """
        try:
            uid = interaction.user.id
            if uid not in GIRLBOSSES:
                # freundlich & nicht-spammy: ephemerer Hinweis
                await interaction.response.send_message(
                    "🚫 Dieser Befehl ist aktuell nur für ausgewählte Queens aktiviert.",
                    ephemeral=True,
                )
                logger.info("Girlboss: Zugriff verweigert für %s (%s)", interaction.user, uid)
                return

            # öffentlich antworten, damit der Ping sichtbar ist
            await interaction.response.send_message(random.choice(GIRLBOSS_MESSAGES))
            logger.info("Girlboss: Nachricht gesendet für %s (%s): %s", interaction.user, uid)

        except Exception as e:
            logger.exception("Girlboss: Fehler bei %s: %s", interaction.user, e)
            # sichere Fallback-Antwort
            if interaction.response.is_done():
                await interaction.followup.send("Heute kein Girlbossen :/", ephemeral=True)
            else:
                await interaction.response.send_message("Heute kein Girlbossen :/", ephemeral=True)

# -------------------- Setup --------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Girlboss(bot))
