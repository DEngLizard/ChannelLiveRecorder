import time
import subprocess
import yt_dlp
import signal
import sys
import os
import re
from datetime import datetime, timedelta, timezone
import contextlib
import io
from colorama import init, Fore, Style
import threading
import argparse

init()

FAST_POLL_INTERVAL = 60
DEFAULT_POLL_INTERVAL = 220
FAST_POLL_DURATION = timedelta(minutes=30)
log_files = {}
cookies_file = None          # Path to cookies.txt
cookies_from_browser = None  # Browser name for --cookies-from-browser
running = True               # global run flag


def log(msg, channel=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = f"[{timestamp}] "
    if channel:
        tag = f"{Fore.MAGENTA + Style.BRIGHT}[chat:@{channel}]{Style.RESET_ALL}"
        log_line = f"{prefix}{tag} {msg}"
        log_path = log_files.get(channel)
        if log_path:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [chat:@{channel}] {msg}\n")
    else:
        log_line = f"{prefix}{msg}"
    print(log_line)


@contextlib.contextmanager
def suppress_stderr():
    stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = stderr


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', name).strip()


def get_stream_info(channel):
    url = f'https://www.youtube.com/@{channel}/streams'
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extract_flat': True,
        'force_generic_extractor': True,
    }
    with suppress_stderr(), yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            for entry in info.get('entries', []):
                if entry.get('release_timestamp'):
                    scheduled = datetime.fromtimestamp(entry['release_timestamp'], tz=timezone.utc)
                    return {'url': entry['url'], 'scheduled_time': scheduled}
        except Exception as e:
            log(f"⚠️ Error checking upcoming: {e}", channel)
    return None


def is_currently_live(channel):
    url = f'https://www.youtube.com/@{channel}/live'
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': True,
    }
    try:
        with suppress_stderr(), yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('is_live'):
                return {
                    'url': info['webpage_url'],
                    'title': sanitize_filename(info.get('title', f'{channel}_stream'))
                }
            elif info.get('release_timestamp'):
                scheduled = datetime.fromtimestamp(info['release_timestamp'], tz=timezone.utc)
                now = datetime.now(timezone.utc)
                delta = scheduled - now
                if delta.total_seconds() > 0:
                    mins = int(delta.total_seconds() // 60)
                    secs = int(delta.total_seconds() % 60)
                    log(f"ℹ️ Stream will begin in {mins}m {secs}s at {scheduled}.", channel)
    except yt_dlp.utils.DownloadError as e:
        error_str = str(e).lower()
        if 'this live event will begin' in error_str or 'not currently live' in error_str:
            log(f"ℹ️ Not currently live.", channel)
        else:
            log(f"⚠️ Error checking live URL: {e}", channel)
    except Exception as e:
        log(f"⚠️ Unknown error: {e}", channel)

    log(f"ℹ️ Not currently live.", channel)
    return None


def start_chat_recording(video_url, output_dir, channel):
    os.makedirs(output_dir, exist_ok=True)
    log(f"💬 Starting chat recording to {output_dir}", channel)

    log_path = os.path.join(output_dir, f"{channel}_chat.log")
    log_files[channel] = log_path
    timestamp_prefix = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    out_template = os.path.join(output_dir, f'{timestamp_prefix}_%(id)s.%(ext)s')

    cmd = [
        'yt-dlp',
        '--skip-download',
        '--write-subs',
        '--sub-langs', 'live_chat',
        '--sub-format', 'json3',
        '-o', out_template,
    ]

    # Prefer browser cookies over file if both somehow set
    if cookies_from_browser:
        cmd += ['--cookies-from-browser', cookies_from_browser]
    elif cookies_file:
        cmd += ['--cookies', cookies_file]

    cmd.append(video_url)

    log(f"▶️ Chat command: {' '.join(cmd)}", channel)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    def stream_output():
        for line in process.stdout:
            line = line.strip()
            if line:
                log(line, channel)

    threading.Thread(target=stream_output, daemon=True).start()
    return process


def main(channel, base_output_path):
    global running
    log(f"🎯 Monitoring chat", channel)
    os.makedirs(base_output_path, exist_ok=True)

    recording_proc = None
    fast_polling = False
    fast_polling_start = None

    while running:
        if recording_proc and recording_proc.poll() is not None:
            log("🛑 Chat recording ended.", channel)
            recording_proc = None

        if not running:
            break

        if not recording_proc:
            stream = is_currently_live(channel)
            if stream:
                recording_proc = start_chat_recording(stream['url'], base_output_path, channel)
                fast_polling = False
                continue

        if fast_polling and datetime.now(timezone.utc) - fast_polling_start > FAST_POLL_DURATION:
            log("⏳ Chat fast polling timed out. Rechecking /streams.", channel)
            fast_polling = False

        if not fast_polling:
            upcoming = get_stream_info(channel)
            if upcoming:
                fast_polling = True
                fast_polling_start = datetime.now(timezone.utc)
                log(f"📅 Upcoming stream (chat) at {upcoming['scheduled_time']}. Entering fast polling...", channel)

        time.sleep(FAST_POLL_INTERVAL if fast_polling else DEFAULT_POLL_INTERVAL)

    log("👋 Exiting chat main loop.", channel)


def cleanup(signum, frame):
    global running
    print("\n🧹 Clean exit (chat recorder).")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    parser = argparse.ArgumentParser(
        description="Record YouTube live chat for a single channel."
    )
    parser.add_argument('channel_name', help='YouTube @channel name (without @)')
    parser.add_argument('output_path', help='Directory to save chat logs')

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--cookies',
        metavar='COOKIE_FILE',
        help='Path to cookies.txt to be passed to yt-dlp as --cookies'
    )
    group.add_argument(
        '--cookies-from-browser',
        metavar='BROWSER',
        help='Browser name for yt-dlp --cookies-from-browser (e.g. firefox, chrome)'
    )

    args = parser.parse_args()

    if args.cookies:
        candidate = os.path.expanduser(args.cookies)
        if os.path.isfile(candidate):
            cookies_file = os.path.abspath(candidate)
            print(f"Using cookies file for chat: {cookies_file}")
        else:
            print(f"⚠️ Cookies file not found: {candidate} (continuing without cookies)")
    elif args.cookies_from_browser:
        cookies_from_browser = args.cookies_from_browser
        print(f"Using cookies from browser for chat: {cookies_from_browser}")

    main(args.channel_name, args.output_path)
