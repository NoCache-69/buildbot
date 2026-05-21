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
    try:
        # Get server list
        url = "https://api.gofile.io/servers"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode('utf-8'))
        
        if res_data.get("status") == "ok":
            servers = res_data.get("data", {}).get("servers", [])
            if servers:
                # Use the last server in the list as in the bash script
                server = servers[-1]["name"]
            else:
                server = "store1" # fallback
        else:
            server = "store1"
            
        print(f"[Gofile] Selected server node: {server}")
        
        # Run curl in subprocess to avoid huge memory usage on python
        cmd = ["curl", "-s", "-X", "POST", f"https://{server}.gofile.io/contents/uploadfile", "-F", f"file=@{file_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            resp = json.loads(result.stdout)
            if resp.get("status") == "ok":
                link = resp.get("data", {}).get("downloadPage")
                print(f"[Gofile] Uploaded {file_path} successfully: {link}")
                return link
            else:
                print(f"[Gofile] Upload API error for {file_path}: {resp}", file=sys.stderr)
        else:
            print(f"[Gofile] Curl failed for {file_path} with code {result.returncode}: {result.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"[Gofile] Exception uploading {file_path}: {e}", file=sys.stderr)
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
            
        return (
            f"🖥️ CPU Load: {cpu_percent:.1f}% (Cores: {cpu_count}, 1m avg: {load_avg[0]:.2f})\n"
            f"📟 RAM Usage: {ram_used_gb:.1f} / {ram_total_gb:.1f} GB ({ram_percent:.1f}%)\n"
            f"💾 Disk space: {disk_free_gb:.1f} GB free of {disk_total_gb:.1f} GB ({disk_percent:.1f}% used)"
        )
    except Exception as e:
        return f"⚠️ Error getting system info: {e}"

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
    
    regex = re.compile(r'\[\s*(\d+)%\s+(\d+)/(\d+)\]\s*(.*)')
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
                percentage = int(match.group(1))
                completed = int(match.group(2))
                total = int(match.group(3))
                action = match.group(4)
                
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
    elapsed_str = format_duration(elapsed)
    
    percentage = ctx["percentage"]
    completed = ctx["completed"]
    total = ctx["total"]
    action = ctx["action"]
    device = ctx["device"]
    command = ctx["command"]
    messages_map = ctx["messages"]
    
    # Calculate linear ETA based on completed tasks
    eta_str = "Calculating..."
    if completed > 5 and elapsed > 5 and total > 0:
        tasks_rem = total - completed
        rate = completed / elapsed  # tasks per second
        if rate > 0:
            eta_seconds = tasks_rem / rate
            eta_str = format_duration(eta_seconds)
            
    progress_bar = make_progress_bar(percentage)
    
    sys_stats = get_sys_info()
    
    # Elegant live status card
    text = (
        f"📱 *AOSP Build Live Status*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔧 *Device:* `{device}`\n"
        f"🕒 *Elapsed Time:* `{elapsed_str}`\n"
        f"📊 *Progress:* `[{progress_bar}]` *{percentage}%*\n"
        f"⚙️ *Tasks:* `{completed:,} / {total:,}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *System Info:*\n```\n{sys_stats}\n```"
    )
    
    broadcast_edit(messages_map, text)

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
            f"• `/sysinfo` - View server CPU, RAM, and Disk storage."
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
            
            status_text += (
                f"📱 *Active Build Details:*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔧 *Device:* `{ctx['device']}`\n"
                f"🕒 *Elapsed:* `{elapsed_str}`\n"
                f"📊 *Progress:* `[{progress_bar}]` *{percentage}%*\n"
                f"⚙️ *Tasks:* `{ctx['completed']:,} / {ctx['total']:,}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )
        sys_info = get_sys_info()
        status_text += f"\n📊 *System Info:*\n```\n{sys_info}\n```"
        send_message(chat_id, status_text)
        
    elif text.startswith("/sysinfo"):
        sys_info = get_sys_info()
        send_message(chat_id, f"🖥️ *Build Server Stats:*\n━━━━━━━━━━━━━━━━━━━━━\n```\n{sys_info}\n```")

def process_post_build(top_path, ctx, exit_code):
    # Give a small 1.5 second window for log writing to catch up and parser to capture final lines
    time.sleep(1.5)
    
    # Calculate duration
    duration = time.time() - ctx["start_time"]
    duration_str = format_duration(duration)
    
    # Determine status
    status = "SUCCESS" if exit_code == 0 else "FAILED"
    
    # Delete the pinned live updates message so we don't clutter the chat
    for chat_id, msg_id in ctx["messages"].items():
        try:
            delete_message(chat_id, msg_id)
        except Exception:
            pass
            
    if status == "SUCCESS":
        # Send initial success status to notify the user that processing has started
        processing_msg = broadcast_message(
            f"✅ *ROM Build Finished Successfully!* 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 *Device:* `{ctx['device']}`\n"
            f"⏱️ *Build Duration:* `{duration_str}`\n\n"
            f"📤 *Status:* Scanning output files & preparing uploads..."
        )
        
        # Let's locate the output directory using our extremely robust search logic
        device = ctx["device"]
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
                f"✅ *ROM Build Finished Successfully!* 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔧 *Device:* `{device}`\n"
                f"⏱️ *Build Duration:* `{duration_str}`\n"
                f"❌ *Output Error:* Could not locate build output directory under `out/target/product/`."
            )
            broadcast_edit(processing_msg, failed_card)
            return
            
        print(f"[Post-Build] Located product directory: {product_dir}")
        
        # Detect ZIP file
        rom_zip = None
        try:
            zip_files = []
            for f in os.listdir(product_dir):
                if f.endswith(".zip") and not "ota" in f.lower() and not "target_files" in f.lower():
                    zip_files.append(os.path.join(product_dir, f))
            if zip_files:
                rom_zip = max(zip_files, key=os.path.getmtime)
        except Exception as e:
            print(f"[Post-Build] Exception scanning ZIP files: {e}", file=sys.stderr)
            
        if not rom_zip:
            failed_card = (
                f"✅ *ROM Build Finished Successfully!* 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔧 *Device:* `{device}`\n"
                f"⏱️ *Build Duration:* `{duration_str}`\n"
                f"❌ *Output Error:* No target ROM zip file found in `{product_dir}`."
            )
            broadcast_edit(processing_msg, failed_card)
            return
            
        # Get md5 and size of ROM zip
        try:
            zname = os.path.basename(rom_zip)
            zsize = os.path.getsize(rom_zip) / (1024**3) # GB
            # Read md5 quickly using shell md5sum for speed
            res_md5 = subprocess.run(["md5sum", rom_zip], capture_output=True, text=True)
            if res_md5.returncode == 0:
                zip_md5 = res_md5.stdout.split()[0]
            else:
                zip_md5 = "Unknown"
        except Exception as e:
            zname = os.path.basename(rom_zip)
            zsize = 0.0
            zip_md5 = "Error"
            
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
            
        # dtbo.img
        dtbo_img = os.path.join(product_dir, "dtbo.img")
        if os.path.exists(dtbo_img):
            upload_queue.append(("DTBO_IMG", dtbo_img))
            
        # vendor_boot.img
        vendor_boot = os.path.join(product_dir, "vendor_boot.img")
        if os.path.exists(vendor_boot):
            upload_queue.append(("VENDOR_BOOT", vendor_boot))
            
        # recovery.img
        recovery_img = os.path.join(product_dir, "recovery.img")
        if os.path.exists(recovery_img):
            upload_queue.append(("RECOVERY_IMG", recovery_img))
            
        # super_empty.img
        super_empty = os.path.join(product_dir, "super_empty.img")
        if os.path.exists(super_empty):
            upload_queue.append(("SUPER_EMPTY", super_empty))
            
        # OTA JSON if found
        if json_file and os.path.exists(json_file):
            upload_queue.append(("OTA_JSON", json_file))
            
        # Map of file type -> URL
        uploaded_urls = {}
        
        # Upload loop
        for file_type, file_path in upload_queue:
            # Update status in TG
            current_status = (
                f"✅ *ROM Build Finished Successfully!* 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔧 *Device:* `{device}`\n"
                f"⏱️ *Build Duration:* `{duration_str}`\n"
                f"📦 *Output:* `{zname}` ({zsize:.2f} GB)\n"
                f"🧬 *MD5:* `{zip_md5}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📤 *Uploading:* `{os.path.basename(file_path)}` to Gofile..."
            )
            broadcast_edit(processing_msg, current_status)
            
            url = upload_to_gofile(file_path)
            if url:
                uploaded_urls[file_type] = url
                
        # Send final build notification card
        links_lines = []
        if "ROM" in uploaded_urls:
            links_lines.append(f"📦 *ROM:* [Download]({uploaded_urls['ROM']})")
        if "OTA_JSON" in uploaded_urls:
            links_lines.append(f"📄 *OTA JSON:* [Download]({uploaded_urls['OTA_JSON']})")
        if "BOOT_IMG" in uploaded_urls:
            links_lines.append(f"🔌 *BOOT_IMG:* [Download]({uploaded_urls['BOOT_IMG']})")
        if "DTBO_IMG" in uploaded_urls:
            links_lines.append(f"🔌 *DTBO_IMG:* [Download]({uploaded_urls['DTBO_IMG']})")
        if "VENDOR_BOOT" in uploaded_urls:
            links_lines.append(f"🔌 *VENDOR_BOOT:* [Download]({uploaded_urls['VENDOR_BOOT']})")
        if "RECOVERY_IMG" in uploaded_urls:
            links_lines.append(f"🔌 *RECOVERY_IMG:* [Download]({uploaded_urls['RECOVERY_IMG']})")
        if "SUPER_EMPTY" in uploaded_urls:
            links_lines.append(f"🔌 *SUPER_EMPTY:* [Download]({uploaded_urls['SUPER_EMPTY']})")
            
        links_section = "\n".join(links_lines) if links_lines else "⚠️ *Upload Error:* Files failed to upload to Gofile."
        
        success_card = (
            f"✅ *ROM Build Finished Successfully!* 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 *Device:* `{device}`\n"
            f"⏱️ *Build Duration:* `{duration_str}`\n"
            f"📦 *Output:* `{zname}` ({zsize:.2f} GB)\n"
            f"🧬 *MD5:* `{zip_md5}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 *Gofile Upload Links:*\n"
            f"{links_section}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        broadcast_edit(processing_msg, success_card)
        
    else:
        # Failure logic
        failure_card = (
            f"❌ *ROM Build Failed!* 😭\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 *Device:* `{ctx['device']}`\n"
            f"⏱️ *Duration:* `{duration_str}`\n"
            f"🛑 *Exit Code:* `{exit_code}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        broadcast_message(failure_card)
        
        # Generate out/error.log from out/tg_build.log (overwrite always)
        error_log_path = os.path.join(top_path, "out", "error.log")
        try:
            if os.path.exists(error_log_path):
                os.remove(error_log_path)
        except Exception:
            pass
            
        try:
            log_file_path = os.path.join(top_path, "out", "tg_build.log")
            if os.path.exists(log_file_path):
                with open(log_file_path, 'r', errors='ignore') as f:
                    lines = f.readlines()
                # Extract the last 1000 lines for a detailed compile trace
                last_lines = lines[-1000:]
                os.makedirs(os.path.dirname(error_log_path), exist_ok=True)
                with open(error_log_path, 'w', errors='ignore') as f:
                    f.writelines(last_lines)
        except Exception as ex:
            print(f"Error creating out/error.log: {ex}", file=sys.stderr)
        
        # Broadcast the error.log document to all subscribers
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
        targets = data.get("targets", "bacon")
        
        if not top_path:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing 'top' parameter"}).encode())
            return
            
        print(f"[API] Build starting in workspace: {top_path}")
        
        # Broadcast initial "Build Starting" message
        start_time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        sys_stats = get_sys_info()
        
        notify_text = (
            f"🚀 *New ROM Build Initiated!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 *Device:* `{device}`\n"
            f"📂 *AOSP Path:* `{os.path.basename(top_path)}`\n"
            f"📅 *Started:* `{start_time_str}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *System Info:*\n```\n{sys_stats}\n```"
        )
        
        messages_map = broadcast_message(notify_text)
        
        with ACTIVE_BUILDS_LOCK:
            # If there's an existing tracker for this path, clean it up first
            if top_path in ACTIVE_BUILDS:
                ACTIVE_BUILDS[top_path]["stop_flag"].set()
                
            stop_flag = threading.Event()
            ACTIVE_BUILDS[top_path] = {
                "start_time": time.time(),
                "command": command,
                "device": device,
                "targets": targets,
                "percentage": 0,
                "completed": 0,
                "total": 0,
                "action": "Starting environment build engine...",
                "messages": messages_map,
                "stop_flag": stop_flag
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
