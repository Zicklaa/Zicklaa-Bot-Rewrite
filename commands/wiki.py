"""/wiki suchen|artikel|zufall – Wikipedia-Artikel als Embed.

- Autocomplete für Artikeltitel
- Ergebnis-Dropdown, Aktualisieren- und Link-Button
- Zusammenfassungen werden 2 Stunden gecacht
"""

import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, BaseView, UserError
from utils.helpers import truncate

# -------------------- Konfiguration --------------------

WIKI_LANGS = ("de", "en")
SEARCH_LIMIT = 5
AUTOCOMPLETE_LIMIT = 10
SUMMARY_TTL = 2 * 60 * 60  # Sekunden

WIKI_ICON = "https://upload.wikimedia.org/wikipedia/commons/6/63/Wikipedia-logo.png"
# Wikimedia verlangt einen aussagekräftigen User-Agent
HEADERS = {"User-Agent": "ZicklaaBotRewrite/1.0 (https://github.com/Zicklaa/Zicklaa-Bot-Rewrite)"}

lang_choices = app_commands.choices(lang=[
    app_commands.Choice(name="Deutsch", value="de"),
    app_commands.Choice(name="English", value="en"),
])


def normalize_lang(lang: str | None) -> str:
    lang = (lang or "de").lower()
    return lang if lang in WIKI_LANGS else "de"


# -------------------- Rendering --------------------


def page_url(summary: dict[str, Any], lang: str) -> str:
    """Link zum Artikel (Desktop bevorzugt), sonst zur Wikipedia-Startseite."""
    urls = summary.get("content_urls") or {}
    for variant in ("desktop", "mobile"):
        url = (urls.get(variant) or {}).get("page")
        if url:
            return url
    return f"https://{lang}.wikipedia.org/"


def build_summary_embed(summary: dict[str, Any], lang: str) -> discord.Embed:
    extract = truncate(summary.get("extract"), 1800) or "*— keine Zusammenfassung vorhanden —*"
    embed = discord.Embed(
        title=summary.get("title") or "Wikipedia",
        url=page_url(summary, lang),
        description=extract,
        color=discord.Color.blurple(),
    )
    embed.set_author(name=f"Wikipedia • {lang.upper()}", icon_url=WIKI_ICON, url=f"https://{lang}.wikipedia.org/")

    image = (summary.get("originalimage") or {}).get("source") or (summary.get("thumbnail") or {}).get("url")
    if image:
        embed.set_thumbnail(url=image)
    if summary.get("description"):
        embed.add_field(
            name="Beschreibung", value=discord.utils.escape_markdown(summary["description"]), inline=False
        )

    # Footer: Zeitpunkt der letzten Änderung, falls bekannt
    embed.set_footer(text=f"Quelle: {lang}.wikipedia.org")
    try:
        embed.timestamp = datetime.fromisoformat(summary["timestamp"].replace("Z", "+00:00"))
        embed.set_footer(text="Letzte Änderung")
    except (KeyError, ValueError, AttributeError):
        pass
    return embed


# -------------------- Interaktive View --------------------


class SearchResultsView(BaseView):
    """Dropdown mit den Suchtreffern + Buttons zum Aktualisieren und Öffnen."""

    error_text = "❌ Konnte den Artikel nicht laden."

    def __init__(self, cog: "Wiki", lang: str, results: list[dict[str, Any]], initial: dict[str, Any]):
        super().__init__(timeout=300)
        self.cog = cog
        self.lang = lang
        self.current = initial

        self.selector.options = [
            discord.SelectOption(
                label=truncate(r.get("title") or r.get("key") or "?", 100),
                description=truncate(r.get("description") or r.get("excerpt") or "", 90),
                value=truncate(r.get("title") or r.get("key") or "?", 100),
            )
            for r in results[:25]
        ]
        # Link-Buttons brauchen ihre URL schon beim Erstellen
        self.open_btn = discord.ui.Button(
            label="🌐 Wikipedia öffnen", style=discord.ButtonStyle.link, url=page_url(initial, lang)
        )
        self.add_item(self.open_btn)

    async def _show(self, interaction: discord.Interaction, title: str, *, bypass_cache: bool = False):
        """Lädt einen Artikel und zeigt ihn in der bestehenden Nachricht."""
        self.current = await self.cog.get_summary(self.lang, title, bypass_cache=bypass_cache)
        self.open_btn.url = page_url(self.current, self.lang)
        await interaction.response.edit_message(embed=build_summary_embed(self.current, self.lang), view=self)

    @discord.ui.select(placeholder="Anderen Artikel auswählen …")
    async def selector(self, interaction: discord.Interaction, select: discord.ui.Select):
        await self._show(interaction, select.values[0])

    @discord.ui.button(label="🔄 Aktualisieren", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, self.current.get("title") or "", bypass_cache=True)


# -------------------- Cog --------------------


class Wiki(BaseCog):
    """Cog: /wiki."""

    wiki = app_commands.Group(name="wiki", description="Wikipedia-Artikel als hübsches Embed anzeigen")

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # (lang, titel) -> (läuft ab [monotonic], Zusammenfassung)
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    # ---------- API ----------

    async def _get_json(self, url: str, **params) -> dict[str, Any]:
        async with self.bot.session.get(url, params=params, headers=HEADERS) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {url}: {(await resp.text())[:300]}")
            return await resp.json()

    async def search_titles(self, lang: str, query: str, limit: int) -> list[dict[str, Any]]:
        data = await self._get_json(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/title", q=query, limit=limit)
        return data.get("pages") or []

    async def get_summary(self, lang: str, title: str, *, bypass_cache: bool = False) -> dict[str, Any]:
        """Zusammenfassung eines Artikels (aus dem Cache, solange er frisch ist)."""
        key = (lang, title.lower().strip())
        cached = self._cache.get(key)
        if cached and not bypass_cache and cached[0] > time.monotonic():
            return cached[1]

        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"
        data = await self._get_json(url, redirect="true")
        self._remember(key, data)
        return data

    def _remember(self, key: tuple[str, str], data: dict[str, Any]):
        self._cache[key] = (time.monotonic() + SUMMARY_TTL, data)

    async def _send_article(
        self, interaction: discord.Interaction, lang: str, data: dict[str, Any],
        results: list[dict[str, Any]] | None = None,
    ):
        """Schickt einen Artikel samt View; ohne Suchtreffer enthält das Dropdown nur ihn selbst."""
        results = results or [{"title": data.get("title", "?"), "description": data.get("description", "")}]
        await interaction.followup.send(
            embed=build_summary_embed(data, lang), view=SearchResultsView(self, lang, results, data)
        )

    # ---------- Autocomplete ----------

    async def title_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not current:
            return []
        try:
            # Sprache aus den bereits ausgefüllten Optionen übernehmen
            lang = normalize_lang(getattr(interaction.namespace, "lang", None))
            pages = await self.search_titles(lang, current, AUTOCOMPLETE_LIMIT)
        except Exception as e:
            self.log("autocomplete_failed", interaction, current=current, error=e)
            return []

        choices = []
        for p in pages:
            title = p.get("title") or p.get("key")
            if title and len(title) <= 100:
                desc = p.get("description") or p.get("excerpt") or ""
                choices.append(app_commands.Choice(name=truncate(f"{title} — {desc}", 100), value=title))
        return choices[:25]

    # ---------- Commands ----------

    @wiki.command(
        name="suchen",
        description="Suche Wikipedia-Artikel und wähle aus Ergebnissen.",
        extras={"error": "❌ Fehler bei der Suche."},
    )
    @app_commands.describe(query="Suchbegriff", lang="Sprache (de/en)")
    @lang_choices
    async def search(self, interaction: discord.Interaction, query: str, lang: Optional[str] = "de"):
        lang = normalize_lang(lang)
        await interaction.response.defer(thinking=True)

        results = await self.search_titles(lang, query, SEARCH_LIMIT)
        if not results:
            raise UserError("😕 Keine Treffer.")
        first_title = results[0].get("title") or results[0].get("key")
        if not first_title:
            raise UserError("😕 Konnte den ersten Treffer nicht lesen.")

        await self._send_article(interaction, lang, await self.get_summary(lang, first_title), results)
        self.log("search_success", interaction, query=query, lang=lang, first_title=first_title)

    @wiki.command(
        name="artikel",
        description="Zeigt einen bestimmten Wikipedia-Artikel.",
        extras={"error": "❌ Artikel konnte nicht geladen werden."},
    )
    @app_commands.describe(title="Exakter Titel (Autocomplete hilft)", lang="Sprache (de/en)")
    @lang_choices
    @app_commands.autocomplete(title=title_autocomplete)
    async def article(self, interaction: discord.Interaction, title: str, lang: Optional[str] = "de"):
        lang = normalize_lang(lang)
        await interaction.response.defer(thinking=True)

        await self._send_article(interaction, lang, await self.get_summary(lang, title))
        self.log("article", interaction, title=title, lang=lang)

    @wiki.command(
        name="zufall",
        description="Zeigt einen zufälligen Wikipedia-Artikel.",
        extras={"error": "❌ Zufallsartikel konnte nicht geladen werden."},
    )
    @app_commands.describe(lang="Sprache (de/en)")
    @lang_choices
    async def random_article(self, interaction: discord.Interaction, lang: Optional[str] = "de"):
        lang = normalize_lang(lang)
        await interaction.response.defer(thinking=True)

        data = await self._get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/random/summary")
        title = data.get("title", "?")
        self._remember((lang, title.lower()), data)

        await self._send_article(interaction, lang, data)
        self.log("random", interaction, title=title, lang=lang)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wiki(bot))
