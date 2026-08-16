#!/bin/bash
# BOB Robot — Startup Script
# Run this on the Arduino UNO Q to start everything
# Usage: bash /home/arduino/bob/start_bob.sh

set -e

BOB_DIR="/home/arduino/bob"
VENV="$BOB_DIR/venv/bin/activate"
LOG_DIR="$BOB_DIR/logs"

source "$VENV"

echo "=============================="
echo "  Starting BOB Robot System"
echo "=============================="

# 1. Check model exists
MODEL="$BOB_DIR/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
if [ ! -f "$MODEL" ]; then
    # Check for any .gguf in models dir
    FOUND=$(find "$BOB_DIR/models" -name "*.gguf" | head -1)
    if [ -z "$FOUND" ]; then
        echo "ERROR: No GGUF model found in $BOB_DIR/models/"
        echo "Download one with: hf download bartowski/Qwen2.5-1.5B-Instruct-GGUF 'Qwen2.5-1.5B-Instruct-Q4_K_M.gguf' --local-dir $BOB_DIR/models/"
        exit 1
    fi
    # Symlink to expected path
    ln -sf "$FOUND" "$MODEL"
    echo "Using model: $FOUND"
fi

# 2. Set display environment for Pygame (7" HDMI screen)
export DISPLAY=:0
export SDL_VIDEODRIVER=x11

# 3. Add user to required groups (dialout for serial, i2c for sensors, video for camera)
groups | grep -q dialout || echo "NOTE: Add user to dialout group: sudo usermod -aG dialout arduino"
groups | grep -q i2c     || echo "NOTE: Add user to i2c group:     sudo usermod -aG i2c arduino"
groups | grep -q video   || echo "NOTE: Add user to video group:   sudo usermod -aG video arduino"

# 4. Start Pygame face display in background (on 7" screen)
echo "[1/2] Starting BOB face display..."
python3 "$BOB_DIR/display/bob_display.py" \
    > "$LOG_DIR/display.log" 2>&1 &
DISPLAY_PID=$!
echo "      Face display PID: $DISPLAY_PID"

# Give display time to initialize and create socket
sleep 3

# 5. Start Python brain
echo "[2/2] Starting BOB brain..."
python3 "$BOB_DIR/brain/main.py" \
    > "$LOG_DIR/brain.log" 2>&1 &
BRAIN_PID=$!
echo "      Brain PID: $BRAIN_PID"

echo ""
echo "=============================="
echo "  BOB is alive!"
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):8000"
echo "  Logs:      $LOG_DIR/"
echo "  Stop:      bash $BOB_DIR/stop_bob.sh"
echo "=============================="

# Save PIDs for stop script
echo "$DISPLAY_PID" > /tmp/bob_display.pid
echo "$BRAIN_PID"   > /tmp/bob_brain.pid

# Wait for brain process
wait $BRAIN_PID
