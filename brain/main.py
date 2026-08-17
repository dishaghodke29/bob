"""
BOB Brain — Main entry point
Starts all subsystems and runs them concurrently.

Usage (on UNO Q):
  source /home/arduino/bob/venv/bin/activate
  python3 /home/arduino/bob/brain/main.py

NOTE: llama-server must already be running (started by start_bob.sh).
"""

import asyncio
import logging
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.serial_bridge import SerialBridge
from brain.llm_agent     import LLMAgent
from brain.voice         import VoicePipeline
from brain.tof_sensor    import ToFSensor
from brain.web_server    import WebServer
from brain.bob_brain     import BobBrain

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-14s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/arduino/bob/logs/brain.log"),
    ],
)
log = logging.getLogger("main")


async def main():
    log.info("=" * 50)
    log.info("  BOB Brain Starting Up")
    log.info("=" * 50)

    # ── Instantiate all subsystems ────────────────────────────────────────────
    telemetry_queue = asyncio.Queue(maxsize=10)

    serial  = SerialBridge(telemetry_queue)
    llm     = LLMAgent()
    voice   = VoicePipeline()
    tof     = ToFSensor()
    web     = WebServer()

    brain = BobBrain(
        serial_bridge  = serial,
        llm_agent      = llm,
        voice          = voice,
        tof_sensor     = tof,
        ws_broadcaster = web.broadcast,
    )
    web.set_brain(brain)

    # ── Start LLM (connect to already-running llama-server) ───────────────────
    log.info("Connecting to llama-server…")
    llm_ok = await llm.start()
    if not llm_ok:
        log.warning("LLM not ready — BOB will respond with fallback messages until it is")

    # ── Start voice pipeline ──────────────────────────────────────────────────
    log.info("Starting voice pipeline…")
    await voice.start()

    # ── Start ToF sensor ──────────────────────────────────────────────────────
    log.info("Starting ToF sensor…")
    tof_ok = await tof.start()
    if not tof_ok:
        log.warning("VL53L5CX not available — running without depth sensor")

    log.info("All systems initialised — BOB is running!")

    # ── Background consumers ──────────────────────────────────────────────────

    async def telemetry_consumer():
        """Drain MCU telemetry from queue and update brain."""
        while True:
            try:
                data = await asyncio.wait_for(telemetry_queue.get(), timeout=1.0)
                brain.update_telemetry(data)
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                log.error("Telemetry consumer error: %s", exc)

    async def tof_consumer():
        """Stream depth frames from ToF sensor into brain."""
        async for depth_map in tof.stream():
            try:
                brain.update_tof(depth_map)
            except Exception as exc:
                log.error("ToF consumer error: %s", exc)

    async def serial_graceful():
        """Run serial bridge — don't crash everything if MCU is not connected."""
        try:
            await serial.start()
        except Exception as exc:
            log.warning("Serial bridge exited: %s (MCU may not be connected)", exc)

    # ── Run everything concurrently ───────────────────────────────────────────
    tasks = [
        asyncio.create_task(serial_graceful(),                  name="serial"),
        asyncio.create_task(brain.run(),                        name="brain"),
        asyncio.create_task(web.start(),                        name="web"),
        asyncio.create_task(telemetry_consumer(),               name="telemetry"),
        asyncio.create_task(voice.listen_loop(brain.handle_voice_input), name="listen"),
    ]
    if tof_ok:
        tasks.append(asyncio.create_task(tof_consumer(), name="tof"))

    try:
        # Run forever — if ANY critical task dies, log it but keep the rest going
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            if t.exception():
                log.error("Task '%s' raised: %s", t.get_name(), t.exception())
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutdown signal received…")
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
