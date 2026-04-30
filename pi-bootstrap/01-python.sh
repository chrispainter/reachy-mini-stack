#!/usr/bin/env bash
# 01-python.sh — Python tooling for Reachy Mini stack
# - Installs pipx (for CLI Python tools)
# - Installs uv (fast Python package manager — what Pollen recommends)
# - Creates ~/reachy-venv virtual env (Bookworm enforces PEP 668; system pip is blocked)
# - Adds shell helper to activate the venv
# Idempotent: safe to re-run.

set -euo pipefail

echo "==> Installing pipx (for global CLI Python tools)"
sudo DEBIAN_FRONTEND=noninteractive apt install -y pipx
pipx ensurepath >/dev/null 2>&1 || true

echo "==> Installing uv (fast Python package manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "  -> uv: $(uv --version)"

echo "==> Creating ~/reachy-venv (seeded with pip)"
if [ ! -d "$HOME/reachy-venv" ]; then
  uv venv "$HOME/reachy-venv" --python 3.11 --seed
  echo "  -> Created"
else
  echo "  -> Already exists (re-seeding pip in case it's missing)"
  uv pip install --python "$HOME/reachy-venv/bin/python" pip setuptools wheel
fi

echo "==> Adding shell helper (rmenv) to ~/.bashrc"
HELPER='# reachy-mini-stack helper'
if ! grep -qF "$HELPER" "$HOME/.bashrc"; then
  cat >> "$HOME/.bashrc" <<'EOF'

# reachy-mini-stack helper
export PATH="$HOME/.local/bin:$PATH"
alias rmenv='source $HOME/reachy-venv/bin/activate'
EOF
  echo "  -> Added 'rmenv' alias and PATH update"
else
  echo "  -> Already present"
fi

echo "==> Verifying venv"
"$HOME/reachy-venv/bin/python" --version
"$HOME/reachy-venv/bin/python" -m pip --version

echo "==> Done. Activate the venv with: source ~/reachy-venv/bin/activate (or 'rmenv' after a new shell)"
