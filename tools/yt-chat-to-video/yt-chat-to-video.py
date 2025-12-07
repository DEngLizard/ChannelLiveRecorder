import os
import re
import argparse
import subprocess
import requests
import json
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import math

# -------- Helpers to normalize YouTube chat records --------
def _extract_renderer_and_times(obj):
    """
    Return (renderer, ts_usec:int|None, offset_ms:int|None) for a single action-like object.
    Supports replay wrappers, live wrappers, and non-text renderers (paid/membership/sticker).
    """
    def pick_renderer_from_item(item_dict):
        """Pick first renderer that carries a timestamp."""
        if not isinstance(item_dict, dict):
            return None
        preferred_keys = [
            'liveChatTextMessageRenderer',
            'liveChatPaidMessageRenderer',
            'liveChatMembershipItemRenderer',
            'liveChatPaidStickerRenderer',
            'liveChatViewerEngagementMessageRenderer',
            'liveChatLegacyPaidMessageRenderer',
        ]
        for k in preferred_keys:
            r = item_dict.get(k)
            if isinstance(r, dict) and ('timestampUsec' in r or 'timestampText' in r):
                return r
        # Fallback: first dict value that has timestampUsec
        for v in item_dict.values():
            if isinstance(v, dict) and 'timestampUsec' in v:
                return v
        return None

    # Replay wrapper
    if isinstance(obj, dict) and 'replayChatItemAction' in obj:
        r = obj['replayChatItemAction']
        try:
            offset_ms = int(r.get('videoOffsetTimeMsec', 0))
        except Exception:
            offset_ms = 0
        for act in r.get('actions', []):
            add = act.get('addChatItemAction')
            if not isinstance(add, dict):
                continue
            item = add.get('item', {})
            renderer = pick_renderer_from_item(item)
            if renderer:
                ts_usec = int(renderer.get('timestampUsec')) if 'timestampUsec' in renderer else None
                return renderer, ts_usec, offset_ms
        return None, None, offset_ms

    # Live wrapper
    if isinstance(obj, dict) and 'addChatItemAction' in obj:
        item = obj['addChatItemAction'].get('item', {})
        renderer = pick_renderer_from_item(item)
        if renderer:
            ts_usec = int(renderer.get('timestampUsec')) if 'timestampUsec' in renderer else None
            return renderer, ts_usec, None

    return None, None, None


def _load_chat_actions(path):
    """
    Load chat as a list of 'action-like' dicts that _extract_renderer_and_times understands.
    Accepts:
      - JSONL (one object per line)
      - Single JSON object with 'actions'
      - JSON array of action objects
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    # Try whole-file JSON first
    try:
        data = json.loads(raw)
        # Case A: single dict with 'actions'
        if isinstance(data, dict) and 'actions' in data and isinstance(data['actions'], list):
            return data['actions']
        # Some yt-dlp replays: top-level has one action
        if isinstance(data, dict) and ('replayChatItemAction' in data or 'addChatItemAction' in data):
            return [data]
        # Case B: array of actions
        if isinstance(data, list):
            return data
        # Fall back to JSONL
        raise ValueError("Not a simple dict/list structure; try JSONL fallback")
    except Exception:
        pass

    # JSONL fallback: parse line-by-line, tolerate garbage lines
    actions = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            actions.append(obj)
        except Exception:
            continue
    return actions


# -------- Original small helpers --------

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def blend_colors(a_color, b_color, opacity):
    return tuple(int(a * opacity + b * (1 - opacity)) for a, b in zip(a_color, b_color))


# -------- Args --------

parser = argparse.ArgumentParser("yt-chat-to-video", add_help=False)
parser.add_argument('--help', action='help', default=argparse.SUPPRESS, help='Show this help message and exit.')
parser.add_argument('input_json_file', help='Path to YouTube live chat JSON file')
parser.add_argument('-o', '--output', help="Output filename")
parser.add_argument('-w', '--width', type=int, default=400, help="Output video width")
parser.add_argument('-h', '--height', type=int, default=540, help="Output video height")
parser.add_argument('-s', '--scale', dest='chat_scale', type=int, default=1, help="Chat resolution scale")
parser.add_argument('-r', '--frame-rate', type=int, default=10, help="Output video framerate")
parser.add_argument('-b', '--background', default="#0f0f0f", help="Chat background color")
parser.add_argument('--transparent', action='store_true', help="Make chat background transparent (forces output to transparent .webm)")
parser.add_argument('-p', '--padding', type=int, default=24, help="Chat inner padding")
parser.add_argument('-f', '--from', type=float, default=0, help='Start time in seconds')
parser.add_argument('-t', '--to', type=float, default=0, help='End time in seconds')
parser.add_argument('--skip-avatars', action='store_true', help='Skip downloading user avatars')
parser.add_argument('--skip-emojis', action='store_true', help='Skip downloading YouTube emoji thumbnails')
parser.add_argument('--no-clip', action='store_false', help='Don\'t clip chat messages at the top')
parser.add_argument('--use-cache', action='store_true', help='Cache downloaded avatars and emojis to disk')
parser.add_argument('--proxy', help='HTTP/HTTPS/SOCKS proxy (e.g. socks5://127.0.0.1:1080/)')
parser.add_argument('--fallback-gap-ms', type=int, default=1200,
                    help='Gap to use (ms) when timestamps collapse or duration is 0 (default: 1200)')
args = parser.parse_args()

# -------- Video sanity --------

width, height = args.width, args.height
fps = args.frame_rate
if width < 2: raise SystemExit("Error: Width must be greater than 2")
if width % 2 != 0: raise SystemExit("Error: Width must be even number")
if width < 100: raise SystemExit("Error: Width can't be less than 100px")
if height < 32: raise SystemExit("Error: Height can't be less than 32px")
if height % 2 != 0: raise SystemExit("Error: Height must be even number")
if fps < 1: raise SystemExit("Error: FPS can't be less than 1")

start_time_seconds = getattr(args, "from")
end_time_seconds = getattr(args, "to")

# -------- Chat style --------

chat_background = hex_to_rgb(args.background)
chat_author_color = blend_colors(hex_to_rgb('#ffffff'), chat_background, 0.7)
chat_message_color = hex_to_rgb('#ffffff')
chat_scale = args.chat_scale
chat_font_size = 13 * chat_scale
chat_padding = args.padding * chat_scale
chat_avatar_size = 24 * chat_scale
chat_emoji_size = 16 * chat_scale
chat_line_height = 16 * chat_scale
chat_avatar_padding = 16 * chat_scale
char_author_padding = 8 * chat_scale
chat_inner_x = chat_padding
chat_inner_width = width - (chat_padding * 2)

# -------- Output name / format --------

if not args.output:
    if not args.input_json_file.endswith('.json'):
        raise SystemExit("Error: Input file must be a JSON file")
    dot = args.input_json_file.rfind('.')
    args.output = args.input_json_file[:dot] + (".webm" if args.transparent else ".mp4")

if args.transparent and not args.output.endswith('.webm'):
    print("Warning: Transparent background requested — forcing .webm")
    dot = args.output.rfind('.')
    args.output = args.output[:dot] + ".webm"

# -------- Proxy --------

if args.proxy:
    os.environ['HTTP_PROXY'] = args.proxy
    os.environ['HTTPS_PROXY'] = args.proxy

# -------- Fonts --------

try:
    script_dir = os.path.dirname(os.path.realpath(__file__))
    chat_message_font = ImageFont.truetype(f"{script_dir}/fonts/Roboto-Regular.ttf", chat_font_size)
    chat_author_font = ImageFont.truetype(f"{script_dir}/fonts/Roboto-Medium.ttf", chat_font_size)
except Exception:
    print("\nWarning: Can't load Roboto fonts. Falling back to default.\n")
    chat_message_font = ImageFont.load_default()
    chat_author_font = ImageFont.load_default()

# -------- Load & normalize chat records --------

actions = _load_chat_actions(args.input_json_file)

# First pass: base timestamp for LIVE logs
first_ts_usec = None
for obj in actions:
    _, ts_usec, _ = _extract_renderer_and_times(obj)
    if ts_usec is not None:
        first_ts_usec = ts_usec if first_ts_usec is None else min(first_ts_usec, ts_usec)

# Build normalized message tuples: (time_ms, avatar_url, author, runs)
messages = []
for obj in actions:
    renderer, ts_usec, offset_ms = _extract_renderer_and_times(obj)
    if not renderer:
        continue

    # Compute time_ms
    if offset_ms is not None:
        time_ms = int(offset_ms)
    elif ts_usec is not None and first_ts_usec is not None:
        time_ms = max(0, int((ts_usec - first_ts_usec) / 1000))  # usec → ms offset
    else:
        continue  # no timing info

    # Time window filter: don't break (input might not be sorted)
    if end_time_seconds != 0 and time_ms > int(end_time_seconds * 1000):
        continue

    # Extract fields
    avatar_url = ""
    try:
        avatar_url = renderer['authorPhoto']['thumbnails'][0]['url']
    except Exception:
        pass

    author = renderer.get('authorName', {}).get('simpleText', '')

    runs = []
    try:
        for run in renderer.get('message', {}).get('runs', []):
            if 'text' in run:
                txt = run['text'].strip()
                if txt:
                    runs.append((0, txt))
            elif 'emoji' in run:
                emoji_url = run['emoji']['image']['thumbnails'][0]['url']
                runs.append((1, emoji_url))
    except Exception:
        # Tolerate odd messages (stickers, paid messages, etc.)
        # Keep an empty line so the author row still renders
        pass

    # If there are truly no runs, provide a minimal placeholder to keep layout stable
    if not runs:
        runs.append((0, ""))

    messages.append((int(time_ms), avatar_url, author, runs))

if not messages:
    if end_time_seconds != 0:
        raise SystemExit("Error: No messages within selected time window")
    raise SystemExit("Error: No messages found in the chat file")

# Sort and compute duration
messages.sort(key=lambda m: m[0])
max_duration_seconds = messages[-1][0] / 1000.0

if end_time_seconds == 0:
    end_time_seconds = max_duration_seconds

duration_seconds = max(0.0, float(end_time_seconds) - float(start_time_seconds))

# --- Fallback if duration is 0 or times are non-increasing ---
if duration_seconds <= 0.0 or all(m[0] == messages[0][0] for m in messages):
    gap = max(1, int(args.fallback_gap_ms))  # ms
    t = 0
    retimed = []
    for (_, avatar_url, author, runs) in messages:
        retimed.append((t, avatar_url, author, runs))
        t += gap
    messages = retimed
    max_duration_seconds = messages[-1][0] / 1000.0
    if end_time_seconds == 0:
        end_time_seconds = max_duration_seconds
    duration_seconds = max(0.0, float(end_time_seconds) - float(start_time_seconds))

# Guard again after fallback
if duration_seconds <= 0.0:
    raise SystemExit(f"Error: Computed duration is 0s (start={start_time_seconds}s, end={end_time_seconds}s). "
                     "Input appears to have no usable timing; try a different JSON or increase --fallback-gap-ms.")

# -------- ffmpeg pipe --------
try:
    ffmpeg = subprocess.Popen([
        'ffmpeg',
        '-y',
        '-f', 'rawvideo',
        '-pix_fmt', ('rgba' if args.transparent else 'rgb24'),
        '-s', f'{width}x{height}',
        '-r', str(fps),
        '-i', '-',           # stdin
        '-an',
        '-vcodec', ('libvpx-vp9' if args.transparent else 'libx264'),
        '-pix_fmt', ('yuva420p' if args.transparent else 'yuv420p'),
        args.output
    ], stdin=subprocess.PIPE)  # keep stderr visible for debugging
except Exception:
    print("Error: ffmpeg not found. Install it and retry.")
    raise

# -------- Drawing setup --------

if args.transparent:
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
else:
    img = Image.new('RGB', (width, height))
draw = ImageDraw.Draw(img)

# -------- Caching --------

skip_avatars = args.skip_avatars
skip_emojis = args.skip_emojis

cache_to_disk = args.use_cache
cache_folder = "yt-chat-to-video_cache"

def GetCachedImageKey(path):
    no_extension, _ = os.path.splitext(path)
    no_protocol = no_extension.split('://', 1)[-1]
    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', no_protocol)
    return safe_key

cache = {}

if cache_to_disk:
    if not os.path.exists(cache_folder):
        os.mkdir(cache_folder)
    else:
        print("Loading cached images from disk...")
        for filename in os.listdir(cache_folder):
            try:
                img_cached = Image.open(os.path.join(cache_folder, filename)).convert("RGBA")
                cache_key = GetCachedImageKey(filename)
                cache[cache_key] = img_cached
            except Exception:
                pass
        print(f"{len(cache)} images loaded from cache")
else:
    print("\nHint: Add --use-cache to avoid re-downloading avatars/emojis next run\n")

# Pre-download avatars
if not skip_avatars:
    for _, avatar_url, _, _ in messages:
        if not avatar_url:
            continue
        cache_key = GetCachedImageKey(avatar_url)
        if cache_key not in cache:
            print(f"Downloading avatar: {avatar_url}")
            try:
                response = requests.get(avatar_url, timeout=15)
                avatar = Image.open(BytesIO(response.content)).convert("RGBA")
                avatar = avatar.resize((chat_avatar_size, chat_avatar_size), Image.LANCZOS)
                cache[cache_key] = avatar
                if cache_to_disk:
                    avatar.save(os.path.join(cache_folder, f"{cache_key}.png"))
            except Exception:
                print(f"Warning: Can't download avatar: {avatar_url}")

def CreateAvatarMask(size, scale):
    hires_size = size * scale
    dmask = Image.new("L", (hires_size, hires_size), 0)
    d = ImageDraw.Draw(dmask)
    d.ellipse((0, 0, hires_size, hires_size), fill=255)
    dmask = dmask.resize((size, size), Image.LANCZOS)
    return dmask

avatar_mask = CreateAvatarMask(chat_avatar_size, 4)

# Pre-download emojis
if not skip_emojis:
    for _, _, _, runs in messages:
        for run in runs:
            if run[0] == 1:
                emoji_url = run[1]
                cache_key = GetCachedImageKey(emoji_url)
                if cache_key not in cache:
                    print(f"Downloading emoji: {emoji_url}")
                    try:
                        response = requests.get(emoji_url, timeout=15)
                        emoji = Image.open(BytesIO(response.content)).convert("RGBA")
                        emoji = emoji.resize((chat_emoji_size, chat_emoji_size), Image.LANCZOS)
                        cache[cache_key] = emoji
                        if cache_to_disk:
                            emoji.save(os.path.join(cache_folder, f"{cache_key}.png"))
                    except Exception:
                        print(f"Warning: Can't download emoji: {emoji_url}")

# -------- Rendering --------

current_message_index = -1

def DrawChat():
    # bg
    if args.transparent:
        draw.rectangle([0, 0, width, height], fill=(0, 0, 0, 0))
    else:
        draw.rectangle([0, 0, width, height], fill=chat_background)

    y = 0
    layout = []

    # from current message back to first
    for i in range(current_message_index, -1, -1):
        message = messages[i]

        avatar_x = chat_inner_x
        author_x = avatar_x + chat_avatar_size + chat_avatar_padding
        runs_x = author_x + chat_author_font.getbbox(message[2])[2] + char_author_padding

        num_lines = 1
        runs_draw = []
        run_x, run_y = runs_x, 0

        for run_type, content in message[3]:
            if run_type == 0:  # text
                for word in content.split(" "):
                    word_width = chat_message_font.getbbox(word + " ")[2]
                    if run_x + word_width > chat_inner_width:
                        num_lines += 1
                        run_x = author_x
                        run_y += chat_line_height
                    runs_draw.append((0, run_x, run_y, word))
                    run_x += word_width
            else:  # emoji
                emoji = cache.get(GetCachedImageKey(content))
                if emoji:
                    emoji_w = emoji.size[0]
                    if run_x + emoji_w > chat_inner_width:
                        num_lines += 1
                        run_x = author_x
                        run_y += chat_line_height
                    runs_draw.append((1, run_x, run_y, emoji))
                    run_x += emoji_w

        if num_lines == 1:
            message_height = chat_avatar_size + ((4 + 4) * chat_scale)
            avatar_y = 4 * chat_scale
            author_y = 8 * chat_scale
            runs_y = 8 * chat_scale
        else:
            message_height = (num_lines * chat_line_height) + ((4 + 4) * chat_scale)
            avatar_y = 4 * chat_scale
            author_y = 4 * chat_scale
            runs_y = 4 * chat_scale

        y += message_height
        no_more_space = y > height

        if not args.no_clip and no_more_space:
            break

        layout.append((message_height, message, avatar_x, avatar_y, author_x, author_y, runs_y, runs_draw))

        if args.no_clip and no_more_space:
            break

    # draw from bottom up
    y = height
    for message_height, message, avatar_x, avatar_y, author_x, author_y, runs_y, runs_draw in layout:
        _, avatar_url, author, _ = message
        y -= message_height

        avatar = cache.get(GetCachedImageKey(avatar_url))
        if avatar:
            img.paste(avatar, (avatar_x, y + avatar_y), mask=avatar_mask)

        draw.text((author_x, y + author_y), author, font=chat_author_font, fill=chat_author_color)

        for run_type, run_x, run_y, content in runs_draw:
            if run_type == 0:
                draw.text((run_x, y + runs_y + run_y), content, font=chat_message_font, fill=chat_message_color)
            else:
                img.paste(content, (run_x, y + runs_y + run_y), mask=content)

# Frame loop
redraw = True
num_frames = int(round(fps * duration_seconds))
if num_frames < 1:
    raise SystemExit(f"Error: Computed frame count is {num_frames}. "
                     f"fps={fps}, duration={duration_seconds}s. Aborting to avoid empty video.")

for i in range(num_frames):
    t_ms = int((start_time_seconds + (i / fps)) * 1000)

    while current_message_index + 1 < len(messages) and t_ms > messages[current_message_index + 1][0]:
        current_message_index += 1
        redraw = True

    if redraw:
        try:
            DrawChat()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\nError while drawing chat: {e}\nExiting...")
            if e and "images do not match" in str(e):
                print("\nTip: delete the 'yt-chat-to-video_cache' folder after changing --scale.\n")
            break
        redraw = False

    ffmpeg.stdin.write(img.tobytes())
    print(f"\rGenerating video frames... {i+1}/{num_frames} ({round(((i+1) / num_frames) * 100)}%)", end="")

print("\nDone!")
ffmpeg.stdin.close()
ffmpeg.wait()
