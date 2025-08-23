import logging
import discord
import random
from discord import app_commands
from discord.ext import commands
from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Spongebob")


class Spongebob(commands.Cog):
    """Cog: /sponge & /randomsponge – Wandelt Text in Spongebob-Case um."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- /sponge ----------------
    @app_commands.command(
        name="sponge",
        description="Wandelt Text in abwechselnd groß/klein geschriebenen Spongebob-Text um.",
    )
    @app_commands.describe(
        text="Der Text, der 'gesponged' werden soll.",
    )
    async def sponge(self, interaction: discord.Interaction, text: str):
        try:
            spongified_text = ""
            upper = True
            for char in text:
                spongified_text += char.upper() if upper else char.lower()
                if char != " ":
                    upper = not upper

            embed = discord.Embed(
                description=f"**{spongified_text}**",
                color=0xFFCC00,
            )
            embed.set_author(
                name="Spongebob",
                icon_url="https://cdn.discordapp.com/emojis/658729208515788810.gif",
            )
            embed.set_footer(text=f"Für {interaction.user.display_name}")

            await interaction.response.send_message(embed=embed)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Sponge text sent",
                interaction.user,
                interaction.user.id,
                command="/sponge",
            )
        except Exception as e:
            await interaction.response.send_message(
                "🤷 Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: sponge()",
                ephemeral=True
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Sponge failed",
                interaction.user,
                interaction.user.id,
                command="/sponge",
                error=e,
                exc_info=True,
            )

    # ---------------- /randomsponge ----------------
    @app_commands.command(
        name="randomsponge",
        description="Wandelt Text in zufällig groß/klein geschriebenen Spongebob-Text um.",
    )
    @app_commands.describe(
        text="Der Text, der 'random gesponged' werden soll.",
    )
    async def randomsponge(self, interaction: discord.Interaction, text: str):
        try:
            spongified_text = "".join(random.choice((str.upper, str.lower))(c) for c in text)

            embed = discord.Embed(
                description=f"**{spongified_text}**",
                color=0xFFCC00,
            )
            embed.set_author(
                name="Spongebob",
                icon_url="https://cdn.discordapp.com/emojis/658729208515788810.gif",
            )
            embed.set_footer(text=f"Für {interaction.user.display_name}")

            await interaction.response.send_message(embed=embed)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Random sponge text sent",
                interaction.user,
                interaction.user.id,
                command="/randomsponge",
            )
        except Exception as e:
            await interaction.response.send_message(
                "🤷 Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: randomsponge()",
                ephemeral=True
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Random sponge failed",
                interaction.user,
                interaction.user.id,
                command="/randomsponge",
                error=e,
                exc_info=True,
            )


# ---------------- Setup ----------------
async def setup(bot: commands.Bot):
    """Fügt das Spongebob-Cog dem Bot hinzu."""
    await bot.add_cog(Spongebob(bot))
