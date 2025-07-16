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

init()

FAST_POLL_INTERVAL = 15
DEFAULT_POLL_INTERVAL = 300
FAST_POLL_DURATION = timedelta(minutes=30)
log_files = {}

def log(msg, channel=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = f"[{timestamp}] "
    if channel:
        tag = f"{Fore.CYAN + Style.BRIGHT}[@{channel}]{Style.RESET_ALL}"
        log_line = f"{prefix}{tag} {msg}"
        log_path = log_files.get(channel)
        if log_path:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [@{channel}] {msg}\n")
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

def start_recording(video_url, output_dir, channel):
    os.makedirs(output_dir, exist_ok=True)
    log(f"🔴 Starting recording to {output_dir}", channel)

    log_path = os.path.join(output_dir, f"{channel}.log")
    log_files[channel] = log_path

    process = subprocess.Popen(
        [
            'yt-dlp',
            '--live-from-start',
            '-o', os.path.join(output_dir, '%(title)s.%(ext)s'),
            video_url
        ],
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
    log(f"🎯 Monitoring", channel)
    os.makedirs(base_output_path, exist_ok=True)

    recording_proc = None
    fast_polling = False
    fast_polling_start = None

    while True:
        if recording_proc and recording_proc.poll() is not None:
            log("🛑 Recording ended.", channel)
            recording_proc = None

        if not recording_proc:
            stream = is_currently_live(channel)
            if stream:
                recording_proc = start_recording(stream['url'], base_output_path, channel)
                fast_polling = False
                continue

        if fast_polling and datetime.now(timezone.utc) - fast_polling_start > FAST_POLL_DURATION:
            log("⏳ Fast polling timed out. Rechecking /streams.", channel)
            fast_polling = False

        if not fast_polling:
            upcoming = get_stream_info(channel)
            if upcoming:
                fast_polling = True
                fast_polling_start = datetime.now(timezone.utc)
                log(f"📅 Upcoming stream at {upcoming['scheduled_time']}. Entering fast polling...", channel)

        time.sleep(FAST_POLL_INTERVAL if fast_polling else DEFAULT_POLL_INTERVAL)

def cleanup(signum, frame):
    print("\n🧹 Clean exit.")
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if len(sys.argv) < 3:
        print("Usage: python live_stream_recorder.py <channel_name> <output_path>")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])
