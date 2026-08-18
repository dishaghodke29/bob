"""
mouth.py — BOB Face Engine: Mouth rendering + speaking visemes

Draws BOB's cartoon mouth as a filled bezier-approximated shape.
Supports: smile, frown, open/close, speaking animation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

import pygame

from . import config as C


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class MouthParams:
    smile:       float = 0.3    # -1.0=deep frown, 0.0=neutral, 1.0=big smile
    open_amount: float = 0.0    # 0=closed, 1=fully open
    width_scale: float = 1.0    # 1.0=normal width
    speak_phase: float = 0.0    # used externally to pick viseme (not used here)


# ── Bezier helpers ────────────────────────────────────────────────────────────

def _quad_bezier(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    steps: int = 24,
) -> List[Tuple[int, int]]:
    """Return integer points along a quadratic bezier from p0→p1(ctrl)→p2."""
    pts = []
    for i in range(steps + 1):
        t  = i / steps
        mt = 1.0 - t
        x  = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y  = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        pts.append((int(x), int(y)))
    return pts


# ── Main draw function ────────────────────────────────────────────────────────

def draw_mouth(
    surface:    pygame.Surface,
    cx:         int,
    cy:         int,
    params:     MouthParams,
) -> None:
    """
    Draw BOB's mouth at screen position (cx, cy).

    When closed: a curved smile/frown line.
    When open:   a filled shape with inside color and optional teeth.
    """
    width  = int(C.MOUTH_W * params.width_scale)
    half_w = width // 2

    # Corner positions (always horizontal)
    lx, ly = cx - half_w, cy
    rx, ry = cx + half_w, cy

    open_amount = max(0.0, min(1.0, params.open_amount))
    smile       = max(-1.0, min(1.0, params.smile))

    # Upper lip control point — smile pulls control point DOWN (+Y) to make a U shape
    upper_ctrl_y = cy + int(smile * 45)
    
    # Lower lip control point — drops further down proportional to open_amount
    open_px       = int(open_amount * C.MOUTH_H * 0.9)
    lower_ctrl_y  = cy + int(smile * 45) + open_px

    if open_amount < 0.06:
        # ── CLOSED mouth: just a curved line ─────────────────────────────────
        pts = _quad_bezier((lx, ly), (cx, upper_ctrl_y), (rx, ry), steps=28)
        if len(pts) >= 2:
            pygame.draw.lines(surface, C.MOUTH_COLOR, False, pts, 8)
        # Rounded corner dots
        pygame.draw.circle(surface, C.MOUTH_COLOR, (lx, ly), 4)
        pygame.draw.circle(surface, C.MOUTH_COLOR, (rx, ry), 4)

    else:
        # ── OPEN mouth: filled shape ──────────────────────────────────────────

        # Upper lip curve (left → right, arching upward with smile)
        upper_pts = _quad_bezier((lx, ly), (cx, upper_ctrl_y), (rx, ry), steps=24)

        # Lower lip curve (right → left, dropping down for opening)
        lower_pts = _quad_bezier((rx, ry), (cx, lower_ctrl_y), (lx, ly), steps=24)

        # Filled interior polygon
        fill_pts = upper_pts + lower_pts
        if len(fill_pts) >= 3:
            pygame.draw.polygon(surface, C.MOUTH_INSIDE, fill_pts)

        # Teeth strip (when open enough)
        if open_amount > 0.35:
            teeth_h  = int(open_px * 0.35 * min(1.0, (open_amount - 0.35) / 0.3))
            teeth_y  = cy + int(smile * 8)
            teeth_w  = int(width * 0.72)
            if teeth_h > 3:
                # Clip teeth inside the mouth shape using a sub-surface approach
                teeth_rect = pygame.Rect(cx - teeth_w // 2, teeth_y, teeth_w, teeth_h)
                pygame.draw.rect(surface, C.TEETH_COLOR, teeth_rect, border_radius=4)
                # Tooth dividers
                n_teeth = 4
                for i in range(1, n_teeth):
                    tx = teeth_rect.left + int(teeth_w * i / n_teeth)
                    pygame.draw.line(surface, (200, 200, 190),
                                     (tx, teeth_y), (tx, teeth_y + teeth_h), 1)

        # Draw upper lip outline on top
        if len(upper_pts) >= 2:
            pygame.draw.lines(surface, C.MOUTH_COLOR, False, upper_pts, 5)
        # Draw lower lip outline
        if len(lower_pts) >= 2:
            pygame.draw.lines(surface, C.MOUTH_COLOR, False, lower_pts, 4)

        # Corner circles to smooth join
        pygame.draw.circle(surface, C.MOUTH_COLOR, (lx, ly), 4)
        pygame.draw.circle(surface, C.MOUTH_COLOR, (rx, ry), 4)


# ── Speaking helper ───────────────────────────────────────────────────────────

def get_speaking_params(phase: float, base_smile: float = 0.3) -> MouthParams:
    """
    Generate animated mouth params for speaking.
    phase: continuously advancing float (time * freq).
    Cycles through different open amounts to simulate talking.
    """
    # Primary jaw oscillation
    jaw = abs(math.sin(math.pi * phase))

    # Secondary overtone for more natural look
    jaw += 0.3 * abs(math.sin(math.pi * phase * 2.3 + 0.5))
    jaw  = min(jaw, 1.0)

    # Slight smile modulation while talking
    smile = base_smile + 0.1 * math.sin(math.pi * phase * 0.7)

    return MouthParams(
        smile       = smile,
        open_amount = jaw * 0.65,  # max 65% open
        width_scale = 1.0 + 0.05 * math.sin(math.pi * phase * 1.5),
    )
