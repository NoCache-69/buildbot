# AOSP ROM Build Tracking Telegram Bot 🚀

An elegant, zero-dependency background Telegram bot built in Python to track Android Open Source Project (AOSP) compilation progress in real-time. It monitors standard terminal build commands (`m`, `mka`, `make`), provides interactive live status cards, and alerts subscribers of build completions with rich detail.

---

## ✨ Features

- **🎯 Zero-Intervention Shell Hooking**: Simply type `m bacon`, `mka`, or `make` in your Android source root; the bot intercepts and tracks the build completely in the background.
- **📊 Real-Time Progress Cards**: Updates subscribers in real-time with an elegant progress card detailing compile percentage, an ASCII visual progress bar, active compiler actions, and custom projected ETA.
- **👤 Multi-User & Multi-Server Attribution**: Tracks and displays the system username and server hostname (e.g., `Builder: dev`, `Host: build-srv-1`) on all progress cards, status checks, and completion alerts. This makes it perfect for teams sharing a single Telegram channel across different servers.
- **☁️ Multi-Host Auto-Uploads**: Automatically uploads completed ROM builds, boot images, and recovery images to your preferred host: **Gofile**, **PixelDrain**, or **Google Drive** (via Service Account, OAuth2, or Rclone). Can be configured in `config.json` or switched live via `/sethost`.
- **💾 Auto-Discovered Outputs**: Displays output ZIP package details (filename, file size, MD5 checksum) upon a successful build.
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
Open your configuration file at `~/.config/tg_build_bot/config.json` (created automatically by `install.sh`) and configure your bot token, owner Telegram user ID, and auto-upload host:
```json
{
    "bot_token": "8834515366:AAHjsHbdXWKDvgiJRhp53juv3WHu6iTtljc",
    "owner_id": 123456789,
    "admin_ids": [],
    "subscribed_chats": [],
    "port": 8080,
    "upload_host": "gofile",
    "pixeldrain_api_key": null,
    "gdrive": {
        "service_account": null,
        "folder_id": null,
        "rclone_remote": null
    }
}
```

#### ☁️ Auto-Upload Host Options (`upload_host`):
Set `"upload_host"` to any of the following:

| Host | Description | Configuration Keys |
| :--- | :--- | :--- |
| **`"gofile"`** *(Default)* | Uploads to [Gofile.io](https://gofile.io). Works out of the box anonymously without authentication. | Optional: `"gofile_token"`, `"gofile_folder_id"` |
| **`"pixeldrain"`** | Uploads to [PixelDrain.com](https://pixeldrain.com). Fast and reliable. | Required: `"pixeldrain_api_key"` (from your PixelDrain API keys page) |
| **`"gdrive"`** | Uploads to Google Drive with public share links. | Supports: Service Account, OAuth2, or Rclone (see below) |
| **`"none"`** | Disables auto-uploading. Output files will still be discovered, sized, and checksummed. | None |

> 📁 **Google Drive Configuration Methods**:
> - **Method 1 (OAuth2 / token.pickle - Recommended)**: Place `token.pickle` in `~/.config/tg_build_bot/token.pickle` (or specify OAuth `client_id`, `client_secret`, and `refresh_token` in `config.json`).
> - **Method 2 (Service Account)**: Place your `service_account.json` in `~/.config/tg_build_bot/service_account.json` and share your target folder with the service account email.
> - **Method 3 (Rclone)**: Set `"rclone_remote": "gdrive"` and optional folder.
> 
> *See the [Google Drive Upload Setup Guide](#-google-drive-upload-setup-guide) below for complete step-by-step instructions.*

> 💡 **Custom Settings Override**:
> You can override the configuration location by exporting the `TG_BOT_CONFIG` environment variable. This is highly useful for running multiple individual bots on different ports/servers:
> ```bash
> export TG_BOT_CONFIG="$HOME/.config/tg_build_bot/custom_config.json"
> ```

---

## ☁️ Google Drive Upload Setup Guide

The bot natively supports uploading completed ROM zips and image artifacts directly to a designated Google Drive folder and provides **direct file download links** (`https://drive.google.com/uc?id=<FILE_ID>&export=download`) in Telegram notifications.

You can configure Google Drive authentication using any of the 3 supported methods:

### 📁 How to Get Your Target Google Drive Folder ID
1. Open [Google Drive](https://drive.google.com/drive/) in your browser.
2. Open or create the folder where you want build artifacts uploaded (e.g. `rom-builds`).
3. Look at the browser URL bar:
   ```
   https://drive.google.com/drive/folders/1S-GX1QSvfigarRLrgsAKlwu5R5BiNqPJ
   ```
4. The string after `folders/` (`1S-GX1QSvfigarRLrgsAKlwu5R5BiNqPJ`) is your **`folder_id`**.

---

### Method A: OAuth2 Credentials / `token.pickle` (Recommended for Personal Drive)

If you already have a `token.pickle` generated from Python scripts (such as PyDrive, google-auth, or gdrive bots), the bot can use it directly without requiring external Google libraries!

#### Option 1: Drop `token.pickle` into the Config Directory
Simply place your `token.pickle` into `~/.config/tg_build_bot/`:
```bash
cp /path/to/token.pickle ~/.config/tg_build_bot/token.pickle
```
The bot will automatically discover `token.pickle`, refresh expired tokens automatically in the background, and upload to your folder.

#### Option 2: Configure in `config.json`
You can also supply your OAuth2 credentials explicitly in `~/.config/tg_build_bot/config.json`:
```json
{
    "upload_host": "gdrive",
    "gdrive": {
        "folder_id": "YOUR_FOLDER_ID",
        "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
        "client_secret": "YOUR_CLIENT_SECRET",
        "refresh_token": "YOUR_REFRESH_TOKEN"
    }
}
```

---

### Method B: Service Account (`service_account.json`)

Service Accounts are ideal for multi-user or headless build servers because they do not expire and require no interactive user login.

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Drive API** under **APIs & Services** > **Library**.
3. Create a Service Account under **APIs & Services** > **Credentials** > **Create Credentials** > **Service Account**.
4. Go to the Service Account's **Keys** tab, click **Add Key** > **Create new key** > **JSON**, and download the file.
5. **Important**: Open your target Google Drive folder, click **Share**, and add the Service Account's email (e.g. `my-sa@project.iam.gserviceaccount.com`) as an **Editor**.
6. Place the downloaded JSON file on your server:
   ```bash
   cp /path/to/your_key.json ~/.config/tg_build_bot/service_account.json
   ```
   *(The bot auto-detects `service_account.json` at this location).*
7. In `~/.config/tg_build_bot/config.json`:
   ```json
   {
       "upload_host": "gdrive",
       "gdrive": {
           "folder_id": "YOUR_FOLDER_ID"
       }
   }
   ```

---

### Method C: Rclone Remote

If you already use [Rclone](https://rclone.org/) on your build server:

1. Configure an Rclone remote named `gdrive` (via `rclone config`).
2. In `~/.config/tg_build_bot/config.json`:
   ```json
   {
       "upload_host": "gdrive",
       "gdrive": {
           "rclone_remote": "gdrive",
           "folder_id": "YOUR_FOLDER_NAME_OR_ID"
       }
   }
   ```

---

### 🔍 Verifying Your Google Drive Setup

Send **`/host`** to your Telegram bot. It will report your active host and credentials status:
```
☁️ Auto-Upload Host Configuration
━━━━━━━━━━━━━━━━━━━━━
📍 Active Host: Google Drive (gdrive)
🔑 Auth Method: OAuth2 Token Pickle (token.pickle)
📁 Folder ID: 1S-GX1QSvfigarRLrgsAKlwu5R5BiNqPJ
```

To switch between hosts at any time without restarting the daemon:
- `/sethost gdrive` — Switch to Google Drive
- `/sethost pixeldrain` — Switch to PixelDrain
- `/sethost gofile` — Switch to Gofile
- `/sethost none` — Disable auto-uploads

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

### 6️⃣ Load Shell Aliases & Script Hooks
To track builds executed directly in interactive terminals (`m`, `mka`, `make`) **and** builds triggered through scripts (e.g., `rom-build.sh`, `rom.sh`, or automated build scripts), configure your shell environment:

#### 1. Add to `~/.bashrc` (or `~/.zshrc`):
```bash
export BASH_ENV="/home/nocache/bot/tg_hooks.sh"
source /home/nocache/bot/tg_hooks.sh
```

#### 2. Add to `~/.profile` (ensures `BASH_ENV` is active across all login/SSH shell sessions):
```bash
export BASH_ENV="/home/nocache/bot/tg_hooks.sh"
```

#### 💡 Quick Setup One-Liner:
```bash
echo 'export BASH_ENV="$HOME/bot/tg_hooks.sh"' >> ~/.bashrc
echo 'source "$HOME/bot/tg_hooks.sh"' >> ~/.bashrc
echo 'export BASH_ENV="$HOME/bot/tg_hooks.sh"' >> ~/.profile
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
| **`/host`** | Displays the current auto-upload host, authentication status, and options. |
| **`/ping`** | Checks bot response latency. |
| **`/help`** | Displays the command reference list. |

### 🛡️ Sudo Commands (Admins & Owner)
| Command | Action |
| :--- | :--- |
| **`/sethost <host>`** | Changes the auto-upload host (`gofile`, `pixeldrain`, `gdrive`, `none`). |
| **`/shutdown`** | Safely powers off the server via `sudo shutdown -h now`. |
| **`/reboot`** | Reboots the server via `sudo reboot`. |
| **`/restart`** | Restarts the bot background service (via `systemctl --user restart tg-build-bot.service`). |
| **`/sudolist`** | Lists the bot owner and all registered sudo admins (alias: `/admins`). |
| **`/synccommands`** | Forces synchronization of command previews and menu buttons with Telegram API. |

> 💡 **Command Previews & Autocomplete**:
> The bot automatically configures Telegram command previews (`setMyCommands`) across private chats, groups, and admin scopes. When any user types `/` in private chat or in a group where the bot is added, Telegram will immediately display interactive command suggestions with full descriptions.

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
