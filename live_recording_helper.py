# live-recording-helper.py (orchestrator)
import subprocess
import time
import yaml
import signal
import sys
import os
import argparse

RECORDER_PATH = os.path.join('recorder', 'live_stream_recorder.py')
CHAT_RECORDER_PATH = os.path.join('recorder', 'live_chat_recorder.py')
CONFIG_PATH = './channellist.yaml'
TEMP_BASE = './temp'          # base temp directory
CHECK_INTERVAL = 240  # seconds

MOVER_PATH = os.path.join('tools', 'move_to_location.py')

# running_processes[channel_name] = {"video": Popen, "chat": Popen}
running_processes = {}
cookies_args = []  # passed through to both recorders
mover_proc = None  # global handle for the mover process
shutting_down = False  # avoid double cleanup


def load_channels():
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
        return config.get('channels', [])


def temp_dir_for_channel(name: str) -> str:
    return os.path.abspath(os.path.join(TEMP_BASE, name))


def start_video_recorder(channel_cfg):
    name = channel_cfg['name']
    temp_target = temp_dir_for_channel(name)

    os.makedirs(temp_target, exist_ok=True)

    cmd = [sys.executable, RECORDER_PATH, name, temp_target] + cookies_args

    print(f"🚀 Starting VIDEO recorder for @{name}, saving to temp {temp_target}")
    # start_new_session=True → child doesn't receive Ctrl+C from the terminal
    return subprocess.Popen(
        cmd,
        start_new_session=True,
    )


def start_chat_recorder(channel_cfg):
    name = channel_cfg['name']
    temp_target = temp_dir_for_channel(name)

    os.makedirs(temp_target, exist_ok=True)

    cmd = [sys.executable, CHAT_RECORDER_PATH, name, temp_target] + cookies_args

    print(f"💬 Starting CHAT recorder for @{name}, saving to temp {temp_target}")
    return subprocess.Popen(
        cmd,
        start_new_session=True,
    )


def start_recorders(channel_cfg):
    procs = {}
    procs["video"] = start_video_recorder(channel_cfg)
    time.sleep(1)  # tiny stagger
    procs["chat"] = start_chat_recorder(channel_cfg)
    return procs


def stop_proc(label, proc):
    if proc and proc.poll() is None:
        print(f"🛑 Stopping {label}")
        try:
            proc.terminate()
        except Exception as e:
            print(f"⚠️ Error sending terminate to {label}: {e}")
        try:
            # Short timeout so shutdown feels snappy
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            print(f"⚠️ {label} did not exit, killing...")
            try:
                proc.kill()
            except Exception as e:
                print(f"⚠️ Error killing {label}: {e}")
        except Exception as e:
            print(f"⚠️ Error while waiting for {label}: {e}")


def stop_recorder(channel_name):
    procs = running_processes.get(channel_name, {})
    stop_proc(f"VIDEO recorder for @{channel_name}", procs.get("video"))
    stop_proc(f"CHAT recorder for @{channel_name}", procs.get("chat"))
    running_processes.pop(channel_name, None)


def start_mover():
    """Start tools/move_to_location.py as a sidecar process."""
    global mover_proc
    if mover_proc is not None and mover_proc.poll() is None:
        return  # already running

    if not os.path.isfile(MOVER_PATH):
        print(f"⚠️ Mover script not found at {MOVER_PATH} – skipping mover start.")
        return

    cmd = [sys.executable, MOVER_PATH]
    print(f"🚚 Starting mover process: {' '.join(cmd)}")
    mover_proc = subprocess.Popen(
        cmd,
        start_new_session=True,  # don't forward Ctrl+C to mover either
    )


def stop_mover():
    """Stop the mover process if running."""
    global mover_proc
    if mover_proc and mover_proc.poll() is None:
        stop_proc("mover process", mover_proc)
    mover_proc = None


def cleanup(signum, frame):
    global shutting_down
    if shutting_down:
        # Ignore repeated Ctrl+C while we're already shutting down
        return
    shutting_down = True

    print("\n🧹 Cleaning up all recorders...")
    # Stop all channel recorders
    for channel in list(running_processes.keys()):
        stop_recorder(channel)

    # Stop mover
    stop_mover()

    print("👋 Helper exiting.")
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    os.makedirs(TEMP_BASE, exist_ok=True)

    # Start mover sidecar once
    start_mover()

    while True:
        configs = load_channels()
        active_channels = {cfg['name']: cfg for cfg in configs}
        current_channels = set(running_processes.keys())

        # Start new recorders for newly configured channels
        for name, cfg in active_channels.items():
            if name not in current_channels:
                running_processes[name] = start_recorders(cfg)
                time.sleep(2)

        # Stop recorders for channels no longer in config
        for name in current_channels - set(active_channels.keys()):
            stop_recorder(name)

        # Restart dead recorders for active channels
        for name in list(active_channels.keys()):
            procs = running_processes.get(name, {})
            for kind in ("video", "chat"):
                proc = procs.get(kind)
                if proc and proc.poll() is not None:
                    print(f"🔁 Restarting dead {kind.UPPER()} recorder for @{name}")
                    if kind == "video":
                        procs["video"] = start_video_recorder(active_channels[name])
                    else:
                        procs["chat"] = start_chat_recorder(active_channels[name])
                    time.sleep(1)
            running_processes[name] = procs

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Orchestrate multiple live stream recorders (video + chat) into temp dirs."
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--cookies',
        metavar='COOKIE_FILE',
        help='Path to cookies.txt to be forwarded to all recorders (yt-dlp --cookies)'
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
            cookies_args = ["--cookies", candidate]
            print(f"Using cookies file for all recorders: {candidate}")
        else:
            print(f"⚠️ Cookies file not found: {candidate} (continuing without cookies)")
    elif args.cookies_from_browser:
        cookies_args = ["--cookies-from-browser", args.cookies_from_browser]
        print(f"Using cookies from browser for all recorders: {args.cookies_from_browser}")

    main()
