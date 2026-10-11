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
scp -4 -q "$HERE/deploy/reachy-voice.service" "$ROBOT:reachy-voice/reachy-voice.service"
ssh -4 "$ROBOT" "ENABLE=${1:-} bash -s" <<'REMOTE'
set -euo pipefail
cd ~/reachy-voice
APP_ENV=/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env
umask 077
# Keys never leave the robot: copy the four needed lines, keep any local VOICE_* overrides.
{ grep -E '^(GEMINI_API_KEY|OPENAI_API_KEY|HOME_AGENT_URL|HOME_AGENT_KEY)=' "$APP_ENV"
  [ -f voice.env ] && grep -vE '^(GEMINI_API_KEY|OPENAI_API_KEY|HOME_AGENT_URL|HOME_AGENT_KEY)=' voice.env || true
} > voice.env.new
grep -q '^VOICE_ENGINE=' voice.env.new || echo 'VOICE_ENGINE=alternate' >> voice.env.new
grep -q '^VOICE_LOG_DIR=' voice.env.new || echo 'VOICE_LOG_DIR=/home/pollen/reachy-voice/logs' >> voice.env.new
mv voice.env.new voice.env && chmod 600 voice.env
sudo install -m 644 reachy-voice.service /etc/systemd/system/reachy-voice.service
sudo systemctl daemon-reload
if [ "$ENABLE" = "--enable" ]; then sudo systemctl enable reachy-voice; fi
sudo systemctl restart reachy-voice
sleep 8
systemctl is-active reachy-voice
# Model load can take longer than the sleep; wait up to 30 s for the "ready" line.
for _ in $(seq 15); do
  f=$(ls -t logs/voice-*.jsonl 2>/dev/null | head -1 || true)
  [ -n "$f" ] && grep -q '"ready"' "$f" && break
  sleep 2
done
tail -n 3 "$(ls -t logs/voice-*.jsonl | head -1)"
REMOTE
