"""
config.py — BOB Face Engine Constants
All geometry, colors and tuning values live here.
"""

# ── Screen ────────────────────────────────────────────────────────────────────
SCREEN_W  = 1024
SCREEN_H  = 600
FPS       = 60
TITLE     = "BOB Face"

# ── Colors ────────────────────────────────────────────────────────────────────
BG_COLOR       = (10,  13,  23)    # dark navy
FACE_COLOR     = (255, 215,   0)   # minion yellow #FFD700
FACE_SHADOW    = (200, 160,   0)   # darker yellow for shading
SCLERA_COLOR   = (255, 255, 255)   # eye white
IRIS_COLOR     = ( 30, 144, 255)   # dodger blue
IRIS_HAPPY     = ( 50, 220, 120)   # green-ish for happy
IRIS_SAD       = ( 80, 100, 180)   # desaturated blue for sad
IRIS_ERROR     = (220,  80,  80)   # reddish for error
PUPIL_COLOR    = ( 10,  10,  10)   # near-black pupil
SHINE_COLOR    = (255, 255, 255)   # eye shine
BROW_COLOR     = ( 61,  43,  31)   # dark warm brown
MOUTH_COLOR    = ( 61,  43,  31)   # same as brows
MOUTH_INSIDE   = (180,  40,  40)   # inner mouth
TEETH_COLOR    = (250, 250, 240)   # off-white teeth
SUBTITLE_BG    = ( 20,  20,  20, 180)
SUBTITLE_FG    = (255, 255, 255)
CHEEK_COLOR    = (255, 160, 100, 80)  # subtle blush (with alpha)

# ── Face geometry (1024×600) ──────────────────────────────────────────────────
FACE_CX    = SCREEN_W // 2          # 512
FACE_CY    = SCREEN_H // 2          # 300
FACE_RX    = 430                    # horizontal radius
FACE_RY    = 270                    # vertical radius

# Eye centers (landscape, two eyes side-by-side)
EYE_L_CX   = 330
EYE_L_CY   = 245
EYE_R_CX   = 694
EYE_R_CY   = 245
EYE_RADIUS = 92                     # sclera radius

# Iris / pupil sizing (fraction of EYE_RADIUS)
IRIS_FRAC  = 0.60
PUPIL_FRAC = 0.35
SHINE_FRAC = 0.10

# Eyebrow geometry (relative to eye center)
BROW_Y_OFFSET = -80                 # above eye center
BROW_WIDTH    = 130
BROW_HEIGHT   = 14                  # thickness

# Mouth geometry
MOUTH_CX   = FACE_CX
MOUTH_CY   = 435
MOUTH_W    = 220                    # full open width reference
MOUTH_H    = 80                     # full open height reference

# ── Animation tuning ──────────────────────────────────────────────────────────
# All "speed" values are per-frame lerp factors (higher = faster)
SMOOTH_SLOW   = 0.04
SMOOTH_MED    = 0.08
SMOOTH_FAST   = 0.15
SMOOTH_SNAP   = 0.25

# Blink timing (seconds)
BLINK_DURATION_CLOSE = 0.06   # seconds to fully close
BLINK_DURATION_OPEN  = 0.10   # seconds to open again
BLINK_INTERVAL_MIN   = 2.5    # minimum gap between blinks
BLINK_INTERVAL_MAX   = 6.0    # maximum gap

# Pupil wander speed
WANDER_SPEED  = SMOOTH_SLOW
WANDER_RADIUS = 0.3           # normalized max wander from center (0-1)

# Speaking mouth oscillation
SPEAK_FREQ_MIN = 2.5          # Hz
SPEAK_FREQ_MAX = 5.0

# ── Socket IPC ────────────────────────────────────────────────────────────────
SOCKET_PATH = "/tmp/bob_display.sock"
