"""Admin-Commands (nur Bot-Owner): /load, /unload, /reload, /sync."""

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, owner_only

COMMANDS_DIR = Path(__file__).parent
EXTENSION_HINT = "Name des Cogs (z.B. fav, chat, remindme)"


def normalize_ext(name: str) -> str:
    """Macht aus 'fav', 'fav.py' oder 'commands.fav' immer 'commands.fav'."""
    name = (name or "").strip().removesuffix(".py")
    return name if not name or name.startswith("commands.") else f"commands.{name}"


def available_extensions() -> list[str]:
    """Alle ladbaren Cogs im commands-Ordner, z. B. ['admin', 'buli', …]."""
    return sorted(f.stem for f in COMMANDS_DIR.glob("*.py") if not f.name.startswith("_"))


class Admin(BaseCog):
    """Cog: Cogs zur Laufzeit laden/entladen und Slash-Commands synchronisieren."""

    async def _ext_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Schlägt Cog-Namen vor (Anzeige kurz, Wert vollqualifiziert)."""
        current = (current or "").lower()
        return [
            app_commands.Choice(name=name, value=f"commands.{name}")
            for name in available_extensions()
            if current in name.lower()
        ][:25]  # Discord-Limit

    async def _change_extension(self, interaction: discord.Interaction, extension: str, action: str):
        """Gemeinsame Logik für /load, /unload und /reload."""
        ext = normalize_ext(extension)
        loaded = ext in self.bot.extensions

        try:
            if action == "load" and loaded:
                msg = f"ℹ️ `{ext}` ist bereits geladen."
            elif action == "unload" and not loaded:
                msg = f"ℹ️ `{ext}` ist nicht geladen."
            elif action == "load":
                await self.bot.load_extension(ext)
                msg = f"✅ Cog `{ext}` wurde geladen."
            elif action == "unload":
                await self.bot.unload_extension(ext)
                msg = f"✅ Cog `{ext}` wurde entladen."
            elif loaded:
                await self.bot.reload_extension(ext)
                msg = f"✅ Cog `{ext}` wurde **neu geladen**."
            else:
                # reload eines nicht geladenen Cogs -> einfach laden
                await self.bot.load_extension(ext)
                msg = f"✅ Cog `{ext}` war nicht geladen und wurde jetzt **geladen**."
        except Exception as e:
            self.log(f"{action} failed", interaction, extension=ext, error=e)
            msg = f"❌ Fehler bei `{action}` von `{ext}`: {e}"
        else:
            self.log(f"{action} done", interaction, extension=ext, result=msg)

        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="load", description="Lädt ein Cog (nur für Bot-Owner).")
    @app_commands.describe(extension=EXTENSION_HINT)
    @app_commands.autocomplete(extension=_ext_autocomplete)
    @owner_only()
    async def load(self, interaction: discord.Interaction, extension: str):
        await self._change_extension(interaction, extension, "load")

    @app_commands.command(name="unload", description="Entlädt ein Cog (nur für Bot-Owner).")
    @app_commands.describe(extension=EXTENSION_HINT)
    @app_commands.autocomplete(extension=_ext_autocomplete)
    @owner_only()
    async def unload(self, interaction: discord.Interaction, extension: str):
        await self._change_extension(interaction, extension, "unload")

    @app_commands.command(name="reload", description="Lädt ein Cog neu (nur für Bot-Owner).")
    @app_commands.describe(extension=EXTENSION_HINT)
    @app_commands.autocomplete(extension=_ext_autocomplete)
    @owner_only()
    async def reload(self, interaction: discord.Interaction, extension: str):
        await self._change_extension(interaction, extension, "reload")

    @app_commands.command(
        name="sync",
        description="Synchronisiert Slash-Commands (nur für Bot-Owner).",
        extras={"error": "❌ Fehler beim Synchronisieren."},
    )
    @owner_only("❌ Nicht erlaubt.")
    async def sync(self, interaction: discord.Interaction):
        """Nötig, wenn sich Namen/Parameter von Commands geändert haben."""
        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.sync_commands()
        await interaction.followup.send(
            f"✅ Slash-Commands für {len(synced)} Guild(s) synchronisiert.", ephemeral=True
        )
        self.log("Commands synced", interaction, guilds=synced)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
