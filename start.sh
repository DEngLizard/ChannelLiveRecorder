#!/usr/bin/env bash
set -euo pipefail

# ChannelLiveRecorder — start.sh
# Starts the helper in the background (daemon-style) by default.
# - Writes PID to ./run/channelliverecorder.pid
# - Writes combined stdout/stderr to ./logs/daemon.log
# - Updates yt-dlp before starting and helper keeps checking daily
#
# Foreground mode:
#   ./start.sh --foreground [helper args...]
#
# Cookies:
#   ./start.sh --cookies-from-browser firefox
#   ./start.sh --no-cookie-fallback
#
# Stop:
#   ./stop.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_ROOT/.venv"
LOG_DIR="$REPO_ROOT/logs"
RUN_DIR="$REPO_ROOT/run"
PID_FILE="$RUN_DIR/channelliverecorder.pid"
DAEMON_LOG="$LOG_DIR/daemon.log"
YTDLP_BIN="/usr/local/bin/yt-dlp"
YTDLP_UPDATE_INTERVAL_HOURS="${YTDLP_UPDATE_INTERVAL_HOURS:-24}"

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ venv not found. Run: ./setup.sh"
  exit 1
fi

if [ ! -x "$YTDLP_BIN" ]; then
  echo "❌ yt-dlp not found at $YTDLP_BIN"
  echo "   Run: ./setup.sh"
  exit 1
fi

VENV_PY="$VENV/bin/python"
FOREGROUND=0
COOKIE_ARGS=()
PASSTHRU_ARGS=()

while (($#)); do
  case "$1" in
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --cookies-from-browser)
      if [ $# -lt 2 ]; then
        echo "❌ --cookies-from-browser requires a browser name"
        exit 1
      fi
      COOKIE_ARGS+=("--cookies-from-browser" "$2")
      shift 2
      ;;
    --cookies)
      if [ $# -lt 2 ]; then
        echo "❌ --cookies requires a file path"
        exit 1
      fi
      COOKIE_ARGS+=("--cookies" "$2")
      shift 2
      ;;
    --no-cookie-fallback)
      PASSTHRU_ARGS+=("--no-cookie-fallback")
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      PASSTHRU_ARGS+=("$1")
      shift
      ;;
  esac
done

if [ ${#COOKIE_ARGS[@]} -eq 0 ] && [ -t 0 ]; then
  echo
  echo "Cookie mode:"
  echo "  1) none (try without cookies)"
  echo "  2) firefox"
  echo "  3) chrome"
  echo "  4) edge"
  echo "  5) chromium"
  read -r -p "Choose [1-5] (default 1): " choice
  choice="${choice:-1}"
  case "$choice" in
    2) COOKIE_ARGS=("--cookies-from-browser" "firefox") ;;
    3) COOKIE_ARGS=("--cookies-from-browser" "chrome") ;;
    4) COOKIE_ARGS=("--cookies-from-browser" "edge") ;;
    5) COOKIE_ARGS=("--cookies-from-browser" "chromium") ;;
    *) COOKIE_ARGS=() ;;
  esac
fi

echo "✅ Using Python: $("$VENV_PY" --version)"

echo "📦 Updating Python deps in venv..."
"$VENV_PY" -m pip install -U pip wheel setuptools
"$VENV_PY" -m pip install -U requests Pillow PyYAML colorama

echo "📦 Updating yt-dlp release binary..."
set +e
"$YTDLP_BIN" -U
YTDLP_UPDATE_RC=$?
set -e
if [ "$YTDLP_UPDATE_RC" -ne 0 ]; then
  echo "⚠️ yt-dlp self-update returned $YTDLP_UPDATE_RC; continuing with existing binary"
fi

echo "✅ yt-dlp path: $YTDLP_BIN"
echo "✅ yt-dlp version: $("$YTDLP_BIN" --version)"

HELPER_CMD=(
  "$VENV_PY"
  "$REPO_ROOT/live_recording_helper.py"
  "--yt-dlp-bin" "$YTDLP_BIN"
  "--yt-dlp-update-interval-hours" "$YTDLP_UPDATE_INTERVAL_HOURS"
  "${COOKIE_ARGS[@]}"
  "${PASSTHRU_ARGS[@]}"
)

if [ -f "$PID_FILE" ]; then
  oldpid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${oldpid:-}" ] && kill -0 "$oldpid" 2>/dev/null; then
    echo "⚠️ Already running (PID $oldpid). Stop it first: ./stop.sh"
    exit 0
  fi
fi

if [ "$FOREGROUND" -eq 1 ]; then
  echo "🚀 Starting in FOREGROUND. Logs: $LOG_DIR"
  echo "▶️ Helper: ${HELPER_CMD[*]}"
  while true; do
    set +e
    "${HELPER_CMD[@]}"
    code=$?
    set -e
    echo "⚠️ Helper exited with code $code. Restarting in 5s..."
    sleep 5
  done
else
  echo "🚀 Starting in BACKGROUND. Logs: $DAEMON_LOG"
  HELPER_CMD_ESCAPED="$(printf "%q " "${HELPER_CMD[@]}")"

  setsid bash -c "
    set -euo pipefail
    echo \"===== \$(date '+%Y-%m-%d %H:%M:%S') start =====\"
    while true; do
      set +e
      $HELPER_CMD_ESCAPED
      code=\$?
      set -e
      echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] helper exited with code \$code; restarting in 5s...\"
      sleep 5
    done
  " >> "$DAEMON_LOG" 2>&1 &

  pid=$!
  echo "$pid" > "$PID_FILE"
  echo "✅ Started. PID $pid"
  echo "Stop with: ./stop.sh"
fi
