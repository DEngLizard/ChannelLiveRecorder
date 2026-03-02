#!/usr/bin/env bash
set -euo pipefail

# ChannelLiveRecorder — setup.sh
# - Creates/uses .venv
# - Uses venv python directly (never system pip) to avoid PEP 668 issues
# - Installs deps needed for chat renderer (requests, Pillow)
# - Checks ffmpeg + deno presence (warns if missing)
# - Logs everything to ./logs/setup.log

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$REPO_ROOT/.venv"
LOG_DIR="$REPO_ROOT/logs"
LOG_FILE="$LOG_DIR/setup.log"

mkdir -p "$LOG_DIR"

# Log to file + console
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================"
echo "   ChannelLiveRecorder — Environment Setup"
echo "============================================"
echo "Repo: $REPO_ROOT"
echo "Log : $LOG_FILE"
echo

# Pick a python executable
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

PY="$(pick_python || true)"
if [[ -z "${PY:-}" ]]; then
  echo "❌ ERROR: Python not found (need python3)."
  exit 1
fi

echo "🔍 Using Python: $PY"
"$PY" --version
echo

echo "--------------------------------------------"
echo "📦 Creating or activating virtual environment"
echo "--------------------------------------------"

if [[ ! -d "$VENV_PATH" ]]; then
  echo "🆕 Creating venv at: $VENV_PATH"
  "$PY" -m venv "$VENV_PATH" || {
    echo
    echo "❌ ERROR: Failed to create venv."
    echo "   On Ubuntu/Debian, install venv support and try again:"
    echo "     sudo apt update"
    echo "     sudo apt install -y python3-venv"
    echo "   If you're on Python 3.13 specifically, you may need:"
    echo "     sudo apt install -y python3.13-venv python3.13-full"
    exit 1
  }
else
  echo "♻️ Using existing venv at: $VENV_PATH"
fi

VENV_PY="$VENV_PATH/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo
  echo "❌ ERROR: venv python not found at: $VENV_PY"
  echo "   Remove .venv and recreate after installing python3-venv:"
  echo "     rm -rf .venv"
  echo "     sudo apt install -y python3-venv"
  echo "     ./setup.sh"
  exit 1
fi

echo "✅ venv python: $VENV_PY"
"$VENV_PY" --version
echo

echo "--------------------------------------------"
echo "📦 Ensuring pip exists inside venv"
echo "--------------------------------------------"
# ensurepip may already be present; don't fail if it's not available
"$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || true

echo "pip inside venv:"
"$VENV_PY" -m pip --version || {
  echo
  echo "❌ ERROR: pip is not available inside the venv."
  echo "   Install venv/full packages and recreate the venv:"
  echo "     sudo apt install -y python3-venv python3-full"
  echo "     rm -rf .venv && ./setup.sh"
  exit 1
}
echo

echo "--------------------------------------------"
echo "📦 Upgrading pip + wheel + setuptools (inside venv)"
echo "--------------------------------------------"
"$VENV_PY" -m pip install --upgrade pip wheel setuptools
echo

echo "--------------------------------------------"
echo "📦 Installing ChannelLiveRecorder dependencies (inside venv)"
echo "--------------------------------------------"
"$VENV_PY" -m pip install -U \
  "yt-dlp[default]" \
  colorama \
  PyYAML \
  requests \
  Pillow
echo

echo "--------------------------------------------"
echo "🧰 Checking ffmpeg (required for chat render + stream merge)"
echo "--------------------------------------------"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "✅ ffmpeg: $(ffmpeg -version | head -n1)"
else
  echo "⚠️ ffmpeg not found."
  echo "   Install it with:"
  echo "     sudo apt update && sudo apt install -y ffmpeg"
fi
echo

echo "--------------------------------------------"
echo "🧩 Checking JS runtime for yt-dlp (Deno recommended)"
echo "--------------------------------------------"
if command -v deno >/dev/null 2>&1; then
  echo "✅ deno: $(deno --version | head -n1)"
else
  echo "⚠️ deno not found."
  echo "   Some YouTube flows require a JS runtime for challenge solving."
  echo "   Install Deno (recommended) and ensure ~/.deno/bin is on PATH."
fi
echo

echo "--------------------------------------------"
echo "✅ Setup complete"
echo "--------------------------------------------"
echo "Next:"
echo "  ./start.sh"
echo