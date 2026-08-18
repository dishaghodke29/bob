#!/usr/bin/env python3
"""
example_controller.py — Send commands to BOB's face from any Python script.

Usage:
  python3 example_controller.py

This script demonstrates how your AI system (brain.py, llm_agent.py, etc.)
can control the face engine over the Unix socket.
"""

import json
import socket
import time

SOCKET_PATH = "/tmp/bob_display.sock"


def send_command(cmd: dict) -> None:
    """Send a single JSON command to the face engine."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCKET_PATH)
        s.sendall((json.dumps(cmd) + "\n").encode())
        s.close()
    except Exception as e:
        print(f"Error sending command: {e}")


def set_state(state: str) -> None:
    """Change BOB's emotional state."""
    send_command({"state": state})


def set_subtitle(text: str, duration: float = 3.0) -> None:
    """Show subtitle text on screen."""
    send_command({"type": "subtitle", "text": text, "duration": duration})


def look_at(x: float, y: float) -> None:
    """Direct BOB's gaze to normalized screen coords (0.0-1.0)."""
    send_command({"look_at": {"x": x, "y": y}})


# ── Demo sequence ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("BOB Face Controller Demo")
    print("Connecting to", SOCKET_PATH)

    states = [
        ("idle",      "I am IDLE",        2.0),
        ("listening", "I am LISTENING",   2.0),
        ("thinking",  "I am THINKING...", 2.0),
        ("speaking",  "I am SPEAKING!",   3.0),
        ("happy",     "I am HAPPY! :D",   2.0),
        ("sad",       "I am SAD :(",      2.0),
        ("surprised", "WHOA!",            2.0),
        ("confused",  "Huh? What?",       2.0),
        ("sleeping",  "zzz...",           3.0),
        ("error",     "ERROR!",           2.0),
        ("idle",      "Back to normal",   2.0),
    ]

    for state, subtitle, duration in states:
        print(f"→ {state}: {subtitle}")
        set_state(state)
        set_subtitle(subtitle, duration)
        time.sleep(duration)

    # Test look_at
    print("→ Gaze test")
    set_state("listening")
    for x in [0.2, 0.8, 0.5, 0.5]:
        look_at(x, 0.5)
        time.sleep(0.8)

    print("Demo complete!")
