"""Reminder per Slash-Command.

- /remindme in <amount> <unit> [text]   → Zeitspanne (Zahl + Einheit)
- /remindme at <input> [text]           → absolutes Datum (Parser: utils/rm_grammar.peg)
- /remindme list                        → eigene Reminder anzeigen (ephemer, blätterbar)

Ablauf: ephemere Kurzbestätigung, dazu eine öffentliche Bestätigungs-Nachricht.
Zum Zeitpunkt antwortet der Bot auf diese Nachricht und pingt den User.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

import discord
from dateutil import tz
from discord import app_commands
from discord.ext import commands, tasks
from parsimonious.exceptions import ParseError, VisitationError

from utils.base import BaseCog, BaseView, UserError
from utils.helpers import NO_MENTIONS, fetch_channel, format_local, truncate
from utils.parser import RemindmeParser

# -------------------- Konfiguration --------------------

CHECK_INTERVAL = 10  # Sekunden zwischen zwei Prüfungen auf fällige Reminder

# Einheit -> (Plural, Sekunden), absteigend sortiert
UNITS = {
    "Jahr": ("Jahre", 365 * 86400),
    "Monat": ("Monate", 30 * 86400),
    "Woche": ("Wochen", 7 * 86400),
    "Tag": ("Tage", 86400),
    "Stunde": ("Stunden", 3600),
    "Minute": ("Minuten", 60),
    "Sekunde": ("Sekunden", 1),
}
# Auswahl im Slash-Command: Plural -> Sekunden
UNIT_SECONDS = {plural: seconds for plural, seconds in UNITS.values()}

PAGE_MAX_LEN = 4096 - 300  # Platz pro Listen-Seite (Embed-Limit minus Reserve)

# -------------------- Datenmodell & Helper --------------------


@dataclass
class Reminder:
    """Ein Reminder – Feldreihenfolge wie die Spalten der Tabelle ``reminders``."""

    id: int | None
    user_id: int
    text: str
    time: float  # Unix-Timestamp
    channel_id: int
    message_id: int  # öffentliche Bestätigungs-Nachricht
    parent_id: int | None = None


def humanize_delta(seconds: float) -> str:
    """Wandelt Sekunden in eine kurze Zeitspanne um (max. 2 Einheiten), z. B. „in 2 Tage 3 Stunden“."""
    parts, rest = [], max(0, int(seconds))
    for singular, (plural, size) in UNITS.items():
        if rest >= size:
            qty, rest = divmod(rest, size)
            parts.append(f"{qty} {singular if qty == 1 else plural}")
        if len(parts) == 2:
            break
    return "in " + " ".join(parts) if parts else "bald"


def build_pages(reminders: list[Reminder]) -> list[str]:
    """Baut die Seiten (Embed-Beschreibungen) der Reminder-Liste."""
    header = "**Deine anstehenden Reminder**"
    pages, lines, length = [], [header], len(header)
    now = time.time()
    for r in reminders:
        text = truncate(r.text.replace("\n", " "), 180)
        line = f"• **{format_local(r.time, seconds=False)}** ({humanize_delta(r.time - now)}) — {text}"
        if length + len(line) + 1 > PAGE_MAX_LEN:
            pages.append("\n".join(lines))
            lines, length = [header], len(header)
        lines.append(line)
        length += len(line) + 1
    pages.append("\n".join(lines))
    return pages


# -------------------- Listen-View --------------------


class ReminderListView(BaseView):
    """Ephemere, blätterbare Reminder-Liste (arbeitet auf den einmal geladenen Remindern)."""

    def __init__(self, user: discord.abc.User, reminders: list[Reminder]):
        super().__init__(timeout=300)
        self.user = user
        self.reminders = reminders
        self.page = 0
        self.pages = build_pages(reminders)

    def make_embed(self) -> discord.Embed:
        """Aktuelle Seite als Embed; aktualisiert dabei auch die Blätter-Buttons."""
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1

        # Grün, wenn in der nächsten Stunde etwas ansteht
        soon = any(r.time - time.time() < 3600 for r in self.reminders)
        embed = discord.Embed(
            title="⏰ Deine Reminder",
            description=self.pages[self.page],
            color=discord.Color.green() if soon else discord.Color.greyple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=self.user.display_name, icon_url=self.user.display_avatar.url)
        embed.set_footer(
            text=f"Seite {self.page + 1}/{len(self.pages)} • {len(self.reminders)} Reminder insgesamt"
        )
        return embed

    async def show(self, interaction: discord.Interaction, page: int):
        """Springt auf eine Seite (auf den gültigen Bereich begrenzt)."""
        self.page = max(0, min(page, len(self.pages) - 1))
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show(interaction, self.page - 1)

    @discord.ui.button(label="Weiter ➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show(interaction, self.page + 1)

    @discord.ui.button(label="🔄 Neu laden", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Aktualisiert nur die Relativzeiten (kein DB-Reload)."""
        self.pages = build_pages(self.reminders)
        await self.show(interaction, self.page)

    @discord.ui.button(label="🗑️ Schließen", style=discord.ButtonStyle.danger)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="(geschlossen)", embed=None, view=None)


# -------------------- Cog --------------------


class RemindMe(BaseCog):
    """Cog: /remindme in | at | list + Hintergrund-Task, der fällige Reminder verschickt."""

    remindme = app_commands.Group(name="remindme", description="Erinnerungen setzen")

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.db = bot.db
        self.parser = RemindmeParser()

    async def cog_load(self):
        self.check_reminders.start()

    async def cog_unload(self):
        self.check_reminders.cancel()

    # ---------- Datenbank ----------

    def insert_reminder(self, reminder: Reminder) -> Reminder:
        cursor = self.db.execute(
            """INSERT INTO reminders (user_id, reminder_text, reminder_time, channel, message_id, parent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (reminder.user_id, reminder.text, reminder.time,
             reminder.channel_id, reminder.message_id, reminder.parent_id),
        )
        self.db.commit()
        reminder.id = cursor.lastrowid
        return reminder

    def delete_reminder(self, reminder: Reminder):
        self.db.execute("DELETE FROM reminders WHERE id=?", (reminder.id,))
        self.db.commit()

    def load_reminders(self, where: str, *params) -> list[Reminder]:
        rows = self.db.execute(f"SELECT * FROM reminders WHERE {where} ORDER BY reminder_time ASC", params)
        return [Reminder(*row) for row in rows.fetchall()]

    # ---------- Reminder anlegen ----------

    async def _create(self, interaction: discord.Interaction, ts: float, text: str, announcement: str):
        """Bestätigt ephemer, postet die öffentliche Bestätigung und speichert den Reminder."""
        await interaction.response.send_message("✅ Reminder wird erstellt …", ephemeral=True)

        reason = f" an:\n**{text}**" if text else "."
        public_msg = await interaction.channel.send(f"📌 <@{interaction.user.id}> wird {announcement}{reason}")

        reminder = self.insert_reminder(
            Reminder(None, interaction.user.id, text, ts, interaction.channel_id, public_msg.id)
        )
        self.log("Reminder created", interaction, reminder_id=reminder.id, reminder_time=ts, text=text)

    @remindme.command(name="in", description="Erinnere mich in X Zeit")
    @app_commands.describe(
        amount="Zahl (z. B. 10)",
        unit="Einheit (Sekunden/Minuten/Stunden/Tage/Wochen/Monate/Jahre)",
        text="Woran soll ich dich erinnern?",
    )
    async def remind_in(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 10_000_000],
        unit: Literal["Sekunden", "Minuten", "Stunden", "Tage", "Wochen", "Monate", "Jahre"],
        text: Optional[str] = "",
    ):
        """Setzt einen Reminder nach einer Zeitspanne."""
        delay = amount * UNIT_SECONDS[unit]
        ts = round(time.time() + delay)
        await self._create(
            interaction, ts, text or "",
            f"{humanize_delta(delay)} (am **{format_local(ts, seconds=False)}**) erinnert",
        )

    @remindme.command(name="at", description="Erinnere mich zu Datum/Uhrzeit (natürliche Eingabe)")
    @app_commands.describe(
        input="Datum/Uhrzeit, z. B. '2025-09-01 15:30', '01.09.2025 15:30', '15:30', '01-09', etc.",
        text="Woran soll ich dich erinnern?",
    )
    async def remind_at(self, interaction: discord.Interaction, input: str, text: Optional[str] = ""):
        """Setzt einen Reminder zu einem bestimmten Zeitpunkt."""
        try:
            parsed = self.parser.parse(input.strip())
            fields = parsed.get("remind_time")
            if not fields:
                raise UserError("❌ Konnte keine Zeitangabe erkennen.")
            if "duration_seconds" in fields:
                raise UserError("❌ Für Zeitspannen nutze bitte `/remindme in …`.")

            # Fehlende Felder mit 'jetzt' auffüllen; zweistellige Jahre meinen 20xx
            now = datetime.now(tz=tz.tzlocal())
            year = fields.get("year", now.year)
            ts = datetime(
                year=year + 2000 if year < 100 else year,
                month=fields.get("month", now.month),
                day=fields.get("day", now.day),
                hour=fields.get("hour", now.hour),
                minute=fields.get("minute", now.minute),
                second=fields.get("second", 0),
                tzinfo=tz.tzlocal(),
            ).timestamp()
        except (ParseError, VisitationError, ValueError) as e:
            raise UserError("❌ Ungültiges Eingabeformat.") from e

        # Knapp vergangene Uhrzeit (< 12 h) ist morgen gemeint
        now_ts = time.time()
        if now_ts - 12 * 3600 < ts < now_ts:
            ts += 86400
        if ts < now_ts:
            raise UserError("❌ Zeit liegt in der Vergangenheit.")

        # Der Text darf auch direkt hinter der Zeitangabe stehen
        await self._create(
            interaction, ts, text or parsed.get("msg", ""),
            f"am **{format_local(ts, seconds=False)}** ({humanize_delta(ts - now_ts)}) erinnert",
        )

    @remindme.command(
        name="list",
        description="Zeige deine anstehenden Reminder",
        extras={"error": "❌ Konnte deine Reminder nicht laden."},
    )
    async def remind_list(self, interaction: discord.Interaction):
        """Zeigt alle anstehenden Reminder des Users (ephemer, blätterbar)."""
        reminders = self.load_reminders("user_id=?", interaction.user.id)
        if not reminders:
            raise UserError("Du hast aktuell **keine** anstehenden Reminder. 🎉")

        view = ReminderListView(interaction.user, reminders)
        await interaction.response.send_message(
            embed=view.make_embed(), view=view, ephemeral=True, allowed_mentions=NO_MENTIONS
        )
        self.log("Reminder list sent", interaction, entries=len(reminders))

    # ---------- Hintergrund-Task ----------

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_reminders(self):
        """Verschickt alle fälligen Reminder."""
        try:
            due = self.load_reminders("reminder_time<=?", time.time())
        except Exception as e:
            # Fehler abfangen, damit der Task weiterläuft
            return self.log("check_reminders_failed", error=e)

        for reminder in due:
            try:
                await self.send_reminder(reminder)
            except Exception as e:
                self.log("send_reminder_failed", user_id=reminder.user_id, reminder_id=reminder.id, error=e)

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

    async def send_reminder(self, reminder: Reminder):
        """Sendet einen fälligen Reminder und löscht ihn."""
        try:
            channel = await fetch_channel(self.bot, reminder.channel_id)
        except (discord.NotFound, discord.Forbidden):
            # Channel gibt es nicht mehr -> Reminder verwerfen
            self.delete_reminder(reminder)
            self.log("reminder_dropped", user_id=reminder.user_id, reminder_id=reminder.id, channel_id=reminder.channel_id)
            return

        # Erst löschen, dann senden: lieber ein verlorener als ein endlos wiederholter Reminder
        self.delete_reminder(reminder)

        # Ohne Text gibt es eine Hivemind-Weisheit
        text = reminder.text or await self.bot.hivemind_sentence(max_overlap_ratio=0.67) or "…"
        content = f"⏰ <@{reminder.user_id}> \nIch werde dich wissen lassen:\n**{text}**"

        try:
            # Als Antwort auf die Bestätigungs-Nachricht – falls es sie noch gibt
            parent = await channel.fetch_message(reminder.message_id)
            await parent.reply(content, mention_author=True)
        except discord.HTTPException:
            await channel.send(content)
        self.log("reminder_delivered", user_id=reminder.user_id, reminder_id=reminder.id, channel_id=reminder.channel_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindMe(bot))
