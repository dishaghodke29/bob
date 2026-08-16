"""
BOB — Motion Detection + Security Module
Watches the EMEET C960 camera for motion using OpenCV background subtraction.
On motion detected:
  • Sends Telegram notification with a snapshot photo
  • Saves event to log
  • Notifies brain state machine

Also provides the lightweight MJPEG stream at reduced resolution/FPS
to save CPU.
"""

import asyncio
import io
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("security")

# ── Config ────────────────────────────────────────────────────────────────────
CAMERA_DEVICE      = 0           # /dev/video0 — EMEET C960
STREAM_WIDTH       = 320
STREAM_HEIGHT      = 240
STREAM_FPS         = 10
STREAM_JPEG_Q      = 45          # JPEG quality (0-100), lower = less CPU

MOTION_THRESHOLD   = 3500        # contour area px² to count as motion
MOTION_COOLDOWN    = 8.0         # seconds between repeated alerts
SNAPSHOT_DIR       = Path("/home/arduino/bob/logs/snapshots")

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False
    log.warning("OpenCV not available — security camera disabled")


class SecurityCamera:
    def __init__(self, on_motion: Optional[Callable] = None):
        self._on_motion    = on_motion   # async callback(frame_bytes)
        self._cap          = None
        self._running      = False
        self._last_alert   = 0.0
        self._bg_sub       = None
        self._latest_frame: Optional[bytes] = None   # latest JPEG bytes
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────
    # Public
    # ──────────────────────────────────────────

    async def start(self) -> bool:
        if not CV2_OK:
            return False
        loop = asyncio.get_event_loop()
        ok   = await loop.run_in_executor(None, self._open_camera)
        if ok:
            self._running = True
            asyncio.create_task(self._camera_loop())
            log.info("Security camera started (%dx%d @ %dfps)",
                     STREAM_WIDTH, STREAM_HEIGHT, STREAM_FPS)
        return ok

    async def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()

    def get_latest_frame(self) -> Optional[bytes]:
        """Returns latest JPEG frame bytes for MJPEG stream."""
        return self._latest_frame

    # ──────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────

    def _open_camera(self) -> bool:
        try:
            cap = cv2.VideoCapture(CAMERA_DEVICE)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  STREAM_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STREAM_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS,          STREAM_FPS)
            cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)   # minimal buffer lag
            if not cap.isOpened():
                return False
            self._cap    = cap
            self._bg_sub = cv2.createBackgroundSubtractorMOG2(
                history=200, varThreshold=40, detectShadows=False)
            return True
        except Exception as e:
            log.error("Camera open error: %s", e)
            return False

    async def _camera_loop(self):
        loop     = asyncio.get_event_loop()
        interval = 1.0 / STREAM_FPS

        while self._running:
            t0 = time.monotonic()

            # Read frame in executor (blocking I/O)
            frame = await loop.run_in_executor(None, self._read_frame)

            if frame is not None:
                # Motion detection
                self._check_motion(frame)

                # Encode to JPEG
                jpeg = await loop.run_in_executor(None, self._encode_jpeg, frame)
                self._latest_frame = jpeg

            # Rate limit
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, interval - elapsed))

    def _read_frame(self):
        if not self._cap or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def _encode_jpeg(self, frame) -> bytes:
        _, buf = cv2.imencode('.jpg', frame,
                              [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_Q])
        return bytes(buf)

    def _check_motion(self, frame):
        if self._bg_sub is None:
            return

        now = time.monotonic()
        if now - self._last_alert < MOTION_COOLDOWN:
            return

        # Apply background subtraction
        fg_mask = self._bg_sub.apply(frame)

        # Morphological cleanup
        kernel  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN,  kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        # Find contours
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        motion_area = sum(cv2.contourArea(c) for c in contours)

        if motion_area > MOTION_THRESHOLD:
            self._last_alert = now
            log.warning("MOTION DETECTED — area=%.0fpx²", motion_area)

            # Draw bounding boxes on snapshot
            snap = frame.copy()
            for c in contours:
                if cv2.contourArea(c) > 500:
                    x, y, w, h = cv2.boundingRect(c)
                    cv2.rectangle(snap, (x, y), (x+w, y+h), (0, 255, 100), 2)

            # Add timestamp overlay
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(snap, f"MOTION {ts}", (5, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1)

            # Save snapshot
            snap_path = SNAPSHOT_DIR / f"motion_{int(now)}.jpg"
            cv2.imwrite(str(snap_path), snap,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])

            # Encode snapshot for Telegram
            _, buf = cv2.imencode('.jpg', snap, [cv2.IMWRITE_JPEG_QUALITY, 80])
            snap_bytes = bytes(buf)

            # Fire async callback
            if self._on_motion:
                asyncio.create_task(self._on_motion(snap_bytes, motion_area))

    def generate_mjpeg(self):
        """Sync generator yielding MJPEG boundary frames — used by FastAPI StreamingResponse."""
        while self._running:
            frame = self._latest_frame
            if frame:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" +
                       frame + b"\r\n")
            time.sleep(1.0 / STREAM_FPS)
