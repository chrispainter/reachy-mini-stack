#!/usr/bin/env bash
# Deploy reachy_voice to the robot and build its venv. Run from the Mac; idempotent.
# The venv layers on /venvs/apps_venv (reachy_mini, numpy, scipy, httpx, websockets,
# onnxruntime, GStreamer) without installing anything into it.
set -euo pipefail
ROBOT="${ROBOT:-pollen@reachy-mini.local}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # voice/

ssh -4 "$ROBOT" 'mkdir -p ~/reachy-voice/reachy_voice ~/reachy-voice/tools ~/reachy-voice/logs'
rsync -a --delete --exclude '__pycache__' -e "ssh -4" "$HERE/reachy_voice/" "$ROBOT:reachy-voice/reachy_voice/"
rsync -a --delete --exclude '__pycache__' -e "ssh -4" "$HERE/tools/" "$ROBOT:reachy-voice/tools/"
ssh -4 "$ROBOT" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/reachy-voice
PY=$(ls -d /home/pollen/.local/share/uv/python/cpython-3.12.*-linux-aarch64-gnu/bin/python3 | tail -1)
[ -x .venv/bin/python ] || /opt/uv/uv venv --python "$PY" .venv
echo "import site; site.addsitedir('/venvs/apps_venv/lib/python3.12/site-packages')" \
  > .venv/lib/python3.12/site-packages/zz_apps_venv.pth
/opt/uv/uv pip install --quiet --python .venv/bin/python -r reachy_voice/requirements.txt
# openwakeword 0.6.0 pins tflite-runtime on Linux, which has no cp312 aarch64 wheel; we use ONNX.
/opt/uv/uv pip install --quiet --python .venv/bin/python --no-deps openwakeword==0.6.0
.venv/bin/python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])"
.venv/bin/python -c "import google.genai, soxr, openwakeword, reachy_mini; print('voice venv ok')"
df -h / | tail -1
REMOTE
