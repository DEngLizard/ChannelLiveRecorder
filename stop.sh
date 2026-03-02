#!/usr/bin/env bash
set -euo pipefail

# ChannelLiveRecorder — stop.sh
# Stops the background helper started by start.sh.
# Sends SIGTERM to the daemon process group, waits, then SIGKILL if needed.

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RUN_DIR="$REPO_ROOT/run"
LOG_DIR="$REPO_ROOT/logs"
PID_FILE="$RUN_DIR/channelliverecorder.pid"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [ ! -f "$PID_FILE" ]; then
  echo "ℹ️ No PID file found at $PID_FILE (already stopped?)"
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -z "${pid:-}" ]; then
  echo "⚠️ PID file is empty. Removing it."
  rm -f "$PID_FILE"
  exit 0
fi

if ! kill -0 "$pid" 2>/dev/null; then
  echo "ℹ️ Process $pid not running. Removing PID file."
  rm -f "$PID_FILE"
  exit 0
fi

echo "🛑 Stopping ChannelLiveRecorder (PID $pid)..."

# Kill the whole process group (the daemon wrapper is session leader)
kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

# Wait up to ~10s
for i in {1..20}; do
  if kill -0 "$pid" 2>/dev/null; then
    sleep 0.5
  else
    break
  fi
done

if kill -0 "$pid" 2>/dev/null; then
  echo "⚠️ Still running; forcing kill..."
  kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
fi

rm -f "$PID_FILE"
echo "✅ Stopped."
