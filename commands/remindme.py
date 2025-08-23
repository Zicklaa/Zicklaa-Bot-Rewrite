# commands/remindme.py
# Hybrid-Version:
# - /remindme in <amount> <unit> [text]  → strukturiert (Zahl + Einheit)
# - /remindme at <input> [text]          → Datum/Uhrzeit wird mit deinem Parser (rm_grammar.peg) geparst
# - /remindme list                       → eigene Reminder anzeigen
#
# Verhalten:
# - Slash-Aufruf: ephemere Kurzbestätigung
# - Öffentliche Bestätigungs-Nachricht vom Bot mit Ping, Text und Zeitpunkt (auf diese wird beim Erinnern geantwortet)
# - Beim Erinnern: Reply auf die Bestätigungs-Nachricht + Ping des Users

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional, Literal

import discord
from discord.ext import commands
from discord import app_commands
from dateutil import tz

from utils.parser import RemindmeParser
from utils.logging_helper import log_event

# -------------------- Logger & Konfiguration --------------------

logger = logging.getLogger("ZicklaaBotRewrite.RemindMe")

# Lade rm_grammar.peg für den Parser des absoluten Datums
globalPfad = os.environ["globalPfad"]
with open(os.path.join(globalPfad, "utils/rm_grammar.peg"), "r", encoding="utf-8") as _f:
    GRAMMAR = _f.read()

# -------------------- Reminder Model & Helper --------------------


class Reminder:
    """Datenmodell für einen Reminder."""

    def __init__(self, message_id, channel_id, user_id, text, time, id=None, parent_id=None):
        self.message_id = message_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.text = text
        self.time = time
        self._id = id
        self._parent_id = parent_id


def reminder_from_record(record):
    """Erstellt ein Reminder-Objekt aus einem DB-Record."""
    return Reminder(
        record[5],  # message_id
        record[4],  # channel_id
        record[1],  # user_id
        record[2],  # text
        record[3],  # time (timestamp)
        record[0],  # id
        record[6],  # parent_id
    )


def format_local(ts: float) -> str:
    """Formatiert einen Timestamp als lokale Zeit."""
    dt = datetime.fromtimestamp(ts, tz=tz.tzlocal())
    return dt.strftime("%d.%m.%Y %H:%M")


def humanize_delta(Sekunden: int) -> str:
    """Wandelt Sekunden in eine menschenlesbare Zeitspanne um."""
    units = [
        ("Jahr", 365 * 86400),
        ("Monat", 30 * 86400),
        ("Woche", 7 * 86400),
        ("Tag", 86400),
        ("Stunde", 3600),
        ("Minute", 60),
        ("Sekunde", 1),
    ]

    # Pluralformen explizit hinterlegen
    plurals = {
        "Jahr": "Jahre",
        "Monat": "Monate",
        "Woche": "Wochen",
        "Tag": "Tage",
        "Stunde": "Stunden",
        "Minute": "Minuten",
        "Sekunde": "Sekunden",
    }

    parts = []
    rem = max(0, int(Sekunden))

    for name, size in units:
        if rem >= size:
            qty, rem = divmod(rem, size)
            word = name if qty == 1 else plurals[name]
            parts.append(f"{qty} {word}")
        if len(parts) == 2:
            break

    return "in " + " ".join(parts) if parts else "bald"

# ---------- Helper & View für die Reminder-Liste ----------


def _truncate(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _build_pages_from_records(records: list[tuple], *, line_max: int = 4096 - 300) -> list[str]:
    """
    Baut Seiten (Embed.description) aus DB-Records. Achtet auf Discord-Limits.
    - records: DB-Zeilen. Erwartet: [id, user_id, text, reminder_time, channel, message_id, parent_id]
    - line_max: weiche Obergrenze je Seite (kleiner als 4096, da Footer/Title usw.)
    """
    pages: list[str] = []
    page_lines: list[str] = []

    # Introzeile pro Seite
    def start_page():
        return ["**Deine anstehenden Reminder**"]

    page_lines = start_page()
    cur_len = sum(len(x) + 1 for x in page_lines)  # + newline

    now_ts = time.time()
    for r in records:
        text = str(r[2] or "").replace("\n", " ")
        ts = float(r[3])
        when = format_local(ts)
        rel = humanize_delta(int(ts - now_ts))
        line = f"• **{when}** ({rel}) — {_truncate(text, 180)}"

        # Falls diese Zeile die Seiten-Limit überschreitet → Seite flushen
        if cur_len + len(line) + 1 > line_max:
            pages.append("\n".join(page_lines))
            page_lines = start_page()
            cur_len = sum(len(x) + 1 for x in page_lines)

        page_lines.append(line)
        cur_len += len(line) + 1

    # letzte Seite anhängen
    if len(page_lines) > 0:
        pages.append("\n".join(page_lines))

    return pages or ["(leer)"]


class ReminderListView(discord.ui.View):
    """Ephemere, paginierte View – cached alle Reminder in-memory."""

    def __init__(self, *, user: discord.abc.User, records: list[tuple]):
        super().__init__(timeout=300)
        self.user = user
        self.records = records
        self.pages = _build_pages_from_records(records)
        self.page = 0
        self.total = len(self.pages)
        self._update_buttons()

    def _update_buttons(self):
        # Buttons anhand der Seitenposition deaktivieren
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= (self.total - 1)

    def _make_embed(self) -> discord.Embed:
        # Farbe je nach Status: grün wenn bald, grau wenn alles weit weg
        color = discord.Color.blurple()
        try:
            soon = any((float(r[3]) - time.time())
                       < 3600 for r in self.records)
            if soon:
                color = discord.Color.green()
            else:
                color = discord.Color.greyple()
        except Exception:
            pass

        embed = discord.Embed(
            title="⏰ Deine Reminder",
            description=self.pages[self.page],
            color=color,
        )
        embed.set_author(
            name=self.user.display_name,
            icon_url=self.user.display_avatar.url if hasattr(
                self.user, "display_avatar") else discord.Embed.Empty,
        )
        embed.set_footer(
            text=f"Seite {self.page + 1}/{self.total} • {len(self.records)} Reminder insgesamt")
        embed.timestamp = discord.utils.utcnow()
        return embed

    async def send_initial(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=self._make_embed(),
            view=self,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            self._update_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="Weiter ➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total - 1:
            self.page += 1
            self._update_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="🔄 Neu laden", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        'Soft-Refresh' aus dem Cache (keine DB). Aktualisiert nur das Relative (z. B. „in 5 Minuten“),
        indem die Seiten neu gerendert werden.
        """
        # Rebuild der Seiten mit aktuellem now_ts
        self.pages = _build_pages_from_records(self.records)
        self.total = len(self.pages)
        self.page = min(self.page, self.total - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="🗑️ Schließen", style=discord.ButtonStyle.danger)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ephemere Nachricht „löschen“ → setze View auf None & Hinweis
        await interaction.response.edit_message(content="(geschlossen)", embed=None, view=None)


# -------------------- Cog-Klasse --------------------

class RemindMe(commands.Cog):
    """
    Slash-Reminders:
    /remindme in <amount> <unit> [text]
    /remindme at <input> [text]        (input wird mit rm_grammar.peg geparst)
    /remindme list
    """

    remindme = app_commands.Group(
        name="remindme", description="Erinnerungen setzen"
    )

    def __init__(self, bot, db, json_model):
        self.bot = bot
        self.db = db
        self.json_model = json_model
        self.cursor = db.cursor()
        self.global_state = {}
        self.parser = RemindmeParser(GRAMMAR)

    # -------- /remindme in --------
    @remindme.command(name="in", description="Erinnere mich in X Zeit")
    @app_commands.describe(
        amount="Zahl (z. B. 10)",
        unit="Einheit (Sekunden/Minuten/Stunden/Tage/Wochen/Monate/Jahre)",
        text="Woran soll ich dich erinnern?"
    )
    async def remind_in(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 10_000_000],
        unit: Literal["Sekunden", "Minuten", "Stunden", "Tage", "Wochen", "Monate", "Jahre"],
        text: Optional[str] = ""
    ):
        """Setzt einen Reminder nach einer Zeitspanne."""
        Sekunden_map = {
            "Sekunden": 1,
            "Minuten": 60,
            "Stunden": 3600,
            "Tage": 86400,
            "Wochen": 604800,
            "Monate": 30 * 86400,   # vereinfachte Monat-/Jahr-Logik
            "Jahre": 365 * 86400,
        }
        remind_after = amount * Sekunden_map[unit]
        ts = round(time.time() + remind_after)

        # 1) Ephemere Bestätigung
        await interaction.response.send_message("✅ Reminder wird erstellt …", ephemeral=True)

        # 2) Öffentliche Bestätigungsnachricht (Ping + Text + Zeitpunkt + Relativ)
        if text:
            reason_text = f" an:\n**{text}**"
        else:
            reason_text = "."

        public_msg = await interaction.channel.send(
            f"📌 <@{interaction.user.id}> wird {humanize_delta(remind_after)} "
            f"(am **{format_local(ts)}** errinert){reason_text}"
        )

        # 3) Reminder speichern – message_id = Bestätigungsnachricht
        reminder = Reminder(public_msg.id, interaction.channel_id,
                            interaction.user.id, text or "", ts)
        reminder = self.insert_reminder(reminder)
        log_event(
            logger,
            logging.INFO,
            self.__class__.__name__,
            "reminder_created_relative",
            interaction.user,
            interaction.user.id,
            reminder_id=reminder._id,
            reminder_time=ts,
            text=text or "",
        )

    # -------- /remindme at --------
    @remindme.command(name="at", description="Erinnere mich zu Datum/Uhrzeit (natürliche Eingabe)")
    @app_commands.describe(
        input="Datum/Uhrzeit, z. B. '2025-09-01 15:30', '01.09.2025 15:30', '15:30', '01-09', etc.",
        text="Woran soll ich dich erinnern?"
    )
    async def remind_at(
        self,
        interaction: discord.Interaction,
        input: str,
        text: Optional[str] = ""
    ):
        """Setzt einen Reminder zu einem bestimmten Zeitpunkt (natürliche Sprache)."""
        try:
            parsed = self.parser.parse(input)
            parsed_time = parsed.get("remind_time")
            if not parsed_time:
                await interaction.response.send_message("❌ Konnte keine Zeitangabe erkennen.", ephemeral=True)
                return
            if "duration_Sekunden" in parsed_time:
                await interaction.response.send_message(
                    "❌ Für Zeitspannen nutze bitte `/remindme in …`.", ephemeral=True
                )
                return

            # Absolutes Datum/Uhrzeit zusammenbauen (fehlende Teile aus 'jetzt' übernehmen)
            now = datetime.now(tz=tz.tzlocal())
            year = parsed_time.get("year", now.year)
            month = parsed_time.get("month", now.month)
            day = parsed_time.get("day", now.day)
            hour = parsed_time.get("hour", now.hour)
            minute = parsed_time.get("minute", now.minute)
            second = parsed_time.get("second", 0)

            ts = datetime(year=year, month=month, day=day, hour=hour,
                          minute=minute, second=second, tzinfo=tz.tzlocal()).timestamp()

            # Bei Vergangenheit ggf. auf morgen gleicher Zeit verschieben (<= 12h alt)
            now_ts = time.time()
            if ts < now_ts and (now_ts - ts) < 12 * 3600:
                ts += 86400
            if ts < time.time():
                await interaction.response.send_message("❌ Zeit liegt in der Vergangenheit.", ephemeral=True)
                return

            reason = text or parsed.get("msg", "")

            # 1) Ephemere Bestätigung
            await interaction.response.send_message("✅ Reminder wird erstellt …", ephemeral=True)

            # 2) Öffentliche Bestätigungsnachricht
            delta = int(ts - time.time())
            if text:
                reason_text = f" an:\n**{text}**"
            else:
                reason_text = "."

            public_msg = await interaction.channel.send(
                f"📌 <@{interaction.user.id}> wird am **{format_local(ts)}** "
                f"({humanize_delta(delta)}) erinnert{reason_text}"
            )

            # 3) Reminder speichern – message_id = Bestätigungsnachricht
            reminder = Reminder(
                public_msg.id, interaction.channel_id, interaction.user.id, reason, ts)
            reminder = self.insert_reminder(reminder)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "reminder_created_absolute",
                interaction.user,
                interaction.user.id,
                reminder_id=reminder._id,
                reminder_time=ts,
                text=reason,
            )

        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "remind_at_parse_failed",
                interaction.user,
                interaction.user.id,
                input=input,
                error=e,
                exc_info=True,
            )
            await interaction.response.send_message("❌ Ungültiges Eingabeformat.", ephemeral=True)

    # -------- /remindme list --------
    @remindme.command(name="list", description="Zeige deine anstehenden Reminder")
    async def remind_list(self, interaction: discord.Interaction):
        """Zeigt alle anstehenden Reminder des Users."""
        await self.get_all_reminders(interaction)

    # ---------- Background Loop (von bot.on_ready gestartet) ----------
    async def check_reminder(self):
        """Hintergrund-Task: prüft regelmäßig, ob ein Reminder fällig ist."""
        try:
            while True:
                self.cursor.execute(
                    "SELECT * FROM reminders ORDER BY reminder_time ASC LIMIT 1")
                results = self.cursor.fetchall()
                if results:
                    reminder = reminder_from_record(results[0])
                    if (reminder.time - time.time()) < 0:
                        await self.send_reminder(reminder)
                await asyncio.sleep(10)
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "check_reminder_loop_failed",
                error=e,
                exc_info=True,
            )

    # ---------- DB/Utility ----------

    async def get_all_reminders(self, interaction: discord.Interaction):
        """Zeigt dem User eine ephemere, paginierte Liste aller eigenen Reminder (ohne weitere DB-Calls beim Blättern)."""
        try:
            user_id = interaction.user.id
            records = self.cursor.execute(
                "SELECT * FROM reminders WHERE user_id=? ORDER BY reminder_time ASC",
                (user_id,),
            ).fetchall()

            if not records:
                await interaction.response.send_message(
                    "Du hast aktuell **keine** anstehenden Reminder. 🎉",
                    ephemeral=True,
                )
                return

            view = ReminderListView(user=interaction.user, records=records)
            await view.send_initial(interaction)
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "reminder_list_sent",
                interaction.user,
                interaction.user.id,
                entries=len(records),
            )

        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "reminder_list_failed",
                interaction.user,
                interaction.user.id,
                error=e,
                exc_info=True,
            )
            if interaction.response.is_done():
                await interaction.followup.send("❌ Konnte deine Reminder nicht laden.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Konnte deine Reminder nicht laden.", ephemeral=True)

    def insert_reminder(self, reminder: Reminder):
        """Fügt einen Reminder in die Datenbank ein."""
        try:
            sql = """INSERT INTO reminders (user_id, reminder_text, reminder_time, channel, message_id, parent_id)
                     VALUES (?, ?, ?, ?, ?, ?)"""
            val = (
                reminder.user_id,
                reminder.text,
                reminder.time,
                reminder.channel_id,
                reminder.message_id,
                reminder._parent_id,
            )
            self.cursor.execute(sql, val)
            self.db.commit()
            self.cursor.execute(
                "SELECT id FROM reminders WHERE user_id=? AND reminder_text=? AND reminder_time=? AND message_id=?",
                (reminder.user_id, reminder.text,
                 reminder.time, reminder.message_id),
            )
            new_id = self.cursor.fetchall()[0][0]
            reminder._id = new_id
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "db_insert_reminder",
                user=None,
                user_id=reminder.user_id,
                reminder_id=new_id,
            )
            return reminder
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "db_insert_reminder_failed",
                user=None,
                user_id=reminder.user_id,
                error=e,
                exc_info=True,
            )

    async def send_reminder(self, reminder: Reminder):
        """Sendet einen fälligen Reminder und löscht ihn danach."""
        try:
            if not await self.check_reminder_exists(reminder):
                self.delete_reminder(reminder)
                return

            channel = self.bot.get_channel(reminder.channel_id)
            if not channel:
                self.delete_reminder(reminder)
                return

            # Auf die öffentliche Bestätigungsnachricht antworten
            parent_msg = None
            try:
                parent_msg = await channel.fetch_message(reminder.message_id)
            except discord.NotFound:
                pass

            if reminder.text:
                content = reminder.text
            else:
                while True:
                    content = self.json_model.make_sentence(
                        max_overlap_ratio=0.67)
                    if content:
                        break
            content = f"⏰ <@{reminder.user_id}> \nIch werde dich wissen lassen:\n**{content}**"

            if reminder._id != self.global_state.get("reminder_id"):
                self.delete_reminder(reminder)
                self.global_state["reminder_id"] = reminder._id
                log_event(
                    logger,
                    logging.INFO,
                    self.__class__.__name__,
                    "reminder_delivered",
                    user=None,
                    user_id=reminder.user_id,
                    reminder_id=reminder._id,
                    channel_id=reminder.channel_id,
                )
                if parent_msg:
                    await parent_msg.reply(content, mention_author=True)
                else:
                    await channel.send(content)

        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "send_reminder_failed",
                user=None,
                user_id=reminder.user_id,
                reminder_id=reminder._id,
                error=e,
                exc_info=True,
            )

    async def check_reminder_exists(self, reminder: Reminder):
        """Prüft, ob ein Reminder noch in der Datenbank existiert."""
        try:
            res = self.cursor.execute(
                "SELECT * FROM reminders where id=?", (reminder._id,)
            ).fetchone()
            return bool(res)
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "db_check_failed",
                user=None,
                user_id=reminder.user_id,
                reminder_id=reminder._id,
                error=e,
                exc_info=True,
            )
            return False

    def delete_reminder(self, reminder: Reminder):
        """Löscht einen Reminder aus der Datenbank."""
        try:
            self.cursor.execute(
                "DELETE FROM reminders WHERE id=?", (reminder._id,))
            self.db.commit()
            log_event(
                logger,
                logging.INFO,
                self.__class__.__name__,
                "db_delete_reminder",
                user=None,
                reminder_id=reminder._id,
            )
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                self.__class__.__name__,
                "db_delete_reminder_failed",
                user=None,
                reminder_id=reminder._id,
                error=e,
                exc_info=True,
            )

# -------------------- Cog-Setup --------------------


async def setup(bot):
    """Fügt das RemindMe-Cog dem Bot hinzu."""
    await bot.add_cog(RemindMe(bot, bot.db, bot.json_model))
