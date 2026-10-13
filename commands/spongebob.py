"""/sponge & /randomsponge – wandelt Text in Spongebob-Case um."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog

SPONGE_ICON = "https://cdn.discordapp.com/emojis/658729208515788810.gif"


def alternate_case(text: str) -> str:
    """AbWeChSeLnD groß/klein; Leerzeichen zählen nicht mit."""
    out, upper = [], True
    for char in text:
        out.append(char.upper() if upper else char.lower())
        if char != " ":
            upper = not upper
    return "".join(out)


def random_case(text: str) -> str:
    """Jeder Buchstabe zufällig groß oder klein."""
    return "".join(random.choice((str.upper, str.lower))(c) for c in text)


class Spongebob(BaseCog):
    """Cog: /sponge & /randomsponge."""

    async def _send(self, interaction: discord.Interaction, text: str):
        """Schickt den umgewandelten Text als Spongebob-Embed."""
        embed = discord.Embed(description=f"**{text}**", color=0xFFCC00)
        embed.set_author(name="Spongebob", icon_url=SPONGE_ICON)
        embed.set_footer(text=f"Für {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        self.log("Sponge text sent", interaction)

    @app_commands.command(
        name="sponge",
        description="Wandelt Text in abwechselnd groß/klein geschriebenen Spongebob-Text um.",
        extras={"error": "🤷 Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: sponge()"},
    )
    @app_commands.describe(text="Der Text, der 'gesponged' werden soll.")
    async def sponge(self, interaction: discord.Interaction, text: str):
        await self._send(interaction, alternate_case(text))

    @app_commands.command(
        name="randomsponge",
        description="Wandelt Text in zufällig groß/klein geschriebenen Spongebob-Text um.",
        extras={"error": "🤷 Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: randomsponge()"},
    )
    @app_commands.describe(text="Der Text, der 'random gesponged' werden soll.")
    async def randomsponge(self, interaction: discord.Interaction, text: str):
        await self._send(interaction, random_case(text))


async def setup(bot: commands.Bot):
    await bot.add_cog(Spongebob(bot))
