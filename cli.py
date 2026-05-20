#!/usr/bin/env python3
import sys
import os
import json
import argparse
import urllib.request
import urllib.error

CONFIG_PATH = "/home/nocache/bot/config.json"
DEFAULT_PORT = 8080

def get_daemon_port():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
                return cfg.get("port", DEFAULT_PORT)
        except Exception:
            pass
    return DEFAULT_PORT

def send_request(endpoint, data):
    port = get_daemon_port()
    url = f"http://127.0.0.1:{port}/api/{endpoint}"
    payload = json.dumps(data).encode('utf-8')

    headers = {
        "Content-Type": "application/json",
        "Content-Length": len(payload)
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data.get("status") == "ok"
    except urllib.error.URLError as e:
        print(f"[CLI] Warning: Failed to contact build tracking daemon on port {port}: {e.reason}", file=sys.stderr)
        print("[CLI] Make sure the background daemon.py is running!", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[CLI] Warning: Unexpected error contacting daemon: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Telegram Build Tracker CLI Trigger")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Start command parser
    parser_start = subparsers.add_parser("start", help="Trigger build start tracking")
    parser_start.add_argument("--top", required=True, help="Absolute path to AOSP root")
    parser_start.add_argument("--command", required=True, help="Complete compile command used")
    parser_start.add_argument("--device", required=True, help="Target device product name")
    parser_start.add_argument("--targets", required=True, help="Specific build target goals")

    # Stop command parser
    parser_stop = subparsers.add_parser("stop", help="Trigger build stop tracking")
    parser_stop.add_argument("--top", required=True, help="Absolute path to AOSP root")
    parser_stop.add_argument("--exit-code", type=int, required=True, help="Build compilation exit status")

    args = parser.parse_args()

    if args.action == "start":
        data = {
            "top": args.top,
            "command": args.command,
            "device": args.device,
            "targets": args.targets
        }
        success = send_request("start", data)
        sys.exit(0 if success else 1)

    elif args.action == "stop":
        data = {
            "top": args.top,
            "exit_code": args.exit_code
        }
        success = send_request("stop", data)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
