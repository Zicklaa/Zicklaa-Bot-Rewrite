"""Gemeinsame Basis für alle Cogs und Views.

Statt in jedem Command try/except + Logging zu wiederholen, gilt überall:
- Erfolg loggen:           ``self.log("Aktion", interaction, key=value)``
- Erwartbarer Fehler:      ``raise UserError("❌ Text für den User")``
- Unerwarteter Fehler:     einfach durchfallen lassen – BaseCog loggt ihn und
                           antwortet mit dem ``extras={"error": "…"}``-Text des Commands.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.settings import OWNER_ID
from utils.logging_helper import LOGGER_NAME, log_event

DEFAULT_ERROR = "Klappt nit lol 🤷"

# -------------------- Fehler & Antworten --------------------


class UserError(app_commands.AppCommandError):
    """Erwartbarer Fehler (falsche Eingabe, falscher Channel, …).

    Der Text wird dem User ephemer angezeigt; geloggt wird nur eine Warnung.
    """


async def reply(interaction: discord.Interaction, content: str | None = None, **kwargs):
    """Antwortet auf eine Interaction – egal, ob schon geantwortet/deferred wurde."""
    if interaction.response.is_done():
        return await interaction.followup.send(content, **kwargs)
    return await interaction.response.send_message(content, **kwargs)


def _describe(source) -> tuple[object | None, str | None]:
    """Zieht (User, Command-Name) aus Interaction, Context oder User."""
    if isinstance(source, discord.Interaction):
        command = source.command
        return source.user, f"/{command.qualified_name}" if command else None
    if isinstance(source, commands.Context):
        command = source.command
        return source.author, f"{source.clean_prefix}{command.qualified_name}" if command else None
    return source, None


# -------------------- Checks --------------------


def owner_only(message: str = "❌ Du bist nicht berechtigt, diesen Befehl zu nutzen."):
    """Slash-Command nur für den Bot-Owner."""

    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            raise UserError(message)
        return True

    return app_commands.check(predicate)


def in_channels(*channel_ids: int, message: str = "Spam woanders, Moruk 🤷"):
    """Slash-Command nur in bestimmten Channels (oder Threads darin)."""

    def predicate(interaction: discord.Interaction) -> bool:
        parent_id = getattr(interaction.channel, "parent_id", None)
        if interaction.channel_id not in channel_ids and parent_id not in channel_ids:
            raise UserError(message)
        return True

    return app_commands.check(predicate)


# -------------------- Cog-Basis --------------------


class BaseCog(commands.Cog):
    """Basisklasse aller Cogs: eigener Logger + einheitliche Fehlerbehandlung."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(f"{LOGGER_NAME}.{type(self).__name__}")

    def log(self, action: str, source=None, /, *, level: int | None = None, error: BaseException | None = None, **details):
        """Loggt ein Ereignis im einheitlichen Format.

        Args:
            action: Kurzbeschreibung, z. B. ``"Image sent"``.
            source: Interaction, Context oder User – liefert User und Command-Name.
            level: Logging-Level (Standard: INFO, bei ``error`` ERROR).
            error: Exception; wird mit Traceback geloggt.
            **details: Weitere Key-Value-Details.
        """
        user, command = _describe(source)
        # Ohne User-Objekt (z. B. in Events) kann die ID direkt als user_id=… mitgegeben werden
        user_id = details.pop("user_id", getattr(user, "id", None))
        if command:
            details = {"command": command, **details}
        if error is not None:
            details["error"] = error
        log_event(
            self.logger,
            level if level is not None else (logging.ERROR if error else logging.INFO),
            type(self).__name__,
            action,
            user,
            user_id,
            exc_info=error or False,
            **details,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Fängt alle Fehler aus Slash-Commands dieses Cogs."""
        error = getattr(error, "original", error)
        if isinstance(error, UserError):
            self.log("Rejected", interaction, level=logging.WARNING, reason=error)
            text = str(error)
        elif isinstance(error, app_commands.CheckFailure):
            self.log("Check failed", interaction, level=logging.WARNING, reason=error)
            text = "❌ Das darfst du hier nicht."
        else:
            self.log("Command failed", interaction, error=error)
            extras = getattr(interaction.command, "extras", None) or {}
            text = extras.get("error", DEFAULT_ERROR)
        try:
            await reply(interaction, text, ephemeral=True)
        except discord.HTTPException:
            pass  # Interaction abgelaufen – der Fehler ist bereits geloggt

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Fängt alle Fehler aus Prefix-/Hybrid-Commands dieses Cogs."""
        error = getattr(error, "original", error)
        if isinstance(error, commands.CheckFailure):
            # z. B. globaler Cooldown oder DM-only -> nur loggen, nicht antworten
            self.log("Check failed", ctx, level=logging.WARNING, reason=error)
            return
        self.log("Command failed", ctx, error=error)
        try:
            await ctx.reply(ctx.command.extras.get("error", DEFAULT_ERROR), ephemeral=True)
        except discord.HTTPException:
            pass


# -------------------- View-Basis --------------------


class BaseView(discord.ui.View):
    """Basisklasse für Views: loggt Fehler in Buttons/Selects und sagt dem User Bescheid."""

    error_text = "❌ Da ist was schiefgelaufen."

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log_event(
            logging.getLogger(f"{LOGGER_NAME}.{type(self).__name__}"),
            logging.ERROR,
            type(self).__name__,
            "View failed",
            interaction.user,
            interaction.user.id,
            item=getattr(item, "label", None) or type(item).__name__,
            error=error,
            exc_info=error,
        )
        try:
            await reply(interaction, self.error_text, ephemeral=True)
        except discord.HTTPException:
            pass
