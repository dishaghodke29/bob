"""
face_engine.py — BOB Face Engine: Main compositor and animation orchestrator.

FaceEngine owns all animated values and drives the full rendering pipeline:
  1. StateMachine → current state + blink/wander timing
  2. Animated values → smooth interpolation toward expression targets
  3. draw() → composites face to the pygame surface

This module is the single source of truth for what BOB's face looks like at
any given frame.
"""

from __future__ import annotations

import math
import time
import pygame

from . import config as C
from .animation import Animated, AnimatedVec2, Oscillator, lerp
from .state_machine import State, StateMachine
from .expressions import EXPRESSIONS, ExpressionParams
from .eyes import EyeParams, draw_eye_pair
from .mouth import MouthParams, draw_mouth, get_speaking_params


class FaceEngine:
    """
    Composites and animates BOB's full face.

    Main loop usage:
        engine = FaceEngine()
        ...
        for event in pygame.event.get():
            ...
        engine.update(dt)
        engine.draw(screen)
    """

    def __init__(self) -> None:
        self._sm = StateMachine()

        # ── Animated eye values ───────────────────────────────────────────
        self._eye_openness  = Animated(1.0,  speed=C.SMOOTH_FAST)
        self._brow_height   = Animated(0.0,  speed=C.SMOOTH_MED)
        self._brow_angle_l  = Animated(0.0,  speed=C.SMOOTH_MED)
        self._brow_angle_r  = Animated(0.0,  speed=C.SMOOTH_MED)
        self._pupil_size    = Animated(1.0,  speed=C.SMOOTH_MED)

        # Pupil gaze direction (normalized -1..1)
        self._gaze   = AnimatedVec2(0.0, 0.0, speed=C.SMOOTH_SLOW)
        # External look-at override (from vision system)
        self._lookat = AnimatedVec2(0.0, 0.0, speed=C.SMOOTH_SLOW)
        self._lookat_active = False
        self._lookat_timeout = 0.0

        # Iris color (R,G,B) animated separately
        self._iris_r = Animated(C.IRIS_COLOR[0], speed=C.SMOOTH_MED)
        self._iris_g = Animated(C.IRIS_COLOR[1], speed=C.SMOOTH_MED)
        self._iris_b = Animated(C.IRIS_COLOR[2], speed=C.SMOOTH_MED)

        # ── Animated mouth values ─────────────────────────────────────────
        self._smile      = Animated(0.3,  speed=C.SMOOTH_MED)
        self._mouth_open = Animated(0.0,  speed=C.SMOOTH_FAST)

        # ── Subtitle display ──────────────────────────────────────────────
        self._subtitle_text     = ""
        self._subtitle_duration = 0.0
        self._subtitle_elapsed  = 0.0
        self._font: pygame.font.Font | None = None

        # ── Misc ──────────────────────────────────────────────────────────
        self._idle_bob = Oscillator(freq=0.25, amplitude=3.0)  # subtle up/down
        self._bg_pulse = Oscillator(freq=0.15, amplitude=0.03)  # background glow pulse
        self._t = 0.0

        # Pre-compute face surface for shadow (cached)
        self._face_surf: pygame.Surface | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def set_state(self, state: State | str) -> None:
        """Change BOB's emotional state."""
        self._sm.set_state(state)

    def look_at(self, norm_x: float, norm_y: float) -> None:
        """
        Direct BOB's gaze toward a normalized screen coordinate.
        norm_x, norm_y: 0.0-1.0 from top-left.
        """
        # Convert 0..1 screen coords to -1..1 gaze direction
        gx = (norm_x - 0.5) * 2.0
        gy = (norm_y - 0.5) * 2.0
        self._lookat.set_target(gx, gy)
        self._lookat_active  = True
        self._lookat_timeout = 5.0  # auto-expire after 5s

    def set_subtitle(self, text: str, duration: float = 3.0) -> None:
        self._subtitle_text     = text
        self._subtitle_duration = duration
        self._subtitle_elapsed  = 0.0

    @property
    def current_state(self) -> State:
        return self._sm.current

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        self._t += dt

        # 1. Update state machine (blink, wander, speaking phase)
        self._sm.update(dt)

        # 2. Fetch target expression for current state
        expr = EXPRESSIONS.get(self._sm.current.value, EXPRESSIONS['idle'])

        # 3. Drive animated values toward expression targets
        self._apply_expression(expr, dt)

        # 4. Override eye openness with blink value from state machine
        blink_open = self._sm.blink_openness
        # Blend: expression drives baseline, blink modulates it
        target_open = expr.eye_openness * blink_open
        self._eye_openness.target = target_open
        self._eye_openness.update(dt)

        # 5. Compute gaze direction
        wx, wy = self._sm.wander_offset
        if self._lookat_active:
            self._lookat_timeout -= dt
            if self._lookat_timeout <= 0:
                self._lookat_active = False
            self._lookat.update(dt)
            lx, ly = self._lookat.value
            # Mix wander with look-at
            self._gaze.set_target(lx * 0.7 + wx * 0.3, ly * 0.7 + wy * 0.3)
        else:
            self._gaze.set_target(expr.pupil_target_x + wx, expr.pupil_target_y + wy)
        self._gaze.update(dt)

        # 6. Speaking mouth animation
        if self._sm.current == State.SPEAKING:
            speak_open = 0.3 + 0.3 * abs(math.sin(
                2 * math.pi * 3.5 * self._t
            ))
            self._mouth_open.target = speak_open
        else:
            self._mouth_open.target = expr.mouth_open
        self._mouth_open.update(dt)

        # 7. Update all other animated values
        self._brow_height.update(dt)
        self._brow_angle_l.update(dt)
        self._brow_angle_r.update(dt)
        self._pupil_size.update(dt)
        self._smile.update(dt)
        self._iris_r.update(dt)
        self._iris_g.update(dt)
        self._iris_b.update(dt)
        self._idle_bob.update(dt)
        self._bg_pulse.update(dt)

        # 8. Subtitle countdown
        if self._subtitle_text:
            self._subtitle_elapsed += dt
            if self._subtitle_elapsed >= self._subtitle_duration:
                self._subtitle_text = ""

    def _apply_expression(self, expr: ExpressionParams, dt: float) -> None:
        """Set targets for all animated values from an expression."""
        self._brow_height.target  = expr.brow_height
        self._brow_angle_l.target = expr.brow_angle
        ang_r = expr.brow_angle_r if expr.brow_angle_r is not None else -expr.brow_angle
        self._brow_angle_r.target = ang_r
        self._pupil_size.target   = expr.pupil_size
        self._smile.target        = expr.smile

        # Iris color target
        ic = expr.iris_color or C.IRIS_COLOR
        self._iris_r.target = ic[0]
        self._iris_g.target = ic[1]
        self._iris_b.target = ic[2]

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        """Render the complete face to the surface."""
        surface.fill(C.BG_COLOR)

        # Background glow (subtle circle behind face for HAPPY/ERROR states)
        self._draw_bg_glow(surface)

        # Face body (yellow ellipse with shadow)
        self._draw_face_body(surface)

        # Build eye params from animated values
        gx, gy = self._gaze.value
        iris_color = (
            int(max(0, min(255, self._iris_r.value))),
            int(max(0, min(255, self._iris_g.value))),
            int(max(0, min(255, self._iris_b.value))),
        )
        eye_params = EyeParams(
            openness       = self._eye_openness.value,
            pupil_nx       = gx,
            pupil_ny       = gy,
            pupil_size     = self._pupil_size.value,
            iris_color     = iris_color,
            brow_height    = self._brow_height.value,
            brow_angle     = self._brow_angle_l.value,
            brow_thickness = 1.0,
        )
        # Mirror brow angle for right eye
        eye_params_r = EyeParams(
            openness       = self._eye_openness.value,
            pupil_nx       = gx,
            pupil_ny       = gy,
            pupil_size     = self._pupil_size.value,
            iris_color     = iris_color,
            brow_height    = self._brow_height.value,
            brow_angle     = self._brow_angle_r.value,
            brow_thickness = 1.0,
        )
        draw_eye_pair(surface, eye_params, eye_params_r)

        # Mouth
        speak_phase = self._sm.speak_phase if self._sm.current == State.SPEAKING else 0.0
        mouth_params = MouthParams(
            smile       = self._smile.value,
            open_amount = self._mouth_open.value,
            speak_phase = speak_phase,
        )
        draw_mouth(surface, C.MOUTH_CX, C.MOUTH_CY, mouth_params)

        # Subtitle bar
        if self._subtitle_text:
            self._draw_subtitle(surface)

        # Sleeping Zs
        if self._sm.current == State.SLEEPING:
            self._draw_sleep_zs(surface)

        # Thinking dots
        if self._sm.current == State.THINKING:
            self._draw_thinking_dots(surface)

    def _draw_bg_glow(self, surface: pygame.Surface) -> None:
        """Subtle colored glow behind face for emotional states."""
        expr = EXPRESSIONS.get(self._sm.current.value)
        if not expr or not expr.glow_color:
            return
        gc = expr.glow_color
        if len(gc) == 4:
            glow = pygame.Surface((C.SCREEN_W, C.SCREEN_H), pygame.SRCALPHA)
            pygame.draw.ellipse(
                glow,
                gc,
                (C.FACE_CX - C.FACE_RX - 40, C.FACE_CY - C.FACE_RY - 40,
                 (C.FACE_RX + 40) * 2, (C.FACE_RY + 40) * 2),
            )
            surface.blit(glow, (0, 0))

    def _draw_face_body(self, surface: pygame.Surface) -> None:
        """Draw the yellow face ellipse with a subtle shadow."""
        # Shadow
        shadow_rect = pygame.Rect(
            C.FACE_CX - C.FACE_RX + 8,
            C.FACE_CY - C.FACE_RY + 12,
            C.FACE_RX * 2,
            C.FACE_RY * 2,
        )
        shadow_surf = pygame.Surface((C.FACE_RX * 2, C.FACE_RY * 2), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (0, 0, 0, 60), shadow_surf.get_rect())
        surface.blit(shadow_surf, shadow_rect.topleft)

        # Main face
        face_rect = pygame.Rect(
            C.FACE_CX - C.FACE_RX,
            C.FACE_CY - C.FACE_RY,
            C.FACE_RX * 2,
            C.FACE_RY * 2,
        )
        pygame.draw.ellipse(surface, C.FACE_COLOR, face_rect)

        # Highlight (top-left sheen)
        hi_surf = pygame.Surface((C.FACE_RX * 2, C.FACE_RY * 2), pygame.SRCALPHA)
        hi_rect = pygame.Rect(C.FACE_RX - 180, C.FACE_RY - 140, 300, 200)
        pygame.draw.ellipse(hi_surf, (255, 255, 255, 25), hi_rect)
        surface.blit(hi_surf, face_rect.topleft)

        # Outline
        pygame.draw.ellipse(surface, C.FACE_SHADOW, face_rect, 4)

    def _draw_subtitle(self, surface: pygame.Surface) -> None:
        """Draw subtitle text bar at bottom."""
        if self._font is None:
            pygame.font.init()
            try:
                self._font = pygame.font.SysFont("DejaVuSans,Ubuntu,Arial", 22)
            except Exception:
                self._font = pygame.font.Font(None, 26)

        # Fade in/out
        t = self._subtitle_elapsed / self._subtitle_duration if self._subtitle_duration > 0 else 1.0
        alpha = int(255 * min(1.0, (1.0 - max(0.0, t - 0.8) / 0.2)))

        bar_h = 44
        bar_surf = pygame.Surface((C.SCREEN_W, bar_h), pygame.SRCALPHA)
        bar_surf.fill((15, 15, 15, int(180 * alpha / 255)))
        surface.blit(bar_surf, (0, C.SCREEN_H - bar_h))

        text_surf = self._font.render(self._subtitle_text, True, C.SUBTITLE_FG)
        text_surf.set_alpha(alpha)
        tx = (C.SCREEN_W - text_surf.get_width()) // 2
        ty = C.SCREEN_H - bar_h + (bar_h - text_surf.get_height()) // 2
        surface.blit(text_surf, (tx, ty))

    def _draw_sleep_zs(self, surface: pygame.Surface) -> None:
        """Floating Z letters for sleeping state."""
        if self._font is None:
            pygame.font.init()
            try:
                self._font = pygame.font.SysFont("DejaVuSans,Ubuntu,Arial", 22)
            except Exception:
                self._font = pygame.font.Font(None, 26)

        for i in range(3):
            phase = (self._t * 0.4 + i * 0.33) % 1.0
            size  = int(20 + 15 * phase)
            alpha = int(255 * (1.0 - phase))
            x = C.EYE_R_CX + 60 + int(30 * phase)
            y = C.EYE_R_CY - 30 - int(80 * phase)
            try:
                zfont = pygame.font.SysFont("DejaVuSans,Ubuntu,Arial", size, bold=True)
            except Exception:
                zfont = pygame.font.Font(None, size + 6)
            zsurf = zfont.render("z", True, (100, 150, 255))
            zsurf.set_alpha(alpha)
            surface.blit(zsurf, (x, y))

    def _draw_thinking_dots(self, surface: pygame.Surface) -> None:
        """Three animated dots near mouth for thinking state."""
        for i in range(3):
            phase = (self._t * 1.5 + i * 0.33) % 1.0
            r = 7 + int(3 * abs(math.sin(math.pi * phase)))
            alpha = 150 + int(105 * abs(math.sin(math.pi * phase)))
            x = C.MOUTH_CX - 30 + i * 30
            y = C.MOUTH_CY + 50
            dot_surf = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(dot_surf, (80, 80, 100, alpha), (r + 2, r + 2), r)
            surface.blit(dot_surf, (x - r - 2, y - r - 2))
