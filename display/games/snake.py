"""
BOB Display — Snake Game
Classic snake with touchscreen swipe controls on the 7" display.
"""

import random
import time
from typing import Callable

import pygame

C_BG      = (10,  12,  20)
C_GRID    = (20,  26,  40)
C_SNAKE_H = (0,  220, 160)
C_SNAKE_B = (0,  160, 120)
C_FOOD    = (255, 80,  80)
C_TEXT    = (200, 220, 255)
C_ACCENT  = (0,  160, 255)
C_BTN     = (30,  50, 100)

CELL = 32
COLS = 28
ROWS = 16
OX   = (1024 - COLS * CELL) // 2
OY   = (600  - ROWS * CELL) // 2 + 10


class Snake:
    def __init__(self, screen: pygame.Surface, on_exit: Callable[[], None]):
        self._screen  = screen
        self._on_exit = on_exit
        self._font_big = pygame.font.SysFont("monospace", 64, bold=True)
        self._font_med = pygame.font.SysFont("monospace", 28, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 18)
        self._back_rect = pygame.Rect(20, 600 - 55, 120, 40)

        # Touch swipe tracking
        self._touch_start = None

        self._reset()

    # ── Public ────────────────────────────────────────────────────────────────

    def update_and_draw(self):
        now = time.monotonic()
        if not self._game_over and now - self._last_move >= self._speed:
            self._last_move = now
            self._step()
        self._draw()

    def handle_touch(self, pos: tuple):
        if self._back_rect.collidepoint(pos):
            self._on_exit()
            return

        if self._game_over:
            self._reset()
            return

        # Swipe detection: store touch start
        if self._touch_start is None:
            self._touch_start = pos
        else:
            dx = pos[0] - self._touch_start[0]
            dy = pos[1] - self._touch_start[1]
            self._touch_start = None

            if abs(dx) > abs(dy):
                if dx > 20  and self._dir != (-1, 0): self._next_dir = (1, 0)
                elif dx < -20 and self._dir != (1, 0): self._next_dir = (-1, 0)
            else:
                if dy > 20  and self._dir != (0, -1): self._next_dir = (0, 1)
                elif dy < -20 and self._dir != (0, 1):  self._next_dir = (0, -1)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _reset(self):
        mid_c, mid_r = COLS // 2, ROWS // 2
        self._snake    = [(mid_c, mid_r), (mid_c-1, mid_r), (mid_c-2, mid_r)]
        self._dir      = (1, 0)
        self._next_dir = (1, 0)
        self._food     = self._spawn_food()
        self._score    = 0
        self._game_over = False
        self._last_move = time.monotonic()
        self._speed    = 0.18   # seconds per step
        self._touch_start = None

    def _spawn_food(self) -> tuple:
        while True:
            pos = (random.randint(0, COLS-1), random.randint(0, ROWS-1))
            if pos not in self._snake:
                return pos

    def _step(self):
        self._dir = self._next_dir
        head = (self._snake[0][0] + self._dir[0],
                self._snake[0][1] + self._dir[1])

        # Wall collision
        if not (0 <= head[0] < COLS and 0 <= head[1] < ROWS):
            self._game_over = True
            return

        # Self collision
        if head in self._snake:
            self._game_over = True
            return

        self._snake.insert(0, head)

        if head == self._food:
            self._score += 10
            self._food   = self._spawn_food()
            # Speed up every 50 points
            self._speed  = max(0.07, self._speed - 0.005)
        else:
            self._snake.pop()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self):
        self._screen.fill(C_BG)

        # Title + score
        title = self._font_sm.render("SNAKE", True, C_ACCENT)
        score = self._font_sm.render(f"Score: {self._score}", True, C_TEXT)
        self._screen.blit(title, (OX, 8))
        self._screen.blit(score, (OX + COLS * CELL - score.get_width(), 8))

        # Grid background
        grid_rect = pygame.Rect(OX, OY, COLS * CELL, ROWS * CELL)
        pygame.draw.rect(self._screen, C_GRID, grid_rect, border_radius=4)

        # Food
        fx = OX + self._food[0] * CELL + CELL // 2
        fy = OY + self._food[1] * CELL + CELL // 2
        pygame.draw.circle(self._screen, C_FOOD, (fx, fy), CELL // 2 - 3)

        # Snake
        for i, (sc, sr) in enumerate(self._snake):
            sx = OX + sc * CELL + 2
            sy = OY + sr * CELL + 2
            col = C_SNAKE_H if i == 0 else C_SNAKE_B
            pygame.draw.rect(self._screen, col,
                             (sx, sy, CELL - 4, CELL - 4),
                             border_radius=5)

        # Game over overlay
        if self._game_over:
            ov = pygame.Surface((1024, 600), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 160))
            self._screen.blit(ov, (0, 0))

            go = self._font_med.render("GAME OVER", True, C_FOOD)
            sc = self._font_sm.render(f"Score: {self._score}  —  Tap to restart", True, C_TEXT)
            self._screen.blit(go, ((1024 - go.get_width()) // 2, 220))
            self._screen.blit(sc, ((1024 - sc.get_width()) // 2, 280))

        # Back button
        pygame.draw.rect(self._screen, C_BTN, self._back_rect, border_radius=8)
        back = self._font_sm.render("← Menu", True, C_TEXT)
        self._screen.blit(back, (self._back_rect.x + 10, self._back_rect.y + 10))

        # Controls hint
        hint = self._font_sm.render("Swipe to steer", True, (80, 100, 130))
        self._screen.blit(hint, (OX + COLS * CELL - hint.get_width(), 600 - 30))
