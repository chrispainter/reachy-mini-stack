#!/usr/bin/env bash
# 02-reachy-sdk.sh — Install Reachy Mini SDK with MuJoCo simulator extras
# Run inside ~/reachy-venv (script activates automatically).
# Idempotent: safe to re-run; uv pip will skip already-satisfied deps.

set -euo pipefail

VENV="$HOME/reachy-venv"
if [ ! -d "$VENV" ]; then
  echo "ERROR: $VENV does not exist. Run 01-python.sh first."
  exit 1
fi

# Make sure uv is in PATH
export PATH="$HOME/.local/bin:$PATH"

echo "==> Installing reachy-mini[mujoco] into $VENV"
uv pip install --python "$VENV/bin/python" "reachy-mini[mujoco]"

echo
echo "==> Versions"
"$VENV/bin/python" - <<'EOF'
import importlib.metadata as m
for pkg in ("reachy-mini", "mujoco", "numpy", "scipy"):
    try:
        print(f"  {pkg}: {m.version(pkg)}")
    except m.PackageNotFoundError:
        print(f"  {pkg}: NOT INSTALLED")
EOF

echo
echo "==> CLI entrypoints in venv"
ls -1 "$VENV/bin/" | grep -E "^reachy|^mujoco|^mjpython" || echo "  (none found yet)"

echo
echo "==> Done. To use:"
echo "    source ~/reachy-venv/bin/activate    (or: rmenv)"
echo "    reachy-mini-daemon --sim             (start simulator)"
