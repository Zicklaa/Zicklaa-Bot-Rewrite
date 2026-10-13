import asyncio
import logging
import time
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from matplotlib.transforms import IdentityTransform

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Statistik")

# -------------------- Konfiguration --------------------

# Kalenderjahre werden in deutscher Zeit geschnitten
TZ = ZoneInfo("Europe/Berlin")

# Cache-Dauer in Sekunden: abgeschlossene Jahre ändern sich praktisch nicht mehr
CACHE_TTL_PAST_YEAR = 24 * 60 * 60
CACHE_TTL_CURRENT_YEAR = 5 * 60

# Discord-Suche: Index evtl. noch nicht bereit (HTTP 202) -> ein paar Mal warten
INDEX_RETRIES = 4
INDEX_MAX_WAIT = 10

# Farben des Diagramms (dunkle Fläche, passend zum Embed)
COLOR_SURFACE = "#1a1a19"
COLOR_BAR = "#3987e5"
COLOR_BAR_RUNNING = "#1c5cab"
COLOR_TEXT = "#f0efec"
COLOR_TEXT_SECONDARY = "#c3c2b7"
COLOR_TEXT_MUTED = "#898781"
COLOR_BASELINE = "#383835"
EMBED_COLOR = 0x3987E5

CHART_FILENAME = "statistik.png"


class SearchIndexNotReady(Exception):
    """Discord baut den Such-Index der Guild noch auf."""


# -------------------- Helpers --------------------


def fmt_int(n: int) -> str:
    """Ganzzahl mit deutschem Tausenderpunkt (12.345)."""
    return f"{n:,}".replace(",", ".")


def fmt_compact(n: int) -> str:
    """Kurzform für Balkenbeschriftungen (55,9k / 1,2 Mio)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".replace(".", ",") + " Mio"
    if n >= 100_000:
        return f"{n / 1000:.0f}k"
    if n >= 10_000:
        return f"{n / 1000:.1f}".replace(".", ",") + "k"
    return fmt_int(n)


def fmt_decimal(x: float) -> str:
    """Kommazahl mit deutschem Dezimalkomma, eine Nachkommastelle."""
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def year_start(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=TZ)


def build_year_table(years: list[int], counts: list[int], current_year: int) -> str:
    """Baut die Jahresübersicht als ausgerichteten Codeblock."""
    width = max(len(fmt_int(c)) for c in counts)
    lines = []
    for i, (year, count) in enumerate(zip(years, counts)):
        if year == current_year:
            trend = "läuft noch"
        elif i == 0:
            trend = ""
        else:
            prev = counts[i - 1]
            if prev == 0:
                trend = "▲ neu" if count else "■ ±0 %"
            else:
                change = round((count - prev) / prev * 100)
                if change > 0:
                    trend = f"▲ +{fmt_int(change)} %"
                elif change < 0:
                    trend = f"▼ −{fmt_int(abs(change))} %"
                else:
                    trend = "■ ±0 %"
        lines.append(f"{year}  {fmt_int(count):>{width}}  {trend}".rstrip())
    return "```\n" + "\n".join(lines) + "\n```"


def render_chart(years: list[int], counts: list[int], current_year: int) -> BytesIO:
    """Zeichnet das Säulendiagramm (synchron, läuft in einem Thread)."""
    dpi = 100
    fig = Figure(figsize=(14, 7.6), dpi=dpi, facecolor=COLOR_SURFACE)
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.045, 0.13, 0.91, 0.60))
    ax.set_facecolor(COLOR_SURFACE)

    n = len(years)
    top = max(counts)
    # Mindestens 6 Slots, damit wenige Jahre nicht riesig in der Mitte kleben
    slots = max(n, 6)
    offset = (slots - n) / 2
    ax.set_xlim(-0.5, slots - 0.5)
    ax.set_ylim(0, top * 1.12)

    # Titel & Untertitel
    total = sum(counts)
    span = str(years[0]) if n == 1 else f"{years[0]}–{years[-1]}"
    fig.text(
        0.045, 0.90, "Nachrichten pro Kalenderjahr",
        color=COLOR_TEXT, fontsize=32, fontweight="bold", ha="left", va="baseline",
    )
    fig.text(
        0.045, 0.825, f"{fmt_int(total)} Nachrichten  ·  {span}",
        color=COLOR_TEXT_SECONDARY, fontsize=20, ha="left", va="baseline",
    )

    # Säulen: oben abgerundet, an der Grundlinie eckig (in Pixeln gezeichnet)
    slot_px = ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0]
    bar_px = min(slot_px * 0.62, 96)
    radius = 10
    for i, (year, count) in enumerate(zip(years, counts)):
        x = i + offset
        cx, base = ax.transData.transform((x, 0))
        label_y = 0
        if count > 0:
            y_top = max(ax.transData.transform((x, count))[1], base + 4)
            x0, x1 = cx - bar_px / 2, cx + bar_px / 2
            r = min(radius, bar_px / 2, y_top - base)
            path = Path(
                [
                    (x0, base), (x0, y_top - r), (x0, y_top), (x0 + r, y_top),
                    (x1 - r, y_top), (x1, y_top), (x1, y_top - r), (x1, base),
                    (x0, base),
                ],
                [
                    Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3,
                    Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO,
                    Path.CLOSEPOLY,
                ],
            )
            fig.add_artist(
                PathPatch(
                    path,
                    transform=IdentityTransform(),
                    facecolor=COLOR_BAR_RUNNING if year == current_year else COLOR_BAR,
                    edgecolor="none",
                )
            )
            label_y = ax.transData.inverted().transform((cx, y_top))[1]

        # Wert über der Säule
        ax.annotate(
            fmt_compact(count), (x, label_y), xytext=(0, 8), textcoords="offset points",
            ha="center", va="bottom", fontsize=17, fontweight="bold",
            color=COLOR_TEXT if count == top else COLOR_TEXT_SECONDARY,
        )

    # Achsen: nur Grundlinie und Jahres-Labels, keine Y-Skala (Werte stehen an den Säulen)
    for side in ("top", "left", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(COLOR_BASELINE)
    ax.spines["bottom"].set_linewidth(1.5)
    ax.set_yticks([])
    ax.set_xticks([i + offset for i in range(n)])
    ax.set_xticklabels(
        [f"{y}\nläuft noch" if y == current_year else str(y) for y in years]
    )
    ax.tick_params(axis="x", length=0, pad=10, labelsize=17, colors=COLOR_TEXT_MUTED)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=COLOR_SURFACE)
    buf.seek(0)
    return buf


# -------------------- Cog-Klasse --------------------


class Statistik(commands.Cog):
    """Cog: /statistik – Eigene Nachrichten pro Kalenderjahr als Diagramm."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, user_id, year) -> (läuft ab [monotonic], Anzahl)
        self._count_cache: dict[tuple[int, int, int], tuple[float, int]] = {}
        # (guild_id, user_id) -> Zeitpunkt der ersten Nachricht
        self._first_message: dict[tuple[int, int], datetime] = {}
        # User, deren Auswertung gerade läuft
        self._running: set[tuple[int, int]] = set()

    # -------------------- Discord-Suche --------------------

    async def _search(self, guild_id: int, **params) -> dict:
        """Ruft die Nachrichtensuche der Guild auf (liefert u.a. total_results)."""
        route = Route("GET", "/guilds/{guild_id}/messages/search", guild_id=guild_id)
        for attempt in range(INDEX_RETRIES):
            data = await self.bot.http.request(route, params=params)
            if isinstance(data, dict) and "total_results" in data:
                return data
            # 202: Index wird noch aufgebaut
            if attempt < INDEX_RETRIES - 1:
                retry_after = 2.0
                if isinstance(data, dict):
                    try:
                        retry_after = float(data.get("retry_after") or 2)
                    except (TypeError, ValueError):
                        pass
                await asyncio.sleep(min(max(retry_after, 1.0), INDEX_MAX_WAIT))
        raise SearchIndexNotReady()

    async def _get_first_message(self, guild_id: int, user_id: int) -> tuple[datetime | None, bool]:
        """Zeitpunkt der ältesten Nachricht des Users + ob es überhaupt Nachrichten gibt."""
        key = (guild_id, user_id)
        if key in self._first_message:
            return self._first_message[key], True

        data = await self._search(
            guild_id,
            author_id=str(user_id),
            include_nsfw="true",
            sort_by="timestamp",
            sort_order="asc",
            limit=1,
        )
        if int(data["total_results"]) == 0:
            return None, False

        try:
            first = discord.utils.snowflake_time(
                int(data["messages"][0][0]["id"])
            ).astimezone(TZ)
        except (KeyError, IndexError, TypeError, ValueError):
            # Treffer vorhanden, aber Nachricht nicht mitgeliefert -> nicht cachen
            return None, True
        self._first_message[key] = first
        return first, True

    async def _count_year(self, guild_id: int, user_id: int, year: int, current_year: int) -> int:
        """Anzahl der Nachrichten des Users in einem Kalenderjahr."""
        key = (guild_id, user_id, year)
        cached = self._count_cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        data = await self._search(
            guild_id,
            author_id=str(user_id),
            include_nsfw="true",
            limit=1,
            # min_id/max_id sind exklusiv
            min_id=str(max(discord.utils.time_snowflake(year_start(year)) - 1, 0)),
            max_id=str(discord.utils.time_snowflake(year_start(year + 1))),
        )
        count = int(data["total_results"])
        ttl = CACHE_TTL_CURRENT_YEAR if year >= current_year else CACHE_TTL_PAST_YEAR
        self._count_cache[key] = (time.monotonic() + ttl, count)
        return count

    # -------------------- /statistik --------------------

    @app_commands.command(
        name="statistik",
        description="Zeigt deine eigenen Nachrichten pro Kalenderjahr als Diagramm.",
    )
    @app_commands.describe(
        privat="Nur für dich sichtbar anzeigen (Standard: für alle sichtbar)"
    )
    @app_commands.guild_only()
    async def statistik(self, interaction: discord.Interaction, privat: bool = False):
        """
        Slash: /statistik [privat]
        - Zählt die Nachrichten des aufrufenden Users pro Kalenderjahr (Discord-Suche)
        - Antwortet mit Embed + Säulendiagramm
        - Bewusst ohne User-Parameter: Auswertung nur für sich selbst
        """
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            await interaction.response.send_message(
                "Das geht nur auf einem Server, Moruk 🤷", ephemeral=True
            )
            return

        run_key = (guild.id, user.id)
        if run_key in self._running:
            await interaction.response.send_message(
                "⏳ Deine Statistik wird gerade schon erstellt, kurz Geduld.",
                ephemeral=True,
            )
            return

        self._running.add(run_key)
        try:
            await interaction.response.defer(thinking=True, ephemeral=privat)

            now = datetime.now(TZ)
            current_year = now.year

            first, has_messages = await self._get_first_message(guild.id, user.id)
            if not has_messages:
                await self._send_no_messages(interaction)
                return

            if first is not None:
                start_year = first.year
            else:
                # Älteste Nachricht nicht ermittelbar -> ab Server- bzw. Account-Erstellung zählen
                start_year = max(
                    guild.created_at.astimezone(TZ).year,
                    user.created_at.astimezone(TZ).year,
                )
            start_year = min(start_year, current_year)

            years = list(range(start_year, current_year + 1))
            counts = [
                await self._count_year(guild.id, user.id, year, current_year)
                for year in years
            ]

            # Führende Jahre ohne Nachrichten abschneiden
            while len(counts) > 1 and counts[0] == 0:
                years.pop(0)
                counts.pop(0)

            total = sum(counts)
            if total == 0:
                await self._send_no_messages(interaction)
                return

            chart = await asyncio.to_thread(render_chart, years, counts, current_year)

            # Kennzahlen
            best_idx = max(range(len(years)), key=lambda i: counts[i])
            this_year_count = counts[-1]

            embed = discord.Embed(
                title="📊 Deine Nachrichten pro Kalenderjahr",
                description=(
                    f"Insgesamt **{fmt_int(total)}** Nachrichten auf **{discord.utils.escape_markdown(guild.name)}**"
                    + (f" seit {discord.utils.format_dt(first, 'D')}." if first else ".")
                ),
                color=EMBED_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

            embed.add_field(
                name="🏆 Stärkstes Jahr",
                value=f"**{years[best_idx]}**\n{fmt_int(counts[best_idx])} Nachrichten",
                inline=True,
            )

            if first is not None:
                days = max((now - first).days + 1, 1)
                embed.add_field(
                    name="📅 Ø pro Tag",
                    value=f"**{fmt_decimal(total / days)}**\nseit der ersten Nachricht",
                    inline=True,
                )

            # Hochrechnung erst, wenn das Jahr alt genug für eine brauchbare Schätzung ist
            day_of_year = now.timetuple().tm_yday
            days_in_year = (year_start(current_year + 1).date() - year_start(current_year).date()).days
            if day_of_year >= 14 and this_year_count > 0:
                projection = round(this_year_count / day_of_year * days_in_year)
                this_year_hint = f"Hochrechnung ≈ {fmt_int(projection)}"
            else:
                this_year_hint = "Stand heute"
            embed.add_field(
                name=f"📈 {current_year} bisher",
                value=f"**{fmt_int(this_year_count)}**\n{this_year_hint}",
                inline=True,
            )

            embed.add_field(
                name="🗓️ Jahresübersicht (Veränderung zum Vorjahr)",
                value=build_year_table(years, counts, current_year),
                inline=False,
            )

            embed.set_image(url=f"attachment://{CHART_FILENAME}")
            embed.set_footer(text="Quelle: Discord-Suche · nur Kanäle, die der Bot sehen kann")

            await interaction.followup.send(
                embed=embed,
                file=discord.File(chart, filename=CHART_FILENAME),
                allowed_mentions=discord.AllowedMentions.none(),
            )

            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Statistics sent",
                user,
                user.id,
                command="/statistik",
                years=len(years),
                total=total,
                privat=privat,
            )

        except SearchIndexNotReady as e:
            await self._send_error(
                interaction,
                "⏳ Discord baut den Such-Index für diesen Server gerade noch auf. "
                "Probier es in ein paar Minuten nochmal.",
            )
            log_event(
                logger,
                logging.WARNING,
                self.__class__.__name__,
                "Search index not ready",
                user,
                user.id,
                command="/statistik",
                error=e,
            )
        except discord.Forbidden as e:
            await self._send_error(
                interaction,
                "❌ Mir fehlt die Berechtigung **Nachrichtenverlauf anzeigen**, "
                "ohne die kann ich nicht zählen.",
            )
            log_event(
                logger,
                logging.WARNING,
                self.__class__.__name__,
                "Statistics forbidden",
                user,
                user.id,
                command="/statistik",
                error=e,
            )
        except Exception as e:
            await self._send_error(
                interaction, "Statistik Schmatistik, das hat nicht geklappt 🤷"
            )
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Statistics failed",
                user,
                user.id,
                command="/statistik",
                error=e,
                exc_info=True,
            )
        finally:
            self._running.discard(run_key)

    async def _send_no_messages(self, interaction: discord.Interaction) -> None:
        await interaction.followup.send(
            "🦗 Du hast hier noch keine Nachrichten geschrieben, die ich zählen könnte.",
            ephemeral=True,
        )
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "No messages found",
            interaction.user,
            interaction.user.id,
            command="/statistik",
        )

    async def _send_error(self, interaction: discord.Interaction, text: str) -> None:
        """Schickt eine Fehlermeldung, egal ob schon geantwortet wurde oder nicht."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except Exception:
            pass


# -------------------- Cog-Setup --------------------


async def setup(bot: commands.Bot):
    await bot.add_cog(Statistik(bot))
