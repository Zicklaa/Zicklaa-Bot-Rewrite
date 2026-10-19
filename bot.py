"""Zicklaa Bot Rewrite – Einstiegspunkt.

Richtet Logging, Datenbank und Hivemind-Modell ein, lädt alle Cogs aus ``commands/``
und registriert die Slash-Commands auf den erlaubten Guilds.
"""

import asyncio
import logging
import os
import random
import re
import sqlite3
import threading
import time
from logging.handlers import TimedRotatingFileHandler

import aiohttp
import discord
from discord.ext import commands

from utils.hivemind.model import MODEL_DB, HivemindModel, install_model
from utils.logging_helper import LOGGER_NAME, log_event
from utils.settings import BASE_DIR, DB_FILE, GUILD_IDS, LOG_FILE

# -------------------- Konfiguration --------------------

TOKEN = os.environ["DISCORD_TOKEN"]

# Sekunden, die zwischen zwei Prefix-Commands eines Users liegen müssen
COMMAND_COOLDOWN = 2

# Autoresponses: Schlüsselwort -> Funktion, die aus dem (kleingeschriebenen) Text die Antwort baut
TRIGGERS = {
    "crazy": lambda c: c.replace("crazy", "***normal***"),
    "kult": lambda _: "***KEIN KULT***",
    # "hallo": lambda _: "Hallo!",
    # "lol": lambda _: "xD",
    # "xd": lambda _: "lol",
    # "uff": lambda _: "uff",
    "gumo": lambda _: "GuMo",
    "brazy": lambda c: c.replace("brazy", "***banal***"),
    "halt echt": lambda c: c.replace("halt echt", "***alt hecht***"),
}

intents = discord.Intents.default()
intents.message_content = True

# -------------------- Logging --------------------


def create_logger() -> logging.Logger:
    """Erstellt den Bot-Logger mit täglich rotierenden Logfiles."""
    # Konsole: alles ab INFO (auch Meldungen von discord.py)
    logging.basicConfig(level=logging.INFO)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=5)
    handler.setFormatter(
        logging.Formatter("%(asctime)s::%(name)s::%(funcName)s::%(levelname)s - %(message)s")
    )
    logger.addHandler(handler)
    return logger


logger = create_logger()

# -------------------- Bot-Klasse --------------------


class ZicklaaBotRewrite(commands.Bot):
    """Bot mit geteilter Datenbank, HTTP-Session und Hivemind-Modell für alle Cogs."""

    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned_or("+"), intents=intents)
        self.db = sqlite3.connect(DB_FILE)
        self.create_tables()
        # Generieren läuft in Worker-Threads, der Austausch nach einem Rebuild auch → Lock
        self._hivemind_lock = threading.Lock()
        self.hivemind = self.load_hivemind()
        # Gemeinsame HTTP-Session für alle Cogs (wird in setup_hook erstellt)
        self.session: aiohttp.ClientSession | None = None
        # user_id -> Zeitpunkt des letzten Prefix-Commands
        self.last_command: dict[int, float] = {}

    # ---------- Daten ----------

    @staticmethod
    def load_hivemind() -> HivemindModel | None:
        """Öffnet das Hivemind-Modell (None, solange noch keins gebaut wurde)."""
        if not MODEL_DB.exists():
            log_event(logger, logging.WARNING, "Bot", "hivemind_missing", path=MODEL_DB)
            return None
        model = HivemindModel(MODEL_DB)
        log_event(logger, logging.INFO, "Bot", "hivemind_loaded", vocab=model.meta.get("vocab"))
        return model

    async def hivemind_sentence(self, max_overlap_ratio: float = 0.6) -> str | None:
        """Ein zufälliger Hivemind-Satz (None, wenn kein Modell da ist oder nichts Neues herauskam)."""

        def generate():
            with self._hivemind_lock:
                return self.hivemind.sentence(max_overlap_ratio) if self.hivemind else None

        return await asyncio.to_thread(generate)

    async def install_hivemind(self, build_path) -> list:
        """Tauscht das Modell gegen ein frisch gebautes aus; das alte wandert ins Archiv."""

        def swap():
            # Erst prüfen, dann tauschen – ein kaputter Build darf das laufende Modell nicht ersetzen
            candidate = HivemindModel(build_path)
            try:
                if candidate.sentence() is None:
                    raise RuntimeError("Neues Modell liefert keine Sätze")
            finally:
                candidate.close()
            with self._hivemind_lock:
                if self.hivemind:
                    self.hivemind.close()
                    self.hivemind = None
                try:
                    return install_model(build_path)
                finally:
                    self.hivemind = self.load_hivemind()

        return await asyncio.to_thread(swap)

    def create_tables(self) -> None:
        """Erstellt notwendige Tabellen in der Datenbank, falls nicht vorhanden."""
        try:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS reminders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    reminder_text TEXT,
                    reminder_time INTEGER,
                    channel INTEGER,
                    message_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS wishlist(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    wishtext TEXT,
                    ts TEXT
                );
                CREATE TABLE IF NOT EXISTS favs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_id INTEGER,
                    name TEXT,
                    channel_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS stars(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER
                );
                """
            )
            # Migration: parent_id kam später zu den Remindern dazu
            columns = [row[1] for row in self.db.execute("PRAGMA table_info(reminders)")]
            if "parent_id" not in columns:
                self.db.execute("ALTER TABLE reminders ADD COLUMN parent_id INTEGER")
            self.db.commit()
        except sqlite3.Error as e:
            log_event(logger, logging.ERROR, "Bot", "create_tables_failed", error=e, exc_info=True)

    # ---------- Start & Stop ----------

    async def setup_hook(self) -> None:
        """Lädt alle Cogs und synchronisiert die Slash-Commands."""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))

        for file in sorted((BASE_DIR / "commands").glob("*.py")):
            if file.name.startswith("_"):
                continue
            try:
                await self.load_extension(f"commands.{file.stem}")
            except Exception as e:
                # Ein kaputtes Cog soll nicht den ganzen Bot am Start hindern
                print(f"Cog {file.stem} konnte nicht geladen werden: {e}")
                log_event(logger, logging.ERROR, "Bot", "cog_load_failed", extension=file.stem, error=e, exc_info=True)

        await self.sync_commands()

    async def sync_commands(self) -> dict[int, int]:
        """Registriert alle Slash-Commands nur auf den erlaubten Guilds.

        Die Commands bleiben im Speicher global registriert (damit ein Cog-Reload sofort
        greift) und werden nur zum Synchronisieren kurz in die Guilds kopiert.
        Gibt ``{guild_id: Anzahl Commands}`` zurück.
        """
        result = {}
        for gid in GUILD_IDS:
            guild = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild)
            result[gid] = len(await self.tree.sync(guild=guild))
            # Lokale Kopie wieder entfernen – Aufrufe fallen auf die globalen Commands zurück
            self.tree.clear_commands(guild=guild)
            log_event(logger, logging.INFO, "Bot", "slash_commands_synced", guild=gid, command_count=result[gid])

        # Bei Discord selbst sollen keine globalen Commands registriert sein
        await self.http.bulk_upsert_global_commands(self.application_id, [])
        log_event(logger, logging.INFO, "Bot", "slash_commands_cleared_global")
        return result

    async def close(self) -> None:
        """Räumt Session und Datenbank beim Beenden auf."""
        if self.session and not self.session.closed:
            await self.session.close()
        await super().close()
        self.db.close()
        if self.hivemind:
            self.hivemind.close()


# -------------------- Bot-Instanz --------------------

bot = ZicklaaBotRewrite()

# -------------------- Events & Checks --------------------


@bot.event
async def on_ready():
    """Wird ausgeführt, wenn der Bot bereit ist."""
    log_event(logger, logging.INFO, "Bot", "startup_complete")


@bot.check
async def is_on_cooldown(ctx: commands.Context) -> bool:
    """Globaler Cooldown für alle Prefix-/Hybrid-Commands."""
    now = time.time()
    if now - bot.last_command.get(ctx.author.id, 0) <= COMMAND_COOLDOWN:
        return False
    bot.last_command[ctx.author.id] = now
    return True


@bot.event
async def on_message(message: discord.Message):
    """Verarbeitet Prefix-Commands und antwortet mit kleiner Wahrscheinlichkeit auf Schlüsselwörter."""
    # Bots (auch der Bot selbst) werden komplett ignoriert
    if message.author.bot:
        return

    # 1) Immer zuerst Commands verarbeiten
    await bot.process_commands(message)

    # 2) War es ein Command (Prefix oder Mention), gibt es keine Autoresponse
    if message.content.startswith(("+", f"<@{bot.user.id}>", f"<@!{bot.user.id}>")):
        return

    # 3) Autoresponse nur mit der konfigurierten Wahrscheinlichkeit
    if random.random() >= float(os.environ["SECRET_PROBABILITY"]):
        return

    content = message.content.lower()
    trigger = next((t for t in TRIGGERS if t in content), None)
    if trigger:
        response = TRIGGERS[trigger](content)
    elif re.search(r"\bdanke\b", content):
        trigger, response = "danke", "Bitte!"
    else:
        return

    await message.reply(response)
    log_event(
        logger, logging.DEBUG, "Bot", "auto_response",
        message.author, message.author.id, trigger=trigger, response=response,
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Fehlerbehandlung für Prefix-Commands ohne eigenes Cog (Cogs: siehe BaseCog)."""
    if hasattr(ctx.command, "on_error"):
        return
    if ctx.cog and ctx.cog.has_error_handler():
        return

    error = getattr(error, "original", error)
    if isinstance(error, commands.CommandNotFound):
        return

    command = ctx.command.qualified_name if ctx.command else None
    if isinstance(error, commands.CheckFailure):
        log_event(
            logger, logging.WARNING, "Bot", "command_check_failed",
            ctx.author, ctx.author.id, command=command, error=error,
        )
    else:
        log_event(
            logger, logging.ERROR, "Bot", "command_error",
            ctx.author, ctx.author.id, command=command, error=error, exc_info=error,
        )


# -------------------- Main --------------------


async def main():
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
