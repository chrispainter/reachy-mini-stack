#!/usr/bin/env bash
# Install the "household" profile into the robot's onboard conversation app and
# point it at Hermes on the Pi. Run from the Mac; idempotent.
#
# Everything lands in the app's instance directory (its site-packages folder), so
# an app update from the dashboard wipes it — just re-run this script afterwards.
set -euo pipefail

ROBOT="${ROBOT:-pollen@reachy-mini.local}"
PI="${PI:-behindtheproduct@reachy-pi.local}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP=/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app
ROBOT_HOST="${ROBOT#*@}"

PI_IP="$(ssh -4 "$PI" "hostname -I | awk '{print \$1}'")"
AGENT_KEY="$(ssh -4 "$PI" "grep '^API_SERVER_KEY=' ~/.config/household/agent.env | cut -d= -f2-")"

ssh -4 "$ROBOT" "mkdir -p $APP/user_personalities/household"
scp -4 -q "$HERE"/robot-profile/household/* "$ROBOT:$APP/user_personalities/household/"

# The key goes over stdin, not the command line, so it doesn't show up in `ps`.
printf '%s\n' "$AGENT_KEY" | ssh -4 "$ROBOT" "umask 077; cat > $APP/.home_agent_key"
ssh -4 "$ROBOT" "APP=$APP PI_IP=$PI_IP bash -s" <<'REMOTE'
set -euo pipefail
AGENT_KEY="$(cat "$APP/.home_agent_key")"; rm -f "$APP/.home_agent_key"
ENV="$APP/.env"
touch "$ENV"; chmod 600 "$ENV"
sed -i '/^HOME_AGENT_URL=/d;/^HOME_AGENT_KEY=/d' "$ENV"
printf 'HOME_AGENT_URL=http://%s:8642\nHOME_AGENT_KEY=%s\n' "$PI_IP" "$AGENT_KEY" >> "$ENV"

# Make "household" the startup profile, keeping whatever voice was chosen in the UI.
/venvs/apps_venv/bin/python - "$APP/startup_settings.json" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
d = json.loads(p.read_text()) if p.exists() else {}
d["profile"] = "user_personalities/household"
p.write_text(json.dumps(d, indent=2) + "\n")
PY

# Check the robot can actually reach Hermes before restarting anything.
curl -fsS -m 5 "http://$PI_IP:8642/health" >/dev/null && echo "robot -> Hermes: ok"
REMOTE

# (Re)start the app so it picks up the profile and .env.
curl -fsS -m 30 -X POST "http://$ROBOT_HOST:8000/api/apps/stop-current-app" >/dev/null || true
curl -fsS -m 30 -X POST "http://$ROBOT_HOST:8000/api/apps/start-app/reachy_mini_conversation_app"; echo
echo "Started. Talk to Reachy; logs: ssh $ROBOT journalctl -u reachy-mini-daemon -f"
