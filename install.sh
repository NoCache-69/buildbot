#!/bin/bash
# Installation script for AOSP Build Tracking Bot
set -e

BOT_DIR="/home/nocache/bot"
CONFIG_FILE="$BOT_DIR/config.json"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/tg-build-bot.service"

echo "=================================================="
echo "🔧 Installing AOSP Build Tracking Telegram Bot"
echo "=================================================="

# 1. Ensure directory structure and make scripts executable
echo "📁 Setting file permissions..."
chmod +x "$BOT_DIR/daemon.py"
chmod +x "$BOT_DIR/cli.py"
chmod +x "$BOT_DIR/kill.sh"

# 2. Check and initialize config.json if not present
if [ ! -f "$CONFIG_FILE" ]; then
    echo "⚙️ Creating default config.json..."
    cat <<EOF > "$CONFIG_FILE"
{
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "subscribed_chats": [],
    "port": 8080
}
EOF
    chmod 600 "$CONFIG_FILE"
else
    echo "ℹ️ config.json already exists. Skipping initialization."
fi

# 3. Setup systemd user service
echo "🚀 Setting up systemd user service..."
mkdir -p "$SYSTEMD_USER_DIR"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=AOSP Build Tracking Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$BOT_DIR
ExecStart=/usr/bin/python3 $BOT_DIR/daemon.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

echo "🔄 Reloading systemd user daemon..."
systemctl --user daemon-reload || echo "⚠️ Warning: systemctl not available or failed. You can launch manually."

# 4. Create manual start script as fallback
echo "💾 Creating manual startup script (start_bot.sh)..."
cat <<EOF > "$BOT_DIR/start_bot.sh"
#!/bin/bash
# Manual launcher for Telegram AOSP Build Tracker Daemon
nohup python3 $BOT_DIR/daemon.py > $BOT_DIR/daemon.log 2>&1 &
echo "🚀 Telegram Build Tracker Bot started in background (PID: \$!)."
echo "📝 Logs are being written to $BOT_DIR/daemon.log"
EOF
chmod +x "$BOT_DIR/start_bot.sh"

echo "=================================================="
echo "🎉 Installation Completed Successfully!"
echo "=================================================="
echo ""
echo "📱 FOLLOW THESE STEPS TO START TRACKING:"
echo "--------------------------------------------------"
echo "1️⃣  Configure your Telegram Bot Token:"
echo "    Open '$CONFIG_FILE' and replace 'YOUR_TELEGRAM_BOT_TOKEN' with your token from @BotFather."
echo ""
echo "2️⃣  Start the background Bot Daemon:"
echo "    Option A (Recommended - systemd):"
echo "      systemctl --user enable tg-build-bot.service"
echo "      systemctl --user start tg-build-bot.service"
echo "      systemctl --user status tg-build-bot.service"
echo ""
echo "    Option B (Fallback - background script):"
echo "      $BOT_DIR/start_bot.sh"
echo ""
echo "3️⃣  Activate your Telegram Chat/Channel:"
echo "    Add your bot to your groups/channels or start a private chat."
echo "    Send the command '/subscribe' inside the chat to register it for alerts."
echo ""
echo "4️⃣  Activate Terminal Commands Tracking:"
echo "    Add the following line to the END of your ~/.bashrc or ~/.zshrc:"
echo "      source $BOT_DIR/tg_hooks.sh"
echo "    Then reload your terminal: 'source ~/.bashrc'"
echo ""
echo "--------------------------------------------------"
