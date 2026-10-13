"""/roll – würfelt einen oder mehrere Würfel; /coinflip – Münzwurf."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError
from utils.helpers import NO_MENTIONS

MAX_WUERFE = 20  # maximale Anzahl Würfe gleichzeitig
MIN_ZAHL = 1     # keine 0 oder negativen Werte

WUERFEL_ICON = "https://upload.wikimedia.org/wikipedia/commons/7/7c/Cima_da_Conegliano%2C_God_the_Father.jpg"


class Roll(BaseCog):
    """Cog: /roll & /coinflip."""

    @app_commands.command(
        name="roll",
        description="Würfelt eine Zahl oder mehrere Würfel (z. B. 6, oder 3d20).",
    )
    @app_commands.describe(
        anzahl="Anzahl Würfe (z. B. 3 für 3 Würfe, optional)",
        seiten="Seiten pro Würfel (z. B. 20 für W20 oder 6 für W6)",
    )
    async def roll(self, interaction: discord.Interaction, anzahl: int = 1, seiten: int = 6):
        """Ohne Argumente 1d6; sonst <anzahl> Würfel mit <seiten> Seiten."""
        if anzahl < MIN_ZAHL or seiten < MIN_ZAHL:
            raise UserError(f"❌ Zahl(en) zu klein. Mindestens {MIN_ZAHL}.")
        if anzahl > MAX_WUERFE:
            raise UserError(f"❌ Maximal {MAX_WUERFE} Würfe erlaubt.")

        wuerfe = [random.randint(1, seiten) for _ in range(anzahl)]
        dice = f"{anzahl}d{seiten}"

        # Ein Wurf -> kurze Textantwort, mehrere -> Embed mit Einzelergebnissen und Summe
        if anzahl == 1:
            await interaction.response.send_message(
                f"🎲 Ergebnis: **{wuerfe[0]}** ({dice})", allowed_mentions=NO_MENTIONS
            )
        else:
            embed = discord.Embed(title="🎲 Würfelwurf", description=dice, color=0x00FF00)
            embed.set_author(name="Magische Würfel", icon_url=WUERFEL_ICON)
            embed.add_field(
                name="Einzelergebnisse",
                value="\n".join(f"Wurf {i}: {wurf}" for i, wurf in enumerate(wuerfe, start=1)),
                inline=False,
            )
            embed.add_field(name="Gesamtergebnis", value=str(sum(wuerfe)), inline=False)
            await interaction.response.send_message(embed=embed, allowed_mentions=NO_MENTIONS)

        self.log("Rolled", interaction, dice=dice, results=wuerfe, total=sum(wuerfe))

    @app_commands.command(name="coinflip", description="Wirft eine Münze (Kopf oder Zahl).")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(("Kopf", "Zahl"))
        await interaction.response.send_message(f"🪙 **{result}!**", allowed_mentions=NO_MENTIONS)
        self.log("Coinflip", interaction, result=result)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roll(bot))
