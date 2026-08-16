"""
BOB Display — Face Renderer  (Goggle-Guy Edition)
Draws BOB's animated face on the Pygame surface.

Character design:
  • Round chubby YELLOW face
  • Two big circular PILOT GOGGLES — silver metallic ring, brown leather band
  • Brown irises, black pupil, one eye slightly derpy (cute/dumb vibe)
  • Wide TOOTHY GRIN — big square white teeth, curved mouth
  • Scanline overlay for that retro robot feel
  • Smooth emotion transitions + blink + pupil drift
"""

import math
import random
import time
from dataclasses import replace
from typing import Tuple

import pygame

from .emotions import (
    EmotionParams, get_emotion,
    C_FACE_YELLOW, C_FACE_SHADOW,
    C_GOGGLE_RING, C_GOGGLE_RING_D, C_GOGGLE_BAND, C_GOGGLE_LENS,
    C_EYE_WHITE, C_IRIS_BROWN, C_IRIS_BROWN_L, C_PUPIL, C_PUPIL_HL,
    C_MOUTH_DARK, C_TEETH, C_TEETH_LINE, C_TONGUE, C_LIP,
    C_BG_DARK, C_ACCENT, C_STATUS_TEXT,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _lerp_c(c1, c2, t):
    return tuple(int(_lerp(a, b, t)) for a, b in zip(c1, c2))

def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── FaceRenderer ─────────────────────────────────────────────────────────────

class FaceRenderer:
    W, H = 1024, 600

    # Face oval geometry
    FACE_CX   = W // 2
    FACE_CY   = H // 2 - 10
    FACE_RX   = 230   # horizontal radius
    FACE_RY   = 240   # vertical radius

    # Goggle geometry
    GOGGLE_R      = 82    # outer goggle rim radius
    GOGGLE_SEP    = 92    # centre-to-centre half-separation
    GOGGLE_Y_OFF  = -35   # offset upward from face centre
    RING_WIDTH    = 14    # thickness of metallic ring
    BAND_H        = 16    # height of leather band
    LENS_R        = 65    # clear lens radius (inside ring)
    IRIS_R        = 38    # brown iris radius
    PUPIL_R       = 20    # black pupil radius
    HL_R          = 7     # white highlight dot

    # Mouth geometry
    MOUTH_Y_OFF   = 80    # offset downward from face centre

    def __init__(self, screen: pygame.Surface):
        self._screen = screen

        # Emotion state
        self._cur  = get_emotion("idle")
        self._tgt  = get_emotion("idle")
        self._t    = 1.0
        self._spd  = 3.0

        # Blink
        self._blink_phase  = 0.0
        self._blink_timer  = 0.0
        self._next_blink   = self._rand_blink()
        self._blinking     = False

        # Pupil drift (separate per eye for derp)
        self._drift_x  = [0.0, 0.0]
        self._drift_y  = [0.0, 0.0]
        self._drift_tx = [0.0, 0.0]
        self._drift_ty = [0.0, 0.0]
        self._drift_tmr = 0.0

        # Mouth speaking animation
        self._mouth_phase = 0.0
        self._speaking    = False

        # Head wobble
        self._wobble_phase = 0.0
        self._wobble_x     = 0.0

        # Subtitle
        self._subtitle   = ""
        self._sub_timer  = 0.0
        self._font_sub   = pygame.font.SysFont("monospace", 20)
        self._font_name  = pygame.font.SysFont("monospace", 26, bold=True)

        # Scanlines (built once)
        self._scanlines = self._make_scanlines()

        self._last_t = time.monotonic()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_emotion(self, name: str, speed: float = 3.5):
        self._tgt     = get_emotion(name)
        self._t       = 0.0
        self._spd     = speed
        self._speaking = (name == "speaking")

    def set_subtitle(self, text: str, duration: float = 4.0):
        self._subtitle  = text
        self._sub_timer = duration

    def update_and_draw(self):
        now = time.monotonic()
        dt  = min(now - self._last_t, 0.05)
        self._last_t = now

        self._update_anim(dt)
        p = self._lerped()
        self._draw(p, dt)

    # ── Animation updates ─────────────────────────────────────────────────────

    def _update_anim(self, dt: float):
        # Emotion transition
        if self._t < 1.0:
            self._t = min(1.0, self._t + dt * self._spd)

        # Blink
        self._blink_timer += dt
        if not self._blinking and self._blink_timer >= self._next_blink:
            self._blinking    = True
            self._blink_phase = 0.0
        if self._blinking:
            self._blink_phase += dt * 9.0
            if self._blink_phase >= 1.0:
                self._blinking    = False
                self._blink_timer = 0.0
                self._next_blink  = self._rand_blink()
                self._blink_phase = 0.0

        # Pupil drift — independent per eye for derpy look
        self._drift_tmr += dt
        if self._drift_tmr > random.uniform(1.2, 3.0):
            self._drift_tmr = 0.0
            p = self._lerped()
            amp = p.idle_drift * 14
            for i in range(2):
                self._drift_tx[i] = random.uniform(-amp, amp)
                self._drift_ty[i] = random.uniform(-amp * 0.5, amp * 0.5)
            # Derp: right eye drifts differently
            if p.derp_factor > 0.1:
                self._drift_tx[1] = random.uniform(-amp * p.derp_factor * 2,
                                                     amp * p.derp_factor * 2)

        for i in range(2):
            self._drift_x[i] = _lerp(self._drift_x[i], self._drift_tx[i], dt * 4.0)
            self._drift_y[i] = _lerp(self._drift_y[i], self._drift_ty[i], dt * 4.0)

        # Mouth speaking wobble
        if self._speaking:
            self._mouth_phase += dt * 7.0

        # Head wobble
        p = self._lerped()
        if p.wobble > 0:
            self._wobble_phase += dt * 5.0
            self._wobble_x = math.sin(self._wobble_phase) * p.wobble * 6
        else:
            self._wobble_phase = 0.0
            self._wobble_x = _lerp(self._wobble_x, 0.0, dt * 8.0)

        # Subtitle timer
        if self._sub_timer > 0:
            self._sub_timer -= dt
            if self._sub_timer <= 0:
                self._subtitle = ""

    def _rand_blink(self) -> float:
        return random.uniform(2.0, 5.5)

    def _blink_factor(self) -> float:
        if not self._blinking:
            return 0.0
        return math.sin(self._blink_phase * math.pi)

    # ── Emotion interpolation ─────────────────────────────────────────────────

    def _lerped(self) -> EmotionParams:
        t  = _smoothstep(self._t)
        c  = self._cur
        tg = self._tgt
        if self._t >= 1.0:
            self._cur = self._tgt
        return replace(
            c,
            eye_open    = _lerp(c.eye_open,    tg.eye_open,    t),
            eye_squeeze = _lerp(c.eye_squeeze,  tg.eye_squeeze, t),
            pupil_x_off = _lerp(c.pupil_x_off, tg.pupil_x_off, t),
            pupil_y_off = _lerp(c.pupil_y_off, tg.pupil_y_off, t),
            pupil_size  = _lerp(c.pupil_size,  tg.pupil_size,  t),
            derp_factor = _lerp(c.derp_factor, tg.derp_factor, t),
            mouth_curve = _lerp(c.mouth_curve, tg.mouth_curve, t),
            mouth_width = _lerp(c.mouth_width, tg.mouth_width, t),
            mouth_open  = _lerp(c.mouth_open,  tg.mouth_open,  t),
            face_squish = _lerp(c.face_squish, tg.face_squish, t),
            ring_color  = _lerp_c(c.ring_color, tg.ring_color, t),
            bg_color    = _lerp_c(c.bg_color,   tg.bg_color,   t),
            blink_rate  = _lerp(c.blink_rate,  tg.blink_rate,  t),
        )

    # ── Master draw ───────────────────────────────────────────────────────────

    def _draw(self, p: EmotionParams, dt: float):
        self._screen.fill(p.bg_color)

        # Apply head wobble offset
        ox = int(self._wobble_x)
        cx = self.FACE_CX + ox
        cy = self.FACE_CY

        self._draw_face_body(cx, cy, p)
        self._draw_goggles(cx, cy, p)
        self._draw_mouth(cx, cy, p)
        self._draw_status(p)
        self._draw_subtitle()

        # Scanline overlay
        self._screen.blit(self._scanlines, (0, 0))

    # ── Face body ─────────────────────────────────────────────────────────────

    def _draw_face_body(self, cx: int, cy: int, p: EmotionParams):
        ry = int(self.FACE_RY * p.face_squish)
        rx = self.FACE_RX

        # Shadow/depth ellipse (slightly offset down-right)
        shadow_surf = pygame.Surface((rx*2+8, ry*2+8), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (*C_FACE_SHADOW, 120),
                            (0, 0, rx*2+8, ry*2+8))
        self._screen.blit(shadow_surf, (cx - rx - 4 + 8, cy - ry - 4 + 10))

        # Main yellow face
        pygame.draw.ellipse(self._screen, C_FACE_YELLOW,
                            (cx - rx, cy - ry, rx*2, ry*2))

        # Subtle cheek highlight (top-left)
        hl_surf = pygame.Surface((rx*2, ry*2), pygame.SRCALPHA)
        pygame.draw.ellipse(hl_surf, (255, 240, 100, 35),
                            (rx//3, ry//3, rx, ry//2))
        self._screen.blit(hl_surf, (cx - rx, cy - ry))

    # ── Goggles ───────────────────────────────────────────────────────────────

    def _draw_goggles(self, cx: int, cy: int, p: EmotionParams):
        gy = cy + self.GOGGLE_Y_OFF
        blink = self._blink_factor()

        # Left and right goggle centres
        eyes = [
            (cx - self.GOGGLE_SEP, gy, 0),   # left  eye, index 0
            (cx + self.GOGGLE_SEP, gy, 1),   # right eye, index 1
        ]

        # ── Leather band (drawn behind everything) ────────────────────────────
        band_y = gy - self.BAND_H // 2
        band_rect = pygame.Rect(
            cx - self.GOGGLE_SEP - self.GOGGLE_R - 20,
            band_y,
            (self.GOGGLE_SEP + self.GOGGLE_R + 20) * 2,
            self.BAND_H,
        )
        pygame.draw.rect(self._screen, C_GOGGLE_BAND, band_rect, border_radius=8)
        # Band highlight
        pygame.draw.rect(self._screen, (120, 80, 40),
                         (band_rect.x, band_rect.y + 2, band_rect.width, 4),
                         border_radius=4)

        # Bridge between the two goggles (connecting piece)
        bx0 = cx - self.GOGGLE_SEP + self.GOGGLE_R - 6
        bx1 = cx + self.GOGGLE_SEP - self.GOGGLE_R + 6
        bridge_rect = pygame.Rect(bx0, gy - 12, bx1 - bx0, 24)
        pygame.draw.rect(self._screen, C_GOGGLE_RING_D, bridge_rect, border_radius=6)
        pygame.draw.rect(self._screen, p.ring_color,
                         (bx0, gy - 8, bx1 - bx0, 16), border_radius=4)

        for (ex, ey, idx) in eyes:
            self._draw_single_goggle(ex, ey, idx, p, blink)

    def _draw_single_goggle(self, cx: int, cy: int, idx: int,
                             p: EmotionParams, blink: float):
        gr     = self.GOGGLE_R
        rw     = self.RING_WIDTH
        lr     = self.LENS_R
        eye_open = max(0.04, p.eye_open * (1.0 - blink))

        # ── Outer metallic ring shadow ────────────────────────────────────────
        pygame.draw.circle(self._screen, C_GOGGLE_RING_D, (cx+3, cy+4), gr)

        # ── Outer metallic ring ───────────────────────────────────────────────
        pygame.draw.circle(self._screen, p.ring_color, (cx, cy), gr)

        # Ring highlight (top arc — simulates chrome sheen)
        hl_arc = pygame.Surface((gr*2, gr*2), pygame.SRCALPHA)
        pygame.draw.arc(hl_arc, (220, 220, 215, 180),
                        (0, 0, gr*2, gr*2), math.radians(30), math.radians(150), rw-2)
        self._screen.blit(hl_arc, (cx - gr, cy - gr))

        # ── Lens background (clear with slight tint) ──────────────────────────
        pygame.draw.circle(self._screen, C_GOGGLE_LENS, (cx, cy), lr)

        # ── Vertical squish mask for blinking ─────────────────────────────────
        # We clip the eyeball contents to a vertically scaled ellipse
        eye_ry = max(3, int(lr * eye_open))

        # Eye white — ellipse for blink squish
        # Squeeze for happiness
        squeeze_rx = max(4, int(lr * (1.0 - p.eye_squeeze * 0.4)))
        eye_surf = pygame.Surface((squeeze_rx*2, eye_ry*2), pygame.SRCALPHA)
        pygame.draw.ellipse(eye_surf, C_EYE_WHITE,
                            (0, 0, squeeze_rx*2, eye_ry*2))
        self._screen.blit(eye_surf, (cx - squeeze_rx, cy - eye_ry))

        # ── Iris ──────────────────────────────────────────────────────────────
        if eye_ry > 5:
            ir = min(self.IRIS_R, eye_ry - 4)

            # Pupil offset from emotion + drift
            px_off = p.pupil_x_off
            py_off = p.pupil_y_off
            # Derp factor: right eye (idx=1) drifts inward
            if idx == 1 and p.derp_factor > 0.05:
                px_off -= p.derp_factor * 0.5

            pdx = int(px_off * ir + self._drift_x[idx] * 0.6)
            pdy = int(py_off * ir + self._drift_y[idx] * 0.6)

            # Clamp pupil inside lens
            max_drift = max(0, squeeze_rx - ir - 4)
            pdx = _clamp(pdx, -max_drift, max_drift)
            pdy = _clamp(pdy, -max(0, eye_ry - ir - 4), max(0, eye_ry - ir - 4))

            ipx = cx + pdx
            ipy = cy + pdy

            # Iris outer (dark brown ring)
            pygame.draw.circle(self._screen, C_IRIS_BROWN, (ipx, ipy), ir)

            # Iris inner (lighter)
            pygame.draw.circle(self._screen, C_IRIS_BROWN_L, (ipx, ipy),
                               max(2, int(ir * 0.65)))

            # Pupil
            pr = max(3, int(ir * p.pupil_size))
            pygame.draw.circle(self._screen, C_PUPIL, (ipx, ipy), pr)

            # Highlight dot
            hx = ipx - pr // 3
            hy = ipy - pr // 3
            pygame.draw.circle(self._screen, C_PUPIL_HL, (hx, hy), self.HL_R)
            # Small secondary highlight
            pygame.draw.circle(self._screen, C_PUPIL_HL,
                               (ipx + pr//4, ipy + pr//4), 3)

        # ── Lens glare (top-left reflection) ─────────────────────────────────
        glare_surf = pygame.Surface((lr*2, lr*2), pygame.SRCALPHA)
        pygame.draw.ellipse(glare_surf, (255, 255, 255, 45),
                            (lr//5, lr//6, lr - lr//3, lr//3))
        self._screen.blit(glare_surf, (cx - lr, cy - lr))

        # ── Inner ring border (dark inner edge) ───────────────────────────────
        pygame.draw.circle(self._screen, C_GOGGLE_RING_D, (cx, cy), lr, 3)

    # ── Mouth ─────────────────────────────────────────────────────────────────

    def _draw_mouth(self, cx: int, cy: int, p: EmotionParams):
        my = cy + self.MOUTH_Y_OFF

        # Speaking: animate mouth open height
        extra_open = 0.0
        if self._speaking:
            extra_open = abs(math.sin(self._mouth_phase)) * 0.3

        curve      = p.mouth_curve
        open_h     = int((p.mouth_open + extra_open) * 55)
        half_w     = int(self.W * p.mouth_width * 0.28)
        steps      = 40

        # Upper lip arc points
        top_pts = []
        for i in range(steps + 1):
            t  = i / steps
            x  = cx - half_w + 2 * half_w * t
            # Bezier-style curve: arch upward in the middle
            arch = math.sin(t * math.pi) * curve * 36
            y    = my - arch - open_h // 2
            top_pts.append((int(x), int(y)))

        # Lower lip arc points
        bot_pts = []
        for i in range(steps + 1):
            t  = i / steps
            x  = cx - half_w + 2 * half_w * t
            arch = math.sin(t * math.pi) * curve * 20
            y    = my + open_h // 2 + arch
            bot_pts.append((int(x), int(y)))

        if len(top_pts) < 2:
            return

        # Fill mouth cavity (dark)
        if open_h > 6:
            mouth_poly = top_pts + list(reversed(bot_pts))
            pygame.draw.polygon(self._screen, C_MOUTH_DARK, mouth_poly)

        # Draw teeth inside the open mouth
        if open_h > 10:
            self._draw_teeth(cx, my, half_w, open_h, curve, p.teeth_count,
                             p.show_tongue)

        # Upper lip outline
        pygame.draw.lines(self._screen, C_LIP, False, top_pts, 5)
        # Lower lip outline
        pygame.draw.lines(self._screen, C_LIP, False, bot_pts, 5)

        # Corner dots (lip corners)
        pygame.draw.circle(self._screen, C_LIP, top_pts[0],  5)
        pygame.draw.circle(self._screen, C_LIP, top_pts[-1], 5)

    def _draw_teeth(self, cx: int, my: int, half_w: int,
                    open_h: int, curve: float, n: int, show_tongue: bool):
        if n == 0:
            return

        # Tongue (visible in surprised)
        if show_tongue:
            t_cx = cx
            t_cy = my + open_h // 4
            t_rx = half_w // 2
            t_ry = open_h // 3
            pygame.draw.ellipse(self._screen, (200, 80, 80),
                                (t_cx - t_rx, t_cy - t_ry, t_rx*2, t_ry*2))

        # Upper teeth row
        tooth_w   = max(6, (half_w * 2 - 12) // n)
        tooth_h   = max(6, open_h // 2 - 4)
        start_x   = cx - half_w + 6
        tooth_top = my - open_h // 2 + 3

        for i in range(n):
            tx = start_x + i * tooth_w
            # Slight arch on tooth top following mouth curve
            arch_off = int(math.sin((i + 0.5) / n * math.pi) * curve * 10)
            ty       = tooth_top - arch_off
            rect     = pygame.Rect(tx + 1, ty, tooth_w - 3, tooth_h)
            pygame.draw.rect(self._screen, C_TEETH, rect, border_radius=4)
            # Tooth divider line
            if i > 0:
                pygame.draw.line(self._screen, C_TEETH_LINE,
                                 (tx, ty + 3), (tx, ty + tooth_h - 3), 2)

        # Bottom teeth (smaller)
        b_tooth_h = max(4, tooth_h // 2)
        b_n       = max(1, n - 1)
        b_w       = max(5, (half_w * 2 - 20) // b_n)
        b_start   = cx - half_w + 12
        b_top     = my + open_h // 2 - b_tooth_h - 2

        for i in range(b_n):
            tx   = b_start + i * b_w
            rect = pygame.Rect(tx + 1, b_top, b_w - 3, b_tooth_h)
            pygame.draw.rect(self._screen, C_TEETH, rect, border_radius=3)
            if i > 0:
                pygame.draw.line(self._screen, C_TEETH_LINE,
                                 (tx, b_top+2), (tx, b_top+b_tooth_h-2), 1)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _draw_status(self, p: EmotionParams):
        # Small name label bottom-left
        name_surf = self._font_name.render("B·O·B", True, C_ACCENT)
        self._screen.blit(name_surf, (20, self.H - 44))

        # Emotion label bottom-right
        emo = self._cur.name.upper()
        emo_surf = self._font_sub.render(emo, True, C_STATUS_TEXT)
        self._screen.blit(emo_surf, (self.W - emo_surf.get_width() - 20,
                                     self.H - 36))

    def _draw_subtitle(self):
        if not self._subtitle:
            return
        surf = self._font_sub.render(self._subtitle, True, (220, 220, 200))
        x    = (self.W - surf.get_width()) // 2
        y    = self.H - 70
        pad  = 10
        bg   = pygame.Rect(x - pad, y - pad//2,
                           surf.get_width() + pad*2, surf.get_height() + pad)
        pygame.draw.rect(self._screen, (30, 25, 15), bg, border_radius=8)
        pygame.draw.rect(self._screen, C_ACCENT, bg, width=1, border_radius=8)
        self._screen.blit(surf, (x, y))

    # ── Scanline overlay ──────────────────────────────────────────────────────

    def _make_scanlines(self) -> pygame.Surface:
        surf = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        for y in range(0, self.H, 4):
            pygame.draw.line(surf, (0, 0, 0, 18), (0, y), (self.W, y))
        return surf
