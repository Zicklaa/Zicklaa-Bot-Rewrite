"""Korpus-Datenbank: die Texte aller geladenen Nachrichten + Lade-Fortschritt pro Channel.

Datenschutz: Pro Nachricht wird ausschließlich der Text gespeichert – kein Autor, kein
Channel, kein Zeitpunkt, keine Message-ID. Der Text ist zugleich der Primärschlüssel,
d. h. es gibt auch keine Einfügereihenfolge, aus der man etwas ableiten könnte, und
gleiche Texte liegen nur einmal vor.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(content TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS channels(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    last_id INTEGER NOT NULL DEFAULT 0,   -- bis hierhin vollständig geladen (nur fürs Fortsetzen)
    messages INTEGER NOT NULL DEFAULT 0,  -- Anzahl gespeicherter Texte (für die Statistik)
    updated_at INTEGER
);
-- Altbestand: Zeilen aus den Text-Dumps des alten Bots (2022/2024), einmalig übernommen
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
