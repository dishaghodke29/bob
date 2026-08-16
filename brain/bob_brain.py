"""
BOB Brain — Main orchestrator & state machine
Coordinates: serial bridge (MCU), VL53L5CX ToF, LLM agent,
voice pipeline, display socket, and web server.
"""

import asyncio
import json
import logging
import os
import socket
import time
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("bob_brain")

DISPLAY_SOCKET = "/tmp/bob_display.sock"

# ── Robot states ─────────────────────────────────────────────────────────────
class State(Enum):
    IDLE       = auto()
    NAVIGATING = auto()
    LISTENING  = auto()
    THINKING   = auto()
    SPEAKING   = auto()
    ESTOP      = auto()
    GAME       = auto()


class BobBrain:
    def __init__(self, serial_bridge, llm_agent, voice, tof_sensor, ws_broadcaster):
        self._serial  = serial_bridge
        self._llm     = llm_agent
        self._voice   = voice
        self._tof     = tof_sensor
        self._ws      = ws_broadcaster       # For web dashboard

        self._state        = State.IDLE
        self._telemetry    = {}              # Latest MCU telemetry
        self._tof_data     = {}              # Latest ToF depth map
        self._running      = False

        # Manual drive from web dashboard
        self._manual_vy    = 0
        self._manual_vx    = 0
        self._manual_omega = 0
        self._manual_mode  = False           # True = web joystick controls

        # Display socket connection
        self._display_sock: Optional[socket.socket] = None

        # Obstacle state
        self._obstacle_detected = False
        self._obstacle_distance = 999.0

    # ──────────────────────────────────────────
    # Public API (called by web server / voice)
    # ──────────────────────────────────────────

    async def handle_voice_input(self, text: str):
        """Process transcribed speech from the voice pipeline."""
        log.info("Voice input: %s", text)
        self._set_state(State.THINKING)
        self._send_display({"type": "emotion", "name": "thinking"})
        self._send_display({"type": "subtitle", "text": f'"{text}"', "duration": 3.0})

        # Build sensor context for LLM
        context = {
            "state":       self._state.name,
            "obstacle_cm": round(self._obstacle_distance, 1),
            "roll":        round(self._telemetry.get("roll",  0), 1),
            "pitch":       round(self._telemetry.get("pitch", 0), 1),
        }

        response = await self._llm.chat(text, context=context)
        log.info("LLM response: %s", response)

        self._set_state(State.SPEAKING)
        self._send_display({"type": "emotion", "name": "speaking"})
        self._send_display({"type": "subtitle", "text": response, "duration": 6.0})

        await self._voice.speak(response)

        self._set_state(State.IDLE)
        self._send_display({"type": "emotion", "name": "idle"})

    async def handle_web_command(self, cmd: dict):
        """Handle commands from the web dashboard."""
        action = cmd.get("action")

        if action == "move":
            self._manual_mode  = True
            self._manual_vy    = int(cmd.get("vy",    0))
            self._manual_vx    = int(cmd.get("vx",    0))
            self._manual_omega = int(cmd.get("omega", 0))

        elif action == "stop":
            self._manual_vy = self._manual_vx = self._manual_omega = 0
            await self._serial.send_stop()

        elif action == "auto":
            self._manual_mode = False

        elif action == "chat":
            text = cmd.get("text", "")
            if text:
                asyncio.create_task(self.handle_voice_input(text))

        elif action == "emotion":
            self._send_display({"type": "emotion", "name": cmd.get("name", "idle")})

        elif action == "estop":
            await self._serial.send_estop()
            self._set_state(State.ESTOP)
            self._send_display({"type": "emotion", "name": "alert"})

    def update_telemetry(self, data: dict):
        """Called by serial bridge when MCU sends telemetry."""
        self._telemetry = data
        # Broadcast to web dashboard
        asyncio.create_task(self._ws({
            "type": "telemetry",
            "data": data,
        }))

    def update_tof(self, depth_map: list):
        """Called by ToF sensor task with 8×8 distance grid."""
        self._tof_data = {"grid": depth_map}
        # Find minimum distance in central 4×4 zone (front-facing)
        min_dist = 999.0
        for r in range(2, 6):
            for c in range(2, 6):
                v = depth_map[r * 8 + c]
                if 0 < v < min_dist:
                    min_dist = v
        self._obstacle_distance = min_dist
        self._obstacle_detected = min_dist < 30.0   # <30cm = obstacle

        # Broadcast ToF to web dashboard
        asyncio.create_task(self._ws({
            "type": "tof",
            "grid": depth_map,
            "min_cm": round(min_dist, 1),
        }))

    # ──────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────

    async def run(self):
        self._running = True
        self._connect_display()
        log.info("BOB Brain running. State: %s", self._state.name)

        while self._running:
            await self._tick()
            await asyncio.sleep(0.05)   # 20Hz brain loop

    async def _tick(self):
        """Main decision loop — runs at 20Hz."""

        # ── E-stop recovery ──
        estop_hw = self._telemetry.get("estop", False)
        if estop_hw and self._state != State.ESTOP:
            self._set_state(State.ESTOP)
            self._send_display({"type": "emotion", "name": "alert"})
        elif not estop_hw and self._state == State.ESTOP:
            self._set_state(State.IDLE)
            self._send_display({"type": "emotion", "name": "idle"})

        # ── Drive logic ──
        if self._state == State.ESTOP:
            await self._serial.send_estop()
            return

        if self._manual_mode:
            # Web joystick control
            if self._obstacle_detected and self._manual_vy > 0:
                # Block forward movement into obstacle
                await self._serial.send_move(0, self._manual_vx, self._manual_omega)
                self._send_display({"type": "emotion", "name": "alert"})
            else:
                await self._serial.send_move(
                    self._manual_vy, self._manual_vx, self._manual_omega)
                if self._state != State.SPEAKING and self._state != State.THINKING:
                    self._send_display({"type": "emotion", "name": "idle"})
        else:
            # Autonomous: stop if obstacle detected
            if self._obstacle_detected:
                await self._serial.send_stop()
                if self._state == State.NAVIGATING:
                    self._set_state(State.IDLE)
                    self._send_display({"type": "emotion", "name": "alert"})
            elif self._state == State.IDLE:
                await self._serial.send_stop()

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    def _set_state(self, state: State):
        if state != self._state:
            log.info("State: %s → %s", self._state.name, state.name)
            self._state = state

    def _connect_display(self):
        """Connect to the Pygame display via Unix socket."""
        try:
            self._display_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._display_sock.connect(DISPLAY_SOCKET)
            self._display_sock.setblocking(False)
            log.info("Connected to display socket")
        except (FileNotFoundError, ConnectionRefusedError):
            log.warning("Display socket not available yet — face display may not be running")
            self._display_sock = None

    def _send_display(self, msg: dict):
        """Send a JSON message to the Pygame display."""
        if not self._display_sock:
            self._connect_display()
        if self._display_sock:
            try:
                self._display_sock.send((json.dumps(msg) + "\n").encode())
            except OSError:
                self._display_sock = None

    @property
    def state(self) -> State:
        return self._state

    @property
    def telemetry(self) -> dict:
        return self._telemetry

    @property
    def tof_data(self) -> dict:
        return self._tof_data

    @property
    def obstacle_distance(self) -> float:
        return self._obstacle_distance
