"""/sternbrett – Auswertung des Sternbretts: Top-Posts, Sternsammler, Überblick pro Jahr.

Datenquelle ist der Sternbrett-Channel selbst: Jedes Embed verlinkt (im Autor-Feld)
auf die Originalnachricht. Die Sternanzahl steht nur am Original, also wird jedes
Original einmalig geladen und in der Tabelle ``star_stats`` gecacht.

- Erster Start: kompletter Durchlauf im Hintergrund (dauert wegen Rate-Limits ein paar Minuten)
- Danach inkrementell: neue Sternbrett-Posts + Originale, deren ⭐ sich geändert haben
  (⭐-Reaktionen auf bekannte Originale markieren den Eintrag als "dirty")
"""

import asyncio
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ft2font import FT2Font
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from matplotlib.transforms import IdentityTransform, blended_transform_factory

from utils.base import BaseCog, BaseView, UserError, owner_only
from utils.helpers import NO_MENTIONS, parse_message_link, truncate

# -------------------- Konfiguration --------------------

STERNBRETT_CHANNEL_ID = 981543834129428560

# Kalenderjahre werden in deutscher Zeit geschnitten
TZ = ZoneInfo("Europe/Berlin")

TOP_N = 10
# Gleichzeitige Abrufe von Originalen (discord.py hält die Rate-Limits selbst ein)
FETCH_CONCURRENCY = 4
# Ab so vielen offenen Originalen gilt der Cache als "wird noch aufgebaut"
PENDING_WARN = 25
VIEW_TIMEOUT = 600

# Status eines Eintrags
STATUS_OK = 0
STATUS_GONE = 1  # Original gelöscht oder nicht mehr lesbar

# Farben der Diagramme (dunkle Fläche wie bei /statistik, Sterne in Gold)
COLOR_SURFACE = "#1a1a19"
COLOR_BAR = "#c98500"
COLOR_BAR_RUNNING = "#7a5200"
COLOR_TEXT = "#f0efec"
COLOR_TEXT_SECONDARY = "#c3c2b7"
COLOR_TEXT_MUTED = "#898781"
COLOR_BASELINE = "#383835"
EMBED_COLOR = 0xFFC83D

CHART_FILENAME = "sternbrett.png"
MEDALS = ["🥇", "🥈", "🥉"]
MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Ansichten: key -> (Button-Label, Emoji)
TABS = {
    "top": ("Top 10", "🏆"),
    "people": ("Sternsammler", "👑"),
    "overview": ("Überblick", "📊"),
}

AVATAR_ID_RE = re.compile(r"/avatars/(\d+)/")
CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")
USER_MENTION_RE = re.compile(r"<@[!&]?\d+>")
CHANNEL_MENTION_RE = re.compile(r"<#\d+>")
FOOTER_CHANNEL_RE = re.compile(r"\|\s*#(.+)$")

# Zeichen, die die Diagramm-Schrift darstellen kann (Rest wäre Tofu □)
_FONT_CHARS = set(FT2Font(font_manager.findfont("DejaVu Sans")).get_charmap())


# -------------------- Datenmodell --------------------


@dataclass
class StarPost:
    message_id: int
    channel_id: int
    channel_name: str | None
    author_key: str  # author_id oder Name, falls das Original weg ist
    author_name: str
    created_at: datetime
    stars: int | None
    content: str
    image_url: str | None
    jump_url: str


# -------------------- Helpers --------------------


def fmt_int(n: int) -> str:
    """Ganzzahl mit deutschem Tausenderpunkt (12.345)."""
    return f"{n:,}".replace(",", ".")


def fmt_decimal(x: float) -> str:
    """Kommazahl mit deutschem Dezimalkomma, eine Nachkommastelle."""
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def chart_text(text: str) -> str:
    """Entfernt Zeichen, die die Schrift nicht kann, und entschärft Mathtext ($)."""
    cleaned = "".join(c for c in text if ord(c) in _FONT_CHARS or c == " ")
    cleaned = " ".join(cleaned.split())
    return cleaned.replace("$", r"\$")


def snippet(post: StarPost, max_len: int) -> str:
    """Einzeiliger Vorschautext fürs Diagramm (ohne Discord-Markup, oder Hinweis auf Medien)."""
    text = CUSTOM_EMOJI_RE.sub(r":\1:", post.content)
    text = CHANNEL_MENTION_RE.sub("#channel", USER_MENTION_RE.sub("@jemand", text))
    text = " ".join(text.split())
    if text:
        return truncate(text, max_len)
    return "Bild/Video" if post.image_url is not None else "Anhang"


def md_snippet(post: StarPost, max_len: int) -> str:
    """Vorschautext für Embeds (Mentions in Embeds pingen nicht und bleiben daher stehen)."""
    text = " ".join(post.content.split())
    if not text:
        return "🖼️ *Bild/Video*" if post.image_url is not None else "📎 *Anhang*"
    text = discord.utils.escape_markdown(truncate(text, max_len))
    return f"„{text}“"


def rank_label(i: int) -> str:
    return MEDALS[i] if i < len(MEDALS) else f"`{i + 1:>2}.`"


def parse_board_message(message: discord.Message) -> dict | None:
    """Liest aus einem Sternbrett-Post die Daten des Originals (None = kein Stern-Embed)."""
    if not message.embeds:
        return None
    embed = message.embeds[0]
    try:
        _, channel_id, message_id = parse_message_link(embed.author.url or "")
    except ValueError:
        return None

    avatar_id = AVATAR_ID_RE.search(embed.author.icon_url or "")
    channel_name = FOOTER_CHANNEL_RE.search(embed.footer.text or "")
    return {
        "message_id": message_id,
        "board_id": message.id,
        "channel_id": channel_id,
        "channel_name": channel_name.group(1).strip() if channel_name else None,
        "author_id": int(avatar_id.group(1)) if avatar_id else None,
        "author_name": embed.author.name or "Unbekannt",
        "created_at": int(discord.utils.snowflake_time(message_id).timestamp()),
        "content": embed.description or "",
        "image_url": embed.image.url,
    }


# -------------------- Diagramme --------------------


def _rounded_bar(fig: Figure, x0: float, y0: float, x1: float, y1: float, radius: float, color: str, horizontal: bool):
    """Zeichnet einen Balken in Pixeln, am freien Ende abgerundet, an der Grundlinie eckig."""
    if horizontal:
        r = min(radius, (y1 - y0) / 2, x1 - x0)
        verts = [
            (x0, y0), (x1 - r, y0), (x1, y0), (x1, y0 + r),
            (x1, y1 - r), (x1, y1), (x1 - r, y1), (x0, y1), (x0, y0),
        ]
    else:
        r = min(radius, (x1 - x0) / 2, y1 - y0)
        verts = [
            (x0, y0), (x0, y1 - r), (x0, y1), (x0 + r, y1),
            (x1 - r, y1), (x1, y1), (x1, y1 - r), (x1, y0), (x0, y0),
        ]
    codes = [
        Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3,
        Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CLOSEPOLY,
    ]
    fig.add_artist(PathPatch(Path(verts, codes), transform=IdentityTransform(), facecolor=color, edgecolor="none"))


def _title(fig: Figure, title: str, subtitle: str, top: float):
    fig.text(0.04, top, chart_text(title), color=COLOR_TEXT, fontsize=30, fontweight="bold", ha="left", va="baseline")
    fig.text(0.04, top - 0.06 * 7.6 / fig.get_figheight(), chart_text(subtitle),
             color=COLOR_TEXT_SECONDARY, fontsize=19, ha="left", va="baseline")


def _to_png(fig: Figure) -> BytesIO:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=fig.dpi, facecolor=COLOR_SURFACE)
    buf.seek(0)
    return buf


def render_ranking(title: str, subtitle: str, rows: list[tuple[str, str, int, str]]) -> BytesIO:
    """Rangliste als horizontale Balken.

    rows: (Name, Untertitel, Wert, Wert-Beschriftung) – bereits sortiert.
    """
    n = len(rows)
    height = 2.3 + 0.86 * n
    fig = Figure(figsize=(14, height), dpi=100, facecolor=COLOR_SURFACE)
    FigureCanvasAgg(fig)

    header = 1.55 / height  # Platz für Titel in Figure-Anteilen
    # Rechts Platz für die Wert-Beschriftung lassen ("17 Posts")
    ax = fig.add_axes((0.36, 0.25 / height, 0.51, 1 - header - 0.25 / height))
    ax.set_facecolor(COLOR_SURFACE)
    ax.set_axis_off()
    top = max(r[2] for r in rows) or 1
    ax.set_xlim(0, top)
    ax.set_ylim(n - 0.5, -0.5)
    _title(fig, title, subtitle, 1 - 0.75 / height)

    left = blended_transform_factory(fig.transFigure, ax.transData)
    bar_h = abs(ax.transData.transform((0, 0))[1] - ax.transData.transform((0, 1))[1]) * 0.56
    for i, (name, sub, value, value_label) in enumerate(rows):
        # Rang + Name + Untertitel links
        fig_y = i
        ax.text(0.04, fig_y, str(i + 1), transform=left, ha="left", va="center",
                fontsize=20, fontweight="bold", color=COLOR_TEXT if i == 0 else COLOR_TEXT_MUTED)
        ax.text(0.075, fig_y - 0.13, truncate(chart_text(name), 24) or "?", transform=left, ha="left", va="center",
                fontsize=17, fontweight="bold", color=COLOR_TEXT)
        ax.text(0.075, fig_y + 0.2, truncate(chart_text(sub), 42), transform=left, ha="left", va="center",
                fontsize=12.5, color=COLOR_TEXT_MUTED)

        # Balken in Pixeln (Mindestlänge, damit kleine Werte sichtbar bleiben)
        x0, cy = ax.transData.transform((0, i))
        x1 = max(ax.transData.transform((value, i))[0], x0 + 6)
        _rounded_bar(fig, x0, cy - bar_h / 2, x1, cy + bar_h / 2, 8, COLOR_BAR, horizontal=True)
        label_x = ax.transData.inverted().transform((x1, cy))[0]
        ax.annotate(value_label, (label_x, i), xytext=(10, 0), textcoords="offset points",
                    ha="left", va="center", fontsize=17, fontweight="bold",
                    color=COLOR_TEXT if value == top else COLOR_TEXT_SECONDARY, annotation_clip=False)

    return _to_png(fig)


def render_columns(title: str, subtitle: str, labels: list[str], values: list[int], muted: set[int] = frozenset()) -> BytesIO:
    """Säulendiagramm (z. B. Posts pro Jahr/Monat); Indizes in ``muted`` sind gedimmt."""
    fig = Figure(figsize=(14, 7.6), dpi=100, facecolor=COLOR_SURFACE)
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.045, 0.13, 0.91, 0.60))
    ax.set_facecolor(COLOR_SURFACE)
    _title(fig, title, subtitle, 0.90)

    n = len(values)
    top = max(values) or 1
    slots = max(n, 6)
    offset = (slots - n) / 2
    ax.set_xlim(-0.5, slots - 0.5)
    ax.set_ylim(0, top * 1.12)

    slot_px = ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0]
    bar_px = min(slot_px * 0.62, 96)
    for i, value in enumerate(values):
        x = i + offset
        cx, base = ax.transData.transform((x, 0))
        label_y = 0
        if value > 0:
            y_top = max(ax.transData.transform((x, value))[1], base + 4)
            _rounded_bar(fig, cx - bar_px / 2, base, cx + bar_px / 2, y_top, 10,
                         COLOR_BAR_RUNNING if i in muted else COLOR_BAR, horizontal=False)
            label_y = ax.transData.inverted().transform((cx, y_top))[1]
        ax.annotate(fmt_int(value), (x, label_y), xytext=(0, 8), textcoords="offset points",
                    ha="center", va="bottom", fontsize=17, fontweight="bold",
                    color=COLOR_TEXT if value == top else COLOR_TEXT_SECONDARY)

    for side in ("top", "left", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(COLOR_BASELINE)
    ax.spines["bottom"].set_linewidth(1.5)
    ax.set_yticks([])
    ax.set_xticks([i + offset for i in range(n)])
    ax.set_xticklabels(labels)
    ax.tick_params(axis="x", length=0, pad=10, labelsize=16, colors=COLOR_TEXT_MUTED)
    return _to_png(fig)


# -------------------- Auswertung --------------------


@dataclass
class AuthorStats:
    name: str
    posts: int = 0
    stars: int = 0
    best: StarPost | None = None


def author_stats(posts: list[StarPost]) -> list[AuthorStats]:
    """Pro Autor: Anzahl Sternbrett-Posts, Summe ⭐, bester Post – sortiert nach Posts."""
    stats: dict[str, AuthorStats] = {}
    for p in posts:
        s = stats.setdefault(p.author_key, AuthorStats(p.author_name))
        s.posts += 1
        if p.stars is not None:
            s.stars += p.stars
            if s.best is None or p.stars > (s.best.stars or 0):
                s.best = p
    return sorted(stats.values(), key=lambda s: (-s.posts, -s.stars, s.name.lower()))


def ranked(posts: list[StarPost]) -> list[StarPost]:
    """Posts mit bekannter Sternanzahl, meiste ⭐ zuerst (bei Gleichstand der ältere)."""
    return sorted((p for p in posts if p.stars is not None), key=lambda p: (-p.stars, p.created_at))


def scope_label(year: int | None) -> str:
    return str(year) if year else "Alle Zeiten"


# -------------------- View --------------------


class SternbrettView(BaseView):
    """Jahr wählen (Select) + Ansicht wechseln (Buttons)."""

    error_text = "❌ Das Sternbrett hat sich verheddert."

    def __init__(self, cog: "Sternbrett", owner_id: int, years: list[int], year: int | None, tab: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.owner_id = owner_id
        self.year = year
        self.tab = tab
        self.message: discord.Message | None = None

        self.year_select = discord.ui.Select(
            placeholder="Jahr wählen",
            options=[discord.SelectOption(label="Alle Zeiten", value="all", emoji="🌟", default=year is None)]
            + [
                discord.SelectOption(label=str(y), value=str(y), emoji="📅", default=y == year)
                for y in sorted(years, reverse=True)[:24]
            ],
            row=0,
        )
        self.year_select.callback = self.on_year
        self.add_item(self.year_select)

        self.tab_buttons: dict[str, discord.ui.Button] = {}
        for key, (label, emoji) in TABS.items():
            button = discord.ui.Button(label=label, emoji=emoji, row=1)
            button.callback = self._tab_callback(key)
            self.tab_buttons[key] = button
            self.add_item(button)
        self._sync_components()

    def _sync_components(self):
        for key, button in self.tab_buttons.items():
            active = key == self.tab
            button.style = discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary
            button.disabled = active
        for option in self.year_select.options:
            option.default = option.value == (str(self.year) if self.year else "all")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Mach dir dein eigenes `/sternbrett` 😉", ephemeral=True
            )
            return False
        return True

    def _tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.tab = key
            await self._update(interaction)

        return callback

    async def on_year(self, interaction: discord.Interaction):
        value = self.year_select.values[0]
        self.year = None if value == "all" else int(value)
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self._sync_components()
        embeds, file = await self.cog.build_page(interaction.guild, self.tab, self.year)
        await interaction.edit_original_response(embeds=embeds, attachments=[file], view=self)
        self.cog.log("Sternbrett page", interaction, tab=self.tab, year=self.year)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


# -------------------- Cog --------------------


class Sternbrett(BaseCog):
    """Cog: /sternbrett – statistische Auswertung des Sternbretts."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.db = bot.db
        self.create_table()
        self._sync_lock = asyncio.Lock()
        self._sync_task: asyncio.Task | None = None
        # Fortschritt eines laufenden Abrufs: (erledigt, gesamt)
        self._progress = (0, 0)
        # message_id -> (läuft ab [monotonic], frische Bild-URL) für den Siegerpost
        self._image_cache: dict[int, tuple[float, str | None]] = {}

    def create_table(self):
        """Cache-Tabelle: ein Eintrag pro Originalnachricht im Sternbrett."""
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS star_stats(
                message_id INTEGER PRIMARY KEY,
                board_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_name TEXT,
                author_id INTEGER,
                author_name TEXT,
                created_at INTEGER NOT NULL,
                stars INTEGER,
                content TEXT,
                image_url TEXT,
                status INTEGER NOT NULL DEFAULT 0,
                dirty INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER
            )
            """
        )
        self.db.commit()

    async def cog_load(self):
        self._sync_task = asyncio.create_task(self._initial_sync())

    async def cog_unload(self):
        if self._sync_task:
            self._sync_task.cancel()

    async def _initial_sync(self):
        await self.bot.wait_until_ready()
        try:
            await self.sync()
        except Exception as e:
            self.log("Initial sync failed", error=e)

    # -------------------- Synchronisation --------------------

    def pending_count(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM star_stats WHERE status=? AND (stars IS NULL OR dirty=1)", (STATUS_OK,)
        ).fetchone()[0]

    async def sync(self):
        """Neue Sternbrett-Posts einlesen und offene/geänderte Originale laden."""
        async with self._sync_lock:
            started = time.monotonic()
            new_posts = await self._crawl_board()
            fetched = await self._fetch_originals()
            if new_posts or fetched:
                self.log("Sync done", new_posts=new_posts, fetched=fetched,
                         seconds=round(time.monotonic() - started, 1))

    async def _crawl_board(self) -> int:
        """Liest den Sternbrett-Channel ab dem zuletzt bekannten Post (beim ersten Mal komplett)."""
        channel = self.bot.get_channel(STERNBRETT_CHANNEL_ID) or await self.bot.fetch_channel(STERNBRETT_CHANNEL_ID)
        last = self.db.execute("SELECT MAX(board_id) FROM star_stats").fetchone()[0]
        after = discord.Object(id=last) if last else None

        added = 0
        async for message in channel.history(limit=None, after=after, oldest_first=True):
            data = parse_board_message(message)
            if data is None:
                continue
            cur = self.db.execute(
                """
                INSERT OR IGNORE INTO star_stats
                    (message_id, board_id, channel_id, channel_name, author_id, author_name,
                     created_at, content, image_url)
                VALUES (:message_id, :board_id, :channel_id, :channel_name, :author_id, :author_name,
                        :created_at, :content, :image_url)
                """,
                data,
            )
            added += cur.rowcount
        self.db.commit()
        return added

    async def _fetch_originals(self) -> int:
        """Lädt Originale ohne (aktuelle) Sternanzahl nach."""
        rows = self.db.execute(
            "SELECT message_id, channel_id FROM star_stats WHERE status=? AND (stars IS NULL OR dirty=1) "
            "ORDER BY created_at DESC",
            (STATUS_OK,),
        ).fetchall()
        if not rows:
            return 0

        self._progress = (0, len(rows))
        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch_one(message_id: int, channel_id: int):
            async with semaphore:
                await self._refresh_original(message_id, channel_id)
                done, total = self._progress
                self._progress = (done + 1, total)
                if (done + 1) % 50 == 0:
                    self.db.commit()

        try:
            await asyncio.gather(*(fetch_one(m, c) for m, c in rows))
        finally:
            self.db.commit()
            self._progress = (0, 0)
        return len(rows)

    async def _refresh_original(self, message_id: int, channel_id: int):
        """Holt ein Original und speichert ⭐-Anzahl und Autor."""
        try:
            message = await self.bot.get_partial_messageable(channel_id).fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            self.db.execute(
                "UPDATE star_stats SET status=?, dirty=0, updated_at=? WHERE message_id=?",
                (STATUS_GONE, int(time.time()), message_id),
            )
            return
        except discord.HTTPException as e:
            # Vorübergehender Fehler -> beim nächsten Sync erneut versuchen
            self.log("Fetch original failed", message_id=message_id, error=e)
            return

        stars = next((r.count for r in message.reactions if str(r.emoji) == "⭐"), 0)
        image = next(
            (a.url for a in message.attachments if (a.content_type or "").startswith("image/")), None
        )
        self.db.execute(
            """
            UPDATE star_stats
            SET stars=?, author_id=?, author_name=?, content=?, image_url=COALESCE(?, image_url),
                channel_name=COALESCE(?, channel_name), dirty=0, updated_at=?
            WHERE message_id=?
            """,
            (
                stars,
                message.author.id,
                message.author.display_name,
                message.content,
                image,
                getattr(message.channel, "name", None),
                int(time.time()),
                message_id,
            ),
        )
        if image:
            self._image_cache[message_id] = (time.monotonic() + 3600, image)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._mark_dirty(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._mark_dirty(payload)

    async def _mark_dirty(self, payload: discord.RawReactionActionEvent):
        """⭐ auf ein bekanntes Original -> Sternanzahl beim nächsten Sync neu laden."""
        if str(payload.emoji) != "⭐":
            return
        self.db.execute(
            "UPDATE star_stats SET dirty=1 WHERE message_id=? AND status=?", (payload.message_id, STATUS_OK)
        )
        self.db.commit()

    # -------------------- Daten laden --------------------

    def load_posts(self, guild: discord.Guild | None) -> list[StarPost]:
        rows = self.db.execute(
            "SELECT message_id, channel_id, channel_name, author_id, author_name, created_at, stars, "
            "content, image_url, status FROM star_stats ORDER BY created_at"
        ).fetchall()
        guild_id = guild.id if guild else 0
        posts = []
        for message_id, channel_id, channel_name, author_id, author_name, created_at, stars, content, image_url, status in rows:
            name = author_name or "Unbekannt"
            member = guild.get_member(author_id) if guild and author_id else None
            posts.append(
                StarPost(
                    message_id=message_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    author_key=str(author_id) if author_id else f"name:{name.lower()}",
                    author_name=member.display_name if member else name,
                    created_at=datetime.fromtimestamp(created_at, TZ),
                    stars=stars if status == STATUS_OK else None,
                    content=content or "",
                    image_url=image_url,
                    jump_url=f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
                )
            )
        return posts

    async def fresh_image_url(self, post: StarPost) -> str | None:
        """Aktuelle Bild-URL (Discord-CDN-Links laufen ab) – max. ein Abruf pro Stunde."""
        if post.image_url is None:
            return None
        cached = self._image_cache.get(post.message_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        url = None
        try:
            message = await self.bot.get_partial_messageable(post.channel_id).fetch_message(post.message_id)
            url = next((a.url for a in message.attachments if (a.content_type or "").startswith("image/")), None)
            url = url or next((e.thumbnail.url or e.image.url for e in message.embeds if e.thumbnail or e.image), None)
        except discord.HTTPException:
            pass
        self._image_cache[post.message_id] = (time.monotonic() + 3600, url)
        return url

    # -------------------- Seiten --------------------

    async def build_page(self, guild: discord.Guild | None, tab: str, year: int | None) -> tuple[list[discord.Embed], discord.File]:
        """Baut Embed(s) + Diagramm für eine Ansicht."""
        all_posts = self.load_posts(guild)
        posts = [p for p in all_posts if year is None or p.created_at.year == year]
        if not posts:
            raise UserError(f"🦗 Im Sternbrett gibt es für **{scope_label(year)}** nichts.")

        builder = {"top": self._page_top, "people": self._page_people, "overview": self._page_overview}[tab]
        embeds, chart = await builder(posts, year, all_posts)

        pending = self.pending_count()
        footer = f"{fmt_int(len(all_posts))} Sternbrett-Posts ausgewertet"
        if pending:
            footer += f" · {fmt_int(pending)} werden noch geladen"
        embeds[-1].set_footer(text=footer)
        embeds[-1].timestamp = discord.utils.utcnow()
        embeds[0].set_image(url=f"attachment://{CHART_FILENAME}")
        return embeds, discord.File(chart, filename=CHART_FILENAME)

    async def _page_top(self, posts: list[StarPost], year: int | None, _all: list[StarPost]):
        top = ranked(posts)[:TOP_N]
        if not top:
            raise UserError("⏳ Die Sternanzahlen werden gerade noch geladen, probier's gleich nochmal.")

        lines = []
        for i, p in enumerate(top):
            lines.append(
                f"{rank_label(i)} **{p.stars} ⭐** · **{discord.utils.escape_markdown(p.author_name)}** "
                f"in <#{p.channel_id}> · {discord.utils.format_dt(p.created_at, 'd')}\n"
                f"└ {md_snippet(p, 70)} [↗]({p.jump_url})"
            )
        embed = discord.Embed(
            title=f"🏆 Die meistgesternten Posts · {scope_label(year)}",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )

        rows = [
            (p.author_name, f"{p.created_at:%d.%m.%Y} · {snippet(p, 60)}", p.stars, f"{p.stars} ★")
            for p in top
        ]
        chart = await asyncio.to_thread(
            render_ranking,
            f"Top {len(top)} · {scope_label(year)}",
            f"Meistgesternte Posts aus {fmt_int(len(posts))} Sternbrett-Einträgen",
            rows,
        )

        # Zweites Embed: der Siegerpost groß
        winner = top[0]
        hero = discord.Embed(
            title=f"🥇 Post {'des Jahres ' + str(year) if year else 'aller Zeiten'}",
            url=winner.jump_url,
            description=truncate(winner.content, 1500) or None,
            color=EMBED_COLOR,
        )
        hero.set_author(name=f"{winner.author_name} · {winner.stars} ⭐")
        image = await self.fresh_image_url(winner)
        if image:
            hero.set_image(url=image)
        return [embed, hero], chart

    async def _page_people(self, posts: list[StarPost], year: int | None, _all: list[StarPost]):
        stats = author_stats(posts)
        top = stats[:TOP_N]

        lines = []
        for i, s in enumerate(top):
            avg = f" · Ø {fmt_decimal(s.stars / s.posts)}" if s.stars else ""
            best = f" · Bester: [{s.best.stars} ⭐]({s.best.jump_url})" if s.best else ""
            lines.append(
                f"{rank_label(i)} **{discord.utils.escape_markdown(s.name)}** — "
                f"**{fmt_int(s.posts)}** Posts · {fmt_int(s.stars)} ⭐{avg}{best}"
            )
        embed = discord.Embed(
            title=f"👑 Sternsammler · {scope_label(year)}",
            description=(
                f"Wer am häufigsten im Sternbrett landet – **{fmt_int(len(stats))}** Leute "
                f"haben es {'in ' + str(year) if year else 'bisher'} geschafft.\n\n" + "\n".join(lines)
            ),
            color=EMBED_COLOR,
        )

        # Sternekönig: meiste ⭐ insgesamt (kann vom Post-König abweichen)
        star_king = max(stats, key=lambda s: s.stars)
        if star_king.stars:
            embed.add_field(name="⭐ Meiste Sterne", value=f"**{discord.utils.escape_markdown(star_king.name)}**\n{fmt_int(star_king.stars)} ⭐", inline=True)
        regulars = [s for s in stats if s.posts >= 3 and s.stars]
        if regulars:
            best_avg = max(regulars, key=lambda s: s.stars / s.posts)
            embed.add_field(
                name="🎯 Bester Schnitt (ab 3 Posts)",
                value=f"**{discord.utils.escape_markdown(best_avg.name)}**\nØ {fmt_decimal(best_avg.stars / best_avg.posts)} ⭐",
                inline=True,
            )

        rows = [
            (s.name, f"{fmt_int(s.stars)} Sterne gesamt", s.posts, f"{s.posts} Posts")
            for s in top
        ]
        chart = await asyncio.to_thread(
            render_ranking,
            f"Sternsammler · {scope_label(year)}",
            "Meiste Posts im Sternbrett",
            rows,
        )
        return [embed], chart

    async def _page_overview(self, posts: list[StarPost], year: int | None, all_posts: list[StarPost]):
        now = datetime.now(TZ)
        known = [p for p in posts if p.stars is not None]
        total_stars = sum(p.stars for p in known)

        embed = discord.Embed(
            title=f"📊 Sternbrett-Überblick · {scope_label(year)}",
            color=EMBED_COLOR,
        )
        embed.add_field(name="📌 Posts", value=f"**{fmt_int(len(posts))}**", inline=True)
        embed.add_field(name="⭐ Sterne", value=f"**{fmt_int(total_stars)}**", inline=True)
        if known:
            embed.add_field(name="📈 Ø pro Post", value=f"**{fmt_decimal(total_stars / len(known))}** ⭐", inline=True)
            record = ranked(known)[0]
            embed.add_field(
                name="🏆 Rekord",
                value=f"[{record.stars} ⭐]({record.jump_url}) von **{discord.utils.escape_markdown(record.author_name)}**",
                inline=True,
            )
        embed.add_field(name="👥 Leute", value=f"**{fmt_int(len({p.author_key for p in posts}))}**", inline=True)

        weekday = Counter(p.created_at.weekday() for p in posts).most_common(1)[0][0]
        hour = Counter(p.created_at.hour for p in posts).most_common(1)[0][0]
        embed.add_field(name="🕒 Prime Time", value=f"**{WEEKDAYS[weekday]}s**\n{hour}–{hour + 1} Uhr", inline=True)

        channels = Counter(p.channel_id for p in posts).most_common(5)
        embed.add_field(
            name="💬 Sternigste Channels",
            value="\n".join(f"<#{cid}> · **{fmt_int(n)}**" for cid, n in channels),
            inline=False,
        )

        if year is None:
            # Alle Zeiten: Posts pro Jahr; Ausreißer-Jahre vor dem Sternbrett zählen mit
            by_year = Counter(p.created_at.year for p in posts)
            years = list(range(min(by_year), max(by_year) + 1))
            values = [by_year.get(y, 0) for y in years]
            labels = [f"{y}\nläuft noch" if y == now.year else str(y) for y in years]
            muted = {i for i, y in enumerate(years) if y == now.year}
            best = max(years, key=lambda y: by_year.get(y, 0))
            embed.description = f"Das stärkste Sternbrett-Jahr war **{best}** mit **{fmt_int(by_year[best])}** Posts."
            chart = await asyncio.to_thread(
                render_columns, "Sternbrett-Posts pro Jahr",
                f"{fmt_int(len(posts))} Posts · {fmt_int(total_stars)} Sterne", labels, values, muted,
            )
        else:
            by_month = Counter(p.created_at.month for p in posts)
            values = [by_month.get(m, 0) for m in range(1, 13)]
            muted = {now.month - 1} if year == now.year else set()
            best = max(range(12), key=lambda m: values[m])
            embed.description = f"Stärkster Monat: **{MONTHS[best]}** mit **{fmt_int(values[best])}** Posts."
            chart = await asyncio.to_thread(
                render_columns, f"Sternbrett-Posts {year}",
                f"{fmt_int(len(posts))} Posts · {fmt_int(total_stars)} Sterne", MONTHS, values, muted,
            )
        return [embed], chart

    # -------------------- /sternbrett --------------------

    def known_years(self) -> list[int]:
        rows = self.db.execute("SELECT DISTINCT created_at FROM star_stats").fetchall()
        return sorted({datetime.fromtimestamp(r[0], TZ).year for r in rows})

    async def year_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        return [
            app_commands.Choice(name=str(y), value=y)
            for y in sorted(self.known_years(), reverse=True)
            if current in str(y)
        ][:25]

    @app_commands.command(
        name="sternbrett",
        description="Statistiken zum Sternbrett: meistgesternte Posts, Sternsammler und Überblick pro Jahr (nur Admin).",
        extras={"error": "Das Sternbrett ist gerade sternhagelvoll 🤷"},
    )
    @app_commands.describe(
        jahr="Kalenderjahr (leer = alle Zeiten)",
        ansicht="Was soll angezeigt werden? (Standard: Top 10)",
        privat="Nur für dich sichtbar anzeigen (Standard: für alle sichtbar)",
    )
    @app_commands.choices(
        ansicht=[app_commands.Choice(name=f"{emoji} {label}", value=key) for key, (label, emoji) in TABS.items()]
    )
    @app_commands.autocomplete(jahr=year_autocomplete)
    @app_commands.guild_only()
    @owner_only("Das Sternbrett auswerten darf nur der Chef 🤷")
    async def sternbrett(
        self,
        interaction: discord.Interaction,
        jahr: int | None = None,
        ansicht: str = "top",
        privat: bool = False,
    ):
        # Erster Komplett-Abruf läuft noch -> Fortschritt anzeigen statt halber Zahlen
        if self._sync_lock.locked() and self.pending_count() >= PENDING_WARN:
            done, total = self._progress
            progress = f" ({fmt_int(done)}/{fmt_int(total)} Posts)" if total else ""
            raise UserError(
                f"⏳ Ich lese das Sternbrett gerade ein{progress}. Probier's in ein paar Minuten nochmal."
            )

        await interaction.response.defer(thinking=True, ephemeral=privat)
        if not self._sync_lock.locked():
            await self.sync()

        if jahr is not None and jahr not in self.known_years():
            raise UserError(f"🦗 Im Sternbrett gibt es für **{jahr}** nichts.")

        embeds, file = await self.build_page(interaction.guild, ansicht, jahr)
        view = SternbrettView(self, interaction.user.id, self.known_years(), jahr, ansicht)
        view.message = await interaction.followup.send(
            embeds=embeds, file=file, view=view, allowed_mentions=NO_MENTIONS, wait=True
        )
        self.log("Sternbrett sent", interaction, tab=ansicht, year=jahr)


async def setup(bot: commands.Bot):
    await bot.add_cog(Sternbrett(bot))
