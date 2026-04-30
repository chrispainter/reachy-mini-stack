# reachy-mini-stack

Pre-arrival Pi 5 + AI HAT setup for the Reachy Mini Wireless. Drives a MuJoCo sim now; becomes the LAN AI inference node when the physical robot arrives.

## What's on the Pi (`reachy-pi.local`, user `behindtheproduct`)

| Layer            | Status      | Notes                                                            |
|------------------|-------------|------------------------------------------------------------------|
| OS               | Bookworm 64 | Pi 5, kernel `6.12.75+rpt-rpi-2712`                              |
| PCIe             | Gen 3 x1    | `dtparam=pciex1_gen=3` in `/boot/firmware/config.txt`            |
| Python           | 3.11.2      | Two venvs: `~/reachy-venv` (SDK), `~/clawbody/.venv` (ClawBody)  |
| `uv`             | 0.11.8      | Installed at `~/.local/bin/uv`                                   |
| Reachy Mini SDK  | 1.7.0       | with `mujoco` extra                                              |
| MuJoCo           | 3.3.0       | Sim daemon binds `0.0.0.0:8000`, mDNS as `reachy_mini`           |
| Hailo runtime    | 4.20.0      | `/dev/hailo0` live; `hailortcli fw-control identify` confirms FW |
| Docker Engine    | 29.4.1      | + Compose v5.1.3, rootless for `behindtheproduct`                |
| ClawBody         | latest      | Cloned to `~/clawbody`, OpenClaw → Reachy bridge with face track |

## Layout

```
pi-bootstrap/      Numbered idempotent setup scripts, runnable on a fresh Pi
inference-node/    LAN AI inference services (post-arrival)
clawbody-config/   OpenClaw → ClawBody bridge config
apps-private/      Private experimental Reachy apps (not for HF Spaces)
docs/              Decisions, troubleshooting
run-sim.sh         Start the simulator on the Pi
run-clawbody.sh    Start ClawBody (Gradio web UI on :7860)
```

## Quick start (on the Pi)

```bash
# Terminal 1 — start the simulator
~/reachy-mini-stack/run-sim.sh

# Terminal 2 — start ClawBody (UI on http://reachy-pi.local:7860)
# First time: edit ~/clawbody/.env with your OPENAI_API_KEY
~/reachy-mini-stack/run-clawbody.sh --no-openclaw          # standalone, OpenAI Realtime only
~/reachy-mini-stack/run-clawbody.sh                         # full OpenClaw bridge (needs gateway config)
```

## OpenClaw bridge — to be wired up

ClawBody expects the OpenClaw gateway at `OPENCLAW_GATEWAY_URL` (default port 18789). The user's OpenClaw runs on a Hostinger VPS at `openclaw.proxybrain.cloud`; its gateway is internal to the container. Two viable paths:

1. **SSH reverse tunnel** from Pi to VPS, mapping `127.0.0.1:18789` on the Pi to the gateway port inside the container.
2. **Add a Traefik route** for the gateway (`gateway.proxybrain.cloud`) with token auth. Higher reach but exposes the port — needs careful auth.

Token lives at `/data/.openclaw/openclaw.json → gateway.token` inside the OpenClaw container.

## Reproduce on a fresh SD card

Flash Raspberry Pi OS Legacy (Bookworm) 64-bit with SSH key + Wi-Fi pre-configured, then on the Pi:

```bash
git clone https://github.com/<YOUR_GH>/reachy-mini-stack ~/reachy-mini-stack
bash ~/reachy-mini-stack/pi-bootstrap/00-base.sh
sudo reboot
bash ~/reachy-mini-stack/pi-bootstrap/01-python.sh
bash ~/reachy-mini-stack/pi-bootstrap/02-reachy-sdk.sh
bash ~/reachy-mini-stack/pi-bootstrap/03-hailo.sh
bash ~/reachy-mini-stack/pi-bootstrap/04-docker.sh
sudo reboot
bash ~/reachy-mini-stack/pi-bootstrap/05-clawbody.sh
```
