"""/translate – übersetzt Text per Google Translate (deep_translator)."""

import asyncio
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands
from deep_translator import GoogleTranslator

from utils.base import BaseCog, UserError
from utils.helpers import truncate

FLAG = {
    "de": "🇩🇪", "en": "🇬🇧", "us": "🇺🇸", "fr": "🇫🇷", "es": "🇪🇸", "it": "🇮🇹",
    "pt": "🇵🇹", "br": "🇧🇷", "nl": "🇳🇱", "pl": "🇵🇱", "tr": "🇹🇷", "ru": "🇷🇺",
    "ja": "🇯🇵", "zh-cn": "🇨🇳", "zh-tw": "🇹🇼", "sv": "🇸🇪", "no": "🇳🇴",
    "da": "🇩🇰", "fi": "🇫🇮", "cs": "🇨🇿", "ro": "🇷🇴", "hu": "🇭🇺",
}

# Zusätzliche Namen, unter denen Sprachen gefunden werden
ALIASES = {
    "deutsch": "de", "englisch": "en", "german": "de", "english": "en",
    "chinese": "zh-cn", "chinesisch": "zh-cn", "brazilian portuguese": "pt",
}

TRANSLATE_TIMEOUT = 20  # Sekunden

# Vorschläge im Autocomplete, solange noch nichts getippt wurde
DEFAULT_SUGGESTIONS = ("de", "en", "fr", "es", "it", "tr", "nl", "pl", "pt", "ru")


def normalize(s: str) -> str:
    return s.strip().lower().replace("_", "-")


def flag(code: str) -> str:
    """Flaggen-Emoji zum Sprachcode (leer, wenn unbekannt)."""
    return FLAG.get(code, FLAG.get(code.split("-")[0], ""))


@dataclass
class LangTables:
    name_to_code: dict[str, str]
    code_to_name: dict[str, str]
    all_display: list[str]  # alle Namen und Codes, sortiert (fürs Autocomplete)


def load_langs() -> LangTables:
    """Lädt die unterstützten Sprachen von Google Translate (synchron)."""
    raw = GoogleTranslator().get_supported_languages(as_dict=True)
    name_to_code = {normalize(name): normalize(code) for name, code in raw.items()}
    for name, code in ALIASES.items():
        name_to_code.setdefault(name, code)

    code_to_name: dict[str, str] = {}
    for name, code in name_to_code.items():
        code_to_name.setdefault(code, name)

    return LangTables(name_to_code, code_to_name, sorted({*name_to_code, *code_to_name}))


class Translate(BaseCog):
    """Cog: /translate from:<sprache> to:<sprache> text:<text> [ephemeral]."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.langs: LangTables | None = None

    async def cog_load(self):
        self.langs = await asyncio.to_thread(load_langs)
        self.log("Cog loaded", languages=len(self.langs.name_to_code))

    def resolve_lang(self, user_input: str) -> str | None:
        """Sprachcode zu einer Eingabe (Code oder Name), sonst None."""
        key = normalize(user_input)
        return key if key in self.langs.code_to_name else self.langs.name_to_code.get(key)

    async def lang_autocomplete(self, _: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not self.langs:
            return []
        current = normalize(current)
        if current:
            # Treffer in Namen oder Codes -> eindeutige Codes in Fundreihenfolge
            tokens = (t for t in self.langs.all_display if current in t)
            codes = dict.fromkeys(
                t if t in self.langs.code_to_name else self.langs.name_to_code[t] for t in tokens
            )
        else:
            codes = DEFAULT_SUGGESTIONS
        return [
            app_commands.Choice(name=f"{code} — {self.langs.code_to_name.get(code, code)}"[:100], value=code)
            for code in codes
        ][:25]

    @app_commands.command(
        name="translate",
        description="Übersetzt einen Text von einer Sprache in eine andere.",
        extras={"error": "❌ Konnte nicht übersetzen."},
    )
    @app_commands.describe(
        from_lang="Quellsprache (z. B. de, en, fr – Autocomplete verfügbar)",
        to_lang="Zielsprache (z. B. de, en, fr – Autocomplete verfügbar)",
        text="Zu übersetzender Text",
        ephemeral="Antwort nur für dich anzeigen",
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
            raise UserError("❌ Sprachenliste noch nicht geladen.")
        source, target = self.resolve_lang(from_lang), self.resolve_lang(to_lang)
        if not source or not target:
            raise UserError("❌ Ungültige Sprachcodes angegeben.")

        await interaction.response.defer(thinking=True, ephemeral=ephemeral)

        # deep_translator arbeitet synchron und ohne eigenes Timeout -> Thread + Zeitlimit
        translated = await asyncio.wait_for(
            asyncio.to_thread(GoogleTranslator(source=source, target=target).translate, text),
            timeout=TRANSLATE_TIMEOUT,
        )

        names = self.langs.code_to_name
        embed = discord.Embed(
            title=f"{flag(source)} {names.get(source, source)} → {flag(target)} {names.get(target, target)}",
            color=discord.Color.green(),
        )
        embed.add_field(name="Original", value=truncate(text, 1000), inline=False)
        embed.add_field(name="Übersetzung", value=truncate(translated, 1000) or "—", inline=False)
        embed.set_footer(text="Google Translate")

        await interaction.followup.send(embed=embed)
        self.log("Translation successful", interaction, source=source, target=target)


async def setup(bot: commands.Bot):
    await bot.add_cog(Translate(bot))
