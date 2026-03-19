#!/usr/bin/env bash
set -euo pipefail

# ChannelLiveRecorder — setup.sh
# - Installs system prerequisites when possible
# - Installs official yt-dlp release binary to /usr/local/bin/yt-dlp
# - Creates/uses .venv and installs Python dependencies inside it
# - Logs everything to ./logs/setup.log

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$REPO_ROOT/.venv"
LOG_DIR="$REPO_ROOT/logs"
LOG_FILE="$LOG_DIR/setup.log"
YTDLP_BIN="/usr/local/bin/yt-dlp"
YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================"
echo "   ChannelLiveRecorder — Environment Setup"
echo "============================================"
echo "Repo: $REPO_ROOT"
echo "Log : $LOG_FILE"
echo

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  return 1
}

have_sudo() {
  command -v sudo >/dev/null 2>&1
}

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif have_sudo; then
    sudo "$@"
  else
    return 1
  fi
}

PY="$(pick_python || true)"
if [[ -z "${PY:-}" ]]; then
  echo "❌ ERROR: Python not found (need python3)."
  exit 1
fi

echo "🔍 Using Python: $PY"
"$PY" --version
echo

if command -v apt-get >/dev/null 2>&1; then
  echo "--------------------------------------------"
  echo "📦 Installing system packages via apt (best effort)"
  echo "--------------------------------------------"
  if run_root apt-get update && run_root apt-get install -y curl ffmpeg ca-certificates python3-venv; then
    echo "✅ System packages installed or already present"
  else
    echo "⚠️ Could not auto-install system packages. Install these manually if missing:"
    echo "   curl ffmpeg ca-certificates python3-venv"
  fi
  echo
else
  echo "⚠️ apt-get not available. Ensure these are installed manually:"
  echo "   curl ffmpeg ca-certificates python3-venv"
  echo
fi

echo "--------------------------------------------"
echo "📦 Installing official yt-dlp binary"
echo "--------------------------------------------"
if command -v curl >/dev/null 2>&1; then
  if run_root curl -L "$YTDLP_URL" -o "$YTDLP_BIN" && run_root chmod a+rx "$YTDLP_BIN"; then
    echo "✅ yt-dlp installed at $YTDLP_BIN"
    "$YTDLP_BIN" --version || true
  else
    echo "❌ Failed to install yt-dlp to $YTDLP_BIN"
    echo "   Re-run as root or with passwordless sudo, or install yt-dlp manually there."
    exit 1
  fi
else
  echo "❌ curl not found; cannot install yt-dlp automatically"
  exit 1
fi
echo

echo "--------------------------------------------"
echo "📦 Creating or activating virtual environment"
echo "--------------------------------------------"
if [[ ! -d "$VENV_PATH" ]]; then
  echo "🆕 Creating venv at: $VENV_PATH"
  "$PY" -m venv "$VENV_PATH" || {
    echo
    echo "❌ ERROR: Failed to create venv."
    echo "   Install python3-venv and try again."
    exit 1
  }
else
  echo "♻️ Using existing venv at: $VENV_PATH"
fi

VENV_PY="$VENV_PATH/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "❌ ERROR: venv python not found at: $VENV_PY"
  exit 1
fi

echo "✅ venv python: $VENV_PY"
"$VENV_PY" --version
echo

echo "--------------------------------------------"
echo "📦 Ensuring pip exists inside venv"
echo "--------------------------------------------"
"$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV_PY" -m pip --version

echo "--------------------------------------------"
echo "📦 Upgrading pip + wheel + setuptools (inside venv)"
echo "--------------------------------------------"
"$VENV_PY" -m pip install --upgrade pip wheel setuptools

echo "--------------------------------------------"
echo "📦 Installing ChannelLiveRecorder Python dependencies"
echo "--------------------------------------------"
"$VENV_PY" -m pip install -U colorama PyYAML requests Pillow

echo "--------------------------------------------"
echo "🧰 Checking installed tools"
echo "--------------------------------------------"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "✅ ffmpeg: $(ffmpeg -version | head -n1)"
else
  echo "⚠️ ffmpeg not found"
fi
if command -v "$YTDLP_BIN" >/dev/null 2>&1; then
  echo "✅ yt-dlp: $($YTDLP_BIN --version)"
fi
if command -v deno >/dev/null 2>&1; then
  echo "✅ deno: $(deno --version | head -n1)"
else
  echo "⚠️ deno not found. Some YouTube challenge flows may work better with Deno installed."
fi

echo "--------------------------------------------"
echo "✅ Setup complete"
echo "--------------------------------------------"
echo "Next:"
echo "  ./start.sh"
echo
