#!/usr/bin/env python3
import os
import sys
import json
import time
import re
import threading
import socket
import glob
import urllib.request
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import shutil
import subprocess

# Configuration path
CONFIG_PATH = "/home/nocache/bot/config.json"
DEFAULT_PORT = 8080

def load_config():
    if not os.path.exists(CONFIG_PATH):
        default_config = {
            "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
            "subscribed_chats": [],
            "port": DEFAULT_PORT
        }
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading config: {e}", file=sys.stderr)
        return {"bot_token": "YOUR_TELEGRAM_BOT_TOKEN", "subscribed_chats": [], "port": DEFAULT_PORT}

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)

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

def telegram_api_call(method, params=None):
    token = CONFIG.get("bot_token", "YOUR_TELEGRAM_BOT_TOKEN")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[Telegram] WARNING: Bot token is not configured in config.json", file=sys.stderr)
        return None
    
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(params).encode('utf-8') if params else None
    
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            print(f"[Telegram] API call HTTP error '{method}': {e.code} {e.reason} - {err_body}", file=sys.stderr)
        except Exception:
            print(f"[Telegram] API call HTTP error '{method}': {e.code} {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[Telegram] API call error '{method}': {e}", file=sys.stderr)
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
    sent_messages = {}
    for chat_id in chats:
        res = send_message(chat_id, text, parse_mode)
        if res and res.get("ok"):
            msg_id = res["result"]["message_id"]
            sent_messages[chat_id] = msg_id
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
    for chat_id, msg_id in messages_map.items():
        edit_message(chat_id, msg_id, text, parse_mode)

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
        
        return (
            f"⚙️ CPU Load: {cpu_percent:.1f}% (Cores: {cpu_count}, 1m avg: {load_avg[0]:.2f})\n"
            f"💾 RAM Usage: {ram_used_gb:.1f} / {ram_total_gb:.1f} GB ({ram_percent:.1f}%)\n"
            f"📁 Disk Space: {disk_free_gb:.1f} GB free of {disk_total_gb:.1f} GB ({disk_percent:.1f}% used)\n"
            f"⏳ Uptime: {uptime_str}"
        )
    except Exception as e:
        return f"Error getting system info: {e}"

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
    
    config_block = format_configuration_html(ctx)
    
    text = (
        f"⚙️ <b>Build In Progress</b>\n"
        f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
        f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
        f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
        f"📈 <b>Progress:</b> <b>[{progress_bar}] {percentage_esc}</b>\n"
        f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
        f"⏱️ <b>Elapsed:</b> <b>{elapsed_esc}</b>\n\n"
        f"{config_block}\n\n"
        f"{sys_info_quoted}"
    )
    
    broadcast_edit(messages_map, text, parse_mode="HTML")

# Telegram polling daemon
def telegram_polling():
    print("[Telegram] Starting bot command polling loop...")
    offset = 0
    
    # Send a startup notification to server logs
    res = telegram_api_call("getMe")
    if res and res.get("ok"):
        bot_user = res["result"]["username"]
        print(f"[Telegram] Connected as @{bot_user}")
    else:
        print("[Telegram] Failed to connect. Token might be missing or invalid.", file=sys.stderr)
        
    while True:
        try:
            updates = telegram_api_call("getUpdates", {"offset": offset, "timeout": 20})
            if updates and updates.get("ok") and updates.get("result"):
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if message and message.get("text"):
                        handle_telegram_message(message)
        except Exception as e:
            print(f"[Telegram] Polling loop exception: {e}", file=sys.stderr)
        time.sleep(1.0)

def handle_telegram_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()
    
    if text.startswith("/start"):
        welcome = (
            f"🚀 *AOSP Build Tracker Bot*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Welcome! This bot tracks AOSP compilation pipelines in real-time.\n\n"
            f"📌 *Commands Available:*\n"
            f"• `/subscribe` - Add this chat/group to receive live build alerts.\n"
            f"• `/unsubscribe` - Remove this chat from receiving alerts.\n"
            f"• `/status` - Check current active build progress.\n"
            f"• `/sysinfo` - View server CPU, RAM, and Disk storage.\n"
            f"• `/ping` - Check if the bot is alive and active."
        )
        send_message(chat_id, welcome)
        
    elif text.startswith("/subscribe"):
        config = CONFIG
        if chat_id not in config["subscribed_chats"]:
            config["subscribed_chats"].append(chat_id)
            save_config(config)
            send_message(chat_id, "✅ *Successfully subscribed!* This chat will now receive real-time build start, progress, and compilation result updates.")
        else:
            send_message(chat_id, "ℹ️ This chat is *already* subscribed to build updates.")
            
    elif text.startswith("/unsubscribe"):
        config = CONFIG
        if chat_id in config["subscribed_chats"]:
            config["subscribed_chats"].remove(chat_id)
            save_config(config)
            send_message(chat_id, "❌ *Unsubscribed!* You will no longer receive build tracking updates in this chat.")
        else:
            send_message(chat_id, "ℹ️ This chat was not subscribed.")
            
    elif text.startswith("/status"):
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
        status_text += f"\n🖥️ *System Info:*\n```\n{sys_info}\n```"
        send_message(chat_id, status_text)
        
    elif text.startswith("/sysinfo"):
        sys_info = get_sys_info()
        send_message(chat_id, f"🖥️ *Build Server Stats:*\n━━━━━━━━━━━━━━━━━━━━━\n```\n{sys_info}\n```")
        
    elif text.startswith("/ping"):
        sent_date = msg.get("date")
        if sent_date:
            elapsed = time.time() - sent_date
            resp_str = f" *{int(elapsed * 1000)}ms*"
        else:
            resp_str = ""
        send_message(chat_id, f"🏓 *Pong!*{resp_str}")

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
                        product_dir = max(matching_dirs, key=os.path.getmtime)
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
        
        # Detect ZIP file (excluding target_files, preferring non-ota zips)
        rom_zip = None
        try:
            zip_files = []
            for f in os.listdir(product_dir):
                if f.endswith(".zip") and not "target_files" in f.lower():
                    zip_files.append(os.path.join(product_dir, f))
            if zip_files:
                non_ota = [z for z in zip_files if "ota" not in os.path.basename(z).lower()]
                if non_ota:
                    rom_zip = max(non_ota, key=os.path.getmtime)
                else:
                    rom_zip = max(zip_files, key=os.path.getmtime)
        except Exception as e:
            print(f"[Post-Build] Exception scanning ZIP files: {e}", file=sys.stderr)
            
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
            
        # Detect OTA JSON file
        json_file = None
        try:
            device_query = device.split('_')[-1] if '_' in device else device
            json_candidates = []
            for f in os.listdir(product_dir):
                if f.endswith(".json") and (device.lower() in f.lower() or device_query.lower() in f.lower()):
                    json_candidates.append(os.path.join(product_dir, f))
            if json_candidates:
                json_file = max(json_candidates, key=os.path.getmtime)
            else:
                # Search recursively under top_path/out/
                out_dir = os.path.join(top_path, "out")
                if os.path.isdir(out_dir):
                    for root, dirs, files in os.walk(out_dir):
                        for f in files:
                            if f.endswith(".json") and (device.lower() in f.lower() or device_query.lower() in f.lower()):
                                json_file = os.path.join(root, f)
                                break
                        if json_file:
                            break
        except Exception as e:
            print(f"[Post-Build] Exception searching JSON: {e}", file=sys.stderr)
 
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
        
        # Upload loop
        for item in files_metadata:
            # Update status in TG
            current_status = (
                f"✅ <b>Build Completed</b>\n"
                f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
                f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
                f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
                f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
                f"🛠️ <b>Actions:</b> <b>{actions_esc}</b>\n"
                f"{config_block}\n\n"
                f"📤 <b>Uploading:</b> <code>{escape_html(item['name'])}</code> to Gofile..."
            )
            broadcast_edit(processing_msg, current_status, parse_mode="HTML")
            
            url = upload_to_gofile(item['path'])
            if url:
                item['link'] = url
                
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
        failure_card = (
            f"❌ <b>Build Failed</b>\n"
            f"🕒 <b>Started:</b> <b>{start_time_esc}</b>\n\n"
            f"📀 <b>Rom:</b> <b>{rom_name_esc}</b>\n"
            f"📱 <b>Device:</b> <b>{device_esc}</b>\n"
            f"⏱️ <b>Elapsed:</b> <b>{duration_esc}</b>\n\n"
            f"🛠️ <b>Actions:</b> <b>{actions_esc} (1 failed)</b>\n"
            f"{config_block}\n\n"
            f"📄 Check logs for details. Error log uploaded if available."
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
            "build_id": build_id
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
                "build_id": build_id
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
