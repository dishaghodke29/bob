"""
socket_server.py — BOB Face Engine: Unix socket IPC server.

Runs in a background thread. Accepts newline-delimited JSON commands from
other processes (bob_brain.py, llm_agent.py, test scripts, etc.) and
enqueues them for the main pygame loop to process.

Socket path: /tmp/bob_display.sock  (same as bob_brain.py already uses)

Supported command formats:
  {"state": "happy"}
  {"type": "emotion", "name": "thinking"}
  {"type": "subtitle", "text": "Hello!", "duration": 3.0}
  {"look_at": {"x": 0.7, "y": 0.3}}

All formats are normalized to a common internal dict before queuing.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import threading

from . import config as C

log = logging.getLogger("bob_face.socket")


class SocketServer:
    """
    Thread-safe Unix socket server for face engine IPC.

    Usage:
        server = SocketServer()
        server.start()                   # spawns background thread
        ...
        cmds = server.get_commands()     # call each frame from main loop
        for cmd in cmds:
            handle(cmd)
        ...
        server.stop()
    """

    def __init__(self) -> None:
        self._queue:   queue.Queue = queue.Queue(maxsize=100)
        self._thread:  threading.Thread | None = None
        self._running: bool = False
        self._sock:    socket.socket | None = None

    def start(self) -> None:
        """Start the socket server in a daemon background thread."""
        # Remove stale socket file from previous run
        try:
            os.unlink(C.SOCKET_PATH)
        except FileNotFoundError:
            pass

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(C.SOCKET_PATH)
        self._sock.listen(8)
        self._sock.settimeout(1.0)   # so the accept() loop can check _running

        self._running = True
        self._thread  = threading.Thread(
            target    = self._accept_loop,
            daemon    = True,
            name      = "bob-face-socket",
        )
        self._thread.start()
        log.info("Socket server listening at %s", C.SOCKET_PATH)

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        try:
            os.unlink(C.SOCKET_PATH)
        except OSError:
            pass
        log.info("Socket server stopped.")

    def get_commands(self) -> list[dict]:
        """Drain and return all pending commands. Call once per frame from main loop."""
        cmds: list[dict] = []
        while True:
            try:
                cmds.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return cmds

    # ── Background threads ────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """Accept incoming connections and spawn a handler thread per client."""
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target = self._handle_client,
                args   = (conn,),
                daemon = True,
                name   = "bob-face-client",
            ).start()

    def _handle_client(self, conn: socket.socket) -> None:
        """Read newline-terminated JSON messages from one client."""
        buf = b""
        try:
            conn.settimeout(10.0)
            while self._running:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf += chunk
                # Process complete messages (split on newlines)
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        cmd = self._normalize(msg)
                        if cmd:
                            try:
                                self._queue.put_nowait(cmd)
                            except queue.Full:
                                log.warning("Command queue full — dropping message")
                    except json.JSONDecodeError as exc:
                        log.warning("Bad JSON from client: %s", exc)
        except Exception as exc:
            log.debug("Client handler error: %s", exc)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _normalize(self, msg: dict) -> dict | None:
        """
        Normalize any supported message format to a common internal command dict.

        Returns None for unrecognized/malformed messages.
        """
        if not isinstance(msg, dict):
            return None

        # Format A: {"state": "happy"}
        if "state" in msg:
            return {"cmd": "state", "state": str(msg["state"]).lower().strip()}

        # Format B: {"type": "emotion", "name": "happy"}  ← bob_brain.py format
        if msg.get("type") == "emotion" and "name" in msg:
            return {"cmd": "state", "state": str(msg["name"]).lower().strip()}

        # Format C: {"type": "subtitle", "text": "...", "duration": 3.0}
        if msg.get("type") == "subtitle" and "text" in msg:
            return {
                "cmd":      "subtitle",
                "text":     str(msg["text"]),
                "duration": float(msg.get("duration", 3.0)),
            }

        # Format D: {"look_at": {"x": 0.7, "y": 0.3}}
        if "look_at" in msg and isinstance(msg["look_at"], dict):
            la = msg["look_at"]
            return {
                "cmd": "look_at",
                "x":   float(la.get("x", 0.5)),
                "y":   float(la.get("y", 0.5)),
            }

        log.debug("Unrecognized message: %s", msg)
        return None
