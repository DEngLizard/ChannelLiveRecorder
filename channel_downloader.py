import subprocess
import os
import yaml
import sys
import argparse

CONFIG_PATH = './channellist.yaml'
YT_DLP = 'yt-dlp'

FORMATS = {
    "videos": "https://www.youtube.com/@{handle}/videos",
    "shorts": "https://www.youtube.com/@{handle}/shorts",
    "live":   "https://www.youtube.com/@{handle}/streams"
}

def load_channels():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        return config.get('channels', [])

def download_channel_section(handle, section_name, url, base_path, members_only=False, browser=None):
    out_dir = os.path.join(base_path, section_name)
    archive_file = os.path.join(base_path, f"archive_{section_name}.txt")
    os.makedirs(out_dir, exist_ok=True)

    print(f"📥 Downloading @{handle} {section_name} → {out_dir} (members_only={members_only})")

    cmd = [
        YT_DLP,
        url,
        '-o', os.path.join(out_dir, '%(upload_date)s - %(title).100B [%(id)s].%(ext)s'),
        '--download-archive', archive_file,
        '--merge-output-format', 'mp4',
        '--format', 'bestvideo+bestaudio/best',
    ]

    if members_only:
        if browser:
            cmd += ['--cookies-from-browser', browser]
        else:
            print(f"⚠️  Skipping members-only for @{handle} because no browser was provided.")
            return
    else:
        cmd += ['--match-filter', "is_live or availability != 'members_only'"]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error downloading {section_name} from @{handle}: {e}")

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
