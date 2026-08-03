# Robot integration notes — 2026-08-03

First end-to-end run of the comedian profile against the physical Reachy Mini
Wireless. Everything here is measured, not assumed.

## It works

Full chain, from one debug run:

```
07:42:33  session starts, 9 tools registered
07:42:35  "Alright, let me see what my writer thought was survivable here."
07:42:35  Tool call received — get_set_list
07:42:35  POST http://127.0.0.1:7861/tools/get_set_list → 200 OK
07:42:36  "Sprint 14 Status. Four lines. I read all four and I have things
           to say about three of them, which for a status doc is a scandal."
```

The robot read the document, called the showrunner, got the set, and performed
the opener aloud. The line it improvised while waiting for the tool result is in
none of the prompts — the persona covering latency in character on its own.

## Topology

The app runs **on the Mac** and reaches the robot over WebRTC. Audio comes out
of the robot's speaker; motion works. Confirmed by ear.

`SHOWRUNNER_URL=http://127.0.0.1:7861` is therefore correct as written. If the
app is ever moved onto the robot's CM4, it must become the Mac's LAN IP
(`192.168.253.103`) and the showrunner must bind `0.0.0.0`.

## Latency baseline (BL-07)

Measured from debug timestamps, cloud realtime backend, app on the Mac:

| Event | t+ms |
|---|---:|
| greeting queued | 0 |
| first speech | 1,338 |
| tool call received | 1,338 |
| bridge fired | 1,361 |
| showrunner HTTP 200 | 1,618 |
| tool executed ok | 1,672 |
| opener delivered | 2,967 |

**Prompt to first audio: ~1.34 s.** That is the number BL-07 compares a local
backend against, and essentially all of it is the cloud round trip.

Tool round trip was 334 ms, of which the raw HTTP leg was ~257 ms. Isolated
benchmarking showed the HTTP leg itself is ~10 ms with a per-call client and
~0.6 ms with a reused one; the bridge now reuses a module-level
`httpx.AsyncClient`. The remaining ~250 ms is the app's event loop and
background-tool-manager overhead, not the bridge.

## Audio

- Speaker volume `100`, microphone volume `100` — confirmed via
  `GET /api/volume/current` and `/api/volume/microphone/current`. Already
  maxed; no headroom left in software.
- `POST /api/volume/test-sound` plays a sound directly on the robot, bypassing
  the app entirely. Useful for separating "speaker is quiet" from "app path is
  quiet". The test sound was **louder** than the app's speech, so there is a
  little software headroom — but not enough to matter.
- **The speaker is simply not loud.** Small sealed driver in a plastic shell.
  For BL-08, put a mic next to it rather than relying on room pickup.

### The microphone side is the real gap

`No Reachy Mini Audio USB device found!` appears twice at startup. The SDK's
`audio_control_utils` talks to the ReSpeaker XVF3800 over **USB**
(VID `0x2886`, PID `0x001A`), which only exists when the app runs on the robot
or on a USB-connected Lite. From the Mac it cannot be reached, so
`AUDIO_STARTUP_CONFIG` never gets applied — AGC, noise suppression and echo
tuning all stay at defaults.

That is mic-side, not speaker-side, so it is **not** the volume problem. But it
matters for a heckle-driven bit: it affects how well the robot hears people
calling out from a few feet away. The daemon does expose
`POST /api/audio/config/apply` and `GET /api/audio/config/parameter/{name}`, so
these can be driven remotely if it becomes a problem — the app just doesn't use
that path.

Current on-robot value: `PP_AGCMAXGAIN = 64.0`. The app's startup config wants
`10.0`.

## Gotchas hit, and their fixes

**SSL — this one blocks everything.** The python.org 3.13 build has no CA
bundle configured (`ssl.get_default_verify_paths().cafile` is `None`), so the
Hugging Face realtime backend fails with `CERTIFICATE_VERIFY_FAILED` and retries
every 5 s forever. The app starts, the UI works, and it simply never speaks.

Fixed by pointing `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` at certifi's bundle in
`reachy_mini_conversation_app/.env`. The permanent alternative is running
`/Applications/Python 3.13/Install Certificates.command` once, which fixes every
venv on the machine.

**Version mismatch — still open.** SDK `1.10.0rc2` vs daemon `1.9.0`. The SDK
warns explicitly that this can cause problems. Worth resolving before a shoot
rather than debugging a strange symptom mid-take.

**Harmless warnings, safe to ignore:**

- `⚠️ Tool 'get_set_list' not found in shared or external tools` — printed three
  times at load, once per bridge tool. The profile's `default_tools` names them
  before the external module is scanned; they register correctly moments later
  (`tool registered: get_set_list`, etc.). Cosmetic ordering only.
- `GStreamer-WARNING ... libgstpython.dylib ... Library not loaded:
  @rpath/libpython3.13.dylib` — a packaging issue in the `gstreamer_python`
  wheel on 3.13. Audio and video both worked regardless.

## Emotion vocabulary

`play_emotion` accepts these intents (from
`tools/play_emotion.py:EMOTION_INTENTS`):

```
amazed, angry, anxious, attentive, bored, calming, confused, dance, disgusted,
displeased, downcast, dying, electric, embarrassed, excited, go_away, goodbye,
grateful, greeting, happy, helpful, impatient, irritated, lonely, loving, no,
no_excited, no_firm, no_sad, random, relief, sad, scared, sleepy, success,
surprised, thinking, tired, uncertain, welcoming, yes, yes_understanding
```

`move_head` takes `left`, `right`, `up`, `down`, `front`. The profile's
`move_hint` table now maps to these real names.

## Running it

Config lives in `reachy_mini_conversation_app/.env`, so no exports are needed:

```bash
# 1. showrunner
cd reachy-mini-stack/showrunner && ../.venv/bin/python -m uvicorn showrunner.api:build_app --factory --port 7861

# 2. arm a set (or use the console at http://127.0.0.1:7861/)
curl -X POST localhost:7861/operator/load  -H 'Content-Type: application/json' -d @doc.json
curl -X POST localhost:7861/operator/write -H 'Content-Type: application/json' -d '{"beat_count":4}'
curl -X POST localhost:7861/operator/arm

# 3. the robot
cd reachy_mini_conversation_app && .venv/bin/reachy-mini-conversation-app --debug --no-camera
```

## Still to do

- Resolve the SDK/daemon version mismatch
- Heckle test — interrupt mid-beat and confirm `get_fact` fires (not yet tried)
- Confirm `mark_beat` reaches the console during a full performance
- Decide mic placement for BL-08
