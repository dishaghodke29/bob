#!/usr/bin/env python3
"""Quick import test for ALL BOB modules."""
import sys
sys.path.insert(0, "/home/arduino/bob")

errors = []

tests = [
    # Brain — core
    ("brain.serial_bridge",   "SerialBridge"),
    ("brain.llm_agent",       "LLMAgent"),
    ("brain.bob_brain",       "BobBrain"),
    ("brain.voice",           "VoicePipeline"),
    ("brain.tof_sensor",      "ToFSensor"),
    ("brain.web_server",      "WebServer"),
    # Brain — security / gimbal
    ("brain.security_camera", "SecurityCamera"),
    ("brain.telegram_bot",    "TelegramBot"),
    ("brain.servo_gimbal",    "ServoGimbal"),
    # Brain — notifications / lights
    ("brain.notifier",        "Notifier"),
    ("brain.light_controller","LightController"),
    # Display
    ("display.face.emotions",      "get_emotion"),
    ("display.face.face_renderer", "FaceRenderer"),
    ("display.games.game_menu",    "GameMenu"),
    ("display.games.tic_tac_toe",  "TicTacToe"),
    ("display.games.snake",        "Snake"),
]

for module, symbol in tests:
    try:
        mod = __import__(module, fromlist=[symbol])
        getattr(mod, symbol)
        print(f"  \u2713  {module}")
    except Exception as e:
        print(f"  \u2717  {module}  \u2192  {e}")
        errors.append(module)

print()
if errors:
    print(f"FAILED: {len(errors)} module(s)")
    sys.exit(1)
else:
    print(f"ALL {len(tests)} MODULES OK \u2713")
