#!/usr/bin/env python3
import os
import time
import shutil
import yaml
from datetime import datetime

# Resolve repo root based on this file's location: <repo>/tools/move_to_location.py
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

CONFIG_PATH = os.path.join(REPO_ROOT, 'channellist.yaml')
TEMP_BASE = os.path.join(REPO_ROOT, 'temp')

POLL_INTERVAL = 240  # seconds between scans

# Typical yt-dlp temp/aux files to ignore
SKIP_EXTENSIONS = {'.part', '.ytdl'}

# Chat JSON detection
CHAT_JSON_EXTENSIONS = {'.json', '.live_chat.json'}

# Import chat renderer
try:
    from chat_render import render_chat_json
except ImportError:
    # Fallback if module import fails; we'll just not render
    render_chat_json = None


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[move_to_location {ts}] {msg}")


def load_channels():
    if not os.path.isfile(CONFIG_PATH):
        log(f"⚠️ Config file not found: {CONFIG_PATH}")
        return []
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f) or {}
        return config.get('channels', [])


def temp_dir_for_channel(name: str) -> str:
    return os.path.join(TEMP_BASE, name)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def is_chat_json(filename: str) -> bool:
    """
    Heuristic: treat .json / .live_chat.json in temp as chat files.
    You can tighten this by checking for 'live_chat' in name if you like.
    """
    lower = filename.lower()
    for ext in CHAT_JSON_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False


def scan_once(seen_sizes: dict):
    """
    Perform a single scan:
    - For each channel in channellist.yaml
    - Look into ./temp/<ChannelName>
    - For each regular file that is not a temp extension:
      - If first time seen: record its size.
      - If already seen and size is unchanged: move it to target.
      - If size changed: update size and wait for next scan.
    - After moving a chat JSON, optionally call chat_render.render_chat_json() on the destination.
    - Remove entries from seen_sizes for files that disappeared.
    """
    channels = load_channels()
    current_paths = set()

    for cfg in channels:
        name = cfg.get('name')
        target = cfg.get('target')

        if not name or not target:
            continue

        temp_dir = temp_dir_for_channel(name)
        if not os.path.isdir(temp_dir):
            # No temp dir for this channel yet
            continue

        target_dir = os.path.abspath(os.path.join(REPO_ROOT, target))
        ensure_dir(target_dir)

        for entry in os.scandir(temp_dir):
            if not entry.is_file():
                continue

            src = entry.path
            current_paths.add(src)

            base_name = entry.name
            _, ext = os.path.splitext(base_name)
            if ext in SKIP_EXTENSIONS:
                continue

            try:
                size = os.path.getsize(src)
            except OSError as e:
                log(f"⚠️ Could not stat '{src}': {e}")
                continue

            if src not in seen_sizes:
                # First time we see this file: remember its size
                seen_sizes[src] = size
                log(f"👀 Tracking new file for stability: '{src}' (size={size})")
                continue

            # Seen before: check if size is stable
            prev_size = seen_sizes[src]
            if size != prev_size:
                # Still growing/changing
                seen_sizes[src] = size
                log(f"⏳ File still changing: '{src}' (old={prev_size}, new={size})")
                continue

            # Size is unchanged between scans: treat as finished
            dest = os.path.join(target_dir, base_name)
            is_chat = is_chat_json(base_name)

            try:
                log(f"➡️ Moving finished file '{src}' -> '{dest}'")
                shutil.move(src, dest)
                # Remove from tracking
                del seen_sizes[src]
            except Exception as e:
                log(f"⚠️ Failed to move '{src}' -> '{dest}': {e}")
                continue

            # If this is a chat JSON and we have a renderer, call it
            if is_chat and render_chat_json is not None:
                try:
                    log(f"🎬 Rendering chat JSON to video for '{dest}'")
                    render_chat_json(dest)
                except Exception as e:
                    log(f"⚠️ Chat rendering failed for '{dest}': {e}")

    # Clean up seen_sizes entries for files that no longer exist or are no longer in temp
    stale_paths = [p for p in seen_sizes.keys() if p not in current_paths]
    for p in stale_paths:
        log(f"🧹 Removing stale tracking entry for '{p}'")
        del seen_sizes[p]


def main_loop():
    log(f"🚚 move_to_location started")
    log(f"   Repo root: {REPO_ROOT}")
    log(f"   Temp base: {TEMP_BASE}")
    ensure_dir(TEMP_BASE)

    # Map: file_path -> last_seen_size
    seen_sizes = {}

    while True:
        try:
            scan_once(seen_sizes)
        except Exception as e:
            log(f"⚠️ Error during scan: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    try:
        main_loop()
    except KeyboardInterrupt:
        log("🧹 move_to_location interrupted, exiting cleanly.")

