# 🎥 YouTube Live Stream + Chat Recorder (Auto-Updating)

This project monitors a list of YouTube channels and automatically records:

* 🎬 **Live video streams**
* 💬 **Live chat (JSON + rendered video)**

It uses [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) and includes:

* ✅ automatic **self-updating yt-dlp (no cron required)**
* ✅ robust **cookie fallback (no cookies → browser cookies)**
* ✅ **correct chat rendering timeline (fixed long-stream bug)**
* ✅ safe temp → final file pipeline
* ✅ crash-resistant auto-restart loop

---

## 📁 Project Structure

```text
ChannelLiveRecorder/
├── live_recording_helper.py        # Main controller (auto-restart + auto-update)
├── channel_downloader.py           # Optional archive downloader
├── channellist.yaml                # Channel config
├── recorder/
│   ├── live_stream_recorder.py     # VIDEO recorder
│   └── live_chat_recorder.py       # CHAT recorder
├── tools/
│   ├── move_to_location.py         # Moves finished files + triggers rendering
│   ├── chat_render.py              # Wrapper for chat rendering
│   └── yt-chat-to-video/
│       └── yt-chat-to-video.py     # Patched renderer (fixed timeline bug)
├── start.sh                        # Daemon launcher (auto-update yt-dlp)
├── stop.sh                         # Stops daemon
├── setup.sh                        # Installs everything cleanly
```

---

## 🧱 Processing Model

### 1. `live_recording_helper.py`

* Reads `channellist.yaml`
* Spawns per-channel:

  * 🎬 video recorder
  * 💬 chat recorder
* Writes into:

```text
./temp/<ChannelName>/
```

* Automatically:

  * restarts crashed recorders
  * updates yt-dlp every ~24h (no cron needed)

---

### 2. `tools/move_to_location.py`

* Runs continuously
* Scans `./temp/*` every 30 seconds
* Moves only **fully written files**:

```text
.temp → stable → moved to target
```

* Detects chat JSON → triggers rendering

---

### 3. Chat Rendering Pipeline

```text
.live_chat.json
   ↓
chat_render.py
   ↓
yt-chat-to-video.py
   ↓
.live_chat.mp4
```

✔ Fixed issue:

* Previously chat videos were ~1–2 minutes
* Now correctly render full stream duration (e.g. 1+ hour)

---

## ⚙️ Requirements

### System packages

```bash
sudo apt update
sudo apt install -y ffmpeg curl ca-certificates python3-venv
```

---

### Install yt-dlp (official binary)

```bash
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
  -o /usr/local/bin/yt-dlp

sudo chmod a+rx /usr/local/bin/yt-dlp
```

Verify:

```bash
which yt-dlp
yt-dlp --version
```

Expected:

```text
/usr/local/bin/yt-dlp
2026.x.x
```

---

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install -U pip wheel setuptools
python -m pip install colorama PyYAML requests pillow
```

⚠️ **Do NOT install yt-dlp in the venv anymore**

---

## 📝 Channel Configuration

```yaml
channels:
  - name: RockBottomPod
    target: ./recordings/RockBottomPod

  - name: SitDownZumock
    target: ./recordings/SitDownZumock
```

---

## 🚀 Running

### Start everything (recommended)

```bash
./start.sh
```

Runs:

* yt-dlp auto-update
* helper daemon
* auto-restart loop

---

### Foreground mode (debugging)

```bash
./start.sh --foreground
```

---

### Stop

```bash
./stop.sh
```

---

## 🔐 Cookies (Improved Fallback)

System now supports:

1. Try without cookies
2. If fails → fallback to:

   * `--cookies-from-browser firefox`
   * OR provided cookie file

Usage:

```bash
./start.sh --cookies-from-browser firefox
```

---

## 🔁 Auto Update (No Cron Needed)

### yt-dlp updates:

* ✅ on every `start.sh`
* ✅ every ~24h while running

```bash
/usr/local/bin/yt-dlp -U
```

---

### ❌ No longer needed:

* cron restart jobs
* pipx installs
* venv yt-dlp installs

---

## 🎬 Chat Rendering (Fixed)

### Before:

* ~1–2 minute videos ❌

### Now:

* Full timeline preserved ✅

### Root cause fixed:

* `videoOffsetTimeMsec` parsing bug
* incorrect replay handling

---

## 📂 Output Example

```text
recordings/
├── ChannelA/
│   ├── 2026-03-19_stream.mp4
│   ├── 2026-03-19.live_chat.json
│   ├── 2026-03-19.live_chat.mp4
```

---

## 🧠 Architecture Improvements

### Before

* multiple yt-dlp installs ❌
* cron restarts ❌
* broken chat timelines ❌

### Now

* single binary `/usr/local/bin/yt-dlp` ✅
* self-updating system ✅
* correct chat sync ✅
* deterministic execution path ✅

---

## 🛠️ Troubleshooting

### Check yt-dlp

```bash
which yt-dlp
yt-dlp --version
```

---

### Check render duration

```bash
ffprobe -v error -show_entries format=duration \
-of default=noprint_wrappers=1:nokey=1 file.mp4
```

---

### Debug chat render

```bash
python tools/chat_render.py <chat.json>
```

---

### Logs

```bash
tail -f logs/daemon.log
```

---

## ⚙️ Optional Improvements

* systemd service (recommended for production)
* log rotation
* archive cleanup automation

---

## 📌 Key Takeaways

* One yt-dlp → `/usr/local/bin/yt-dlp`
* No cron required
* Chat rendering fixed
* Fully self-healing system

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
