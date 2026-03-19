#!/usr/bin/env python3
"""Orchestrator for ChannelLiveRecorder.

Starts one video recorder and one chat recorder per configured channel,
keeps them alive, starts the mover sidecar, and performs periodic yt-dlp
self-updates without needing cron.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

import yaml


RECORDER_PATH = os.path.join("recorder", "live_stream_recorder.py")
CHAT_RECORDER_PATH = os.path.join("recorder", "live_chat_recorder.py")
CONFIG_PATH = "./channellist.yaml"
TEMP_BASE = "./temp"
CHECK_INTERVAL = 240  # seconds
DEFAULT_YTDLP_BIN = "/usr/local/bin/yt-dlp"
DEFAULT_UPDATE_INTERVAL_HOURS = 24.0

MOVER_PATH = os.path.join("tools", "move_to_location.py")

running_processes: dict[str, dict[str, subprocess.Popen[Any]]] = {}
cookies_args: list[str] = []
cookie_fallback_args: list[str] = []
yt_dlp_bin: str = DEFAULT_YTDLP_BIN
yt_dlp_update_interval_seconds: float = DEFAULT_UPDATE_INTERVAL_HOURS * 3600
last_yt_dlp_update_ts: float | None = None
mover_proc: subprocess.Popen[Any] | None = None
shutting_down = False

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(REPO_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("helper")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler(os.path.join(LOG_DIR, "live_recording_helper.log"), encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)

if not logger.handlers:
    logger.addHandler(_fh)
    logger.addHandler(_sh)


def log(msg: str) -> None:
    logger.info(msg)


def load_channels() -> list[dict[str, Any]]:
    if not os.path.isfile(CONFIG_PATH):
        log(f"⚠️ Config file not found: {CONFIG_PATH}")
        return []

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as exc:
        log(f"⚠️ Failed to load config {CONFIG_PATH}: {exc}")
        return []

    channels = config.get("channels", [])
    if not isinstance(channels, list):
        log(f"⚠️ Invalid config format in {CONFIG_PATH}: 'channels' is not a list")
        return []

    cleaned: list[dict[str, Any]] = []
    for entry in channels:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        cleaned.append(entry)
    return cleaned


def temp_dir_for_channel(name: str) -> str:
    return os.path.abspath(os.path.join(TEMP_BASE, name))


def build_child_base_cmd(script_path: str, channel_name: str, temp_target: str) -> list[str]:
    cmd = [
        sys.executable,
        script_path,
        channel_name,
        temp_target,
        "--yt-dlp-bin",
        yt_dlp_bin,
    ]
    cmd.extend(cookies_args)
    cmd.extend(cookie_fallback_args)
    return cmd


def start_video_recorder(channel_cfg: dict[str, Any]) -> subprocess.Popen[Any]:
    name = channel_cfg["name"]
    temp_target = temp_dir_for_channel(name)
    os.makedirs(temp_target, exist_ok=True)
    cmd = build_child_base_cmd(RECORDER_PATH, name, temp_target)
    log(f"🚀 Starting VIDEO recorder for @{name}, saving to temp {temp_target}")
    return subprocess.Popen(cmd, start_new_session=True)


def start_chat_recorder(channel_cfg: dict[str, Any]) -> subprocess.Popen[Any]:
    name = channel_cfg["name"]
    temp_target = temp_dir_for_channel(name)
    os.makedirs(temp_target, exist_ok=True)
    cmd = build_child_base_cmd(CHAT_RECORDER_PATH, name, temp_target)
    log(f"💬 Starting CHAT recorder for @{name}, saving to temp {temp_target}")
    return subprocess.Popen(cmd, start_new_session=True)


def start_recorders(channel_cfg: dict[str, Any]) -> dict[str, subprocess.Popen[Any]]:
    procs: dict[str, subprocess.Popen[Any]] = {}
    procs["video"] = start_video_recorder(channel_cfg)
    time.sleep(1)
    procs["chat"] = start_chat_recorder(channel_cfg)
    return procs


def stop_proc(label: str, proc: subprocess.Popen[Any] | None) -> None:
    if proc and proc.poll() is None:
        log(f"🛑 Stopping {label}")
        try:
            proc.terminate()
        except Exception as exc:
            log(f"⚠️ Error sending terminate to {label}: {exc}")
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            log(f"⚠️ {label} did not exit, killing...")
            try:
                proc.kill()
            except Exception as exc:
                log(f"⚠️ Error killing {label}: {exc}")
        except Exception as exc:
            log(f"⚠️ Error while waiting for {label}: {exc}")


def stop_recorder(channel_name: str) -> None:
    procs = running_processes.get(channel_name, {})
    stop_proc(f"VIDEO recorder for @{channel_name}", procs.get("video"))
    stop_proc(f"CHAT recorder for @{channel_name}", procs.get("chat"))
    running_processes.pop(channel_name, None)


def start_mover() -> None:
    global mover_proc
    if mover_proc is not None and mover_proc.poll() is None:
        return

    if not os.path.isfile(MOVER_PATH):
        log(f"⚠️ Mover script not found at {MOVER_PATH} – skipping mover start.")
        return

    cmd = [sys.executable, MOVER_PATH]
    log(f"🚚 Starting mover process: {' '.join(cmd)}")
    mover_proc = subprocess.Popen(cmd, start_new_session=True)


def stop_mover() -> None:
    global mover_proc
    if mover_proc and mover_proc.poll() is None:
        stop_proc("mover process", mover_proc)
    mover_proc = None


def update_yt_dlp(force: bool = False) -> None:
    global last_yt_dlp_update_ts

    now = time.time()
    if not force and last_yt_dlp_update_ts is not None:
        if (now - last_yt_dlp_update_ts) < yt_dlp_update_interval_seconds:
            return

    if not os.path.isfile(yt_dlp_bin):
        log(f"⚠️ yt-dlp binary not found for helper auto-update: {yt_dlp_bin}")
        last_yt_dlp_update_ts = now
        return

    log(f"📦 Checking yt-dlp updates via: {yt_dlp_bin} -U")
    try:
        proc = subprocess.run(
            [yt_dlp_bin, "-U"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        output = (proc.stdout or "").strip()
        if output:
            for line in output.splitlines():
                log(f"yt-dlp: {line}")
        if proc.returncode != 0:
            log(f"⚠️ yt-dlp self-update returned {proc.returncode}; continuing with existing binary.")
        else:
            version_proc = subprocess.run(
                [yt_dlp_bin, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            version = (version_proc.stdout or "").strip()
            if version:
                log(f"✅ yt-dlp version now: {version}")
    except Exception as exc:
        log(f"⚠️ yt-dlp self-update failed: {exc}")
    finally:
        last_yt_dlp_update_ts = now


def cleanup(signum: int | None, frame: Any) -> None:
    global shutting_down
    if shutting_down:
        return
    shutting_down = True

    log("🧹 Cleaning up all recorders...")
    for channel in list(running_processes.keys()):
        stop_recorder(channel)

    stop_mover()
    log("👋 Helper exiting.")
    raise SystemExit(0)


def main() -> None:
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    os.makedirs(TEMP_BASE, exist_ok=True)

    update_yt_dlp(force=True)
    start_mover()

    while True:
        update_yt_dlp(force=False)

        configs = load_channels()
        active_channels = {cfg["name"]: cfg for cfg in configs}
        current_channels = set(running_processes.keys())

        for name, cfg in active_channels.items():
            if name not in current_channels:
                running_processes[name] = start_recorders(cfg)
                time.sleep(2)

        for name in current_channels - set(active_channels.keys()):
            stop_recorder(name)

        for name in list(active_channels.keys()):
            procs = running_processes.get(name, {})
            for kind in ("video", "chat"):
                proc = procs.get(kind)
                if proc and proc.poll() is not None:
                    log(f"🔁 Restarting dead {kind.upper()} recorder for @{name}")
                    if kind == "video":
                        procs["video"] = start_video_recorder(active_channels[name])
                    else:
                        procs["chat"] = start_chat_recorder(active_channels[name])
                    time.sleep(1)
            running_processes[name] = procs

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Orchestrate multiple live stream recorders (video + chat) into temp dirs."
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--cookies",
        metavar="COOKIE_FILE",
        help="Path to cookies.txt to be forwarded to all recorders (yt-dlp --cookies)",
    )
    group.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="Browser name for yt-dlp --cookies-from-browser (e.g. firefox, chrome)",
    )

    parser.add_argument(
        "--no-cookie-fallback",
        action="store_true",
        help="If cookies are provided, do NOT try the no-cookies-first then cookies fallback logic.",
    )
    parser.add_argument(
        "--yt-dlp-bin",
        default=DEFAULT_YTDLP_BIN,
        help="Absolute path or command name for the yt-dlp binary to use.",
    )
    parser.add_argument(
        "--yt-dlp-update-interval-hours",
        type=float,
        default=DEFAULT_UPDATE_INTERVAL_HOURS,
        help="How often the helper should run yt-dlp -U while it is running.",
    )

    args = parser.parse_args()

    yt_dlp_bin = os.path.expanduser(args.yt_dlp_bin)
    if not os.path.isabs(yt_dlp_bin):
        resolved = shutil.which(yt_dlp_bin)
        yt_dlp_bin = resolved or yt_dlp_bin

    if not os.path.isfile(yt_dlp_bin):
        log(f"⚠️ yt-dlp binary not found at startup: {yt_dlp_bin}")
    else:
        log(f"Using yt-dlp binary for all recorders: {yt_dlp_bin}")

    yt_dlp_update_interval_seconds = max(1.0, args.yt_dlp_update_interval_hours) * 3600

    if args.cookies:
        candidate = os.path.expanduser(args.cookies)
        if os.path.isfile(candidate):
            cookies_args = ["--cookies", candidate]
            log(f"Using cookies file for all recorders: {candidate}")
        else:
            log(f"⚠️ Cookies file not found: {candidate} (continuing without cookies)")
    elif args.cookies_from_browser:
        cookies_args = ["--cookies-from-browser", args.cookies_from_browser]
        log(f"Using cookies from browser for all recorders: {args.cookies_from_browser}")

    if cookies_args and (not args.no_cookie_fallback):
        cookie_fallback_args = ["--cookie-fallback"]
        log("Cookie fallback enabled: recorders will try without cookies first, then retry with cookies if needed.")

    main()
