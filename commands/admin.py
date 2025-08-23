import logging
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Admin")

# Nur dieser User darf load/unload/reload/sync ausführen
OWNER_ID = 288413759117066241

# Deine festen Guilds für gezieltes Sync (entspricht deinem bot.py-Block)
GUILD_IDS: tuple[int, ...] = (
    567050382920908801,
    122739462210846721,
)


def _normalize_ext(name: str) -> str:
    """
    Nimmt Eingaben wie 'fav' oder 'commands.fav' und liefert immer 'commands.fav'.
    Entfernt .py-Endung, trims whitespace.
    """
    n = (name or "").strip().removesuffix(".py")
    if not n:
        return n
    return n if n.startswith("commands.") else f"commands.{n}"


def _available_extensions() -> list[str]:
    """
    Sucht im ./commands Ordner nach *.py (ohne _*), gibt Liste wie 'commands.remindme' zurück.
    """
    p = Path(__file__).resolve().parent  # .../commands/admin.py
    commands_dir = p.parent / "commands"
    if not commands_dir.exists():
        return []
    exts: list[str] = []
    for f in commands_dir.glob("*.py"):
        if f.name.startswith("_"):
            continue
        exts.append(f"commands.{f.stem}")
    return sorted(exts)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- Autocomplete-Helper ----
    async def _ext_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = (current or "").lower()
        choices = []
        for ext in _available_extensions():
            # nur die Endkomponente anzeigen (freundlicher), value bleibt vollqualifiziert
            label = ext.split(".", 1)[1] if ext.startswith("commands.") else ext
            if current_lower in label.lower():
                choices.append(app_commands.Choice(name=label, value=ext))
            if len(choices) >= 25:  # Discord-Limit
                break
        return choices

    # ---------------- /load ----------------
    @app_commands.command(name="load", description="Lädt ein Cog (nur für Bot-Owner).")
    @app_commands.describe(extension="Name des Cogs (z.B. fav, chat, remindme)")
    @app_commands.autocomplete(extension=_ext_autocomplete)
    async def load(self, interaction: discord.Interaction, extension: str):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ Du bist nicht berechtigt, diesen Befehl zu nutzen.", ephemeral=True
            )
            log_event(
                logger,
                logging.WARNING,
                self.__class__.__name__,
                "Unauthorized load",
                interaction.user,
                interaction.user.id,
                command="/load",
                extension=extension,
            )
            return

        ext = _normalize_ext(extension)
        try:
            if ext in self.bot.extensions:
                await interaction.response.send_message(
                    f"ℹ️ `{ext}` ist bereits geladen.", ephemeral=True
                )
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "Load skipped",
                    interaction.user,
                    interaction.user.id,
                    command="/load",
                    extension=ext,
                )
                return

            await self.bot.load_extension(ext)
            await interaction.response.send_message(
                f"✅ Cog `{ext}` wurde geladen.", ephemeral=True
            )
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Cog loaded",
                interaction.user,
                interaction.user.id,
                command="/load",
                extension=ext,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Laden von `{ext}`: {e}", ephemeral=True
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Load failed",
                interaction.user,
                interaction.user.id,
                command="/load",
                extension=ext,
                error=e,
                exc_info=True,
            )

    # ---------------- /unload ----------------
    @app_commands.command(name="unload", description="Entlädt ein Cog (nur für Bot-Owner).")
    @app_commands.describe(extension="Name des Cogs (z.B. fav, chat, remindme)")
    @app_commands.autocomplete(extension=_ext_autocomplete)
    async def unload(self, interaction: discord.Interaction, extension: str):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ Du bist nicht berechtigt, diesen Befehl zu nutzen.", ephemeral=True
            )
            log_event(
                logger,
                logging.WARNING,
                self.__class__.__name__,
                "Unauthorized unload",
                interaction.user,
                interaction.user.id,
                command="/unload",
                extension=extension,
            )
            return

        ext = _normalize_ext(extension)
        try:
            if ext not in self.bot.extensions:
                await interaction.response.send_message(
                    f"ℹ️ `{ext}` ist nicht geladen.", ephemeral=True
                )
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "Unload skipped",
                    interaction.user,
                    interaction.user.id,
                    command="/unload",
                    extension=ext,
                )
                return

            await self.bot.unload_extension(ext)
            await interaction.response.send_message(
                f"✅ Cog `{ext}` wurde entladen.", ephemeral=True
            )
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Cog unloaded",
                interaction.user,
                interaction.user.id,
                command="/unload",
                extension=ext,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Entladen von `{ext}`: {e}", ephemeral=True
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Unload failed",
                interaction.user,
                interaction.user.id,
                command="/unload",
                extension=ext,
                error=e,
                exc_info=True,
            )

    # ---------------- /reload ----------------
    @app_commands.command(name="reload", description="Lädt ein Cog neu (nur für Bot-Owner).")
    @app_commands.describe(extension="Name des Cogs (z.B. fav, chat, remindme)")
    @app_commands.autocomplete(extension=_ext_autocomplete)
    async def reload(self, interaction: discord.Interaction, extension: str):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ Du bist nicht berechtigt, diesen Befehl zu nutzen.", ephemeral=True
            )
            log_event(
                logger,
                logging.WARNING,
                self.__class__.__name__,
                "Unauthorized reload",
                interaction.user,
                interaction.user.id,
                command="/reload",
                extension=extension,
            )
            return

        ext = _normalize_ext(extension)
        try:
            # falls nicht geladen → erst laden, sonst reload schlägt fehl
            if ext not in self.bot.extensions:
                await self.bot.load_extension(ext)
                msg = f"✅ Cog `{ext}` war nicht geladen und wurde jetzt **geladen**."
            else:
                await self.bot.reload_extension(ext)
                msg = f"✅ Cog `{ext}` wurde **neu geladen**."

            await interaction.response.send_message(msg, ephemeral=True)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Cog reloaded",
                interaction.user,
                interaction.user.id,
                command="/reload",
                extension=ext,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Reload von `{ext}`: {e}", ephemeral=True
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Reload failed",
                interaction.user,
                interaction.user.id,
                command="/reload",
                extension=ext,
                error=e,
                exc_info=True,
            )

    # ---------------- /sync ----------------
    @app_commands.command(
        name="sync",
        description="Synchronisiert Slash-Commands (nur für Bot-Owner)."
    )
    async def sync(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Nicht erlaubt.", ephemeral=True)
            log_event(
                logger,
                logging.WARNING,
                self.__class__.__name__,
                "Unauthorized sync",
                interaction.user,
                interaction.user.id,
                command="/sync",
            )
            return

        try:
            # 1) Guilds synchronisieren
            for gid in GUILD_IDS:
                guild = discord.Object(id=int(gid))
                # Wichtig: globale (in-memory) Commands in diese Guild kopieren
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "Guild synced",
                    interaction.user,
                    interaction.user.id,
                    command="/sync",
                    guild_id=gid,
                    commands=len(synced),
                )

            # 2) Globale Commands beim API-Server entfernen
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync(guild=None)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Global commands cleared",
                interaction.user,
                interaction.user.id,
                command="/sync",
            )
            
            await interaction.response.send_message(
                f"✅ Slash-Commands für {len(GUILD_IDS)} Guild(s) synchronisiert.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message("❌ Fehler beim Synchronisieren.", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Sync failed",
                interaction.user,
                interaction.user.id,
                command="/sync",
                error=e,
                exc_info=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
