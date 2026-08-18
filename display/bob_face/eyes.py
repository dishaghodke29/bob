"""
eyes.py — BOB Face Engine: Eye rendering (sclera, iris, pupil, eyelid, brow)

All drawing is purely procedural using pygame.draw — no image files required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import pygame

from . import config as C

# ── Optional gfxdraw for anti-aliased circles ─────────────────────────────────
try:
    import pygame.gfxdraw
    _HAS_GFXDRAW = True
except ImportError:
    _HAS_GFXDRAW = False


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class EyeParams:
    openness:       float           = 1.0    # 0=fully closed, 1=fully open
    pupil_nx:       float           = 0.0    # normalized gaze X  (-1..1)
    pupil_ny:       float           = 0.0    # normalized gaze Y  (-1..1)
    pupil_size:     float           = 1.0    # scale factor
    iris_color:     Optional[Tuple] = None   # None → C.IRIS_COLOR
    brow_height:    float           = 0.0    # -1=low, 0=neutral, 1=raised
    brow_angle:     float           = 0.0    # tilt: -1=inner-up/angry, +1=inner-down/sad
    brow_thickness: float           = 1.0    # thickness scale


def _filled_circle(surf: pygame.Surface, cx: int, cy: int, r: int, color) -> None:
    """Draw a filled circle, using gfxdraw for anti-aliasing when available."""
    if r <= 0:
        return
    if _HAS_GFXDRAW and len(color) == 3:
        pygame.gfxdraw.aacircle(surf, cx, cy, r, color)
        pygame.gfxdraw.filled_circle(surf, cx, cy, r, color)
    else:
        pygame.draw.circle(surf, color, (cx, cy), r)


def draw_eye(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    radius: int,
    params: EyeParams,
) -> None:
    """
    Draw a single cartoon eye at pixel position (cx, cy).

    Layers (bottom to top):
      1. Sclera (white circle)
      2. Iris (colored circle, offset by gaze)
      3. Pupil (black circle)
      4. Eye shine (two white dots)
      5. Upper eyelid (yellow, slides down from top)
      6. Lower eyelid (yellow, slides up from bottom when nearly closed)
      7. Eye ring outline
      8. Eyebrow (above the eye)
    """
    iris_color = params.iris_color if params.iris_color else C.IRIS_COLOR

    # ── 1. Sclera ─────────────────────────────────────────────────────────────
    _filled_circle(surface, cx, cy, radius, C.SCLERA_COLOR)

    # ── 2. Iris (offset by gaze direction) ───────────────────────────────────
    iris_r   = int(radius * C.IRIS_FRAC)
    max_off  = int(radius * 0.22)          # max pixel offset from center
    iris_dx  = int(params.pupil_nx * max_off)
    iris_dy  = int(params.pupil_ny * max_off)
    iris_cx  = cx + iris_dx
    iris_cy  = cy + iris_dy

    # Clamp iris inside sclera
    dist = math.hypot(iris_dx, iris_dy)
    clamp_r = radius - iris_r - 2
    if dist > clamp_r and dist > 0:
        scale   = clamp_r / dist
        iris_cx = cx + int(iris_dx * scale)
        iris_cy = cy + int(iris_dy * scale)

    _filled_circle(surface, iris_cx, iris_cy, iris_r, iris_color)

    # Iris rim (slightly darker)
    rim_color = tuple(max(0, c - 50) for c in iris_color)
    pygame.draw.circle(surface, rim_color, (iris_cx, iris_cy), iris_r, 2)

    # ── 3. Pupil ──────────────────────────────────────────────────────────────
    pupil_r = int(radius * C.PUPIL_FRAC * params.pupil_size)
    pupil_r = max(4, min(pupil_r, iris_r - 4))
    _filled_circle(surface, iris_cx, iris_cy, pupil_r, C.PUPIL_COLOR)

    # ── 4. Eye shine ──────────────────────────────────────────────────────────
    shine_r  = max(3, int(radius * C.SHINE_FRAC))
    shine_dx = int(-radius * 0.28)
    shine_dy = int(-radius * 0.28)
    _filled_circle(surface, iris_cx + shine_dx, iris_cy + shine_dy, shine_r, C.SHINE_COLOR)
    # Secondary smaller shine
    _filled_circle(surface, iris_cx + int(shine_dx * 0.3),
                   iris_cy + int(shine_dy * 1.5), max(2, shine_r // 2), C.SHINE_COLOR)

    # ── 5. Upper eyelid ───────────────────────────────────────────────────────
    # openness=1.0 → lid at very top (barely visible)
    # openness=0.0 → lid covers entire eye
    openness = max(0.0, min(1.0, params.openness))
    lid_bottom_y = cy - radius + int(openness * radius * 2)

    if lid_bottom_y > cy - radius:
        # Polygon: top of eye bounding box → across → down to lid_bottom_y
        top_y    = cy - radius - 4
        right_x  = cx + radius + 4
        left_x   = cx - radius - 4
        lid_pts  = [
            (left_x,   top_y),
            (right_x,  top_y),
            (right_x,  lid_bottom_y),
            (cx,       lid_bottom_y - int(radius * 0.2 * (1 - openness))),
            (left_x,   lid_bottom_y),
        ]
        pygame.draw.polygon(surface, C.FACE_COLOR, lid_pts)

    # ── 6. Lower eyelid (only when almost closed) ─────────────────────────────
    if openness < 0.25:
        lower_pct   = 1.0 - openness / 0.25
        lower_top_y = cy + radius - int(lower_pct * radius * 0.7)
        bottom_y    = cy + radius + 4
        right_x     = cx + radius + 4
        left_x      = cx - radius - 4
        lower_pts   = [
            (left_x,  lower_top_y),
            (right_x, lower_top_y),
            (right_x, bottom_y),
            (left_x,  bottom_y),
        ]
        pygame.draw.polygon(surface, C.FACE_COLOR, lower_pts)

    # ── 7. Eye ring outline ───────────────────────────────────────────────────
    pygame.draw.circle(surface, C.FACE_SHADOW, (cx, cy), radius, 3)

    # ── 8. Eyebrow ────────────────────────────────────────────────────────────
    _draw_brow(surface, cx, cy, radius, params)


def _draw_brow(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    radius: int,
    params: EyeParams,
) -> None:
    """Draw eyebrow as a thick rotated rounded rectangle above the eye."""
    brow_y    = cy + C.BROW_Y_OFFSET - int(params.brow_height * 18)
    brow_w    = C.BROW_WIDTH
    brow_h    = max(8, int(C.BROW_HEIGHT * params.brow_thickness))
    angle_rad = math.radians(params.brow_angle * 22)   # max ~22 degrees tilt

    # Four corner points of the brow rectangle (before rotation)
    hw = brow_w // 2
    hh = brow_h // 2
    corners = [
        (-hw, -hh),
        ( hw, -hh),
        ( hw,  hh),
        (-hw,  hh),
    ]

    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    def rotate(px: float, py: float) -> tuple:
        rx = px * cos_a - py * sin_a
        ry = px * sin_a + py * cos_a
        return (int(cx + rx), int(brow_y + ry))

    pts = [rotate(px, py) for px, py in corners]
    pygame.draw.polygon(surface, C.BROW_COLOR, pts)

    # Rounded end caps (circles at left and right of brow)
    left_end  = rotate(-hw, 0)
    right_end = rotate( hw, 0)
    pygame.draw.circle(surface, C.BROW_COLOR, left_end,  hh)
    pygame.draw.circle(surface, C.BROW_COLOR, right_end, hh)


# ── Convenience: draw both eyes ───────────────────────────────────────────────

def draw_eye_pair(
    surface:      pygame.Surface,
    params_left:  EyeParams,
    params_right: EyeParams,
) -> None:
    """Draw both of BOB's eyes using positions from config."""
    draw_eye(surface, C.EYE_L_CX, C.EYE_L_CY, C.EYE_RADIUS, params_left)
    draw_eye(surface, C.EYE_R_CX, C.EYE_R_CY, C.EYE_RADIUS, params_right)
