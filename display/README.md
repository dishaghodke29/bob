# BOB Face Engine

Native fullscreen animated face for the BOB robot, running directly on the **Arduino UNO Q** with a 7-inch HDMI touchscreen.

**No browser. No internet. No Electron. Pure Python + Pygame.**

---

## What it looks like

- Minion-inspired yellow cartoon robot face
- Large expressive blue eyes with pupils, iris, eyelids, eyebrows
- Smooth animated mouth (smiles, frowns, speaks)
- Natural blinking with random timing
- Pupils wander and track targets
- 10 emotional states with smooth transitions
- Renders at 1024×600 fullscreen, targets 60 FPS
- Controlled via Unix socket from your AI brain

---

## Directory structure

```
display/
├── bob_face/
│   ├── __init__.py
│   ├── main.py           ← entry point
│   ├── config.py         ← all constants, colors, geometry
│   ├── animation.py      ← easing, Animated values, Oscillator
│   ├── expressions.py    ← per-state facial parameters
│   ├── state_machine.py  ← blinking, wander, speaking timing
│   ├── eyes.py           ← eye + eyelid + brow rendering
│   ├── mouth.py          ← mouth rendering + visemes
│   ├── face_engine.py    ← compositor and animation orchestrator
│   └── socket_server.py  ← Unix socket IPC server
├── bob_face.service      ← systemd service
├── example_controller.py ← shows how to control the face
└── requirements_face.txt
```

---

## Installation on UNO Q

```bash
# 1. Install pygame into the BOB venv
source /home/arduino/bob/venv/bin/activate
pip install pygame==2.6.1

# 2. Install pygame system dependencies (if needed)
sudo apt-get install -y libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev python3-pygame

# 3. Upload files (from your PC)
scp -r display/ arduino@192.168.1.20:/home/arduino/bob/

# 4. Test manually (run with display)
ssh arduino@192.168.1.20
DISPLAY=:0 python3 -m bob_face
# Press ESC to exit, keys 1-0 to cycle states
```

---

## Run manually

```bash
# From the board over SSH:
DISPLAY=:0 source /home/arduino/bob/venv/bin/activate
cd /home/arduino/bob/display
DISPLAY=:0 python3 -m bob_face
```

---

## Auto-start on boot (systemd)

```bash
# Copy service file
cp /home/arduino/bob/display/bob_face.service ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable bob_face
systemctl --user start bob_face

# Check status
systemctl --user status bob_face

# View logs
journalctl --user -u bob_face -f
```

---

## Socket control protocol

The face engine listens at `/tmp/bob_display.sock` (Unix domain socket).

Send newline-terminated JSON:

```bash
# Change state
echo '{"state": "happy"}' | nc -U /tmp/bob_display.sock

# Show subtitle
echo '{"type": "subtitle", "text": "Hello!", "duration": 3.0}' | nc -U /tmp/bob_display.sock

# Direct gaze (0.0-1.0 normalized screen coords)
echo '{"look_at": {"x": 0.7, "y": 0.4}}' | nc -U /tmp/bob_display.sock

# Alternative format (compatible with existing brain.py)
echo '{"type": "emotion", "name": "thinking"}' | nc -U /tmp/bob_display.sock
```

---

## States

| Key | State | Behavior |
|---|---|---|
| `1` | `idle` | Natural blink, eye wander, relaxed |
| `2` | `listening` | Wide attentive eyes, raised brows |
| `3` | `thinking` | Eyes up-left, furrowed brow, dots |
| `4` | `speaking` | Mouth animates continuously |
| `5` | `happy` | Big smile, green iris, energetic |
| `6` | `sad` | Droop brows, frown, blue iris |
| `7` | `surprised` | O-mouth, huge pupils |
| `8` | `confused` | Uneven brows, tilted expression |
| `9` | `sleeping` | Closed eyes, floating Zs |
| `0` | `error` | Furrowed, red iris, glow |

---

## Connecting to your AI brain

In `bob_brain.py`, the `_send_display()` method already sends to this socket:

```python
self._send_display({"type": "emotion", "name": "thinking"})
self._send_display({"type": "subtitle", "text": response, "duration": 6.0})
```

Both formats are supported out of the box — no changes to brain.py needed.

---

## Keyboard shortcuts (dev mode)

| Key | Action |
|---|---|
| `1`–`9`, `0` | Cycle through all states |
| `ESC` | Quit |
| Click/touch | Direct gaze to that point |

---

## Performance on UNO Q

- CPU: ~8-12% on one core (pygame is efficient)
- RAM: ~45MB
- Runs alongside LLM, Whisper, and camera without issues
- Camera is on-demand only (zero CPU when not in use)
