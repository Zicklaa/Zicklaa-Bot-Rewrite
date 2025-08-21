import logging
import os
import discord
from datetime import datetime, timedelta, timezone
import requests
from zoneinfo import ZoneInfo
from discord.ext import commands
from discord import app_commands

# -------------------- Logger & Konfiguration --------------------

logger = logging.getLogger("ZicklaaBotRewrite.Buli")

BERLIN_TZ = ZoneInfo("Europe/Berlin")
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
BASE = "https://api.football-data.org/v4"
_SESSION: requests.Session | None = None  # Für Keep-Alive

# -------------------- Cog-Klasse --------------------

class Buli(commands.Cog):
    """Cog für den Bundesliga-Spieltag-Command."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="buli", description="Zeigt den nächsten Bundesliga-Spieltag an")
    async def buli(self, interaction: discord.Interaction):
        """Slash-Command: Zeigt den nächsten Bundesliga-Spieltag als Embed."""
        try:
            api_token = os.environ["FOOTBALL_DATA_API_TOKEN"]
            if not api_token:
                raise RuntimeError("FOOTBALL_DATA_API_TOKEN nicht gesetzt.")

            session = get_session(api_token)
            matchday, fixtures, date_range = fetch_next_matchday_with_scores(session)

            embed = discord.Embed(
                title=f"Bundesliga – Spieltag {matchday}",
                description="\n".join(format_line(m) for m in fixtures),
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Zeiten: Europa/Berlin  •  Zeitraum: {date_range}")
            embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/fr/b/b4/Logo_Bundesliga.png")

            await interaction.response.send_message(embed=embed)
            logger.info(f"Buli-Embed gesendet an {interaction.user} (ID: {interaction.user.id})")

        except Exception as e:
            await interaction.response.send_message("❌ Klappt nit lol 🤷", ephemeral=True)
            logger.error(f"Buli von {interaction.user.name}: {e}")

# -------------------- API & Hilfsfunktionen --------------------

def get_session(api_token: str) -> requests.Session:
    """Erstellt oder aktualisiert eine Requests-Session mit Auth-Token."""
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({"X-Auth-Token": api_token})
        _SESSION = s
    else:
        _SESSION.headers.update({"X-Auth-Token": api_token})
    return _SESSION

def fd_get(session: requests.Session, path: str, params: dict | None = None) -> dict:
    """API-Request an football-data.org."""
    url = f"{BASE}{path}"
    resp = session.get(url, params=params, timeout=15)
    if resp.status_code == 429:
        raise RuntimeError("Rate Limit erreicht (HTTP 429).")
    if not resp.ok:
        raise RuntimeError(f"API Fehler {resp.status_code}: {resp.text}")
    return resp.json()

def to_dt(utc_iso: str) -> datetime:
    """Konvertiert ISO-String in datetime."""
    return datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))

def team_name(team: dict) -> str:
    """Gibt den Teamnamen zurück (Short, TLA oder Name)."""
    return team.get("shortName") or team.get("tla") or team.get("name") or "?"

def score_str(match: dict) -> str:
    """Formatiert das Spielergebnis/Livescore."""
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
        if status == "IN_PLAY":
            return f" — {home}:{away} (LIVE)"
        elif status == "FINISHED":
            return f" — {home}:{away}{pen_suffix}"
        else:
            return f" — {home}:{away}"
    if status == "IN_PLAY":
        return " — LIVE"
    return ""

def format_line(match: dict) -> str:
    """Formatiert eine Zeile für das Embed."""
    home = team_name(match["homeTeam"])
    away = team_name(match["awayTeam"])
    dt_local = to_dt(match["utcDate"]).astimezone(BERLIN_TZ)
    when = dt_local.strftime(f"{WEEKDAYS[dt_local.weekday()]}, %d.%m. %H:%M")
    venue = (match.get("venue") or "").strip()
    venue_str = f"  —  {venue}" if venue else ""
    return f"`{when}`  **{home}** vs **{away}**{venue_str}{score_str(match)}"

def determine_next_matchday_from_scheduled(scheduled_matches: list[dict]) -> tuple[int, list[dict]]:
    """Bestimmt den nächsten Spieltag aus geplanten Spielen."""
    md_to_matches: dict[int, list[dict]] = {}
    for m in scheduled_matches:
        md = m.get("matchday")
        if md is not None:
            md_to_matches.setdefault(md, []).append(m)
    if not md_to_matches:
        raise RuntimeError("Konnte den nächsten Spieltag nicht bestimmen.")

    next_md = min(
        md_to_matches.keys(),
        key=lambda md: min(to_dt(x["utcDate"]) for x in md_to_matches[md])
    )
    fixtures_sorted = sorted(md_to_matches[next_md], key=lambda m: to_dt(m["utcDate"]))
    return next_md, fixtures_sorted

def fetch_next_matchday_with_scores(session: requests.Session) -> tuple[int, list[dict], str]:
    """Holt alle Spiele des nächsten Spieltags inkl. Ergebnisse."""
    today_utc = datetime.now(timezone.utc).date()
    scheduled = fd_get(
        session, "/competitions/BL1/matches",
        params={
            "status": "SCHEDULED",
            "dateFrom": today_utc.isoformat(),
            "dateTo": (today_utc + timedelta(days=21)).isoformat(),
        },
    ).get("matches", [])

    if not scheduled:
        scheduled = fd_get(session, "/competitions/BL1/matches",
                           params={"status": "SCHEDULED"}).get("matches", [])

    if not scheduled:
        raise RuntimeError("Keine anstehenden Bundesliga-Spiele gefunden.")

    next_md, fixtures_sched = determine_next_matchday_from_scheduled(scheduled)

    first_kick = to_dt(fixtures_sched[0]["utcDate"])
    last_kick = to_dt(fixtures_sched[-1]["utcDate"])
    date_from = (first_kick - timedelta(days=1)).date().isoformat()
    date_to = (last_kick + timedelta(days=1)).date().isoformat()

    window_matches = fd_get(
        session, "/competitions/BL1/matches",
        params={"dateFrom": date_from, "dateTo": date_to},
    ).get("matches", [])

    fixtures = [m for m in window_matches if m.get("matchday") == next_md] or fixtures_sched
    fixtures.sort(key=lambda m: to_dt(m["utcDate"]))

    first_local = to_dt(fixtures[0]["utcDate"]).astimezone(BERLIN_TZ)
    last_local = to_dt(fixtures[-1]["utcDate"]).astimezone(BERLIN_TZ)
    date_range = (
        first_local.strftime("%d.%m.%Y")
        if first_local.date() == last_local.date()
        else f'{first_local.strftime("%d.%m.%Y")} – {last_local.strftime("%d.%m.%Y")}'
    )
    return next_md, fixtures, date_range

# -------------------- Cog-Setup --------------------

async def setup(bot):
    """Fügt das Buli-Cog dem Bot hinzu."""
    await bot.add_cog(Buli(bot))
