# 🎥 YouTube Live Stream Recorder

This project monitors a list of YouTube channels and automatically records live streams using [`yt-dlp`](https://github.com/yt-dlp/yt-dlp). Each channel has its own target directory for recorded videos.

---

## 📁 Project Structure

```
live-recorder/
├── live-recording-helper.py        # Main controller: manages per-channel processes
├── channel_downloader.py           # Script to download all public/members-only videos from channels
├── channellist.yaml                # List of channels and their output directories
├── recorder/
│   └── live_stream_recorder.py     # Single-channel monitor & recorder logic
```

---

## ⚙️ Requirements

- Python 3.7+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) installed and in your `PATH`
- Chrome or another browser for `--cookies-from-browser` support
- PyYAML

Install dependencies with:

```bash
pip install yt-dlp colorama pyyaml
```

---

## 📝 Setup

### 1. Configure Channels

Edit `channellist.yaml` to define the YouTube channels and their recording directories:

```yaml
channels:
  - name: RockBottomPod
    target: ./recordings/RockBottomPod

  - name: SitDownZumock
    target: ./recordings/SitDownZumock
    members-only: true  # Optional: allows downloading of members-only content
```

### 2. Run the Live Recording Helper

Launch the main controller:

```bash
python live-recording-helper.py --cookies-from-browser chrome
```

This will:
- Monitor all listed channels in parallel
- Automatically create each `target` directory if it doesn't exist
- Detect upcoming streams and switch to fast polling before they start
- Start `yt-dlp --live-from-start` recording as soon as a stream goes live
- Supports optional use of browser cookies for members-only access

### 3. Download Full Channel Videos

To download all available videos (including optional members-only videos) from each configured channel:

```bash
python channel_downloader.py --cookies-from-browser chrome
```

This will download content into:
```
<target>/{live,short,video}/
```

Members-only videos will only be downloaded if the flag `members-only: true` is set in `channellist.yaml`.

---

## ✅ Features

- ✅ Multi-channel support
- ✅ Auto-creation of target directories
- ✅ Smart polling for upcoming/live streams
- ✅ Per-channel process isolation
- ✅ Cross-platform (Windows/Linux)
- ✅ Resilient to crashes — auto-restarts processes if needed
- ✅ Optional members-only video support via browser cookies
- ✅ Full archive download via `channel_downloader.py`

---

## 🛠️ Tips

- Use `screen` or `tmux` to run in the background
- For long-running setups, consider a `systemd` service (ask if you want a unit file)
- To view logs, open `<target>/<channel>.log`

---

## 📂 Output

Recordings and downloads are saved under each channel's specified target directory:

```
recordings/
├── RockBottomPod/
│   ├── My Epic Livestream.mp4
│   └── RockBottomPod.log
├── SitDownZumock/
│   ├── Another Stream.webm
│   ├── video/
│   ├── live/
│   ├── short/
```

---

## 🤝 License

MIT License

Copyright (c) 2025 DEng.Lizard

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
