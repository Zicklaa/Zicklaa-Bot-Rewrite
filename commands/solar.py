"""/solar – Live-Daten der Ziegler PV-Anlage (Sungrow-Wechselrichter per Modbus)."""

import asyncio
import logging
import struct

import discord
from discord import app_commands
from discord.ext import commands
from pymodbus.client import ModbusTcpClient

from utils.base import BaseCog, UserError
from utils.logging_helper import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.Solar")

IP_ADDRESS = "192.168.0.43"
PORT = 502


def decode_int16(val: int) -> int:
    """Vorzeichenbehafteter 16-Bit Wert (für Netz- und Batterierichtung)."""
    return struct.unpack("h", struct.pack("H", val))[0]


def fetch_sungrow_data() -> dict | None:
    """Synchroner Modbus-Call zur WiNet-S mit korrigierter Tagesverbrauchs-Formel."""
    client = ModbusTcpClient(IP_ADDRESS, port=PORT, timeout=3)
    if not client.connect():
        return None

    try:
        res = client.read_input_registers(address=13000, count=45)
        if res.isError():
            return None

        r = res.registers

        # Saubere Tageswerte (in kWh)
        pv_daily = r[1] / 10.0               # Reg 13001: PV Ertrag Heute
        grid_import_daily = r[15] / 10.0     # Reg 13015: Netzbezug Heute
        grid_export_daily = r[16] / 10.0     # Reg 13016: Einspeisung Heute (Tageswert!)
        bat_charge_daily = r[26] / 10.0      # Reg 13026: Akku Geladen Heute
        bat_discharge_daily = r[29] / 10.0   # Reg 13029: Akku Entladen Heute

        # Korrekter Tages-Hausverbrauch (PV + Bezug + Akku-Entladung - Einspeisung - Akku-Ladung)
        calculated_house_daily = pv_daily + grid_import_daily + bat_discharge_daily - grid_export_daily - bat_charge_daily
        house_daily = round(max(0.0, calculated_house_daily), 1)

        return {
            "pv_power_w": r[33],                    # Reg 13033
            "pv_daily_kwh": pv_daily,               # Reg 13001
            "house_power_w": r[7],                  # Reg 13007
            "house_daily_kwh": house_daily,         # Korrigierter Tagesverbrauch
            "grid_power_w": decode_int16(r[9]),     # Reg 13009
            "grid_import_daily_kwh": grid_import_daily, # Reg 13015
            "grid_export_daily_kwh": grid_export_daily, # Reg 13016
            "battery_soc": r[22] / 10.0,            # Reg 13022
            "battery_soh": r[23] / 10.0,            # Reg 13023
            "battery_temp": r[24] / 10.0,           # Reg 13024
            "battery_power_w": decode_int16(r[25]), # Reg 13025
            "bat_charge_daily_kwh": bat_charge_daily,   # Reg 13026
            "bat_discharge_daily_kwh": bat_discharge_daily # Reg 13029
        }
    except Exception as e:
        logger.error(f"Fehler beim Lesen der Modbus-Daten: {e}")
        return None
    finally:
        client.close()


class Solar(BaseCog):
    """Cog: /solar – Fragt Live-Daten der Ziegler PV-Anlage ab."""

    @app_commands.command(
        name="solar",
        description="Zeigt den aktuellen Status der Ziegler PV-Anlage.",
        extras={"error": "Solar Schmolar, Fehler beim Abrufen der PV-Daten."},
    )
    async def solar(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Modbus-Client ist synchron -> in einen Thread auslagern
        data = await asyncio.to_thread(fetch_sungrow_data)
        if not data:
            raise UserError("❌ **Fehler:** Wechselrichter der Ziegler PV-Anlage ist aktuell nicht erreichbar.")

        # Status-Logik
        bat_pwr = data["battery_power_w"]
        if bat_pwr > 0:
            bat_status = f"⚡ Laden ({bat_pwr} W)"
        elif bat_pwr < 0:
            bat_status = f"🔋 Entladen ({abs(bat_pwr)} W)"
        else:
            bat_status = "💤 Standby"

        grid_pwr = data["grid_power_w"]
        if grid_pwr > 0:
            grid_status = f"🟢 Einspeisung ({grid_pwr} W)"
        elif grid_pwr < 0:
            grid_status = f"🔴 Netzbezug ({abs(grid_pwr)} W)"
        else:
            grid_status = "⚪ Neutral (0 W)"

        # Embed Erstellung
        embed = discord.Embed(
            title="☀️ Ziegler PV-Anlage Status",
            color=discord.Color.gold() if data["pv_power_w"] > 0 else discord.Color.dark_blue(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="☀️ Photovoltaik",
            value=(
                f"**Leistung:** `{data['pv_power_w']} W`\n"
                f"**Ertrag Heute:** `{data['pv_daily_kwh']:.1f} kWh`"
            ),
            inline=True
        )

        embed.add_field(
            name="🔋 Speicher",
            value=(
                f"**SOC:** `{data['battery_soc']:.1f}%` *(SOH {data['battery_soh']:.0f}%)*\n"
                f"**Status:** `{bat_status}`\n"
                f"**Geladen Heute:** `{data['bat_charge_daily_kwh']:.1f} kWh`\n"
                f"**Entladen Heute:** `{data['bat_discharge_daily_kwh']:.1f} kWh`\n"
                f"**Temperatur:** `{data['battery_temp']:.1f} °C`"
            ),
            inline=True
        )

        embed.add_field(
            name="🏠 Haus & Netz",
            value=(
                f"**Verbrauch Aktuell:** `{data['house_power_w']} W`\n"
                f"**Verbrauch Heute:** `{data['house_daily_kwh']:.1f} kWh`\n"
                f"**Netz Status:** `{grid_status}`\n"
                f"**Einspeisung Heute:** `{data['grid_export_daily_kwh']:.1f} kWh`\n"
                f"**Bezug Heute:** `{data['grid_import_daily_kwh']:.1f} kWh`"
            ),
            inline=False
        )

        embed.set_footer(text="Ziegler PV-Anlage")

        await interaction.followup.send(embed=embed)
        self.log("Solar dashboard sent", interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Solar(bot))
