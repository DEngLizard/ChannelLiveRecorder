# 🎥 YouTube Live Stream + Chat Recorder

This project monitors a list of YouTube channels and automatically records **live streams and live chat** using [`yt-dlp`](https://github.com/yt-dlp/yt-dlp).  
Recordings are first written into per-channel temp directories and then a background mover process relocates **finished files** to their final targets, optionally rendering chat JSON into a video.

---

## 📁 Project Structure

```text
ChannelLiveRecorder/
├── live-recording-helper.py        # Main controller: manages per-channel video+chat recorders + temp dirs
├── channel_downloader.py           # Script to download all public/members-only videos from channels
├── channellist.yaml                # List of channels and their final output directories
├── recorder/
│   ├── live_stream_recorder.py     # Single-channel monitor & VIDEO recorder
│   └── live_chat_recorder.py       # Single-channel monitor & CHAT recorder (yt-dlp live_chat)
└── tools/
    ├── move_to_location.py         # Watches ./temp/* and moves finished files to per-channel targets + renders chat
    ├── chat_render.py              # Helper to call yt-chat-to-video on finished chat JSON files
    └── yt-chat-to-video/
        └── yt-chat-to-video.py     # Chat JSON → video renderer (from upstream project)
```

---

## 🧱 Processing Model

1. **live-recording-helper.py**
   - Reads `channellist.yaml`.
   - For each configured channel, starts:
     - `recorder/live_stream_recorder.py` (video)
     - `recorder/live_chat_recorder.py` (chat)
   - Both recorders write into:
     - `./temp/<ChannelName>/...`

2. **tools/move_to_location.py**
   - Runs as a separate long‑lived process.
   - Every 30 seconds it scans `./temp/<ChannelName>/` for each channel.
   - For each regular file:
     - On first sight: remembers its size.
     - On next scan: if the size is **unchanged**, it considers the file “finished” and moves it to the channel’s `target` directory from `channellist.yaml`.
     - Skips temp extensions such as `.part` and `.ytdl`.

3. **Chat JSON → Video (optional)**
   - If a moved file looks like a chat JSON (e.g. `.json`, `.live_chat.json`):
     - `move_to_location.py` calls `tools/chat_render.py` → `yt-chat-to-video.py`
     - This produces a rendered chat video file next to the JSON.

This design keeps:
- Recording isolated in `./temp`
- Final destinations clean and only populated with fully written, merged files
- Chat rendering decoupled from the live recorders

---

## ⚙️ Requirements

- Python 3.8+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (installed in your venv, recommended: `yt-dlp[default]`)
- `ffmpeg` (for both yt-dlp muxing and chat video rendering)
- Python libraries (installed into `.venv`):
  - `colorama`
  - `PyYAML`
  - `requests`
  - `Pillow` (PIL)
- A browser profile on the server **or** a cookies file:
  - Recommended: Firefox on the server and `--cookies-from-browser firefox`
  - Alternative: `cookies.txt` exported from your desktop browser

Example install (inside your `.venv`):

```bash
python -m pip install --upgrade pip wheel setuptools
python -m pip install "yt-dlp[default]" colorama PyYAML requests pillow
```

Make sure `ffmpeg` is installed on the system:

```bash
sudo apt install ffmpeg
```

---

## 📝 Channel Configuration (`channellist.yaml`)

Example:

```yaml
channels:
  - name: RockBottomPod
    target: ./recordings/RockBottomPod

  - name: SitDownZumock
    target: ./recordings/SitDownZumock
    members-only: true  # Optional: used by channel_downloader.py
```

- `name`: The YouTube handle **without** `@` (e.g. `@RockBottomPod` → `RockBottomPod`).
- `target`: Final destination folder for all completed files for that channel.
- `members-only`: Optional flag used by `channel_downloader.py` for archive downloads.

The helper and recorders will always write into:

```text
./temp/<ChannelName>/...
```

and `tools/move_to_location.py` will move finished files into the configured `target` paths.

---

## 🚀 Running the System

### 1. Activate the Virtual Environment

From the repo root:

```bash
source .venv/bin/activate   # Linux/macOS
# or
.\.venv\Scriptsctivate    # Windows (PowerShell/cmd)
```

### 2. Start the Live Recording Helper

Using Firefox profile on the server (recommended):

```bash
python live-recording-helper.py --cookies-from-browser firefox
```

Or using a static cookies file:

```bash
python live-recording-helper.py --cookies ~/ChannelLiveRecorder/cookies.txt
```

This will:

- Monitor all channels listed in `channellist.yaml`
- For each channel:
  - Start video + chat recorders, writing into `./temp/<ChannelName>/`
  - Restart recorders if they crash
  - Respect the chosen auth method (`--cookies` or `--cookies-from-browser`)

### 3. Start the Mover + Chat Renderer

In another shell (also in repo root):

```bash
source .venv/bin/activate   # optional but recommended
python tools/move_to_location.py
```

This process:

- Scans `./temp/*` every 30 seconds
- Tracks file size between scans
- Moves only **stable, fully written files** into their corresponding `target` directories
- Automatically kicks off chat rendering for finished chat JSON files

You can run both `live-recording-helper.py` and `tools/move_to_location.py` under `tmux`, `screen`, or as `systemd` services.

---

## 🎬 Chat Rendering Details

- `recorder/live_chat_recorder.py` uses `yt-dlp` with:
  - `--skip-download`
  - `--write-subs --sub-langs live_chat --sub-format json3`
- The output is a JSON chat log file in `./temp/<ChannelName>/...`.
- Once the JSON is stable and moved to the target directory, `tools/move_to_location.py` calls:

```bash
python tools/chat_render.py <path-to-chat-json>
```

- `tools/chat_render.py` then invokes:

```bash
python tools/yt-chat-to-video/yt-chat-to-video.py <chat.json> [options]
```

to generate a chat video (`.mp4` or `.webm`, depending on transparency settings).

You can later customize chat rendering (resolution, FPS, style) by editing default options in `chat_render.py` or calling it with additional CLI flags.

---

## 📥 Full Channel Archive Downloader

`channel_downloader.py` can be used to grab all videos (optionally including members‑only) for each channel defined in `channellist.yaml`.

Example:

```bash
python channel_downloader.py --cookies-from-browser firefox
```

Downloads are organized under each channel’s `target` directory, usually in subfolders like `video/`, `live/`, `short/` (depending on how you structure the downloader script).

---

## ✅ Features Recap

- ✅ Multi-channel live monitoring
- ✅ Separate VIDEO and CHAT recorders per channel
- ✅ Temp-based workflow (`./temp/<ChannelName>`) to keep targets clean
- ✅ Safe file finalization: only size-stable files are moved
- ✅ Automatic chat JSON → video rendering
- ✅ Uses browser cookies (`--cookies-from-browser`) or static `cookies.txt`
- ✅ Auto-restarts recorders on failure
- ✅ Cross-platform (Linux/Windows, with Python + ffmpeg)

---

## 🛠️ Operational Tips

- Use `tmux`/`screen` or `systemd` to keep processes running after logout.
- Point your `target` paths to large storage volumes if you’re archiving a lot of streams.
- Regularly prune old recordings and chat videos if disk space is limited.
- If YouTube changes its internals, updating `yt-dlp` is usually the first fix:
  ```bash
  python -m pip install -U "yt-dlp[default]"
  ```

---

## 📂 Example Output Layout

```text
recordings/
├── RockBottomPod/
│   ├── 2025-05-01_20-00-00_Stream_Title.mp4
│   ├── 2025-05-01_20-00-00_Stream_Title.live_chat.json
│   ├── 2025-05-01_20-00-00_Stream_Title.live_chat.mp4
│   └── RockBottomPod.log
└── SitDownZumock/
    ├── 2025-05-02_21-00-00_Another_Stream.webm
    ├── 2025-05-02_21-00-00_Another_Stream.live_chat.json
    ├── 2025-05-02_21-00-00_Another_Stream.live_chat.mp4
    └── SitDownZumock.log
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
