#!/usr/bin/env bash
# Copy the spike to the robot and build its venv. Run from the Mac; idempotent.
# The venv layers on top of /venvs/apps_venv (for reachy_mini, numpy, scipy, GStreamer)
# without installing anything into it.
set -euo pipefail
ROBOT="${ROBOT:-pollen@reachy-mini.local}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # voice/

ssh -4 "$ROBOT" 'mkdir -p ~/voice-spike/logs'
rsync -a --delete --exclude '.venv' --exclude 'logs' --exclude '__pycache__' \
  -e "ssh -4" "$HERE/spike/" "$ROBOT:voice-spike/spike/"
ssh -4 "$ROBOT" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/voice-spike
mkdir -p logs
PY=/home/pollen/.local/share/uv/python/cpython-3.12.12-linux-aarch64-gnu/bin/python3
[ -x .venv/bin/python ] || /opt/uv/uv venv --python "$PY" .venv
# addsitedir also processes apps_venv's own .pth files (GStreamer bundle setup).
echo "import site; site.addsitedir('/venvs/apps_venv/lib/python3.12/site-packages')" \
  > .venv/lib/python3.12/site-packages/zz_apps_venv.pth
/opt/uv/uv pip install --quiet --python .venv/bin/python -r spike/requirements.txt
cp spike/run.sh ./run.sh && chmod +x run.sh
.venv/bin/python -c "import google.genai, reachy_mini, scipy; print('spike venv ok')"
df -h / | tail -1
REMOTE
