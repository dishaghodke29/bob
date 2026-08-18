"""
BOB Brain — Main entry point
Starts all subsystems and runs them concurrently.

Usage (on UNO Q):
  source /home/arduino/bob/venv/bin/activate
  python3 /home/arduino/bob/brain/main.py

NOTE: llama-server must already be running (started by start_bob.sh).
NOTE: Web server is disabled — saves ~15% CPU. Re-enable if needed.
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.serial_bridge import SerialBridge
from brain.llm_agent     import LLMAgent
from brain.voice         import VoicePipeline
from brain.tof_sensor    import ToFSensor
from brain.bob_brain     import BobBrain

# ── Logging — single handler only, no duplicate lines ────────────────────────
log_handlers = [
    logging.StreamHandler(),
    logging.FileHandler("/home/arduino/bob/logs/brain.log", mode="w"),  # overwrite each run
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-14s] %(levelname)s: %(message)s",
    handlers=log_handlers,
    force=True,   # removes any existing handlers (prevents duplicates)
)
# Silence noisy libs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

log = logging.getLogger("main")

ENABLE_WEB_SERVER = False   # Disabled — saves ~200MB RAM + 15% CPU


async def main():
    log.info("=" * 50)
    log.info("  BOB Brain Starting Up")
    log.info("=" * 50)

    telemetry_queue = asyncio.Queue(maxsize=10)

    serial = SerialBridge(telemetry_queue)
    llm    = LLMAgent()
    voice  = VoicePipeline()
    tof    = ToFSensor()

    # Dummy broadcaster if web server is off
    async def noop_broadcast(msg: dict) -> None:
        pass

    brain = BobBrain(
        serial_bridge  = serial,
        llm_agent      = llm,
        voice          = voice,
        tof_sensor     = tof,
        ws_broadcaster = noop_broadcast,
    )

    # ── Start LLM ─────────────────────────────────────────────────────────────
    log.info("Connecting to llama-server…")
    llm_ok = await llm.start()
    if not llm_ok:
        log.warning("LLM not ready yet — will retry on first voice input")

    # ── Start voice pipeline ──────────────────────────────────────────────────
    log.info("Starting voice pipeline…")
    await voice.start()

    # ── Start ToF (optional) ──────────────────────────────────────────────────
    tof_ok = await tof.start()
    if not tof_ok:
        log.warning("ToF sensor not available — running without depth sensor")

    log.info("All systems ready — say 'Hey BOB' to start talking!")

    # ── Background tasks ──────────────────────────────────────────────────────

    async def telemetry_consumer():
        while True:
            try:
                data = await asyncio.wait_for(telemetry_queue.get(), timeout=1.0)
                brain.update_telemetry(data)
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                log.error("Telemetry error: %s", exc)

    async def tof_consumer():
        async for depth_map in tof.stream():
            try:
                brain.update_tof(depth_map)
            except Exception as exc:
                log.error("ToF consumer error: %s", exc)

    async def serial_task():
        """Serial bridge — won't crash if MCU not connected."""
        try:
            await serial.start()
        except Exception as exc:
            log.warning("Serial bridge stopped: %s (MCU may not be connected)", exc)

    # ── Gather all tasks ──────────────────────────────────────────────────────
    tasks = [
        asyncio.create_task(serial_task(),                                  name="serial"),
        asyncio.create_task(brain.run(),                                    name="brain"),
        asyncio.create_task(telemetry_consumer(),                           name="telemetry"),
        asyncio.create_task(voice.listen_loop(brain.handle_voice_input),    name="listen"),
    ]
    if tof_ok:
        tasks.append(asyncio.create_task(tof_consumer(), name="tof"))

    if ENABLE_WEB_SERVER:
        from brain.web_server import WebServer
        web = WebServer()
        web.set_brain(brain)
        tasks.append(asyncio.create_task(web.start(), name="web"))
        log.info("Web dashboard: http://192.168.1.20:8000")

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            if t.exception():
                log.error("Task '%s' crashed: %s", t.get_name(), t.exception())
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutdown signal…")
    finally:
        log.info("Shutting down BOB…")
        for t in tasks:
            t.cancel()
        try:
            await serial.send_stop()
        except Exception:
            pass
        await llm.stop()
        await voice.stop()
        log.info("BOB shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
