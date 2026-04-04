#!/usr/bin/env python3
"""Single-channel LIVE chat recorder."""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass


def _setup_logger(repo_root: str, channel: str) -> logging.Logger:
    log_dir = os.path.join(repo_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(f"chat:{channel}")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(os.path.join(log_dir, f"chat_{channel}.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


AUTH_PATTERNS = [
    re.compile(r"sign in to confirm.*not a bot", re.IGNORECASE),
    re.compile(r"use --cookies-from-browser|use --cookies", re.IGNORECASE),
    re.compile(r"http error 403", re.IGNORECASE),
    re.compile(r"http error 429", re.IGNORECASE),
    re.compile(r"forbidden", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"challenge solving failed", re.IGNORECASE),
    re.compile(r"remote components.*were skipped", re.IGNORECASE),
]

NOT_LIVE_PATTERNS = [
    re.compile(r"the channel is not currently live", re.IGNORECASE),
    re.compile(r"not currently live", re.IGNORECASE),
]

BEGIN_IN_RE = re.compile(
    r"this live event will begin in\s+(\d+)\s+(second|seconds|minute|minutes|hour|hours|day|days)",
    re.IGNORECASE,
)

CHAT_ACTIVITY_MARKERS = (
    "Writing video subtitles to:",
    "Writing video subtitles",
    "Destination:",
    "live_chat",
    ".json3",
    "[download]",
)


@dataclass
class RunSummary:
    return_code: int
    saw_write_activity: bool
    saw_auth_block: bool
    not_live: bool
    begins_in_seconds: int | None


def _parse_begins_in_seconds(line: str) -> int | None:
    m = BEGIN_IN_RE.search(line)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    mult = {
        "second": 1,
        "seconds": 1,
        "minute": 60,
        "minutes": 60,
        "hour": 3600,
        "hours": 3600,
        "day": 86400,
        "days": 86400,
    }[unit]
    return n * mult


def run_yt_dlp(cmd: list[str], logger: logging.Logger, stall_seconds: int = 240) -> RunSummary:
    logger.info("▶️ Chat command: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    saw_write_activity = False
    saw_auth_block = False
    not_live = False
    begins_in_seconds: int | None = None
    last_activity = time.time()

    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            logger.info(line)

            if any(marker in line for marker in CHAT_ACTIVITY_MARKERS):
                saw_write_activity = True
                last_activity = time.time()

            if any(p.search(line) for p in AUTH_PATTERNS):
                saw_auth_block = True

            if any(p.search(line) for p in NOT_LIVE_PATTERNS):
                not_live = True

            begins = _parse_begins_in_seconds(line)
            if begins is not None:
                begins_in_seconds = begins

            if saw_write_activity and (time.time() - last_activity) > stall_seconds:
                logger.info("⚠️ No chat write activity for %ss — treating as stalled, restarting...", stall_seconds)
                proc.kill()
                break

    except Exception as exc:
        logger.info("⚠️ Exception while reading yt-dlp output: %s", exc)
        try:
            proc.kill()
        except Exception:
            pass

    try:
        rc = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        rc = proc.wait()

    return RunSummary(
        return_code=rc,
        saw_write_activity=saw_write_activity,
        saw_auth_block=saw_auth_block,
        not_live=not_live,
        begins_in_seconds=begins_in_seconds,
    )


def build_base_cmd(yt_dlp_bin: str, channel: str, out_dir: str) -> list[str]:
    out_tmpl = os.path.join(out_dir, "%(epoch>%Y-%m-%d_%H-%M-%S)s_%(id)s.%(ext)s")
    return [
        yt_dlp_bin,
        "--newline",
        "--no-color",
        "--ignore-errors",
        "--no-abort-on-error",
        "--remote-components",
        "ejs:github",
        "--skip-download",
        "--live-from-start",
        "--write-subs",
        "--sub-langs",
        "live_chat",
        "--sub-format",
        "json3",
        "-o",
        out_tmpl,
        f"https://www.youtube.com/@{channel}/live",
    ]


def compute_sleep_seconds(summary: RunSummary, poll_slow: int, poll_fast: int, fast_mode_until_ts: float | None) -> int:
    now = time.time()

    if fast_mode_until_ts is not None and now < fast_mode_until_ts:
        return poll_fast

    if summary.saw_write_activity and summary.return_code == 0:
        return 15

    if summary.not_live:
        return poll_slow

    if summary.begins_in_seconds is not None:
        s = summary.begins_in_seconds
        if s >= 6 * 3600:
            return 20 * 60
        if s >= 2 * 3600:
            return 15 * 60
        if s >= 30 * 60:
            return 5 * 60
        if s >= 5 * 60:
            return poll_fast
        return 15

    return poll_fast


def main() -> int:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

    p = argparse.ArgumentParser()
    p.add_argument("channel")
    p.add_argument("out_dir")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cookies", dest="cookies", help="cookies.txt for yt-dlp")
    g.add_argument("--cookies-from-browser", dest="cookies_from_browser", help="yt-dlp browser name (e.g. firefox)")
    p.add_argument("--cookie-fallback", action="store_true", help="Try without cookies first, then with cookies if AUTH problems detected")
    p.add_argument("--yt-dlp-bin", default="yt-dlp", help="Absolute path or command name for yt-dlp")
    p.add_argument("--stall-seconds", type=int, default=240, help="Restart if no chat write activity for this long (only after chat starts)")
    p.add_argument("--poll-slow", type=int, default=240, help="Seconds between checks when channel is not live")
    p.add_argument("--poll-fast", type=int, default=60, help="Seconds between checks when close to live or in fast mode")
    p.add_argument("--fast-enter-minutes", type=int, default=30, help="Enter fast mode when scheduled start is within this many minutes")
    p.add_argument("--late-grace-minutes", type=int, default=20, help="Keep fast mode for this many minutes AFTER scheduled start")
    p.add_argument("--auth-backoff-initial", type=int, default=600, help="Initial backoff after auth/bot blocks in seconds")
    p.add_argument("--auth-backoff-max", type=int, default=3600, help="Maximum backoff after repeated auth/bot blocks in seconds")
    p.add_argument("--prefer-cookies-minutes", type=int, default=180, help="After an auth problem, prefer starting WITH cookies for this many minutes")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    logger = _setup_logger(repo_root, args.channel)

    yt_dlp_bin = os.path.expanduser(args.yt_dlp_bin)
    if not os.path.isabs(yt_dlp_bin):
        yt_dlp_bin = shutil.which(yt_dlp_bin) or yt_dlp_bin
    logger.info("Using yt-dlp binary: %s", yt_dlp_bin)

    cookie_args: list[str] = []
    if args.cookies:
        cookie_args = ["--cookies", os.path.expanduser(args.cookies)]
    elif args.cookies_from_browser:
        cookie_args = ["--cookies-from-browser", args.cookies_from_browser]

    base_cmd = build_base_cmd(yt_dlp_bin, args.channel, args.out_dir)
    fast_mode_until_ts: float | None = None
    fast_enter_threshold = max(1, args.fast_enter_minutes) * 60
    late_grace_seconds = max(0, args.late_grace_minutes) * 60
    auth_failures = 0
    prefer_cookies_until_ts: float | None = None

    def maybe_update_fast_mode(summary: RunSummary) -> None:
        nonlocal fast_mode_until_ts
        if summary.begins_in_seconds is None:
            return
        s = summary.begins_in_seconds
        if s <= fast_enter_threshold:
            candidate = time.time() + s + late_grace_seconds
            prev = fast_mode_until_ts or 0
            fast_mode_until_ts = max(prev, candidate)
            if candidate > prev + 1:
                remaining = int(fast_mode_until_ts - time.time())
                logger.info("⚡ Fast mode active for ~%ss (covers scheduled start + lateness buffer).", max(0, remaining))

    while True:
        start_with_cookies = bool(
            cookie_args
            and prefer_cookies_until_ts is not None
            and time.time() < prefer_cookies_until_ts
        )

        cmd = base_cmd.copy()
        if start_with_cookies:
            cmd[1:1] = cookie_args
            logger.info("🍪 Preferring cookies-first mode due to recent auth/bot block.")

        summary = run_yt_dlp(cmd, logger, stall_seconds=args.stall_seconds)
        maybe_update_fast_mode(summary)

        if summary.return_code == 0 and summary.saw_write_activity:
            auth_failures = 0
            logger.info("✅ Chat recorder cycle completed; next check in 15s...")
            time.sleep(15)
            continue

        if args.cookie_fallback and cookie_args and (not start_with_cookies) and summary.saw_auth_block:
            logger.info("🔁 Auth/challenge issue detected — retrying chat WITH cookies...")
            cmd2 = base_cmd.copy()
            cmd2[1:1] = cookie_args
            summary2 = run_yt_dlp(cmd2, logger, stall_seconds=args.stall_seconds)
            maybe_update_fast_mode(summary2)

            if summary2.return_code == 0 and summary2.saw_write_activity:
                auth_failures = 0
                prefer_cookies_until_ts = time.time() + max(1, args.prefer_cookies_minutes) * 60
                logger.info("✅ Chat recorder cycle completed with cookies; next check in 15s...")
                time.sleep(15)
                continue

            summary = summary2

        if summary.saw_auth_block:
            auth_failures += 1
            prefer_cookies_until_ts = time.time() + max(1, args.prefer_cookies_minutes) * 60
            sleep_s = min(args.auth_backoff_max, args.auth_backoff_initial * (2 ** (auth_failures - 1)))
            logger.info(
                "🚫 Auth/bot block detected (count=%s). Backing off chat checks for %ss to avoid hammering YouTube.",
                auth_failures,
                sleep_s,
            )
            time.sleep(sleep_s)
            continue

        if summary.not_live or summary.begins_in_seconds is not None:
            auth_failures = 0

        sleep_s = compute_sleep_seconds(summary, args.poll_slow, args.poll_fast, fast_mode_until_ts)
        logger.info("⏳ No chat recording. Next check in %ss...", sleep_s)
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())
