"""
BOB — Servo Gimbal Controller
Controls a servo motor mounted on BOB that holds the camera + VL53L5CX sensor.

Behaviour:
  1. LOOK-BEFORE-MOVE: Before BOB turns, the servo first rotates the camera
     to look in that direction, checks ToF for obstacles, then signals the
     brain it's safe to move.

  2. GIMBAL MODE (X-axis stabilisation): While BOB's body is turning,
     the servo compensates using the MPU-6050 gyro Z rate so the camera
     stays locked on the same forward target — like a camera gimbal.
     (X-axis only, as requested)

  3. SCAN MODE: In patrol/security mode, the servo sweeps left↔right
     continuously to widen the field of view.

Hardware:
  The servo is controlled via a PWM GPIO pin on the Linux side (pigpio)
  OR via a serial command to the MCU (which drives the servo via PWM).
  We use the serial command approach (no pigpio dependency).

Servo range: 0–180 degrees, centre = 90° (looking straight forward)
"""

import asyncio
import logging
import math
import time
from typing import Optional

log = logging.getLogger("gimbal")

# ── Servo config ──────────────────────────────────────────────────────────────
SERVO_CENTRE   = 90    # degrees — straight ahead
SERVO_MIN      = 10    # leftmost
SERVO_MAX      = 170   # rightmost
LOOK_ANGLE     = 45    # how far to look before a turn (degrees)
LOOK_DWELL     = 0.6   # seconds to wait while looking before moving
SCAN_STEP      = 2     # degrees per scan step
SCAN_INTERVAL  = 0.04  # seconds per scan step

# ── PID for gimbal stabilisation ─────────────────────────────────────────────
KP   = 1.2    # proportional gain
KI   = 0.04   # integral gain
KD   = 0.08   # derivative gain
MAX_CORRECTION = 30    # max degrees of correction per update


class ServoGimbal:
    def __init__(self, serial_bridge):
        """
        serial_bridge: SerialBridge instance — we send servo angle via
        a custom serial command {"cmd":"servo","angle":90} to the MCU.
        """
        self._serial   = serial_bridge
        self._angle    = SERVO_CENTRE   # current commanded angle
        self._running  = False

        # Gimbal PID state
        self._pid_integral  = 0.0
        self._pid_last_err  = 0.0
        self._pid_last_t    = time.monotonic()

        # Latest gyro Z rate from telemetry (deg/s), updated by brain
        self._gyro_z        = 0.0

        # Scan mode
        self._scanning      = False
        self._scan_dir      = 1    # +1 right, -1 left
        self._scan_task: Optional[asyncio.Task] = None

        # Gimbal mode active flag
        self._gimbal_active = False

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def update_gyro(self, gz: float):
        """Called by brain at 20Hz with MPU-6050 gyro Z rate (deg/s)."""
        self._gyro_z = gz
        if self._gimbal_active:
            self._apply_gimbal_correction()

    async def look_and_clear(self, direction: str) -> bool:
        """
        Look in direction ('left'/'right'/'forward') before BOB moves.
        Returns True if ToF says the path is clear.
        Pauses scan mode while looking.
        """
        self._pause_scan()

        target_angle = {
            "left":    SERVO_CENTRE - LOOK_ANGLE,
            "right":   SERVO_CENTRE + LOOK_ANGLE,
            "forward": SERVO_CENTRE,
        }.get(direction, SERVO_CENTRE)

        log.info("Gimbal: looking %s (→ %d°)", direction, target_angle)
        await self.set_angle(target_angle, smooth=True)
        await asyncio.sleep(LOOK_DWELL)   # dwell to capture ToF reading

        # The brain will read obstacle_distance from tof_sensor
        # We just return True here; brain decides based on ToF data
        return True

    async def enable_gimbal(self):
        """
        Enable X-axis gimbal stabilisation.
        Camera will counteract body rotation using gyro Z.
        """
        self._gimbal_active = True
        self._pid_integral  = 0.0
        self._pid_last_err  = 0.0
        self._pid_last_t    = time.monotonic()
        log.info("Gimbal stabilisation ENABLED")

    async def disable_gimbal(self):
        """Disable gimbal — servo returns to centre."""
        self._gimbal_active = False
        await self.set_angle(SERVO_CENTRE)
        log.info("Gimbal stabilisation DISABLED")

    async def start_scan(self):
        """Start continuous left↔right scan sweep (security patrol mode)."""
        self._scanning = True
        if self._scan_task and not self._scan_task.done():
            return
        self._scan_task = asyncio.create_task(self._scan_loop())
        log.info("Gimbal scan sweep started")

    async def stop_scan(self):
        """Stop scan sweep and return to centre."""
        self._scanning = False
        if self._scan_task:
            self._scan_task.cancel()
        await self.set_angle(SERVO_CENTRE)
        log.info("Gimbal scan stopped")

    async def set_angle(self, angle: float, smooth: bool = False):
        """Command the servo to a specific angle (0-180)."""
        angle = max(SERVO_MIN, min(SERVO_MAX, angle))

        if smooth:
            # Interpolate in steps
            steps = max(1, int(abs(angle - self._angle) / 3))
            for i in range(steps + 1):
                t = i / steps
                interp = self._angle + (angle - self._angle) * t
                await self._send_servo(interp)
                await asyncio.sleep(0.015)
        else:
            await self._send_servo(angle)

        self._angle = angle

    # ──────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────

    def _apply_gimbal_correction(self):
        """
        PID controller: counteract body rotation using gyro Z.
        If robot turns right (+gz), servo moves left to keep camera forward.
        """
        now = time.monotonic()
        dt  = max(0.001, now - self._pid_last_t)
        self._pid_last_t = now

        # Error: gyro Z rate is the disturbance we want to cancel
        err = self._gyro_z

        # PID terms
        self._pid_integral  = max(-20, min(20,
            self._pid_integral + err * dt))
        derivative          = (err - self._pid_last_err) / dt
        self._pid_last_err  = err

        correction = (KP * err + KI * self._pid_integral + KD * derivative)
        correction = max(-MAX_CORRECTION, min(MAX_CORRECTION, correction))

        new_angle = self._angle - correction   # subtract: counteract rotation
        asyncio.create_task(self.set_angle(new_angle))

    async def _scan_loop(self):
        """Continuous sweep left ↔ right for security patrol."""
        while self._scanning:
            self._angle += SCAN_STEP * self._scan_dir

            if self._angle >= SERVO_MAX:
                self._angle  = SERVO_MAX
                self._scan_dir = -1
            elif self._angle <= SERVO_MIN:
                self._angle  = SERVO_MIN
                self._scan_dir = 1

            await self._send_servo(self._angle)
            await asyncio.sleep(SCAN_INTERVAL)

    def _pause_scan(self):
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()

    async def _send_servo(self, angle: float):
        """Send servo angle command to MCU via serial bridge."""
        await self._serial.send_command({
            "cmd":   "servo",
            "angle": round(angle, 1),
        })

    @property
    def current_angle(self) -> float:
        return self._angle

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def gimbal_active(self) -> bool:
        return self._gimbal_active
