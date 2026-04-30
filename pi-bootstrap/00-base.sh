#!/usr/bin/env bash
# 00-base.sh — Base system setup for Reachy Mini stack on Pi 5 (Bookworm)
# - Full apt update/upgrade
# - Base build tools + kernel headers (needed for Hailo PCIe driver via DKMS)
# - Enable PCIe Gen 3 for the Hailo AI HAT (default is Gen 2)
# Idempotent: safe to re-run.

set -euo pipefail

echo "==> apt update + upgrade"
sudo apt update
sudo DEBIAN_FRONTEND=noninteractive apt -y \
  -o Dpkg::Options::="--force-confdef" \
  -o Dpkg::Options::="--force-confold" \
  full-upgrade

echo "==> Installing base packages"
sudo DEBIAN_FRONTEND=noninteractive apt install -y \
  git curl wget ca-certificates gnupg \
  build-essential pkg-config cmake meson ninja-build \
  raspberrypi-kernel-headers linux-headers-rpi-2712 dkms \
  python3 python3-venv python3-pip python3-dev \
  libcairo2-dev libgirepository1.0-dev libffi-dev libssl-dev libusb-1.0-0-dev \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav \
  libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
  jq htop tmux vim less \
  software-properties-common

echo "==> Configuring PCIe Gen 3 for Hailo HAT"
CONFIG=/boot/firmware/config.txt
if ! grep -q "^dtparam=pciex1_gen=3" "$CONFIG"; then
  {
    echo ""
    echo "# Hailo AI HAT — enable PCIe Gen 3 for max bandwidth"
    echo "dtparam=pciex1_gen=3"
  } | sudo tee -a "$CONFIG" >/dev/null
  echo "  -> Added dtparam=pciex1_gen=3"
  echo "  -> *** Reboot required for this to take effect ***"
else
  echo "  -> dtparam=pciex1_gen=3 already set"
fi

echo "==> Done."
