# Zicklaa Bot Rewrite

Ein Discord-Bot für den Server *Bens Haus der Enten*.  Die Neuimplementation nutzt
`discord.py` 2.x und moderne Slash-Commands.  Dieses Dokument beschreibt Aufbau,
Konfiguration und den kompletten Funktionsumfang.

## Inhalt
- [Architektur](#architektur)
- [Setup](#setup)
- [Daten & Logging](#daten--logging)
- [Befehlsübersicht](#befehlsübersicht)

## Architektur
- **bot.py** – Hauptdatei. Lädt Token & Pfade aus `.env`, initialisiert Logger,
  SQLite‑Datenbank (`reminder-wishlist.db`) und Markov‑Modell (`static/hivemind.json`).
- **commands/** – Alle Cogs (je eine Datei pro Feature) werden beim Start
  automatisch geladen und die Slash‑Commands nur auf zugelassene Guilds
  synchronisiert.
- **utils/** – Parser für `/remindme at` (natürliche Zeitangaben).
- Der Bot reagiert mit kleiner Wahrscheinlichkeit (`SECRET_PROBABILITY`) auf
  Schlüsselwörter wie „crazy“, „kult“, „hallo“, „lol“, „xd“, „uff“, „gumo“ usw.
- Globale Cooldowns verhindern Command‑Spam.

## Setup
### Abhängigkeiten
```bash
pip install -r requirements.txt
```

### .env-Datei
Beispiel:
```env
DISCORD_TOKEN=...
globalPfad=/pfad/zum/bot
SECRET_PROBABILITY=0.05
OPENAI_API_KEY=...
FAL_KEY=...
FOOTBALL_DATA_API_TOKEN=...
LASTFM_API_KEY=...
LASTFM_API_SECRET=...
LYRICS_KEY=...
```
Weitere Variablen können nach Bedarf ergänzt werden.

### Start
```bash
python bot.py
```

## Daten & Logging
- Rotierende Logfiles unter `Old Logs/ZicklaaBotRewriteLog.log` relativ zu
  `globalPfad`.
- SQLite-DB für Reminder (`reminders`), Wunschliste (`wishlist`), Favs und
  Sternbrett (`stars`).
- Erinnerungen, Favs und Sternbrett‑Einträge nutzen Message‑IDs zum Verknüpfen
  mit Originalnachrichten.

## Befehlsübersicht
### Allgemein
- `/ping` – Latenz prüfen.
- `/datum` – aktuelles Datum (deutsch formatiert).
- `/git` – Link zum GitHub‑Repository.
- `/quote <link>` – Zitiert eine Nachricht per Link.
- `/choose <optionen>` – wählt zufällig eine Option.
- `/roll [anzahl] [seiten]` & `/coinflip` – Würfel bzw. Münzwurf.
- `/wetter <ort>` & `/asciiwetter <ort>` – Wetter als Bild oder ASCII.
- `/translate from:<sprache> to:<sprache> text:<txt>` – Übersetzung via
  GoogleTranslator.
- `/wiki suchen|artikel|zufall` – Wikipedia‑Artikel als Embed.
- `/statistik [privat]` – eigene Nachrichten pro Kalenderjahr als Embed mit
  Diagramm (nur für sich selbst, gezählt über die Discord‑Suche).

### Erinnerungen
- `/remindme in <zahl> <einheit> [text]` – erinnert nach Zeitspanne.
- `/remindme at <eingabe> [text]` – natürliche Zeitangabe.
- `/remindme list` – anstehende Reminder anzeigen.

### Chat & KI
- `/chat <text>` – ChatGPT‑Antwort.
- `/hmchat <text>` – GPT mit Markov‑Flavor.
- `/image fast|hd|nsfw|hdnsfw <prompt>` – Bildgenerierung via FAL.
- `/tts <text> [voice]` – Text‑to‑Speech.

### Hivemind
- `/hm` – ein Satz aus dem Markov‑Modell.
- `/hmm` – fünf Sätze (nur im Spam‑Channel).

### Spiele & Spaß
- `/discordle` & `/bildcordle` – Wer schrieb die Nachricht / welches Bild?
- `/magic8 [frage]` – Antworten der magischen Acht.
- `/sponge <text>` & `/randomsponge <text>` – Spongebob‑Case.
- `/girlboss` – motivierende Nachricht (nur für ausgewählte User).
- `/kindermoerder` & `/raul` – Raul‑GIF posten.
- `/jamesh` – „Da gibt es ein James Hoffmann Video dazu.“
- `/ltb` – zufälliges lustiges Bildchen aus Ordner.
- `/rezept` – zufälliges gepinntes Rezept.
- `/lyrics full|link <lastfm-user>` – aktueller Song inkl. Lyrics bzw. Link.

### Favoriten & Sternbrett
- Reagiere mit 🦶 auf eine Nachricht → Bot fragt nach Namen und speichert als
  Fav; 🗑️ löscht eigenen Fav.
- `/fav [name]` – eigenen Fav abrufen.
- `/rfav` – zufälligen Fav eines Users.
- `/allfavs` – alle Favs als Textdatei per DM.
- ⭐‑Reaktionen ab `THRESHOLD` posten automatisch ins Sternbrett.
- `/star <link>` – Nachricht manuell ins Sternbrett posten (nur Admin).

### Fußball & Info
- `/buli` – nächster Bundesliga‑Spieltag (Football‑Data API).
- `/tabelle` – aktuelle Bundesliga‑Tabelle.

### Admin
- `/load <cog>` – Cog laden.
- `/unload <cog>` – Cog entladen.
- `/reload <cog>` – Cog neu laden.
- `/sync` – Slash‑Commands synchronisieren.

