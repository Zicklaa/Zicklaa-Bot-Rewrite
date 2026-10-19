"""Lädt alle Nachrichten eines Servers in den Korpus.

- Alle Text-, Voice- und Stage-Channels + aktive und archivierte Threads (auch Foren)
- Pro Channel wird gespeichert, bis zu welcher Nachricht geladen wurde → jeder Lauf
  (auch ein abgebrochener) macht genau dort weiter; der erste Lauf lädt alles
- Discord erlaubt pro Channel nur ~1 Request (100 Nachrichten) pro Sekunde, über
  mehrere Channels hinweg skaliert es → mehrere Channels parallel, die größten zuerst
"""

import asyncio
import sqlite3
import time
from collections import deque
from dataclasses import dataclass

import discord

CONCURRENCY = 8  # Channels gleichzeitig (Discord-Limit global: 50 Requests/s)
CHANNEL_RATE = 95.0  # erwartete Nachrichten/s pro Channel, bis echte Werte vorliegen
KEEP_TYPES = (discord.MessageType.default, discord.MessageType.reply)

Source = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread


def snowflake_ts(snowflake: int) -> float:
    return ((snowflake >> 22) + discord.utils.DISCORD_EPOCH) / 1000


@dataclass
class Job:
    channel: Source
    name: str
    last_id: int  # bis hierhin schon im Korpus
    estimate: int  # erwartete neue Nachrichten
    start_ts: float
    end_ts: float
    fetched: int = 0
    cur_ts: float = 0.0
    state: str = "pending"  # pending | running | done | skipped | error
    error: str | None = None
    started_at: float = 0.0

    @property
    def fraction(self) -> float:
        """Wie weit die Zeitachse des Channels schon geladen ist (0–1)."""
        if self.state == "done":
            return 1.0
        span = self.end_ts - self.start_ts
        if span <= 0 or not self.cur_ts:
            return 0.0
        return min(max((self.cur_ts - self.start_ts) / span, 0.0), 1.0)

    @property
    def rate(self) -> float:
        elapsed = time.monotonic() - self.started_at
        if self.state == "running" and elapsed > 20 and self.fetched > 500:
            return self.fetched / elapsed
        return CHANNEL_RATE

    @property
    def remaining(self) -> float:
        """Geschätzte noch zu ladende Nachrichten (Startschätzung, mit der Zeit hochgerechnet)."""
        if self.state not in ("pending", "running"):
            return 0.0
        left = max(self.estimate - self.fetched, 0)
        covered = self.cur_ts - self.start_ts
        if self.fetched >= 1000 and covered > 0:
            extrapolated = self.fetched * max(self.end_ts - self.cur_ts, 0) / covered
            weight = self.fraction
            left = weight * extrapolated + (1 - weight) * left
        return left


class Scraper:
    def __init__(self, guild: discord.Guild, corpus: sqlite3.Connection):
        self.guild = guild
        self.db = corpus
        self.jobs: list[Job] = []
        self.status = ""  # was gerade beim Suchen passiert
        self.channels = self.threads = self.up_to_date = 0
        self.skipped: list[str] = []
        self.stored = 0  # in diesem Lauf neu gespeicherte Nachrichten (ohne Bots/System)
        self._samples: deque[tuple[float, int]] = deque()

    # ---------- Kennzahlen ----------

    @property
    def fetched(self) -> int:
        return sum(j.fetched for j in self.jobs)

    def rate(self) -> float:
        """Nachrichten/s über die letzten 30 Sekunden."""
        now, total = time.monotonic(), self.fetched
        self._samples.append((now, total))
        while len(self._samples) > 2 and now - self._samples[0][0] > 30:
            self._samples.popleft()
        t0, n0 = self._samples[0]
        return (total - n0) / (now - t0) if now > t0 else 0.0

    def progress(self) -> tuple[float, float | None]:
        """(Anteil fertig, geschätzte Restsekunden)."""
        remaining = sum(j.remaining for j in self.jobs)
        done = self.fetched
        fraction = done / (done + remaining) if done + remaining else 1.0
        open_jobs = [j for j in self.jobs if j.state in ("pending", "running")]
        if not open_jobs:
            return fraction, 0.0
        # Engpass ist entweder der größte einzelne Channel oder die Summe über alle Slots
        slowest = max(j.remaining / j.rate for j in open_jobs)
        overall = remaining / (CONCURRENCY * CHANNEL_RATE)
        return fraction, max(slowest, overall)

    # ---------- 1. Channels finden ----------

    def _perms(self, channel) -> discord.Permissions | None:
        try:
            return channel.permissions_for(self.guild.me)
        except discord.ClientException:  # Thread ohne bekannten Parent
            return None

    def _readable(self, channel) -> bool:
        perms = self._perms(channel)
        return bool(perms and perms.read_messages and perms.read_message_history)

    async def discover(self):
        known = dict(self.db.execute("SELECT id, last_id FROM channels"))
        sources: list[Source] = []
        for channel in self.guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
                if self._readable(channel):
                    sources.append(channel)
                else:
                    self.skipped.append(f"#{channel.name}")
        self.channels = len(sources)

        threads: dict[int, discord.Thread] = {}
        self.status = "aktive Threads"
        for thread in await self.guild.active_threads():
            threads[thread.id] = thread
        parents = [c for c in (*self.guild.text_channels, *self.guild.forums) if self._readable(c)]
        for i, parent in enumerate(parents, start=1):
            self.status = f"archivierte Threads in #{parent.name} ({i}/{len(parents)})"
            try:
                async for thread in parent.archived_threads(limit=None):
                    threads[thread.id] = thread
                perms = self._perms(parent)
                if isinstance(parent, discord.TextChannel) and perms and perms.manage_threads:
                    async for thread in parent.archived_threads(private=True, limit=None):
                        threads[thread.id] = thread
            except discord.HTTPException:
                pass  # kein Zugriff auf die Thread-Liste dieses Channels
        thread_list = [t for t in threads.values() if self._readable(t)]
        self.threads = len(thread_list)

        # Was schon vollständig im Korpus ist, braucht keinen einzigen Request
        todo = []
        for source in (*sources, *thread_list):
            last_id = known.get(source.id, 0)
            newest = source.last_message_id
            if last_id and (newest is None or newest <= last_id):
                self.up_to_date += 1
            else:
                todo.append(source)

        # Größe schätzen (Reihenfolge + Restzeit): Threads zählen selbst mit,
        # Channels per Stichprobe der letzten 100 Nachrichten
        probes = asyncio.Semaphore(CONCURRENCY)
        done = 0

        async def make_job(source: Source) -> Job | None:
            nonlocal done
            async with probes:
                job = await self._estimate(source, known.get(source.id, 0))
            done += 1
            self.status = f"Größe schätzen ({done}/{len(todo)})"
            return job

        jobs = await asyncio.gather(*(make_job(s) for s in todo))
        self.jobs = sorted((j for j in jobs if j), key=lambda j: j.estimate, reverse=True)
        self.status = ""

    async def _estimate(self, source: Source, last_id: int) -> Job | None:
        if isinstance(source, discord.Thread):
            parent = source.parent
            name = f"#{parent.name if parent else '?'} › {source.name}"
        else:
            name = f"#{source.name}"
        start_ts = snowflake_ts(last_id) if last_id else snowflake_ts(source.id)
        end_ts = snowflake_ts(source.last_message_id) if source.last_message_id else time.time()
        job = Job(source, name, last_id, 0, start_ts, max(end_ts, start_ts))

        if isinstance(source, discord.Thread):
            # message_count ist bei sehr alten Threads gedeckelt – reicht als Größenordnung
            span = max(end_ts - snowflake_ts(source.id), 1)
            job.estimate = max(1, round((source.message_count or 0) * (end_ts - start_ts) / span))
            return job
        try:
            recent = [m async for m in source.history(limit=100)]
        except discord.Forbidden:
            self.skipped.append(name)
            return None
        except discord.HTTPException:
            recent = []
        newer = [m for m in recent if m.id > last_id]
        if len(newer) < len(recent) or len(recent) < 100:
            job.estimate = len(newer)
        else:
            span = max((recent[0].created_at - recent[-1].created_at).total_seconds(), 1)
            job.estimate = round(len(recent) / span * (end_ts - start_ts))
        if not newer:
            # Channel hat nichts Neues (z. B. leerer Voice-Chat) → trotzdem als erledigt merken
            self._save(job, [], recent[0].id if recent else 0)
            self.up_to_date += 1
            return None
        return job

    # ---------- 2. Laden ----------

    async def run(self):
        slots = asyncio.Semaphore(CONCURRENCY)

        async def worker(job: Job):
            async with slots:
                await self._fetch(job)

        # Reihenfolge der Tasks = Reihenfolge der Slots → größte Channels zuerst
        await asyncio.gather(*(worker(j) for j in self.jobs))

    async def _fetch(self, job: Job):
        job.state = "running"
        job.started_at = time.monotonic()
        rows: list[tuple] = []
        last_id = job.last_id
        try:
            async for message in job.channel.history(limit=None, after=discord.Object(id=job.last_id), oldest_first=True):
                job.fetched += 1
                job.cur_ts = message.created_at.timestamp()
                last_id = message.id
                if message.content and not message.author.bot and message.type in KEEP_TYPES:
                    rows.append((message.id, job.channel.id, message.author.id, message.content))
                if job.fetched % 100 == 0:
                    self._save(job, rows, last_id)
                    rows = []
            job.state = "done"
        except discord.Forbidden:
            job.state = "skipped"
            self.skipped.append(job.name)
        except discord.HTTPException as e:
            job.state = "error"
            job.error = f"{e.status} {e.text}"[:100]
        finally:
            # Alles bis last_id ist verarbeitet → auch beim Abbruch konsistent speicherbar
            self._save(job, rows, last_id)

    def _save(self, job: Job, rows: list[tuple], last_id: int):
        if not rows and last_id <= job.last_id:
            return
        self.db.executemany("INSERT OR IGNORE INTO messages(id, channel_id, author_id, content) VALUES (?, ?, ?, ?)", rows)
        self.db.execute(
            """
            INSERT INTO channels(id, name, last_id, messages, updated_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                last_id = max(channels.last_id, excluded.last_id),
                messages = channels.messages + excluded.messages,
                updated_at = excluded.updated_at
            """,
            (job.channel.id, job.name, last_id, len(rows), int(time.time())),
        )
        self.db.commit()
        self.stored += len(rows)
        job.last_id = max(job.last_id, last_id)
