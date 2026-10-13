"""/buli & /tabelle – Bundesliga-Spieltage und Tabelle (football-data.org).

Rate-Limit-freundlich:
- /buli lädt ALLE Spiele der Saison mit einem API-Call in den Cache.
- Blättern zwischen Spieltagen liest nur aus dem Cache.
- Refresh macht einen Call nur für den aktuellen Spieltag (mit Cooldown).
"""

import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, BaseView, reply

# -------------------- Konfiguration --------------------

BERLIN_TZ = ZoneInfo("Europe/Berlin")
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
BASE_URL = "https://api.football-data.org/v4"
COMPETITION = "BL1"
LOGO_URL = "https://upload.wikimedia.org/wikipedia/fr/b/b4/Logo_Bundesliga.png"

LIVE_STATUSES = {"IN_PLAY", "PAUSED"}  # was als „live“ gilt
REFRESH_COOLDOWN_SECONDS = 10          # Cooldown für den Refresh-Button
TABLE_TTL_SECONDS = 180                # Cache-Lebensdauer der Tabelle

# -------------------- Hilfsfunktionen --------------------


def to_dt(utc_iso: str) -> datetime:
    return datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))


def kickoff(match: dict) -> datetime:
    """Anstoßzeit in deutscher Zeit."""
    return to_dt(match["utcDate"]).astimezone(BERLIN_TZ)


def team_name(team: dict | None) -> str:
    """Möglichst kurzer Teamname."""
    team = team or {}
    return team.get("shortName") or team.get("tla") or team.get("name") or "?"


def score_str(match: dict) -> str:
    """Spielstand als Anhang für die Spielzeile, z. B. `` — `2:1` ✅``."""
    status = match.get("status")
    score = match.get("score") or {}
    live = " 🔴 LIVE" if status in LIVE_STATUSES else ""

    # Erstes Ergebnis nehmen, das vollständig vorliegt
    for key in ("fullTime", "regularTime", "extraTime", "halfTime"):
        part = score.get(key) or {}
        home, away = part.get("home"), part.get("away")
        if home is not None and away is not None:
            break
    else:
        return f" —{live}" if live else ""

    suffix = live
    if status == "FINISHED":
        suffix = " ✅"
        pen = score.get("penalties") or {}
        if pen.get("home") is not None and pen.get("away") is not None:
            suffix += f" (n.E. {pen['home']}:{pen['away']})"
    return f" — `{home}:{away}`{suffix}"


def format_date_range(fixtures: list[dict]) -> str:
    """Zeitraum eines (sortierten) Spieltags, z. B. ``01.09.2025 – 03.09.2025``."""
    first, last = kickoff(fixtures[0]), kickoff(fixtures[-1])
    if first.date() == last.date():
        return f"{first:%d.%m.%Y}"
    return f"{first:%d.%m.%Y} – {last:%d.%m.%Y}"


def determine_next_matchday(all_matches: list[dict]) -> int | None:
    """Bestimmt den „nächsten/aktuellen“ Spieltag.

    Das ist der kleinste Spieltag mit mindestens einem Spiel, das noch aussteht
    (Status SCHEDULED/TIMED oder Datum in der Zukunft); sonst der kleinste mit Live-Spiel.
    """
    now = datetime.now(timezone.utc)
    upcoming, live = [], []
    for m in all_matches:
        md = m.get("matchday")
        if not isinstance(md, int):
            continue
        if m.get("status") in {"SCHEDULED", "TIMED"} or to_dt(m["utcDate"]) >= now:
            upcoming.append(md)
        elif m.get("status") in LIVE_STATUSES:
            live.append(md)
    return min(upcoming or live, default=None)


# -------------------- Embeds --------------------


def build_matchday_embed(matchday: int, fixtures: list[dict]) -> discord.Embed:
    """Spieltag als Embed, Spiele nach Tagen gruppiert."""
    if any(m.get("status") in LIVE_STATUSES for m in fixtures):
        color = discord.Color.green()
    elif fixtures and all(m.get("status") == "FINISHED" for m in fixtures):
        color = discord.Color.greyple()
    else:
        color = discord.Color.red()

    # Spiele (bereits nach Anstoß sortiert) pro Kalendertag sammeln
    days: dict = defaultdict(list)
    for m in fixtures:
        days[kickoff(m).date()].append(m)

    lines = []
    for day, matches in days.items():
        lines.append(f"**{WEEKDAYS[day.weekday()]}, {day:%d.%m.%Y}**\n┄┄┄┄┄┄┄┄┄┄")
        lines.extend(
            f"🕒 `{kickoff(m):%H:%M}`  •  **{team_name(m['homeTeam'])}** vs **{team_name(m['awayTeam'])}**{score_str(m)}"
            for m in matches
        )
        lines.append("")

    embed = discord.Embed(
        title=f"🇩🇪 Männerfußball Bundesliga – Spieltag {matchday}",
        description="\n".join(lines).strip() or "Keine Spiele gefunden.",
        color=color,
    )
    date_range = format_date_range(fixtures) if fixtures else ""
    embed.set_footer(text=f"Zeitraum: {date_range} • Zeitzone: Europa/Berlin")
    embed.set_thumbnail(url=LOGO_URL)
    return embed


def build_table_embed(table: list[dict]) -> discord.Embed:
    """Kompakte Tabelle als Monospace-Codeblock: Pl | Team | Pkt | Sp | Diff."""
    if not table:
        return discord.Embed(
            title="🇩🇪 Bundesliga – Tabelle",
            description="Keine Daten verfügbar.",
            color=discord.Color.greyple(),
        )

    header = f"{'Pl':<2} {'Team':<14} {'Pkt':>3} {'Sp':>2} {'Diff':>4}"
    lines = [header, "─" * len(header)]
    for row in table:
        lines.append(
            f"{row.get('position', ''):<2} {team_name(row.get('team'))[:12]:<14} "
            f"{row.get('points', 0):>3} {row.get('playedGames', 0):>2} {row.get('goalDifference', 0):>+4}"
        )

    embed = discord.Embed(
        title="🇩🇪 Bundesliga – Tabelle",
        description="```\n" + "\n".join(lines) + "\n```",
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=LOGO_URL)
    return embed


# -------------------- View --------------------


class MatchdayView(BaseView):
    """Buttons unter dem Spieltag: Zurück / Refresh / Weiter."""

    error_text = "❌ Fehler beim Aktualisieren."

    def __init__(self, cog: "Buli", matchday: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.matchday = matchday
        self.previous.disabled = matchday <= cog.md_min
        self.next.disabled = matchday >= cog.md_max
        # Refresh gibt es nur auf dem aktuellen Spieltag
        self.refresh.disabled = matchday != cog.current_matchday

    @discord.ui.button(label="⬅️ Vorheriger", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_matchday(interaction, self.matchday - 1)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_matchday(interaction, self.matchday, refresh=True)

    @discord.ui.button(label="Nächster ➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_matchday(interaction, self.matchday + 1)


# -------------------- Cog --------------------


class Buli(BaseCog):
    """Cog: /buli & /tabelle."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # Spieltags-Cache: matchday -> nach Anstoß sortierte Spiele
        self.matchdays: dict[int, list[dict]] = {}
        self.md_min, self.md_max = 1, 34
        self.next_matchday: int | None = None

        # Refresh-Cooldown pro Spieltag und Tabellen-Cache (jeweils time.monotonic())
        self._refresh_allowed_at: dict[int, float] = {}
        self._table_embed: discord.Embed | None = None
        self._table_cached_until = 0.0

    @property
    def current_matchday(self) -> int:
        return self.next_matchday or self.md_min

    # ---------- API ----------

    async def _api_get(self, path: str, **params) -> dict:
        """GET gegen football-data.org; wirft RuntimeError bei Fehlern."""
        headers = {"X-Auth-Token": os.environ["FOOTBALL_DATA_API_TOKEN"]}
        async with self.bot.session.get(f"{BASE_URL}{path}", params=params, headers=headers) as resp:
            if resp.status == 429:
                raise RuntimeError("Rate Limit erreicht (HTTP 429).")
            if not resp.ok:
                raise RuntimeError(f"API Fehler {resp.status}: {await resp.text()}")
            return await resp.json()

    async def _fetch_matches(self, **params) -> list[dict]:
        """Spiele der Saison (optional gefiltert), nach Anstoß sortiert."""
        data = await self._api_get(f"/competitions/{COMPETITION}/matches", **params)
        return sorted(data.get("matches", []), key=lambda m: to_dt(m["utcDate"]))

    async def _load_season(self):
        """Lädt ALLE Spiele der Saison neu und überschreibt den Cache (1 API-Call)."""
        matches = await self._fetch_matches()
        if not matches:
            raise RuntimeError("Keine Spiele für laufende Saison gefunden.")

        grouped: dict[int, list[dict]] = defaultdict(list)
        for m in matches:
            if isinstance(m.get("matchday"), int):
                grouped[m["matchday"]].append(m)

        self.matchdays = dict(grouped)
        self.md_min, self.md_max = (min(grouped), max(grouped)) if grouped else (1, 34)
        self.next_matchday = determine_next_matchday(matches)
        self.log("Cache built", matchdays=len(grouped), next_matchday=self.next_matchday)

    # ---------- Commands ----------

    @app_commands.command(
        name="buli",
        description="Zeigt den nächsten Bundesliga-Spieltag an",
        extras={"error": "❌ Klappt nit lol 🤷"},
    )
    async def buli(self, interaction: discord.Interaction):
        """Zeigt den nächsten Spieltag mit Navigation & Live-Refresh."""
        await interaction.response.defer()
        await self._load_season()  # immer frische Daten

        matchday = self.current_matchday
        await interaction.followup.send(
            embed=build_matchday_embed(matchday, self.matchdays[matchday]),
            view=MatchdayView(self, matchday),
        )
        self.log("Matchday embed sent", interaction, matchday=matchday)

    async def show_matchday(self, interaction: discord.Interaction, matchday: int, *, refresh: bool = False):
        """Zeigt einen Spieltag in der bestehenden Nachricht (für die Buttons).

        Blättern liest nur aus dem Cache; ``refresh`` lädt den aktuellen Spieltag neu,
        wenn der Cooldown abgelaufen ist.
        """
        if not self.matchdays:
            await self._load_season()
        matchday = max(self.md_min, min(self.md_max, matchday))

        fresh = False
        if refresh and matchday == self.next_matchday:
            wait = self._refresh_allowed_at.get(matchday, 0) - time.monotonic()
            if wait > 0:
                await interaction.response.send_message(
                    f"⏳ Bitte warte noch **{int(wait) + 1}s**, bevor du erneut refreshst.", ephemeral=True
                )
                return
            self._refresh_allowed_at[matchday] = time.monotonic() + REFRESH_COOLDOWN_SECONDS
            fresh = True

        # Neu laden bei Refresh – oder falls der Spieltag wider Erwarten nicht im Cache ist
        if fresh or not self.matchdays.get(matchday):
            fixtures = await self._fetch_matches(matchday=matchday)
            if not fixtures:
                raise RuntimeError(f"Keine Spiele für Spieltag {matchday} gefunden.")
            self.matchdays[matchday] = fixtures

        await interaction.response.edit_message(
            embed=build_matchday_embed(matchday, self.matchdays[matchday]),
            view=MatchdayView(self, matchday),
        )
        self.log("Refresh (live)" if fresh else "Navigation (Cache)", interaction, command="/buli", matchday=matchday)

    @app_commands.command(
        name="tabelle",
        description="Zeigt die aktuelle Bundesliga-Tabelle (mit Cache & hübscher Formatierung).",
        extras={"error": "❌ Tabelle derzeit nicht verfügbar."},
    )
    @app_commands.describe(refresh="Ignoriere Cache und lade neu (kann Rate Limit belasten).")
    async def tabelle(self, interaction: discord.Interaction, refresh: bool = False):
        cached = not refresh and self._table_embed is not None and time.monotonic() < self._table_cached_until
        if not cached:
            await interaction.response.defer(thinking=True)
            data = await self._api_get(f"/competitions/{COMPETITION}/standings")
            total = next((s for s in data.get("standings", []) if s.get("type") == "TOTAL"), None)
            if not total:
                raise RuntimeError("Standings (TOTAL) nicht gefunden.")
            self._table_embed = build_table_embed(total.get("table", []))
            self._table_cached_until = time.monotonic() + TABLE_TTL_SECONDS

        # reply() nutzt je nach Fall die direkte Antwort oder das Followup
        await reply(interaction, embed=self._table_embed)
        self.log("Table from cache" if cached else "Table refreshed", interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Buli(bot))
