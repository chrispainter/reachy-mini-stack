#!/usr/bin/env bash
# 05-clawbody.sh — Clone & install ClawBody (OpenClaw → Reachy Mini bridge)
# - Uses its own venv at ~/clawbody/.venv (per upstream README)
# - Installs with mediapipe_vision extras for face tracking
# - Creates .env from .env.example for user to configure
# Idempotent: re-runs `git pull` and re-installs in place.

set -euo pipefail

CB_DIR="$HOME/clawbody"
export PATH="$HOME/.local/bin:$PATH"

if [ -d "$CB_DIR/.git" ]; then
  echo "==> Updating ClawBody repo at $CB_DIR"
  git -C "$CB_DIR" pull --ff-only
else
  echo "==> Cloning ClawBody to $CB_DIR"
  git clone https://github.com/tomrikert/clawbody "$CB_DIR"
fi

cd "$CB_DIR"

if [ ! -d "$CB_DIR/.venv" ]; then
  echo "==> Creating ClawBody venv (seeded)"
  uv venv "$CB_DIR/.venv" --python 3.11 --seed
else
  echo "==> ClawBody venv already exists"
fi

echo "==> Installing ClawBody (editable) + mediapipe_vision"
uv pip install --python "$CB_DIR/.venv/bin/python" -e ".[mediapipe_vision]"

echo "==> Installing reachy-mini[mujoco] into ClawBody venv (so it can drive the sim)"
uv pip install --python "$CB_DIR/.venv/bin/python" "reachy-mini[mujoco]"

if [ -f "$CB_DIR/.env.example" ] && [ ! -f "$CB_DIR/.env" ]; then
  echo "==> Creating .env from .env.example (placeholder values — edit before running)"
  cp "$CB_DIR/.env.example" "$CB_DIR/.env"
  chmod 600 "$CB_DIR/.env"
fi

echo
echo "==> Verifying clawbody CLI"
"$CB_DIR/.venv/bin/clawbody" --help 2>&1 | head -20 || echo "  (clawbody CLI not on PATH yet)"

echo
echo "==> Done. Next steps:"
echo "    1. Edit $CB_DIR/.env with OPENAI_API_KEY (and optionally OpenClaw gateway settings)"
echo "    2. Terminal 1: source ~/reachy-venv/bin/activate && reachy-mini-daemon --sim --headless --no-media"
echo "    3. Terminal 2: source $CB_DIR/.venv/bin/activate && clawbody --gradio --no-openclaw"
echo "    4. Open http://reachy-pi.local:7860 in your browser"
