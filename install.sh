#!/bin/bash
# Installation script for AOSP Build Tracking Bot
set -e

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$BOT_DIR/config.json"
USER_CONFIG_DIR="$HOME/.config/tg_build_bot"
USER_CONFIG_FILE="$USER_CONFIG_DIR/config.json"
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
if [ -f "$CONFIG_FILE" ] && [ ! -f "$USER_CONFIG_FILE" ]; then
    echo "🚚 Migrating existing local config.json to $USER_CONFIG_FILE..."
    mkdir -p "$USER_CONFIG_DIR"
    mv "$CONFIG_FILE" "$USER_CONFIG_FILE"
    chmod 700 "$USER_CONFIG_DIR"
    chmod 600 "$USER_CONFIG_FILE"
elif [ ! -f "$USER_CONFIG_FILE" ]; then
    echo "⚙️ Creating default config.json at $USER_CONFIG_FILE..."
    mkdir -p "$USER_CONFIG_DIR"
    cat <<EOF > "$USER_CONFIG_FILE"
{
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "owner_id": null,
    "admin_ids": [],
    "subscribed_chats": [],
    "port": 8080
}
EOF
    chmod 700 "$USER_CONFIG_DIR"
    chmod 600 "$USER_CONFIG_FILE"
else
    echo "ℹ️ config.json already exists at $USER_CONFIG_FILE. Skipping initialization."
fi

# 3. Setup systemd user service
echo "🚀 Setting up systemd user service..."
mkdir -p "$SYSTEMD_USER_DIR"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=AOSP Build Tracking Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$BOT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $BOT_DIR/daemon.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

echo "🔄 Reloading systemd user daemon..."
systemctl --user daemon-reload || echo "⚠️ Warning: systemctl not available or failed. You can launch manually."

# Enable user lingering so the service starts at system boot, not just on login
if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$USER" && echo "✅ User lingering enabled — bot will start at boot." || echo "⚠️ Could not enable lingering. Bot may only start after login."
else
    echo "⚠️ loginctl not found. Bot may only start after you log in."
fi

# Enable and start the service now
echo "🚀 Enabling and starting tg-build-bot.service..."
systemctl --user enable tg-build-bot.service
systemctl --user start tg-build-bot.service
systemctl --user status tg-build-bot.service --no-pager || true

# 4. Create manual start script as fallback
echo "💾 Creating manual startup script (start_bot.sh)..."
cat <<'EOF' > "$BOT_DIR/start_bot.sh"
#!/bin/bash
# Manual launcher for Telegram AOSP Build Tracker Daemon
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
nohup python3 "$BOT_DIR/daemon.py" > "$BOT_DIR/daemon.log" 2>&1 &
echo "🚀 Telegram Build Tracker Bot started in background (PID: $!)."
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
echo "    Open '$USER_CONFIG_FILE' and replace 'YOUR_TELEGRAM_BOT_TOKEN' with your token from @BotFather."
echo ""
echo "2️⃣  The bot is already running! Manage it with:"
echo "      systemctl --user status tg-build-bot.service"
echo "      systemctl --user restart tg-build-bot.service"
echo "      systemctl --user stop tg-build-bot.service"
echo "    Or use the kill script:"
echo "      $BOT_DIR/kill.sh"
echo ""
echo "3️⃣  Activate your Telegram Chat/Channel:"
echo "    Add your bot to your groups/channels or start a private chat."
echo "    Send the command '/subscribe' inside the chat to register it for alerts."
echo ""
echo "4️⃣  Activate Terminal Commands & Script Tracking:"
echo "    To track builds from interactive terminals (m, mka, make) and scripts (rom-build.sh, etc.):"
echo ""
echo "    ▶ Add to ~/.bashrc (or ~/.zshrc):"
echo "        export BASH_ENV=\"$BOT_DIR/tg_hooks.sh\""
echo "        source \"$BOT_DIR/tg_hooks.sh\""
echo ""
echo "    ▶ Add to ~/.profile (ensures BASH_ENV is active for all login/SSH shell scripts):"
echo "        export BASH_ENV=\"$BOT_DIR/tg_hooks.sh\""
echo ""
echo "    💡 Quick Setup One-Liner:"
echo "        echo 'export BASH_ENV=\"$BOT_DIR/tg_hooks.sh\"' >> ~/.bashrc"
echo "        echo 'source \"$BOT_DIR/tg_hooks.sh\"' >> ~/.bashrc"
echo "        echo 'export BASH_ENV=\"$BOT_DIR/tg_hooks.sh\"' >> ~/.profile"
echo ""
echo "    Then reload your active shell: 'source ~/.bashrc'"
echo ""
echo "--------------------------------------------------"
