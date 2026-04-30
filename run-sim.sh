#!/usr/bin/env bash
# run-sim.sh — Convenience: start the Reachy Mini simulator daemon (headless, no-media).
# Run this on the Pi. Daemon binds to 0.0.0.0:8000 (mDNS-announced as reachy_mini).
# Press Ctrl+C to stop.
set -euo pipefail
source "$HOME/reachy-venv/bin/activate"
exec reachy-mini-daemon --sim --headless --no-media "$@"
