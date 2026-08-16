"""
tof_sensor.py — BOB Robot VL53L5CX 8×8 Time-of-Flight Sensor
==============================================================
Sensor  : VL53L5CX (8×8 multi-zone ToF, ST Microelectronics)
Library : vl53l5cx-ctypes  (pip install vl53l5cx-ctypes)
Bus     : I2C-1 (/dev/i2c-1)
Platform: Debian Linux arm64 (Arduino UNO Q)

The sensor returns a 64-element list of distances in millimetres.
This module normalises them to centimetres and yields them via an
async generator at approximately 10 Hz.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator, List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────── Constants ────────────────────────────────────────
I2C_BUS        = 1          # /dev/i2c-1
RANGING_FREQ   = 15         # Hz — sensor ranging rate (max 15 Hz for 8×8)
YIELD_FREQ     = 10         # Hz — generator output rate
YIELD_INTERVAL = 1.0 / YIELD_FREQ
GRID_SIZE      = 64         # 8×8 = 64 zones
ZERO_GRID: List[float] = [0.0] * GRID_SIZE

# ──────────────────────────── Optional library import ──────────────────────────
try:
    import vl53l5cx_ctypes as vl53l5cx
    _HAS_VL53 = True
    logger.debug("vl53l5cx_ctypes imported successfully.")
except ImportError:
    vl53l5cx = None  # type: ignore
    _HAS_VL53 = False
    logger.warning(
        "vl53l5cx_ctypes is not installed — ToF sensor unavailable. "
        "Install with: pip install vl53l5cx-ctypes"
    )


# ═══════════════════════════════════════════════════════════════════════════════
class ToFSensor:
    """
    Async wrapper around the VL53L5CX 8×8 ToF sensor.

    Usage::

        tof = ToFSensor()
        ok = await tof.start()
        if ok:
            async for grid in tof.stream():
                process(grid)   # list of 64 floats in cm
    """

    def __init__(self) -> None:
        self._sensor = None
        self._available = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tof")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._warned_unavailable = False

    # ─────────────────────────── Lifecycle ─────────────────────────────────────

    async def start(self) -> bool:
        """
        Initialise the VL53L5CX sensor.

        Returns ``True`` when the sensor is ready, ``False`` otherwise.
        Hardware errors and missing libraries are handled gracefully.
        """
        self._loop = asyncio.get_running_loop()

        if not _HAS_VL53:
            logger.warning(
                "ToFSensor.start(): vl53l5cx_ctypes not available — "
                "sensor will produce zero data."
            )
            self._available = False
            return False

        logger.info("Initialising VL53L5CX on I2C bus %d …", I2C_BUS)
        try:
            ok = await self._loop.run_in_executor(
                self._executor, self._blocking_init
            )
            self._available = ok
            if ok:
                logger.info("VL53L5CX sensor ready (8×8 @ %d Hz).", RANGING_FREQ)
            return ok
        except Exception as exc:
            logger.error(
                "Unexpected error initialising VL53L5CX: %s", exc, exc_info=True
            )
            self._available = False
            return False

    def _blocking_init(self) -> bool:
        """Blocking sensor initialisation — runs in executor thread."""
        try:
            sensor = vl53l5cx.VL53L5CX(i2c_bus=I2C_BUS)
            sensor.init()
            sensor.set_ranging_frequency_hz(RANGING_FREQ)
            sensor.set_resolution(vl53l5cx.RESOLUTION_8X8)
            sensor.start_ranging()
            self._sensor = sensor
            return True
        except OSError as exc:
            logger.error(
                "I2C error initialising VL53L5CX (bus=%d): %s — "
                "check wiring and that /dev/i2c-%d is accessible.",
                I2C_BUS, exc, I2C_BUS, exc_info=True,
            )
            return False
        except Exception as exc:
            logger.error(
                "Failed to initialise VL53L5CX: %s", exc, exc_info=True
            )
            return False

    async def stop(self) -> None:
        """Stop ranging and release resources."""
        logger.info("Stopping ToFSensor …")
        if self._sensor is not None:
            try:
                await (self._loop or asyncio.get_running_loop()).run_in_executor(
                    self._executor, self._sensor.stop_ranging
                )
                logger.info("VL53L5CX ranging stopped.")
            except Exception as exc:
                logger.warning("Error stopping VL53L5CX: %s", exc)
        self._executor.shutdown(wait=False)
        logger.info("ToFSensor stopped.")

    # ─────────────────────────── Async generator ───────────────────────────────

    async def stream(self) -> AsyncGenerator[List[float], None]:
        """
        Async generator that yields an 8×8 distance grid (64 floats, cm) at
        approximately ``YIELD_FREQ`` Hz.

        If the sensor is unavailable, yields a zero grid and logs a single
        warning, then continues yielding zeros so callers don't need to special-
        case the unavailable state.
        """
        loop = self._loop or asyncio.get_running_loop()

        while True:
            t_start = loop.time()

            if not self._available:
                if not self._warned_unavailable:
                    logger.warning(
                        "ToFSensor.stream(): sensor not available — "
                        "yielding zero grid. This warning will not repeat."
                    )
                    self._warned_unavailable = True
                yield list(ZERO_GRID)
            else:
                try:
                    grid_cm = await loop.run_in_executor(
                        self._executor, self._blocking_read
                    )
                    yield grid_cm
                except asyncio.CancelledError:
                    logger.info("ToFSensor.stream() cancelled.")
                    return
                except Exception as exc:
                    logger.error(
                        "Error reading VL53L5CX: %s — yielding zero grid.", exc,
                        exc_info=True,
                    )
                    yield list(ZERO_GRID)

            # Throttle to YIELD_FREQ
            elapsed = loop.time() - t_start
            sleep_time = YIELD_INTERVAL - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    # ─────────────────────────── Helpers (blocking) ────────────────────────────

    def _blocking_read(self) -> List[float]:
        """
        Wait for new sensor data and return a 64-element list of distances in
        centimetres. Polls the sensor's data-ready flag with a short busy-wait.
        """
        # Poll until new data ready (sensor produces ~15 frames/s, so max ~70 ms)
        deadline = time.monotonic() + 0.5  # 500 ms timeout
        while not self._sensor.data_ready():
            if time.monotonic() > deadline:
                logger.warning("VL53L5CX data_ready() timeout — returning zero grid.")
                return list(ZERO_GRID)
            time.sleep(0.005)  # 5 ms poll interval

        data = self._sensor.get_ranging_data()

        # distance_mm is a list/array of 64 values (may contain 0 for invalid zones)
        mm_values = data.distance_mm
        cm_values: List[float] = []
        for mm in mm_values:
            cm = float(mm) / 10.0 if mm and mm > 0 else 0.0
            cm_values.append(cm)

        # Pad or truncate to exactly 64 elements
        if len(cm_values) < GRID_SIZE:
            cm_values.extend([0.0] * (GRID_SIZE - len(cm_values)))
        elif len(cm_values) > GRID_SIZE:
            cm_values = cm_values[:GRID_SIZE]

        logger.debug(
            "ToF read: min=%.1f cm, max=%.1f cm",
            min(v for v in cm_values if v > 0, default=0.0),
            max(cm_values),
        )
        return cm_values

    # ─────────────────────────── Convenience ───────────────────────────────────

    def grid_to_matrix(self, grid: List[float]) -> List[List[float]]:
        """Reshape flat 64-element grid to 8×8 nested list."""
        return [grid[i * 8 : (i + 1) * 8] for i in range(8)]

    def min_distance_cm(self, grid: List[float]) -> float:
        """Return the minimum non-zero distance in the grid (cm)."""
        nonzero = [v for v in grid if v > 0.0]
        return min(nonzero) if nonzero else 0.0

    def center_distance_cm(self, grid: List[float]) -> float:
        """
        Return the average distance of the four central zones (indices 27, 28,
        35, 36 in row-major order) — useful for forward obstacle detection.
        """
        center_indices = [27, 28, 35, 36]
        values = [grid[i] for i in center_indices if grid[i] > 0.0]
        return sum(values) / len(values) if values else 0.0


# ──────────────────────────── Quick self-test ──────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def _test() -> None:
        tof = ToFSensor()
        ok = await tof.start()
        print(f"Sensor available: {ok}")

        count = 0
        async for grid in tof.stream():
            matrix = tof.grid_to_matrix(grid)
            nearest = tof.min_distance_cm(grid)
            center  = tof.center_distance_cm(grid)
            print(f"[{count:04d}] nearest={nearest:.1f} cm  center={center:.1f} cm")
            count += 1
            if count >= 20:
                break

        await tof.stop()

    asyncio.run(_test())
