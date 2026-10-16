"""/translate – übersetzt Text per Google Translate.

Übersetzt wird über den Endpunkt translate.googleapis.com (client=gtx). Die
Scraping-Seite translate.google.com/m, die deep_translator nutzt, blockt Google
für Server-IPs mit einer CAPTCHA-Seite. deep_translator liefert nur noch die
(statische) Sprachenliste.
"""

import asyncio
from dataclasses import dataclass

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES

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

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATE_TIMEOUT = 20  # Sekunden
MAX_CHARS = 5000

# Quellsprache automatisch erkennen lassen
AUTO = "auto"

# Vorschläge im Autocomplete, solange noch nichts getippt wurde
DEFAULT_SUGGESTIONS = (AUTO, "de", "en", "fr", "es", "it", "tr", "nl", "pl", "pt", "ru")


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
    """Baut die Sprachtabellen aus der Sprachenliste von deep_translator."""
    name_to_code = {normalize(name): normalize(code) for name, code in GOOGLE_LANGUAGES_TO_CODES.items()}
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
        self.langs = load_langs()
        self.log("Cog loaded", languages=len(self.langs.name_to_code))

    async def google_translate(self, text: str, source: str, target: str) -> tuple[str, str]:
        """Übersetzt Text; gibt (Übersetzung, erkannte Quellsprache) zurück."""
        params = {"client": "gtx", "sl": source, "tl": target, "dt": "t"}
        try:
            # POST, damit auch lange Texte nicht an der URL-Länge scheitern
            async with self.bot.session.post(
                TRANSLATE_URL, params=params, data={"q": text},
                timeout=aiohttp.ClientTimeout(total=TRANSLATE_TIMEOUT),
            ) as resp:
                if resp.status == 429:
                    raise UserError("⏳ Google Translate bremst gerade, probier's gleich nochmal.")
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except asyncio.TimeoutError:
            raise UserError("⏳ Google Translate antwortet nicht, probier's später nochmal.") from None

        # data[0]: Liste von Satz-Abschnitten [Übersetzung, Original, …]; data[2]: erkannte Sprache
        translated = "".join(part[0] for part in data[0] or [] if part and part[0])
        detected = normalize(data[2]) if len(data) > 2 and isinstance(data[2], str) else source
        return translated, detected

    def resolve_lang(self, user_input: str) -> str | None:
        """Sprachcode zu einer Eingabe (Code oder Name), sonst None."""
        key = normalize(user_input)
        if key in (AUTO, "automatisch"):
            return AUTO
        return key if key in self.langs.code_to_name else self.langs.name_to_code.get(key)

    def lang_name(self, code: str) -> str:
        return "automatisch erkennen" if code == AUTO else self.langs.code_to_name.get(code, code)

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
            app_commands.Choice(name=f"{code} — {self.lang_name(code)}"[:100], value=code)
            for code in codes
        ][:25]

    @app_commands.command(
        name="translate",
        description="Übersetzt einen Text von einer Sprache in eine andere.",
        extras={"error": "❌ Konnte nicht übersetzen."},
    )
    @app_commands.describe(
        from_lang="Quellsprache (z. B. de, en, fr oder auto – Autocomplete verfügbar)",
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
        if not source or not target or target == AUTO:
            raise UserError("❌ Ungültige Sprachcodes angegeben.")
        if len(text) > MAX_CHARS:
            raise UserError(f"❌ Zu lang: maximal {MAX_CHARS} Zeichen.")

        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        translated, detected = await self.google_translate(text, source, target)

        source_label = f"{flag(detected)} {self.lang_name(detected)}"
        if source == AUTO:
            source_label += " (erkannt)"
        embed = discord.Embed(
            title=f"{source_label} → {flag(target)} {self.lang_name(target)}",
            color=discord.Color.green(),
        )
        embed.add_field(name="Original", value=truncate(text, 1000), inline=False)
        embed.add_field(name="Übersetzung", value=truncate(translated, 1000) or "—", inline=False)
        embed.set_footer(text="Google Translate")

        await interaction.followup.send(embed=embed)
        self.log("Translation successful", interaction, source=detected, target=target)


async def setup(bot: commands.Bot):
    await bot.add_cog(Translate(bot))
