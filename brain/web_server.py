"""
web_server.py — BOB Robot FastAPI Web Dashboard Server
=======================================================
Serves the web dashboard at http://0.0.0.0:8000
Dashboard static files : /home/arduino/bob/dashboard/
WebSocket endpoint     : /ws   (bidirectional JSON)
Status API             : /api/status
Camera MJPEG stream    : /video_feed (EMEET C960 @ /dev/video0)
Platform               : Debian Linux arm64 (Arduino UNO Q)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# ──────────────────────────── Optional cv2 ─────────────────────────────────────
try:
    import cv2
    _HAS_CV2 = True
    logger.debug("OpenCV (cv2) available — camera stream enabled.")
except ImportError:
    cv2 = None  # type: ignore
    _HAS_CV2 = False
    logger.warning(
        "OpenCV (cv2) not installed — /video_feed will return 404. "
        "Install with: pip install opencv-python-headless"
    )

# ──────────────────────────── FastAPI / Uvicorn ────────────────────────────────
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ──────────────────────────── Constants ────────────────────────────────────────
HOST              = "0.0.0.0"
PORT              = 8000
DASHBOARD_DIR     = Path("/home/arduino/bob/dashboard")
CAMERA_DEVICE     = 2           # /dev/video2 — EMEET C960
CAMERA_WIDTH      = 640
CAMERA_HEIGHT     = 480
CAMERA_FPS        = 15          # 15fps saves CPU vs 20fps
JPEG_QUALITY      = 65
FRAME_INTERVAL    = 1.0 / CAMERA_FPS


# ═══════════════════════════════════════════════════════════════════════════════
class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.add(ws)
        logger.info("WebSocket client connected. Total: %d", len(self._active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._active.discard(ws)
        logger.info("WebSocket client disconnected. Total: %d", len(self._active))

    async def broadcast(self, message: dict) -> None:
        """Send *message* as JSON to all connected WebSocket clients."""
        if not self._active:
            return
        payload = json.dumps(message)
        dead: Set[WebSocket] = set()
        async with self._lock:
            clients = set(self._active)

        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("Failed to send to WebSocket client: %s", exc)
                dead.add(ws)

        if dead:
            async with self._lock:
                self._active -= dead
            logger.info(
                "Removed %d dead WebSocket connection(s). Remaining: %d",
                len(dead), len(self._active),
            )


# ═══════════════════════════════════════════════════════════════════════════════
class CameraThread(threading.Thread):
    """
    Background daemon thread that continuously captures frames from the EMEET
    C960 USB camera (/dev/video0) using OpenCV and stores the latest JPEG bytes
    in a thread-safe slot for the MJPEG streaming endpoint.
    """

    def __init__(self) -> None:
        super().__init__(name="camera-thread", daemon=True)
        self._latest_frame: Optional[bytes] = None
        self._lock = threading.Lock()
        self._running = False
        self._encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY] if _HAS_CV2 else []

    @property
    def latest_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_frame

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        if not _HAS_CV2:
            logger.warning("CameraThread: OpenCV not available — thread exiting.")
            return

        # Try configured device first, then auto-scan 0..4
        device = CAMERA_DEVICE
        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            logger.warning("CameraThread: /dev/video%d failed — scanning…", device)
            cap = None
            for idx in range(5):
                if idx == device:
                    continue
                test = cv2.VideoCapture(idx)
                if test.isOpened():
                    cap = test
                    device = idx
                    logger.info("CameraThread: found camera at /dev/video%d", idx)
                    break
            if cap is None:
                logger.error("CameraThread: no camera found on /dev/video0-4")
                return
        logger.info("CameraThread: opened /dev/video%d", device)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        logger.info(
            "CameraThread: capturing at %dx%d @ %d fps",
            CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS,
        )

        self._running = True
        try:
            while self._running:
                t0 = time.monotonic()
                ret, frame = cap.read()
                if not ret:
                    logger.warning("CameraThread: failed to read frame — retrying …")
                    time.sleep(0.1)
                    continue

                ok, jpeg_buf = cv2.imencode(".jpg", frame, self._encode_params)
                if ok:
                    with self._lock:
                        self._latest_frame = jpeg_buf.tobytes()

                elapsed = time.monotonic() - t0
                sleep_t = FRAME_INTERVAL - elapsed
                if sleep_t > 0:
                    time.sleep(sleep_t)
        finally:
            cap.release()
            logger.info("CameraThread: camera released.")


# ═══════════════════════════════════════════════════════════════════════════════
class WebServer:
    """
    FastAPI-based web server for BOB's dashboard.

    Usage::

        server = WebServer()
        server.set_brain(brain)
        await server.start()   # blocks (runs uvicorn)
    """

    def __init__(self) -> None:
        self._brain = None
        self._manager = ConnectionManager()
        self._camera = CameraThread() if _HAS_CV2 else None
        self._app = self._build_app()

    # ─────────────────────────── Public API ────────────────────────────────────

    def set_brain(self, brain: Any) -> None:
        """Wire up the brain reference so WebSocket commands can reach it."""
        self._brain = brain
        logger.info("WebServer: brain reference set (%s).", type(brain).__name__)

    async def broadcast(self, msg: dict) -> None:
        """Send *msg* JSON to all connected WebSocket clients."""
        await self._manager.broadcast(msg)

    async def start(self) -> None:
        """
        Start the camera capture thread and then run uvicorn on 0.0.0.0:8000.
        This method blocks until the server shuts down.
        """
        if self._camera is not None:
            self._camera.start()
            logger.info("Camera capture thread started.")

        logger.info("Starting uvicorn on %s:%d …", HOST, PORT)
        config = uvicorn.Config(
            app=self._app,
            host=HOST,
            port=PORT,
            log_level="info",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        await server.serve()

    # ─────────────────────────── App builder ───────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(
            title="BOB Robot Dashboard",
            description="Web dashboard and control API for the BOB autonomous robot.",
            version="1.0.0",
        )

        # ── CORS (allow all origins for local LAN access) ─────────────────────
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── Static files (/static → dashboard dir) ────────────────────────────
        if DASHBOARD_DIR.exists():
            app.mount(
                "/static",
                StaticFiles(directory=str(DASHBOARD_DIR)),
                name="static",
            )
            logger.info("Static files mounted from %s", DASHBOARD_DIR)
        else:
            logger.warning(
                "Dashboard directory %s does not exist — /static not mounted.",
                DASHBOARD_DIR,
            )

        # ── Route: GET / ──────────────────────────────────────────────────────
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def serve_index() -> FileResponse:
            index_path = DASHBOARD_DIR / "index.html"
            if not index_path.exists():
                logger.error("index.html not found at %s", index_path)
                raise HTTPException(
                    status_code=404,
                    detail=f"Dashboard index.html not found at {index_path}",
                )
            return FileResponse(str(index_path))

        # ── Route: GET /api/status ─────────────────────────────────────────────
        @app.get("/api/status")
        async def api_status() -> JSONResponse:
            status: Dict[str, Any] = {
                "online": True,
                "timestamp": time.time(),
                "brain_state": "unknown",
                "telemetry": {},
                "obstacle_distance_cm": None,
            }

            if self._brain is not None:
                try:
                    if hasattr(self._brain, "state"):
                        status["brain_state"] = str(self._brain.state)
                    if hasattr(self._brain, "telemetry"):
                        status["telemetry"] = self._brain.telemetry
                    if hasattr(self._brain, "obstacle_distance"):
                        status["obstacle_distance_cm"] = self._brain.obstacle_distance
                except Exception as exc:
                    logger.warning("Error reading brain state for /api/status: %s", exc)

            return JSONResponse(content=status)

        # ── Route: WebSocket /ws ───────────────────────────────────────────────
        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket) -> None:
            await self._manager.connect(websocket)
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        cmd = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("WebSocket: received non-JSON message: %r", raw)
                        await websocket.send_text(
                            json.dumps({"error": "invalid JSON", "received": raw})
                        )
                        continue

                    logger.debug("WebSocket command received: %s", cmd)

                    if self._brain is not None and hasattr(self._brain, "handle_web_command"):
                        try:
                            await self._brain.handle_web_command(cmd)
                        except Exception as exc:
                            logger.error(
                                "brain.handle_web_command() raised: %s", exc, exc_info=True
                            )
                            await websocket.send_text(
                                json.dumps({"error": "command execution failed", "detail": str(exc)})
                            )
                    else:
                        logger.warning(
                            "WebSocket command dropped — brain not set or "
                            "handle_web_command() not available."
                        )
                        await websocket.send_text(
                            json.dumps({"error": "brain not available"})
                        )
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                logger.error("WebSocket error: %s", exc, exc_info=True)
            finally:
                await self._manager.disconnect(websocket)

        # ── Route: GET /video_feed (MJPEG) ────────────────────────────────────
        @app.get("/video_feed")
        async def video_feed() -> StreamingResponse:
            if not _HAS_CV2 or self._camera is None:
                raise HTTPException(
                    status_code=404,
                    detail="Camera stream unavailable: OpenCV is not installed.",
                )

            return StreamingResponse(
                self._mjpeg_generator(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

        return app

    # ─────────────────────────── MJPEG generator ───────────────────────────────

    async def _mjpeg_generator(self):
        """
        Async generator that yields MJPEG frames from the camera thread.
        Clients can consume this as a standard browser <img src="/video_feed">.
        """
        loop = asyncio.get_running_loop()
        last_frame: Optional[bytes] = None

        while True:
            frame = self._camera.latest_frame  # thread-safe property

            if frame is None:
                # Camera not yet ready — send a small delay and retry
                await asyncio.sleep(0.05)
                continue

            # Avoid re-sending the identical frame (saves bandwidth)
            if frame is not last_frame:
                last_frame = frame
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )

            await asyncio.sleep(FRAME_INTERVAL)


# ──────────────────────────── Quick self-test ──────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    class _MockBrain:
        state = "idle"
        telemetry: Dict[str, Any] = {"speed": 0, "heading": 0}
        obstacle_distance_cm: Optional[float] = 45.3

        async def handle_web_command(self, cmd: dict) -> None:
            logger.info("MockBrain received command: %s", cmd)

    async def _test() -> None:
        server = WebServer()
        server.set_brain(_MockBrain())
        await server.start()

    asyncio.run(_test())
