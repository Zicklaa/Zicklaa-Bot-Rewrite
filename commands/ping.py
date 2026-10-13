"""/ping – zeigt die aktuelle Latenz des Bots."""

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog


class Ping(BaseCog):
    """Cog: /ping – Latenz als farbiges Embed."""

    @app_commands.command(
        name="ping",
        description="Zeigt die aktuelle Latenz des Bots.",
        extras={"error": "❌ Konnte Ping-Status nicht abrufen."},
    )
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)

        # Grün = schnell, Gelb = geht so, Rot = langsam
        if latency < 150:
            color = discord.Color.green()
        elif latency < 300:
            color = discord.Color.yellow()
        else:
            color = discord.Color.red()

        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Die aktuelle Latenz beträgt **{latency} ms**.",
            color=color,
            timestamp=interaction.created_at,
        )
        embed.set_footer(
            text=f"Geprüft von {interaction.user}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        self.log("Command executed", interaction, latency=latency)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
