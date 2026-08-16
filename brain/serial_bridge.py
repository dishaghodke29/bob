"""
BOB Brain — Serial Bridge
Async bidirectional communication between Debian Linux and the MCU
via /dev/ttyHS1 at 115200 baud.

Publishes: telemetry dict to asyncio Queue (consumed by bob_brain.py)
Receives:  command dicts from bob_brain.py and writes JSON lines to serial
"""

import asyncio
import json
import logging
import serial
import serial.serialutil
from typing import Optional

log = logging.getLogger("serial_bridge")

SERIAL_PORT  = "/dev/ttyHS1"
BAUD_RATE    = 115200
READ_TIMEOUT = 0.01   # seconds — non-blocking read interval


class SerialBridge:
    def __init__(
        self,
        telemetry_queue: asyncio.Queue,
        port: str = SERIAL_PORT,
        baud: int = BAUD_RATE,
    ):
        self._port   = port
        self._baud   = baud
        self._tq     = telemetry_queue
        self._ser: Optional[serial.Serial] = None
        self._running = False
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    async def send_command(self, cmd: dict):
        """Queue a command dict to be written to the MCU."""
        try:
            self._send_queue.put_nowait(cmd)
        except asyncio.QueueFull:
            log.warning("Send queue full — dropping command: %s", cmd)

    async def send_move(self, vy: int, vx: int, omega: int):
        await self.send_command({"cmd": "move", "vy": vy, "vx": vx, "omega": omega})

    async def send_stop(self):
        await self.send_command({"cmd": "stop"})

    async def send_estop(self):
        await self.send_command({"cmd": "estop"})

    async def send_ping(self):
        await self.send_command({"cmd": "ping"})

    async def send_calibrate(self):
        await self.send_command({"cmd": "calibrate"})

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    async def start(self):
        self._loop    = asyncio.get_event_loop()
        self._running = True
        await asyncio.gather(
            self._reader_task(),
            self._writer_task(),
        )

    async def stop(self):
        self._running = False
        await self.send_stop()
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ──────────────────────────────────────────
    # Internal tasks (run in executor to avoid blocking event loop)
    # ──────────────────────────────────────────

    def _open_serial(self) -> bool:
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baud,
                timeout=READ_TIMEOUT,
            )
            log.info("Serial opened: %s @ %d baud", self._port, self._baud)
            return True
        except serial.serialutil.SerialException as e:
            log.error("Cannot open serial port %s: %s", self._port, e)
            return False

    async def _reader_task(self):
        """Read telemetry lines from MCU, parse JSON, push to telemetry_queue."""
        loop = asyncio.get_event_loop()

        while self._running:
            # Connect / reconnect
            if not self._ser or not self._ser.is_open:
                ok = await loop.run_in_executor(None, self._open_serial)
                if not ok:
                    await asyncio.sleep(2.0)
                    continue

            try:
                raw = await loop.run_in_executor(None, self._ser.readline)
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line.startswith("{"):
                    continue
                data = json.loads(line)
                # Non-blocking put — drop oldest if full
                if self._tq.full():
                    try:
                        self._tq.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await self._tq.put(data)

            except json.JSONDecodeError:
                pass  # Corrupt line — skip
            except (serial.serialutil.SerialException, OSError) as e:
                log.warning("Serial read error: %s — reconnecting", e)
                if self._ser:
                    self._ser.close()
                await asyncio.sleep(1.0)

    async def _writer_task(self):
        """Write queued commands to MCU as JSON lines."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                cmd = await asyncio.wait_for(self._send_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            if not self._ser or not self._ser.is_open:
                await asyncio.sleep(0.05)
                continue

            line = json.dumps(cmd, separators=(",", ":")) + "\n"
            try:
                await loop.run_in_executor(None, self._ser.write, line.encode())
            except (serial.serialutil.SerialException, OSError) as e:
                log.warning("Serial write error: %s", e)
