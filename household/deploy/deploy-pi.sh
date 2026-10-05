#!/usr/bin/env bash
# Deploy the Hermes household agent to the Pi. Run from the Mac; idempotent.
#
# Secrets never leave the Pi. They live in ~/.config/household/agent.env (host-owned,
# mode 600) and reach the container through compose's env_file:
#   OPENAI_API_KEY  copied once from ~/clawbody/.env
#   API_SERVER_KEY  generated once; the robot uses it to call Hermes
# The data volume (~/hermes-home) is owned by the container's user, so config files
# go in with `docker cp` rather than a host-side copy.
set -euo pipefail

PI="${PI:-behindtheproduct@reachy-pi.local}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

ssh -4 "$PI" 'mkdir -p ~/reachy-mini-stack/household/hermes ~/hermes-home ~/.config/household'
scp -4 -q "$HERE"/hermes/{docker-compose.yml,config.yaml,SOUL.md} "$PI":~/reachy-mini-stack/household/hermes/

ssh -4 "$PI" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/reachy-mini-stack/household/hermes

SECRETS=~/.config/household/agent.env
touch "$SECRETS"; chmod 600 "$SECRETS"
grep -q '^OPENAI_API_KEY=' "$SECRETS" || grep '^OPENAI_API_KEY=' ~/clawbody/.env >> "$SECRETS"
grep -q '^API_SERVER_KEY=' "$SECRETS" || echo "API_SERVER_KEY=$(openssl rand -hex 32)" >> "$SECRETS"

export HERMES_HOME_DIR=~/hermes-home HERMES_SECRETS="$SECRETS"
docker compose up -d
for f in config.yaml SOUL.md; do
  docker cp "$f" hermes:/opt/data/"$f"
  docker exec hermes chown hermes:hermes /opt/data/"$f"
done
# Keys come from env_file; drop any copies in the volume's .env so there's one source.
docker exec hermes sh -c 'touch /opt/data/.env && sed -i "/^OPENAI_API_KEY=/d;/^API_SERVER_KEY=/d" /opt/data/.env'
docker compose restart
REMOTE

echo "Waiting for Hermes health..."
for _ in $(seq 1 60); do
  if curl -fsS -m 3 "http://${PI#*@}:8642/health" >/dev/null 2>&1; then
    echo "Hermes is up at http://${PI#*@}:8642"; exit 0
  fi
  sleep 3
done
echo "Hermes did not become healthy; check: ssh $PI docker logs hermes" >&2
exit 1
