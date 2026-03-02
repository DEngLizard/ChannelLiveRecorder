#!/usr/bin/env python3
import os
import sys
import time
import shutil
import yaml
import re
import json
import subprocess
import logging
from datetime import datetime
from contextlib import contextmanager

# Resolve repo root based on this file's location: <repo>/tools/move_to_location.py
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, os.pardir))

CONFIG_PATH = os.path.join(REPO_ROOT, 'channellist.yaml')
TEMP_BASE = os.path.join(REPO_ROOT, 'temp')

POLL_INTERVAL = 240  # seconds between scans

# Typical yt-dlp temp/aux files to ignore
# NOTE: .log added so recorder/log output files are never moved
SKIP_EXTENSIONS = {'.part', '.ytdl', '.log'}

# Chat JSON detection
CHAT_JSON_EXTENSIONS = {'.json', '.live_chat.json'}

# Separate-stream outputs sometimes produced by yt-dlp when merge fails or ffmpeg isn't available.
# Example: 2026-02-23_21-31-56__dYfVubrMnU...f136.mp4 and ...f140.mp4
FRAGMENT_RE = re.compile(r"^(?P<prefix>.+?)\.f(?P<fmt>\d{3,4})\.(?P<ext>mp4|mkv|webm|m4a|mp3|aac)$", re.IGNORECASE)

# Import chat renderer (chat_render.py is in the same tools/ directory)
render_chat_json = None
try:
    if TOOLS_DIR not in sys.path:
        sys.path.insert(0, TOOLS_DIR)
    from chat_render import render_chat_json  # type: ignore
except Exception:
    render_chat_json = None


LOG_DIR = os.path.join(REPO_ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("move_to_location")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_fh = logging.FileHandler(os.path.join(LOG_DIR, "move_to_location.log"), encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)

if not logger.handlers:
    logger.addHandler(_fh)
    logger.addHandler(_sh)


def log(msg: str):
    logger.info(msg)


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


def is_fragment_media(filename: str) -> bool:
    return FRAGMENT_RE.match(filename) is not None


def fragment_group_key(filename: str) -> str | None:
    m = FRAGMENT_RE.match(filename)
    if not m:
        return None
    # Group by the shared prefix *without* the .f###.ext suffix
    return m.group("prefix")


def ffprobe_stream_kinds(path: str) -> tuple[bool, bool]:
    """Return (has_video, has_audio). Uses ffprobe if available, else best-effort guess."""
    try:
        subprocess.run(["ffprobe", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        # Fallback based on common format ids in filename
        lower = os.path.basename(path).lower()
        if ".f140." in lower or ".f141." in lower or ".f251." in lower:
            return (False, True)
        return (True, False)

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams", [])
        has_v = any(s.get("codec_type") == "video" for s in streams)
        has_a = any(s.get("codec_type") == "audio" for s in streams)
        return (has_v, has_a)
    except Exception:
        lower = os.path.basename(path).lower()
        if ".f140." in lower or ".f141." in lower or ".f251." in lower:
            return (False, True)
        return (True, False)


def merge_av_pair(video_path: str, audio_path: str, out_path: str) -> bool:
    """Mux video+audio into out_path using ffmpeg stream copy."""
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-c",
        "copy",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        out_path,
    ]
    log(f"🧩 Merging A/V: '{os.path.basename(video_path)}' + '{os.path.basename(audio_path)}' -> '{os.path.basename(out_path)}'")
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        log(f"⚠️ ffmpeg merge failed: {e}")
        return False


@contextmanager
def pushd(path: str):
    """
    Temporarily chdir to `path` and restore after.
    Used so chat rendering outputs are created "in place"
    (next to the moved chat json).
    """
    prev = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev)


def scan_once(seen_sizes: dict):
    """
    Perform a single scan:
    - For each channel in channellist.yaml
    - Look into ./temp/<ChannelName>
    - For each regular file that is not a temp extension:
      - If first time seen: record its size.
      - If already seen and size is unchanged: move it to target.
      - If size changed: update size and wait for next scan.
    - After moving a chat JSON, render the chat "in place" (cwd=destination folder).
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
            continue

        target_dir = os.path.abspath(os.path.join(REPO_ROOT, target))
        ensure_dir(target_dir)

        # First pass: update stability tracking
        entries = list(os.scandir(temp_dir))

        for entry in entries:
            if not entry.is_file():
                continue

            src = entry.path
            current_paths.add(src)

            base_name = entry.name
            _, ext = os.path.splitext(base_name)
            ext = ext.lower()

            # Never move logs (or other skipped extensions)
            if ext in SKIP_EXTENSIONS:
                continue

            try:
                size = os.path.getsize(src)
            except OSError as e:
                log(f"⚠️ Could not stat '{src}': {e}")
                continue

            if src not in seen_sizes:
                seen_sizes[src] = size
                log(f"👀 Tracking new file for stability: '{src}' (size={size})")
                continue

            prev_size = seen_sizes[src]
            if size != prev_size:
                seen_sizes[src] = size
                log(f"⏳ File still changing: '{src}' (old={prev_size}, new={size})")
                continue

            # Never move fragmented A/V files; we will attempt to merge them first.
            if is_fragment_media(base_name):
                # Keep tracking stability, but don't move.
                continue

            dest = os.path.join(target_dir, base_name)
            is_chat = is_chat_json(base_name)

            try:
                log(f"➡️ Moving finished file '{src}' -> '{dest}'")
                shutil.move(src, dest)
                del seen_sizes[src]
            except Exception as e:
                log(f"⚠️ Failed to move '{src}' -> '{dest}': {e}")
                continue

            # If this is a chat JSON and we have a renderer, render "in place"
            # by running from the destination directory.
            if is_chat and render_chat_json is not None:
                try:
                    dest_dir = os.path.dirname(os.path.abspath(dest))
                    with pushd(dest_dir):
                        log(f"🎬 Rendering chat JSON in place (cwd='{dest_dir}') for '{dest}'")
                        render_chat_json(dest)
                except Exception as e:
                    log(f"⚠️ Chat rendering failed for '{dest}': {e}")

        # Second pass (per-channel): if we have stable .f### files, try to merge them into a single MP4.
        stable_fragment_files: list[str] = []
        current_paths_in_dir = set()
        for entry in entries:
            if not entry.is_file():
                continue
            current_paths_in_dir.add(entry.path)
            name_lower = entry.name.lower()
            if any(name_lower.endswith(x) for x in SKIP_EXTENSIONS):
                continue
            if not is_fragment_media(entry.name):
                continue
            # treat as stable if tracked and unchanged since last scan
            try:
                size = os.path.getsize(entry.path)
            except OSError:
                continue
            if entry.path in seen_sizes and seen_sizes[entry.path] == size:
                stable_fragment_files.append(entry.path)

        # Group stable fragments by shared prefix
        groups: dict[str, list[str]] = {}
        for p in stable_fragment_files:
            key = fragment_group_key(os.path.basename(p))
            if not key:
                continue
            groups.setdefault(key, []).append(p)

        for key, files in groups.items():
            # If a merged output already exists in temp, do nothing.
            out_name = f"{key}.mp4"
            out_path = os.path.join(temp_dir, out_name)
            if os.path.exists(out_path):
                continue

            # Identify one audio-only and one video-only file
            video_candidates = []
            audio_candidates = []
            for f in files:
                has_v, has_a = ffprobe_stream_kinds(f)
                if has_v and not has_a:
                    video_candidates.append(f)
                elif has_a and not has_v:
                    audio_candidates.append(f)

            if not video_candidates or not audio_candidates:
                continue

            # Pick the largest video and largest audio (best chance it's the full stream)
            video_path = max(video_candidates, key=lambda p: os.path.getsize(p))
            audio_path = max(audio_candidates, key=lambda p: os.path.getsize(p))

            if merge_av_pair(video_path, audio_path, out_path):
                # If merge succeeded, remove all fragments in this group
                for f in files:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
                    seen_sizes.pop(f, None)
                # Track new merged output on next scan
                try:
                    seen_sizes[out_path] = os.path.getsize(out_path)
                    log(f"✅ Merge complete, created '{out_path}'")
                except Exception:
                    pass

    # Clean up seen_sizes entries for files that no longer exist or are no longer in temp
    stale_paths = [p for p in list(seen_sizes.keys()) if p not in current_paths]
    for p in stale_paths:
        log(f"🧹 Removing stale tracking entry for '{p}'")
        del seen_sizes[p]


def main_loop():
    log("🚚 move_to_location started")
    log(f"   Repo root: {REPO_ROOT}")
    log(f"   Temp base: {TEMP_BASE}")
    ensure_dir(TEMP_BASE)

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
