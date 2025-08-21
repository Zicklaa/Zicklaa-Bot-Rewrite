# Zicklaa Bot Rewrite

Zicklaa Bot ist ein Discord‑Bot, der verschiedenste Komfort‑Features für den Server *Bens Haus der Enten* bereitstellt. Der Code wurde komplett in Python neu geschrieben und nutzt moderne Slash‑Commands.

## Features

- **Allgemein**
  - `/ping` – zeigt die aktuelle Latenz.
  - Automatische Antworten auf bestimmte Schlagwörter.
- **RemindMe** – Erinnerungen setzen.
  - `/remindme in <amount> <unit> [text]`
  - `/remindme at <input> [text]`
  - `/remindme list`
- **Chat** – Interaktion mit GPT und Bildgenerator.
  - `/chat <text>` – ChatGPT (OpenAI).
  - `/hmchat` – Antwort im Hivemind‑Stil (Markov + GPT).
  - `/image fast|hd <prompt>` – Bilder via FAL AI.
- **Hivemind** – Zufällige Sätze aus einem Markov‑Modell (`/hm`, `/hmm`).
- **Fav/Starboard**
  - Reaktionen speichern (`/fav`, `/rfav`, `/allfavs`).
  - Sternbrett mit automatischem Post bei ⭐‑Reaktionen (`/star`).
- **Sonstiges**
  - `/buli` – nächster Bundesliga‑Spieltag.
  - `/ltb` – zufälliges Bild aus dem *Lustige Bildchen*‑Ordner.
  - `/reload` – Cog neu laden (nur Owner).

## Setup

1. **Python-Abhängigkeiten installieren**
   ```bash
   pip install discord.py python-dotenv markovify requests fal-client openai pytz python-dateutil parsimonious
   ```

2. **.env-Datei anlegen** – Beispiele:
   ```env
   DISCORD_TOKEN=...            # Token des Bots
   globalPfad=/pfad/zum/bot     # Basisordner für Datenbank, Logs, etc.
   SECRET_PROBABILITY=0.05      # Wahrscheinlichkeit für Auto‑Replies
   OPENAI_API_KEY=...
   FAL_KEY=...
   FOOTBALL_DATA_API_TOKEN=...  # für /buli
   ```

3. **Starten**
   ```bash
   python bot.py
   ```

## Daten & Logging

- Logs werden täglich rotiert und liegen unter `Old Logs/ZicklaaBotLog.log` relativ zu `globalPfad`.
- Für Reminder, Favs und Sternbrett wird eine SQLite‑Datenbank (`reminder-wishlist.db`) genutzt.

## Entwicklung

- Cogs liegen im Verzeichnis `commands/` und werden beim Start automatisch geladen.
- Der Parser für `/remindme at` befindet sich unter `utils/`.
- Pull Requests sind willkommen.
