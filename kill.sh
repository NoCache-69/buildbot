#!/bin/bash
# Stop/Kill script for Telegram AOSP Build Tracker Daemon

echo "=================================================="
echo "🛑 Stopping AOSP Build Tracking Bot..."
echo "=================================================="

# 1. Stop systemd service if active
if systemctl --user is-active --quiet tg-build-bot.service 2>/dev/null; then
    echo "⚙️ Stopping systemd user service (tg-build-bot.service)..."
    systemctl --user stop tg-build-bot.service
    echo "✅ systemd service stopped."
else
    echo "ℹ️ systemd service is already inactive or not running."
fi

# 2. Kill any manual background launcher processes
if pgrep -f daemon.py > /dev/null; then
    echo "🔥 Terminating background processes (pkill -f daemon.py)..."
    pkill -f daemon.py
    echo "✅ Background daemon processes killed."
else
    echo "ℹ️ No manual background daemon processes found."
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 Bot has been successfully stopped!"
echo "=================================================="
