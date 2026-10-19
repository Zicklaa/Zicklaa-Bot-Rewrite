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
- **bot.py** – Hauptdatei. Initialisiert Logger, SQLite‑Datenbank
  (`reminder-wishlist.db`), Hivemind‑Modell (`static/hivemind/model.db`) und eine
  gemeinsame HTTP‑Session, lädt alle Cogs und registriert die Slash‑Commands
  nur auf den zugelassenen Guilds.
- **commands/** – Alle Cogs (je eine Datei pro Feature), werden beim Start
  automatisch geladen.
- **utils/**
  - `settings.py` – Pfade und IDs, die mehrere Module brauchen (lädt `.env`).
  - `base.py` – `BaseCog`/`BaseView` mit einheitlichem Logging und zentraler
    Fehlerbehandlung, `UserError`, Checks (`owner_only`, `in_channels`).
  - `helpers.py` – Text‑, Zeit‑ und Nachrichten‑Helfer.
  - `parser.py` + `rm_grammar.peg` – Parser für `/remindme at`.
  - `logging_helper.py` – einheitliches Log‑Format.
  - `hivemind/` – Markov‑Kette aus allen Server‑Nachrichten: `scrape.py` lädt
    die Nachrichten (fortsetzbar), `build.py` baut daraus das Modell (eigener
    Prozess), `model.py` erzeugt die Sätze.
- Der Bot reagiert mit kleiner Wahrscheinlichkeit (`SECRET_PROBABILITY`) auf
  Schlüsselwörter wie „crazy“, „kult“, „gumo“, „danke“ usw.
- Ein globaler Cooldown verhindert Spam bei Prefix‑Commands.

### Ein neues Cog schreiben
```python
from discord import app_commands
from utils.base import BaseCog, UserError

class Beispiel(BaseCog):
    @app_commands.command(name="beispiel", description="…",
                          extras={"error": "Text bei unerwartetem Fehler"})
    async def beispiel(self, interaction, zahl: int):
        if zahl < 1:
            raise UserError("❌ Zahl zu klein.")   # ephemere Antwort + Warnung im Log
        await interaction.response.send_message(str(zahl))
        self.log("Beispiel sent", interaction, zahl=zahl)

async def setup(bot):
    await bot.add_cog(Beispiel(bot))
```
Kein `try/except` nötig: Unerwartete Fehler loggt `BaseCog` mit Traceback und
antwortet mit dem `extras["error"]`‑Text. Nach Änderungen reicht `/reload <cog>`;
`/sync` ist nur nötig, wenn sich Namen oder Parameter von Commands ändern.

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
- `/solar` – Live‑Status der PV‑Anlage (Sungrow‑Wechselrichter per Modbus).

### Erinnerungen
- `/remindme in <zahl> <einheit> [text]` – erinnert nach Zeitspanne.
- `/remindme at <eingabe> [text]` – Datum/Uhrzeit, z. B. `15:30`,
  `01.09.2025 15:30`, `2025-09-01`.
- `/remindme list` – anstehende Reminder anzeigen.

### Chat & KI (nur im Spam‑Channel)
- `/chat <text> [websearch]` – ChatGPT‑Antwort.
- `/hmchat` – ChatGPT antwortet auf einen zufälligen Hivemind‑Satz.
- `/image fast|hd|nsfw|hdnsfw <prompt>` – Bildgenerierung via FAL.
- `/image pipeline <text>` – HD‑Bild mit automatisch optimiertem Prompt.
- `/tts <text> [voice]` – Text‑to‑Speech.

### Hivemind
- `/hm [stil]` – ein Satz aus dem Markov‑Modell. Stile: 🌀 Chaos (wilder
  Wortsalat), ⚖️ Ausgewogen (Standard), 🎓 Eloquent (fast richtige Sätze).
  Alle anderen Stellen (`/hmchat`, Reminder ohne Text) nutzen „Ausgewogen“.
- `/hmm [stil]` – fünf Sätze (nur im Spam‑Channel).
- `/hivemind rebuild [modus]` – lädt alle neuen Nachrichten des Servers und baut
  das Modell neu, mit Live‑Fortschritt und Abbrechen‑Button (nur Admin). Der
  erste Lauf lädt die komplette History (dauert Stunden, Discord erlaubt pro
  Channel nur ~100 Nachrichten/s), danach nur noch Neues. Abbrechen ist
  jederzeit möglich, der nächste Lauf macht genau dort weiter.
  - Daten: `static/hivemind/corpus.db` (Nachrichten), `model.db` (aktives
    Modell), `archiv/` (die letzten 3 ersetzten Modelle + Backup der Text‑Dumps
    des alten Bots als `hivemind_dumps_2022-2024.tar.xz`; deren Inhalt steckt
    bereits als Altbestand in `corpus.db`).
  - Datenschutz: Pro Nachricht wird nur der Text gespeichert – kein Autor,
    Channel, Zeitpunkt oder Message‑ID; gleiche Texte nur einmal. Pro Channel
    merkt sich der Bot lediglich, bis wohin er geladen hat.

### Spiele & Spaß
- `/discordle` & `/bildcordle` – Wer schrieb die Nachricht / welches Bild?
- `/magic8 [frage]` – Antworten der magischen Acht.
- `/sponge <text>` & `/randomsponge <text>` – Spongebob‑Case.
- `/girlboss` – motivierende Nachricht (nur für ausgewählte User).
- `/kindermoerder` & `/raul` – Raul‑GIF posten.
- `/jamesh` – „Da gibt es ein James Hoffmann Video dazu.“
- `/ltb` – zufälliges lustiges Bildchen aus Ordner.
- `/rezept` – zufälliges gepinntes Rezept.
- `/chefkoch suchen <zutaten>` & `/chefkoch rotd` – Rezepte von Chefkoch.
- `/lyrics full|link <lastfm-user>` – aktueller Song inkl. Lyrics bzw. Link.
- `+wdm <text>` (nur per DM) – postet den Text anonym in den Wichtel‑Channel.

### Favoriten & Sternbrett
- Reagiere mit 🦶 auf eine Nachricht → Bot fragt per DM nach einem Namen und
  speichert sie als Fav; 🗑️ auf einem geposteten Fav löscht den eigenen Fav.
- `/fav [name]` – eigenen Fav abrufen.
- `/rfav` – zufälligen Fav eines Users.
- `/allfavs` – alle Favs als Textdatei per DM.
- ⭐‑Reaktionen ab `THRESHOLD` posten automatisch ins Sternbrett; Anhänge
  landen zusätzlich im Ordner für `/ltb`.
- `/star <link>` – Nachricht manuell ins Sternbrett posten (nur Owner).
- `/sternbrett [jahr] [ansicht] [privat]` – Auswertung des Sternbretts mit Diagramm:
  meistgesternte Posts (Top 10 + Siegerpost), Sternsammler und Überblick pro
  Jahr/Monat; Jahr und Ansicht lassen sich per Menü umschalten. Die ⭐‑Zahlen der
  Originale werden in `star_stats` gecacht (erster Abruf nach dem Start dauert
  einige Minuten, danach nur noch inkrementell). Nur für den Owner.

### Fußball & Info
- `/buli` – nächster Bundesliga‑Spieltag (Football‑Data API).
- `/tabelle` – aktuelle Bundesliga‑Tabelle.

### Admin
- `/load <cog>` – Cog laden.
- `/unload <cog>` – Cog entladen.
- `/reload <cog>` – Cog neu laden.
- `/sync` – Slash‑Commands synchronisieren (nach Änderungen an Namen/Parametern).

