"""
animation.py — BOB Face Engine: Easing & Animated Values

Provides:
  - Pure easing functions (lerp, ease_out, ease_in_out, spring)
  - Animated class: wraps a float that smoothly chases a target each frame
  - AnimatedVec2: same but for (x, y) pairs
"""

from __future__ import annotations
import math


# ── Easing functions ──────────────────────────────────────────────────────────

def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation, t clamped to [0,1]."""
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


def ease_out(t: float) -> float:
    """Quadratic ease-out: fast start, slow finish."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 2


def ease_in_out(t: float) -> float:
    """Sinusoidal ease-in-out: smooth start and finish."""
    t = max(0.0, min(1.0, t))
    return -(math.cos(math.pi * t) - 1.0) / 2.0


def ease_in(t: float) -> float:
    """Quadratic ease-in: slow start, fast finish."""
    t = max(0.0, min(1.0, t))
    return t * t


def bounce_out(t: float) -> float:
    """Bouncy easing for expressive pops."""
    t = max(0.0, min(1.0, t))
    if t < 1 / 2.75:
        return 7.5625 * t * t
    elif t < 2 / 2.75:
        t -= 1.5 / 2.75
        return 7.5625 * t * t + 0.75
    elif t < 2.5 / 2.75:
        t -= 2.25 / 2.75
        return 7.5625 * t * t + 0.9375
    else:
        t -= 2.625 / 2.75
        return 7.5625 * t * t + 0.984375


# ── Animated scalar ───────────────────────────────────────────────────────────

class Animated:
    """
    A float value that smoothly approaches its target each frame.

    Usage:
        openness = Animated(1.0, speed=0.12)
        openness.target = 0.0          # set new target
        openness.update(dt)            # call each frame
        v = openness.value             # read current
    """

    def __init__(self, initial: float = 0.0, speed: float = 0.10) -> None:
        self.value  = float(initial)
        self.target = float(initial)
        self.speed  = speed            # lerp factor per frame (≈ speed/FPS per second)

    def update(self, dt: float) -> None:
        """Exponential decay approach — frame-rate independent."""
        # speed is expressed as "fraction per 60fps frame"
        # convert to per-second: alpha = 1 - (1-speed)^(dt*60)
        alpha = 1.0 - (1.0 - self.speed) ** (dt * 60.0)
        self.value = lerp(self.value, self.target, alpha)

    def snap(self) -> None:
        """Instantly jump to target."""
        self.value = self.target

    @property
    def done(self) -> bool:
        return abs(self.value - self.target) < 0.001

    def __float__(self) -> float:
        return self.value

    def __repr__(self) -> str:
        return f"Animated({self.value:.3f} → {self.target:.3f})"


# ── Animated 2D vector ────────────────────────────────────────────────────────

class AnimatedVec2:
    """Smoothly animated (x, y) pair."""

    def __init__(
        self,
        x: float = 0.0,
        y: float = 0.0,
        speed: float = 0.10,
    ) -> None:
        self.x = Animated(x, speed)
        self.y = Animated(y, speed)

    def set_target(self, x: float, y: float) -> None:
        self.x.target = x
        self.y.target = y

    def snap(self) -> None:
        self.x.snap()
        self.y.snap()

    def update(self, dt: float) -> None:
        self.x.update(dt)
        self.y.update(dt)

    @property
    def value(self) -> tuple[float, float]:
        return (self.x.value, self.y.value)


# ── Timer helper ──────────────────────────────────────────────────────────────

class Timer:
    """Simple countdown timer."""

    def __init__(self, duration: float = 1.0, auto_reset: bool = False) -> None:
        self._duration   = duration
        self._elapsed    = 0.0
        self._auto_reset = auto_reset
        self._fired      = False

    def reset(self, duration: float | None = None) -> None:
        if duration is not None:
            self._duration = duration
        self._elapsed = 0.0
        self._fired   = False

    def update(self, dt: float) -> bool:
        """Returns True the frame the timer fires."""
        if self._fired and not self._auto_reset:
            return False
        self._elapsed += dt
        if self._elapsed >= self._duration:
            self._elapsed = self._elapsed % self._duration if self._auto_reset else self._duration
            if not self._fired or self._auto_reset:
                self._fired = True
                return True
        return False

    @property
    def progress(self) -> float:
        """0.0 → 1.0 as timer counts down."""
        return min(1.0, self._elapsed / self._duration) if self._duration > 0 else 1.0

    @property
    def done(self) -> bool:
        return self._fired and not self._auto_reset


# ── Oscillator ────────────────────────────────────────────────────────────────

class Oscillator:
    """Sine wave oscillator, useful for speaking mouth, idle breathing etc."""

    def __init__(self, freq: float = 1.0, amplitude: float = 1.0, phase: float = 0.0) -> None:
        self.freq      = freq         # Hz
        self.amplitude = amplitude
        self.phase     = phase        # radians
        self._t        = 0.0

    def update(self, dt: float) -> float:
        self._t += dt
        return math.sin(2 * math.pi * self.freq * self._t + self.phase) * self.amplitude

    @property
    def value(self) -> float:
        return math.sin(2 * math.pi * self.freq * self._t + self.phase) * self.amplitude

    def reset(self) -> None:
        self._t = 0.0
