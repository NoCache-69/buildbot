# AOSP ROM Build Tracking Telegram Bot 🚀

An elegant, zero-dependency background Telegram bot built in Python to track Android Open Source Project (AOSP) compilation progress in real-time. It monitors standard terminal build commands (`m`, `mka`, `make`), provides interactive live status cards, and alerts subscribers of build completions with rich detail.

---

## ✨ Features

- **🎯 Zero-Intervention Shell Hooking**: Simply type `m bacon`, `mka`, or `make` in your Android source root; the bot intercepts and tracks the build completely in the background.
- **📊 Real-Time Progress Cards**: Updates subscribers in real-time with an elegant progress card detailing compile percentage, an ASCII visual progress bar, active compiler actions, and custom projected ETA.
- **👤 Multi-User & Multi-Server Attribution**: Tracks and displays the system username and server hostname (e.g., `Builder: dev`, `Host: build-srv-1`) on all progress cards, status checks, and completion alerts. This makes it perfect for teams sharing a single Telegram channel across different servers.
- **💾 Auto-Discovered Outputs**: Displays output ZIP package details (filename and file size) upon a successful build.
- **🔍 Error Snippet Capture**: If a build fails, the last 25 lines of the compiler output are automatically extracted, formatted, and delivered directly to Telegram.
- **🖥️ System Health Metrics**: Check build server performance (`/specs`) to monitor OS release, kernel version, CPU load, RAM usage, and available disk space.
- **⚙️ Seamless Background Service**: Easily configured as a systemd user-level service (`tg-build-bot.service`), running persistently without root permissions.

---

## 📁 Repository Overview

- **[daemon.py](file:///home/nocache/bot/daemon.py)**: The main background service. Runs a fast, thread-safe `ThreadingHTTPServer` to receive build triggers and handles the Telegram polling loop.
- **[cli.py](file:///home/nocache/bot/cli.py)**: Trigger CLI tool that wraps and communicates status events (`start`/`stop`) to the background daemon via local POST requests.
- **[tg_hooks.sh](file:///home/nocache/bot/tg_hooks.sh)**: Shell aliases and wrappers for `m`, `mka`, and `make`. Captures compilation logs to `out/tg_build.log` and fires start/stop notifications.
- **[install.sh](file:///home/nocache/bot/install.sh)**: Auto-installer script setting correct file permissions, initializing configuration structures, and generating the systemd user service unit.
- **config.json**: User configuration containing the Telegram bot token, subscribed chat IDs, and port details. It is loaded dynamically from `~/.config/tg_build_bot/config.json` to avoid source control leakage and allow multi-user environments, but can be customized with the `TG_BOT_CONFIG` environment variable.

---

## 🚀 Setup & Execution Guide

Follow these simple steps to configure and start your background build tracking bot:

### 1️⃣ Obtain a Telegram Bot Token
1. Message [@BotFather](https://t.me/BotFather) on Telegram.
2. Send `/newbot` and follow the instructions to choose a name and username.
3. Copy the HTTP API token generated for you (e.g., `8834515366:AAHjs...`).

### 2️⃣ Configure Bot Settings
Open your configuration file at `~/.config/tg_build_bot/config.json` (created automatically by `install.sh`) and configure your bot token and owner Telegram user ID:
```json
{
    "bot_token": "8834515366:AAHjsHbdXWKDvgiJRhp53juv3WHu6iTtljc",
    "owner_id": 123456789,
    "admin_ids": [],
    "subscribed_chats": [],
    "port": 8080
}
```

> 💡 **Custom Settings Override**:
> You can override the configuration location by exporting the `TG_BOT_CONFIG` environment variable. This is highly useful for running multiple individual bots on different ports/servers:
> ```bash
> export TG_BOT_CONFIG="$HOME/.config/tg_build_bot/custom_config.json"
> ```

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

The bot features a 3-tier role-based permission system:
- **Owner**: Configured via `owner_id` in `config.json`. Can manage sudo admins via `/addsudo` and `/delsudo`.
- **Admins (Sudo)**: Authorized via `/addsudo`. Can execute server management commands (`/shutdown`, `/reboot`, `/restart`, `/sudolist`).
- **Users**: Open access to all standard tracking and informational commands. Unauthorized attempts to execute sudo or owner commands trigger a warning message.

### 👤 Public Commands (All Users)
| Command | Action |
| :--- | :--- |
| **`/start`** | Welcomes users and displays all available tracking commands. |
| **`/subscribe`** | Subscribes the current chat, group, or channel to live build updates. |
| **`/unsubscribe`** | Stops sending build alerts to the current chat. |
| **`/status`** | Displays details about any currently compiling ROMs (elapsed, ETA, compilation bar, compiler tasks). |
| **`/specs`** | Shows server specs including OS distribution, Linux kernel version, CPU load, RAM usage, and free disk space (alias: `/sysinfo`). |
| **`/ping`** | Checks bot response latency. |
| **`/help`** | Displays the command reference list. |

### 🛡️ Sudo Commands (Admins & Owner)
| Command | Action |
| :--- | :--- |
| **`/shutdown`** | Safely powers off the server via `sudo shutdown -h now`. |
| **`/reboot`** | Reboots the server via `sudo reboot`. |
| **`/restart`** | Restarts the bot background service (via `systemctl --user restart tg-build-bot.service`). |
| **`/sudolist`** | Lists the bot owner and all registered sudo admins (alias: `/admins`). |

### 👑 Owner Commands (Owner Only)
| Command | Action |
| :--- | :--- |
| **`/addsudo <id>`** | Adds a user to the sudo admins list (supports reply to user message or numeric ID). |
| **`/delsudo <id>`** | Removes a user from the sudo admins list (alias: `/rmsudo`). |

---

## 🛠️ Management & Maintenance

### How to View Real-Time Daemon Logs
Track the daemon's internal state (connecting to Telegram API, parsing HTTP calls):
```bash
journalctl --user -u tg-build-bot.service -f
```
*(If you used the manual fallback launcher, tail `/home/nocache/bot/daemon.log` instead.)*

### Stopping/Killing the Bot Daemon

#### ⚡ Easy Stop Utility (Recommended):
You can stop the bot (whether running via systemd or the manual fallback script) in one simple command using the provided utility:
```bash
/home/nocache/bot/kill.sh
```

#### Manual Methods:
* **For systemd service**:
  ```bash
  systemctl --user stop tg-build-bot.service
  ```
* **For manual background launcher**:
  ```bash
  pkill -f daemon.py
  ```

### Restarting the Bot
```bash
# For systemd
systemctl --user restart tg-build-bot.service

# For manual launcher
/home/nocache/bot/kill.sh && /home/nocache/bot/start_bot.sh
```
