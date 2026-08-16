"""
BOB — Smart Light Controller
Controls Wipro and Havells smart lights (both Tuya-based under the hood)
LOCALLY via WiFi — no cloud, no Google, no internet required.

How it works:
  Tuya smart devices communicate over your local WiFi using a documented
  local protocol. tinytuya implements this protocol in Python.

Setup (one time — ~10 minutes):
  1. Open Tuya IoT Platform (iot.tuya.com) → free account
  2. Create a cloud project → get Access ID + Secret
  3. Run: python3 -m tinytuya wizard
     (scans your local network, finds devices, saves IDs + keys)
  4. Paste the device IDs and keys into /home/arduino/bob/.env

Alternatively — use tinytuya scan directly:
  python3 -m tinytuya scan
  (may find devices without needing the cloud account)

BOB voice commands (handled by LLM → light_controller):
  "turn on the lights"
  "turn off the lights"
  "set lights to blue"
  "make lights warm white"
  "dim the lights to 50%"
  "set lights to party mode"  → cycling colours
"""

import asyncio
import logging
import os
from typing import Optional

log = logging.getLogger("lights")

# ── Config (from .env) ────────────────────────────────────────────────────────
# After running tinytuya wizard, fill these in .env:
#
#   BOB_LIGHT_1_ID=xxxxxxxxxxxxxxx       # Wipro light device ID
#   BOB_LIGHT_1_KEY=xxxxxxxxxxxxxxxx     # Local key (16 chars)
#   BOB_LIGHT_1_IP=192.168.1.xx          # IP on your local network
#
#   BOB_LIGHT_2_ID=xxxxxxxxxxxxxxx       # Havells light device ID
#   BOB_LIGHT_2_KEY=xxxxxxxxxxxxxxxx
#   BOB_LIGHT_2_IP=192.168.1.xx

LIGHT_CONFIGS = []
for i in range(1, 5):   # supports up to 4 lights
    dev_id  = os.getenv(f"BOB_LIGHT_{i}_ID",  "")
    dev_key = os.getenv(f"BOB_LIGHT_{i}_KEY", "")
    dev_ip  = os.getenv(f"BOB_LIGHT_{i}_IP",  "")
    name    = os.getenv(f"BOB_LIGHT_{i}_NAME", f"Light {i}")
    if dev_id and dev_key and dev_ip:
        LIGHT_CONFIGS.append({"id": dev_id, "key": dev_key,
                               "ip": dev_ip, "name": name})

# ── Colour presets (HSV — Tuya format: H 0-360, S 0-1000, V 0-1000) ──────────
COLOUR_PRESETS = {
    "white":      (0,    0,    1000),
    "warm white": (30,   200,  1000),
    "cool white": (200,  100,  1000),
    "red":        (0,    1000, 1000),
    "green":      (120,  1000, 900),
    "blue":       (240,  1000, 1000),
    "purple":     (270,  1000, 900),
    "orange":     (30,   1000, 1000),
    "pink":       (340,  800,  1000),
    "yellow":     (60,   1000, 1000),
    "teal":       (180,  1000, 900),
    "night":      (30,   500,  200),    # dim warm
    "focus":      (200,  100,  1000),   # bright cool white
    "relax":      (30,   400,  600),    # dim warm amber
}


try:
    import tinytuya
    TUYA_OK = True
except ImportError:
    TUYA_OK = False
    log.warning("tinytuya not installed — light control disabled. "
                "Run: pip install tinytuya")


class LightController:
    def __init__(self):
        self._devices: list[dict] = []
        self._ready = False
        self._party_task: Optional[asyncio.Task] = None

    # ──────────────────────────────────────────
    # Startup
    # ──────────────────────────────────────────

    async def start(self) -> bool:
        if not TUYA_OK:
            return False
        if not LIGHT_CONFIGS:
            log.warning(
                "No lights configured. Run 'python3 -m tinytuya wizard' "
                "then add BOB_LIGHT_1_ID / KEY / IP to .env"
            )
            return False

        loop = asyncio.get_event_loop()
        self._devices = await loop.run_in_executor(None, self._init_devices)
        self._ready   = len(self._devices) > 0
        log.info("Light controller: %d light(s) ready", len(self._devices))
        return self._ready

    def _init_devices(self) -> list:
        devs = []
        for cfg in LIGHT_CONFIGS:
            try:
                d = tinytuya.BulbDevice(cfg["id"], cfg["ip"], cfg["key"])
                d.set_version(3.3)
                d.set_socketTimeout(3)
                status = d.status()
                if status:
                    devs.append({"device": d, "name": cfg["name"]})
                    log.info("Light '%s' connected at %s", cfg["name"], cfg["ip"])
            except Exception as e:
                log.warning("Light '%s' error: %s", cfg.get("name", "?"), e)
        return devs

    # ──────────────────────────────────────────
    # Commands (called by brain from voice/web)
    # ──────────────────────────────────────────

    async def turn_on(self, names: list[str] = None):
        await self._run_on_devices("turn_on", names)
        log.info("Lights ON")

    async def turn_off(self, names: list[str] = None):
        self._stop_party()
        await self._run_on_devices("turn_off", names)
        log.info("Lights OFF")

    async def set_brightness(self, pct: int, names: list[str] = None):
        """Set brightness 0-100%."""
        pct = max(0, min(100, pct))
        await self._run_on_devices("set_brightness_percentage", names, pct)
        log.info("Lights brightness → %d%%", pct)

    async def set_colour(self, colour: str, names: list[str] = None):
        """Set colour by name (from COLOUR_PRESETS) or hex (#RRGGBB)."""
        self._stop_party()

        if colour.startswith("#") and len(colour) == 7:
            h, s, v = self._hex_to_hsv(colour)
        else:
            h, s, v = COLOUR_PRESETS.get(colour.lower(),
                                          COLOUR_PRESETS["white"])
        await self._run_on_devices("set_hsv", names, h, s / 1000, v / 1000)
        log.info("Lights colour → %s (H%d S%d V%d)", colour, h, s, v)

    async def set_white(self, temp_k: int = 4000, brightness: int = 100,
                        names: list[str] = None):
        """Set white with colour temperature (2700K warm → 6500K cool)."""
        self._stop_party()
        # Map 2700-6500K to 0-1000 Tuya scale
        t = int((temp_k - 2700) / (6500 - 2700) * 1000)
        b = max(10, min(1000, brightness * 10))
        await self._run_on_devices("set_colourtemp", names, t)
        await self._run_on_devices("set_brightness", names, b)
        log.info("Lights white: %dK %d%%", temp_k, brightness)

    async def party_mode(self, interval: float = 1.0, names: list[str] = None):
        """Cycle through colours — party mode!"""
        self._stop_party()
        colours = list(COLOUR_PRESETS.keys())
        idx = [0]

        async def _cycle():
            while True:
                col = colours[idx[0] % len(colours)]
                await self.set_colour(col, names)
                idx[0] += 1
                await asyncio.sleep(interval)

        self._party_task = asyncio.create_task(_cycle())
        log.info("Party mode ON")

    def _stop_party(self):
        if self._party_task and not self._party_task.done():
            self._party_task.cancel()
            self._party_task = None

    # ──────────────────────────────────────────
    # Voice command parser
    # ──────────────────────────────────────────

    async def handle_voice_command(self, text: str) -> bool:
        """
        Parse a natural-language voice command and act on it.
        Returns True if command was handled.
        Called by the brain when LLM identifies a light command.
        """
        t = text.lower().strip()

        if any(w in t for w in ["turn on", "lights on", "switch on", "on the light"]):
            await self.turn_on()
            return True

        if any(w in t for w in ["turn off", "lights off", "switch off", "off the light"]):
            await self.turn_off()
            return True

        if "party" in t or "disco" in t:
            await self.party_mode()
            return True

        if "dim" in t or "low" in t:
            await self.set_brightness(30)
            return True

        if "bright" in t or "full" in t or "maximum" in t:
            await self.set_brightness(100)
            return True

        if "half" in t or "50" in t:
            await self.set_brightness(50)
            return True

        if "warm" in t:
            await self.set_white(temp_k=2700, brightness=80)
            return True

        if "cool" in t or "focus" in t or "study" in t:
            await self.set_white(temp_k=6000, brightness=100)
            return True

        if "relax" in t or "night" in t or "sleep" in t:
            await self.set_colour("night")
            return True

        # Check for specific colour names
        for colour in COLOUR_PRESETS:
            if colour in t:
                await self.set_colour(colour)
                return True

        # Check for brightness percentage: "set to 70 percent"
        import re
        m = re.search(r'(\d+)\s*(?:percent|%)', t)
        if m:
            await self.set_brightness(int(m.group(1)))
            return True

        return False   # Not a light command

    # ──────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────

    async def _run_on_devices(self, method: str, names: list[str],
                              *args):
        """Run a tinytuya method on selected (or all) devices."""
        if not self._ready:
            return
        loop = asyncio.get_event_loop()
        targets = self._devices if not names else [
            d for d in self._devices if d["name"] in names
        ]
        for dev_info in targets:
            dev = dev_info["device"]
            await loop.run_in_executor(
                None, lambda d=dev, m=method, a=args: getattr(d, m)(*a)
            )

    @staticmethod
    def _hex_to_hsv(hex_col: str):
        """Convert #RRGGBB to Tuya HSV (H 0-360, S 0-1000, V 0-1000)."""
        import colorsys
        r = int(hex_col[1:3], 16) / 255
        g = int(hex_col[3:5], 16) / 255
        b = int(hex_col[5:7], 16) / 255
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        return int(h * 360), int(s * 1000), int(v * 1000)

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def device_names(self) -> list[str]:
        return [d["name"] for d in self._devices]
