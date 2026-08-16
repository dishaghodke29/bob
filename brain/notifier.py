"""
BOB — Push Notifications via ntfy.sh
Zero-setup push notifications to your phone from anywhere.

How it works:
  BOB sends an HTTP POST to ntfy.sh with a topic only you know.
  Your phone gets an instant push notification via the free ntfy app.
  No account required. No tokens. Just a secret topic name.

Setup (2 minutes):
  1. Install "ntfy" app on your phone (Android / iOS — free)
  2. In the app, subscribe to your topic: e.g.  bob-robot-xyz123
  3. Set BOB_NTFY_TOPIC in /home/arduino/bob/.env
     (make it something random so others can't subscribe)

That's it. BOB will push alerts to your phone instantly.

Extra features:
  • Also writes a Cloudflare Tunnel URL to /home/arduino/bob/logs/tunnel.log
    so you can access the live dashboard from anywhere.
  • Optional: self-host ntfy on the UNO Q for fully private alerts.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("notifier")

# ── Config ────────────────────────────────────────────────────────────────────
NTFY_TOPIC   = os.getenv("BOB_NTFY_TOPIC",  "bob-robot-changeme")
NTFY_SERVER  = os.getenv("BOB_NTFY_SERVER", "https://ntfy.sh")   # or self-hosted
COOLDOWN     = 10.0   # seconds between repeated alerts of same type


class Notifier:
    def __init__(self):
        self._client    = httpx.AsyncClient(timeout=8.0)
        self._last_sent: dict[str, float] = {}
        self._enabled   = NTFY_TOPIC != "bob-robot-changeme"

        if not self._enabled:
            log.warning(
                "Notifier: set BOB_NTFY_TOPIC in .env — "
                "e.g. BOB_NTFY_TOPIC=bob-robot-abc123\n"
                "Install ntfy app on your phone and subscribe to that topic."
            )
        else:
            log.info("Notifier: ntfy.sh topic = %s/%s", NTFY_SERVER, NTFY_TOPIC)

    # ──────────────────────────────────────────
    # Public alert methods
    # ──────────────────────────────────────────

    async def motion_alert(self, snapshot_bytes: bytes, area: float):
        """Send motion detected alert with snapshot attached."""
        await self._push(
            title    = "🚨 BOB: Motion Detected!",
            message  = f"Movement spotted — area {area:.0f}px²\n{time.strftime('%H:%M:%S')}",
            priority = "high",
            tags     = ["rotating_light", "camera"],
            attach   = snapshot_bytes,
            filename = f"motion_{int(time.time())}.jpg",
            key      = "motion",
        )

    async def obstacle_alert(self, distance_cm: float):
        """Alert when BOB is blocked."""
        await self._push(
            title    = "⚠️ BOB: Obstacle!",
            message  = f"Object {distance_cm:.0f}cm ahead — BOB stopped",
            priority = "default",
            tags     = ["warning"],
            key      = "obstacle",
        )

    async def online_alert(self, dashboard_url: str = ""):
        """Notify that BOB has booted and is ready."""
        msg = "BOB is online and watching! 🤖"
        if dashboard_url:
            msg += f"\nDashboard: {dashboard_url}"
        await self._push(
            title    = "✅ BOB is Online",
            message  = msg,
            priority = "low",
            tags     = ["robot", "white_check_mark"],
            key      = "online",
            cooldown = 30.0,
        )

    async def offline_alert(self):
        await self._push(
            title    = "😴 BOB is Offline",
            message  = "BOB has shut down.",
            priority = "low",
            tags     = ["zzz"],
            key      = "offline",
            cooldown = 30.0,
        )

    async def custom(self, title: str, message: str,
                     priority: str = "default", tags: list = None):
        """Send any custom notification."""
        await self._push(title=title, message=message,
                         priority=priority, tags=tags or [], key="custom")

    # ──────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────

    async def _push(self, title: str, message: str, priority: str = "default",
                    tags: list = None, attach: Optional[bytes] = None,
                    filename: str = "attach.jpg", key: str = "default",
                    cooldown: float = COOLDOWN):

        if not self._enabled:
            log.debug("Notifier disabled — would send: %s | %s", title, message)
            return

        # Cooldown per key
        now = time.monotonic()
        if now - self._last_sent.get(key, 0) < cooldown:
            return
        self._last_sent[key] = now

        url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
        headers = {
            "Title":    title,
            "Priority": priority,
            "Tags":     ",".join(tags or []),
        }

        try:
            if attach:
                # Send image as attachment
                headers["Filename"] = filename
                await self._client.post(url, content=attach, headers=headers)
            else:
                await self._client.post(url, content=message.encode(), headers=headers)
            log.info("ntfy sent: %s", title)
        except Exception as e:
            log.warning("ntfy error: %s", e)

    async def close(self):
        await self._client.aclose()


# ── Cloudflare Tunnel helper ──────────────────────────────────────────────────

async def start_cloudflare_tunnel(port: int = 8000) -> str:
    """
    Starts a Cloudflare Quick Tunnel (cloudflared) in background.
    Returns the public HTTPS URL.
    No account needed for quick tunnels.
    Install: curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg
             echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
             sudo apt install cloudflared
    """
    import asyncio
    import re

    log.info("Starting Cloudflare Quick Tunnel on port %d…", port)
    try:
        proc = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://localhost:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Read stderr for the tunnel URL (cloudflared logs it there)
        url = ""
        for _ in range(60):   # wait up to 30 seconds
            line = await asyncio.wait_for(proc.stderr.readline(), timeout=1.0)
            text = line.decode(errors="ignore")
            m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", text)
            if m:
                url = m.group(0)
                log.info("Cloudflare Tunnel URL: %s", url)
                # Save to log file
                Path("/home/arduino/bob/logs/tunnel.log").write_text(
                    f"{url}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
                return url
        return ""
    except FileNotFoundError:
        log.warning("cloudflared not installed — no public tunnel")
        log.warning("Install: sudo apt install cloudflared")
        return ""
    except Exception as e:
        log.warning("Cloudflare tunnel error: %s", e)
        return ""
