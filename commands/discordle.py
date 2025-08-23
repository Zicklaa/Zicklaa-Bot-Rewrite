# discordle_cog.py
# -*- coding: utf-8 -*-
"""
Discordle / Bildcordle – Slash-Command-Version für discord.py 2.x
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from utils.logging_helper import log_event

logger = logging.getLogger("ZicklaaBotRewrite.Discordle")
logging.basicConfig(level=logging.INFO)

# --- Daten ---------------------------------------------------------------

user_list: Dict[int, str] = {
    255843901452189696: "Maik#4496",
    369579608615682071: "Windowmarker#8038",
    122721968406528001: "Lou E Coyote#3879",
    136103007065473024: "Krato#2209",
    240554673134764032: "vergyl#8505",
    288413759117066241: "z++#6969",
    189024459766759424: "exalibur#2817",
    119845703844495360: "Yoshii#0125",
    217030695799881729: "vladoks#9898",
    426347844748705792: "Armlehne#3129",
    227493008130572288: "somehowyellow#3394",
    197036529644863489: "Dinooooo#7276",
    226379429251776512: "grumbel#5982",
    218777864282177546: "Sunshower#2126",
    134035884507922433: "TheDavi#9963",
    191119825353965568: "Anna#0001",
    97427959731720192: "Guy.#2505",
    144981368294604811: "Kahimey#1948",
    370904224034455564: "Teutobald#7131",
    162863123617939456: "Turantel#1596",
    301096437511487498: "This is fine.#0549",
    128263704314773504: "Hebelios#4392",
    305615676544909323: "WMS#0001",
    428974837805875201: "BenSwolo#0751",
    176612606444830720: "Laufamholzer#7435",
    203169780180451328: "Dr Blazing Green Blaze#4072",
    253552795733458944: "Brotmann#5898",
    342019184689152024: "NooGravity#4345",
    205720251789213696: "JonSnowWhite#6467",
    413068385962819584: "galaali#1923",
    156136437887008771: "Dalton#5000",
    169427086539227136: "kyz3#9730",
    165549213378150400: "loixL#1107",
    373135654521143317: "SirTeaRex#2299",
    200009451292459011: "Fritzvonkola#6253",
    177808504881414144: "lucra400#4435",
    184773457005903873: "Zerus#8478",
    274204764068118529: "SpaceHippo#1896",
    232111930351943680: "Wabooti#8101",
    133886693379014656: "Jarmanien#0001",
    165575458954543104: "DieterTheHorst#1357",
    208949142729261056: "Olley#7784",
    148790752254754817: "mbn#0404",
    122738631646511106: "Ben#8168",
    107787146366066688: "Rilko#4768",
    179680865805271040: "&HansTrashy#0001",
    145444659240370176: "locke#5790",
    247064633599459328: "hanfi#8643",
    211519719075741698: "F2#2999",
    157917509046108161: "Flips#0815",
    749235359925272686: "senfglas#6741",
    231527378243813386: "Luca Bazooka#8144",
    148471614483202048: "DonMartino#1000",
    184372370486591489: "Jack#2126",
    192318108990570497: "Khas#2052",
    95480104779526144: "Neriik#1984",
}
unerwuenscht: Dict[int, str] = {
    571051961256902671: "Der Gelbfus Cowboy#1008",
    368105370532577280: "Zapier#0625",
    595627591118094347: 'Axel "Omega Prime" Werner#4331',
    335930325462941698: "Weltherrschaftsbot#7241",
    356268235697553409: ".fmbot#8173",
}
channel_ids: Dict[int, int] = {
    122739462210846721: 1449075600,
    486547650976677899: 1536072480,
    608746970340786282: 1565208000,
    608746838333587456: 1565208000,
    608785121449082898: 1565215200,
    735911531350458368: 1595525400,
    828045747101499462: 1617490800,
    614191599433547786: 1566504000,
    635242159880273921: 1571522400,
    528742785935998979: 1546131600,
    769960530290147378: 1603645200,
    675448334089060409: 1581109200,
    860154286141997056: 1625148000,
}
ext_list: Sequence[str] = (
    "3g2", "3gp", "amv", "asf", "avi", "gifv", "m4p", "m4v", "mov",
    "mp2", "mp4", "mpeg", "mpg", "webm", "mp3"
)

# --- Helpers -------------------------------------------------------------


def random_date_since(unix_start: int) -> datetime:
    current = int(time.time())
    stamp = random.randint(unix_start, current)
    return datetime.fromtimestamp(stamp)


def is_allowed_author(uid: int) -> bool:
    return uid in user_list and uid not in unerwuenscht


async def fetch_random_messages(ch: discord.TextChannel, around: datetime, limit=100):
    return [m async for m in ch.history(limit=limit, around=around)]


def pick_candidates(correct: str, pool: Iterable[str], k: int = 4) -> List[str]:
    cands = {correct}
    pool_list = list(pool)
    random.shuffle(pool_list)
    for name in pool_list:
        if len(cands) >= k:
            break
        cands.add(name)
    result = list(cands)
    random.shuffle(result)
    return result


def is_image_like(url: str) -> bool:
    return not any(url.lower().endswith("." + ext) for ext in ext_list)


async def add_guess_reactions(msg: discord.Message):
    for emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "❌"]:
        try:
            await msg.add_reaction(emoji)
        except Exception as e:
            log_event(
                logger,
                logging.WARNING,
                "Discordle",
                "Reaction add failed",
                emoji=emoji,
                error=e,
                exc_info=True,
            )

# --- Embeds --------------------------------------------------------------


def build_text_embed(ctx_user: str, message: discord.Message, candidates: Sequence[str]):
    e = discord.Embed(
        title="Discordle",
        description="Welcher User hat dieses lyrische Meisterwerk verfasst?",
        color=0x00FF00,
    )
    e.set_author(
        name="Mysteriös",
        icon_url="https://i.pinimg.com/564x/b5/46/3c/b5463c3591ec63cf076ac48179e3b0db.jpg",
    )
    e.set_footer(text=f"Discordle by: {ctx_user}")
    e.add_field(name="**Runde 1**", value=message.content, inline=False)
    e.add_field(name="**Runde 2**",
                value=f"||{message.created_at:%d.%m.%Y, %H:%M}||", inline=False)
    e.add_field(name="**Runde 3**",
                value="||#" +
                str(message.channel).ljust(
                    random.randint(25, 50), "\u2000")+"||",
                inline=False)
    e.add_field(name="**Runde 4**", value="||" +
                "\n".join(candidates) + "||", inline=False)
    e.add_field(name="**Auflösung**",
                value="||" +
                str(message.author).ljust(random.randint(25, 50), "\u2000")
                + f"\n[Link zur Nachricht]({message.jump_url})||",
                inline=False)
    return e


def build_image_embed(ctx_user: str, message: discord.Message, img_url: str, candidates: Sequence[str]):
    e = discord.Embed(
        title="Bildcordle",
        description="Welcher User hat dieses optische Meisterwerk verfasst?",
        color=0x00FF00,
    )
    e.set_author(
        name="Mysteriös",
        icon_url="https://i.pinimg.com/564x/b5/46/3c/b5463c3591ec63cf076ac48179e3b0db.jpg",
    )
    e.set_footer(text=f"Discordle by: {ctx_user}")
    e.set_image(url=img_url)
    e.add_field(name="**Runde 1**", value="Siehe Bild", inline=False)
    e.add_field(name="**Runde 2**",
                value=f"||{message.created_at:%d.%m.%Y, %H:%M}||", inline=False)
    e.add_field(name="**Runde 3**",
                value="||#" +
                str(message.channel).ljust(
                    random.randint(25, 50), "\u2000")+"||",
                inline=False)
    e.add_field(name="**Runde 4**", value="||" +
                "\n".join(candidates) + "||", inline=False)
    e.add_field(name="**Auflösung**",
                value="||" +
                str(message.author).ljust(random.randint(25, 50), "\u2000")
                + f"\n[Link zur Nachricht]({message.jump_url})||",
                inline=False)
    return e

# --- Cog ----------------------------------------------------------------


@dataclass
class ChannelSource:
    cid: int
    start: int


class Discordle(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sources = [ChannelSource(cid, s)
                        for cid, s in channel_ids.items()]
        self.usernames = list(user_list.values())

    async def _pick_channel(self) -> Optional[discord.TextChannel]:
        src = random.choice(self.sources)
        ch = self.bot.get_channel(src.cid)
        if isinstance(ch, discord.TextChannel):
            return ch
        try:
            ch = await self.bot.fetch_channel(src.cid)
            return ch if isinstance(ch, discord.TextChannel) else None
        except:
            return None

    async def _pick_text_msg(self) -> Optional[discord.Message]:
        for _ in range(8):
            ch = await self._pick_channel()
            if not ch:
                continue
            around = random_date_since(
                channel_ids.get(ch.id, int(time.time())))
            msgs = await fetch_random_messages(ch, around, 100)
            random.shuffle(msgs)
            for m in msgs:
                if (m.content and is_allowed_author(m.author.id)
                        and 5 < len(m.content.split()) < 50):
                    return m
        return None

    async def _pick_image_msg(self) -> Optional[Tuple[discord.Message, str]]:
        for _ in range(8):
            ch = await self._pick_channel()
            if not ch:
                continue
            around = random_date_since(
                channel_ids.get(ch.id, int(time.time())))
            msgs = await fetch_random_messages(ch, around, 100)
            random.shuffle(msgs)
            for m in msgs:
                if is_allowed_author(m.author.id) and m.attachments:
                    for att in m.attachments:
                        if is_image_like(att.url):
                            return m, att.url
        return None

    @app_commands.command(name="discordle", description="Starte eine Discordle-Runde (Text).")
    async def cmd_dc(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        msg = await self._pick_text_msg()
        if not msg:
            await interaction.followup.send("Was ist denn mit Karsten los??")
            return
        cands = pick_candidates(str(msg.author), self.usernames, 4)
        emb = build_text_embed(interaction.user.display_name, msg, cands)
        out = await interaction.followup.send(embed=emb)
        await add_guess_reactions(out)

    @app_commands.command(name="bildcordle", description="Starte eine Bildcordle-Runde (Bild).")
    async def cmd_bc(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        found = await self._pick_image_msg()
        if not found:
            await interaction.followup.send("Was ist denn mit Karsten los??")
            return
        msg, url = found
        cands = pick_candidates(str(msg.author), self.usernames, 4)
        emb = build_image_embed(interaction.user.display_name, msg, url, cands)
        out = await interaction.followup.send(embed=emb)
        await add_guess_reactions(out)

# --- Setup ---------------------------------------------------------------


async def setup(bot: commands.Bot):
    await bot.add_cog(Discordle(bot))
