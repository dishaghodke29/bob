"""
BOB Display — Game Menu
Touchscreen game selector shown on the 7" display.
"""

import pygame
from typing import Callable

C_BG     = (10, 12, 20)
C_PANEL  = (20, 26, 48)
C_ACCENT = (0, 160, 255)
C_TEXT   = (200, 220, 255)
C_HOVER  = (30, 80, 160)
C_BACK   = (60, 60, 80)

GAMES = [
    {"name": "Tic-Tac-Toe", "key": "tictactoe", "icon": "✕ ○"},
    {"name": "Snake",        "key": "snake",     "icon": "~●~"},
]


class GameMenu:
    W, H = 1024, 600

    def __init__(self, screen: pygame.Surface, on_select: Callable[[str], None]):
        self._screen    = screen
        self._on_select = on_select
        self._font_title = pygame.font.SysFont("monospace", 36, bold=True)
        self._font_game  = pygame.font.SysFont("monospace", 28, bold=True)
        self._font_icon  = pygame.font.SysFont("monospace", 22)
        self._font_back  = pygame.font.SysFont("monospace", 20)
        self._hovered    = None
        self._buttons    = self._build_buttons()

    def _build_buttons(self) -> list[dict]:
        buttons = []
        start_x = (self.W - (len(GAMES) * 220 + (len(GAMES) - 1) * 30)) // 2
        y = (self.H - 180) // 2
        for i, game in enumerate(GAMES):
            x = start_x + i * 250
            buttons.append({
                "rect": pygame.Rect(x, y, 220, 180),
                "game": game,
            })
        # Back button
        buttons.append({
            "rect": pygame.Rect(20, self.H - 60, 120, 40),
            "game": {"name": "Back", "key": "face", "icon": "←"},
        })
        return buttons

    def draw(self):
        self._screen.fill(C_BG)

        # Title
        title = self._font_title.render("SELECT GAME", True, C_ACCENT)
        self._screen.blit(title, ((self.W - title.get_width()) // 2, 40))

        # Divider
        pygame.draw.line(self._screen, C_ACCENT,
                         (100, 100), (self.W - 100, 100), 1)

        # Game buttons
        mx, my = pygame.mouse.get_pos()
        for btn in self._buttons:
            r    = btn["rect"]
            game = btn["game"]
            is_back = game["key"] == "face"

            hovered = r.collidepoint(mx, my)
            bg = C_HOVER if hovered else (C_BACK if is_back else C_PANEL)
            pygame.draw.rect(self._screen, bg, r, border_radius=16)
            border_col = C_ACCENT if hovered else (100, 100, 130)
            pygame.draw.rect(self._screen, border_col, r, width=2, border_radius=16)

            if not is_back:
                icon_surf = self._font_icon.render(game["icon"], True, C_ACCENT)
                self._screen.blit(icon_surf,
                    (r.centerx - icon_surf.get_width() // 2, r.y + 40))
                name_surf = self._font_game.render(game["name"], True, C_TEXT)
                self._screen.blit(name_surf,
                    (r.centerx - name_surf.get_width() // 2, r.y + 100))
            else:
                back_surf = self._font_back.render("← Back", True, C_TEXT)
                self._screen.blit(back_surf,
                    (r.centerx - back_surf.get_width() // 2,
                     r.centery - back_surf.get_height() // 2))

    def handle_touch(self, pos: tuple):
        for btn in self._buttons:
            if btn["rect"].collidepoint(pos):
                self._on_select(btn["game"]["key"])
                return
