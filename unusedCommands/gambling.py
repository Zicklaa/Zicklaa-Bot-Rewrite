# gambling_cog.py
# -*- coding: utf-8 -*-
"""
Gambling-Cog für discord.py 2.x
- Persistente Währung via JSON (ein Server)
- Slash-Commands: /balance, /daily, /give, /coinflip, /slots, /dice, /leaderboard
- Seltene hohe Multiplikatoren bei Slots & Dice
"""

from __future__ import annotations

import json
import logging
import random
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("ZicklaaBotRewrite.Gambling")
logging.basicConfig(level=logging.INFO)

# -------------------- Konfiguration --------------------

CURRENCY = "🪙"          # Symbol der Fake-Währung
START_DAILY = 100         # täglicher Bonus
DAILY_COOLDOWN_H = 20     # wie oft /daily erlaubt (in Std)
MIN_BET = 10              # minimaler Einsatz
MAX_BET = 250_000         # maximaler Einsatz (Schutz)

ALLOWED_GAMBLING_CHANNEL_ID = 123456789012345678

# Datenpfad
DATA_PATH = Path("./static/gambling.json").resolve()
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

# -------------------- Persistenz --------------------

@dataclass
class Ledger:
    balances: Dict[str, int]
    daily_ts: Dict[str, str]  # ISO TS pro user_id

class Store:
    """Sehr einfache JSON-Persistenz (ein Server)."""
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    async def init(self):
        import asyncio
        self._lock = asyncio.Lock()
        if not self.path.exists():
            await self._write(Ledger(balances={}, daily_ts={}))
        # sanity load
        _ = await self.read()

    async def read(self) -> Ledger:
        async with self._lock:  # type: ignore
            if not self.path.exists():
                return Ledger(balances={}, daily_ts={})
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return Ledger(
                    balances=data.get("balances", {}),
                    daily_ts=data.get("daily_ts", {}),
                )
            except Exception as e:
                log.exception("Konnte Ledger nicht laden: %s", e)
                return Ledger(balances={}, daily_ts={})

    async def write(self, ledger: Ledger):
        async with self._lock:  # type: ignore
            await self._write(ledger)

    async def _write(self, ledger: Ledger):
        tmp = self.path.with_suffix(".tmp")
        data = {"balances": ledger.balances, "daily_ts": ledger.daily_ts}
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

# -------------------- Utils --------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def fmt_amount(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def ensure_positive_int(amount: int) -> int:
    if amount < 0:
        raise ValueError("Negativer Betrag.")
    return int(amount)

def clamp_bet(amount: int) -> int:
    return max(MIN_BET, min(MAX_BET, amount))

def user_key(user: discord.abc.User) -> str:
    return str(user.id)

def guild_only_check(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None

guild_only = app_commands.check(guild_only_check)

# -------------------- Spiele-Logik --------------------

SLOTS_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "7️⃣", "🍀", "🍇"]
# Gewinnlogik:
# - 3x 7️⃣ → 20x
# - 3x ⭐  → 10x
# - 3x beliebig → 5x
# - 2x beliebig → 2x
# - Seltene Jackpot-Überraschung (0.2%) → 50x
# - sonst 0x

def slots_spin() -> tuple[list[str], int]:
    r = [random.choice(SLOTS_SYMBOLS) for _ in range(3)]
    # Seltene Jackpot-Chance (0.2 %)
    if random.random() < 0.002:
        return r, 50
    if r[0] == r[1] == r[2]:
        if r[0] == "7️⃣":
            return r, 20
        if r[0] == "⭐":
            return r, 10
        return r, 5
    if r[0] == r[1] or r[1] == r[2] or r[0] == r[2]:
        return r, 2
    return r, 0

# Dice:
# User tippt eine Zahl 1-6 → Gewinn 6x bei Treffer (fair).
# Seltene Lucky-Roll (0.5 %) → 20x (unabhängig von Tipp; überschreibt 6x)
def dice_roll(guess: int) -> tuple[int, int, bool]:
    roll = random.randint(1, 6)
    lucky = random.random() < 0.005
    if lucky:
        return roll, 20, True
    return roll, (6 if roll == guess else 0), False

# Coinflip:
# fair 50/50 → 2x oder 0x
def coinflip_result() -> bool:
    return random.random() < 0.5

# -------------------- Cog --------------------

class Gambling(commands.Cog):
    """
    Einfache Gambling-Ökonomie pro Server (ein JSON-File).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = Store(DATA_PATH)

    async def cog_load(self):
        await self.store.init()

    # ---- interne Ledger-Helfer ----

    async def _get_ledger(self) -> Ledger:
        return await self.store.read()

    async def _get_balance(self, user: discord.abc.User) -> int:
        ledger = await self._get_ledger()
        return int(ledger.balances.get(user_key(user), 0))

    async def _add_balance(self, user: discord.abc.User, delta: int) -> int:
        ledger = await self._get_ledger()
        uid = user_key(user)
        cur = int(ledger.balances.get(uid, 0))
        new = max(0, cur + int(delta))
        ledger.balances[uid] = new
        await self.store.write(ledger)
        return new

    async def _set_balance(self, user: discord.abc.User, amount: int) -> int:
        ledger = await self._get_ledger()
        ledger.balances[user_key(user)] = max(0, int(amount))
        await self.store.write(ledger)
        return int(ledger.balances[user_key(user)])

    async def _can_daily(self, user: discord.abc.User) -> tuple[bool, int]:
        ledger = await self._get_ledger()
        uid = user_key(user)
        iso = ledger.daily_ts.get(uid)
        if not iso:
            return True, 0
        last = datetime.fromisoformat(iso)
        delta = now_utc() - last
        remain = max(0, int(DAILY_COOLDOWN_H * 3600 - delta.total_seconds()))
        return remain <= 0, remain

    async def _mark_daily(self, user: discord.abc.User):
        ledger = await self._get_ledger()
        ledger.daily_ts[user_key(user)] = now_utc().isoformat()
        await self.store.write(ledger)

    # -------------------- Commands --------------------

    @app_commands.command(name="balance", description="Zeigt dein aktuelles Guthaben.")
    @guild_only
    async def balance(self, interaction: discord.Interaction):
        bal = await self._get_balance(interaction.user)
        await interaction.response.send_message(
            f"💼 Dein Kontostand: **{CURRENCY} {fmt_amount(bal)}**", ephemeral=True
        )

    @app_commands.command(name="daily", description="Täglicher Bonus.")
    @guild_only
    async def daily(self, interaction: discord.Interaction):
        allowed, remain = await self._can_daily(interaction.user)
        if not allowed:
            h, m = divmod(remain // 60, 60)
            await interaction.response.send_message(
                f"⏳ Daily noch nicht verfügbar. Warte **{h}h {m}m**.",
                ephemeral=True,
            )
            return
        new_bal = await self._add_balance(interaction.user, START_DAILY)
        await self._mark_daily(interaction.user)
        await interaction.response.send_message(
            f"✅ Daily gutgeschrieben: **{CURRENCY} {fmt_amount(START_DAILY)}**\n"
            f"Neuer Kontostand: **{CURRENCY} {fmt_amount(new_bal)}**"
        )

    @app_commands.command(name="give", description="Überweise Coins an jemand anderen.")
    @guild_only
    @app_commands.describe(user="Empfänger", amount="Betrag (mind. MIN_BET)")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if user.id == interaction.user.id:
            await interaction.response.send_message("🤨 Dir selbst etwas überweisen… really?", ephemeral=True)
            return
        try:
            amount = ensure_positive_int(amount)
        except Exception:
            await interaction.response.send_message("Bitte einen **positiven** Betrag angeben.", ephemeral=True)
            return
        if amount < MIN_BET:
            await interaction.response.send_message(f"Mindesteinzahlung: **{CURRENCY} {MIN_BET}**.", ephemeral=True)
            return
        sender_bal = await self._get_balance(interaction.user)
        if sender_bal < amount:
            await interaction.response.send_message("❌ Nicht genug Guthaben.", ephemeral=True)
            return
        await self._add_balance(interaction.user, -amount)
        new_rec = await self._add_balance(user, amount)
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} → {user.mention}: **{CURRENCY} {fmt_amount(amount)}**\n"
            f"{user.mention} neuer Kontostand: **{CURRENCY} {fmt_amount(new_rec)}**"
        )

    @app_commands.command(name="coinflip", description="50/50 – Verdopple deinen Einsatz (oder verliere ihn).")
    @guild_only
    @app_commands.describe(amount="Einsatz")
    async def coinflip(self, interaction: discord.Interaction, amount: int):
        try:
            amount = ensure_positive_int(amount)
        except Exception:
            await interaction.response.send_message("Bitte einen **positiven** Einsatz angeben.", ephemeral=True)
            return
        amount = clamp_bet(amount)
        bal = await self._get_balance(interaction.user)
        if bal < amount:
            await interaction.response.send_message("❌ Nicht genug Guthaben.", ephemeral=True)
            return

        win = coinflip_result()
        delta = amount if win else -amount
        new_bal = await self._add_balance(interaction.user, delta)

        icon = "🟩" if win else "🟥"
        msg = f"{icon} **Coinflip** – Einsatz **{CURRENCY} {fmt_amount(amount)}** → "
        if win:
            msg += f"Gewinn **{CURRENCY} {fmt_amount(amount)}** (2×)\n"
        else:
            msg += f"verloren.\n"
        msg += f"Neuer Kontostand: **{CURRENCY} {fmt_amount(new_bal)}**"
        await interaction.response.send_message(msg)

    @app_commands.command(name="slots", description="Slotmachine mit seltenen hohen Multiplikatoren.")
    @guild_only
    @app_commands.describe(amount="Einsatz")
    async def slots(self, interaction: discord.Interaction, amount: int):
        try:
            amount = ensure_positive_int(amount)
        except Exception:
            await interaction.response.send_message("Bitte einen **positiven** Einsatz angeben.", ephemeral=True)
            return
        amount = clamp_bet(amount)
        bal = await self._get_balance(interaction.user)
        if bal < amount:
            await interaction.response.send_message("❌ Nicht genug Guthaben.", ephemeral=True)
            return

        reels, mult = slots_spin()
        gain = amount * mult
        delta = gain - amount  # Einsatz abziehen, Gewinn addieren
        new_bal = await self._add_balance(interaction.user, delta)

        reels_str = " | ".join(reels)
        if mult == 0:
            txt = f"🧨 **Slots**: `{reels_str}` → nix getroffen. Einsatz weg."
        else:
            txt = f"🎰 **Slots**: `{reels_str}` → **{mult}×** → Gewinn **{CURRENCY} {fmt_amount(gain)}**"
        txt += f"\nNeuer Kontostand: **{CURRENCY} {fmt_amount(new_bal)}**"
        await interaction.response.send_message(txt)

    @app_commands.command(name="dice", description="Würfel 1–6. Treffer zahlt 6×. Selten: Lucky 20×.")
    @guild_only
    @app_commands.describe(amount="Einsatz", guess="Dein Tipp (1–6)")
    async def dice(self, interaction: discord.Interaction, amount: int, guess: int):
        try:
            amount = ensure_positive_int(amount)
        except Exception:
            await interaction.response.send_message("Bitte einen **positiven** Einsatz angeben.", ephemeral=True)
            return
        if not (1 <= guess <= 6):
            await interaction.response.send_message("Bitte **guess** zwischen 1–6 angeben.", ephemeral=True)
            return
        amount = clamp_bet(amount)
        bal = await self._get_balance(interaction.user)
        if bal < amount:
            await interaction.response.send_message("❌ Nicht genug Guthaben.", ephemeral=True)
            return

        roll, mult, lucky = dice_roll(guess)
        gain = amount * mult
        delta = gain - amount
        new_bal = await self._add_balance(interaction.user, delta)

        if mult == 0:
            txt = f"🎲 **Dice**: gewürfelt **{roll}** – leider daneben. Einsatz weg."
        else:
            head = "🍀 **Lucky Roll!** " if lucky else "🎯 **Treffer!** "
            txt = f"{head}gewürfelt **{roll}** → **{mult}×** → Gewinn **{CURRENCY} {fmt_amount(gain)}**"
        txt += f"\nNeuer Kontostand: **{CURRENCY} {fmt_amount(new_bal)}**"
        await interaction.response.send_message(txt)

    @app_commands.command(name="leaderboard", description="Top 10 reichste Spieler.")
    @guild_only
    async def leaderboard(self, interaction: discord.Interaction):
        ledger = await self._get_ledger()
        # Nur Member der aktuellen Guild anzeigen (sicherheitshalber)
        ids = [str(m.id) for m in interaction.guild.members] 
        rows = [(uid, bal) for uid, bal in ledger.balances.items() if uid in ids]
        rows.sort(key=lambda x: x[1], reverse=True)
        top = rows[:10]

        if not top:
            await interaction.response.send_message("Noch keine Konten vorhanden.")
            return

        lines = []
        for i, (uid, bal) in enumerate(top, 1):
            member = interaction.guild.get_member(int(uid))  # type: ignore
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{i:>2}.** {name} — {CURRENCY} {fmt_amount(int(bal))}")

        embed = discord.Embed(
            title="🏆 Coins Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

# -------------------- Setup --------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Gambling(bot))
