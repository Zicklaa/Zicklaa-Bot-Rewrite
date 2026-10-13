"""/wetter & /asciiwetter – Wetterdaten von wttr.in als Bild bzw. ASCII-Art."""

from io import BytesIO
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog

ERROR_TEXT = "Wetter schmetter, sag ich schon immer."
# Werbe-Hinweis, den wttr.in an die Textausgabe hängt
WTTR_AD = "Folgen Sie https://twitter.com/igor_chubin für wttr.in Updates"


class Wetter(BaseCog):
    """Cog: /wetter & /asciiwetter."""

    @app_commands.command(
        name="wetter",
        description="Zeigt das Wetter für einen Ort als Bild.",
        extras={"error": ERROR_TEXT},
    )
    @app_commands.describe(location="Der gewünschte Ort, z.B. Stuttgart")
    async def wetter(self, interaction: discord.Interaction, location: str):
        await interaction.response.defer()

        url = f"https://de.wttr.in/{quote(location)}_m.png"
        async with self.bot.session.get(url) as resp:
            resp.raise_for_status()
            image = await resp.read()

        await interaction.followup.send(file=discord.File(BytesIO(image), "wetter.png"))
        self.log("Weather image sent", interaction, location=location, url=url)

    @app_commands.command(
        name="asciiwetter",
        description="Zeigt das Wetter für einen Ort als ASCII-Art.",
        extras={"error": ERROR_TEXT},
    )
    @app_commands.describe(location="Der gewünschte Ort, z.B. Berlin")
    async def asciiwetter(self, interaction: discord.Interaction, location: str):
        await interaction.response.defer(thinking=True)

        url = f"https://wttr.in/{quote(location)}?n&T&2&lang=de"
        async with self.bot.session.get(url) as resp:
            text = (await resp.text()).replace(WTTR_AD, "")

        # Discord erlaubt max. 2000 Zeichen pro Nachricht
        await interaction.followup.send(f"```\n{text[:1990]}\n```")
        self.log("ASCII weather sent", interaction, location=location)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wetter(bot))
