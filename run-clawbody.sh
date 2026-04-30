#!/usr/bin/env bash
# run-clawbody.sh — Convenience: start ClawBody with Gradio web UI bound to the Pi's LAN IP.
# Requires the simulator (run-sim.sh) running in another shell first.
# Pass --no-openclaw to run without the OpenClaw bridge; otherwise edit ~/clawbody/.env first.
# Open http://reachy-pi.local:7860 in your browser.
set -euo pipefail
source "$HOME/clawbody/.venv/bin/activate"
cd "$HOME/clawbody"
# Gradio defaults to 127.0.0.1 — bind to all interfaces so the LAN can reach it
export GRADIO_SERVER_NAME=0.0.0.0
exec clawbody --gradio "$@"
