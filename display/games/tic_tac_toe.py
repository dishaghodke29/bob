"""
BOB Display — Tic-Tac-Toe vs AI (Minimax with alpha-beta pruning)
Touchscreen-native: tap a cell to play. AI plays as O.
"""

import math
import time
from typing import Callable, Optional

import pygame

C_BG     = (10,  12,  20)
C_GRID   = (0,  120, 220)
C_X      = (255,  80,  80)
C_O      = (80,  200, 120)
C_TIE    = (180, 180, 180)
C_TEXT   = (200, 220, 255)
C_ACCENT = (0,  160, 255)
C_WIN    = (255, 220,  40)
C_BTN    = (30,  50, 100)


class TicTacToe:
    W, H      = 1024, 600
    CELL      = 130
    GRID_COLS = 3
    GRID_ROWS = 3
    AI_DELAY  = 0.4    # seconds before AI moves (feels more natural)

    def __init__(self, screen: pygame.Surface, on_exit: Callable[[], None]):
        self._screen   = screen
        self._on_exit  = on_exit
        self._font_big  = pygame.font.SysFont("monospace", 72, bold=True)
        self._font_med  = pygame.font.SysFont("monospace", 32, bold=True)
        self._font_sm   = pygame.font.SysFont("monospace", 20)

        # Grid origin (centred)
        self._ox = (self.W - self.CELL * 3) // 2
        self._oy = (self.H - self.CELL * 3) // 2 + 20

        self._reset()

    # ── Public ────────────────────────────────────────────────────────────────

    def update_and_draw(self):
        now = time.monotonic()

        # AI move after delay
        if (self._ai_pending and not self._game_over and
                now - self._ai_timer >= self.AI_DELAY):
            self._ai_pending = False
            self._do_ai_move()

        self._draw()

    def handle_touch(self, pos: tuple):
        if self._game_over:
            # Tap anywhere to restart
            self._reset()
            return

        # Back button
        if self._back_rect.collidepoint(pos):
            self._on_exit()
            return

        if not self._player_turn or self._ai_pending:
            return

        # Map touch to cell
        col = (pos[0] - self._ox) // self.CELL
        row = (pos[1] - self._oy) // self.CELL
        if 0 <= col < 3 and 0 <= row < 3:
            if self._board[row][col] == 0:
                self._board[row][col] = 1   # Human = 1 (X)
                self._player_turn = False
                if not self._check_end():
                    self._ai_pending = True
                    self._ai_timer   = time.monotonic()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _reset(self):
        self._board       = [[0] * 3 for _ in range(3)]
        self._player_turn = True
        self._game_over   = False
        self._winner      = None   # 1=human, -1=AI, 0=tie
        self._win_line    = None
        self._ai_pending  = False
        self._ai_timer    = 0.0
        self._back_rect   = pygame.Rect(20, self.H - 55, 120, 40)

    def _do_ai_move(self):
        best_score = -math.inf
        best_move  = None
        for r in range(3):
            for c in range(3):
                if self._board[r][c] == 0:
                    self._board[r][c] = -1
                    score = self._minimax(0, False, -math.inf, math.inf)
                    self._board[r][c] = 0
                    if score > best_score:
                        best_score = score
                        best_move  = (r, c)
        if best_move:
            self._board[best_move[0]][best_move[1]] = -1
        self._player_turn = True
        self._check_end()

    def _minimax(self, depth: int, is_max: bool, alpha: float, beta: float) -> float:
        w = self._eval_board()
        if w != 0 or depth == 9:
            return w

        if is_max:
            best = -math.inf
            for r in range(3):
                for c in range(3):
                    if self._board[r][c] == 0:
                        self._board[r][c] = -1
                        best = max(best, self._minimax(depth+1, False, alpha, beta))
                        self._board[r][c] = 0
                        alpha = max(alpha, best)
                        if beta <= alpha:
                            return best
            return best
        else:
            best = math.inf
            for r in range(3):
                for c in range(3):
                    if self._board[r][c] == 0:
                        self._board[r][c] = 1
                        best = min(best, self._minimax(depth+1, True, alpha, beta))
                        self._board[r][c] = 0
                        beta = min(beta, best)
                        if beta <= alpha:
                            return best
            return best

    def _eval_board(self) -> float:
        lines = (
            *[self._board[r] for r in range(3)],
            *[[self._board[r][c] for r in range(3)] for c in range(3)],
            [self._board[i][i]   for i in range(3)],
            [self._board[i][2-i] for i in range(3)],
        )
        for line in lines:
            s = sum(line)
            if s ==  3: return  1.0
            if s == -3: return -1.0
        return 0.0

    def _check_end(self) -> bool:
        # Check rows, cols, diags
        lines = [
            *[((r,0),(r,1),(r,2)) for r in range(3)],
            *[((0,c),(1,c),(2,c)) for c in range(3)],
            ((0,0),(1,1),(2,2)),
            ((0,2),(1,1),(2,0)),
        ]
        for line in lines:
            vals = [self._board[r][c] for r, c in line]
            if abs(sum(vals)) == 3:
                self._winner   = vals[0]
                self._win_line = line
                self._game_over = True
                return True

        # Check tie
        if all(self._board[r][c] != 0 for r in range(3) for c in range(3)):
            self._winner    = 0
            self._game_over = True
            return True
        return False

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self):
        self._screen.fill(C_BG)

        # Title
        title = self._font_sm.render("TIC-TAC-TOE  —  You: X    BOB: O", True, C_ACCENT)
        self._screen.blit(title, ((self.W - title.get_width()) // 2, 12))

        # Grid lines
        for i in range(1, 3):
            x = self._ox + i * self.CELL
            y = self._oy + i * self.CELL
            pygame.draw.line(self._screen, C_GRID,
                             (x, self._oy), (x, self._oy + 3*self.CELL), 3)
            pygame.draw.line(self._screen, C_GRID,
                             (self._ox, y), (self._ox + 3*self.CELL, y), 3)

        # Pieces
        for r in range(3):
            for c in range(3):
                cx = self._ox + c * self.CELL + self.CELL // 2
                cy = self._oy + r * self.CELL + self.CELL // 2
                v  = self._board[r][c]
                if v == 1:
                    self._draw_x(cx, cy)
                elif v == -1:
                    self._draw_o(cx, cy)

        # Win line
        if self._win_line:
            pts = [(self._ox + c*self.CELL + self.CELL//2,
                    self._oy + r*self.CELL + self.CELL//2)
                   for r, c in self._win_line]
            pygame.draw.line(self._screen, C_WIN, pts[0], pts[2], 6)

        # Status
        if self._game_over:
            if self._winner == 1:
                msg, col = "YOU WIN! 🎉", C_O
            elif self._winner == -1:
                msg, col = "BOB WINS!", C_X
            else:
                msg, col = "IT'S A TIE!", C_TIE
            surf = self._font_med.render(msg, True, col)
            bx = (self.W - surf.get_width()) // 2
            pygame.draw.rect(self._screen, (20, 25, 45),
                (bx - 20, self.H - 90, surf.get_width() + 40, 50), border_radius=10)
            self._screen.blit(surf, (bx, self.H - 85))
            hint = self._font_sm.render("Tap anywhere to play again", True, C_TEXT)
            self._screen.blit(hint, ((self.W - hint.get_width()) // 2, self.H - 40))
        else:
            turn_msg = "Your turn (X)" if self._player_turn else "BOB is thinking..."
            col      = C_O if self._player_turn else C_X
            surf     = self._font_sm.render(turn_msg, True, col)
            self._screen.blit(surf, ((self.W - surf.get_width()) // 2, self.H - 40))

        # Back button
        pygame.draw.rect(self._screen, C_BTN, self._back_rect, border_radius=8)
        back_surf = self._font_sm.render("← Menu", True, C_TEXT)
        self._screen.blit(back_surf, (self._back_rect.x + 10,
                                      self._back_rect.y + 10))

    def _draw_x(self, cx: int, cy: int):
        pad = 28
        pygame.draw.line(self._screen, C_X,
                         (cx-pad, cy-pad), (cx+pad, cy+pad), 6)
        pygame.draw.line(self._screen, C_X,
                         (cx+pad, cy-pad), (cx-pad, cy+pad), 6)

    def _draw_o(self, cx: int, cy: int):
        pygame.draw.circle(self._screen, C_O, (cx, cy), 38, 6)
