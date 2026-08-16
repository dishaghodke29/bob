"""
BOB Brain — Main entry point
Starts all subsystems and runs them concurrently.

Usage (on UNO Q):
  source /home/arduino/bob/venv/bin/activate
  python3 /home/arduino/bob/brain/main.py
"""

import asyncio
import logging
import sys
import os

# Ensure project is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.serial_bridge import SerialBridge
from brain.llm_agent     import LLMAgent
from brain.voice         import VoicePipeline
from brain.tof_sensor    import ToFSensor
from brain.web_server    import WebServer
from brain.bob_brain     import BobBrain

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

    # Shared queues
    telemetry_queue = asyncio.Queue(maxsize=10)

    # Instantiate subsystems
    serial  = SerialBridge(telemetry_queue)
    llm     = LLMAgent()
    voice   = VoicePipeline()
    tof     = ToFSensor()
    web     = WebServer()

    # Brain ties everything together
    brain = BobBrain(
        serial_bridge  = serial,
        llm_agent      = llm,
        voice          = voice,
        tof_sensor     = tof,
        ws_broadcaster = web.broadcast,
    )

    # Wire web server to brain
    web.set_brain(brain)

    # ── Start all services ──────────────────────────────────────────────────
    log.info("Starting LLM server (llama-server)...")
    llm_ok = await llm.start()
    if not llm_ok:
        log.error("LLM failed to start — continuing without AI")

    log.info("Starting voice pipeline...")
    await voice.start()

    log.info("Starting ToF sensor...")
    tof_ok = await tof.start()
    if not tof_ok:
        log.warning("VL53L5CX not available — continuing without depth sensor")

    # ── Telemetry consumer ──────────────────────────────────────────────────
    async def telemetry_consumer():
        while True:
            data = await telemetry_queue.get()
            brain.update_telemetry(data)

    # ── ToF consumer ────────────────────────────────────────────────────────
    async def tof_consumer():
        async for depth_map in tof.stream():
            brain.update_tof(depth_map)

    # ── Run all concurrently ─────────────────────────────────────────────────
    log.info("All systems go! Running BOB...")
    try:
        await asyncio.gather(
            serial.start(),
            brain.run(),
            web.start(),
            telemetry_consumer(),
            tof_consumer() if tof_ok else asyncio.sleep(0),
            voice.listen_loop(brain.handle_voice_input),
        )
    except KeyboardInterrupt:
        log.info("Shutting down BOB...")
    finally:
        await serial.send_stop()
        await llm.stop()
        await voice.stop()
        log.info("BOB shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
