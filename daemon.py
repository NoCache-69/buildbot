#!/usr/bin/env python3
import os
import sys
import json
import time
import re
import threading
import socket
import http.client
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import datetime
import platform

# Configuration path
def get_config_path():
    env_path = os.environ.get("TG_BOT_CONFIG")
    if env_path:
        return env_path
    user_path = os.path.expanduser("~/.config/tg_build_bot/config.json")
    if os.path.exists(user_path):
        return user_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "config.json")

CONFIG_PATH = get_config_path()
DEFAULT_PORT = 8080

def load_config():
    default_config = {
        "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
        "owner_id": None,
        "admin_ids": [],
        "subscribed_chats": [],
        "port": DEFAULT_PORT
    }
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    
    try:
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
            if "owner_id" not in cfg and "owner" not in cfg:
                cfg["owner_id"] = None
            if "admin_ids" not in cfg and "admins" not in cfg:
                cfg["admin_ids"] = []
            return cfg
    except Exception as e:
        print(f"Error reading config: {e}", file=sys.stderr)
        return default_config

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)

# Permission helper functions (3 tiers: Owner, Admin/Sudo, User)
def get_owner_id(cfg=None):
    c = cfg if cfg is not None else CONFIG
    val = c.get("owner_id")
    if val is None:
        val = c.get("owner")
    if val is not None and str(val).isdigit():
        return int(val)
    return val

def get_admin_ids(cfg=None):
    c = cfg if cfg is not None else CONFIG
    admins = c.get("admin_ids")
    if admins is None:
        admins = c.get("admins")
    if not admins or not isinstance(admins, list):
        return []
    result = []
    for a in admins:
        if str(a).isdigit():
            result.append(int(a))
        else:
            result.append(a)
    return result

def is_owner(user_id, cfg=None):
    owner = get_owner_id(cfg)
    if owner is None:
        return False
    return user_id == owner or str(user_id) == str(owner)

def is_sudo(user_id, cfg=None):
    if is_owner(user_id, cfg):
        return True
    admins = get_admin_ids(cfg)
    return user_id in admins or str(user_id) in [str(a) for a in admins]

def get_user_role(user_id, cfg=None):
    if is_owner(user_id, cfg):
        return "owner"
    elif is_sudo(user_id, cfg):
        return "admin"
    else:
        return "user"

def upload_to_gofile(file_path):
    if not os.path.exists(file_path):
        print(f"[Gofile] Error: file not found: {file_path}", file=sys.stderr)
        return None
        
    # Get server list
    servers = []
    try:
        url = "https://api.gofile.io/servers"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode('utf-8'))
        if res_data.get("status") == "ok":
            servers = [s["name"] for s in res_data.get("data", {}).get("servers", []) if s.get("name")]
    except Exception as e:
        print(f"[Gofile] Failed to get server list: {e}", file=sys.stderr)
        
    if not servers:
        servers = ["store1", "store5", "store8"]  # Fallbacks
        
    # Order servers so that the last one is tried first (to preserve original design behavior as first choice)
    ordered_servers = []
    if servers:
        last_srv = servers[-1]
        ordered_servers.append(last_srv)
        for s in servers[:-1]:
            if s != last_srv:
                ordered_servers.append(s)
    else:
        ordered_servers = ["store1"]

    max_attempts = min(3, len(ordered_servers))
    
    for attempt in range(max_attempts):
        server = ordered_servers[attempt]
        print(f"[Gofile] Upload attempt {attempt + 1}/{max_attempts} using server: {server}")
        try:
            # Run curl in subprocess to avoid huge memory usage on python
            cmd = ["curl", "-s", "-X", "POST", f"https://{server}.gofile.io/contents/uploadfile", "-F", f"file=@{file_path}"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                try:
                    resp = json.loads(result.stdout)
                    if resp.get("status") == "ok":
                        link = resp.get("data", {}).get("downloadPage")
                        print(f"[Gofile] Uploaded {file_path} successfully: {link}")
                        return link
                    else:
                        print(f"[Gofile] Upload API error for {file_path} on {server}: {resp}", file=sys.stderr)
                except Exception as parse_err:
                    print(f"[Gofile] Response parse error on {server} (raw output: {result.stdout.strip()}): {parse_err}", file=sys.stderr)
            else:
                print(f"[Gofile] Curl failed for {file_path} on {server} with code {result.returncode}: {result.stderr}", file=sys.stderr)
        except Exception as e:
            print(f"[Gofile] Exception uploading {file_path} on {server}: {e}", file=sys.stderr)
            
        if attempt < max_attempts - 1:
            print(f"[Gofile] Retrying with a different server...", file=sys.stderr)
            time.sleep(2)
        
    return None

# Global variables
CONFIG = load_config()
ACTIVE_BUILDS = {}  # key: top_path, value: build_context dict
ACTIVE_BUILDS_LOCK = threading.Lock()
BOT_USERNAME = None

# --- Persistent connection pool for Telegram API ---
# Avoids TCP+TLS handshake per API call and supports concurrent access via
# a small connection pool (up to 4 idle connections reused across threads).
_TG_POOL = []
_TG_POOL_LOCK = threading.Lock()
_TG_POOL_MAX = 4

def _tg_get_connection(timeout):
    with _TG_POOL_LOCK:
        if _TG_POOL:
            return _TG_POOL.pop()
    return http.client.HTTPSConnection("api.telegram.org", timeout=timeout)

def _tg_release_connection(conn):
    with _TG_POOL_LOCK:
        if len(_TG_POOL) < _TG_POOL_MAX:
            _TG_POOL.append(conn)
        else:
            try:
                conn.close()
            except Exception:
                pass

def _tg_discard_connection(conn):
    try:
        conn.close()
    except Exception:
        pass

def telegram_api_call(method, params=None, timeout=30):
    token = CONFIG.get("bot_token", "YOUR_TELEGRAM_BOT_TOKEN")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[Telegram] WARNING: Bot token is not configured in config.json", file=sys.stderr)
        return None

    path = f"/bot{token}/{method}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(params).encode('utf-8') if params else None

    for attempt in range(2):
        conn = _tg_get_connection(timeout)
        try:
            conn.request("POST" if data else "GET", path, body=data, headers=headers)
            response = conn.getresponse()
            status = response.status
            body = response.read().decode('utf-8')
        except socket.timeout:
            _tg_discard_connection(conn)
            if method == "getUpdates":
                # Long-poll read timeouts are expected and harmless.
                return None
            continue
        except (http.client.HTTPException, OSError) as e:
            _tg_discard_connection(conn)
            if attempt == 0:
                continue
            print(f"[Telegram] API call error '{method}': {e}", file=sys.stderr)
            return None
        except Exception as e:
            _tg_discard_connection(conn)
            print(f"[Telegram] API call error '{method}': {e}", file=sys.stderr)
            return None

        if status == 200:
            _tg_release_connection(conn)
            try:
                return json.loads(body)
            except Exception as e:
                print(f"[Telegram] API call parse error '{method}': {e}", file=sys.stderr)
                return None
        if status == 429:
            _tg_release_connection(conn)
            try:
                retry_after = int(json.loads(body).get("parameters", {}).get("retry_after", 2))
            except Exception:
                retry_after = 2
            print(f"[Telegram] Rate limited on '{method}', retrying in {retry_after}s", file=sys.stderr)
            time.sleep(retry_after)
            continue
        _tg_release_connection(conn)
        print(f"[Telegram] API call HTTP error '{method}': {status} - {body}", file=sys.stderr)
        return None

    print(f"[Telegram] API call error '{method}': connection failed after retries", file=sys.stderr)
    return None

def send_message(chat_id, text, parse_mode="Markdown"):
    params = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    return telegram_api_call("sendMessage", params)

def edit_message(chat_id, message_id, text, parse_mode="Markdown"):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    return telegram_api_call("editMessageText", params)

def delete_message(chat_id, message_id):
    params = {"chat_id": chat_id, "message_id": message_id}
    return telegram_api_call("deleteMessage", params)

def broadcast_message(text, parse_mode="Markdown"):
    chats = CONFIG.get("subscribed_chats", [])
    if not chats:
        return {}
    sent_messages = {}
    lock = threading.Lock()

    def _send(chat_id):
        res = send_message(chat_id, text, parse_mode)
        if res and res.get("ok"):
            msg_id = res["result"]["message_id"]
            with lock:
                sent_messages[chat_id] = msg_id

    with ThreadPoolExecutor(max_workers=min(4, len(chats))) as pool:
        list(pool.map(_send, chats))
    return sent_messages

def send_document(chat_id, file_path, caption=None):
    token = CONFIG.get("bot_token", "YOUR_TELEGRAM_BOT_TOKEN")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[Telegram] WARNING: Bot token is not configured in config.json", file=sys.stderr)
        return None
        
    if not os.path.exists(file_path):
        print(f"[Telegram] Error: File to upload does not exist: {file_path}", file=sys.stderr)
        return None
        
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{token}/sendDocument",
        "-F", f"chat_id={chat_id}",
        "-F", f"document=@{file_path}"
    ]
    if caption:
        cmd += ["-F", f"caption={caption}"]
        
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except Exception:
            return None
    return None

def broadcast_document(file_path, caption=None):
    chats = CONFIG.get("subscribed_chats", [])
    for chat_id in chats:
        send_document(chat_id, file_path, caption)

def broadcast_edit(messages_map, text, parse_mode="Markdown"):
    if not messages_map:
        return

    def _edit(item):
        chat_id, msg_id = item
        edit_message(chat_id, msg_id, text, parse_mode)

    with ThreadPoolExecutor(max_workers=min(4, len(messages_map))) as pool:
        list(pool.map(_edit, messages_map.items()))

def pin_message(chat_id, message_id):
    params = {"chat_id": chat_id, "message_id": message_id}
    return telegram_api_call("pinChatMessage", params)

def broadcast_pin(messages_map):
    for chat_id, msg_id in messages_map.items():
        try:
            pin_message(chat_id, msg_id)
        except Exception as e:
            print(f"[Telegram] Failed to pin message {msg_id} in chat {chat_id}: {e}", file=sys.stderr)

def escape_markdown(text):
    if text is None:
        return ""
    s = str(text)
    for c in ['_', '*', '`', '[']:
        s = s.replace(c, f"\\{c}")
    return s

def escape_html(text):
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

# Bot command definitions for Telegram command autocomplete / preview
BOT_COMMANDS_DEFAULT = [
    {"command": "status", "description": "Check current active build progress"},
    {"command": "subscribe", "description": "Subscribe this chat to live build alerts"},
    {"command": "unsubscribe", "description": "Unsubscribe this chat from build alerts"},
    {"command": "specs", "description": "View build server specs (CPU, RAM, Disk)"},
    {"command": "ping", "description": "Check bot latency and responsiveness"},
    {"command": "help", "description": "View complete command list and guide"},
    {"command": "start", "description": "Start the bot and view welcome info"},
]

BOT_COMMANDS_GROUP = [
    {"command": "status", "description": "Check current active build progress"},
    {"command": "subscribe", "description": "Subscribe this group to live build alerts"},
    {"command": "unsubscribe", "description": "Unsubscribe this group from build alerts"},
    {"command": "specs", "description": "View build server specs (CPU, RAM, Disk)"},
    {"command": "ping", "description": "Check bot latency and responsiveness"},
    {"command": "help", "description": "View complete command list and guide"},
    {"command": "start", "description": "View bot introduction and info"},
]

BOT_COMMANDS_PRIVATE = [
    {"command": "start", "description": "Start the bot and view welcome info"},
    {"command": "status", "description": "Check current active build progress"},
    {"command": "subscribe", "description": "Subscribe this chat to live build alerts"},
    {"command": "unsubscribe", "description": "Unsubscribe this chat from build alerts"},
    {"command": "specs", "description": "View build server specs (CPU, RAM, Disk)"},
    {"command": "ping", "description": "Check bot latency and responsiveness"},
    {"command": "help", "description": "View complete command list and guide"},
]

BOT_COMMANDS_SUDO = [
    {"command": "start", "description": "Start the bot and view welcome info"},
    {"command": "status", "description": "Check current active build progress"},
    {"command": "subscribe", "description": "Subscribe this chat to live build alerts"},
    {"command": "unsubscribe", "description": "Unsubscribe this chat from build alerts"},
    {"command": "specs", "description": "View build server specs (CPU, RAM, Disk)"},
    {"command": "ping", "description": "Check bot latency and responsiveness"},
    {"command": "help", "description": "View complete command list and guide"},
    {"command": "sudolist", "description": "List configured bot sudo admins"},
    {"command": "restart", "description": "Restart the bot service (sudo)"},
    {"command": "reboot", "description": "Reboot the build server (sudo)"},
    {"command": "shutdown", "description": "Safely shut down the server (sudo)"},
]

BOT_COMMANDS_OWNER = BOT_COMMANDS_SUDO + [
    {"command": "addsudo", "description": "Add a user to sudo admins (owner)"},
    {"command": "delsudo", "description": "Remove a user from sudo admins (owner)"},
]

def register_user_commands(user_id, role="admin"):
    """Register custom command preview scope for a specific admin or owner chat."""
    try:
        uid = int(user_id) if str(user_id).isdigit() else user_id
        cmds = BOT_COMMANDS_OWNER if role == "owner" else BOT_COMMANDS_SUDO
        res = telegram_api_call("setMyCommands", {
            "commands": cmds,
            "scope": {"type": "chat", "chat_id": uid}
        })
        return bool(res and res.get("ok"))
    except Exception as e:
        print(f"[Telegram] Error registering custom commands for {user_id}: {e}", file=sys.stderr)
        return False

def unregister_user_commands(user_id):
    """Remove custom command preview scope for a user, reverting them to default/private scope."""
    try:
        uid = int(user_id) if str(user_id).isdigit() else user_id
        res = telegram_api_call("deleteMyCommands", {
            "scope": {"type": "chat", "chat_id": uid}
        })
        return bool(res and res.get("ok"))
    except Exception as e:
        print(f"[Telegram] Error deleting custom commands for {user_id}: {e}", file=sys.stderr)
        return False

def setup_bot_commands():
    """Register command lists and descriptions with Telegram for command preview / autocomplete across all scopes."""
    print("[Telegram] Registering bot commands for previews across chats and groups...")
    try:
        # 1. Default fallback scope for any chat
        telegram_api_call("setMyCommands", {
            "commands": BOT_COMMANDS_DEFAULT,
            "scope": {"type": "default"}
        })

        # 2. All group and supergroup chats
        telegram_api_call("setMyCommands", {
            "commands": BOT_COMMANDS_GROUP,
            "scope": {"type": "all_group_chats"}
        })

        # 3. Group administrators
        telegram_api_call("setMyCommands", {
            "commands": BOT_COMMANDS_GROUP,
            "scope": {"type": "all_chat_administrators"}
        })

        # 4. All private chats (regular users)
        telegram_api_call("setMyCommands", {
            "commands": BOT_COMMANDS_PRIVATE,
            "scope": {"type": "all_private_chats"}
        })

        # 5. Owner private chat commands
        owner_id = get_owner_id()
        if owner_id:
            register_user_commands(owner_id, role="owner")

        # 6. Configured sudo admins private chat commands
        for admin_id in get_admin_ids():
            if admin_id and admin_id != owner_id:
                register_user_commands(admin_id, role="admin")

        # 7. Explicitly set chat menu button to show commands list
        telegram_api_call("setChatMenuButton", {
            "menu_button": {"type": "commands"}
        })
        print("[Telegram] Bot commands and chat menu button registered successfully.")
        return True
    except Exception as e:
        print(f"[Telegram] Error setting up bot commands: {e}", file=sys.stderr)
        return False


def format_configuration(ctx):
    lines = ["🔧 *Configuration:*"]
    variant = ctx.get("variant", "Unknown")
    release = ctx.get("release", "Unknown")
    if variant and variant != "Unknown":
        lines.append(f"  🔹 *Variant:* *{escape_markdown(variant)}*")
    if release and release != "Unknown":
        lines.append(f"  📦 *Release:* *{escape_markdown(release)}*")
    platform_version = ctx.get("platform_version")
    if platform_version and platform_version != "Unknown":
        lines.append(f"  🤖 *Android Version:* *{escape_markdown(platform_version)}*")
    return "\n".join(lines)

def format_configuration_html(ctx):
    lines = ["🔧 <b>Configuration:</b>"]
    variant = ctx.get("variant", "Unknown")
    release = ctx.get("release", "Unknown")
    if variant and variant != "Unknown":
        lines.append(f"  🔹 <b>Variant:</b> <b>{escape_html(variant)}</b>")
    if release and release != "Unknown":
        lines.append(f"  📦 <b>Release:</b> <b>{escape_html(release)}</b>")
    platform_version = ctx.get("platform_version")
    if platform_version and platform_version != "Unknown":
        lines.append(f"  🤖 <b>Android Version:</b> <b>{escape_html(platform_version)}</b>")
    return "\n".join(lines)

def make_quoted_block_html(title, text):
    return f"<b>{title}</b>\n<pre>{escape_html(text)}</pre>"

def make_progress_bar(percentage, length=15):
    filled = int(round((percentage / 100.0) * length))
    return "█" * filled + "░" * (length - filled)

def format_duration(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def get_uptime_str():
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        h = int(uptime_seconds // 3600)
        m = int((uptime_seconds % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "Unknown"

def get_os_info():
    try:
        if hasattr(platform, 'freedesktop_os_release'):
            try:
                info = platform.freedesktop_os_release()
                if "PRETTY_NAME" in info:
                    return info["PRETTY_NAME"]
            except Exception:
                pass
        if os.path.exists('/etc/os-release'):
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        return line.split('=', 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return f"{platform.system()} {platform.release()}"

def get_kernel_version():
    try:
        return platform.release()
    except Exception:
        return "Unknown"

def get_sys_info():
    try:
        # CPU Info (Standard Library)
        cpu_count = os.cpu_count() or 1
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        # Approximate CPU percent from 1-minute load average
        cpu_percent = min(100.0, (load_avg[0] / cpu_count) * 100.0)
        
        # RAM Info (Linux proc filesystem parsing - zero-dependency)
        ram_total_gb, ram_used_gb, ram_percent = 0.0, 0.0, 0.0
        try:
            mem_total, mem_available = 0, 0
            if os.path.exists('/proc/meminfo'):
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if line.startswith('MemTotal:'):
                            mem_total = int(line.split()[1]) * 1024 # KB to Bytes
                        elif line.startswith('MemAvailable:'):
                            mem_available = int(line.split()[1]) * 1024
                if mem_total > 0:
                    mem_used = mem_total - mem_available
                    ram_total_gb = mem_total / (1024**3)
                    ram_used_gb = mem_used / (1024**3)
                    ram_percent = (mem_used / mem_total) * 100.0
        except Exception:
            pass
            
        # Disk Info (Standard Library shutil)
        disk_total_gb, disk_free_gb, disk_percent = 0.0, 0.0, 0.0
        try:
            total, used, free = shutil.disk_usage('/')
            disk_total_gb = total / (1024**3)
            disk_free_gb = free / (1024**3)
            disk_percent = (used / total) * 100.0 if total > 0 else 0.0
        except Exception:
            pass
            
        uptime_str = get_uptime_str()
        os_info = get_os_info()
        kernel_info = get_kernel_version()
        
        return (
            f"🐧 OS: {os_info}\n"
            f"🧬 Kernel: {kernel_info}\n"
            f"⚙️ CPU Load: {cpu_percent:.1f}% (Cores: {cpu_count}, 1m avg: {load_avg[0]:.2f})\n"
            f"💾 RAM Usage: {ram_used_gb:.1f} / {ram_total_gb:.1f} GB ({ram_percent:.1f}%)\n"
            f"📁 Disk Space: {disk_free_gb:.1f} GB free of {disk_total_gb:.1f} GB ({disk_percent:.1f}% used)\n"
            f"⏳ Uptime: {uptime_str}"
        )
    except Exception as e:
        return f"Error getting system info: {e}"

def _do_shutdown(chat_id):
    try:
        subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
    except Exception as e:
        print(f"[System] Shutdown error: {e}", file=sys.stderr)
        send_message(chat_id, f"❌ *Shutdown failed:* `{escape_markdown(str(e))}`")

def _do_reboot(chat_id):
    try:
        subprocess.run(["sudo", "reboot"], check=True)
    except Exception as e:
        print(f"[System] Reboot error: {e}", file=sys.stderr)
        send_message(chat_id, f"❌ *Reboot failed:* `{escape_markdown(str(e))}`")

def _do_restart(chat_id):
    try:
        res = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "tg-build-bot.service"])
        if res.returncode == 0:
            subprocess.run(["systemctl", "--user", "restart", "tg-build-bot.service"], check=True)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            start_script = os.path.join(script_dir, "start_bot.sh")
            if os.path.exists(start_script):
                subprocess.Popen(["/bin/bash", start_script])
                sys.exit(0)
            else:
                python = sys.executable
                os.execv(python, [python] + sys.argv)
    except Exception as e:
        print(f"[Bot] Restart error: {e}", file=sys.stderr)
        send_message(chat_id, f"❌ *Restart failed:* `{escape_markdown(str(e))}`")

def get_rom_name(top_path):
    config_path = os.path.join(top_path, ".repo", "manifests.git", "config")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', errors='ignore') as f:
                content = f.read()
            match = re.search(r'url\s*=\s*(.*)', content)
            if match:
                url = match.group(1).strip()
                if "git@" in url and ":" in url:
                    url = url.split(":")[-1]
                if "://" in url:
                    url = url.split("://")[-1]
                parts = [p for p in url.split("/") if p]
                if parts:
                    if "." in parts[0] or parts[0] == "git":
                        if len(parts) > 1:
                            org = parts[1]
                        else:
                            org = parts[0]
                    else:
                        org = parts[0]
                    if org.endswith(".git"):
                        org = org[:-4]
                    if org == "Infinity-X":
                        return "Project Infinity X"
                    return org
        except Exception as e:
            print(f"[ROM Name] Error reading .repo config: {e}", file=sys.stderr)
            
    manifest_xml = os.path.join(top_path, ".repo", "manifest.xml")
    if os.path.exists(manifest_xml):
        try:
            with open(manifest_xml, 'r', errors='ignore') as f:
                content = f.read()
            match = re.search(r'fetch="([^"]+)"', content)
            if match:
                fetch_url = match.group(1)
                parts = [p for p in fetch_url.replace(":", "/").split("/") if p]
                for p in parts:
                    if p in ["github.com", "gitlab.com", "git"]:
                        idx = parts.index(p)
                        if idx + 1 < len(parts):
                            org = parts[idx + 1]
                            if org.endswith(".git"):
                                org = org[:-4]
                            if org == "Infinity-X":
                                return "Project Infinity X"
                            return org
        except Exception:
            pass
            
    return "AOSP"

def get_build_vars(top_path):
    variant = "userdebug"
    release = "bp4a"
    soong_vars_path = os.path.join(top_path, "out", "soong", "soong.variables")
    if os.path.exists(soong_vars_path):
        try:
            with open(soong_vars_path, 'r', errors='ignore') as f:
                data = json.load(f)
            if "Target_build_variant" in data:
                variant = data["Target_build_variant"]
            if "Release_config" in data:
                release = data["Release_config"]
            elif "Target_release" in data:
                release = data["Target_release"]
            elif "Release_version" in data:
                release = data["Release_version"]
        except Exception as e:
            print(f"[BuildVars] Error reading soong.variables: {e}", file=sys.stderr)
    return variant, release

def get_formatted_start_time(epoch_time):
    local_t = time.localtime(epoch_time)
    base_str = time.strftime("%Y-%m-%d %I:%M:%S %p", local_t)
    is_dst = local_t.tm_isdst
    offset_seconds = -time.altzone if is_dst else -time.timezone
    offset_hours = offset_seconds // 3600
    offset_mins = abs(offset_seconds % 3600) // 60
    sign = "+" if offset_hours >= 0 else "-"
    offset_hours = abs(offset_hours)
    tz_str = f"UTC{sign}{offset_hours:02d}:{offset_mins:02d}"
    return f"{base_str} {tz_str}"

def format_duration_verbose(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h > 0:
        parts.append(f"{h} hour" if h == 1 else f"{h} hours")
    if m > 0:
        parts.append(f"{m} minute" if m == 1 else f"{m} minutes")
    if s > 0 or not parts:
        parts.append(f"{s} second" if s == 1 else f"{s} seconds")
    return ", ".join(parts)

def make_quoted_block(title, text):
    return f"*{title}*\n```\n{text}\n```"

# get_preview_url removed

def get_file_type(file_path):
    ext = os.path.splitext(file_path)[1].upper()
    if ext.startswith("."):
        ext = ext[1:]
    return ext if ext else "FILE"

def format_file_size(size_bytes):
    if size_bytes >= 1024**3:
        val = size_bytes / (1024**3)
        return f"{val:.2f} GiB".replace(".00", "")
    elif size_bytes >= 1024**2:
        val = size_bytes / (1024**2)
        return f"{val:.2f} MiB".replace(".00", "")
    elif size_bytes >= 1024:
        val = size_bytes / 1024
        return f"{val:.2f} KiB".replace(".00", "")
    return f"{size_bytes} Bytes"

def get_file_md5(file_path):
    try:
        res = subprocess.run(["md5sum", file_path], capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.split()[0]
    except Exception:
        pass
    import hashlib
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return "Unknown"

def extract_error_snippet(top_path, max_lines=20, max_chars=1500):
    """Extract the last few lines of out/error.log for inline display."""
    error_log_path = os.path.join(top_path, "out", "error.log")
    if not os.path.exists(error_log_path):
        return None
    try:
        with open(error_log_path, 'r', errors='ignore') as f:
            lines = f.readlines()
        # Strip ANSI escape codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        lines = [ansi_escape.sub('', l).rstrip() for l in lines]
        snippet = "\n".join(lines[-max_lines:]).strip()
        if not snippet:
            return None
        if len(snippet) > max_chars:
            snippet = snippet[-max_chars:]
        return snippet
    except Exception as e:
        print(f"[Post-Build] Error reading error.log: {e}", file=sys.stderr)
        return None

# Build Tracking Loop Thread
def track_build_log(top_path):
    print(f"[Tracker] Starting log tracking for: {top_path}")
    logfile = os.path.join(top_path, "out", "tg_build.log")
    
    # Wait for the log file to be created (up to 15 seconds)
    retries = 15
    while retries > 0:
        with ACTIVE_BUILDS_LOCK:
            if top_path not in ACTIVE_BUILDS or ACTIVE_BUILDS[top_path]["stop_flag"].is_set():
                return
        if os.path.exists(logfile):
            break
        time.sleep(1.0)
        retries -= 1
        
    if not os.path.exists(logfile):
        print(f"[Tracker] Log file not found after retries: {logfile}", file=sys.stderr)
        return
        
    print(f"[Tracker] Log file found. Tailing: {logfile}")
    
    regex = re.compile(r'\[\s*(?:(\d+)%\s+)?(\d+)/(\d+)(?:\s+[^\]]*)?\]\s*(.*)')
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    
    last_update = 0
    
    with open(logfile, 'r', errors='ignore') as f:
        # Keep reading lines
        while True:
            with ACTIVE_BUILDS_LOCK:
                if top_path not in ACTIVE_BUILDS:
                    break
                ctx = ACTIVE_BUILDS[top_path]
                stop_requested = ctx["stop_flag"].is_set()
                
            line = f.readline()
            if not line:
                # Rate-limited live progress updates to Telegram even during quiet compiler phases
                now = time.time()
                if now - last_update >= 10:
                    update_live_progress(top_path)
                    last_update = now
                if stop_requested:
                    break
                time.sleep(0.5)
                continue
                
            # Strip ANSI escape sequences (especially when running in a real PTY/TTY)
            clean_line = ansi_escape.sub('', line).strip()
            match = regex.match(clean_line)
            if match:
                pct_val = match.group(1)
                completed = int(match.group(2))
                total = int(match.group(3))
                action = match.group(4)
                
                if pct_val is not None:
                    percentage = int(pct_val)
                else:
                    percentage = int((completed / total) * 100) if total > 0 else 0
                
                # Ensure percentage is between 0 and 100
                percentage = min(100, max(0, percentage))
                
                with ACTIVE_BUILDS_LOCK:
                    if top_path in ACTIVE_BUILDS:
                        ACTIVE_BUILDS[top_path].update({
                            "percentage": percentage,
                            "completed": completed,
                            "total": total,
                            "action": action
                        })
            
            # Rate-limited live progress updates to Telegram (every 10 seconds)
            now = time.time()
            if now - last_update >= 10:
                update_live_progress(top_path)
                last_update = now
                
    # Final log parse check and final message update
    update_live_progress(top_path)

def update_live_progress(top_path):
    with ACTIVE_BUILDS_LOCK:
        if top_path not in ACTIVE_BUILDS:
            return
        ctx = ACTIVE_BUILDS[top_path]
        
    elapsed = time.time() - ctx["start_time"]
    elapsed_str = format_duration_verbose(elapsed)
    
    percentage = ctx["percentage"]
    completed = ctx["completed"]
    total = ctx["total"]
    action = ctx["action"]
    device = ctx["device"]
    messages_map = ctx["messages"]
    rom_name = ctx.get("rom_name", "AOSP")
    
    progress_bar = make_progress_bar(percentage, length=10)
    
    # Get dynamic sys_info
    sys_stats = get_sys_info()
    sys_info_quoted = make_quoted_block_html("🖥️ System info:", sys_stats)
    
    start_time_str = get_formatted_start_time(ctx["start_time"])

    rom_name_esc = escape_html(rom_name)
    device_esc = escape_html(device)
    start_time_esc = escape_html(start_time_str)
    elapsed_esc = escape_html(elapsed_str)
    percentage_esc = escape_html(f"{percentage:.2f}%")
    actions_esc = escape_html(f"{completed}/{total}")

    # ETA estimation
    eta_str = "N/A"
    if percentage > 0:
        eta_seconds = (elapsed / (percentage / 100.0)) - elapsed
        if eta_seconds > 0:
            eta_str = format_duration_verbose(eta_seconds)

    config_block = format_configuration_html(ctx)

    text = (
        f"⚙️ <b>Build In Progress</b>\n"
        f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
        f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
        f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
        f"📈 <b>Progress:</b> <b>[{progress_bar}] {percentage_esc}</b>\n"
        f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
        f"⏱️ <b>Elapsed:</b> <b>{elapsed_esc}</b>\n"
        f"⏳ <b>ETA:</b> <b>{escape_html(eta_str)}</b>\n\n"
        f"{config_block}\n\n"
        f"{sys_info_quoted}"
    )
    
    broadcast_edit(messages_map, text, parse_mode="HTML")

def send_startup_message():
    text = "🤖 *Bot is online!* Ready to track builds."
    recipients = set(CONFIG.get("subscribed_chats", []))
    owner = get_owner_id()
    if owner:
        recipients.add(owner)
    for cid in recipients:
        try:
            send_message(cid, text)
        except Exception as e:
            print(f"[Telegram] Error sending startup message to {cid}: {e}", file=sys.stderr)
    if recipients:
        print(f"[Telegram] Sent startup welcome message to {len(recipients)} chat(s).")

# Telegram polling daemon
def telegram_polling():
    print("[Telegram] Starting bot command polling loop...")
    offset = 0

    # Send a startup notification to server logs and subscribed chats
    res = None
    for _ in range(5):
        res = telegram_api_call("getMe")
        if res and res.get("ok"):
            break
        time.sleep(2)

    if res and res.get("ok"):
        global BOT_USERNAME
        BOT_USERNAME = res["result"].get("username")
        print(f"[Telegram] Connected as @{BOT_USERNAME}")
        setup_bot_commands()
        send_startup_message()
    else:
        print("[Telegram] Failed to connect. Token might be missing or invalid.", file=sys.stderr)

    while True:
        try:
            # Use timeout=25 so Telegram's own 20s long-poll timeout fires first.
            # This avoids the old bug where urllib's 10s timeout hit before Telegram's,
            # generating a continuous spam of "The read operation timed out" errors.
            updates = telegram_api_call("getUpdates", {"offset": offset, "timeout": 20}, timeout=25)
            if updates and updates.get("ok") and updates.get("result"):
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if message and message.get("text"):
                        handle_telegram_message(message)
        except Exception as e:
            print(f"[Telegram] Polling loop exception: {e}", file=sys.stderr)
        time.sleep(0.5)

def handle_telegram_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    if not text:
        return
    
    sender = msg.get("from") or {}
    user_id = sender.get("id") or chat_id
    
    parts = text.split()
    first_word = parts[0]
    if '@' in first_word:
        cmd_part, bot_target = first_word.split('@', 1)
        if BOT_USERNAME and bot_target.lower() != BOT_USERNAME.lower():
            return
        cmd = cmd_part.lower()
    else:
        cmd = first_word.lower()
    
    if cmd == "/start":
        welcome = (
            f"🚀 *AOSP Build Tracker Bot*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Welcome! This bot tracks AOSP compilation pipelines in real-time.\n\n"
            f"📌 *Commands Available:*\n"
            f"• `/subscribe` - Add this chat/group to receive live build alerts.\n"
            f"• `/unsubscribe` - Remove this chat from receiving alerts.\n"
            f"• `/status` - Check current active build progress.\n"
            f"• `/specs` - View server specs (OS, Kernel, CPU, RAM, Disk).\n"
            f"• `/ping` - Check if the bot is alive and active.\n"
            f"• `/help` - View complete command list."
        )
        send_message(chat_id, welcome)
        
    elif cmd == "/subscribe":
        config = CONFIG
        if chat_id not in config["subscribed_chats"]:
            config["subscribed_chats"].append(chat_id)
            save_config(config)
            send_message(chat_id, "✅ *Successfully subscribed!* This chat will now receive real-time build start, progress, and compilation result updates.")
        else:
            send_message(chat_id, "ℹ️ This chat is *already* subscribed to build updates.")
            
    elif cmd == "/unsubscribe":
        config = CONFIG
        if chat_id in config["subscribed_chats"]:
            config["subscribed_chats"].remove(chat_id)
            save_config(config)
            send_message(chat_id, "❌ *Unsubscribed!* You will no longer receive build tracking updates in this chat.")
        else:
            send_message(chat_id, "ℹ️ This chat was not subscribed.")
            
    elif cmd == "/status":
        with ACTIVE_BUILDS_LOCK:
            active_list = list(ACTIVE_BUILDS.values())
            
        if not active_list:
            send_message(chat_id, "💤 *No active builds.* There are currently no ROM compilation tasks executing on the server.")
            return
            
        # Compile status for all active builds
        status_text = ""
        for ctx in active_list:
            elapsed = time.time() - ctx["start_time"]
            elapsed_str = format_duration(elapsed)
            percentage = ctx["percentage"]
            progress_bar = make_progress_bar(percentage)
            
            device_esc = escape_markdown(ctx['device'])
            elapsed_esc = escape_markdown(elapsed_str)
            tasks_esc = escape_markdown(f"{ctx['completed']:,} / {ctx['total']:,}")
            
            status_text += (
                f"📱 *Active Build Details:*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📱 *Device:* *{device_esc}*\n"
                f"⏱️ *Elapsed:* *{elapsed_esc}*\n"
                f"📈 *Progress:* `[{progress_bar}]` *{percentage}%*\n"
                f"🛠️ *Actions:* *{tasks_esc}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )
        sys_info = get_sys_info()
        status_text += f"\n🖥️ *System Specs:*\n```\n{sys_info}\n```"
        send_message(chat_id, status_text)
        
    elif cmd in ("/specs", "/sysinfo"):
        sys_info = get_sys_info()
        send_message(chat_id, f"🖥️ *Build Server Specs:*\n━━━━━━━━━━━━━━━━━━━━━\n```\n{sys_info}\n```")
        
    elif cmd == "/ping":
        sent_date = msg.get("date")
        if sent_date:
            elapsed_ms = int((time.time() - sent_date) * 1000)
            resp_str = f" *{elapsed_ms}ms*"
        else:
            resp_str = ""
        send_message(chat_id, f"🏓 *Pong!*{resp_str}")

    elif cmd == "/help":
        help_text = (
            f"📚 *Build Tracker Bot Commands*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Public Commands:*\n"
            f"• `/start` — Welcome message and bot intro.\n"
            f"• `/subscribe` — Subscribe this chat to build alerts.\n"
            f"• `/unsubscribe` — Unsubscribe this chat from alerts.\n"
            f"• `/status` — Show all active builds with progress.\n"
            f"• `/specs` — Show server specs (OS, Kernel, CPU, RAM, Disk).\n"
            f"• `/ping` — Check bot latency.\n"
            f"• `/help` — Show this command list.\n\n"
            f"🛡️ *Sudo Commands (Admin/Owner):*\n"
            f"• `/shutdown` — Safely shut down the server.\n"
            f"• `/reboot` — Reboot the server.\n"
            f"• `/restart` — Restart the bot service.\n"
            f"• `/sudolist` — List configured sudo admins.\n"
            f"• `/synccommands` — Refresh Telegram command autocomplete list.\n\n"
            f"👑 *Owner Commands:*\n"
            f"• `/addsudo <user_id>` — Add a user to sudo admins.\n"
            f"• `/delsudo <user_id>` — Remove a user from sudo admins.\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 Use `m bacon`, `mka`, or `make` in your AOSP source tree to trigger build tracking."
        )
        send_message(chat_id, help_text)

    elif cmd == "/addsudo":
        if not is_owner(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* Only the bot owner can add sudo users.")
            return

        target_id = None
        reply = msg.get("reply_to_message")
        if reply and reply.get("from"):
            target_id = reply["from"].get("id")
        elif len(parts) > 1:
            arg = parts[1].strip()
            if arg.lstrip('-').isdigit():
                target_id = int(arg)
            elif arg.startswith('@'):
                send_message(chat_id, f"⚠️ Cannot resolve username `{arg}` directly. Please use the user's numeric ID (e.g. `/addsudo 123456789`) or reply to their message with `/addsudo`.")
                return

        if not target_id:
            send_message(chat_id, "ℹ️ *Usage:* `/addsudo <user_id>` or reply to a user's message with `/addsudo`")
            return

        if is_owner(target_id):
            send_message(chat_id, f"ℹ️ User `{target_id}` is already the bot owner.")
            return

        admin_ids = get_admin_ids()
        if target_id in admin_ids or str(target_id) in [str(a) for a in admin_ids]:
            send_message(chat_id, f"ℹ️ User `{target_id}` is already a sudo admin.")
            return

        if "admin_ids" not in CONFIG or not isinstance(CONFIG["admin_ids"], list):
            CONFIG["admin_ids"] = []
        CONFIG["admin_ids"].append(target_id)
        save_config(CONFIG)
        register_user_commands(target_id, role="admin")
        send_message(chat_id, f"✅ *Success:* User `{target_id}` has been added as a sudo admin.")

    elif cmd in ("/delsudo", "/rmsudo"):
        if not is_owner(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* Only the bot owner can remove sudo users.")
            return

        target_id = None
        reply = msg.get("reply_to_message")
        if reply and reply.get("from"):
            target_id = reply["from"].get("id")
        elif len(parts) > 1:
            arg = parts[1].strip()
            if arg.lstrip('-').isdigit():
                target_id = int(arg)

        if not target_id:
            send_message(chat_id, "ℹ️ *Usage:* `/delsudo <user_id>` or reply to a user's message with `/delsudo`")
            return

        admin_ids = get_admin_ids()
        if target_id not in admin_ids and str(target_id) not in [str(a) for a in admin_ids]:
            send_message(chat_id, f"ℹ️ User `{target_id}` is not in the sudo admin list.")
            return

        CONFIG["admin_ids"] = [a for a in admin_ids if a != target_id and str(a) != str(target_id)]
        if "admins" in CONFIG and isinstance(CONFIG["admins"], list):
            CONFIG["admins"] = [a for a in CONFIG["admins"] if a != target_id and str(a) != str(target_id)]
        save_config(CONFIG)
        unregister_user_commands(target_id)
        send_message(chat_id, f"✅ *Success:* User `{target_id}` removed from sudo admins.")

    elif cmd in ("/sudolist", "/admins"):
        if not is_sudo(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* You do not have permission to execute this command. Sudo access required.")
            return

        owner = get_owner_id()
        admins = get_admin_ids()
        role = get_user_role(user_id)
        
        text = f"👑 *Bot Roles & Permissions*\n━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"👑 *Owner:* `{owner if owner is not None else 'Not Configured'}`\n"
        if admins:
            admins_str = "\n".join([f"• `{a}`" for a in admins])
            text += f"🛡️ *Sudo Admins ({len(admins)}):*\n{admins_str}\n"
        else:
            text += f"🛡️ *Sudo Admins:* _None_\n"
        text += f"━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"👤 *Your Role:* *{role.capitalize()}*"
        send_message(chat_id, text)

    elif cmd == "/shutdown":
        if not is_sudo(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* You do not have permission to execute this command. Sudo access required.")
            return

        send_message(chat_id, "🛑 *Shutting down the server now...*")
        threading.Timer(1.5, _do_shutdown, args=[chat_id]).start()

    elif cmd == "/reboot":
        if not is_sudo(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* You do not have permission to execute this command. Sudo access required.")
            return

        send_message(chat_id, "🔄 *Rebooting the server now...*")
        threading.Timer(1.5, _do_reboot, args=[chat_id]).start()

    elif cmd == "/restart":
        if not is_sudo(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* You do not have permission to execute this command. Sudo access required.")
            return

        send_message(chat_id, "🔄 *Restarting bot service now...*")
        threading.Timer(1.5, _do_restart, args=[chat_id]).start()

    elif cmd in ("/synccommands", "/updatecommands"):
        if not is_sudo(user_id):
            send_message(chat_id, "⚠️ *Access Denied:* You do not have permission to execute this command. Sudo access required.")
            return

        ok = setup_bot_commands()
        if ok:
            send_message(chat_id, "✅ *Command previews synchronized successfully with Telegram!*")
        else:
            send_message(chat_id, "❌ *Failed to synchronize commands with Telegram.* Check daemon logs.")

# Detect the newest ROM zip and matching OTA JSON across various ROM naming conventions
def parse_filename_epoch(filename, ref_year=None):
    if ref_year is None:
        ref_year = datetime.datetime.now().year

    m = re.search(r"(20[2-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[-_]([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)", filename)
    if m:
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), tzinfo=datetime.timezone.utc)
        return dt.timestamp(), True

    m = re.search(r"(20[2-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[-_]([01]\d|2[0-3])([0-5]\d)(?!\d)", filename)
    if m:
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), 0, tzinfo=datetime.timezone.utc)
        return dt.timestamp(), True

    m = re.search(r"(20[2-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)", filename)
    if m:
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), tzinfo=datetime.timezone.utc)
        return dt.timestamp(), True

    m = re.search(r"(20[2-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)(?!\d)", filename)
    if m:
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), 0, tzinfo=datetime.timezone.utc)
        return dt.timestamp(), True

    m = re.search(r"(20[2-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])(?!\d)", filename)
    if m:
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), 0, 0, tzinfo=datetime.timezone.utc)
        return dt.timestamp(), True

    m = re.search(r"(20[2-3]\d)[-\.](0[1-9]|1[0-2])[-\.](0[1-9]|[12]\d|3[01])(?:[-_]([01]\d|2[0-3])(?::?([0-5]\d))?)?(?!\d)", filename)
    if m:
        h = int(m.group(4)) if m.group(4) else 0
        mn = int(m.group(5)) if m.group(5) else 0
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), h, mn, 0, tzinfo=datetime.timezone.utc)
        return dt.timestamp(), bool(m.group(4))

    m = re.search(r"(20[2-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)", filename)
    if m:
        dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, 0, 0, tzinfo=datetime.timezone.utc)
        return dt.timestamp(), False

    m = re.search(r"(?:^|[^0-9])(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)(?:[^0-9]|$)", filename)
    if m:
        dt = datetime.datetime(ref_year, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), 0, tzinfo=datetime.timezone.utc)
        return dt.timestamp(), True

    return 0.0, False

def extract_json_zip_name(json_path):
    try:
        with open(json_path, "r", errors="ignore") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "response" in data and isinstance(data["response"], list) and len(data["response"]) > 0:
                return data["response"][0].get("filename")
            elif "filename" in data:
                return data["filename"]
    except Exception:
        pass
    return None

def find_ota_json_files(product_dir, device=""):
    d_short = device.split("_")[-1] if "_" in device else device
    candidates = []
    search_dirs = [product_dir]
    try:
        for entry in os.scandir(product_dir):
            if entry.is_dir() and not entry.name.startswith("."):
                search_dirs.append(entry.path)
    except Exception:
        pass

    ignored_prefixes = (
        "installed-files", "module-info", "apex_info", "target_files",
        "compatibility_matrix", "device_manifest", "framework_manifest"
    )

    for sdir in search_dirs:
        try:
            for fname in os.listdir(sdir):
                if not fname.endswith(".json") or fname.startswith("."):
                    continue
                if any(fname.startswith(p) for p in ignored_prefixes):
                    continue
                candidates.append(os.path.join(sdir, fname))
        except Exception:
            pass

    return candidates

def find_best_rom_zip(product_dir, device="", start_time=None, top_path=None, return_score=False):
    if not product_dir or not os.path.isdir(product_dir):
        return (None, None, None) if return_score else (None, None)

    d_short = device.split("_")[-1] if "_" in device else device
    ref_year = datetime.datetime.fromtimestamp(start_time, tz=datetime.timezone.utc).year if start_time else datetime.datetime.now().year

    ota_jsons = find_ota_json_files(product_dir, device)
    if not ota_jsons and top_path:
        out_prod = os.path.join(top_path, "out", "target", "product")
        if os.path.isdir(out_prod):
            try:
                for root, dirs, files in os.walk(out_prod):
                    rel = os.path.relpath(root, out_prod)
                    if rel.count(os.sep) >= 3:
                        dirs.clear()
                    for f in files:
                        if f.endswith(".json") and not f.startswith("."):
                            if not any(f.startswith(p) for p in ("installed-files", "module-info", "apex_info", "target_files")):
                                if d_short and d_short.lower() in f.lower():
                                    ota_jsons.append(os.path.join(root, f))
            except Exception:
                pass

    json_map = {}
    for jpath in ota_jsons:
        ref_zip = extract_json_zip_name(jpath)
        if ref_zip:
            json_map[os.path.basename(ref_zip)] = jpath

    ignored_substrings = ("target_files", "symbols", "otacerts", "tests")
    candidates = []

    try:
        files = os.listdir(product_dir)
    except Exception as e:
        print(f"[Post-Build] Error listing product dir {product_dir}: {e}", file=sys.stderr)
        return (None, None, None) if return_score else (None, None)

    for fname in files:
        if not fname.endswith(".zip") or fname.startswith("."):
            continue
        fl = fname.lower()
        if any(ign in fl for ign in ignored_substrings):
            continue

        fpath = os.path.join(product_dir, fname)
        if not os.path.isfile(fpath):
            continue

        try:
            stat_res = os.stat(fpath)
            fsize = stat_res.st_size
            mtime = stat_res.st_mtime
            ctime = stat_res.st_ctime
        except Exception:
            continue

        fs_time = max(mtime, ctime)
        ts_epoch, has_time = parse_filename_epoch(fname, ref_year)
        is_fresh = 1 if (start_time and fs_time >= (start_time - 120)) else 0
        device_match = 1 if (d_short and d_short.lower() in fl) else 0
        json_match = 1 if fname in json_map else 0
        is_branded = 1 if (ts_epoch > 0 or json_match or not fl.endswith("-ota.zip")) else 0

        score = (
            device_match,
            is_branded,
            json_match,
            ts_epoch,
            is_fresh,
            fs_time,
            fsize
        )
        candidates.append((score, fpath))

    if not candidates:
        return (None, None, None) if return_score else (None, None)

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_zip = candidates[0]
    best_zip_name = os.path.basename(best_zip)

    matched_json = json_map.get(best_zip_name)
    if not matched_json and ota_jsons:
        device_jsons = [j for j in ota_jsons if (d_short and d_short.lower() in os.path.basename(j).lower())]
        matched_json = max(device_jsons, key=os.path.getmtime) if device_jsons else max(ota_jsons, key=os.path.getmtime)

    if return_score:
        return best_zip, matched_json, best_score
    return best_zip, matched_json

def process_post_build(top_path, ctx, exit_code):
    time.sleep(1.5)
    
    # Calculate duration
    duration = time.time() - ctx["start_time"]
    duration_str = format_duration_verbose(duration)
    
    # Determine status
    status = "SUCCESS" if exit_code == 0 else "FAILED"
    
    # Delete the pinned live updates message so we don't clutter the chat
    for chat_id, msg_id in ctx["messages"].items():
        try:
            delete_message(chat_id, msg_id)
        except Exception:
            pass
            
    # Auto-detect ROM details as fallbacks
    rom_name = ctx.get("rom_name")
    if not rom_name or rom_name == "AOSP":
        rom_name = get_rom_name(top_path)
    variant = ctx.get("variant")
    release = ctx.get("release")
    if not variant or not release or variant == "Unknown" or release == "Unknown":
        v_det, r_det = get_build_vars(top_path)
        if not variant or variant == "Unknown":
            variant = v_det
        if not release or release == "Unknown":
            release = r_det
            
    # Save the fallbacks back to ctx so format_configuration uses them
    ctx["variant"] = variant
    ctx["release"] = release
            
    device = ctx["device"]
    start_time_str = get_formatted_start_time(ctx["start_time"])
    
    rom_name_esc = escape_html(rom_name)
    device_esc = escape_html(device)
    start_time_esc = escape_html(start_time_str)
    duration_esc = escape_html(duration_str)
    actions_esc = escape_html(f"{ctx['completed']}/{ctx['total']}")
    
    config_block = format_configuration_html(ctx)
            
    if status == "SUCCESS":
        # Send initial success status to notify the user that processing has started
        processing_msg = broadcast_message(
            f"✅ <b>Build Completed</b>\n"
            f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
            f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
            f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
            f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
            f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
            f"{config_block}\n\n"
            f"📤 <b>Status:</b> Scanning output files &amp; preparing uploads...",
            parse_mode="HTML"
        )
        
        # Let's locate the output directory using our extremely robust search logic
        product_dir = None
        
        # 1. Try exact device
        d_path = os.path.join(top_path, "out", "target", "product", device)
        if os.path.isdir(d_path):
            product_dir = d_path
        # 2. Try stripped device
        elif "_" in device:
            d_short = device.split("_")[-1]
            d_path_short = os.path.join(top_path, "out", "target", "product", d_short)
            if os.path.isdir(d_path_short):
                product_dir = d_path_short
                
        # 3. Fallback to scanning out/target/product/
        if not product_dir:
            base_product_path = os.path.join(top_path, "out", "target", "product")
            if os.path.isdir(base_product_path):
                try:
                    subdirs = [os.path.join(base_product_path, d) for d in os.listdir(base_product_path) if os.path.isdir(os.path.join(base_product_path, d))]
                    matching_dirs = []
                    for sd in subdirs:
                        if any(f.endswith(".zip") for f in os.listdir(sd)):
                            matching_dirs.append(sd)
                    if matching_dirs:
                        best_sd = None
                        best_score = None
                        for sd in matching_dirs:
                            best_z, _, score = find_best_rom_zip(sd, device, start_time=ctx.get("start_time"), top_path=top_path, return_score=True)
                            if best_z and (best_score is None or score > best_score):
                                best_sd = sd
                                best_score = score
                        product_dir = best_sd if best_sd else max(matching_dirs, key=os.path.getmtime)
                except Exception as e:
                    print(f"[Post-Build] Exception scanning base product path: {e}", file=sys.stderr)
                    
        if not product_dir:
            # Fallback output if out directory couldn't be discovered at all
            failed_card = (
                f"✅ <b>Build Completed</b>\n"
                f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
                f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
                f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
                f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
                f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
                f"{config_block}\n\n"
                f"❌ <b>Output Error:</b> Could not locate build output directory under <code>out/target/product/</code>."
            )
            broadcast_edit(processing_msg, failed_card, parse_mode="HTML")
            return
            
        print(f"[Post-Build] Located product directory: {product_dir}")
        
        rom_zip, json_file = find_best_rom_zip(product_dir, device, start_time=ctx.get("start_time"), top_path=top_path)
            
        if not rom_zip:
            failed_card = (
                f"✅ <b>Build Completed</b>\n"
                f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
                f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
                f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
                f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
                f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
                f"{config_block}\n\n"
                f"❌ <b>Output Error:</b> No target ROM zip file found in <code>{escape_html(product_dir)}</code>."
            )
            broadcast_edit(processing_msg, failed_card, parse_mode="HTML")
            return

        print(f"[Post-Build] Selected newest ROM zip: {rom_zip}")
        if json_file:
            print(f"[Post-Build] Selected matching OTA JSON: {json_file}")
 
        # Detect other files
        upload_queue = []
        upload_queue.append(("ROM", rom_zip))
        
        # boot.img
        boot_img = os.path.join(product_dir, "boot.img")
        if os.path.exists(boot_img):
            upload_queue.append(("BOOT_IMG", boot_img))
            
        # dtbo.img (if exists)
        dtbo_img = os.path.join(product_dir, "dtbo.img")
        if os.path.exists(dtbo_img):
            upload_queue.append(("DTBO_IMG", dtbo_img))
            
        # init_boot.img (newer devices)
        init_boot_img = os.path.join(product_dir, "init_boot.img")
        if os.path.exists(init_boot_img):
            upload_queue.append(("INIT_BOOT", init_boot_img))

        # recovery.img / vendor_boot.img (whichever is available)
        recovery_img = os.path.join(product_dir, "recovery.img")
        vendor_boot = os.path.join(product_dir, "vendor_boot.img")
        if os.path.exists(recovery_img):
            upload_queue.append(("RECOVERY_IMG", recovery_img))
        elif os.path.exists(vendor_boot):
            upload_queue.append(("VENDOR_BOOT", vendor_boot))
            
        # super_empty.img
        super_empty = os.path.join(product_dir, "super_empty.img")
        if os.path.exists(super_empty):
            upload_queue.append(("SUPER_EMPTY", super_empty))
            
        # OTA JSON if found
        if json_file and os.path.exists(json_file):
            upload_queue.append(("OTA_JSON", json_file))
            
        # Collect metadata first
        files_metadata = []
        for file_type, file_path in upload_queue:
            fname = os.path.basename(file_path)
            ftype = get_file_type(file_path)
            fsize = format_file_size(os.path.getsize(file_path))
            fmd5 = get_file_md5(file_path)
            files_metadata.append({
                "type_key": file_type,
                "path": file_path,
                "name": fname,
                "type": ftype,
                "size": fsize,
                "md5": fmd5,
                "link": ""
            })
        
        # Upload all files concurrently via thread pool
        names_for_status = ", ".join(escape_html(it["name"]) for it in files_metadata)
        current_status = (
            f"✅ <b>Build Completed</b>\n"
            f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
            f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
            f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
            f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
            f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
            f"{config_block}\n\n"
            f"📤 <b>Uploading:</b> <code>{names_for_status}</code> to Gofile..."
        )
        broadcast_edit(processing_msg, current_status, parse_mode="HTML")

        def _upload_one(item):
            url = upload_to_gofile(item["path"])
            if url:
                item["link"] = url

        with ThreadPoolExecutor(max_workers=min(4, len(files_metadata))) as pool:
            list(pool.map(_upload_one, files_metadata))
                
        # Build files lines for collapsible quote box
        files_lines = []
        for idx, item in enumerate(files_metadata, 1):
            name_esc = escape_html(item['name'])
            type_esc = escape_html(item['type'])
            size_esc = escape_html(item['size'])
            md5_esc = escape_html(item['md5'])
            link_html = f'<a href="{escape_html(item["link"])}">{escape_html(item["link"])}</a>' if item['link'] else "<i>Upload Failed</i>"
            
            files_lines.append(f"<b>{idx}. File:</b> <code>{name_esc}</code>")
            files_lines.append(f"   Type: {type_esc} | Size: {size_esc}")
            files_lines.append(f"   MD5: <code>{md5_esc}</code>")
            files_lines.append(f"   Link: {link_html}")
            if idx < len(files_metadata):
                files_lines.append("") # empty line between files
                
        files_content = "\n".join(files_lines)
        
        success_card = (
            f"✅ <b>Build Completed</b>\n"
            f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
            f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
            f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
            f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
            f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
            f"{config_block}\n\n"
            f"<blockquote expandable>\n"
            f"<b>Rom Files uploaded:</b>\n"
            f"{files_content}\n"
            f"</blockquote>"
        )
        broadcast_edit(processing_msg, success_card, parse_mode="HTML")
        broadcast_pin(processing_msg)
        
    else:
        # Failure logic
        error_snippet = extract_error_snippet(top_path)
        snippet_block = ""
        if error_snippet:
            snippet_block = (
                f"\n\n📄 <b>Error Snippet (last lines):</b>\n"
                f"<pre>{escape_html(error_snippet)}</pre>"
            )
        failure_card = (
            f"❌ <b>Build Failed</b>\n"
            f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
            f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
            f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
            f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
            f"🛠️ <b>Actions:</b> <b>{actions_esc} (1 failed)</b>\n"
            f"{config_block}\n\n"
            f"📄 Check logs for details. Error log uploaded if available."
            f"{snippet_block}"
        )
        broadcast_message(failure_card, parse_mode="HTML")
        
        # Broadcast the existing error.log document if it exists
        error_log_path = os.path.join(top_path, "out", "error.log")
        if os.path.exists(error_log_path):
            broadcast_document(error_log_path, caption=f"🔍 Error log trace for device `{ctx['device']}`")

# HTTP Server API Interface
class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to suppress standard HTTP logging to console
        return

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
        except Exception:
            print(f"[API] Error: Invalid JSON payload in POST to {self.path}")
            self.send_error(400, "Invalid JSON payload")
            return
            
        print(f"[API] Received POST request to {self.path} with data {data}")
        if self.path == '/api/start':
            self.handle_start(data)
        elif self.path == '/api/stop':
            self.handle_stop(data)
        else:
            print(f"[API] Error: Path {self.path} not matched")
            self.send_error(404, "Endpoint not found")

    def handle_start(self, data):
        top_path = data.get("top")
        command = data.get("command", "m bacon")
        device = data.get("device", "Unknown")
        if "_" in device:
            device = device.split("_", 1)[1]
        targets = data.get("targets", "bacon")
        variant = data.get("variant", "Unknown")
        release = data.get("release", "Unknown")
        
        # Extract new environment variables
        platform_version = data.get("platform_version", "Unknown")
        target_product = data.get("target_product", "Unknown")
        target_arch = data.get("target_arch", "Unknown")
        build_id = data.get("build_id", "Unknown")
        user = data.get("user", "Unknown")
        host = data.get("host", "Unknown")
        
        if not top_path:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing 'top' parameter"}).encode())
            return
            
        print(f"[API] Build starting in workspace: {top_path}")
        
        # Extract ROM name
        rom_name = get_rom_name(top_path)
        
        # Fallbacks for variant / release
        if not variant or variant == "Unknown":
            v_det, r_det = get_build_vars(top_path)
            variant = v_det
            if not release or release == "Unknown":
                release = r_det
        elif not release or release == "Unknown":
            _, r_det = get_build_vars(top_path)
            release = r_det

        # Broadcast initial "Build Starting" message
        start_time_epoch = time.time()
        start_time_str = get_formatted_start_time(start_time_epoch)
        progress_bar = make_progress_bar(0.0, length=10)
        sys_stats = get_sys_info()
        sys_info_quoted = make_quoted_block_html("🖥️ System info:", sys_stats)
        rom_name_esc = escape_html(rom_name)
        device_esc = escape_html(device)
        start_time_esc = escape_html(start_time_str)
        
        ctx_temp = {
            "variant": variant,
            "release": release,
            "platform_version": platform_version,
            "target_product": target_product,
            "target_arch": target_arch,
            "build_id": build_id,
            "user": user,
            "host": host
        }
        config_block = format_configuration_html(ctx_temp)
        
        notify_text = (
            f"⚙️ <b>Build In Progress</b>\n"
            f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
            f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
            f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
            f"📈 <b>Progress:</b> <b>[{progress_bar}] 0.00%</b>\n"
            f"🛠️ <b>Actions:</b> <b>0/0</b>\n"
            f"⏱️ <b>Elapsed:</b> <b>0 seconds</b>\n\n"
            f"{config_block}\n\n"
            f"{sys_info_quoted}"
        )
        
        messages_map = broadcast_message(notify_text, parse_mode="HTML")
        
        with ACTIVE_BUILDS_LOCK:
            # If there's an existing tracker for this path, clean it up first
            if top_path in ACTIVE_BUILDS:
                ACTIVE_BUILDS[top_path]["stop_flag"].set()
                
            stop_flag = threading.Event()
            ACTIVE_BUILDS[top_path] = {
                "start_time": start_time_epoch,
                "command": command,
                "device": device,
                "targets": targets,
                "percentage": 0,
                "completed": 0,
                "total": 0,
                "action": "Starting environment build engine...",
                "messages": messages_map,
                "stop_flag": stop_flag,
                "rom_name": rom_name,
                "variant": variant,
                "release": release,
                "platform_version": platform_version,
                "target_product": target_product,
                "target_arch": target_arch,
                "build_id": build_id,
                "user": user,
                "host": host
            }
            print(f"[API] ACTIVE_BUILDS keys after start: {list(ACTIVE_BUILDS.keys())}")
            
        # Spawn log tailing parser thread
        threading.Thread(target=track_build_log, args=(top_path,), daemon=True).start()
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def handle_stop(self, data):
        top_path = data.get("top")
        exit_code = data.get("exit_code", 0)
        
        if not top_path:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing 'top' parameter"}).encode())
            return
            
        print(f"[API] Build stopped in workspace {top_path} with exit code {exit_code}")
        print(f"[API] ACTIVE_BUILDS keys at stop: {list(ACTIVE_BUILDS.keys())}")
        
        with ACTIVE_BUILDS_LOCK:
            if top_path not in ACTIVE_BUILDS:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "No active build found for this workspace"}).encode())
                return
            
            ctx = ACTIVE_BUILDS[top_path]
            # Signal the tailing thread to finish up
            ctx["stop_flag"].set()
            # Remove from active builds map
            del ACTIVE_BUILDS[top_path]
            
        # Spawn post-build processor in background thread to avoid blocking CLI
        threading.Thread(target=process_post_build, args=(top_path, ctx, exit_code), daemon=True).start()
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

def run_http_server(port):
    server = ThreadingHTTPServer(('127.0.0.1', port), APIHandler)
    print(f"[API] HTTP Server listening on http://127.0.0.1:{port}")
    server.serve_forever()

if __name__ == "__main__":
    # Ensure config loading
    port = CONFIG.get("port", DEFAULT_PORT)
    
    # 1. Spawn Telegram Bot Polling in background
    threading.Thread(target=telegram_polling, daemon=True).start()
    
    # 2. Start HTTP Server in foreground
    try:
        run_http_server(port)
    except KeyboardInterrupt:
        print("\n[Daemon] Shutting down...")
        sys.exit(0)
