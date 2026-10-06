#!/usr/bin/env bash
# On the robot: free the mic from Pollen's app, run one spike, always restore the app.
#   ~/voice-spike/run.sh spike.gemini_spike --voice Kore
set -euo pipefail
if [ $# -lt 1 ]; then
  echo "usage: run.sh <module> [args...]" >&2
  exit 2
fi
cd ~/voice-spike
API=http://127.0.0.1:8000
APP_ENV=/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env

restore() {
  sleep 2   # let the media device settle before the app grabs it again
  curl -s -m 30 -X POST "$API/api/apps/start-app/reachy_mini_conversation_app" >/dev/null || true
  echo "restored reachy_mini_conversation_app"
}
trap restore EXIT

curl -s -m 30 -X POST "$API/api/apps/stop-current-app" >/dev/null || true
stopped=0
for _ in $(seq 1 20); do
  if ! curl -sf -m 5 "$API/api/apps/current-app-status" | grep -qE '"state" *: *"running"'; then
    stopped=1
    break
  fi
  sleep 1
done
if [ "$stopped" -ne 1 ]; then
  echo "error: conversation app still running after 20 s" >&2
  exit 1
fi

set -a; . "$APP_ENV"; set +a      # GEMINI_API_KEY / OPENAI_API_KEY, never printed
module="$1"; shift
.venv/bin/python -m "$module" "$@"
