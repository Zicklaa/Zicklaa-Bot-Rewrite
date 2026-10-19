"""Hivemind: Markov-Kette aus allen Server-Nachrichten, gespeichert in SQLite.

- ``model``  – liest das fertige Modell und baut Sätze (läuft im Bot)
- ``build``  – baut ein neues Modell aus dem Korpus (läuft als eigener Prozess)
- ``scrape`` – lädt die Nachrichten des Servers in den Korpus (fortsetzbar)
"""
