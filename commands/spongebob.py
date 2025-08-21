import logging
import discord
import random
from discord import app_commands
from discord.ext import commands

# Logger-Setup
logger = logging.getLogger("ZicklaaBotRewrite.Spongebob")


class Spongebob(commands.Cog):
    """Cog: /sponge & /randomsponge – Wandelt Text in Spongebob-Case um."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- /sponge ----------------
    @app_commands.command(
        name="sponge",
        description="Wandelt Text in abwechselnd groß/klein geschriebenen Spongebob-Text um."
    )
    @app_commands.describe(
        text="Der Text, der 'gesponged' werden soll."
    )
    async def sponge(self, interaction: discord.Interaction, text: str):
        try:
            # abwechselnd groß/klein schreiben
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
            logger.info("Spongebob-Text gepostet für %s (ID: %s)",
                        interaction.user, interaction.user.id)

        except Exception as e:
            await interaction.response.send_message(
                "🤷 Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: sponge()",
                ephemeral=True
            )
            logger.error("Fehler bei /sponge von %s (ID: %s): %s",
                         interaction.user, interaction.user.id, e)

    # ---------------- /randomsponge ----------------
    @app_commands.command(
        name="randomsponge",
        description="Wandelt Text in zufällig groß/klein geschriebenen Spongebob-Text um."
    )
    @app_commands.describe(
        text="Der Text, der 'random gesponged' werden soll."
    )
    async def randomsponge(self, interaction: discord.Interaction, text: str):
        try:
            # zufällige Groß-/Kleinschreibung
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
            logger.info("Random-Spongebob-Text gepostet für %s (ID: %s)",
                        interaction.user, interaction.user.id)

        except Exception as e:
            await interaction.response.send_message(
                "🤷 Irgendwas klappt nedde. Scheiß Zicklaa zsamme gschwind. Hint: randomsponge()",
                ephemeral=True
            )
            logger.error("Fehler bei /randomsponge von %s (ID: %s): %s",
                         interaction.user, interaction.user.id, e)


# ---------------- Setup ----------------
async def setup(bot: commands.Bot):
    """Fügt das Spongebob-Cog dem Bot hinzu."""
    await bot.add_cog(Spongebob(bot))
