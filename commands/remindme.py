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

# -------------------- Logger & Konfiguration --------------------

logger = logging.getLogger("ZicklaaBot.RemindMe")

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
        self.insert_reminder(reminder)
        logger.info(
            f"Reminder erstellt (in): User={interaction.user.id}, Zeit={ts}, Text='{text}'")

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
            self.insert_reminder(reminder)
            logger.info(
                f"Reminder erstellt (at): User={interaction.user.id}, Zeit={ts}, Text='{reason}'")

        except Exception as e:
            logger.error(f"RemindMe /at Parse-Fehler: {e}")
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
            logger.error(f"RemindMe check_reminder(): {e}")

    # ---------- DB/Utility ----------
    async def get_all_reminders(self, interaction: discord.Interaction):
        """Sendet dem User eine Liste aller eigenen Reminder."""
        try:
            user_id = interaction.user.id
            all_reminders = self.cursor.execute(
                "SELECT * FROM reminders WHERE user_id=? ORDER BY reminder_time ASC",
                (user_id,),
            ).fetchall()
            if not all_reminders:
                await interaction.response.send_message("Du hast keine Reminder, du Megabrain", ephemeral=True)
                return

            lines = ["Ich werde dich demnächst wissen lassen:"]
            now_ts = time.time()
            for r in all_reminders:
                ts = r[3]
                lines.append(
                    f"• **{format_local(ts)}** ({humanize_delta(int(ts - now_ts))}) – **{r[2]}**")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            logger.info(f"Reminder-Liste gesendet an User={user_id}")

        except Exception as e:
            logger.error("RemindMe get_all_reminders(): " + str(e))

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
            logger.info(f"Neuer Reminder in die DB gepusht: {new_id}")
            reminder._id = new_id
            return reminder
        except Exception as e:
            logger.error("RemindMe insert_reminder(): " + str(e))

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
                logger.info(f"Auf Reminder geantwortet: {reminder._id}")
                if parent_msg:
                    await parent_msg.reply(content, mention_author=True)
                else:
                    await channel.send(content)

        except Exception as e:
            logger.error(f"RemindMe send_reminder(): {e}")

    async def check_reminder_exists(self, reminder: Reminder):
        """Prüft, ob ein Reminder noch in der Datenbank existiert."""
        try:
            res = self.cursor.execute(
                "SELECT * FROM reminders where id=?", (reminder._id,)
            ).fetchone()
            return bool(res)
        except Exception as e:
            logger.error("RemindMe check_reminder_exists(): " + str(e))
            return False

    def delete_reminder(self, reminder: Reminder):
        """Löscht einen Reminder aus der Datenbank."""
        try:
            self.cursor.execute(
                "DELETE FROM reminders WHERE id=?", (reminder._id,))
            self.db.commit()
            logger.info(f"Reminder gelöscht: {reminder._id}")
        except Exception as e:
            logger.error("RemindMe delete_reminder(): " + str(e))

# -------------------- Cog-Setup --------------------


async def setup(bot):
    """Fügt das RemindMe-Cog dem Bot hinzu."""
    await bot.add_cog(RemindMe(bot, bot.db, bot.json_model))
