# AOSP ROM Build Tracking Telegram Bot 🚀

An elegant, zero-dependency background Telegram bot built in Python to track Android Open Source Project (AOSP) compilation progress in real-time. It monitors standard terminal build commands (`m`, `mka`, `make`), provides interactive live status cards, and alerts subscribers of build completions with rich detail.

---

## ✨ Features

- **🎯 Zero-Intervention Shell Hooking**: Simply type `m bacon`, `mka`, or `make` in your Android source root; the bot intercepts and tracks the build completely in the background.
- **📊 Real-Time Progress Cards**: Updates subscribers in real-time with an elegant progress card detailing compile percentage, an ASCII visual progress bar, active compiler actions, and custom projected ETA.
- **💾 Auto-Discovered Outputs**: Displays output ZIP package details (filename and file size) upon a successful build.
- **🔍 Error Snippet Capture**: If a build fails, the last 25 lines of the compiler output are automatically extracted, formatted, and delivered directly to Telegram.
- **🖥️ System Health Metrics**: Check build server load (`/sysinfo`) to monitor CPU load, RAM usage, and available disk space.
- **📁 Compilation History**: Access history for the last 5 ROM compilation tasks via `/history`.
- **⚙️ Seamless Background Service**: Easily configured as a systemd user-level service (`tg-build-bot.service`), running persistently without root permissions.

---

## 📁 Repository Overview

- **[daemon.py](file:///home/nocache/bot/daemon.py)**: The main background service. Runs a fast, thread-safe `ThreadingHTTPServer` to receive build triggers and handles the Telegram polling loop.
- **[cli.py](file:///home/nocache/bot/cli.py)**: Trigger CLI tool that wraps and communicates status events (`start`/`stop`) to the background daemon via local POST requests.
- **[tg_hooks.sh](file:///home/nocache/bot/tg_hooks.sh)**: Shell aliases and wrappers for `m`, `mka`, and `make`. Captures compilation logs to `out/tg_build.log` and fires start/stop notifications.
- **[install.sh](file:///home/nocache/bot/install.sh)**: Auto-installer script setting correct file permissions, initializing configuration structures, and generating the systemd user service unit.
- **[config.json](file:///home/nocache/bot/config.json)**: User configuration containing the Telegram bot token, subscribed chat IDs, port details, and compiled build history.

---

## 🚀 Setup & Execution Guide

Follow these simple steps to configure and start your background build tracking bot:

### 1️⃣ Obtain a Telegram Bot Token
1. Message [@BotFather](https://t.me/BotFather) on Telegram.
2. Send `/newbot` and follow the instructions to choose a name and username.
3. Copy the HTTP API token generated for you (e.g., `8834515366:AAHjs...`).

### 2️⃣ Configure Bot Settings
Open your configuration file [config.json](file:///home/nocache/bot/config.json) and replace `"YOUR_TELEGRAM_BOT_TOKEN"` with your actual Telegram bot token:
```json
{
    "bot_token": "8834515366:AAHjsHbdXWKDvgiJRhp53juv3WHu6iTtljc",
    "subscribed_chats": [],
    "history": [],
    "port": 8080
}
```

### 3️⃣ Run the Installer
Generate the systemd service file and configure file permissions by executing:
```bash
cd /home/nocache/bot
./install.sh
```

### 4️⃣ Start the Background Daemon
Choose **one** of the options below to run the bot:

#### Option A: Using systemd (Recommended)
This runs the bot as a persistent user service that starts automatically upon boot:
```bash
systemctl --user enable tg-build-bot.service
systemctl --user start tg-build-bot.service
```
To check service status:
```bash
systemctl --user status tg-build-bot.service
```

#### Option B: Manual Fallback Launcher
If systemd is not available on your environment, start the bot in the background via the generated launcher:
```bash
/home/nocache/bot/start_bot.sh
```

### 5️⃣ Subscribe to Alerts
1. Open a chat with your bot on Telegram (or add it to your team's group/channel).
2. Start the conversation with `/start`.
3. Send the command **`/subscribe`** in the chat.
   > ℹ️ *The bot will now register this chat and broadcast ROM compilation updates here.*

### 6️⃣ Load Shell Aliases
Activate terminal build tracking by appending the hooks to your terminal shell. Add the following line to the end of your `~/.bashrc` (or `~/.zshrc`):
```bash
source /home/nocache/bot/tg_hooks.sh
```
Reload your active terminal environment:
```bash
source ~/.bashrc
```

---

## 📱 Telegram Commands Reference

Send these commands directly to the bot inside your subscribed chats:

| Command | Action |
| :--- | :--- |
| **`/start`** | Welcomes users and displays all available tracking commands. |
| **`/subscribe`** | Subscribes the current chat, group, or channel to live build updates. |
| **`/unsubscribe`** | Stops sending build alerts to the current chat. |
| **`/status`** | Displays details about any currently compiling ROMs (elapsed, ETA, compilation bar, compiler tasks). |
| **`/sysinfo`** | Shows build server performance specs (CPU load, RAM consumption, and Free Disk space). |
| **`/history`** | Lists the 5 most recent compilations, their durations, completion times, and status. |

---

## 🛠️ Management & Maintenance

### How to View Real-Time Daemon Logs
Track the daemon's internal state (connecting to Telegram API, parsing HTTP calls):
```bash
journalctl --user -u tg-build-bot.service -f
```
*(If you used the manual fallback launcher, tail `/home/nocache/bot/daemon.log` instead.)*

### Stopping/Killing the Bot Daemon

#### For systemd service (Recommended):
```bash
systemctl --user stop tg-build-bot.service
```

#### For manual fallback launcher (PID pkill):
If you started the bot manually in the background using `start_bot.sh`, stop the background processes by running:
```bash
pkill -f daemon.py
```

### Restarting the Bot
```bash
# For systemd
systemctl --user restart tg-build-bot.service

# For manual launcher
pkill -f daemon.py && /home/nocache/bot/start_bot.sh
```
