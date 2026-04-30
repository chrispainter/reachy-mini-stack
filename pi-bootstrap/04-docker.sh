#!/usr/bin/env bash
# 04-docker.sh — Install Docker Engine on Pi 5 (Bookworm) using Docker's official APT repo
# This is the inference-node foundation: STT/TTS/vision services will run as containers.
# Adds the current user to the docker group (requires logout or reboot to take effect).
# Idempotent: safe to re-run.

set -euo pipefail

if command -v docker >/dev/null 2>&1; then
  echo "==> Docker already installed: $(docker --version)"
else
  echo "==> Adding Docker official APT repo"
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg \
    | sudo gpg --dearmor --batch --yes -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  echo "==> Installing Docker Engine + Compose plugin + Buildx"
  sudo apt update
  sudo DEBIAN_FRONTEND=noninteractive apt install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
fi

echo "==> Adding $USER to docker group (effective after logout/reboot)"
if ! groups "$USER" | grep -qw docker; then
  sudo usermod -aG docker "$USER"
  echo "  -> Added"
else
  echo "  -> Already in docker group"
fi

echo "==> Versions"
docker --version
docker compose version

echo "==> Done. To use docker without sudo, log out and back in (or reboot)."
