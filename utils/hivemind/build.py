"""Baut ein neues Hivemind-Modell aus dem Korpus – als eigener Prozess.

Aufruf (macht /hivemind rebuild automatisch):
    python -m utils.hivemind.build --out static/hivemind/model.build.db

Schreibt Fortschritt als JSON-Zeilen auf stdout: {"phase": …, "done": …, "total": …},
am Ende {"result": {...}}.

Ablauf:
1. Altbestand (die Text-Dumps von 2022 und 2024) einmalig in den Korpus übernehmen
2. Alle Zeilen sammeln, filtern, Duplikate entfernen
3. Wörter → IDs, n-Gramme zählen (numpy), kumulierte Gewichte berechnen
4. Ketten, Vokabular und Bloom-Filter sortiert in eine frische SQLite-Datei schreiben
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from array import array
from pathlib import Path

import numpy as np

from utils.hivemind.model import (
    BEGIN, CORPUS_DB, END, FNV_PRIME, GOLDEN, OVERLAP_NGRAMS, SALT,
)
from utils.hivemind.corpus import open_corpus
from utils.settings import STATIC_DIR

# 3er-Kontext nur speichern, wenn er mindestens so viele verschiedene Folgewörter hat.
# Kontexte mit nur einem Folgewort würden einfach das Original weitererzählen –
# dort springt die Kette auf den 2er-Kontext zurück und mischt Nachrichten.
ORDER3_MIN_BRANCHES = 3

# Zielfehlerrate des Bloom-Filters (falsch-positive "ist ein Original")
BLOOM_FP_RATE = 0.01

# Text-Dumps des alten Bots (Channel-weise, schon gefiltert; merged_file.txt = deren Summe)
LEGACY_GLOBS = ("25-07-2022/hivemind_*.txt", "20-05-2024/hivemind_*.txt")
LEGACY_EXCLUDE = ("merged",)

# Wie bisher: Bot-Commands, Links und Nachrichten, die mit Emoji/Mention beginnen, fliegen raus
SKIP_PREFIXES = ("<", "http", "+", "$", ".", "!", "?")

CHUNK = 500_000


def progress(phase: str, done: int = 0, total: int = 0):
    print(json.dumps({"phase": phase, "done": done, "total": total}), flush=True)


def keep_message(content: str) -> bool:
    return bool(content) and not content.startswith(SKIP_PREFIXES)


# -------------------- 1. Altbestand --------------------


def import_legacy(corpus: sqlite3.Connection):
    if corpus.execute("SELECT 1 FROM meta WHERE key = 'legacy_imported'").fetchone():
        return
    files = sorted(
        p for pattern in LEGACY_GLOBS for p in STATIC_DIR.glob(pattern)
        if not any(x in p.name for x in LEGACY_EXCLUDE)
    )
    raw = 0
    for i, path in enumerate(files):
        progress("legacy", i, len(files))
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [(" ".join(line.split()),) for line in f if not line.isspace()]
        raw += len(lines)
        corpus.executemany("INSERT OR IGNORE INTO legacy_lines(text) VALUES (?)", lines)
    # Rohzahl merken: legacy_lines selbst ist schon ohne Duplikate
    corpus.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)", [("legacy_imported", len(files)), ("legacy_raw_lines", raw)]
    )
    corpus.commit()
    progress("legacy", len(files), len(files))


# -------------------- 2. Zeilen --------------------


def collect_lines(corpus: sqlite3.Connection) -> tuple[list[str], dict]:
    """Alle Zeilen aus Altbestand + geladenen Nachrichten, gefiltert und ohne Duplikate."""
    total = (
        corpus.execute("SELECT count(*) FROM legacy_lines").fetchone()[0]
        + corpus.execute("SELECT count(*) FROM messages").fetchone()[0]
    )
    seen: set[str] = set()
    lines: list[str] = []
    raw_lines = 0
    done = 0

    def add(line: str):
        nonlocal raw_lines
        raw_lines += 1
        if line not in seen:
            seen.add(line)
            lines.append(line)

    for (text,) in corpus.execute("SELECT text FROM legacy_lines"):
        if text:
            add(text)
        done += 1
        if done % 200_000 == 0:
            progress("lines", done, total)

    messages = kept = 0
    for (content,) in corpus.execute("SELECT content FROM messages"):
        messages += 1
        if keep_message(content):
            kept += 1
            for line in content.splitlines():
                words = line.split()
                if words:
                    add(" ".join(words))
        done += 1
        if done % 200_000 == 0:
            progress("lines", done, total)

    progress("lines", total, total)
    # Duplikate innerhalb des Altbestands wurden schon beim Import verworfen → mitzählen
    row = corpus.execute("SELECT value FROM meta WHERE key = 'legacy_raw_lines'").fetchone()
    legacy_unique = corpus.execute("SELECT count(*) FROM legacy_lines").fetchone()[0]
    raw_lines += max((row[0] if row else legacy_unique) - legacy_unique, 0)
    stats = {"messages": messages, "messages_kept": kept, "raw_lines": raw_lines, "lines": len(lines)}
    return lines, stats


# -------------------- 3. Zählen --------------------


def tokenize(lines: list[str]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Wörter → IDs. Gibt (Wort-IDs flach, Wörter pro Zeile, Vokabular ab ID 2) zurück."""
    vocab: dict[str, int] = {}
    words: list[str] = []
    flat = array("i")
    lengths = array("i")
    get = vocab.get
    for n, line in enumerate(lines):
        ws = line.split()
        for w in ws:
            i = get(w)
            if i is None:
                i = vocab[w] = len(words) + 2
                words.append(w)
            flat.append(i)
        lengths.append(len(ws))
        if n % 200_000 == 0:
            progress("tokens", n, len(lines))
    progress("tokens", len(lines), len(lines))
    return np.frombuffer(flat, dtype=np.int32).astype(np.int64), np.frombuffer(lengths, dtype=np.int32).astype(np.int64), words


def build_sequence(flat: np.ndarray, lengths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Alle Zeilen als [B, B, B, w1 … wn, E] hintereinander + Positionen der Vorhersageziele."""
    sizes = lengths + 4
    starts = np.zeros(len(sizes), dtype=np.int64)
    np.cumsum(sizes[:-1], out=starts[1:])
    seq = np.full(int(sizes.sum()), BEGIN, dtype=np.int64)

    word_starts = np.zeros(len(lengths), dtype=np.int64)
    np.cumsum(lengths[:-1], out=word_starts[1:])
    within = np.arange(len(flat), dtype=np.int64) - np.repeat(word_starts, lengths)
    seq[np.repeat(starts + 3, lengths) + within] = flat
    seq[starts + 3 + lengths] = END

    target = np.ones(len(seq), dtype=bool)
    for k in range(3):
        target[starts + k] = False
    return seq, np.flatnonzero(target)


def count_rows(*cols: np.ndarray) -> tuple[list[np.ndarray], np.ndarray]:
    """Eindeutige Zeilen über mehrere Spalten (sortiert) + ihre Häufigkeit."""
    order = np.lexsort(cols[::-1])
    cols = [c[order] for c in cols]
    change = np.zeros(len(order), dtype=bool)
    change[0] = True
    for c in cols:
        change[1:] |= c[1:] != c[:-1]
    first = np.flatnonzero(change)
    counts = np.diff(np.append(first, len(order)))
    return [c[first] for c in cols], counts


def cumulative(state_change: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Laufende Summe der Häufigkeiten, die bei jedem neuen Kontext neu beginnt."""
    cum = np.cumsum(counts)
    state_first = np.flatnonzero(state_change)
    offsets = np.repeat(np.append(0, cum[state_first[1:] - 1]), np.diff(np.append(state_first, len(counts))))
    return cum - offsets


def chain_rows(seq: np.ndarray, targets: np.ndarray, min_branches: int):
    """Kette 2. und 3. Ordnung als (Schlüssel…, kumulierte Häufigkeit, Folgewort)."""
    nxt = seq[targets]
    s = (seq[targets - 2] << 32) | seq[targets - 1]
    w0 = seq[targets - 3]

    progress("chain", 0, 2)
    (s2, n2), c2 = count_rows(s, nxt)
    change2 = np.ones(len(s2), dtype=bool)
    change2[1:] = s2[1:] != s2[:-1]
    chain2 = (s2, cumulative(change2, c2), n2)

    progress("chain", 1, 2)
    (w03, s3, n3), c3 = count_rows(w0, s, nxt)
    change3 = np.ones(len(s3), dtype=bool)
    change3[1:] = (s3[1:] != s3[:-1]) | (w03[1:] != w03[:-1])
    state_id = np.cumsum(change3) - 1
    branches = np.bincount(state_id)
    keep = branches[state_id] >= min_branches
    w03, s3, n3, c3, change3 = w03[keep], s3[keep], n3[keep], c3[keep], change3[keep]
    chain3 = (w03, s3, cumulative(change3, c3), n3)
    progress("chain", 2, 2)
    return chain2, chain3


# -------------------- Bloom-Filter --------------------


def _splitmix64(z: np.ndarray) -> np.ndarray:
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def _window_hashes(seq_u: np.ndarray, is_word: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Hashes aller n-Wort-Fenster innerhalb einer Zeile (wie ``model.ngram_hashes``)."""
    count = len(seq_u) - n + 1
    valid = is_word[:count].copy()
    for j in range(1, n):
        valid &= is_word[j : j + count]
    starts = np.flatnonzero(valid)
    h = np.full(len(starts), (n * GOLDEN) & ((1 << 64) - 1), dtype=np.uint64)
    for j in range(n):
        h = (h ^ seq_u[starts + j]) * np.uint64(FNV_PRIME)
    h1 = _splitmix64(h)
    return h1, _splitmix64(h1 ^ np.uint64(SALT)) | np.uint64(1)


def build_bloom(seq: np.ndarray) -> tuple[bytes, int, int, int]:
    seq_u = seq.astype(np.uint64)
    is_word = seq >= 2
    items = 0
    for n in OVERLAP_NGRAMS:
        window = is_word[: len(seq) - n + 1].copy()
        for j in range(1, n):
            window &= is_word[j : j + len(window)]
        items += int(window.sum())
    bits = max(8, math.ceil(-items * math.log(BLOOM_FP_RATE) / math.log(2) ** 2 / 8) * 8)
    hashes = max(1, round(bits / max(items, 1) * math.log(2)))

    data = np.zeros(bits // 8, dtype=np.uint8)
    m = np.uint64(bits)
    step = 0
    for n in OVERLAP_NGRAMS:
        h1, h2 = _window_hashes(seq_u, is_word, n)
        for i in range(hashes):
            progress("bloom", step, len(OVERLAP_NGRAMS) * hashes)
            step += 1
            pos = (h1 + np.uint64(i) * h2) % m
            np.bitwise_or.at(data, (pos >> np.uint64(3)).astype(np.int64), (np.uint64(1) << (pos & np.uint64(7))).astype(np.uint8))
    progress("bloom", step, step)
    return data.tobytes(), bits, hashes, items


# -------------------- 4. Schreiben --------------------


def write_model(out: Path, words: list[str], chain2, chain3, bloom, meta: dict):
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA cache_size = -1000000;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value) WITHOUT ROWID;
        CREATE TABLE vocab(id INTEGER PRIMARY KEY, word TEXT NOT NULL);
        CREATE TABLE chain2(s INTEGER, cum INTEGER, next INTEGER, PRIMARY KEY (s, cum)) WITHOUT ROWID;
        CREATE TABLE chain3(w0 INTEGER, s INTEGER, cum INTEGER, next INTEGER, PRIMARY KEY (w0, s, cum)) WITHOUT ROWID;
        CREATE TABLE bloom(data BLOB NOT NULL);
        """
    )
    total = len(words) + len(chain2[0]) + len(chain3[0])
    done = 0

    def insert(sql: str, cols):
        nonlocal done
        for i in range(0, len(cols[0]), CHUNK):
            db.executemany(sql, zip(*(c[i : i + CHUNK].tolist() for c in cols)))
            done += min(CHUNK, len(cols[0]) - i)
            progress("write", done, total)

    db.executemany("INSERT INTO vocab(id, word) VALUES (?, ?)", enumerate(words, start=2))
    done += len(words)
    insert("INSERT INTO chain2(s, cum, next) VALUES (?, ?, ?)", chain2)
    insert("INSERT INTO chain3(w0, s, cum, next) VALUES (?, ?, ?, ?)", chain3)
    db.execute("INSERT INTO bloom(data) VALUES (?)", (bloom,))
    db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", meta.items())
    db.commit()
    db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=CORPUS_DB)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--order3-min-branches", type=int, default=ORDER3_MIN_BRANCHES)
    args = parser.parse_args()

    # Bot läuft parallel weiter → niedrigere CPU-Priorität
    os.nice(10)
    started = time.time()

    corpus = open_corpus(args.corpus)
    import_legacy(corpus)
    lines, stats = collect_lines(corpus)
    stats["legacy_lines"] = corpus.execute("SELECT count(*) FROM legacy_lines").fetchone()[0]
    stats["channels"] = corpus.execute("SELECT count(*) FROM channels WHERE last_id > 0").fetchone()[0]
    corpus.close()
    if not lines:
        raise SystemExit("Korpus ist leer")

    flat, lengths, words = tokenize(lines)
    del lines
    seq, targets = build_sequence(flat, lengths)
    del flat
    chain2, chain3 = chain_rows(seq, targets, args.order3_min_branches)
    del targets
    bloom, bloom_bits, bloom_hashes, bloom_items = build_bloom(seq)
    del seq

    stats |= {
        "tokens": int(lengths.sum()),
        "vocab": len(words),
        "chain2_rows": len(chain2[0]),
        "chain3_rows": len(chain3[0]),
        "bloom_items": bloom_items,
    }
    meta = stats | {
        "built_at": int(time.time()),
        "order3_min_branches": args.order3_min_branches,
        "bloom_bits": bloom_bits,
        "bloom_hashes": bloom_hashes,
    }
    write_model(args.out, words, chain2, chain3, bloom, meta)
    stats["seconds"] = round(time.time() - started)
    stats["size"] = args.out.stat().st_size
    print(json.dumps({"result": stats}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
