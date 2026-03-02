#!/usr/bin/env python3
"""Single-channel LIVE video recorder.

Behavior goals:
- Poll /@channel/live forever.
- Use sane polling intervals:
    * NOT LIVE  -> slow poll (default 240s)
    * SCHEDULED -> adaptive poll based on "will begin in X ..."
    * FAST MODE -> once we are close to scheduled start, poll ~every minute AND
                   keep that fast polling for a grace period after scheduled start
                   (streamers can be 5–15 minutes late).
    * LIVE/RECORDING -> yt-dlp runs until stream ends; then short pause and resume monitoring
- Cookie fallback ONLY for auth/bot/challenge failures, not for "not live" or "begins in".
- Always enables EJS remote components: --remote-components ejs:github
- Auto-caps "scheduled far away" polling at 20 minutes max.
- Uses --live-from-start so even if we detect late, we still capture from the beginning (as allowed).
- Writes logs to logs/video_<channel>.log

Usage:
  python recorder/live_stream_recorder.py <ChannelName> <TempDir> [--cookies-from-browser firefox] [--cookie-fallback]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import logging
from dataclasses import dataclass


# -------- logging --------

def _setup_logger(repo_root: str, channel: str) -> logging.Logger:
    log_dir = os.path.join(repo_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(f"video:{channel}")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(os.path.join(log_dir, f"video_{channel}.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


# -------- output classification --------

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

# Example: "This live event will begin in 10 hours."
BEGIN_IN_RE = re.compile(
    r"this live event will begin in\s+(\d+)\s+(second|seconds|minute|minutes|hour|hours|day|days)",
    re.IGNORECASE,
)

DOWNLOAD_ACTIVITY_MARKERS = (
    "[download]",
    "Destination:",
    "Downloading",
    "Merging formats",
    "Fixing malformed",   # ffmpeg fixups sometimes
)


@dataclass
class RunSummary:
    return_code: int
    saw_download_activity: bool
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
        "second": 1, "seconds": 1,
        "minute": 60, "minutes": 60,
        "hour": 3600, "hours": 3600,
        "day": 86400, "days": 86400,
    }[unit]
    return n * mult


def run_yt_dlp(cmd: list[str], logger: logging.Logger, stall_seconds: int = 180) -> RunSummary:
    """Run yt-dlp and stream output. Stall watchdog triggers if no download activity for a while."""
    logger.info("▶️ Video command: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    saw_download_activity = False
    saw_auth_block = False
    not_live = False
    begins_in_seconds: int | None = None
    last_activity = time.time()

    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            logger.info(line)

            # download activity detection
            if any(m in line for m in DOWNLOAD_ACTIVITY_MARKERS):
                saw_download_activity = True
                last_activity = time.time()

            # classify
            if any(p.search(line) for p in AUTH_PATTERNS):
                saw_auth_block = True

            if any(p.search(line) for p in NOT_LIVE_PATTERNS):
                not_live = True

            bi = _parse_begins_in_seconds(line)
            if bi is not None:
                begins_in_seconds = bi

            # Stall watchdog: only meaningful if we expected to be downloading.
            if saw_download_activity and (time.time() - last_activity) > stall_seconds:
                logger.info("⚠️ No download activity for %ss — treating as stalled, restarting...", stall_seconds)
                proc.kill()
                break

    except Exception as e:
        logger.info("⚠️ Exception while reading yt-dlp output: %s", e)
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
        saw_download_activity=saw_download_activity,
        saw_auth_block=saw_auth_block,
        not_live=not_live,
        begins_in_seconds=begins_in_seconds,
    )


def build_base_cmd(channel: str, out_dir: str) -> list[str]:
    out_tmpl = os.path.join(out_dir, "%(epoch>%Y-%m-%d_%H-%M-%S)s_%(id)s_%(title)s.%(ext)s")
    return [
        "yt-dlp",
        "--newline",
        "--no-color",
        "--ignore-errors",
        "--no-abort-on-error",
        "--remote-components",
        "ejs:github",
        "--merge-output-format",
        "mp4",
        "--live-from-start",
        "-o",
        out_tmpl,
        f"https://www.youtube.com/@{channel}/live",
    ]


def compute_sleep_seconds(
    logger: logging.Logger,
    summary: RunSummary,
    poll_slow: int,
    poll_fast: int,
    fast_mode_until_ts: float | None,
) -> int:
    now = time.time()

    # If we’re inside the "fast mode" window (near scheduled start or a bit after),
    # do NOT drop back to slow polling even if yt-dlp says "not live".
    if fast_mode_until_ts is not None and now < fast_mode_until_ts:
        return poll_fast

    # If yt-dlp actually downloaded/recorded something, keep the loop responsive.
    if summary.saw_download_activity and summary.return_code == 0:
        return 15

    # Not live: slow polling
    if summary.not_live:
        return poll_slow

    # Scheduled: adaptive polling based on begin time
    if summary.begins_in_seconds is not None:
        s = summary.begins_in_seconds

        # Far away -> don't hammer YouTube, cap max wait at 20 minutes
        if s >= 6 * 3600:
            return 20 * 60
        if s >= 2 * 3600:
            return 15 * 60
        if s >= 30 * 60:
            return 5 * 60
        if s >= 5 * 60:
            return poll_fast
        return 15  # last 5 minutes

    # Generic failure: default to fast-ish retry
    return poll_fast


def main() -> int:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

    p = argparse.ArgumentParser()
    p.add_argument("channel")
    p.add_argument("out_dir")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cookies", dest="cookies", help="cookies.txt for yt-dlp")
    g.add_argument("--cookies-from-browser", dest="cookies_from_browser", help="yt-dlp browser name (e.g. firefox)")
    p.add_argument(
        "--cookie-fallback",
        action="store_true",
        help="Try without cookies first, then with cookies if AUTH problems detected",
    )
    p.add_argument(
        "--stall-seconds",
        type=int,
        default=180,
        help="Kill/restart if no download activity for this long (only after download starts)",
    )
    p.add_argument("--poll-slow", type=int, default=240, help="Seconds between checks when channel is not live")
    p.add_argument("--poll-fast", type=int, default=60, help="Seconds between checks when close to live or in fast mode")
    p.add_argument(
        "--fast-enter-minutes",
        type=int,
        default=30,
        help="Enter fast mode when scheduled start is within this many minutes",
    )
    p.add_argument(
        "--late-grace-minutes",
        type=int,
        default=20,
        help="Keep fast mode for this many minutes AFTER scheduled start (lateness buffer)",
    )
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    logger = _setup_logger(repo_root, args.channel)

    cookie_args: list[str] = []
    if args.cookies:
        cookie_args = ["--cookies", os.path.expanduser(args.cookies)]
    elif args.cookies_from_browser:
        cookie_args = ["--cookies-from-browser", args.cookies_from_browser]

    base_cmd = build_base_cmd(args.channel, args.out_dir)

    # Fast-mode window tracking
    fast_mode_until_ts: float | None = None
    fast_enter_threshold = max(1, args.fast_enter_minutes) * 60
    late_grace_seconds = max(0, args.late_grace_minutes) * 60

    def maybe_update_fast_mode(summary: RunSummary) -> None:
        """If we see a scheduled time, enter/extend fast mode near start and keep through lateness grace."""
        nonlocal fast_mode_until_ts
        if summary.begins_in_seconds is None:
            return

        s = summary.begins_in_seconds
        if s <= fast_enter_threshold:
            candidate = time.time() + s + late_grace_seconds
            prev = fast_mode_until_ts or 0
            fast_mode_until_ts = max(prev, candidate)
            # Log only when it changes meaningfully
            if candidate > prev + 1:
                remaining = int(fast_mode_until_ts - time.time())
                logger.info("⚡ Fast mode active for ~%ss (covers scheduled start + lateness buffer).", max(0, remaining))

    while True:
        # 1) Try WITHOUT cookies
        summary = run_yt_dlp(base_cmd.copy(), logger, stall_seconds=args.stall_seconds)
        maybe_update_fast_mode(summary)

        # If success & download happened, continue loop after short delay
        if summary.return_code == 0 and summary.saw_download_activity:
            logger.info("✅ Video recorder cycle completed; next check in 15s...")
            time.sleep(15)
            continue

        # 2) Cookie fallback ONLY for auth/challenge-type failures
        if args.cookie_fallback and cookie_args and summary.saw_auth_block:
            logger.info("🔁 Auth/challenge issue detected — retrying WITH cookies...")
            cmd2 = base_cmd.copy()
            cmd2[1:1] = cookie_args
            summary2 = run_yt_dlp(cmd2, logger, stall_seconds=args.stall_seconds)
            maybe_update_fast_mode(summary2)

            if summary2.return_code == 0 and summary2.saw_download_activity:
                logger.info("✅ Video recorder cycle completed with cookies; next check in 15s...")
                time.sleep(15)
                continue

            # Use the second summary for sleep decision if we tried cookies
            summary = summary2

        sleep_s = compute_sleep_seconds(
            logger,
            summary,
            poll_slow=args.poll_slow,
            poll_fast=args.poll_fast,
            fast_mode_until_ts=fast_mode_until_ts,
        )
        logger.info("⏳ No recording. Next check in %ss...", sleep_s)
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())