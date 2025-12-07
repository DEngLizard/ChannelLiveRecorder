import subprocess
import os
import yaml
import sys
import argparse
import json
import re

CONFIG_PATH = './downloadlist.yaml'
YT_DLP = 'yt-dlp'

FORMATS = {
    "videos": "https://www.youtube.com/@{handle}/videos",
    "shorts": "https://www.youtube.com/@{handle}/shorts",
    "live":   "https://www.youtube.com/@{handle}/streams"
}

VIDEO_ID_REGEX = re.compile(r'\[([a-zA-Z0-9_-]{11})\]')

def load_channels():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        return config.get('channels', [])

def extract_downloaded_ids(directory):
    video_ids = set()
    for fname in os.listdir(directory):
        match = VIDEO_ID_REGEX.search(fname)
        if match:
            video_ids.add(match.group(1))
    return video_ids

def download_channel_section(handle, section_name, url, base_path, members_only=False, browser=None):
    out_dir = os.path.join(base_path, section_name)
    os.makedirs(out_dir, exist_ok=True)

    downloaded_ids = extract_downloaded_ids(out_dir)

    print(f"📥 Probing @{handle} {section_name} → {out_dir} (members_only={members_only})")

    probe_cmd = [
        YT_DLP,
        '--flat-playlist',
        '--dump-json',
        url
    ]

    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to probe {url}: {e}")
        return

    for line in result.stdout.strip().splitlines():
        try:
            data = json.loads(line)
            video_id = data.get('id')
            title = data.get('title', video_id)
            availability = str(data.get('availability') or '').lower()

            if not video_id:
                continue

            if video_id in downloaded_ids:
                print(f"✅ Skipped already downloaded: {title}")
                continue

            if not members_only and 'subscriber_only' in availability:
                print(f"⏩ Skipped members-only: {title}")
                continue

            cmd = [
                YT_DLP,
                f"https://www.youtube.com/watch?v={video_id}",
                '-o', os.path.join(out_dir, '%(upload_date)s - %(title).100B [%(id)s].%(ext)s'),
                '--merge-output-format', 'mp4',
                '--format', 'bestvideo+bestaudio/best',
                '--no-warnings',
                '--ignore-errors'
            ]

            if members_only and browser:
                cmd += ['--cookies-from-browser', browser]

            subprocess.run(cmd, check=True)

        except Exception as e:
            print(f"⚠️ Error processing video: {e}")

def main():
    parser = argparse.ArgumentParser(description="Download all content from listed YouTube channels.")
    parser.add_argument('--cookies-from-browser', metavar='BROWSER', help="Use browser cookies (e.g., chrome, firefox) for members-only videos")
    args = parser.parse_args()

    browser = args.cookies_from_browser
    channels = load_channels()

    for ch in channels:
        handle = ch['name']
        target = os.path.abspath(ch['target'])
        members_only = ch.get('members-only', False)

        for section, url_tpl in FORMATS.items():
            url = url_tpl.format(handle=handle)
            download_channel_section(handle, section, url, target, members_only, browser)

if __name__ == '__main__':
    main()
