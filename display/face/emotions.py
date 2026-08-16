"""
BOB Display — Emotion Definitions
Visual parameters for each of BOB's emotional states.
Works with the goggle-character face_renderer.py.
"""

from dataclasses import dataclass
from typing import Tuple

# ── Colour Palette ──────────────────────────────────────────────────────────
C_FACE_YELLOW   = (255, 210,  20)
C_FACE_SHADOW   = (220, 175,   0)

C_GOGGLE_RING   = (165, 162, 155)   # silver metallic
C_GOGGLE_RING_D = ( 90,  86,  80)   # dark shadow on ring
C_GOGGLE_BAND   = ( 75,  48,  18)   # brown leather strap
C_GOGGLE_LENS   = (228, 242, 255)   # near-clear lens tint

C_EYE_WHITE     = (245, 248, 255)
C_IRIS_BROWN    = (118,  68,  28)
C_IRIS_BROWN_L  = (162, 108,  48)
C_PUPIL         = ( 12,   8,   5)
C_PUPIL_HL      = (255, 255, 255)

C_MOUTH_DARK    = ( 28,  10,   4)
C_TEETH         = (244, 244, 239)
C_TEETH_LINE    = (198, 192, 180)
C_TONGUE        = (218,  76,  76)
C_LIP           = (198, 152,   8)

C_BG_DARK       = ( 14,  16,  22)
C_BG_ALERT      = ( 26,   6,   6)

C_ACCENT        = (255, 210,  20)
C_STATUS_TEXT   = (200, 178,  98)


@dataclass
class EmotionParams:
    name:           str

    # Eye openness
    eye_open:       float = 1.0    # 0=fully closed, 1=fully open
    eye_squeeze:    float = 0.0    # squint inward (happy squint)

    # Pupil placement
    pupil_x_off:    float = 0.0    # -1 left … +1 right (relative to iris r)
    pupil_y_off:    float = 0.0    # -1 up  … +1 down
    pupil_size:     float = 0.52   # relative to iris radius

    # Derp: right eye pupil drifts inward/independently
    derp_factor:    float = 0.0    # 0=straight, 1=maximum derp

    # Goggle hardware colour
    ring_color:     Tuple = C_GOGGLE_RING
    band_color:     Tuple = C_GOGGLE_BAND

    # Mouth
    mouth_curve:    float = 0.50   # 0=flat line, 1=huge smile, -1=frown
    mouth_width:    float = 0.62   # relative to face width
    mouth_open:     float = 0.35   # tooth gap height factor
    teeth_count:    int   = 6
    show_tongue:    bool  = False

    # Whole-face
    face_squish:    float = 1.0
    bg_color:       Tuple = C_BG_DARK
    face_color:     Tuple = C_FACE_YELLOW

    # Animation feel
    blink_rate:     float = 3.5    # avg blinks per minute
    idle_drift:     float = 1.0    # pupil drift amplitude
    wobble:         float = 0.0    # head side-wobble amplitude


EMOTIONS: dict[str, EmotionParams] = {

    # ── Default resting face — slight derp, friendly grin ──────────────────
    "idle": EmotionParams(
        name        = "idle",
        eye_open    = 1.0,
        pupil_size  = 0.50,
        derp_factor = 0.18,     # a little cross-eyed by default
        mouth_curve = 0.48,
        mouth_open  = 0.30,
        teeth_count = 6,
        blink_rate  = 3.5,
        idle_drift  = 1.2,
    ),

    # ── Happy — squinting eyes, huge toothy grin, head wobble ──────────────
    "happy": EmotionParams(
        name        = "happy",
        eye_open    = 0.65,
        eye_squeeze = 0.14,
        pupil_size  = 0.42,
        derp_factor = 0.05,
        mouth_curve = 0.92,
        mouth_width = 0.74,
        mouth_open  = 0.46,
        teeth_count = 8,
        wobble      = 0.7,
        blink_rate  = 6.5,
        idle_drift  = 0.4,
    ),

    # ── Listening — wide eyes, attentive, pupils up ─────────────────────────
    "listening": EmotionParams(
        name        = "listening",
        eye_open    = 1.18,
        pupil_size  = 0.56,
        pupil_y_off = -0.12,
        derp_factor = 0.06,
        mouth_curve = 0.22,
        mouth_open  = 0.14,
        teeth_count = 4,
        blink_rate  = 1.8,
        idle_drift  = 0.25,
    ),

    # ── Thinking — half-closed, pupils to the side, extra derpy ────────────
    "thinking": EmotionParams(
        name        = "thinking",
        eye_open    = 0.52,
        pupil_x_off = 0.42,
        pupil_y_off = -0.20,
        pupil_size  = 0.42,
        derp_factor = 0.55,
        mouth_curve = 0.12,
        mouth_open  = 0.08,
        teeth_count = 2,
        blink_rate  = 1.0,
        idle_drift  = 0.85,
    ),

    # ── Speaking — mouth animates open/close ────────────────────────────────
    "speaking": EmotionParams(
        name        = "speaking",
        eye_open    = 0.98,
        pupil_size  = 0.50,
        derp_factor = 0.10,
        mouth_curve = 0.55,
        mouth_width = 0.66,
        mouth_open  = 0.40,
        teeth_count = 6,
        blink_rate  = 3.0,
        idle_drift  = 0.5,
    ),

    # ── Alert / E-stop — huge alarmed eyes, red rings, frown ───────────────
    "alert": EmotionParams(
        name        = "alert",
        eye_open    = 1.32,
        pupil_size  = 0.60,
        pupil_y_off =  0.10,
        derp_factor = 0.0,
        ring_color  = (200, 75, 55),
        mouth_curve = -0.35,
        mouth_width = 0.52,
        mouth_open  = 0.10,
        teeth_count = 4,
        bg_color    = C_BG_ALERT,
        blink_rate  = 11.0,
        wobble      = 1.3,
        idle_drift  = 0.08,
    ),

    # ── Sleeping — almost-closed eyes, tiny smile ───────────────────────────
    "sleeping": EmotionParams(
        name        = "sleeping",
        eye_open    = 0.05,
        pupil_size  = 0.20,
        derp_factor = 0.0,
        mouth_curve = 0.18,
        mouth_open  = 0.06,
        teeth_count = 2,
        blink_rate  = 0.15,
        idle_drift  = 0.04,
        wobble      = 0.0,
    ),

    # ── Surprised — comically giant eyes, wide-open mouth, tongue ──────────
    "surprised": EmotionParams(
        name        = "surprised",
        eye_open    = 1.42,
        pupil_size  = 0.62,
        derp_factor = 0.22,
        mouth_curve = 0.02,
        mouth_width = 0.52,
        mouth_open  = 0.56,
        teeth_count = 6,
        show_tongue = True,
        face_squish = 1.10,
        blink_rate  = 13.0,
        wobble      = 0.9,
        idle_drift  = 0.3,
    ),
}


def get_emotion(name: str) -> EmotionParams:
    return EMOTIONS.get(name, EMOTIONS["idle"])
