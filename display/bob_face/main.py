"""
main.py — BOB Face Engine Entry Point

Runs the pygame render loop and socket server in a background thread.
Designed to run fullscreen on the 7-inch HDMI touchscreen (1024×600).

Launch:
  DISPLAY=:0 python3 -m bob_face
OR
  DISPLAY=:0 python3 /home/arduino/bob/display/bob_face/main.py

Control via Unix socket:
  echo '{"state":"happy"}' | nc -U /tmp/bob_display.sock
"""

from __future__ import annotations

import logging
import math
import os
import sys
import time

import pygame

# Allow running as script or as module
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bob_face import config as C
from bob_face.face_engine import FaceEngine
from bob_face.socket_server import SocketServer
from bob_face.state_machine import State

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-18s] %(levelname)s: %(message)s",
)
log = logging.getLogger("bob_face.main")


def run() -> None:
    log.info("BOB Face Engine starting…")

    # ── pygame init ──────────────────────────────────────────────────────────
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")   # use X11 on UNO Q
    os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "bob_face")

    pygame.init()
    pygame.font.init()
    pygame.mouse.set_visible(False)  # hide cursor on touchscreen

    # Fullscreen at native resolution
    flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
    try:
        screen = pygame.display.set_mode((C.SCREEN_W, C.SCREEN_H), flags)
    except Exception:
        # Fallback to windowed if fullscreen fails (dev mode)
        log.warning("Fullscreen failed — running windowed at %dx%d", C.SCREEN_W, C.SCREEN_H)
        screen = pygame.display.set_mode((C.SCREEN_W, C.SCREEN_H))

    pygame.display.set_caption(C.TITLE)
    clock = pygame.time.Clock()

    # ── Create face engine ───────────────────────────────────────────────────
    engine = FaceEngine()

    # ── Start socket server (background thread) ──────────────────────────────
    server = SocketServer()
    try:
        server.start()
    except Exception as exc:
        log.warning("Socket server failed to start: %s (continuing without IPC)", exc)

    log.info("BOB Face Engine running at %dx%d — socket: %s", C.SCREEN_W, C.SCREEN_H, C.SOCKET_PATH)

    # ── Startup animation — boot state ───────────────────────────────────────
    engine.set_state(State.IDLE)
    engine.set_subtitle("BOB Online", 2.0)

    # ── Main loop ─────────────────────────────────────────────────────────────
    running = True
    prev_time = time.perf_counter()

    while running:
        # Delta time (capped to avoid spiral of death)
        now = time.perf_counter()
        dt  = min(now - prev_time, 0.05)
        prev_time = now

        # ── Events ────────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                # Dev shortcuts: press keys to cycle states
                elif event.key == pygame.K_1:
                    engine.set_state(State.IDLE)
                elif event.key == pygame.K_2:
                    engine.set_state(State.LISTENING)
                elif event.key == pygame.K_3:
                    engine.set_state(State.THINKING)
                elif event.key == pygame.K_4:
                    engine.set_state(State.SPEAKING)
                elif event.key == pygame.K_5:
                    engine.set_state(State.HAPPY)
                elif event.key == pygame.K_6:
                    engine.set_state(State.SAD)
                elif event.key == pygame.K_7:
                    engine.set_state(State.SURPRISED)
                elif event.key == pygame.K_8:
                    engine.set_state(State.CONFUSED)
                elif event.key == pygame.K_9:
                    engine.set_state(State.SLEEPING)
                elif event.key == pygame.K_0:
                    engine.set_state(State.ERROR)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Touch → gaze at touch point (test feature)
                mx, my = pygame.mouse.get_pos()
                engine.look_at(mx / C.SCREEN_W, my / C.SCREEN_H)

        # ── Process socket commands ───────────────────────────────────────────
        for cmd in server.get_commands():
            _handle_command(engine, cmd)

        # ── Update + Draw ─────────────────────────────────────────────────────
        engine.update(dt)
        engine.draw(screen)
        pygame.display.flip()
        clock.tick(C.FPS)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    server.stop()
    pygame.quit()
    log.info("BOB Face Engine stopped.")


def _handle_command(engine: FaceEngine, cmd: dict) -> None:
    """Dispatch a normalized command dict to the face engine."""
    kind = cmd.get("cmd")
    if kind == "state":
        state_name = cmd.get("state", "idle")
        try:
            engine.set_state(State(state_name))
            log.debug("State → %s", state_name)
        except ValueError:
            # Try mapping common alternative names
            aliases = {
                "speaking":  "speaking",
                "talk":      "speaking",
                "listen":    "listening",
                "think":     "thinking",
                "sleep":     "sleeping",
                "wake":      "idle",
                "default":   "idle",
                "normal":    "idle",
                "excited":   "happy",
                "angry":     "confused",
            }
            mapped = aliases.get(state_name)
            if mapped:
                engine.set_state(State(mapped))
            else:
                log.warning("Unknown state: %r", state_name)

    elif kind == "subtitle":
        text     = cmd.get("text", "")
        duration = float(cmd.get("duration", 3.0))
        engine.set_subtitle(text, duration)

    elif kind == "look_at":
        x = float(cmd.get("x", 0.5))
        y = float(cmd.get("y", 0.5))
        engine.look_at(x, y)

    else:
        log.debug("Unknown command: %s", cmd)


if __name__ == "__main__":
    run()
