# bot.py
import asyncio
import logging
import os
import random
import re
import sys
import time
import traceback
import json
import sqlite3
import pathlib

from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv

import discord
from discord.ext import commands

import markovify

# -------------------- Konfiguration & Setup --------------------

# .env laden
load_dotenv()

# Token und globale Pfade aus .env holen
TOKEN = os.environ["DISCORD_TOKEN"]
globalPfad = os.environ["globalPfad"]

# Discord-Intents
intents = discord.Intents.default()
intents.message_content = True

# User-Cooldown-Tracking
user_last_command = {}

# -------------------- Logging --------------------


def create_log_file(path: str) -> logging.Logger:
    """Erstellt einen Logger mit rotierenden Logfiles."""
    logger = logging.getLogger("ZicklaaBot")
    logger.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler(
        path, when="midnight", interval=1, backupCount=5)
    formatter = logging.Formatter(
        "%(asctime)s::%(name)s::%(funcName)s::%(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


logger = create_log_file(os.path.join(
    globalPfad, "Old Logs/ZicklaaBotLog.log"))

# -------------------- Datenbank & Modelle --------------------


def json_model():
    """Lädt das Markov-Modell aus einer JSON-Datei."""
    with open(os.path.join(globalPfad, "static/hivemind.json"), encoding="utf-8") as json_file:
        hivemind_json = json.load(json_file)
    model = markovify.Text.from_json(hivemind_json)
    print("hivemind.json loaded")
    return model

# -------------------- Bot-Klasse --------------------


class ZicklaaBotRewrite(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
        self.db = sqlite3.connect(os.path.join(
            globalPfad, "reminder-wishlist.db"))
        self.create_tables()
        self.json_model = json_model()

    def create_tables(self):
        """Erstellt notwendige Tabellen in der Datenbank, falls nicht vorhanden."""
        try:
            cursor = self.db.cursor()
            # Reminders
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    reminder_text TEXT,
                    reminder_time INTEGER,
                    channel INTEGER,
                    message_id INTEGER
                )
            """)
            reminder_columns = [
                x[1] for x in cursor.execute("PRAGMA table_info(reminders)").fetchall()
            ]
            if "parent_id" not in reminder_columns:
                cursor.execute(
                    "ALTER TABLE reminders ADD COLUMN parent_id INTEGER")
            # Wishlist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wishlist(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    wishtext TEXT,
                    ts TEXT
                )
            """)
            # Favs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS favs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_id INTEGER,
                    name TEXT,
                    channel_id INTEGER
                )
            """)
            # Stars
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stars(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER
                )
            """)
        except Exception as e:
            logging.error(f"Fehler beim Erstellen der Tabellen: {e}")

    async def setup_hook(self) -> None:
        """Lädt alle Cogs und synchronisiert Slash-Commands."""
        commands_dir = pathlib.Path(__file__).parent / "commands"
        for file in commands_dir.glob("*.py"):
            if file.name.startswith("_"):
                continue
            ext = f"commands.{file.stem}"
            await self.load_extension(ext)
            logging.info("Extension geladen: %s", ext)

        # Guild-Sync für spezifische Server
        for guild_id in (567050382920908801, 122739462210846721):
            guild = discord.Object(id=guild_id)
            await self.tree.sync(guild=guild)
            logging.info(
                "Slash-Commands für GUILD %s synchronisiert.", guild_id)

        # Global-Sync (alle Server)
        await self.tree.sync()
        logging.info("Slash-Commands global synchronisiert.")

# -------------------- Bot-Instanz --------------------


bot = ZicklaaBotRewrite()

# -------------------- Events & Checks --------------------


@bot.event
async def on_ready():
    """Wird ausgeführt, wenn der Bot bereit ist."""
    print("✅ Bot wurde erfolgreich gestartet!")
    logger.info("=======================Startup=========================")
    remindme = bot.get_cog("RemindMe")
    await remindme.check_reminder()


@bot.check
async def is_on_cooldown(ctx):
    """Globaler Cooldown für alle Commands."""
    global user_last_command
    if str(ctx.author) not in user_last_command:
        user_last_command[str(ctx.author)] = 10
    elapsed = time.time() - user_last_command[str(ctx.author)]
    if elapsed > 2:
        user_last_command[str(ctx.author)] = time.time()
        return True
    return False


@bot.event
async def on_message(message):
    """Reagiert auf bestimmte Nachrichten mit zufälliger Wahrscheinlichkeit."""
    if message.author.id == 1407707429176873093:
        return

    if random.random() <= float(os.environ["SECRET_PROBABILITY"]):
        await bot.process_commands(message)
        return

    content = message.content.lower()

    triggers: dict[str, callable] = {
        "crazy": lambda c: c.replace("crazy", "***normal***"),
        "kult": lambda _: "***KEIN KULT***",
        "hi": lambda _: "Hallo!",
        "lol": lambda _: "xD",
        "xd": lambda _: "lol",
        "uff": lambda _: "uff",
        "gumo": lambda _: "GuMo",
        "brazy": lambda c: c.replace("brazy", "***banal***"),
        "halt echt": lambda c: c.replace("halt echt", "***alt hecht***"),
    }

    response = None
    for trigger, func in triggers.items():
        if trigger in content:
            response = func(content)
            break
    else:
        if re.search(r"\bdanke\b", content) is not None:
            response = "Bitte!"

    if response:
        await message.reply(response)
        logger.debug("Auto-response '%s' auf Nachricht von %s",
                     response, message.author)


@bot.event
async def on_command_error(ctx, error):
    """Fehlerbehandlung für Commands."""
    if hasattr(ctx.command, "on_error"):
        return
    cog = ctx.cog
    if cog and cog._get_overridden_method(cog.cog_command_error) is not None:
        return

    ignored = (commands.CommandNotFound,)
    error = getattr(error, "original", error)

    if isinstance(error, ignored):
        return

    if isinstance(error, commands.errors.CheckFailure):
        logger.error(f"User {str(ctx.author)} triggered: {error}")
        return
    else:
        print(f"Ignoring exception in command {ctx.command}:", file=sys.stderr)
        traceback.print_exception(
            type(error), error, error.__traceback__, file=sys.stderr
        )

# -------------------- Main --------------------


async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
