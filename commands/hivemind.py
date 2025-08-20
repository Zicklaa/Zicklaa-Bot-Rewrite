import logging
import discord
from discord.ext import commands
from discord import app_commands

# -------------------- Logger & Konfiguration --------------------

logger = logging.getLogger("ZicklaaBot.Hivemind")

# AllowedMentions: Keine Pings für User, Rollen, everyone/here oder Replies
am = discord.AllowedMentions(
    users=False,
    everyone=False,
    roles=False,
    replied_user=False
)

# Satz-Generierungs-Parameter
ratio = 0.7
SPAM_CHANNEL_ID = 528742785935998979

# -------------------- Cog-Klasse --------------------


class Hivemind(commands.Cog):
    """Cog für zufällige Sätze aus dem Hivemind (Markov-Modell)."""

    def __init__(self, bot, json_model):
        self.bot = bot
        self.json_model = json_model

    @app_commands.command(
        name="hm",
        description="Generiert einen zufälligen Satz aus dem Hivemind."
    )
    async def hm(self, interaction: discord.Interaction):
        """Slash-Command: /hm – Ein zufälliger Satz."""
        try:
            while True:
                satz = self.json_model.make_sentence(max_overlap_ratio=ratio)
                if satz:
                    await interaction.response.send_message(satz, allowed_mentions=am)
                    break
            logger.info("Hivemind für: %s", interaction.user.name)
        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            logger.error("Hivemind ERROR von %s: %s", interaction.user.name, e)

    @app_commands.command(
        name="hmm",
        description="Generiert 5 zufällige Sätze (nur im Spam-Channel)."
    )
    async def hmm(self, interaction: discord.Interaction):
        """Slash-Command: /hmm – Fünf Sätze, nur im Spam-Channel."""
        if interaction.channel_id != SPAM_CHANNEL_ID:
            await interaction.response.send_message(
                "Spam woanders, Moruk 🤷", ephemeral=True
            )
            logger.info("Hippomode ERROR von %s", interaction.user.name)
            return

        try:
            lines = []
            for _ in range(5):
                while True:
                    satz = self.json_model.make_sentence(
                        max_overlap_ratio=ratio)
                    if satz:
                        lines.append(satz)
                        break
            await interaction.response.send_message(
                "\n".join(lines), allowed_mentions=am
            )
            logger.info("Hivemind für: %s", interaction.user.name)
        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            logger.error("Hivemind ERROR von %s: %s", interaction.user.name, e)

# -------------------- Cog-Setup --------------------


async def setup(bot: commands.Bot):
    """Fügt das Hivemind-Cog dem Bot hinzu."""
    await bot.add_cog(Hivemind(bot, bot.json_model))
