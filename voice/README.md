# reachy_voice

Household voice assistant for the Reachy Mini Wireless. Say **"Hey Jarvis"** (a custom
"Hey Reachy" model comes in Plan 3), talk naturally, and Reachy hands real work to the
household's Hermes agent on the Pi without going silent.

- Engines: Gemini 3.8 Live and OpenAI gpt-live-1. Set `VOICE_ENGINE` in `~/reachy-voice/voice.env`
  on the robot to `gemini`, `openai` or `alternate` (alternates per conversation for the bake-off).
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
