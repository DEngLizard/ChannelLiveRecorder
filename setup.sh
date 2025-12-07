#!/usr/bin/env bash
set -e

echo "============================================"
echo "   ChannelLiveRecorder — Environment Setup"
echo "============================================"
echo

# Detect repo root
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Python venv path
VENV_PATH="$REPO_ROOT/.venv"

echo "🔍 Checking for Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 not installed! Install Python 3.10+"
    exit 1
fi

echo "🔍 Checking pip..."
python3 -m pip -q --version || {
    echo "❌ pip missing! Run: sudo apt install python3-pip"
    exit 1
}

echo "--------------------------------------------"
echo "📦 Creating or activating virtual environment"
echo "--------------------------------------------"

if [ ! -d "$VENV_PATH" ]; then
    echo "🆕 Creating new venv at $VENV_PATH ..."
    python3 -m venv "$VENV_PATH"
else
    echo "♻️ Using existing venv at $VENV_PATH ..."
fi

# Activate venv
echo "⚡ Activating venv..."
# shellcheck disable=SC1090
source "$VENV_PATH/bin/activate"

echo "Python version inside venv:"
python3 --version
echo

echo "--------------------------------------------"
echo "📦 Upgrading pip + wheel"
echo "--------------------------------------------"
python3 -m pip install --upgrade pip wheel setuptools

echo "--------------------------------------------"
echo "📦 Installing ChannelLiveRecorder dependencies"
echo "--------------------------------------------"

# Required for your scripts
python3 -m pip install \
    yt-dlp[default] \
    colorama \
    PyYAML

echo "--------------------------------------------"
echo "📦 Checking Deno / JS runtime (yt-dlp requirement)"
echo "--------------------------------------------"
if ! command -v deno >/dev/null 2>&1; then
    echo "⚠️ Deno not found!"
    echo "   YouTube now requires a JS runtime for signature decryption."
    echo "   Install Deno with:"
    echo "   curl -fsSL https://deno.land/install.sh | sh"
    echo "   Then add ~/.deno/bin to your PATH."
else
    echo "✅ Deno detected: $(deno --version | head -n1)"
fi

echo
echo "============================================"
echo "🎉 Setup complete!"
echo "============================================"
echo
echo "To activate your venv in future shells:"
echo "    source .venv/bin/activate"
echo
echo "To run the recording system:"
echo "    python live-recording-helper.py"
echo
echo "With cookies:"
echo "    python live-recording-helper.py --cookies ~/ChannelLiveRecorder/cookies.txt"
echo
echo "To test a single channel recorder directly:"
echo "    python recorder/live_stream_recorder.py SomeChannel /tmp/output_dir --cookies ~/ChannelLiveRecorder/cookies.txt"
echo
echo "============================================"
