#!/usr/bin/env bash
# 03-hailo.sh — Install Hailo AI HAT runtime + DKMS PCIe driver on Pi 5 (Bookworm)
# Uses the `hailo-all` meta-package from the official Raspberry Pi APT repo.
# Pulls in: hailort runtime, hailo PCIe driver (DKMS), hailo-tappas, rpicam-apps integration.
# Idempotent: safe to re-run; verification at the end is non-destructive.

set -euo pipefail

echo "==> Verifying PCIe device"
if ! lspci -d 1e60: | grep -q "Hailo"; then
  echo "ERROR: No Hailo device on PCIe bus. Check the HAT is seated and PCIe ribbon is connected."
  exit 1
fi
lspci -d 1e60:

echo
echo "==> Installing hailo-all (HailoRT + DKMS driver + Tappas + rpicam-apps integration)"
sudo DEBIAN_FRONTEND=noninteractive apt install -y hailo-all

echo
echo "==> Verifying DKMS module status"
sudo dkms status | grep -i hailo || echo "  (no hailo DKMS modules found yet — may need reboot)"

echo
echo "==> Verifying device node /dev/hailo0"
if [ -e /dev/hailo0 ]; then
  ls -la /dev/hailo0
  echo "  -> /dev/hailo0 present"
else
  echo "  -> /dev/hailo0 NOT present yet. Likely needs a reboot for the kernel module to load."
fi

echo
echo "==> Verifying HailoRT CLI (hailortcli)"
if command -v hailortcli >/dev/null 2>&1; then
  echo "  -> hailortcli installed: $(hailortcli --version 2>&1 | head -1)"
else
  echo "  -> hailortcli not on PATH"
fi

echo
echo "==> If /dev/hailo0 was missing, reboot now: sudo reboot"
echo "    After reboot, verify with: hailortcli fw-control identify"
