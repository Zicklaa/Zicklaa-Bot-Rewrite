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

    @app_commands.command(name="hmm", description="Generiert 5 zufällige Sätze (nur im Spam-Channel).")
    async def hmm(self, interaction: discord.Interaction):
        if interaction.channel_id != SPAM_CHANNEL_ID:
            await interaction.response.send_message("Spam woanders, Moruk 🤷", ephemeral=True)
            logger.info("Hippomode ERROR von %s (ID: %s)",
                        interaction.user.name, interaction.user.id)
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

            # Den „denkt…“-Stub wieder weg
            try:
                await interaction.delete_original_response()
            except Exception:
                pass

            logger.info("Hivemind /hmm von %s (ID: %s)",
                        interaction.user.name, interaction.user.id)

        except Exception as e:
            # Falls das Löschen oben fehlschlug, wenigstens sauber abschließen
            try:
                await interaction.followup.send("Klappt nit lol 🤷", ephemeral=True)
            except Exception:
                pass
            logger.error("Hivemind ERROR von %s (ID: %s): %s",
                         interaction.user.name, interaction.user.id, e)


# -------------------- Cog-Setup --------------------


async def setup(bot: commands.Bot):
    """Fügt das Hivemind-Cog dem Bot hinzu."""
    await bot.add_cog(Hivemind(bot, bot.json_model))
