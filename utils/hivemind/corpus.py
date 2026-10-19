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
CREATE TABLE IF NOT EXISTS legacy_lines(text TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value) WITHOUT ROWID;
"""


def open_corpus(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    _drop_metadata(db)
    db.executescript(SCHEMA)
    return db


def _drop_metadata(db: sqlite3.Connection):
    """Altes Schema (mit ID/Autor/Channel pro Nachricht) auf reine Texte umstellen."""
    columns = [row[1] for row in db.execute("PRAGMA table_info(messages)")]
    if not columns or columns == ["content"]:
        return
    db.execute("ALTER TABLE messages RENAME TO messages_old")
    db.executescript(SCHEMA)
    db.execute("INSERT OR IGNORE INTO messages(content) SELECT content FROM messages_old")
    db.execute("DROP TABLE messages_old")
    db.commit()
    # Gelöschte Seiten physisch überschreiben, damit die Metadaten nicht in der Datei bleiben
    db.execute("VACUUM")
