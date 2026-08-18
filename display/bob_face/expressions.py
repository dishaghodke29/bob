"""
expressions.py — BOB Face Engine: Per-state visual parameter sets.

Each robot state has a matching ExpressionParams that defines the target
look. FaceEngine interpolates animated values toward these targets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from . import config as C


@dataclass
class ExpressionParams:
    # ── Eyes ─────────────────────────────────────────────────────────────────
    eye_openness:   float          = 1.0    # 0=closed, 1=open
    brow_height:    float          = 0.0    # -1=lowered, 0=neutral, 1=raised
    brow_angle:     float          = 0.0    # neg=angry-inner-up, pos=sad-inner-down
    brow_angle_r:   Optional[float]= None   # right brow (mirrors left if None)
    pupil_size:     float          = 1.0    # 1.0=normal
    pupil_target_x: float          = 0.0   # normalized gaze direction
    pupil_target_y: float          = 0.0
    iris_color:     Optional[Tuple]= None   # None → C.IRIS_COLOR

    # ── Mouth ─────────────────────────────────────────────────────────────────
    smile:          float          = 0.3    # -1=frown, 0=neutral, 1=smile
    mouth_open:     float          = 0.0    # 0=closed, 1=fully open

    # ── Behavior overrides ────────────────────────────────────────────────────
    blink_rate_mult: float         = 1.0   # 1=normal, 0=no blink, 2=fast
    idle_wander:     bool          = True   # pupils wander randomly

    # ── Visual extras ─────────────────────────────────────────────────────────
    glow_color:     Optional[Tuple]= None   # RGBA background glow


# ── Expression definitions for every state ───────────────────────────────────

EXPRESSIONS: dict[str, ExpressionParams] = {

    "idle": ExpressionParams(
        eye_openness    = 1.0,
        brow_height     = 0.0,
        brow_angle      = 0.0,
        pupil_size      = 1.0,
        smile           = 0.25,
        mouth_open      = 0.0,
        blink_rate_mult = 1.0,
        idle_wander     = True,
    ),

    "listening": ExpressionParams(
        eye_openness    = 1.08,          # slightly wider = attentive
        brow_height     = 0.3,
        brow_angle      = 0.0,
        pupil_size      = 1.05,
        pupil_target_y  = -0.12,         # slight upward gaze (toward user's face)
        smile           = 0.15,
        mouth_open      = 0.0,
        blink_rate_mult = 0.6,           # less blinking = attentive
        idle_wander     = False,
    ),

    "thinking": ExpressionParams(
        eye_openness    = 0.82,
        brow_height     = 0.45,
        brow_angle      = -0.55,         # left brow up = furrowed
        brow_angle_r    = 0.2,           # right brow slightly different = asymmetric
        pupil_size      = 0.9,
        pupil_target_x  = -0.35,         # looking up-left
        pupil_target_y  = -0.35,
        smile           = 0.0,
        mouth_open      = 0.0,
        blink_rate_mult = 0.7,
        idle_wander     = False,
    ),

    "speaking": ExpressionParams(
        eye_openness    = 1.0,
        brow_height     = 0.1,
        brow_angle      = 0.0,
        pupil_size      = 1.0,
        pupil_target_y  = 0.05,          # slight downward = addressing listener
        smile           = 0.3,
        mouth_open      = 0.0,           # controlled by speaking animation in engine
        blink_rate_mult = 0.5,
        idle_wander     = True,
    ),

    "happy": ExpressionParams(
        eye_openness    = 1.12,
        brow_height     = 0.6,
        brow_angle      = 0.0,
        pupil_size      = 1.12,
        smile           = 1.0,
        mouth_open      = 0.25,
        iris_color      = C.IRIS_HAPPY,
        blink_rate_mult = 1.5,
        idle_wander     = True,
        glow_color      = (80, 200, 80, 40),
    ),

    "sad": ExpressionParams(
        eye_openness    = 0.70,
        brow_height     = -0.25,
        brow_angle      = 0.65,          # inner corners droop = sad V-shape
        pupil_size      = 0.88,
        pupil_target_y  = 0.3,           # looking down
        smile           = -0.75,
        mouth_open      = 0.0,
        iris_color      = C.IRIS_SAD,
        blink_rate_mult = 0.5,
        idle_wander     = False,
    ),

    "surprised": ExpressionParams(
        eye_openness    = 1.25,
        brow_height     = 1.0,
        brow_angle      = 0.0,
        pupil_size      = 1.25,
        smile           = 0.0,
        mouth_open      = 0.75,
        blink_rate_mult = 0.1,           # rarely blinks when surprised
        idle_wander     = False,
    ),

    "confused": ExpressionParams(
        eye_openness    = 0.88,
        brow_height     = 0.2,
        brow_angle      = -0.55,         # left brow up
        brow_angle_r    = 0.45,          # right brow down = asymmetric look
        pupil_size      = 0.92,
        pupil_target_x  = 0.25,          # slight sideways glance
        smile           = -0.15,
        mouth_open      = 0.08,          # slightly open = "huh?"
        blink_rate_mult = 1.2,
        idle_wander     = True,
    ),

    "sleeping": ExpressionParams(
        eye_openness    = 0.0,           # fully closed
        brow_height     = -0.15,
        brow_angle      = 0.0,
        pupil_size      = 0.7,
        smile           = 0.1,           # peaceful expression
        mouth_open      = 0.0,
        blink_rate_mult = 0.0,           # no blinking (already closed)
        idle_wander     = False,
    ),

    "error": ExpressionParams(
        eye_openness    = 0.82,
        brow_height     = -0.1,
        brow_angle      = -0.6,
        brow_angle_r    = -0.6,          # both brows furrowed = concern
        pupil_size      = 0.85,
        smile           = -0.35,
        mouth_open      = 0.1,
        iris_color      = C.IRIS_ERROR,
        blink_rate_mult = 1.8,           # rapid blinking = agitated
        idle_wander     = True,
        glow_color      = (200, 50, 50, 45),
    ),
}
