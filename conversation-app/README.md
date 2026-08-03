# Conversation app — Phase 1 wiring

The comedian profile and the showrunner bridge for
[`pollen-robotics/reachy_mini_conversation_app`](https://github.com/pollen-robotics/reachy_mini_conversation_app).

## Where things run

Two processes, and **which machine each one runs on decides `SHOWRUNNER_URL`**.
Getting this wrong produces a connection error from the bridge that looks like a
bug in the tool but is only a wrong address.

| Topology | Conversation app | `SHOWRUNNER_URL` | Showrunner bind |
|---|---|---|---|
| **A — both on the Mac** | Mac | `http://127.0.0.1:7861` | `127.0.0.1` (default) |
| **B — app on the robot** | Reachy CM4 | `http://<mac-lan-ip>:7861` | `0.0.0.0` |

Reachy Mini **Wireless** runs the app onboard, so topology B is the likely one —
the upstream README's Wireless section says to set the backend env vars *on the
robot*. Audio confirms it: the app tunes the XVF3800 processor on the robot's own
hardware and never opens a local audio device.

Current addresses on this network:

- Mac: `192.168.253.103`
- Robot: `192.168.253.143` (also `reachy-mini.local`)

## Run — topology A (both on the Mac)

```bash
cd ../showrunner && ../.venv/bin/python -m uvicorn showrunner.api:build_app --factory --port 7861
```

Console at http://127.0.0.1:7861/ — load a document, review the facts, write the
set, arm it.

```bash
export REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=/Users/painter/palettepal/reachy-mini-stack/conversation-app/external_profiles
export REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=/Users/painter/palettepal/reachy-mini-stack/conversation-app/external_tools
export REACHY_MINI_CUSTOM_PROFILE=comedian
export AUTOLOAD_EXTERNAL_TOOLS=1
export SHOWRUNNER_URL=http://127.0.0.1:7861
reachy-mini-conversation-app --ui
```

## Run — topology B (app on the robot)

Bind the showrunner so the robot can reach it:

```bash
cd ../showrunner && ../.venv/bin/python -m uvicorn showrunner.api:build_app --factory --host 0.0.0.0 --port 7861
```

Confirm from the robot before starting the app — this is the check that saves
the debugging session:

```bash
ssh <robot-user>@reachy-mini.local 'curl -s http://192.168.253.103:7861/health'
```

Expect `{"status":"ok","phase":...}`. If it hangs or refuses, the showrunner is
still bound to loopback or the Mac firewall is blocking 7861 — fix that before
touching the app.

Then on the robot, `external_profiles/` and `external_tools/` must exist locally
(copy this directory over) and `SHOWRUNNER_URL` points back at the Mac:

```bash
export SHOWRUNNER_URL=http://192.168.253.103:7861
```

> Binding `0.0.0.0` puts the console and the tool endpoints on the LAN with no
> authentication — deliberate, per the spec's out-of-scope list. Fine on a home
> or office network; do not do it on untrusted wifi.

## Why a bridge instead of MCP

The conversation app has first-class remote MCP support, but it cannot be
pointed at a local server. `tool_spaces.validate_space_mcp_url` requires an
HTTPS host ending `.hf.space` on port 443 with the exact path
`/gradio_api/mcp/`, and it guards the only place `RemoteMcpServerConfig` is
constructed. The installed-spaces manifest is re-validated on read, so
hand-editing it doesn't help either. `mcp_client.py` does allow plain HTTP for
localhost — but nothing in the app calls that code path.

So Phase 1 bridges over plain HTTP instead.

## Phase 2

Delete `external_tools/showrunner_bridge.py`. The showrunner deploys as an HF
Space, its Gradio MCP endpoint matches the validator, and the app installs it
from the Tools UI over MCP. That also makes the topology question moot — the
robot reaches a public HTTPS URL either way.
