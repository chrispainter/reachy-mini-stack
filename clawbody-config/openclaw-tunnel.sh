#!/usr/bin/env bash
# openclaw-tunnel.sh — Persistent SSH tunnel from Pi to OpenClaw VPS.
#
# Forwards Pi:127.0.0.1:18789 -> VPS:127.0.0.1:18789 -> socat bridge -> docker exec ->
# OpenClaw container's gateway WebSocket on 127.0.0.1:18789.
#
# Run on the Pi. Idempotent — kills any prior tunnel before starting a new one.
# Backgrounds itself with `ssh -fN`. Use `pkill -f openclaw-tunnel` to stop.

set -euo pipefail

VPS_HOST=83.136.219.206
VPS_USER=root
KEY="$HOME/.ssh/openclaw-tunnel"
PORT=18789

# Kill any existing tunnel on this port
EXISTING=$(pgrep -af "ssh.*-L *${PORT}:127.0.0.1:${PORT}.*${VPS_USER}@${VPS_HOST}" | awk '{print $1}' || true)
if [ -n "${EXISTING:-}" ]; then
  echo "==> Killing existing tunnel(s): $EXISTING"
  echo "$EXISTING" | xargs kill 2>/dev/null || true
  sleep 1
fi

echo "==> Opening tunnel: localhost:${PORT} -> ${VPS_USER}@${VPS_HOST}:${PORT}"
ssh -fN \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -i "$KEY" \
    -L "${PORT}:127.0.0.1:${PORT}" \
    "${VPS_USER}@${VPS_HOST}"

sleep 1
if pgrep -af "ssh.*-L *${PORT}:127.0.0.1:${PORT}.*${VPS_USER}@${VPS_HOST}" >/dev/null; then
  echo "  -> tunnel active. Verify: nc -z 127.0.0.1 ${PORT} && echo OK"
else
  echo "ERROR: tunnel did not start"
  exit 1
fi
