import logging
import random
import discord
from discord import app_commands
from discord.ext import commands
from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Roll")

# Konstante Limits
MAX_WUERFE = 20  # maximal Anzahl Würfe gleichzeitig
MIN_ZAHL = 1     # keine 0 oder negativen Werte


class Roll(commands.Cog):
    """Cog: /roll – würfelt Zahlen oder klassische RPG-Würfel; /coinflip – Münzwurf."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------- /roll --------------------
    @app_commands.command(
        name="roll",
        description="Würfelt eine Zahl oder mehrere Würfel (z. B. 6, oder 3d20).",
    )
    @app_commands.describe(
        anzahl="Anzahl Würfe (z. B. 3 für 3 Würfe, optional)",
        seiten="Seiten pro Würfel (z. B. 20 für W20 oder 6 für W6)",
    )
    async def roll(
        self,
        interaction: discord.Interaction,
        anzahl: int = 1,
        seiten: int = 6
    ):
        """
        Slash: /roll
        - ohne Argumente: Standard = 1d6
        - mit 1 Zahl: würfelt von 1..N
        - mit 2 Zahlen: würfelt N Würfel mit X Seiten
        """
        try:
            if anzahl < MIN_ZAHL or seiten < MIN_ZAHL:
                await interaction.response.send_message(
                    f"❌ Zahl(en) zu klein. Mindestens {MIN_ZAHL}.",
                    ephemeral=True
                )
                log_event(
                    logger,
                    logging.WARNING,
                    self.__class__.__name__,
                    "Invalid roll input",
                    interaction.user,
                    interaction.user.id,
                    command="/roll",
                    dice=f"{anzahl}d{seiten}",
                )
                return

            if anzahl > MAX_WUERFE:
                await interaction.response.send_message(
                    f"❌ Maximal {MAX_WUERFE} Würfe erlaubt.",
                    ephemeral=True
                )
                log_event(
                    logger,
                    logging.WARNING,
                    self.__class__.__name__,
                    "Too many rolls",
                    interaction.user,
                    interaction.user.id,
                    command="/roll",
                    dice=f"{anzahl}d{seiten}",
                )
                return

            if anzahl == 1:
                wurf = random.randint(1, seiten)
                await interaction.response.send_message(
                    f"🎲 Ergebnis: **{wurf}** (1d{seiten})",
                    allowed_mentions=discord.AllowedMentions.none()
                )
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "Single roll",
                    interaction.user,
                    interaction.user.id,
                    command="/roll",
                    result=wurf,
                    sides=seiten,
                )
                return

            wuerfe = [random.randint(1, seiten) for _ in range(anzahl)]
            gesamt = sum(wuerfe)

            embed = discord.Embed(
                title="🎲 Würfelwurf",
                description=f"{anzahl}d{seiten}",
                color=0x00FF00
            )
            embed.set_author(
                name="Magische Würfel",
                icon_url="https://upload.wikimedia.org/wikipedia/commons/7/7c/Cima_da_Conegliano%2C_God_the_Father.jpg",
            )
            ergebnisse = "\n".join(
                f"Wurf {i+1}: {wurf}" for i, wurf in enumerate(wuerfe)
            )
            embed.add_field(
                name="Einzelergebnisse",
                value=ergebnisse,
                inline=False
            )
            embed.add_field(
                name="Gesamtergebnis",
                value=str(gesamt),
                inline=False
            )

            await interaction.response.send_message(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Multiple rolls",
                interaction.user,
                interaction.user.id,
                command="/roll",
                dice=f"{anzahl}d{seiten}",
                results=wuerfe,
                total=gesamt,
            )

        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Command failed",
                interaction.user,
                interaction.user.id,
                command="/roll",
                error=e,
                exc_info=True,
            )

    # -------------------- /coinflip --------------------
    @app_commands.command(
        name="coinflip",
        description="Wirft eine Münze (Kopf oder Zahl).",
    )
    async def coinflip(self, interaction: discord.Interaction):
        """
        Slash: /coinflip
        - Münzwurf, zufälliges Ergebnis „Kopf“ oder „Zahl“.
        """
        try:
            result = random.choice(["Kopf", "Zahl"])
            await interaction.response.send_message(
                f"🪙 **{result}!**",
                allowed_mentions=discord.AllowedMentions.none()
            )
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Coinflip",
                interaction.user,
                interaction.user.id,
                command="/coinflip",
                result=result,
            )
        except Exception as e:
            await interaction.response.send_message("Klappt nit lol 🤷", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Coinflip failed",
                interaction.user,
                interaction.user.id,
                command="/coinflip",
                error=e,
                exc_info=True,
            )


# Standard Setup für discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(Roll(bot))
