#!/bin/bash
# Manual launcher for Telegram AOSP Build Tracker Daemon
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
nohup python3 "$BOT_DIR/daemon.py" > "$BOT_DIR/daemon.log" 2>&1 &
echo "🚀 Telegram Build Tracker Bot started in background (PID: $!)."
echo "📝 Logs are being written to $BOT_DIR/daemon.log"
