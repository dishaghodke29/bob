"""
BOB Display — Main Pygame Application
Runs fullscreen at 1024×600 on the Waveshare 7" HDMI touchscreen.

Communicates with the Python brain via a Unix domain socket:
  /tmp/bob_display.sock

Protocol (JSON lines):
  Brain → Display:
    {"type": "emotion", "name": "happy"}
    {"type": "emotion", "name": "thinking", "speed": 5.0}
    {"type": "subtitle", "text": "Hello!", "duration": 4.0}
    {"type": "screen", "name": "face"}
    {"type": "screen", "name": "game_menu"}
    {"type": "screen", "name": "tictactoe"}
    {"type": "screen", "name": "snake"}

  Display → Brain:
    {"type": "touch", "x": 512, "y": 300}
    {"type": "game_event", "game": "tictactoe", "event": "player_won"}
"""

import asyncio
import json
import logging
import os
import socket
import sys
import threading
from typing import Optional

import pygame

# ── Path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from display.face.face_renderer import FaceRenderer
from display.games.game_menu    import GameMenu
from display.games.tic_tac_toe  import TicTacToe
from display.games.snake        import Snake

import argparse

log = logging.getLogger("bob_display")

SOCKET_PATH = "/tmp/bob_display.sock"
FPS         = 60
SCREEN_W    = 1024
SCREEN_H    = 600


def _detect_mode() -> str:
    """
    Auto-detect display mode:
      - If running on the 7" HDMI screen (1024×600 native) → fullscreen
      - Otherwise (regular monitor) → windowed for testing
    Override with --windowed or --fullscreen CLI flags.
    """
    parser = argparse.ArgumentParser(description="BOB Face Display")
    parser.add_argument("--windowed",   action="store_true", help="Run in a window (testing)")
    parser.add_argument("--fullscreen", action="store_true", help="Force fullscreen")
    args, _ = parser.parse_known_args()

    if args.fullscreen:
        return "fullscreen"
    if args.windowed:
        return "windowed"

    # Auto-detect: check native resolution
    import subprocess
    try:
        out = subprocess.check_output(["xrandr", "--current"], text=True, timeout=3)
        # If ANY connected display is 1024x600 → assume 7" screen
        if "1024x600" in out:
            return "fullscreen"
    except Exception:
        pass
    return "windowed"   # Default safe: windowed on unknown monitors


class BobDisplay:
    def __init__(self):
        self._running     = False
        self._screen_name = "face"       # "face" | "game_menu" | "tictactoe" | "snake"

        # IPC socket
        self._sock_thread: Optional[threading.Thread] = None
        self._msg_queue: list[dict] = []
        self._msg_lock  = threading.Lock()

        # Pygame objects (created in run())
        self._screen:   Optional[pygame.Surface] = None
        self._face:     Optional[FaceRenderer]   = None
        self._game_menu: Optional[GameMenu]      = None
        self._ttt:      Optional[TicTacToe]      = None
        self._snake:    Optional[Snake]           = None

        self._brain_conn: Optional[socket.socket] = None

    # ──────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────

    def run(self):
        """Start the display — this blocks until exit."""
        display_mode = _detect_mode()
        is_fullscreen = (display_mode == "fullscreen")

        # Setup Pygame
        os.environ.setdefault("DISPLAY", ":0")
        pygame.init()

        if is_fullscreen:
            pygame.mouse.set_visible(False)
            flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
            self._screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
            log.info("Display: FULLSCREEN %dx%d", SCREEN_W, SCREEN_H)
        else:
            pygame.mouse.set_visible(True)
            flags = pygame.RESIZABLE
            self._screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
            log.info("Display: WINDOWED %dx%d (testing mode — press F for fullscreen, ESC to quit)", SCREEN_W, SCREEN_H)

        pygame.display.set_caption("BOB — Robot Face Display")

        # Create sub-systems
        self._face      = FaceRenderer(self._screen)
        self._game_menu = GameMenu(self._screen, on_select=self._on_game_select)
        self._ttt       = TicTacToe(self._screen, on_exit=self._back_to_menu)
        self._snake     = Snake(self._screen, on_exit=self._back_to_menu)

        # Start IPC socket listener
        self._start_socket_listener()

        # Main loop
        clock   = pygame.time.Clock()
        self._running = True
        log.info("BOB display running at %dx%d @ %d FPS", SCREEN_W, SCREEN_H, FPS)

        while self._running:
            dt = clock.tick(FPS) / 1000.0

            # Process messages from brain
            self._process_messages()

            # Handle Pygame events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False

                elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                    pos = self._get_touch_pos(event)
                    self._send_to_brain({"type": "touch", "x": pos[0], "y": pos[1]})
                    self._handle_touch(pos)

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self._screen_name != "face":
                            self._set_screen("face")
                        else:
                            self._running = False
                    elif event.key == pygame.K_f:
                        # Toggle fullscreen on the fly
                        pygame.display.toggle_fullscreen()
                    elif event.key == pygame.K_1:
                        self._face.set_emotion("idle")
                    elif event.key == pygame.K_2:
                        self._face.set_emotion("happy")
                    elif event.key == pygame.K_3:
                        self._face.set_emotion("thinking")
                    elif event.key == pygame.K_4:
                        self._face.set_emotion("listening")
                    elif event.key == pygame.K_5:
                        self._face.set_emotion("speaking")
                    elif event.key == pygame.K_6:
                        self._face.set_emotion("alert")
                    elif event.key == pygame.K_7:
                        self._face.set_emotion("sleeping")
                    elif event.key == pygame.K_8:
                        self._face.set_emotion("surprised")
                    elif event.key == pygame.K_g:
                        self._set_screen("game_menu")

            # Draw current screen
            self._draw()
            pygame.display.flip()

        pygame.quit()
        self._cleanup_socket()

    # ──────────────────────────────────────────
    # Screen management
    # ──────────────────────────────────────────

    def _set_screen(self, name: str):
        self._screen_name = name
        if name == "face":
            self._face.set_emotion("idle")

    def _on_game_select(self, game: str):
        self._set_screen(game)

    def _back_to_menu(self):
        self._set_screen("game_menu")

    def _handle_touch(self, pos: tuple):
        if self._screen_name == "game_menu":
            self._game_menu.handle_touch(pos)
        elif self._screen_name == "tictactoe":
            self._ttt.handle_touch(pos)
        elif self._screen_name == "snake":
            self._snake.handle_touch(pos)
        elif self._screen_name == "face":
            # Tap face → open game menu
            self._set_screen("game_menu")

    def _get_touch_pos(self, event) -> tuple:
        if event.type == pygame.FINGERDOWN:
            return (int(event.x * SCREEN_W), int(event.y * SCREEN_H))
        return event.pos

    # ──────────────────────────────────────────
    # Draw dispatch
    # ──────────────────────────────────────────

    def _draw(self):
        if self._screen_name == "face":
            self._face.update_and_draw()
        elif self._screen_name == "game_menu":
            self._game_menu.draw()
        elif self._screen_name == "tictactoe":
            self._ttt.update_and_draw()
        elif self._screen_name == "snake":
            self._snake.update_and_draw()

    # ──────────────────────────────────────────
    # IPC socket (Unix domain socket)
    # ──────────────────────────────────────────

    def _start_socket_listener(self):
        # Remove old socket file if it exists
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass

        self._sock_thread = threading.Thread(
            target=self._socket_listener, daemon=True)
        self._sock_thread.start()

    def _socket_listener(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        srv.listen(1)
        srv.settimeout(1.0)
        log.info("Display socket listening at %s", SOCKET_PATH)

        while self._running:
            try:
                conn, _ = srv.accept()
                self._brain_conn = conn
                buf = ""
                while self._running:
                    try:
                        data = conn.recv(1024).decode("utf-8", errors="ignore")
                        if not data:
                            break
                        buf += data
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            line = line.strip()
                            if line:
                                try:
                                    msg = json.loads(line)
                                    with self._msg_lock:
                                        self._msg_queue.append(msg)
                                except json.JSONDecodeError:
                                    pass
                    except (socket.timeout, OSError):
                        break
                conn.close()
                self._brain_conn = None
            except socket.timeout:
                pass

        srv.close()

    def _process_messages(self):
        with self._msg_lock:
            msgs = self._msg_queue[:]
            self._msg_queue.clear()

        for msg in msgs:
            t = msg.get("type")
            if t == "emotion":
                self._face.set_emotion(
                    msg.get("name", "idle"),
                    msg.get("speed", 3.0),
                )
            elif t == "subtitle":
                self._face.set_subtitle(
                    msg.get("text", ""),
                    msg.get("duration", 4.0),
                )
            elif t == "screen":
                self._set_screen(msg.get("name", "face"))

    def _send_to_brain(self, data: dict):
        if self._brain_conn:
            try:
                self._brain_conn.send(
                    (json.dumps(data) + "\n").encode())
            except OSError:
                pass

    def _cleanup_socket(self):
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass


# ──────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    display = BobDisplay()
    display.run()
