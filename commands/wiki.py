# wiki_cog.py
# -*- coding: utf-8 -*-
"""
Wikipedia-Cog (discord.py 2.x)
- /wiki suchen <query> [lang]
- /wiki artikel <title> [lang]
- /wiki zufall [lang]
Features:
- Async REST-API (aiohttp)
- Autocomplete für Titel
- Ergebnis-Dropdown + Refresh + Link-Button
- TTL-Cache zur Rate-Reduktion
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Wiki")

# -------------------- Konfiguration --------------------

WIKI_LANGS: Tuple[str, ...] = ("de", "en")
SEARCH_LIMIT_DEFAULT = 5
AUTOCOMPLETE_LIMIT = 10
SUMMARY_TTL = timedelta(hours=2)

WIKI_ICON = "https://upload.wikimedia.org/wikipedia/commons/6/63/Wikipedia-logo.png"


# -------------------- Cache --------------------

@dataclass
class CacheEntry:
    data: Dict[str, Any]
    ts: datetime


class TTLCache:
    def __init__(self, ttl: timedelta):
        self.ttl = ttl
        self._d: Dict[Tuple[str, str], CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: Tuple[str, str]) -> Optional[Dict[str, Any]]:
        async with self._lock:
            entry = self._d.get(key)
            if not entry:
                return None
            if datetime.now(timezone.utc) - entry.ts > self.ttl:
                self._d.pop(key, None)
                return None
            return entry.data

    async def set(self, key: Tuple[str, str], data: Dict[str, Any]):
        async with self._lock:
            self._d[key] = CacheEntry(data=data, ts=datetime.now(timezone.utc))


# -------------------- HTTP Client --------------------

async def http_get_json(session: aiohttp.ClientSession, url: str, **params) -> Dict[str, Any]:
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"HTTP {resp.status} for {url}: {text[:300]}")
        return await resp.json()


async def wiki_summary(session: aiohttp.ClientSession, lang: str, title: str) -> Dict[str, Any]:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
    return await http_get_json(session, url, redirect="true")


async def wiki_search_titles(session: aiohttp.ClientSession, lang: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    url = f"https://{lang}.wikipedia.org/w/rest.php/v1/search/title"
    data = await http_get_json(session, url, q=query, limit=limit)
    return data.get("pages", []) or []


async def wiki_random_summary(session: aiohttp.ClientSession, lang: str) -> Dict[str, Any]:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/random/summary"
    return await http_get_json(session, url)


# -------------------- Rendering --------------------

def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip() + "…"


def _page_url_from_summary(summary: Dict[str, Any], lang: str) -> str:
    return (
        (((summary.get("content_urls") or {}).get("desktop") or {}).get("page"))
        or (summary.get("content_urls", {}).get("mobile", {}) or {}).get("page")
        or f"https://{lang}.wikipedia.org/"
    )


def build_summary_embed(summary: Dict[str, Any], lang: str) -> discord.Embed:
    title = summary.get("title") or "Wikipedia"
    page_url = _page_url_from_summary(summary, lang)
    desc = summary.get("description")
    extract = summary.get("extract") or ""
    extract = _truncate(
        extract.strip(), 1800) if extract else "*— keine Zusammenfassung vorhanden —*"

    embed = discord.Embed(
        title=title,
        url=page_url,
        description=extract,
        color=discord.Color.blurple(),
    )
    embed.set_author(name=f"Wikipedia • {lang.upper()}",
                     icon_url=WIKI_ICON, url=f"https://{lang}.wikipedia.org/")

    image = (summary.get("originalimage") or {}).get(
        "source") or (summary.get("thumbnail") or {}).get("url")
    if image:
        embed.set_thumbnail(url=image)

    if desc:
        embed.add_field(name="Beschreibung",
                        value=discord.utils.escape_markdown(desc), inline=False)

    ts = summary.get("timestamp")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            embed.timestamp = dt
            embed.set_footer(text="Letzte Änderung")
        except Exception:
            embed.set_footer(text=f"Quelle: {lang}.wikipedia.org")
    else:
        embed.set_footer(text=f"Quelle: {lang}.wikipedia.org")

    return embed


# -------------------- Interaktive View --------------------

class SearchResultsView(discord.ui.View):
    """Dropdown + Buttons (Refresh & Link). Link-Button bekommt URL beim Erstellen und wird bei Änderungen aktualisiert."""

    def __init__(self, cog: "Wiki", lang: str, results: List[Dict[str, Any]], initial: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cog = cog
        self.lang = lang
        self.results = results
        self.current = initial

        # --- Select ---
        options = []
        for r in results[:25]:
            title = r.get("title") or r.get("key") or "?"
            desc = r.get("description") or r.get("excerpt") or ""
            options.append(discord.SelectOption(label=_truncate(
                title, 100), description=_truncate(desc, 90), value=title))
        self.selector.options = options

        # --- Link-Button (URL MUSS JETZT gesetzt sein) ---
        self.open_btn = discord.ui.Button(
            label="🌐 Wikipedia öffnen",
            style=discord.ButtonStyle.link,
            url=_page_url_from_summary(initial, lang),
        )
        self.add_item(self.open_btn)

    def _update_link_button(self):
        # URL neu setzen, wenn Article gewechselt/refreshed wurde
        self.open_btn.url = _page_url_from_summary(self.current, self.lang)

    @discord.ui.select(placeholder="Anderen Artikel auswählen …")
    async def selector(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            title = select.values[0]
            data = await self.cog.get_summary(self.lang, title)
            self.current = data
            self._update_link_button()
            embed = build_summary_embed(data, self.lang)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.cog.__class__.__name__,
                "select_failed",
                interaction.user,
                interaction.user.id,
                error=e,
                exc_info=True,
            )
            if interaction.response.is_done():
                await interaction.followup.send("❌ Konnte den Artikel nicht laden.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Konnte den Artikel nicht laden.", ephemeral=True)

    @discord.ui.button(label="🔄 Aktualisieren", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            title = self.current.get("title") or ""
            fresh = await self.cog.get_summary(self.lang, title, bypass_cache=True)
            self.current = fresh
            self._update_link_button()
            embed = build_summary_embed(fresh, self.lang)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.cog.__class__.__name__,
                "refresh_failed",
                interaction.user,
                interaction.user.id,
                error=e,
                exc_info=True,
            )
            if interaction.response.is_done():
                await interaction.followup.send("❌ Refresh fehlgeschlagen.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Refresh fehlgeschlagen.", ephemeral=True)


# -------------------- Cog --------------------

class Wiki(commands.Cog):
    """Wikipedia-Integration mit hübschen Embeds und Interaktionen."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = TTLCache(SUMMARY_TTL)

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "cog_loaded",
        )

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "cog_unloaded",
        )

    # --------- Cache-aware Helper ---------

    async def get_summary(self, lang: str, title: str, *, bypass_cache: bool = False) -> Dict[str, Any]:
        assert self.session is not None
        key = (lang, title.lower().strip())
        if not bypass_cache:
            cached = await self.cache.get(key)
            if cached:
                return cached
        data = await wiki_summary(self.session, lang, title)
        await self.cache.set(key, data)
        return data

    # --------- Autocomplete ---------

    async def title_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        try:
            lang = "de"
            # type: ignore[union-attr]
            for opt in interaction.data.get("options", []):
                if isinstance(opt, dict) and opt.get("name") in ("lang", "sprache"):
                    lang = (opt.get("value") or "de").lower()
            lang = lang if lang in WIKI_LANGS else "de"

            if not current:
                return []

            assert self.session is not None
            pages = await wiki_search_titles(self.session, lang, current, limit=AUTOCOMPLETE_LIMIT)
            choices: List[app_commands.Choice[str]] = []
            for p in pages:
                title = p.get("title") or p.get("key")
                if not title:
                    continue
                desc = p.get("description") or p.get("excerpt") or ""
                choices.append(app_commands.Choice(
                    name=_truncate(f"{title} — {desc}", 100), value=title))
            return choices[:25]
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "autocomplete_failed",
                interaction.user,
                interaction.user.id,
                current=current,
                error=e,
                exc_info=True,
            )
            return []

    # -------------------- Commands --------------------

    wiki = app_commands.Group(
        name="wiki", description="Wikipedia-Artikel als hübsches Embed anzeigen")

    @wiki.command(name="suchen", description="Suche Wikipedia-Artikel und wähle aus Ergebnissen.")
    @app_commands.describe(query="Suchbegriff", lang="Sprache (de/en)")
    @app_commands.choices(lang=[app_commands.Choice(name="Deutsch", value="de"),
                                app_commands.Choice(name="English", value="en")])
    async def search(self, interaction: discord.Interaction, query: str, lang: Optional[str] = "de"):
        lang = (lang or "de").lower()
        if lang not in WIKI_LANGS:
            lang = "de"

        await interaction.response.defer(thinking=True)
        try:
            assert self.session is not None
            results = await wiki_search_titles(self.session, lang, query, limit=SEARCH_LIMIT_DEFAULT)
            if not results:
                await interaction.followup.send("😕 Keine Treffer.", ephemeral=True)
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "search_no_results",
                    interaction.user,
                    interaction.user.id,
                    query=query,
                    lang=lang,
                )
                return

            first_title = results[0].get("title") or results[0].get("key")
            if not first_title:
                await interaction.followup.send("😕 Konnte den ersten Treffer nicht lesen.", ephemeral=True)
                return

            data = await self.get_summary(lang, first_title)
            embed = build_summary_embed(data, lang)
            view = SearchResultsView(self, lang, results, data)
            await interaction.followup.send(embed=embed, view=view)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "search_success",
                interaction.user,
                interaction.user.id,
                query=query,
                lang=lang,
                first_title=first_title,
            )
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "search_failed",
                interaction.user,
                interaction.user.id,
                query=query,
                lang=lang,
                error=e,
                exc_info=True,
            )
            await interaction.followup.send("❌ Fehler bei der Suche.", ephemeral=True)

    @wiki.command(name="artikel", description="Zeigt einen bestimmten Wikipedia-Artikel.")
    @app_commands.describe(title="Exakter Titel (Autocomplete hilft)", lang="Sprache (de/en)")
    @app_commands.choices(lang=[app_commands.Choice(name="Deutsch", value="de"),
                                app_commands.Choice(name="English", value="en")])
    @app_commands.autocomplete(title=title_autocomplete)
    async def article(self, interaction: discord.Interaction, title: str, lang: Optional[str] = "de"):
        lang = (lang or "de").lower()
        if lang not in WIKI_LANGS:
            lang = "de"

        await interaction.response.defer(thinking=True)
        try:
            data = await self.get_summary(lang, title)
            embed = build_summary_embed(data, lang)
            view = SearchResultsView(
                self, lang, [{"title": title, "description": data.get("description", "")}], data)
            await interaction.followup.send(embed=embed, view=view)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "article",
                interaction.user,
                interaction.user.id,
                title=title,
                lang=lang,
            )
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "article_failed",
                interaction.user,
                interaction.user.id,
                title=title,
                lang=lang,
                error=e,
                exc_info=True,
            )
            await interaction.followup.send("❌ Artikel konnte nicht geladen werden.", ephemeral=True)

    @wiki.command(name="zufall", description="Zeigt einen zufälligen Wikipedia-Artikel.")
    @app_commands.describe(lang="Sprache (de/en)")
    @app_commands.choices(lang=[app_commands.Choice(name="Deutsch", value="de"),
                                app_commands.Choice(name="English", value="en")])
    async def random_article(self, interaction: discord.Interaction, lang: Optional[str] = "de"):
        lang = (lang or "de").lower()
        if lang not in WIKI_LANGS:
            lang = "de"

        await interaction.response.defer(thinking=True)
        try:
            assert self.session is not None
            data = await wiki_random_summary(self.session, lang)
            title = data.get("title", "?")
            await self.cache.set((lang, title.lower()), data)
            embed = build_summary_embed(data, lang)
            view = SearchResultsView(
                self, lang, [{"title": title, "description": data.get("description", "")}], data)
            await interaction.followup.send(embed=embed, view=view)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "random",
                interaction.user,
                interaction.user.id,
                title=title,
                lang=lang,
            )
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "random_failed",
                interaction.user,
                interaction.user.id,
                lang=lang,
                error=e,
                exc_info=True,
            )
            await interaction.followup.send("❌ Zufallsartikel konnte nicht geladen werden.", ephemeral=True)


# -------------------- Setup --------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Wiki(bot))
