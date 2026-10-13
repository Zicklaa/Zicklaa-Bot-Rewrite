"""Kleine Helfer, die mehrere Cogs brauchen (Text, Zeit, Nachrichten-Links)."""

import re
from datetime import datetime
from urllib.parse import urlparse

import discord
from dateutil import tz

# Antworten des Bots sollen nie jemanden pingen
NO_MENTIONS = discord.AllowedMentions.none()

ELLIPSIS = "…"

# -------------------- Text --------------------


def truncate(text: str | None, max_len: int) -> str:
    """Kürzt Text auf max_len Zeichen, möglichst an einer Wortgrenze, mit „…“."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    cut = text[: max(0, max_len - len(ELLIPSIS))]
    space = cut.rfind(" ")
    if space >= int(max_len * 0.6):
        cut = cut[:space]
    return cut.rstrip() + ELLIPSIS if cut else text[:max_len]


def split_text(text: str | None, max_len: int) -> list[str]:
    """Teilt Text bevorzugt an Absätzen/Zeilen/Satzenden; kein Teil ist länger als max_len."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return [text] if text else []

    chunks, buf = [], ""
    for piece in re.split(r"(\n\n|\n|(?<=[.!?])\s+)", text):
        if len(buf) + len(piece) <= max_len:
            buf += piece
            continue
        if buf.strip():
            chunks.append(buf.strip())
        # Einzelstück länger als das Limit -> hart schneiden
        while len(piece) > max_len:
            chunks.append(piece[:max_len])
            piece = piece[max_len:]
        buf = piece
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


# -------------------- Zeit --------------------


def format_local(when: datetime | float, seconds: bool = True) -> str:
    """Datum/Timestamp in lokaler Zeit, z. B. ``31.12.2025, 23:59:00``."""
    if not isinstance(when, datetime):
        when = datetime.fromtimestamp(when, tz=tz.tzlocal())
    return when.astimezone(tz.tzlocal()).strftime(
        "%d.%m.%Y, %H:%M:%S" if seconds else "%d.%m.%Y %H:%M"
    )


# -------------------- Nachrichten --------------------


def parse_message_link(link: str) -> tuple[int, int, int]:
    """Zerlegt einen Nachrichtenlink in (guild_id, channel_id, message_id).

    Akzeptiert discord.com sowie die ptb-/canary-Subdomains.
    Raises:
        ValueError: wenn es kein gültiger Nachrichtenlink ist.
    """
    try:
        url = urlparse(link.strip())
        parts = [p for p in url.path.split("/") if p]
        if not url.netloc.endswith("discord.com") or len(parts) < 4 or parts[0] != "channels":
            raise ValueError
        return int(parts[1]), int(parts[2]), int(parts[3])
    except (ValueError, AttributeError):
        raise ValueError(f"Ungültiger Nachrichtenlink: {link}") from None


async def fetch_channel(bot: discord.Client, channel_id: int):
    """Channel/Thread aus dem Cache, sonst per API (kann NotFound/Forbidden werfen)."""
    return bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)


async def fetch_message(bot: discord.Client, channel_id: int, message_id: int) -> discord.Message:
    """Lädt eine Nachricht anhand von Channel- und Message-ID."""
    channel = await fetch_channel(bot, channel_id)
    return await channel.fetch_message(message_id)
