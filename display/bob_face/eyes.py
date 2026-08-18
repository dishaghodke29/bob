"""
eyes.py — BOB Face Engine: Fused Minion Goggles

Updated to perfectly match the reference image:
- No black pupil (solid brown iris)
- Large top-right white shine
- Smaller bottom-left light-brown shine
- Strap connection buckles
- Thick black stroke outlines on the goggles
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import pygame

from . import config as C


@dataclass
class EyeParams:
    openness:       float           = 1.0
    pupil_nx:       float           = 0.0
    pupil_ny:       float           = 0.0
    pupil_size:     float           = 1.0
    iris_color:     Optional[Tuple] = None
    brow_height:    float           = 0.0
    brow_angle:     float           = 0.0
    brow_thickness: float           = 1.0


def draw_eye_pair(surface: pygame.Surface, p_l: EyeParams, p_r: EyeParams) -> None:
    """
    Draw both minion goggles perfectly layered.
    """
    gr = C.GOGGLE_RADIUS
    er = C.EYE_RADIUS
    cx_l = C.EYE_L_CX
    cx_r = C.EYE_R_CX
    cy = C.EYE_CY

    # 1. Base strap is already drawn by face_engine.

    # 2. Strap Buckles (where strap meets goggle)
    bw = 25
    bh = 70
    by = cy - bh // 2
    # Left buckle
    pygame.draw.rect(surface, C.GOGGLE_RIM_DARK, (cx_l - gr - bw + 8, by, bw, bh), border_radius=6)
    pygame.draw.rect(surface, (30, 30, 30), (cx_l - gr - bw + 8, by, bw, bh), 4, border_radius=6)
    # Right buckle
    pygame.draw.rect(surface, C.GOGGLE_RIM_DARK, (cx_r + gr - 8, by, bw, bh), border_radius=6)
    pygame.draw.rect(surface, (30, 30, 30), (cx_r + gr - 8, by, bw, bh), 4, border_radius=6)

    # 3. Outer goggle frame (Black shadow base first)
    pygame.draw.circle(surface, (30, 30, 30), (cx_l, cy), gr + 4)
    pygame.draw.circle(surface, (30, 30, 30), (cx_r, cy), gr + 4)
    
    # Base silver fill
    pygame.draw.circle(surface, C.GOGGLE_RIM, (cx_l, cy), gr)
    pygame.draw.circle(surface, C.GOGGLE_RIM, (cx_r, cy), gr)

    # 4. Sclera (White base)
    pygame.draw.circle(surface, C.SCLERA_COLOR, (cx_l, cy), er)
    pygame.draw.circle(surface, C.SCLERA_COLOR, (cx_r, cy), er)

    # 5. Inner eye (Solid Brown Iris, Shines)
    _draw_inner(surface, cx_l, cy, p_l)
    _draw_inner(surface, cx_r, cy, p_r)

    # 6. Eyelids (Yellow background dropping down)
    _draw_lid(surface, cx_l, cy, p_l)
    _draw_lid(surface, cx_r, cy, p_r)

    # 7. Re-draw thick silver rim over eyelids to keep it clean
    pygame.draw.circle(surface, C.GOGGLE_RIM, (cx_l, cy), gr, C.RIM_THICKNESS)
    pygame.draw.circle(surface, C.GOGGLE_RIM, (cx_r, cy), gr, C.RIM_THICKNESS)

    # Inner and outer black strokes for the rim
    pygame.draw.circle(surface, (30, 30, 30), (cx_l, cy), er, 4)
    pygame.draw.circle(surface, (30, 30, 30), (cx_r, cy), er, 4)
    pygame.draw.circle(surface, (30, 30, 30), (cx_l, cy), gr, 4)
    pygame.draw.circle(surface, (30, 30, 30), (cx_r, cy), gr, 4)

    # 8. Eyebrows (high up on forehead)
    _draw_brow(surface, cx_l, cy, p_l)
    _draw_brow(surface, cx_r, cy, p_r)


def _draw_inner(surface: pygame.Surface, cx: int, cy: int, p: EyeParams) -> None:
    er = C.EYE_RADIUS
    iris_r = int(er * C.IRIS_FRAC)
    max_off = int(er * 0.35)

    idx = int(p.pupil_nx * max_off)
    idy = int(p.pupil_ny * max_off)

    dist = math.hypot(idx, idy)
    clamp = er - iris_r - 2
    if dist > clamp and dist > 0:
        idx = int(idx * (clamp / dist))
        idy = int(idy * (clamp / dist))

    icx = cx + idx
    icy = cy + idy

    icolor = p.iris_color or C.IRIS_COLOR
    
    # Main Brown Iris (NO black pupil)
    pygame.draw.circle(surface, icolor, (icx, icy), iris_r)
    
    # Dark outer ring for iris depth
    pygame.draw.circle(surface, (40, 20, 10), (icx, icy), iris_r, 4)

    # Primary shine (Large white dot upper right)
    sr1 = int(iris_r * 0.28)
    pygame.draw.circle(surface, C.SHINE_COLOR, (icx + int(iris_r*0.3), icy - int(iris_r*0.3)), sr1)

    # Secondary shine (Lighter brown crescent/dot lower left)
    sr2 = int(iris_r * 0.18)
    light_brown = (min(255, icolor[0]+80), min(255, icolor[1]+60), min(255, icolor[2]+40))
    pygame.draw.circle(surface, light_brown, (icx - int(iris_r*0.35), icy + int(iris_r*0.35)), sr2)


def _draw_lid(surface: pygame.Surface, cx: int, cy: int, p: EyeParams) -> None:
    op = max(0.0, min(1.0, p.openness))
    if op >= 0.99:
        return
    
    gr = C.GOGGLE_RADIUS
    
    # Upper lid drops down
    lid_bot_y = cy - gr + int((1.0 - op) * gr * 2)
    lid_rect = pygame.Rect(cx - gr, cy - gr, gr * 2, lid_bot_y - (cy - gr))
    pygame.draw.rect(surface, C.BG_COLOR, lid_rect)

    # Lower lid rises up when mostly closed
    if op < 0.2:
        lower_pct = 1.0 - (op / 0.2)
        lower_h = int(lower_pct * gr * 0.6)
        lower_rect = pygame.Rect(cx - gr, cy + gr - lower_h, gr * 2, lower_h)
        pygame.draw.rect(surface, C.BG_COLOR, lower_rect)


def _draw_brow(surface: pygame.Surface, cx: int, cy: int, p: EyeParams) -> None:
    brow_y = cy + C.BROW_Y_OFFSET - int(p.brow_height * 20)
    bw = C.BROW_WIDTH
    bh = max(4, int(C.BROW_HEIGHT * p.brow_thickness))

    pts = []
    steps = 12
    for i in range(steps + 1):
        t = i / float(steps)
        x = cx - bw//2 + int(bw * t)
        arc = (1.0 - (2.0 * t - 1.0)**2) * C.BROW_CURVE
        tilt = (t - 0.5) * p.brow_angle * 30
        pts.append((x, brow_y - int(arc) + int(tilt)))
        
    bot_pts = []
    for i in range(steps, -1, -1):
        t = i / float(steps)
        x = cx - bw//2 + int(bw * t)
        arc = (1.0 - (2.0 * t - 1.0)**2) * C.BROW_CURVE
        tilt = (t - 0.5) * p.brow_angle * 30
        bot_pts.append((x, brow_y - int(arc) + int(tilt) + bh))

    pygame.draw.polygon(surface, C.BROW_COLOR, pts + bot_pts)
