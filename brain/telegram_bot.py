"""
BOB — Telegram Bot for Remote Security & Control
Works from ANYWHERE in the world — no port forwarding needed.

Features:
  • Motion alert with snapshot photo
  • /start   — welcome message
  • /status  — BOB's current state, obstacle distance, roll/pitch
  • /camera  — get a current snapshot from the camera
  • /drive <direction> [speed] — forward/back/left/right/stop
  • /emotion <name> — change BOB's face
  • /say <text> — make BOB speak something
  • /patrol  — start/stop autonomous patrol

Setup (one time):
  1. Message @BotFather on Telegram → /newbot → get TOKEN
  2. Get your chat ID: message @userinfobot
  3. Set BOB_TELEGRAM_TOKEN and BOB_TELEGRAM_CHAT_ID in environment
     or in /home/arduino/bob/.env file

Install: already included in venv (python-telegram-bot via httpx)
We use raw Bot API HTTP calls (no extra library needed).
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("telegram")

# ── Config ────────────────────────────────────────────────────────────────────
# Set these in /home/arduino/bob/.env or as environment variables
TOKEN   = os.getenv("BOB_TELEGRAM_TOKEN",  "")    # Bot token from @BotFather
CHAT_ID = os.getenv("BOB_TELEGRAM_CHAT_ID", "")   # Your personal chat ID

API     = f"https://api.telegram.org/bot{TOKEN}"
POLL_INTERVAL = 1.5   # seconds between polling for updates


class TelegramBot:
    def __init__(self, brain_ref):
        self._brain   = brain_ref
        self._client  = httpx.AsyncClient(timeout=15.0)
        self._running = False
        self._offset  = 0     # Telegram update offset
        self._enabled = bool(TOKEN and CHAT_ID)

        if not self._enabled:
            log.warning(
                "Telegram bot disabled — set BOB_TELEGRAM_TOKEN and "
                "BOB_TELEGRAM_CHAT_ID in /home/arduino/bob/.env"
            )

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    async def start(self):
        if not self._enabled:
            return
        self._running = True
        log.info("Telegram bot polling started")
        await self.send_message("🤖 *BOB is online!*\nI'm watching the house\\. Send /help for commands\\.")
        asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._enabled:
            await self.send_message("😴 BOB is going offline\\.")
        await self._client.aclose()

    # ──────────────────────────────────────────
    # Alert — called by SecurityCamera
    # ──────────────────────────────────────────

    async def send_motion_alert(self, snapshot_bytes: bytes, area: float):
        """Send motion detection alert with snapshot photo."""
        if not self._enabled:
            return
        caption = (
            f"🚨 *MOTION DETECTED*\n"
            f"Area: {area:.0f}px²\n"
            f"Time: {time.strftime('%H:%M:%S')}\n\n"
            f"Reply:\n"
            f"`/camera` \\- live snapshot\n"
            f"`/stop` \\- stop BOB motors"
        )
        await self._send_photo(snapshot_bytes, caption)

    # ──────────────────────────────────────────
    # Send helpers
    # ──────────────────────────────────────────

    async def send_message(self, text: str):
        if not self._enabled:
            return
        try:
            await self._client.post(f"{API}/sendMessage", json={
                "chat_id":    CHAT_ID,
                "text":       text,
                "parse_mode": "MarkdownV2",
            })
        except Exception as e:
            log.warning("Telegram send error: %s", e)

    async def _send_photo(self, photo_bytes: bytes, caption: str = ""):
        if not self._enabled:
            return
        try:
            await self._client.post(
                f"{API}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption,
                      "parse_mode": "MarkdownV2"},
                files={"photo": ("snap.jpg", photo_bytes, "image/jpeg")},
            )
        except Exception as e:
            log.warning("Telegram photo error: %s", e)

    async def _send_document(self, data: bytes, filename: str):
        try:
            await self._client.post(
                f"{API}/sendDocument",
                data={"chat_id": CHAT_ID},
                files={"document": (filename, data, "application/octet-stream")},
            )
        except Exception as e:
            log.warning("Telegram doc error: %s", e)

    # ──────────────────────────────────────────
    # Polling loop
    # ──────────────────────────────────────────

    async def _poll_loop(self):
        while self._running:
            try:
                r = await self._client.get(
                    f"{API}/getUpdates",
                    params={"offset": self._offset, "timeout": 10},
                    timeout=15.0,
                )
                data = r.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        await self._handle_update(update)
            except Exception as e:
                log.debug("Telegram poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    async def _handle_update(self, update: dict):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        # Security: only accept from authorised chat
        if str(msg.get("chat", {}).get("id", "")) != str(CHAT_ID):
            return

        text = (msg.get("text") or "").strip().lower()
        log.info("Telegram command: %s", text)

        if text.startswith("/start") or text.startswith("/help"):
            await self.send_message(
                "🤖 *BOB Remote Control*\n\n"
                "/status \\— robot status\n"
                "/camera \\— live snapshot\n"
                "/drive forward \\— move forward\n"
                "/drive back \\— move backward\n"
                "/drive left \\— strafe left\n"
                "/drive right \\— strafe right\n"
                "/drive stop \\— stop motors\n"
                "/patrol \\— toggle patrol mode\n"
                "/emotion happy \\— change face\n"
                "/say Hello\\! \\— make BOB speak\n"
                "/snapshots \\— list recent snapshots"
            )

        elif text.startswith("/status"):
            await self._cmd_status()

        elif text.startswith("/camera"):
            await self._cmd_camera()

        elif text.startswith("/drive"):
            parts = text.split()
            direction = parts[1] if len(parts) > 1 else "stop"
            speed     = int(parts[2]) if len(parts) > 2 else 180
            await self._cmd_drive(direction, speed)

        elif text.startswith("/stop"):
            await self._cmd_drive("stop", 0)

        elif text.startswith("/patrol"):
            await self._cmd_patrol()

        elif text.startswith("/emotion"):
            parts = text.split()
            emo   = parts[1] if len(parts) > 1 else "idle"
            await self._brain.handle_web_command({"action": "emotion", "name": emo})
            await self.send_message(f"😊 Emotion set to `{emo}`")

        elif text.startswith("/say"):
            phrase = text[4:].strip()
            if phrase:
                asyncio.create_task(self._brain.handle_voice_input(phrase))
                await self.send_message(f"🔊 BOB says: _{phrase}_")

        elif text.startswith("/snapshots"):
            await self._cmd_snapshots()

    # ──────────────────────────────────────────
    # Commands
    # ──────────────────────────────────────────

    async def _cmd_status(self):
        t = self._brain.telemetry
        obs = self._brain.obstacle_distance
        state = self._brain.state.name

        msg = (
            f"🤖 *BOB Status*\n"
            f"State: `{state}`\n"
            f"Obstacle: `{obs:.1f} cm`\n"
            f"Roll: `{t.get('roll', 0):.1f}°`\n"
            f"Pitch: `{t.get('pitch', 0):.1f}°`\n"
            f"E\\-Stop: `{'YES ⚠️' if t.get('estop') else 'No'}`\n"
            f"IMU: `{'OK ✓' if t.get('ok') else 'Error'}`"
        )
        await self.send_message(msg)

    async def _cmd_camera(self):
        # Get snapshot from security camera via brain reference
        cam = getattr(self._brain, '_security_cam', None)
        if cam:
            frame = cam.get_latest_frame()
            if frame:
                await self._send_photo(frame, f"📷 `{time.strftime('%H:%M:%S')}`")
                return
        await self.send_message("📷 Camera not available")

    async def _cmd_drive(self, direction: str, speed: int):
        speed = min(255, max(0, speed))
        cmd_map = {
            "forward": {"vy":  speed, "vx": 0,     "omega": 0},
            "back":    {"vy": -speed, "vx": 0,     "omega": 0},
            "left":    {"vy": 0,      "vx": -speed, "omega": 0},
            "right":   {"vy": 0,      "vx":  speed, "omega": 0},
            "stop":    {"vy": 0,      "vx": 0,     "omega": 0},
        }
        if direction not in cmd_map:
            await self.send_message(f"Unknown direction: `{direction}`")
            return
        vals = cmd_map[direction]
        await self._brain.handle_web_command({
            "action": "move", **vals
        })
        icon = {"forward":"⬆️","back":"⬇️","left":"⬅️","right":"➡️","stop":"⏹"}.get(direction,"▶️")
        await self.send_message(f"{icon} Driving `{direction}` at speed `{speed}`")

    async def _cmd_patrol(self):
        # Toggle patrol mode in brain
        if hasattr(self._brain, 'toggle_patrol'):
            patrolling = await self._brain.toggle_patrol()
            await self.send_message(
                f"{'🔍 Patrol started' if patrolling else '⏹ Patrol stopped'}"
            )
        else:
            await self.send_message("Patrol not implemented yet")

    async def _cmd_snapshots(self):
        snaps = sorted(SNAPSHOT_DIR.glob("*.jpg"))[-5:]  # last 5
        if not snaps:
            await self.send_message("No snapshots yet")
            return
        await self.send_message(f"📂 Last {len(snaps)} snapshot\\(s\\):")
        for snap in snaps:
            data = snap.read_bytes()
            ts   = snap.stem.replace("motion_", "")
            try:
                caption = f"🕐 `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(ts)))}`"
            except Exception:
                caption = snap.name
            await self._send_photo(data, caption)
