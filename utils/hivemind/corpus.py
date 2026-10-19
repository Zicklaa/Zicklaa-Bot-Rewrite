"""Korpus-Datenbank: alle geladenen Nachrichten + Lade-Fortschritt pro Channel."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY,          -- Message-ID (Zeitpunkt steckt im Snowflake)
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    content TEXT NOT NULL            -- ungefiltert; gefiltert wird erst beim Bauen
);
CREATE TABLE IF NOT EXISTS channels(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    last_id INTEGER NOT NULL DEFAULT 0,   -- bis hierhin vollständig geladen
    messages INTEGER NOT NULL DEFAULT 0,  -- davon gespeichert (ohne Bots/Systemnachrichten)
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS legacy_lines(text TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value) WITHOUT ROWID;
"""


def open_corpus(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    db.executescript(SCHEMA)
    return db
