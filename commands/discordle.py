"""/discordle & /bildcordle – Ratespiel: Wer hat diese Nachricht bzw. dieses Bild gepostet?"""

import random
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.base import BaseCog, UserError
from utils.helpers import fetch_channel, truncate

# -------------------- Daten --------------------

# Mitspieler: nur Nachrichten dieser User werden gezogen, ihre Namen sind die Antwortmöglichkeiten
USER_LIST: dict[int, str] = {
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
# Bots & Co., die nie gezogen werden
UNERWUENSCHT: dict[int, str] = {
    571051961256902671: "Der Gelbfus Cowboy#1008",
    368105370532577280: "Zapier#0625",
    595627591118094347: 'Axel "Omega Prime" Werner#4331',
    335930325462941698: "Weltherrschaftsbot#7241",
    356268235697553409: ".fmbot#8173",
}
# Channel-ID -> Unix-Timestamp, ab dem zufällige Nachrichten gezogen werden
CHANNEL_IDS: dict[int, int] = {
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
# Anhänge mit diesen Endungen sind keine Bilder (Videos/Audio)
NON_IMAGE_EXTENSIONS = (
    "3g2", "3gp", "amv", "asf", "avi", "gifv", "m4p", "m4v", "mov",
    "mp2", "mp4", "mpeg", "mpg", "webm", "mp3",
)

GUESS_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "❌")
MYSTERY_ICON = "https://i.pinimg.com/564x/b5/46/3c/b5463c3591ec63cf076ac48179e3b0db.jpg"
ATTEMPTS = 8  # so viele zufällige Stellen werden probiert, bevor aufgegeben wird

# -------------------- Helpers --------------------


def is_allowed_author(uid: int) -> bool:
    return uid in USER_LIST and uid not in UNERWUENSCHT


def is_image_like(url: str) -> bool:
    return not url.lower().endswith(tuple("." + ext for ext in NON_IMAGE_EXTENSIONS))


def pick_candidates(correct: str, pool: list[str], k: int = 4) -> list[str]:
    """Liefert k gemischte Antwortmöglichkeiten inklusive der richtigen."""
    others = random.sample([name for name in pool if name != correct], k - 1)
    candidates = [correct, *others]
    random.shuffle(candidates)
    return candidates


def spoiler_padded(text: str) -> str:
    """Spoiler mit zufälliger Breite, damit die Länge nichts verrät."""
    return text.ljust(random.randint(25, 50), "\u2000")


def build_embed(
    title: str, question: str, host: str, message: discord.Message,
    candidates: list[str], *, round_one: str, image_url: str | None = None,
) -> discord.Embed:
    """Baut das Rätsel-Embed: jede Runde verrät per Spoiler etwas mehr."""
    embed = discord.Embed(title=title, description=question, color=0x00FF00)
    embed.set_author(name="Mysteriös", icon_url=MYSTERY_ICON)
    embed.set_footer(text=f"Discordle by: {host}")
    if image_url:
        embed.set_image(url=image_url)

    rounds = {
        "Runde 1": round_one,
        "Runde 2": f"||{message.created_at:%d.%m.%Y, %H:%M}||",
        "Runde 3": f"||#{spoiler_padded(str(message.channel))}||",
        "Runde 4": "||" + "\n".join(candidates) + "||",
        "Auflösung": f"||{spoiler_padded(str(message.author))}\n[Link zur Nachricht]({message.jump_url})||",
    }
    for name, value in rounds.items():
        embed.add_field(name=f"**{name}**", value=value, inline=False)
    return embed


# -------------------- Cog --------------------


class Discordle(BaseCog):
    """Cog: /discordle (Text) & /bildcordle (Bild)."""

    async def _random_messages(self) -> list[discord.Message]:
        """Lädt bis zu 100 Nachrichten rund um einen zufälligen Zeitpunkt aus einem zufälligen Channel."""
        channel_id, start = random.choice(list(CHANNEL_IDS.items()))
        try:
            channel = await fetch_channel(self.bot, channel_id)
        except discord.HTTPException:
            return []
        if not isinstance(channel, discord.TextChannel):
            return []

        around = datetime.fromtimestamp(random.randint(start, int(time.time())))
        messages = [m async for m in channel.history(limit=100, around=around)]
        random.shuffle(messages)
        return [m for m in messages if is_allowed_author(m.author.id)]

    async def _pick_text_msg(self) -> discord.Message | None:
        """Sucht eine Textnachricht mit 6–49 Wörtern."""
        for _ in range(ATTEMPTS):
            for m in await self._random_messages():
                if m.content and 5 < len(m.content.split()) < 50:
                    return m
        return None

    async def _pick_image_msg(self) -> tuple[discord.Message, str] | None:
        """Sucht eine Nachricht mit Bild-Anhang; gibt (Nachricht, Bild-URL) zurück."""
        for _ in range(ATTEMPTS):
            for m in await self._random_messages():
                for att in m.attachments:
                    if is_image_like(att.url):
                        return m, att.url
        return None

    async def _send_round(self, interaction: discord.Interaction, embed: discord.Embed):
        """Schickt das Rätsel und hängt die Rate-Reaktionen an."""
        out = await interaction.followup.send(embed=embed, wait=True)
        for emoji in GUESS_EMOJIS:
            try:
                await out.add_reaction(emoji)
            except discord.HTTPException as e:
                self.log("Reaction add failed", interaction, emoji=emoji, error=e)
        self.log("Round started", interaction, title=embed.title)

    def _candidates(self, message: discord.Message) -> list[str]:
        return pick_candidates(str(message.author), list(USER_LIST.values()))

    @app_commands.command(name="discordle", description="Starte eine Discordle-Runde (Text).")
    async def cmd_dc(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        msg = await self._pick_text_msg()
        if not msg:
            raise UserError("Was ist denn mit Karsten los??")

        await self._send_round(interaction, build_embed(
            "Discordle", "Welcher User hat dieses lyrische Meisterwerk verfasst?",
            interaction.user.display_name, msg, self._candidates(msg), round_one=truncate(msg.content, 1024),
        ))

    @app_commands.command(name="bildcordle", description="Starte eine Bildcordle-Runde (Bild).")
    async def cmd_bc(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        found = await self._pick_image_msg()
        if not found:
            raise UserError("Was ist denn mit Karsten los??")

        msg, url = found
        await self._send_round(interaction, build_embed(
            "Bildcordle", "Welcher User hat dieses optische Meisterwerk verfasst?",
            interaction.user.display_name, msg, self._candidates(msg), round_one="Siehe Bild", image_url=url,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Discordle(bot))
