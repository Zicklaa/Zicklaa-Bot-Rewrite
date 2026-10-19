"""Hivemind-Modell zur Laufzeit: Sätze aus der Markov-Kette in ``model.db``.

Aufbau des Modells (siehe ``build``):
- ``chain2``: Folgewort je 2-Wort-Kontext, kumulierte Häufigkeit als Schlüssel
  → Ziehen nach Häufigkeit ist ein einziger Index-Lookup (``cum > r``)
- ``chain3``: dasselbe für 3-Wort-Kontexte, aber nur dort, wo es mehrere Folgewörter
  gibt. Damit klingen die Sätze grammatischer, ohne einfach ein Original nachzuerzählen.
  Ab wie vielen Folgewörtern der 3er-Kontext genutzt wird, legt der Stil fest.
- Bloom-Filter über alle 5- bis 9-Wort-Folgen der Originale: Sätze, die zu lange
  wörtlich aus einer einzigen Nachricht stammen, werden verworfen (der Mashup-Teil).
"""

import os
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.settings import STATIC_DIR

# -------------------- Pfade --------------------

HIVEMIND_DIR = STATIC_DIR / "hivemind"
CORPUS_DB = HIVEMIND_DIR / "corpus.db"  # gesammelte Nachrichten (wächst inkrementell)
MODEL_DB = HIVEMIND_DIR / "model.db"  # aktives Modell
ARCHIVE_DIR = HIVEMIND_DIR / "archiv"  # ersetzte Modelle
LEGACY_JSON = STATIC_DIR / "hivemind.json"  # altes markovify-Modell, wird beim ersten Rebuild archiviert
ARCHIVE_KEEP = 3  # so viele alte Modelle bleiben im Archiv (je ~300–500 MB)

# -------------------- Satz-Parameter --------------------

BEGIN, END = 0, 1  # reservierte Wort-IDs für Satzanfang/-ende
MIN_WORDS = 5  # kürzere Sätze sind selten lustig und fast immer Originale
MAX_WORDS = 25  # längere Ketten driften ins Unverständliche ab
TRIES = 200  # Versuche pro Satz (ein Versuch kostet < 1 ms)

# Overlap-Prüfung: Fenstergröße = round(ratio * Satzlänge) + 1 (+ Bonus des Stils),
# begrenzt auf die im Bloom-Filter gespeicherten Längen
OVERLAP_NGRAMS = (5, 6, 7, 8, 9)


@dataclass(frozen=True)
class Style:
    label: str
    order3_min_branches: int | None  # None = nur 2er-Kontext (wie das alte markovify)
    overlap_bonus: int  # so viele Wörter mehr am Stück darf ein Satz aus einem Original haben


# Gewichtung: wie stark die Kette auf Grammatik statt auf Zufall setzt
STYLES = {
    "chaos": Style("🌀 Chaos – wilder Wortsalat", None, 0),
    "ausgewogen": Style("⚖️ Ausgewogen – lustig, aber meist sinnvoll", 3, 0),
    "eloquent": Style("🎓 Eloquent – fast schon richtige Sätze", 2, 2),
}
DEFAULT_STYLE = "ausgewogen"

# -------------------- Hashing (identisch in build.py, dort mit numpy) --------------------

MASK = (1 << 64) - 1
FNV_PRIME = 0x100000001B3
GOLDEN = 0x9E3779B97F4A7C15
SALT = 0xD6E8FEB86659FD93


def splitmix64(z: int) -> int:
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return z ^ (z >> 31)


def ngram_hashes(ids: list[int]) -> tuple[int, int]:
    """Zwei unabhängige 64-Bit-Hashes einer Wortfolge (für Double-Hashing im Bloom-Filter)."""
    h = (len(ids) * GOLDEN) & MASK
    for i in ids:
        h = ((h ^ i) * FNV_PRIME) & MASK
    h1 = splitmix64(h)
    return h1, splitmix64(h1 ^ SALT) | 1


class Bloom:
    def __init__(self, data: bytes, bits: int, hashes: int):
        self.data = data
        self.bits = bits
        self.hashes = hashes

    def __contains__(self, ids: list[int]) -> bool:
        h1, h2 = ngram_hashes(ids)
        for i in range(self.hashes):
            pos = ((h1 + i * h2) & MASK) % self.bits
            if not self.data[pos >> 3] >> (pos & 7) & 1:
                return False
        return True


# -------------------- Modell --------------------


class HivemindModel:
    """Read-only-Zugriff auf ein fertiges ``model.db`` (nicht thread-safe → Aufrufer sperrt)."""

    def __init__(self, path: Path):
        # immutable=1: Datei wird nie verändert, nur ersetzt → kein Locking, maximales Caching
        self.db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        self.meta = dict(self.db.execute("SELECT key, value FROM meta"))
        (blob,) = self.db.execute("SELECT data FROM bloom").fetchone()
        self.bloom = Bloom(blob, int(self.meta["bloom_bits"]), int(self.meta["bloom_hashes"]))
        # Fenstergrößen, die beim Bauen wirklich im Filter gelandet sind
        ngrams = [int(n) for n in str(self.meta.get("overlap_ngrams", "5,6,7")).split(",")]
        self.min_n, self.max_n = min(ngrams), max(ngrams)
        self._totals2: dict[int, int] = {}
        self._totals3: dict[tuple[int, int], tuple[int, int]] = {}
        self._words: dict[int, str] = {}

    def close(self):
        self.db.close()

    # ---------- Kette ----------

    def _total2(self, s: int) -> int:
        total = self._totals2.get(s)
        if total is None:
            row = self.db.execute("SELECT cum FROM chain2 WHERE s = ? ORDER BY cum DESC LIMIT 1", (s,)).fetchone()
            total = self._totals2[s] = row[0] if row else 0
        return total

    def _total3(self, w0: int, s: int) -> tuple[int, int]:
        """(Gesamtgewicht, Anzahl verschiedener Folgewörter) eines 3er-Kontexts."""
        key = (w0, s)
        cached = self._totals3.get(key)
        if cached is None:
            if len(self._totals3) > 500_000:
                self._totals3.clear()
            cached = self._totals3[key] = self.db.execute(
                "SELECT coalesce(max(cum), 0), count(*) FROM chain3 WHERE w0 = ? AND s = ?", (w0, s)
            ).fetchone()
        return cached

    def _next(self, w0: int, w1: int, w2: int, min_branches: int | None) -> int:
        """Zieht das Folgewort: 3er-Kontext, wo er sich genug verzweigt, sonst 2er-Kontext."""
        s = (w1 << 32) | w2
        total, branches = self._total3(w0, s) if min_branches else (0, 0)
        if total and branches >= min_branches:
            return self.db.execute(
                "SELECT next FROM chain3 WHERE w0 = ? AND s = ? AND cum > ? ORDER BY cum LIMIT 1",
                (w0, s, random.randrange(total)),
            ).fetchone()[0]
        if len(self._totals2) > 500_000:
            self._totals2.clear()
        return self.db.execute(
            "SELECT next FROM chain2 WHERE s = ? AND cum > ? ORDER BY cum LIMIT 1",
            (s, random.randrange(self._total2(s))),
        ).fetchone()[0]

    def _walk(self, style: Style) -> list[int] | None:
        """Ein zufälliger Satz als Wort-IDs (None = zu lang geworden)."""
        w0 = w1 = w2 = BEGIN
        ids = []
        for _ in range(MAX_WORDS + 1):
            nxt = self._next(w0, w1, w2, style.order3_min_branches)
            if nxt == END:
                return ids
            ids.append(nxt)
            w0, w1, w2 = w1, w2, nxt
        return None

    def _is_original(self, ids: list[int], max_overlap_ratio: float, style: Style) -> bool:
        """True, wenn eine zu lange Wortfolge wörtlich aus einer Nachricht stammt."""
        n = round(max_overlap_ratio * len(ids)) + 1 + style.overlap_bonus
        n = min(max(n, self.min_n), self.max_n)
        return any(ids[i : i + n] in self.bloom for i in range(len(ids) - n + 1))

    def _text(self, ids: list[int]) -> str:
        missing = [i for i in set(ids) if i not in self._words]
        if missing:
            if len(self._words) > 200_000:
                self._words.clear()
            placeholders = ",".join("?" * len(missing))
            self._words.update(self.db.execute(f"SELECT id, word FROM vocab WHERE id IN ({placeholders})", missing))
        return " ".join(self._words[i] for i in ids)

    def sentence(self, max_overlap_ratio: float = 0.6, style: str = DEFAULT_STYLE) -> str | None:
        """Ein neuer Satz, der kein (Fast-)Original ist – oder None nach ``TRIES`` Fehlversuchen."""
        chosen = STYLES[style]
        for _ in range(TRIES):
            ids = self._walk(chosen)
            if ids is not None and len(ids) >= MIN_WORDS and not self._is_original(ids, max_overlap_ratio, chosen):
                return self._text(ids)
        return None


# -------------------- Austausch --------------------


def install_model(build_path: Path) -> list[Path]:
    """Neues Modell aktivieren: bisheriges Modell (und die alte markovify-JSON) ins Archiv.

    Das aktive Modell muss vorher geschlossen sein. Gibt die archivierten Dateien zurück.
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archived = []
    if MODEL_DB.exists():
        stamp = datetime.fromtimestamp(MODEL_DB.stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")
        archived.append(MODEL_DB.rename(ARCHIVE_DIR / f"model_{stamp}.db"))
    if LEGACY_JSON.exists():
        archived.append(LEGACY_JSON.rename(ARCHIVE_DIR / "hivemind_markovify_2024-05-20.json"))
    os.replace(build_path, MODEL_DB)
    for old in sorted(ARCHIVE_DIR.glob("model_*.db"))[:-ARCHIVE_KEEP]:
        old.unlink()
    return archived
