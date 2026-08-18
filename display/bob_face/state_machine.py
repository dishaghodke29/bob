"""
state_machine.py — BOB Face Engine: State and time-based behavior driver.

Manages:
  - Which state BOB is in
  - Blink timer (natural, random-interval blinking)
  - Pupil wander (idle drift)
  - Speaking phase (for mouth animation)
  - Per-state overrides (no blink when sleeping, fast blink for error)
"""

from __future__ import annotations

import math
import random
from enum import Enum

from . import config as C
from .animation import lerp


class State(str, Enum):
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"
    HAPPY     = "happy"
    SAD       = "sad"
    SURPRISED = "surprised"
    CONFUSED  = "confused"
    SLEEPING  = "sleeping"
    ERROR     = "error"


class StateMachine:
    """
    Drives all time-based face behaviors.

    Call update(dt) every frame.
    Read properties to get current animated values.
    """

    def __init__(self) -> None:
        self.current:     State = State.IDLE
        self._prev:       State = State.IDLE
        self._state_time: float = 0.0      # seconds in current state

        # ── Blink system ───────────────────────────────────────────────────
        self._blink_phase:    str   = "wait"  # wait | closing | opening
        self._blink_t:        float = 0.0
        self._blink_openness: float = 1.0
        self._time_to_blink:  float = self._rand_blink_interval()

        # ── Pupil wander ───────────────────────────────────────────────────
        self._wander_x:  float = 0.0
        self._wander_y:  float = 0.0
        self._wx_target: float = 0.0
        self._wy_target: float = 0.0
        self._wander_cd: float = 0.0      # countdown to next target change

        # ── Speaking oscillator ────────────────────────────────────────────
        self._speak_phase: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def set_state(self, state: "State | str") -> None:
        if isinstance(state, str):
            state = State(state.lower())
        if state == self.current:
            return
        self._prev       = self.current
        self.current     = state
        self._state_time = 0.0

        # State entry actions
        if state == State.SLEEPING:
            # Begin closing eyes immediately
            self._blink_phase    = "closing"
            self._blink_t        = 0.0
            self._blink_openness = 1.0
        elif state == State.SURPRISED:
            # Eyes snap wide open, suppress blinking for 2s
            self._blink_openness = 1.0
            self._blink_phase    = "wait"
            self._time_to_blink  = 2.0
        elif state != State.SLEEPING and self._prev == State.SLEEPING:
            # Waking up — eyes open
            self._blink_phase    = "opening"
            self._blink_t        = 0.0

    def update(self, dt: float) -> None:
        self._state_time += dt
        self._update_blink(dt)
        self._update_wander(dt)
        if self.current == State.SPEAKING:
            self._speak_phase += dt * 4.0   # ~4Hz natural speech rate

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def blink_openness(self) -> float:
        """0.0 = fully closed, 1.0 = fully open."""
        return self._blink_openness

    @property
    def wander_offset(self) -> tuple:
        """Normalized pupil wander offset (x, y), each in roughly -0.3..0.3."""
        return (self._wander_x, self._wander_y)

    @property
    def speak_phase(self) -> float:
        return self._speak_phase

    @property
    def state_time(self) -> float:
        return self._state_time

    # ── Private ───────────────────────────────────────────────────────────────

    def _rand_blink_interval(self) -> float:
        return random.uniform(C.BLINK_INTERVAL_MIN, C.BLINK_INTERVAL_MAX)

    def _update_blink(self, dt: float) -> None:
        from .expressions import EXPRESSIONS
        expr = EXPRESSIONS.get(self.current.value)
        rate = expr.blink_rate_mult if expr else 1.0

        # Sleeping: eyes stay closed with tiny breathing oscillation
        if self.current == State.SLEEPING:
            breathe = 0.04 * abs(math.sin(math.pi * self._state_time * 0.2))
            self._blink_openness = breathe
            return

        # No blinking for states with rate=0
        if rate < 0.01:
            return

        if self._blink_phase == "wait":
            self._time_to_blink -= dt * rate
            if self._time_to_blink <= 0.0:
                self._blink_phase = "closing"
                self._blink_t     = 0.0

        elif self._blink_phase == "closing":
            self._blink_t       += dt
            progress             = self._blink_t / C.BLINK_DURATION_CLOSE
            self._blink_openness = 1.0 - min(1.0, progress)
            if progress >= 1.0:
                self._blink_phase = "opening"
                self._blink_t     = 0.0

        elif self._blink_phase == "opening":
            self._blink_t       += dt
            progress             = self._blink_t / C.BLINK_DURATION_OPEN
            self._blink_openness = min(1.0, progress)
            if progress >= 1.0:
                self._blink_phase   = "wait"
                self._time_to_blink = self._rand_blink_interval()

    def _update_wander(self, dt: float) -> None:
        from .expressions import EXPRESSIONS
        expr = EXPRESSIONS.get(self.current.value)
        if not (expr and expr.idle_wander):
            # Drift back to center
            self._wander_x = lerp(self._wander_x, 0.0, 0.05)
            self._wander_y = lerp(self._wander_y, 0.0, 0.05)
            return

        # Count down to next random target
        self._wander_cd -= dt
        if self._wander_cd <= 0.0:
            r          = C.WANDER_RADIUS
            self._wx_target = random.uniform(-r, r)
            self._wy_target = random.uniform(-r * 0.6, r * 0.6)
            self._wander_cd = random.uniform(1.2, 3.5)

        # Smoothly approach wander target
        self._wander_x = lerp(self._wander_x, self._wx_target, C.WANDER_SPEED)
        self._wander_y = lerp(self._wander_y, self._wy_target, C.WANDER_SPEED)
