#!/usr/bin/env python3
import os
import sys
import subprocess
from datetime import datetime

# Path to yt-chat-to-video.py relative to this file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
YT_CHAT_TO_VIDEO = os.path.join(SCRIPT_DIR, "yt-chat-to-video", "yt-chat-to-video.py")


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[chat_render {ts}] {msg}")


def render_chat_json(json_path: str, extra_args=None):
    """
    Render a single YouTube live chat JSON file into a video using yt-chat-to-video.py.
    If extra_args is provided (list of strings), they are appended to the CLI.
    """
    if not os.path.isfile(json_path):
        log(f"⚠️ Chat JSON not found: {json_path}")
        return False

    if not os.path.isfile(YT_CHAT_TO_VIDEO):
        log(f"⚠️ yt-chat-to-video.py not found at: {YT_CHAT_TO_VIDEO}")
        return False

    json_path = os.path.abspath(json_path)
    cmd = [sys.executable, YT_CHAT_TO_VIDEO, json_path]

    if extra_args:
        cmd.extend(extra_args)

    log(f"🎬 Rendering chat JSON -> video: {json_path}")
    log("    Command: " + " ".join(cmd))

    try:
        subprocess.run(cmd, check=True)
        log("✅ Chat render completed")
        return True
    except subprocess.CalledProcessError as e:
        log(f"⚠️ Chat render failed with exit code {e.returncode}")
    except Exception as e:
        log(f"⚠️ Chat render error: {e}")

    return False


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {os.path.basename(sys.argv[0])} <chat_json> [extra yt-chat-to-video args...]")
        sys.exit(1)

    json_path = sys.argv[1]
    extra = sys.argv[2:] if len(sys.argv) > 2 else None
    ok = render_chat_json(json_path, extra_args=extra)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
