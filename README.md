
# 🎥 YouTube Live Stream Recorder

This project monitors a list of YouTube channels and automatically records live streams using [`yt-dlp`](https://github.com/yt-dlp/yt-dlp). Each channel has its own target directory for recorded videos.

---

## 📁 Project Structure

```
live-recorder/
├── live-recording-helper.py        # Main controller: manages per-channel processes
├── channellist.yaml                # List of channels and their output directories
├── recorder/
│   └── live_stream_recorder.py     # Single-channel monitor & recorder logic
```

---

## ⚙️ Requirements

- Python 3.7+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) installed and in your `PATH`
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
```

### 2. Run the Helper

Launch the main controller:

```bash
python live-recording-helper.py
```

This will:
- Monitor all listed channels in parallel
- Automatically create each `target` directory if it doesn't exist
- Detect upcoming streams and switch to fast polling before they start
- Start `yt-dlp --live-from-start` recording as soon as a stream goes live
- Stop recorders when a channel is removed from the list

---

## ✅ Features

- ✅ Multi-channel support
- ✅ Auto-creation of target directories
- ✅ Smart polling for upcoming/live streams
- ✅ Per-channel process isolation
- ✅ Cross-platform (Windows/Linux)
- ✅ Resilient to crashes — auto-restarts processes if needed

---

## 🛠️ Tips

- Use `screen` or `tmux` to run in the background
- For long-running setups, consider a `systemd` service (ask if you want a unit file)
- To view logs, redirect output per process or enhance the logger

---

## 📂 Output

Recordings are saved under each channel's specified target directory using the stream's title:

```
recordings/
├── RockBottomPod/
│   └── My Epic Livestream.mp4
├── SitDownZumock/
│   └── Another Stream.webm
```

---

## 🤝 License

MIT (or your preferred license)
