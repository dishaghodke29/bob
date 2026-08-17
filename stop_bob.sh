#!/bin/bash
# BOB Robot — Stop Script

echo "Stopping BOB..."

# Kill by PID files
for pidfile in /tmp/bob_brain.pid /tmp/bob_display.pid /tmp/bob_llama.pid; do
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        kill "$PID" 2>/dev/null && echo "  Killed PID $PID ($(basename $pidfile .pid))"
        rm -f "$pidfile"
    fi
done

# Fallback: kill by process name
pkill -f llama-server   2>/dev/null
pkill -f bob_display.py 2>/dev/null
pkill -f "brain/main.py" 2>/dev/null

echo "BOB stopped."
