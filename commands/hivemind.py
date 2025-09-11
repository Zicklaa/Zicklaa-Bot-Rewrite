import logging
import discord
from discord.ext import commands
from discord import app_commands

from utils.logging_helper import log_event

# -------------------- Logger & Konfiguration --------------------

logger = logging.getLogger("ZicklaaBotRewrite.Hivemind")

# AllowedMentions: Keine Pings für User, Rollen, everyone/here oder Replies
am = discord.AllowedMentions(
    users=False,
    everyone=False,
    roles=False,
    replied_user=False
)

# Satz-Generierungs-Parameter
ratio = 0.6
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
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Sentence sent",
                interaction.user,
                interaction.user.id,
                command="/hm",
            )
        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Sentence failed",
                interaction.user,
                interaction.user.id,
                command="/hm",
                error=e,
                exc_info=True,
            )

    @app_commands.command(name="hmm", description="Generiert 5 zufällige Sätze (nur im Spam-Channel).")
    async def hmm(self, interaction: discord.Interaction):
        if interaction.channel_id != SPAM_CHANNEL_ID:
            await interaction.response.send_message("Spam woanders, Moruk 🤷", ephemeral=True)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Wrong channel",
                interaction.user,
                interaction.user.id,
                command="/hmm",
                channel_id=interaction.channel_id,
            )
            return

        try:
            # Ephemeral „Denke…“ schicken (verhindert Timeout)
            await interaction.response.defer(thinking=True, ephemeral=False)

            for _ in range(5):
                while True:
                    satz = self.json_model.make_sentence(
                        max_overlap_ratio=ratio)
                    if satz:
                        await interaction.channel.send(
                            satz,
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                        break

            try:
                await interaction.delete_original_response()
            except Exception:
                pass

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "HMM executed",
                interaction.user,
                interaction.user.id,
                command="/hmm",
            )

        except Exception as e:
            # Falls das Löschen oben fehlschlug, wenigstens sauber abschließen
            try:
                await interaction.followup.send("Klappt nit lol 🤷", ephemeral=True)
            except Exception:
                pass
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "HMM failed",
                interaction.user,
                interaction.user.id,
                command="/hmm",
                error=e,
                exc_info=True,
            )


# -------------------- Cog-Setup --------------------


async def setup(bot: commands.Bot):
    """Fügt das Hivemind-Cog dem Bot hinzu."""
    await bot.add_cog(Hivemind(bot, bot.json_model))
