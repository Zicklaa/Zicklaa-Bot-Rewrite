# buli_cog.py
from collections import defaultdict
import logging
import os
import discord
from datetime import datetime, timedelta, timezone
import requests
from zoneinfo import ZoneInfo
from discord.ext import commands
from discord import app_commands

logger = logging.getLogger("ZicklaaBotRewrite.Buli")

BERLIN_TZ = ZoneInfo("Europe/Berlin")
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
BASE = "https://api.football-data.org/v4"
COMP = "BL1"
_SESSION: requests.Session | None = None

LIVE_STATUSES = {"IN_PLAY", "PAUSED"}  # was als „live“ gilt
REFRESH_COOLDOWN_SECONDS = 10  # ⏱️ Cooldown in Sekunden für Refresh
TABLE_TTL_SECONDS = 180  # Cache-Lebensdauer der Tabelle


'''# Emojis für alle Bundesliga-Vereine 2025/26
TEAM_EMOJIS = {
    "Bayern": "🔴⚪",
    "Leverkusen": "🔴⚫",
    "Frankfurt": "⚫🦅",
    "Dortmund": "🟡⚫",
    "Freiburg": "⚫🔴",
    "Mainz": "🔵⚪",
    "RB Leipzig": "⚪🔴🐂",
    "Bremen": "🟢⚪⚓",
    "Stuttgart": "⚪🔴",
    "M'gladbach": "⚫⚪🍀",
    "Wolfsburg": "🟢⚪🐺",
    "Augsburg": "🟢⚪🔴",
    "Union Berlin": "🔴⚪",
    "St. Pauli": "🤎⚪☠️",
    "Hoffenheim": "🔵⚪",
    "HSV": "🔵⚪⚓",
    "Heidenheim": "🔴🔵",
    "1. FC Köln": "⚪🔴🐐",
}'''

# -------------------- Buttons --------------------


class MatchdayView(discord.ui.View):
    def __init__(self, cog: "Buli", matchday: int, md_min: int, md_max: int, *, current_md: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.matchday = matchday
        self.md_min = md_min
        self.md_max = md_max
        self.current_md = current_md
        self._apply_disabled()
        # Tabelle: Cache + Timestamp
        self._table_embed: discord.Embed | None = None
        self._table_cached_until: datetime | None = None

    def _apply_disabled(self):
        # Randbegrenzungen
        self.previous.disabled = self.matchday <= self.md_min
        self.next.disabled = self.matchday >= self.md_max
        # Refresh nur auf dem „aktuellen“ (Start-)Spieltag
        self.refresh.disabled = (self.matchday != self.current_md)

    @discord.ui.button(label="⬅️ Vorheriger", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.matchday <= self.md_min:
            await interaction.response.defer()
            return
        self.matchday -= 1
        self._apply_disabled()
        await self.cog.update_embed(interaction, self.matchday, use_cache_only=True)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Nur aktiv, wenn matchday == current_md (Button ist ansonsten disabled)
        await self.cog.update_embed(interaction, self.matchday, refresh=True)

    @discord.ui.button(label="Nächster ➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.matchday >= self.md_max:
            await interaction.response.defer()
            return
        self.matchday += 1
        self._apply_disabled()
        await self.cog.update_embed(interaction, self.matchday, use_cache_only=True)

# -------------------- Cog --------------------


class Buli(commands.Cog):
    """
    Bundesliga-Viewer mit Rate-Limit-freundlichem Cache:
    - Erster Call lädt ALLE Spiele der Saison (1 API-Call).
    - Navigation liest aus Cache.
    - Refresh macht 1 Call NUR auf dem nächsten/aktuellen Spieltag (mit Cooldown).
    """

    def __init__(self, bot):
        self.bot = bot
        self._md_min: int | None = None
        self._md_max: int | None = None

        # Cache: matchday -> [matches...], sowie vorberechnete Date-Ranges
        self._md_cache: dict[int, list[dict]] = {}
        self._md_date_range: dict[int, str] = {}
        self._cache_ready: bool = False

        # Merker: Welcher Spieltag ist „next/aktuell“ laut Cache?
        self._next_matchday: int | None = None

        # Cooldown-Tracker pro Spieltag
        self._refresh_cooldown_until: dict[int, datetime] = {}

    @app_commands.command(name="buli", description="Zeigt den nächsten Bundesliga-Spieltag an")
    async def buli(self, interaction: discord.Interaction):
        """Slash-Command: Zeigt den nächsten Spieltag mit Navigation & Live-Refresh (nur auf aktuellem Spieltag)."""
        try:
            api_token = os.environ["FOOTBALL_DATA_API_TOKEN"]
            if not api_token:
                raise RuntimeError("FOOTBALL_DATA_API_TOKEN nicht gesetzt.")

            session = get_session(api_token)

            # 1) Cache initial füllen (1 API-Call) und Bounds bestimmen
            await self._ensure_cache(session)

            md_min, md_max = self._md_min or 1, self._md_max or 34
            start_md = self._next_matchday or md_min

            fixtures = self._md_cache[start_md]
            date_range = self._md_date_range[start_md]
            embed = build_embed(start_md, fixtures, date_range)
            view = MatchdayView(self, start_md, md_min,
                                md_max, current_md=start_md)

            await interaction.response.send_message(embed=embed, view=view)
            logger.info(
                f"Buli-Embed gesendet an {interaction.user} (ID: {interaction.user.id}), Start-Spieltag={start_md}")

        except Exception as e:
            await interaction.response.send_message("❌ Klappt nit lol 🤷", ephemeral=True)
            logger.exception(f"Buli von {interaction.user.name}: {e}")

    @app_commands.command(name="tabelle", description="Zeigt die aktuelle Bundesliga-Tabelle (mit Cache & hübscher Formatierung).")
    @app_commands.describe(refresh="Ignoriere Cache und lade neu (kann Rate Limit belasten).")
    async def tabelle(self, interaction: discord.Interaction, refresh: bool = False):
        try:
            api_token = os.environ["FOOTBALL_DATA_API_TOKEN"]
            if not api_token:
                raise RuntimeError("FOOTBALL_DATA_API_TOKEN nicht gesetzt.")
            session = get_session(api_token)

            now = datetime.now(timezone.utc)

            use_cache = (
                not refresh
                and self._table_embed is not None
                and self._table_cached_until is not None
                and now < self._table_cached_until
            )

            if use_cache:
                await interaction.response.send_message(embed=self._table_embed)
                logger.info(
                    "Tabelle aus Cache gesendet (gültig bis %s).", self._table_cached_until)
                return

            # „Frisch“ laden
            await interaction.response.defer(thinking=True, ephemeral=False)
            data = fd_get_standings(session)
            standings = data.get("standings", [])
            total = next(
                (s for s in standings if s.get("type") == "TOTAL"), None)
            if not total:
                raise RuntimeError("Standings (TOTAL) nicht gefunden.")

            embed = build_table_embed(total)

            # Cache aktualisieren
            self._table_embed = embed
            self._table_cached_until = now + \
                timedelta(seconds=TABLE_TTL_SECONDS)

            await interaction.followup.send(embed=embed)
            logger.info("Tabelle frisch geladen und gecached bis %s.",
                        self._table_cached_until)

        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Tabelle derzeit nicht verfügbar.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Tabelle derzeit nicht verfügbar.", ephemeral=True)
            logger.exception("Fehler beim Laden der Tabelle: %s", e)

    async def update_embed(
        self,
        interaction: discord.Interaction,
        matchday: int,
        *,
        refresh: bool = False,
        use_cache_only: bool = False,
    ):
        """
        Aktualisiert das Embed:
        - use_cache_only=True: kein API-Call, nur Cache.
        - refresh=True: wenn matchday == _next_matchday -> 1 API-Call (mit Cooldown),
                        sonst Cache.
        """
        try:
            api_token = os.environ["FOOTBALL_DATA_API_TOKEN"]
            session = get_session(api_token)

            # Safety: Cache da?
            if not self._cache_ready:
                await self._ensure_cache(session)

            # Clamp sicherheitshalber
            md_min, md_max = self._md_min or 1, self._md_max or 34
            matchday = max(md_min, min(md_max, matchday))
            current_md = self._next_matchday or md_min

            if use_cache_only:
                fixtures = self._md_cache.get(matchday) or []
                date_range = self._md_date_range.get(matchday, "")
            else:
                # Refresh-Strategie (nur auf aktuellem Spieltag + Cooldown)
                if refresh and self._next_matchday is not None and matchday == self._next_matchday:
                    now = datetime.now(timezone.utc)
                    until = self._refresh_cooldown_until.get(matchday)
                    if until and now < until:
                        # Cooldown aktiv → ephemere Info, kein API-Call
                        seconds = int((until - now).total_seconds())
                        await interaction.response.send_message(
                            f"⏳ Bitte warte noch **{seconds}s**, bevor du erneut refreshst.",
                            ephemeral=True,
                        )
                        logger.info(
                            f"Refresh-Cooldown aktiv für Spieltag {matchday}: {seconds}s verbleibend.")
                        return

                    # Erlaubt → 1 API-Call + Cooldown setzen
                    fixtures, date_range = fetch_matchday(session, matchday)
                    self._md_cache[matchday] = fixtures
                    self._md_date_range[matchday] = date_range
                    self._refresh_cooldown_until[matchday] = now + \
                        timedelta(seconds=REFRESH_COOLDOWN_SECONDS)
                    logger.info(
                        f"Refresh vom aktuellen Spieltag {matchday}: 1 API-Call. Nächster Refresh ab {self._refresh_cooldown_until[matchday].isoformat()}")
                else:
                    # Kein Refresh oder nicht aktueller Spieltag → Cache nutzen
                    fixtures = self._md_cache.get(matchday) or []
                    date_range = self._md_date_range.get(matchday, "")

            # Falls aus irgendeinem Grund leer (sollte nicht passieren), fallback einmalig:
            if not (fixtures and date_range):
                fixtures, date_range = fetch_matchday(session, matchday)
                self._md_cache[matchday] = fixtures
                self._md_date_range[matchday] = date_range
                logger.info(
                    f"Fallback-Fetch für Spieltag {matchday}: 1 API-Call.")

            embed = build_embed(matchday, fixtures, date_range)
            view = MatchdayView(self, matchday, md_min,
                                md_max, current_md=current_md)

            # Wenn wir oben bereits geantwortet haben (Cooldown-Hinweis), NICHT nochmal antworten
            if interaction.response.is_done():
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)

            action = "Refresh (live)" if (refresh and matchday == self._next_matchday) else (
                "Navigation (Cache)" if use_cache_only else "Update")
            logger.info(
                f"{action} für Spieltag {matchday} von {interaction.user}")

        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Fehler beim Aktualisieren.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Fehler beim Aktualisieren.", ephemeral=True)
            logger.exception(f"Update Embed Error: {e}")

    # -------------------- Cache/Init --------------------

    async def _ensure_cache(self, session: requests.Session):
        """Lädt einmalig alle Spiele der Saison und füllt den Matchday-Cache (1 API-Call)."""
        if self._cache_ready:
            return

        # 1 API-Call
        data = fd_get(session, f"/competitions/{COMP}/matches", params=None)
        matches = data.get("matches", [])
        if not matches:
            raise RuntimeError("Keine Spiele für laufende Saison gefunden.")

        # md_min/md_max
        mds = [m.get("matchday")
               for m in matches if isinstance(m.get("matchday"), int)]
        self._md_min, self._md_max = (min(mds), max(mds)) if mds else (1, 34)

        # matchday -> list[matches], sortiert
        grouped: dict[int, list[dict]] = defaultdict(list)
        for m in matches:
            md = m.get("matchday")
            if isinstance(md, int):
                grouped[md].append(m)

        for md, lst in grouped.items():
            lst.sort(key=lambda m: to_dt(m["utcDate"]))
            self._md_cache[md] = lst
            self._md_date_range[md] = format_date_range(lst) if lst else ""

        # „nächsten/aktuellen“ Spieltag bestimmen
        self._next_matchday = determine_next_matchday_from_all(matches)
        self._cache_ready = True

        logger.info(
            f"Cache geladen: {len(self._md_cache)} Spieltage, Bounds={self._md_min}-{self._md_max}, next={self._next_matchday}")

# -------------------- Gruppierung & Embed --------------------


def group_fixtures_by_day(fixtures: list[dict]) -> dict[datetime.date, list[dict]]:
    buckets: dict[datetime.date, list[dict]] = defaultdict(list)
    for m in fixtures:
        dt_local = to_dt(m["utcDate"]).astimezone(BERLIN_TZ)
        buckets[dt_local.date()].append(m)

    sorted_days: dict[datetime.date, list[dict]] = {}
    for day in sorted(buckets.keys()):
        sorted_days[day] = sorted(
            buckets[day], key=lambda x: to_dt(x["utcDate"]))
    return sorted_days


def build_embed(matchday: int, fixtures: list[dict], date_range: str) -> discord.Embed:
    color = discord.Color.red()
    if any(m.get("status") in LIVE_STATUSES for m in fixtures):
        color = discord.Color.green()
    elif fixtures and all(m.get("status") == "FINISHED" for m in fixtures):
        color = discord.Color.greyple()

    lines: list[str] = []
    grouped = group_fixtures_by_day(fixtures)

    for day, matches in grouped.items():
        wd = WEEKDAYS[day.weekday()]
        day_head = f"**{wd}, {day.strftime('%d.%m.%Y')}**"
        sep = "┄┄┄┄┄┄┄┄┄┄"
        lines.append(f"{day_head}\n{sep}")
        for m in matches:
            home = team_name(m["homeTeam"])
            away = team_name(m["awayTeam"])
            dt_local = to_dt(m["utcDate"]).astimezone(BERLIN_TZ)
            when = dt_local.strftime("%H:%M")
            score = score_str(m)
            lines.append(f"🕒 `{when}`  •  **{home}** vs **{away}**{score}")
        lines.append("")

    description = "\n".join(lines).strip()

    embed = discord.Embed(
        title=f"🇩🇪 Bundesliga – Spieltag {matchday}",
        description=description or "Keine Spiele gefunden.",
        color=color,
    )
    embed.set_footer(text=f"Zeitraum: {date_range} • Zeitzone: Europa/Berlin")
    embed.set_thumbnail(
        url="https://upload.wikimedia.org/wikipedia/fr/b/b4/Logo_Bundesliga.png")
    return embed


'''def add_emoji(team: str) -> str:
    emoji = TEAM_EMOJIS.get(team, "")
    return f"{emoji} {team}" if emoji else team'''

# -------------------- API & Hilfsfunktionen --------------------


def get_session(api_token: str) -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({"X-Auth-Token": api_token})
        _SESSION = s
    else:
        _SESSION.headers.update({"X-Auth-Token": api_token})
    return _SESSION


def fd_get(session: requests.Session, path: str, params: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    resp = session.get(url, params=params, timeout=15)
    if resp.status_code == 429:
        raise RuntimeError("Rate Limit erreicht (HTTP 429).")
    if not resp.ok:
        raise RuntimeError(f"API Fehler {resp.status_code}: {resp.text}")
    return resp.json()


def to_dt(utc_iso: str) -> datetime:
    return datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))


def team_name(team: dict) -> str:
    return team.get("shortName") or team.get("tla") or team.get("name") or "?"


def score_str(match: dict) -> str:
    status = match.get("status")
    s = match.get("score") or {}
    candidates = [
        s.get("fullTime") or {},
        s.get("regularTime") or {},
        s.get("extraTime") or {},
        s.get("halfTime") or {},
    ]
    home = away = None
    for c in candidates:
        h, a = c.get("home"), c.get("away")
        if h is not None and a is not None:
            home, away = h, a
            break

    pen = s.get("penalties") or {}
    pen_home, pen_away = pen.get("home"), pen.get("away")
    pen_suffix = f" (n.E. {pen_home}:{pen_away})" if (
        pen_home is not None and pen_away is not None and status == "FINISHED"
    ) else ""

    if home is not None and away is not None:
        if status in LIVE_STATUSES:
            return f" — `{home}:{away}` 🔴 LIVE"
        elif status == "FINISHED":
            return f" — `{home}:{away}` ✅{pen_suffix}"
        else:
            return f" — `{home}:{away}`"
    if status in LIVE_STATUSES:
        return " — 🔴 LIVE"
    return ""


def fetch_matchday(session: requests.Session, matchday: int) -> tuple[list[dict], str]:
    matches = fd_get(
        session, f"/competitions/{COMP}/matches",
        params={"matchday": matchday}
    ).get("matches", [])

    if not matches:
        raise RuntimeError(f"Keine Spiele für Spieltag {matchday} gefunden.")

    matches.sort(key=lambda m: to_dt(m["utcDate"]))
    date_range = format_date_range(matches)
    return matches, date_range


def determine_next_matchday_from_all(all_matches: list[dict]) -> int | None:
    """
    Bestimmt „nächsten/aktuellen“ Spieltag aus ALLEN Matches:
    - Bevorzugt den kleinsten matchday mit mindestens einem Spiel, dessen Status SCHEDULED/TIMED ist,
      oder dessen Datum in der Zukunft liegt.
    - Falls aktuell Spiele laufen (IN_PLAY/PAUSED) und derselbe Spieltag auch noch zukünftige Spiele hat,
      bleibt dieser Spieltag „current“.
    """
    now = datetime.now(timezone.utc)

    candidates: dict[int, list[dict]] = defaultdict(list)
    for m in all_matches:
        md = m.get("matchday")
        if not isinstance(md, int):
            continue
        status = m.get("status")
        dt_utc = to_dt(m["utcDate"])
        if status in {"SCHEDULED", "TIMED"} or dt_utc >= now:
            candidates[md].append(m)

    if candidates:
        return min(candidates.keys())

    live_md = [m.get("matchday")
               for m in all_matches if m.get("status") in LIVE_STATUSES]
    if live_md:
        return min([md for md in live_md if isinstance(md, int)], default=None)

    return None


def format_date_range(fixtures: list[dict]) -> str:
    first_local = to_dt(fixtures[0]["utcDate"]).astimezone(BERLIN_TZ)
    last_local = to_dt(fixtures[-1]["utcDate"]).astimezone(BERLIN_TZ)
    return (
        first_local.strftime("%d.%m.%Y")
        if first_local.date() == last_local.date()
        else f'{first_local.strftime("%d.%m.%Y")} – {last_local.strftime("%d.%m.%Y")}'
    )


def fd_get_standings(session: requests.Session) -> dict:
    return fd_get(session, f"/competitions/{COMP}/standings", params=None)


def form_to_badges(form: str | None) -> str:
    """
    Wandelt 'W,D,L,W,...' in 🟩🟨🟥 um (max 5).
    """
    if not form:
        return "–"
    mapping = {"W": "🟩", "D": "🟨", "L": "🟥"}
    parts = [p.strip()[:1] for p in form.split(",") if p.strip()]
    last5 = parts[-5:]  # nur die letzten 5
    return "".join(mapping.get(x, "▫️") for x in last5)


def pad(text: str, width: int) -> str:
    # monospaced padding für Codeblock-Tabellen
    t = text[:width]
    return t + " " * max(0, width - len(t))


def team_label(team_obj: dict) -> str:
    # Kürzerer Teamname bevorzugt
    short = team_obj.get("shortName") or team_obj.get(
        "tla") or team_obj.get("name") or "?"
    return short


def build_table_embed(standings_block: dict) -> discord.Embed:
    """
    Kompakte Bundesliga-Tabelle als Monospace-Codeblock:
    Spalten: Pl | Team | Pkt | Sp | Diff
    - Teamname hart gekürzt (max. 12 Zeichen), optional mit Vereins-Emoji.
    - Kein 'Form' und keine 'Tore', um Breite klein zu halten.
    """
    table: list[dict] = standings_block.get("table", [])
    if not table:
        return discord.Embed(
            title="🇩🇪 Bundesliga – Tabelle",
            description="Keine Daten verfügbar.",
            color=discord.Color.greyple(),
        )

    # Kopfzeile (schmal gehalten)
    header = f"{'Pl':<2} {'Team':<14} {'Pkt':>3} {'Sp':>2} {'Diff':>4}"
    sep = "─" * len(header)

    lines = [header, sep]

    for row in table:
        pos = str(row.get("position", ""))
        name = (row.get("team", {}) or {}).get("shortName") or (row.get(
            "team", {}) or {}).get("tla") or (row.get("team", {}) or {}).get("name") or "?"
        base = name[:12]  # max 12 Zeichen für den Namen

        pts = row.get("points", 0)
        sp = row.get("playedGames", 0)
        gd = row.get("goalDifference", 0)  # mit Vorzeichen

        line = f"{pos:<2} {base:<14} {pts:>3} {sp:>2} {gd:>+4}"
        lines.append(line)

    desc = "```\n" + "\n".join(lines) + "\n```"

    embed = discord.Embed(
        title="🇩🇪 Bundesliga – Tabelle",
        description=desc,
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(
        url="https://upload.wikimedia.org/wikipedia/fr/b/b4/Logo_Bundesliga.png")
    return embed


# -------------------- Cog Setup --------------------

async def setup(bot):
    await bot.add_cog(Buli(bot))
