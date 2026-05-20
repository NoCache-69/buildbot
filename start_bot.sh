#!/bin/bash
# Manual launcher for Telegram AOSP Build Tracker Daemon
nohup python3 /home/nocache/bot/daemon.py > /home/nocache/bot/daemon.log 2>&1 &
echo "🚀 Telegram Build Tracker Bot started in background (PID: $!)."
echo "📝 Logs are being written to /home/nocache/bot/daemon.log"
