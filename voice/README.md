# reachy_voice

Household voice assistant for the Reachy Mini Wireless. Say **"Hey Jarvis"** (a custom
"Hey Reachy" model comes in Plan 3), talk naturally, and Reachy hands real work to the
household's Hermes agent on the Pi without going silent.

- Engines: Gemini 3.8 Live, OpenAI gpt-live-1, and xAI Grok speech-to-speech. Set `VOICE_ENGINE`
  in `~/reachy-voice/voice.env` on the robot to `gemini`, `openai`, `grok`, or `alternate`
  (`alternate` swaps Gemini and OpenAI per conversation for the bake-off; it does not include Grok).
- Wake word: openWakeWord (`WAKE_MODEL`, `WAKE_THRESHOLD`); nothing leaves the robot until it fires.
- Hand-offs: Hermes at `HOME_AGENT_URL`. List and note requests use the quick lane (`QUICK_MODEL`).
- Sessions close after `IDLE_TIMEOUT_S` (30) of quiet. While a hand-off is pending they stay open
  up to `PENDING_MAX_S` (330). They never run past `MAX_SESSION_S` (600).
- Logs: `~/reachy-voice/logs/voice-*.jsonl` (first_audio latency, delegations, session ends).

## Body language

Reachy moves with the conversation. Four states: **sleeping** (head down, motors off), **awake in
conversation** (wake-up move, turn toward the voice, still and antennas perked while you talk, head
motion and face tracking while it talks, expressions), **awake idle** (head at neutral, motors on, so a
quick second "Hey Jarvis" needs no wake-up move), then **sleep** once it has been idle for
`IDLE_AWAKE_S`. The service starts asleep.

Settings in `~/reachy-voice/voice.env` on the robot:

- `BODY_ENABLED` (default `true`): `false` gives voice-only, exactly as before.
- `IDLE_AWAKE_S` (default 300): idle time after a conversation before Reachy goes to sleep.
- `EXPRESSION_MIN_GAP_S` (default 8): minimum spacing between expressions, across sessions.
- `TRACKING_WEIGHT` (default 0.6): how strongly the head follows a face while Reachy talks.

Calibration (direction-of-arrival mapping, turn limits, antenna poses) lives in
`reachy_voice/body_calibration.py`; see `BODY_NOTES.md`.

## Deploy and operate (from the Mac)

    voice/deploy/deploy-voice.sh            # deploy + restart the service
    voice/deploy/deploy-voice.sh --enable   # also start at boot
    ssh pollen@reachy-mini.local 'journalctl -u reachy-voice -f'
    ssh pollen@reachy-mini.local 'sudo systemctl stop reachy-voice'   # silence Reachy

The service stops the daemon's current app when it starts, because only one owner can hold the mic.
Don't start Pollen's conversation app while `reachy-voice` is running.

`voice/spike/` is the frozen measurement spike that chose these engines (see `spike/RESULTS.md`).

## Grok

`VOICE_ENGINE=grok` uses xAI speech-to-speech (`wss://api.x.ai/v1/realtime`) as the robot's voice.
The socket is outbound only. This app does not listen on the network, and a failed Grok start does
not fall back to Gemini or OpenAI.

In `~/reachy-voice/voice.env` on the robot (mode 600):

```bash
VOICE_ENGINE=grok
XAI_API_KEY=...                 # required; never commit it
# XAI_MODEL=grok-voice-latest   # default; set grok-voice-3.0 to pin a version
# XAI_VOICE=eve                 # default built-in voice
```

`GEMINI_API_KEY` and `OPENAI_API_KEY` are not required for this engine. Audio is PCM at 16 kHz,
matching the robot mic and speaker. `reasoning.effort` is `none` so replies stay in the same
latency band as the other engines (target about 1–1.5 s to first audio; the log is the measurement).
`express` and `look` are offered when `BODY_ENABLED` is true (the default). Household lists still
go to Hermes through `ask_home_agent`; Hermes itself stays on the model in `household/hermes/config.yaml`.

`voice/deploy/deploy-voice.sh` copies `XAI_API_KEY` from the conversation-app `.env` when that line
is present, and otherwise keeps the `XAI_API_KEY` and `VOICE_ENGINE` already in `voice.env`.

## Local test on the physical robot

Run this on the robot. Do not point the voice process at a laptop, and do not open a port for it.

### What runs where

| Machine | Role |
| --- | --- |
| Reachy Mini Wireless (`pollen@reachy-mini.local`) | `reachy-mini-daemon` and `reachy-voice`. `ReachyMini()` takes no host argument; it talks to the daemon on that same machine (`127.0.0.1:8000`). |
| Mac | Deploy only, via `voice/deploy/deploy-voice.sh`. |
| Pi (`behindtheproduct@reachy-pi.local`) | Hermes, and only if you want a list or note hand-off. Not required to hear Grok speak. |

The Pi simulator is a different install: Python 3.11.2, `reachy-mini` 1.7.0 with MuJoCo 3.3.0, started with `run-sim.sh`. Do not use `pi-bootstrap/` to prepare the robot.

### Versions to confirm

The voice plan and `household/README.md` record the robot as software / SDK **1.11.0** (1.10 or newer is required). `voice/deploy/deploy-voice.sh` builds the venv with uv (`/opt/uv/uv`) and Python **3.12**:

`/home/pollen/.local/share/uv/python/cpython-3.12.*-linux-aarch64-gnu/bin/python3`

That venv adds `/venvs/apps_venv` (Python 3.12), which supplies `reachy_mini`, numpy, scipy, `httpx` 0.28, `websockets` 15, and onnxruntime 1.27. `voice/reachy_voice/requirements.txt` adds `google-genai==2.28.0`, `soxr==1.1.0`, tqdm, and requests. The deploy script also installs `openwakeword==0.6.0` with `--no-deps`. There is no Node.js dependency on this path.

```bash
ssh pollen@reachy-mini.local 'systemctl is-active reachy-mini-daemon; ~/reachy-voice/.venv/bin/python -c "
import sys, importlib.metadata as m
print(\"python\", sys.version.split()[0])
for pkg in (\"reachy-mini\", \"websockets\", \"httpx\", \"google-genai\", \"soxr\", \"openwakeword\"):
    print(pkg, m.version(pkg))
"'
```

Expect Python 3.12.x, `reachy-mini` 1.11.0, and `websockets` 15.x. Re-check rather than assuming those pins have not moved. `reachy-voice` itself stays inactive until you start it; the daemon should already be active.

### Power and network

Power the Reachy Mini Wireless so `reachy-mini-daemon` is running. This repo does not document a USB tether or a laptop-hosted daemon for this app; direction-of-arrival is an on-robot USB read inside the SDK, and the voice program does not choose a USB device.

The robot is on the house Wi-Fi and needs outbound WSS to `api.x.ai`. No new listening port is opened. The service unit stops the daemon's current app first (`POST http://127.0.0.1:8000/api/apps/stop-current-app`) because only one program can hold the mic.

### Config switch

On the robot, in `~/reachy-voice/voice.env`:

```bash
VOICE_ENGINE=grok
XAI_API_KEY=...
```

Optional: `XAI_MODEL`, `XAI_VOICE`, `BODY_ENABLED`, `HOME_AGENT_URL`, `HOME_AGENT_KEY`, `VOICE_LOG_DIR` (deploy writes `/home/pollen/reachy-voice/logs` when it is missing). There is no robot-host variable.

### Start

From the Mac, in this repo, after `voice.env` has the two lines above:

```bash
voice/deploy/deploy-voice.sh
```

If the code is already deployed and only the env file changed:

```bash
ssh pollen@reachy-mini.local 'sudo systemctl restart reachy-voice'
```

The unit runs `~/reachy-voice/.venv/bin/python -m reachy_voice.main` with `EnvironmentFile=/home/pollen/reachy-voice/voice.env`. To watch it in the foreground instead:

```bash
ssh pollen@reachy-mini.local 'curl -s -m 30 -X POST http://127.0.0.1:8000/api/apps/stop-current-app; cd ~/reachy-voice && set -a && . ./voice.env && set +a && .venv/bin/python -m reachy_voice.main'
```

### Smoke test

With the room quiet, about 1 m from the robot:

1. Say **Hey Jarvis**. Expect the wake chime, then a short spoken reply.
2. Read the new log:

```bash
ssh pollen@reachy-mini.local 'cd ~/reachy-voice && f=$(ls -t logs/voice-*.jsonl | head -1); python3 -c "
import json
for l in open(\"$f\"):
    e=json.loads(l)
    if e[\"event\"] in (\"ready\",\"wake\",\"session_open\",\"first_audio\",\"session_end\",\"session_error\",\"engine_error\"):
        print({k:v for k,v in e.items() if k!=\"ts\"})
"'
```

Expect `ready` with `engine_mode` `grok`, `session_open` with `engine` `grok`, and a `first_audio` line. No `session_error`.
3. Stay quiet for about 35 seconds. Expect the sleep chime and `session_end` with `reason` `idle`.
4. Optional, only when Hermes is up on the Pi and `HOME_AGENT_URL` / `HOME_AGENT_KEY` are set: ask "What's on the grocery list?" Expect a `delegation` with `lane` `quick`.

Stop it with:

```bash
ssh pollen@reachy-mini.local 'sudo systemctl stop reachy-voice'
```

Development tests mock the socket. They do not call xAI and they do not touch the robot.
