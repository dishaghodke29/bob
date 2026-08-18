"""
config.py — BOB Face Engine: Authentic Minion Geometry
"""

# ── Screen ────────────────────────────────────────────────────────────────────
SCREEN_W  = 1024
SCREEN_H  = 600
FPS       = 60
TITLE     = "BOB"

# ── Minion Colors ─────────────────────────────────────────────────────────────
BG_COLOR        = (255, 215,   0)   # signature minion yellow
STRAP_COLOR     = ( 25,  25,  25)   # very dark grey/black strap
GOGGLE_RIM      = (160, 160, 165)   # bright metallic silver rim
GOGGLE_RIM_DARK = (100, 100, 105)   # rim shadow
SCLERA_COLOR    = (255, 255, 255)   # eye white
IRIS_COLOR      = (101,  67,  33)   # deep brown iris
IRIS_HAPPY      = ( 80, 160,  80)
IRIS_SAD        = ( 70,  90, 160)
IRIS_ERROR      = (180,  50,  50)
PUPIL_COLOR     = ( 15,  15,  15)
SHINE_COLOR     = (255, 255, 255)
BROW_COLOR      = ( 30,  20,  10)
MOUTH_COLOR     = ( 30,  20,  10)
MOUTH_INSIDE    = (140,  30,  30)
TEETH_COLOR     = (245, 245, 235)
SUBTITLE_FG     = ( 30,  20,   0)

# ── Goggle strap geometry ─────────────────────────────────────────────────────
# Strap is much thinner now, just passing behind the giant goggles
STRAP_Y1    = 255
STRAP_Y2    = 345
STRAP_H     = STRAP_Y2 - STRAP_Y1

# ── Eye geometry ──────────────────────────────────────────────────────────────
# Eyes are huge and very close together (touching/overlapping in center)
EYE_L_CX    = 342
EYE_R_CX    = 682
EYE_CY      = 300

GOGGLE_RADIUS = 180   # massive outer ring
RIM_THICKNESS =  35   # thick silver ring
EYE_RADIUS    = GOGGLE_RADIUS - RIM_THICKNESS

# Iris / pupil sizing
IRIS_FRAC   = 0.45    # Iris size
PUPIL_FRAC  = 0.45    # Pupil is 45% of the IRIS
SHINE_FRAC  = 0.12    # Shine dot

# Eyebrow geometry (small, arched, high up on forehead)
BROW_Y_OFFSET    = -230
BROW_WIDTH       = 100
BROW_HEIGHT      = 6
BROW_CURVE       = 25

# Mouth geometry (small permanent smirk)
MOUTH_CX    = SCREEN_W // 2
MOUTH_CY    = 495
MOUTH_W     = 100
MOUTH_H     = 50

# ── Animation tuning ──────────────────────────────────────────────────────────
SMOOTH_SLOW   = 0.04
SMOOTH_MED    = 0.08
SMOOTH_FAST   = 0.15
SMOOTH_SNAP   = 0.25

BLINK_DURATION_CLOSE = 0.07
BLINK_DURATION_OPEN  = 0.10
BLINK_INTERVAL_MIN   = 2.5
BLINK_INTERVAL_MAX   = 6.0

WANDER_SPEED  = SMOOTH_SLOW
WANDER_RADIUS = 0.28

SOCKET_PATH = "/tmp/bob_display.sock"
