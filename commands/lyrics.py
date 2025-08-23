# lyrics_cog.py
# -*- coding: utf-8 -*-
"""
Lyrics-Cog (discord.py 2.x, Slash-Commands)
- /lyrics full <lastfm-username> : Aktueller Song + Lyrics als Embed
- /lyrics link <lastfm-username> : Aktueller Song + Lyrics-Link als Embed
"""

from __future__ import annotations

import logging
import os
import discord
import lyricsgenius
import pylast
from discord import app_commands
from discord.ext import commands

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Lyrics")

# -------------------- Settings --------------------

ALLOWED_CHANNEL_IDS: list[int] = [
    608746970340786282,  # f2-in-concert
    870242601125675008,  # f2-in-concert thread
    567411189336768532,  # testchannel (Dev-Channel)
]

# API Keys aus .env laden
LASTFM_API_KEY = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET = os.environ["LASTFM_API_SECRET"]
LYRICS_API_KEY = os.environ["LYRICS_KEY"]


class Lyrics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------- Helpers --------------------

    def _get_lastfm_user(self, username: str) -> pylast.User:
        """Erstellt eine LastFM-User-Instanz."""
        try:
            network = pylast.LastFMNetwork(
                api_key=LASTFM_API_KEY,
                api_secret=LASTFM_API_SECRET,
            )
            return network.get_user(username)
        except Exception as e:
            raise RuntimeError(f"LastFM-User konnte nicht geladen werden: {e}")

    def _build_song_embed(self, user: pylast.User, track: pylast.Track, username: str) -> discord.Embed:
        """Baut ein Basis-Embed für einen LastFM-Track."""
        try:
            dur = track.get_duration() or 0
        except Exception:
            dur = 0
        minutes, seconds = divmod(int(dur / 1000), 60)

        artisturl = "https://www.last.fm/de/music/" + \
            str(track.get_artist()).replace(" ", "+")
        songurl = artisturl + "/_/" + \
            str(track.get_name()).replace(" ", "+").replace("/", "%2F")

        name = f"[{track.get_name()}]({songurl})"
        artist = f"[{track.get_artist()}]({artisturl})"

        embed = discord.Embed(color=0x1D9BF0)

        if user.get_image():
            embed.set_author(
                name=username,
                icon_url=user.get_image(),
                url=f"https://www.last.fm/user/{username}",
            )
        else:
            embed.set_author(
                name=username, url=f"https://www.last.fm/user/{username}")

        if track.get_cover_image():
            embed.set_thumbnail(url=str(track.get_cover_image()))

        embed.add_field(name="Titel", value=name, inline=False)
        embed.add_field(name="Artist", value=artist, inline=True)

        album = str(track.get_album() or "").replace(
            str(track.get_artist()), "").replace(" - ", "")
        footer = f"Album: {album} | Duration: {minutes}:{seconds:02d} | Plays: {track.get_playcount()}"
        embed.set_footer(text=footer)

        return embed

    # -------------------- Slash-Commands --------------------

    lyrics = app_commands.Group(
        name="lyrics", description="Zeigt Lyrics vom aktuellen LastFM-Song")

    @lyrics.command(name="full", description="Aktuellen Song + Lyrics anzeigen")
    async def lyrics_full(self, interaction: discord.Interaction, username: str):
        if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
            await interaction.response.send_message(
                "❌ Dieser Command ist nur in bestimmten Channels erlaubt.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            user = self._get_lastfm_user(username)
            track = user.get_now_playing()
            if not track:
                await interaction.followup.send("🎧 Dieser User hört gerade nichts.")
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "User not playing",
                    interaction.user,
                    interaction.user.id,
                    command="lyrics full",
                    target=username,
                )
                return

            embed = self._build_song_embed(user, track, username)

            # Lyrics via Genius
            try:
                genius = lyricsgenius.Genius(LYRICS_API_KEY)
                song = genius.search_song(
                    title=str(track.get_name()), artist=str(track.get_artist()))
                if song and song.lyrics:
                    lyrics_text = song.lyrics.replace(
                        "EmbedShare URLCopyEmbedCopy", "")
                    lyrics_text = lyrics_text.partition("Read More")[2].strip()
                    while lyrics_text:
                        part, lyrics_text = lyrics_text[:1020], lyrics_text[1020:]
                        embed.add_field(
                            name="Lyrics", value=part, inline=False)
                else:
                    embed.add_field(
                        name="Lyrics", value="❌ Keine Lyrics gefunden.", inline=False)
            except Exception as e:
                embed.add_field(
                    name="Lyrics", value="❌ Fehler beim Abrufen von Lyrics.", inline=False)
                log_event(
                    logger,
                    logging.ERROR,
                    self.__class__.__name__,
                    "Genius error",
                    interaction.user,
                    interaction.user.id,
                    command="lyrics full",
                    target=username,
                    error=e,
                    exc_info=True,
                )

            await interaction.followup.send(embed=embed)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Lyrics full sent",
                interaction.user,
                interaction.user.id,
                command="lyrics full",
                target=username,
            )

        except Exception as e:
            await interaction.followup.send("❌ Fehler beim Abrufen von Daten.", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Lyrics full failed",
                interaction.user,
                interaction.user.id,
                command="lyrics full",
                target=username,
                error=e,
                exc_info=True,
            )

    @lyrics.command(name="link", description="Aktuellen Song + Genius-Link anzeigen")
    async def lyrics_link(self, interaction: discord.Interaction, username: str):
        if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
            await interaction.response.send_message(
                "❌ Dieser Command ist nur in bestimmten Channels erlaubt.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            user = self._get_lastfm_user(username)
            track = user.get_now_playing()
            if not track:
                await interaction.followup.send("🎧 Dieser User hört gerade nichts.")
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "User not playing",
                    interaction.user,
                    interaction.user.id,
                    command="lyrics link",
                    target=username,
                )
                return

            embed = self._build_song_embed(user, track, username)

            try:
                genius = lyricsgenius.Genius(LYRICS_API_KEY)
                song = genius.search_song(
                    title=str(track.get_name()), artist=str(track.get_artist()))
                if song and song.url:
                    embed.add_field(
                        name="Lyrics-Link", value=f"[{track}]({song.url})", inline=False)
                else:
                    embed.add_field(name="Lyrics-Link",
                                    value="❌ Kein Link gefunden.", inline=False)
            except Exception as e:
                embed.add_field(
                    name="Lyrics-Link", value="❌ Fehler beim Abrufen des Links.", inline=False)
                log_event(
                    logger,
                    logging.ERROR,
                    self.__class__.__name__,
                    "Genius error",
                    interaction.user,
                    interaction.user.id,
                    command="lyrics link",
                    target=username,
                    error=e,
                    exc_info=True,
                )

            await interaction.followup.send(embed=embed)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "Lyrics link sent",
                interaction.user,
                interaction.user.id,
                command="lyrics link",
                target=username,
            )

        except Exception as e:
            await interaction.followup.send("❌ Fehler beim Abrufen von Daten.", ephemeral=True)
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "Lyrics link failed",
                interaction.user,
                interaction.user.id,
                command="lyrics link",
                target=username,
                error=e,
                exc_info=True,
            )


# -------------------- Setup --------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Lyrics(bot))
