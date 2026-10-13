"""/lyrics full|link – aktueller LastFM-Song eines Users mit Lyrics bzw. Genius-Link."""

import asyncio
import os

import discord
import lyricsgenius
import pylast
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError, in_channels
from utils.helpers import truncate
from utils.settings import TEST_CHANNEL_ID

# -------------------- Konfiguration --------------------

ALLOWED_CHANNEL_IDS = (
    608746970340786282,  # f2-in-concert
    870242601125675008,  # f2-in-concert thread
    TEST_CHANNEL_ID,
)

LASTFM_API_KEY = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET = os.environ["LASTFM_API_SECRET"]
LYRICS_API_KEY = os.environ["LYRICS_KEY"]

ERROR_TEXT = "❌ Fehler beim Abrufen von Daten."
MAX_LYRICS_LEN = 5000
lyrics_channels = in_channels(
    *ALLOWED_CHANNEL_IDS, message="❌ Dieser Command ist nur in bestimmten Channels erlaubt."
)

# -------------------- Helpers (synchron, laufen im Thread) --------------------


def build_song_embed(user: pylast.User, track: pylast.Track, username: str) -> discord.Embed:
    """Baut das Basis-Embed für einen LastFM-Track."""
    try:
        duration = track.get_duration() or 0
    except Exception:
        duration = 0
    minutes, seconds = divmod(duration // 1000, 60)

    artist, title = str(track.get_artist()), str(track.get_name())
    artist_url = "https://www.last.fm/de/music/" + artist.replace(" ", "+")
    song_url = artist_url + "/_/" + title.replace(" ", "+").replace("/", "%2F")

    embed = discord.Embed(color=0x1D9BF0)
    embed.set_author(
        name=username,
        icon_url=user.get_image() or None,
        url=f"https://www.last.fm/user/{username}",
    )
    cover = track.get_cover_image()
    if cover:
        embed.set_thumbnail(url=str(cover))

    embed.add_field(name="Titel", value=f"[{title}]({song_url})", inline=False)
    embed.add_field(name="Artist", value=f"[{artist}]({artist_url})", inline=True)

    album = str(track.get_album() or "").replace(artist, "").replace(" - ", "")
    embed.set_footer(
        text=f"Album: {album} | Duration: {minutes}:{seconds:02d} | Plays: {track.get_playcount()}"
    )
    return embed


def add_lyrics(embed: discord.Embed, song) -> None:
    """Hängt die kompletten Lyrics an (auf mehrere Felder verteilt)."""
    if not (song and song.lyrics):
        embed.add_field(name="Lyrics", value="❌ Keine Lyrics gefunden.", inline=False)
        return
    # Genius liefert Kopf- und Fußzeilen mit -> abschneiden
    text = song.lyrics.replace("EmbedShare URLCopyEmbedCopy", "").partition("Read More")[2].strip()
    # Ein Embed fasst insgesamt max. 6000 Zeichen -> sehr lange Lyrics kappen
    text = truncate(text, MAX_LYRICS_LEN)
    for start in range(0, len(text), 1020):
        embed.add_field(name="Lyrics", value=text[start:start + 1020], inline=False)


def add_link(embed: discord.Embed, song, track: pylast.Track) -> None:
    """Hängt nur den Link zur Genius-Seite an."""
    value = f"[{track}]({song.url})" if song and song.url else "❌ Kein Link gefunden."
    embed.add_field(name="Lyrics-Link", value=value, inline=False)


# -------------------- Cog --------------------


class Lyrics(BaseCog):
    """Cog: /lyrics."""

    lyrics = app_commands.Group(name="lyrics", description="Zeigt Lyrics vom aktuellen LastFM-Song")

    def _fetch_embed(self, username: str, full: bool) -> discord.Embed | None:
        """Holt Song (LastFM) und Lyrics (Genius); None, wenn der User nichts hört."""
        network = pylast.LastFMNetwork(api_key=LASTFM_API_KEY, api_secret=LASTFM_API_SECRET)
        user = network.get_user(username)
        track = user.get_now_playing()
        if not track:
            return None

        embed = build_song_embed(user, track, username)
        field = "Lyrics" if full else "Lyrics-Link"
        try:
            song = lyricsgenius.Genius(LYRICS_API_KEY).search_song(
                title=str(track.get_name()), artist=str(track.get_artist())
            )
            if full:
                add_lyrics(embed, song)
            else:
                add_link(embed, song, track)
        except Exception as e:
            embed.add_field(name=field, value=f"❌ Fehler beim Abrufen von {field}.", inline=False)
            self.log("Genius error", target=username, error=e)
        return embed

    async def _send(self, interaction: discord.Interaction, username: str, full: bool):
        """Gemeinsame Logik für /lyrics full und /lyrics link."""
        await interaction.response.defer(thinking=True)

        # pylast und lyricsgenius arbeiten synchron -> in einen Thread auslagern
        embed = await asyncio.to_thread(self._fetch_embed, username, full)
        if embed is None:
            raise UserError("🎧 Dieser User hört gerade nichts.")

        await interaction.followup.send(embed=embed)
        self.log("Lyrics sent", interaction, target=username)

    @lyrics.command(name="full", description="Aktuellen Song + Lyrics anzeigen", extras={"error": ERROR_TEXT})
    @lyrics_channels
    async def lyrics_full(self, interaction: discord.Interaction, username: str):
        await self._send(interaction, username, full=True)

    @lyrics.command(name="link", description="Aktuellen Song + Genius-Link anzeigen", extras={"error": ERROR_TEXT})
    @lyrics_channels
    async def lyrics_link(self, interaction: discord.Interaction, username: str):
        await self._send(interaction, username, full=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Lyrics(bot))
