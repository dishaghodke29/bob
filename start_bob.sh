#!/bin/bash
# BOB Robot — Startup Script
# Usage: bash /home/arduino/bob/start_bob.sh

BOB_DIR="/home/arduino/bob"
VENV="$BOB_DIR/venv/bin/activate"
LOG_DIR="$BOB_DIR/logs"
LLAMA_BIN="$BOB_DIR/llama.cpp/build/bin/llama-server"

# ── 0. Ensure log dir exists ──────────────────────────────────────────────────
mkdir -p "$LOG_DIR"

source "$VENV"

echo "========================================"
echo "   Starting BOB Robot System"
echo "========================================"

# ── 1. Kill any stale processes ───────────────────────────────────────────────
echo "[0/3] Cleaning up stale processes..."
pkill -f llama-server   2>/dev/null; sleep 1
pkill -f bob_display.py 2>/dev/null
pkill -f "brain/main.py" 2>/dev/null
sleep 1

# ── 2. Pick model (prefer 0.5B — much faster on ARM) ──────────────────────────
MODEL_05B="$BOB_DIR/models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
MODEL_15B="$BOB_DIR/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
MODEL_SYM="$BOB_DIR/models/bob_llm.gguf"

if [ -f "$MODEL_05B" ]; then
    MODEL="$MODEL_05B"
    echo "      Model: Qwen 0.5B (fast mode) ✓"
elif [ -f "$MODEL_SYM" ]; then
    MODEL="$MODEL_SYM"
    echo "      Model: bob_llm.gguf (symlink)"
elif [ -f "$MODEL_15B" ]; then
    MODEL="$MODEL_15B"
    echo "      Model: Qwen 1.5B (slower — consider downloading 0.5B)"
else
    echo "ERROR: No GGUF model found in $BOB_DIR/models/"
    echo "  Download: huggingface-cli download bartowski/Qwen2.5-0.5B-Instruct-GGUF \\"
    echo "    'Qwen2.5-0.5B-Instruct-Q4_K_M.gguf' --local-dir $BOB_DIR/models/"
    exit 1
fi

# ── 3. Start llama-server (background) ────────────────────────────────────────
echo "[1/3] Starting llama-server (local LLM)..."
nohup "$LLAMA_BIN" \
    --model   "$MODEL" \
    --host    127.0.0.1 \
    --port    8080 \
    --ctx-size 512 \
    --threads  4 \
    --batch-size 128 \
    --no-mmap \
    --flash-attn \
    --log-disable \
    -ngl 0 \
    > "$LOG_DIR/llama.log" 2>&1 &
LLAMA_PID=$!
echo "      llama-server PID: $LLAMA_PID"

# ── 4. Wait for llama-server to be ready (up to 45s) ─────────────────────────
echo "      Waiting for LLM to load..."
for i in $(seq 1 45); do
    sleep 1
    if curl -s http://127.0.0.1:8080/health 2>/dev/null | grep -q "ok"; then
        echo "      LLM ready! (${i}s)"
        break
    fi
    if [ $i -eq 45 ]; then
        echo "WARNING: LLM did not respond in 45s — check $LOG_DIR/llama.log"
    fi
done

# ── 5. Set display environment ────────────────────────────────────────────────
export DISPLAY=:0
export SDL_VIDEODRIVER=x11

# ── 6. Start Pygame face display ──────────────────────────────────────────────
echo "[2/3] Starting BOB face display..."
nohup python3 "$BOB_DIR/display/bob_display.py" \
    > "$LOG_DIR/display.log" 2>&1 &
DISPLAY_PID=$!
echo "      Face display PID: $DISPLAY_PID"
sleep 2

# ── 7. Start Python brain ─────────────────────────────────────────────────────
echo "[3/3] Starting BOB brain..."
nohup python3 "$BOB_DIR/brain/main.py" \
    > "$LOG_DIR/brain.log" 2>&1 &
BRAIN_PID=$!
echo "      Brain PID: $BRAIN_PID"

# ── 8. Save PIDs ──────────────────────────────────────────────────────────────
echo "$LLAMA_PID"   > /tmp/bob_llama.pid
echo "$DISPLAY_PID" > /tmp/bob_display.pid
echo "$BRAIN_PID"   > /tmp/bob_brain.pid

echo ""
echo "========================================"
echo "  BOB is ALIVE!"
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):8000"
echo "  Logs:      $LOG_DIR/"
echo "  Stop:      bash $BOB_DIR/stop_bob.sh"
echo "========================================"

# Follow brain log live
tail -f "$LOG_DIR/brain.log"
