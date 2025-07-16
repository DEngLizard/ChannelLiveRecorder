# live-recording-helper.py (orchestrator) - UPDATED
import subprocess
import time
import yaml
import signal
import sys
import os
import argparse

RECORDER_PATH = os.path.join('recorder', 'live_stream_recorder.py')
CONFIG_PATH = './channellist.yaml'
CHECK_INTERVAL = 300  # seconds

running_processes = {}
cookies_arg = []

def load_channels():
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
        return config.get('channels', [])

def start_recorder(channel_cfg):
    name = channel_cfg['name']
    target = os.path.abspath(channel_cfg['target'])

    # Ensure the directory exists
    os.makedirs(target, exist_ok=True)

    cmd = [sys.executable, RECORDER_PATH, name, target] + cookies_arg

    print(f"\U0001F680 Starting recorder for @{name}, saving to {target}")
    return subprocess.Popen(cmd)

def stop_recorder(channel_name):
    proc = running_processes.get(channel_name)
    if proc and proc.poll() is None:
        print(f"🛑 Stopping recorder for @{channel_name}")
        proc.terminate()
        proc.wait()
    running_processes.pop(channel_name, None)

def cleanup(signum, frame):
    print("\n\U0001F9F9 Cleaning up all recorders...")
    for channel in list(running_processes.keys()):
        stop_recorder(channel)
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    while True:
        configs = load_channels()
        active_channels = {cfg['name']: cfg for cfg in configs}
        current_channels = set(running_processes.keys())

        for name, cfg in active_channels.items():
            if name not in current_channels:
                running_processes[name] = start_recorder(cfg)

        for name in current_channels - set(active_channels.keys()):
            stop_recorder(name)

        for name in list(active_channels.keys()):
            proc = running_processes.get(name)
            if proc and proc.poll() is not None:
                print(f"\U0001F501 Restarting dead recorder for @{name}")
                running_processes[name] = start_recorder(active_channels[name])

        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookies-from-browser', metavar='BROWSER', help='Forward browser cookie login to record members-only streams')
    args = parser.parse_args()

    if args.cookies_from_browser:
        cookies_arg = ["--cookies-from-browser", args.cookies_from_browser]

    main()
