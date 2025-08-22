# translate_cog.py
# -*- coding: utf-8 -*-
"""
Translate-Cog (discord.py 2.x, deep_translator)
- /translate from:<sprache> to:<sprache> text:<text> [ephemeral]
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from deep_translator import GoogleTranslator

logger = logging.getLogger("ZicklaaBot.Translate")

FLAG = {
    "de": "🇩🇪", "en": "🇬🇧", "us": "🇺🇸", "fr": "🇫🇷", "es": "🇪🇸", "it": "🇮🇹",
    "pt": "🇵🇹", "br": "🇧🇷", "nl": "🇳🇱", "pl": "🇵🇱", "tr": "🇹🇷", "ru": "🇷🇺",
    "ja": "🇯🇵", "zh-cn": "🇨🇳", "zh-tw": "🇹🇼", "sv": "🇸🇪", "no": "🇳🇴",
    "da": "🇩🇰", "fi": "🇫🇮", "cs": "🇨🇿", "ro": "🇷🇴", "hu": "🇭🇺",
}


def normalize(s: str) -> str:
    return s.strip().lower().replace("_", "-")


@dataclass
class LangTables:
    name_to_code: Dict[str, str]
    code_to_name: Dict[str, str]
    all_display: List[str]


class Translate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.langs: LangTables | None = None

    async def cog_load(self):
        def _load_langs() -> LangTables:
            try:
                raw = GoogleTranslator.get_supported_languages(as_dict=True)  # type: ignore[attr-defined]
            except TypeError:
                raw = GoogleTranslator().get_supported_languages(as_dict=True)

            name_to_code = {normalize(name): normalize(code) for name, code in raw.items()}
            aliases = {"deutsch": "de", "englisch": "en", "german": "de", "english": "en",
                       "chinese": "zh-cn", "chinesisch": "zh-cn", "brazilian portuguese": "pt"}
            for k, v in aliases.items():
                name_to_code.setdefault(normalize(k), normalize(v))

            code_to_name: Dict[str, str] = {}
            for name, code in name_to_code.items():
                code_to_name.setdefault(code, name)

            all_display = sorted(set(list(name_to_code.keys()) + list(code_to_name.keys())))
            return LangTables(name_to_code, code_to_name, all_display)

        self.langs = await asyncio.to_thread(_load_langs)
        logger.info("Translate-Cog geladen. Sprachen: %d", len(self.langs.name_to_code) if self.langs else -1)

    def resolve_lang(self, user_input: str) -> str | None:
        if not self.langs:
            return None
        key = normalize(user_input)
        if key in self.langs.code_to_name:
            return key
        return self.langs.name_to_code.get(key)

    async def lang_autocomplete(self, _: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not self.langs:
            return []
        cur = normalize(current)
        if not cur:
            seeds = ["de", "en", "fr", "es", "it", "tr", "nl", "pl", "pt", "ru"]
            return [app_commands.Choice(name=f"{code} — {self.langs.code_to_name.get(code, code)}", value=code) for code in seeds]
        choices: List[app_commands.Choice[str]] = []
        for token in self.langs.all_display:
            if cur in token:
                code = token if token in self.langs.code_to_name else self.langs.name_to_code.get(token, token)
                name = self.langs.code_to_name.get(code, code)
                label = f"{code} — {name}"
                if all(c.value != code for c in choices):
                    choices.append(app_commands.Choice(name=label[:100], value=code))
            if len(choices) >= 25:
                break
        return choices

    async def translate_text(self, text: str, target: str, source: str) -> Tuple[str, str]:
        def _work():
            trans = GoogleTranslator(source=source, target=target).translate(text)
            return trans, source
        return await asyncio.to_thread(_work)

    @app_commands.command(
        name="translate",
        description="Übersetzt einen Text von einer Sprache in eine andere."
    )
    @app_commands.describe(
        from_lang="Quellsprache (z. B. de, en, fr – Autocomplete verfügbar)",
        to_lang="Zielsprache (z. B. de, en, fr – Autocomplete verfügbar)",
        text="Zu übersetzender Text",
        ephemeral="Antwort nur für dich anzeigen"
    )
    @app_commands.autocomplete(to_lang=lang_autocomplete, from_lang=lang_autocomplete)
    async def translate_cmd(
        self,
        interaction: discord.Interaction,
        from_lang: str,
        to_lang: str,
        text: str,
        ephemeral: bool = False,
    ):
        if not self.langs:
            await interaction.response.send_message("❌ Sprachenliste noch nicht geladen.", ephemeral=True)
            return

        target = self.resolve_lang(to_lang)
        source = self.resolve_lang(from_lang)
        if not target or not source:
            await interaction.response.send_message("❌ Ungültige Sprachcodes angegeben.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=ephemeral)

        try:
            translated, detected = await self.translate_text(text, target, source)
            src_code = detected or source
            dst_code = target
            src_name = self.langs.code_to_name.get(src_code, src_code)
            dst_name = self.langs.code_to_name.get(dst_code, dst_code)

            def flag(code: str) -> str:
                return FLAG.get(code, FLAG.get(code.split("-")[0], ""))

            embed = discord.Embed(
                title=f"{flag(src_code)} {src_name} → {flag(dst_code)} {dst_name}",
                color=discord.Color.green(),
            )
            embed.add_field(name="Original", value=text[:1000] + ("…" if len(text) > 1000 else ""), inline=False)
            embed.add_field(name="Übersetzung", value=translated[:1000] + ("…" if len(translated) > 1000 else ""), inline=False)
            embed.set_footer(text="Google Translate")

            await interaction.followup.send(embed=embed)
            logger.info("Translate OK by %s: %s → %s", interaction.user, src_code, dst_code)

        except Exception as e:
            logger.exception("Translate Fehler: %s", e)
            await interaction.followup.send("❌ Konnte nicht übersetzen.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Translate(bot))
