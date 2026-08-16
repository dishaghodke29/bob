#!/bin/bash
# BOB Robot — Stop Script
echo "Stopping BOB..."
[ -f /tmp/bob_brain.pid   ] && kill $(cat /tmp/bob_brain.pid)   2>/dev/null && echo "Brain stopped"
[ -f /tmp/bob_display.pid ] && kill $(cat /tmp/bob_display.pid) 2>/dev/null && echo "Display stopped"
pkill -f "llama-server"     2>/dev/null && echo "llama-server stopped"
pkill -f "bob_display.py"   2>/dev/null
pkill -f "brain/main.py"    2>/dev/null
rm -f /tmp/bob_*.pid /tmp/bob_display.sock
echo "BOB stopped."
