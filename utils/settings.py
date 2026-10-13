"""Zentrale Konfiguration: Pfade und IDs, die mehrere Module brauchen."""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env einmalig laden – alle anderen Module lesen danach nur noch os.environ
load_dotenv()

# -------------------- Pfade --------------------

BASE_DIR = Path(os.environ["globalPfad"])
STATIC_DIR = BASE_DIR / "static"
BILDCHEN_DIR = BASE_DIR / "LustigeBildchen"  # Quelle für /ltb, Ziel fürs Sternbrett
LOG_FILE = BASE_DIR / "Old Logs" / "ZicklaaBotRewriteLog.log"
DB_FILE = BASE_DIR / "reminder-wishlist.db"

# -------------------- Discord-IDs --------------------

# Bot-Owner: darf Admin-Commands und /star nutzen
OWNER_ID = 288413759117066241

# Nur auf diesen Guilds werden Slash-Commands registriert
GUILD_IDS: tuple[int, ...] = (122739462210846721, 567050382920908801)

SPAM_CHANNEL_ID = 528742785935998979
TEST_CHANNEL_ID = 567411189336768532  # Dev-Channel
