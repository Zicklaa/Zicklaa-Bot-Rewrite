"""/hm & /hmm – zufällige Sätze aus dem Hivemind; /hivemind rebuild – Hivemind neu bauen."""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, BaseView, UserError, in_channels, owner_only
from utils.helpers import NO_MENTIONS, truncate
from utils.hivemind.corpus import open_corpus
from utils.hivemind.model import CORPUS_DB, DEFAULT_STYLE, HIVEMIND_DIR, STYLES
from utils.hivemind.scrape import Scraper
from utils.settings import BASE_DIR, GUILD_IDS, OWNER_ID, SPAM_CHANNEL_ID

# -------------------- Konfiguration --------------------

HIVEMIND_GUILD_ID = GUILD_IDS[0]  # Bens Haus der Enten – egal, wo /hivemind rebuild aufgerufen wird
BUILD_DB = HIVEMIND_DIR / "model.build.db"
UPDATE_INTERVAL = 5  # Sekunden zwischen zwei Aktualisierungen der Fortschrittsanzeige
UNAVAILABLE = "🧠 Das Hivemind ist gerade nicht verfügbar."

PHASES = {
    "discover": "Channels & Threads finden",
    "scrape": "Nachrichten laden",
    "build": "Modell bauen",
    "install": "Aktivieren & archivieren",
}
# Anteil der Phasen am Gesamtbalken je Modus
PHASE_WEIGHTS = {
    "update": {"discover": 0.02, "scrape": 0.83, "build": 0.14, "install": 0.01},
    "build": {"discover": 0.0, "scrape": 0.0, "build": 0.97, "install": 0.03},
}
# Schritte von utils.hivemind.build: Phase -> (Label, Anteil am Bauen)
BUILD_STEPS = {
    "legacy": ("Altbestand übernehmen", 0.05),
    "lines": ("Zeilen sammeln & Duplikate entfernen", 0.15),
    "tokens": ("Wörter erfassen", 0.15),
    "chain": ("Markov-Kette berechnen", 0.25),
    "bloom": ("Original-Filter bauen", 0.15),
    "write": ("Modell schreiben", 0.25),
}
STATE_ICONS = {"wait": "⏸️", "run": "⏳", "done": "✅", "skip": "➖", "fail": "❌", "cancel": "⏹️"}
COLOR_RUNNING, COLOR_DONE, COLOR_FAILED, COLOR_CANCELLED = 0x5865F2, 0x57F287, 0xED4245, 0x95A5A6

STYLE_CHOICES = [app_commands.Choice(name=style.label, value=key) for key, style in STYLES.items()]
STYLE_DESCRIBE = "Wie wild darf's werden? (Standard: Ausgewogen)"

# -------------------- Formatierung --------------------


def fmt_int(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def bar(fraction: float, width: int = 12) -> str:
    filled = round(min(max(fraction, 0.0), 1.0) * width)
    return "▰" * filled + "▱" * (width - filled)


def pct(fraction: float) -> str:
    # 99 % statt 100 %, solange etwas nicht wirklich fertig ist
    return f"{min(int(fraction * 100), 99)} %"


def count_corpus() -> int:
    """Anzahl gespeicherter Nachrichtentexte (eigene Verbindung → läuft im Worker-Thread)."""
    db = open_corpus(CORPUS_DB)
    try:
        return db.execute("SELECT count(*) FROM messages").fetchone()[0]
    finally:
        db.close()


# -------------------- Rebuild-Lauf --------------------


class RebuildRun:
    """Ein Durchlauf von /hivemind rebuild: führt die Phasen aus und rendert den Fortschritt."""

    def __init__(self, cog: "Hivemind", guild: discord.Guild, mode: str):
        self.cog = cog
        self.guild = guild
        self.mode = mode
        self.states = {phase: "wait" for phase in PHASES}
        if mode == "build":
            self.states["discover"] = self.states["scrape"] = "skip"
        self.scraper: Scraper | None = None
        self.build_step: dict | None = None
        self.result: dict | None = None
        self.archived: list = []
        self.samples: list[str] = []
        # Vorher-Stand für die Bilanz am Ende
        self.corpus_before: int | None = None
        model = cog.bot.hivemind
        self.lines_before: int | None = int(model.meta["lines"]) if model else None
        self.error: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        self.task: asyncio.Task | None = None
        self.message: discord.Message | None = None

    @property
    def running(self) -> bool:
        return self.finished is None

    # ---------- Ablauf ----------

    async def run(self):
        phase = None
        try:
            self.corpus_before = await asyncio.to_thread(count_corpus)
            if self.mode == "update":
                corpus = open_corpus(CORPUS_DB)
                try:
                    self.scraper = Scraper(self.guild, corpus)
                    phase = self._enter("discover")
                    await self.scraper.discover()
                    self.states[phase] = "done"
                    phase = self._enter("scrape")
                    await self.scraper.run()
                    self.states[phase] = "done"
                finally:
                    corpus.close()

            phase = self._enter("build")
            self.result = await self._build()
            self.states[phase] = "done"

            phase = self._enter("install")
            # Austausch nicht mittendrin abbrechen lassen
            self.archived = await asyncio.shield(self.cog.bot.install_hivemind(BUILD_DB))
            self.states[phase] = "done"
            for _ in range(3):
                if sentence := await self.cog.bot.hivemind_sentence():
                    self.samples.append(sentence)
        except asyncio.CancelledError:
            if phase:
                self.states[phase] = "cancel"
            raise
        except Exception as e:
            self.error = truncate(f"{type(e).__name__}: {e}", 300)
            if phase:
                self.states[phase] = "fail"
            self.cog.log("Hivemind rebuild failed", user_id=OWNER_ID, phase=phase, error=e)
        finally:
            self.finished = time.time()
            BUILD_DB.unlink(missing_ok=True)

    def _enter(self, phase: str) -> str:
        self.states[phase] = "run"
        return phase

    async def _build(self) -> dict:
        """Startet utils.hivemind.build als eigenen Prozess (der Bot bleibt reaktionsfähig)."""
        BUILD_DB.unlink(missing_ok=True)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "utils.hivemind.build", "--corpus", str(CORPUS_DB), "--out", str(BUILD_DB),
            cwd=BASE_DIR, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stderr = asyncio.create_task(proc.stderr.read())
        result = None
        try:
            async for raw in proc.stdout:
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if "result" in data:
                    result = data["result"]
                else:
                    self.build_step = data
            code = await proc.wait()
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        finally:
            errors = (await stderr).decode(errors="replace").strip()
        if code != 0 or result is None:
            last = errors.splitlines()[-1] if errors else f"Exit-Code {code}"
            raise RuntimeError(f"Build fehlgeschlagen: {last}")
        return result

    # ---------- Fortschritt ----------

    def _fraction(self, phase: str) -> float:
        state = self.states[phase]
        if state == "done":
            return 1.0
        if state != "run":
            return 0.0
        if phase == "scrape" and self.scraper:
            return self.scraper.progress()[0]
        if phase == "build" and self.build_step:
            done = 0.0
            for step, (_, weight) in BUILD_STEPS.items():
                if step == self.build_step["phase"]:
                    total = self.build_step["total"]
                    return done + weight * (self.build_step["done"] / total if total else 0)
                done += weight
        return 0.0

    def _phase_text(self, phase: str) -> str:
        state = self.states[phase]
        if state == "skip":
            return "Übersprungen – es wird nur aus dem vorhandenen Korpus neu gebaut."
        if state == "wait":
            return "–"
        scraper = self.scraper

        if phase == "discover" and scraper:
            if state == "run":
                return f"Suche {scraper.status or 'Channels'} …"
            text = (
                f"{scraper.channels} Channels, {fmt_int(scraper.threads)} Threads · "
                f"{fmt_int(scraper.up_to_date)} schon aktuell · {fmt_int(len(scraper.jobs))} zu laden"
            )
            if scraper.skipped:
                text += f"\n🔒 Ohne Zugriff: {truncate(', '.join(sorted(set(scraper.skipped))), 300)}"
            return text

        if phase == "scrape" and scraper:
            jobs = scraper.jobs
            finished = sum(j.state != "pending" and j.state != "running" for j in jobs)
            lines = []
            if state == "run":
                fraction, eta = scraper.progress()
                lines.append(f"`{bar(fraction)}` **{pct(fraction)}**" + (f" · noch ca. {fmt_duration(eta)}" if eta else ""))
                lines.append(
                    f"**{fmt_int(scraper.fetched)}** Nachrichten · {fmt_int(scraper.rate())}/s · "
                    f"{fmt_int(finished)}/{fmt_int(len(jobs))} Channels fertig"
                )
                running = sorted((j for j in jobs if j.state == "running"), key=lambda j: j.remaining, reverse=True)
                for job in running[:4]:
                    reached = f" · Stand {datetime.fromtimestamp(job.cur_ts):%m/%Y}" if job.cur_ts else ""
                    lines.append(f"🔄 {truncate(job.name, 32)} `{bar(job.fraction, 8)}` {pct(job.fraction)}{reached}")
                if len(running) > 4:
                    lines.append(f"… und {len(running) - 4} weitere")
            else:
                lines.append(
                    f"**{fmt_int(scraper.fetched)}** Nachrichten geladen, davon **{fmt_int(scraper.stored)}** "
                    f"neu im Korpus · {fmt_int(finished)}/{fmt_int(len(jobs))} Channels"
                )
            failed = [j for j in jobs if j.state == "error"]
            if failed:
                names = ", ".join(j.name for j in failed[:5])
                lines.append(f"⚠️ {len(failed)} mit Fehler (nächster Rebuild versucht's nochmal): {truncate(names, 200)}")
            return "\n".join(lines)

        if phase == "build":
            if state == "run":
                if not self.build_step:
                    return "Starte …"
                step = self.build_step["phase"]
                label = BUILD_STEPS.get(step, (step, 0))[0]
                number = list(BUILD_STEPS).index(step) + 1 if step in BUILD_STEPS else "?"
                total = self.build_step["total"]
                inner = self.build_step["done"] / total if total else 0
                return f"`{bar(self._fraction('build'))}` **{pct(self._fraction('build'))}**\nSchritt {number}/{len(BUILD_STEPS)}: {label} `{bar(inner, 8)}`"
            if self.result:
                r = self.result
                return (
                    f"{fmt_int(r['lines'])} verschiedene Zeilen ({fmt_int(r['raw_lines'] - r['lines'])} Duplikate entfernt) · "
                    f"{fmt_int(r['tokens'])} Wörter, davon {fmt_int(r['vocab'])} verschiedene\n"
                    f"Kette: {fmt_int(r['chain2_rows'] + r['chain3_rows'])} Übergänge · "
                    f"{r['size'] / 1e6:.0f} MB · gebaut in {fmt_duration(r['seconds'])}"
                )

        if phase == "install":
            if state == "run":
                return "Prüfe neues Modell und tausche es aus …"
            if state == "done":
                archived = ", ".join(f"`{p.name}`" for p in self.archived)
                return "Neues Hivemind ist aktiv." + (f"\nArchiviert: {archived}" if archived else "")
        return "–" if state != "fail" else "Fehlgeschlagen"

    def _balance(self) -> str:
        """Vorher/Nachher-Vergleich als Sanity-Check."""
        r = self.result
        lines = [
            f"Nachrichten im Korpus: {fmt_int(self.corpus_before)} → **{fmt_int(r['messages'])}** "
            f"(**+{fmt_int(r['messages'] - self.corpus_before)}**)",
            f"Dazu Altbestand aus den Dumps 2022/2024: {fmt_int(r['legacy_lines'])} Zeilen",
        ]
        if self.lines_before is not None:
            diff = r["lines"] - self.lines_before
            lines.append(
                f"Hivemind kennt jetzt **{fmt_int(r['lines'])}** verschiedene Zeilen "
                f"(vorher {fmt_int(self.lines_before)}, {'+' if diff >= 0 else '−'}{fmt_int(abs(diff))})"
            )
        else:
            lines.append(f"Hivemind kennt jetzt **{fmt_int(r['lines'])}** verschiedene Zeilen")
        return "\n".join(lines)

    def embed(self) -> discord.Embed:
        duration = fmt_duration((self.finished or time.time()) - self.started)
        cancelled = "cancel" in self.states.values()
        if self.running:
            weights = PHASE_WEIGHTS[self.mode]
            fraction = sum(weights[p] * self._fraction(p) for p in PHASES)
            description = f"`{bar(fraction, 20)}` **{pct(fraction)}**"
            if self.states["scrape"] == "run" and self.scraper:
                _, eta = self.scraper.progress()
                if eta:
                    description += f" · Laden noch ca. {fmt_duration(eta)}, danach ein paar Minuten Bauen"
            color = COLOR_RUNNING
        elif cancelled:
            description = (
                f"⏹️ **Abgebrochen** nach {duration}. Alles bis hierhin Geladene ist gespeichert – "
                "der nächste Rebuild macht genau dort weiter. Das bisherige Hivemind bleibt aktiv."
            )
            color = COLOR_CANCELLED
        elif self.error:
            description = f"❌ **Fehlgeschlagen** nach {duration}:\n`{self.error}`\nDas bisherige Hivemind bleibt aktiv."
            color = COLOR_FAILED
        else:
            description = f"✅ **Fertig** nach {duration} – das neue Hivemind ist aktiv."
            color = COLOR_DONE

        embed = discord.Embed(title="🧠 Hivemind-Rebuild", description=description, color=color)
        for i, (phase, title) in enumerate(PHASES.items(), start=1):
            embed.add_field(
                name=f"{STATE_ICONS[self.states[phase]]} {i}. {title}",
                value=truncate(self._phase_text(phase), 1024),
                inline=False,
            )
        if self.result and self.corpus_before is not None:
            embed.add_field(name="📊 Bilanz", value=self._balance(), inline=False)
        if self.samples:
            embed.add_field(
                name="🎲 Kostprobe",
                value=truncate("\n".join(f"> {s}" for s in self.samples), 1024),
                inline=False,
            )
        started = datetime.fromtimestamp(self.started)
        footer = f"Gestartet {started:%d.%m. %H:%M} Uhr"
        footer += f" · aktualisiert alle {UPDATE_INTERVAL} s" if self.running else f" · Dauer {duration}"
        embed.set_footer(text=footer)
        return embed


class RebuildView(BaseView):
    """Abbrechen-Button unter der Fortschrittsanzeige."""

    error_text = "❌ Abbrechen hat nicht geklappt."

    def __init__(self, run: RebuildRun):
        super().__init__(timeout=None)
        self.run = run

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Finger weg, das darf nur der Chef 😉", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Abbrechen", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.run.states["install"] == "run":
            await interaction.response.send_message("Zu spät – das neue Modell wird gerade aktiviert.", ephemeral=True)
            return
        button.disabled = True
        button.label = "Wird abgebrochen …"
        await interaction.response.edit_message(view=self)
        if self.run.task:
            self.run.task.cancel()


# -------------------- Cog --------------------


class Hivemind(BaseCog):
    """Cog: /hm (ein Satz), /hmm (fünf Sätze, nur im Spam-Channel), /hivemind rebuild (nur Admin)."""

    hivemind = app_commands.Group(name="hivemind", description="Hivemind verwalten (nur Admin)")

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.current: RebuildRun | None = None
        self._watcher: asyncio.Task | None = None

    async def cog_unload(self):
        if self.current and self.current.task:
            self.current.task.cancel()

    async def _sentence(self, style: str = DEFAULT_STYLE) -> str:
        sentence = await self.bot.hivemind_sentence(style=style)
        if not sentence:
            raise UserError(UNAVAILABLE)
        return sentence

    @app_commands.command(name="hm", description="Generiert einen zufälligen Satz aus dem Hivemind.")
    @app_commands.describe(stil=STYLE_DESCRIBE)
    @app_commands.choices(stil=STYLE_CHOICES)
    async def hm(self, interaction: discord.Interaction, stil: str = DEFAULT_STYLE):
        await interaction.response.send_message(await self._sentence(stil), allowed_mentions=NO_MENTIONS)
        self.log("Sentence sent", interaction, style=stil)

    @app_commands.command(name="hmm", description="Generiert 5 zufällige Sätze (nur im Spam-Channel).")
    @app_commands.describe(stil=STYLE_DESCRIBE)
    @app_commands.choices(stil=STYLE_CHOICES)
    @in_channels(SPAM_CHANNEL_ID)
    async def hmm(self, interaction: discord.Interaction, stil: str = DEFAULT_STYLE):
        # Die Sätze kommen als eigene Nachrichten; die "denkt nach"-Antwort wird danach gelöscht
        await interaction.response.defer(thinking=True)
        for _ in range(5):
            await interaction.channel.send(await self._sentence(stil), allowed_mentions=NO_MENTIONS)

        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
        self.log("HMM executed", interaction, style=stil)

    # ---------- /hivemind rebuild ----------

    @hivemind.command(
        name="rebuild",
        description="Lädt alle neuen Server-Nachrichten und baut das Hivemind neu (nur Admin).",
        extras={"error": "Rebuild ließ sich nicht starten 🤷"},
    )
    @app_commands.describe(modus="Standard: neue Nachrichten laden (beim ersten Mal: alle) und neu bauen")
    @app_commands.choices(
        modus=[
            app_commands.Choice(name="📥 Neue Nachrichten laden + neu bauen", value="update"),
            app_commands.Choice(name="🧠 Nur neu bauen (vorhandener Korpus)", value="build"),
        ]
    )
    @owner_only("Das Hivemind umbauen darf nur der Chef 🤷")
    async def rebuild(self, interaction: discord.Interaction, modus: str = "update"):
        if self.current and self.current.running:
            where = f": {self.current.message.jump_url}" if self.current.message else "."
            raise UserError(f"⏳ Es läuft schon ein Rebuild{where}")
        guild = self.bot.get_guild(HIVEMIND_GUILD_ID)
        if guild is None:
            raise UserError("❌ Den Hivemind-Server kenne ich gerade nicht.")

        run = RebuildRun(self, guild, modus)
        await interaction.response.send_message("🧠 Rebuild gestartet – der Fortschritt steht gleich hier im Channel.", ephemeral=True)
        # Normale Nachricht statt Interaction-Antwort: die lässt sich nur 15 Minuten lang bearbeiten
        run.message = await interaction.channel.send(embed=run.embed(), view=RebuildView(run))
        self.current = run
        run.task = asyncio.create_task(run.run())
        self._watcher = asyncio.create_task(self._watch(run))
        self.log("Hivemind rebuild started", interaction, mode=modus)

    async def _watch(self, run: RebuildRun):
        """Aktualisiert die Fortschrittsanzeige, bis der Lauf vorbei ist."""
        last = None
        while True:
            done = run.task.done()
            embed = run.embed()
            payload = embed.to_dict()
            if run.message and (payload != last or done):
                try:
                    await run.message.edit(embed=embed, **({"view": None} if done else {}))
                    last = payload
                except discord.NotFound:
                    run.message = None  # Anzeige gelöscht – der Rebuild läuft trotzdem weiter
                except discord.HTTPException as e:
                    self.log("Hivemind progress edit failed", user_id=OWNER_ID, level=logging.WARNING, error_text=str(e))
            if done:
                break
            await asyncio.sleep(UPDATE_INTERVAL)

        outcome = "cancelled" if "cancel" in run.states.values() else "failed" if run.error else "finished"
        self.log(f"Hivemind rebuild {outcome}", user_id=OWNER_ID, mode=run.mode, result=run.result, error_text=run.error)


async def setup(bot: commands.Bot):
    await bot.add_cog(Hivemind(bot))
