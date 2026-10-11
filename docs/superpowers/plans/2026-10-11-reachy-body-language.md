# Reachy Body Language Implementation Plan (Plan 3, part 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reachy wakes up, turns toward the person, tracks their face while speaking, moves its head with its own speech, shows fitting expressions, stays still while people talk, and sleeps with motors off after `IDLE_AWAKE_S` of no conversation. The voice never breaks because of the body.

**Architecture:**
- A new `Body` unit is the only code that drives motion. It wraps the `reachy_mini` SDK, running blocking SDK calls in a worker thread behind an asyncio lock. It never raises.
- Pure policy units decide when Reachy expresses itself and when it sleeps: `AwakeTimer`, `ExpressionGate`, a table of automatic cues, and `doa_to_yaw`. They are unit-tested on the Mac with fakes.
- `VoiceSession` calls body hooks on speaking and listening transitions and on hand-off events.
- Gemini gets `express` and `look` tools. OpenAI gets a cheap `ExpressionPicker` that runs after each Reachy utterance.
- `main.py` owns the wake → session → rest → sleep lifecycle.

**Tech Stack:**
- `reachy_mini` SDK 1.11.0 on the robot (`ReachyMini` motion API, `RecordedMoves`, `create_head_pose`)
- Pollen's `reachy_mini_conversation_app.tools.play_emotion.resolve_emotion_name`, which is installed in apps_venv and imported with a guard
- `httpx` and `gpt-5.4-nano` for the picker
- pytest on the Mac

**Spec:** `docs/superpowers/specs/2026-10-11-reachy-body-language-design.md`

## Global Constraints

- **The repo is public:** no keys or personal details in commits. Keys stay in `~/reachy-voice/voice.env` on the robot.
- **The body can never break the voice.**
  - Every public `Body` method catches `Exception`, logs `body_error` with `action` and `error=repr(exc)`, and returns.
  - Session code calls the body only through spawned tasks or awaits that can't raise.
- **SDK motion calls block** (`goto_target`, `wake_up`, `goto_sleep` and `RecordedMoves(...)` construction). `Body` runs them via `asyncio.to_thread`. Only `async_play_move` is awaited directly. All motion goes through one `asyncio.Lock`.
- **Emotion moves play with `sound=False`.** Their sounds would collide with Reachy's voice output.
- **Emotion library:** `RecordedMoves("pollen-robotics/reachy-mini-emotions-library")`, which is already cached on the robot. Names are resolved with Pollen's `resolve_emotion_name(intent, lib.list_moves())` when it imports. Otherwise only an exact name match counts. If the library can't load, expressions are disabled for that run and logged once.
- **Behaviour (from the spec):**
  - *Listening:* face tracking paused with `start_head_tracking(weight=0.0)`, wobbling off, antennas at `ANTENNA_LISTEN`, no expressions.
  - *Speaking:* `start_head_tracking(weight=TRACKING_WEIGHT)`, `enable_wobbling()`, antennas at `ANTENNA_REST`.
  - *Expression:* tracking weight 0 and wobbling off for the move's duration, then the current mode is restored.
- **Automatic cues** (event → intent):

  | Event | Intent |
  |---|---|
  | wake from sleep | `welcoming` |
  | hand-off start | `thinking` |
  | hand-off ok | `yes_understanding` |
  | hand-off failed | `uncertain` |
  | session end (reason ≠ `error`) | `goodbye` |

- **Expression gate.** It applies to cues and model picks alike:
  - at most one expression per `EXPRESSION_MIN_GAP_S` (default 8)
  - none while the person spoke within the last 0.5 s
  - none in the first 1.0 s of a Reachy utterance

  A rejected expression is dropped and logged as `expression_dropped`.
- **New settings:**

  | Variable | Default | Type |
  |---|---|---|
  | `BODY_ENABLED` | `true` | true/false/1/0/yes/no |
  | `IDLE_AWAKE_S` | `300` | number |
  | `EXPRESSION_MIN_GAP_S` | `8` | number |
  | `TRACKING_WEIGHT` | `0.6` | number |

  `BODY_ENABLED=false` gives `NullBody`, which is exactly Plan 2's behaviour.
- **Gemini body tools:**
  - `express(emotion)` and `look(direction)`, declared `behavior=NON_BLOCKING`.
  - Answered immediately with `{"ok": true}` and `scheduling=SILENT`.
  - `direction` is one of `left`, `right`, `up`, `down`, `front` or `at_person`.
- **OpenAI picker:** `gpt-5.4-nano` via `POST https://api.openai.com/v1/chat/completions` with a 3 s timeout. It returns an intent from `EMOTIONS` or `None`; any error also returns `None`.
- **Mac tests:**
  - Run with `cd voice && ../.venv/bin/python -m pytest -q`.
  - New test files are named `voice/tests/test_rv_*.py`.
  - `reachy_mini` and `reachy_mini_conversation_app` are not installed on the Mac, so `body.py` imports them lazily inside methods and tests use fakes.
- **Robot SSH:** `ssh -4 pollen@reachy-mini.local`. Deploy with `voice/deploy/deploy-voice.sh`; the service is already enabled at boot.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A motor or SDK error mid-conversation.** The conversation continues voice-only and the session isn't stuck. Tested in Task 4 (Body swallows and logs) and Task 6 (session with a raising body).
2. **The model spams `express`.** The gate holds expressions to one per 8 s and never fires one while the person is talking. Tested in Task 2 (gate) and Task 6 (session drops extras).
3. **A wake word arrives while Reachy is asleep, or right after a session.** The timer reports the right state, and an already-awake Reachy skips the wake-up move. Tested in Task 2 (`AwakeTimer`).
4. **The emotion library is missing or a name doesn't resolve.** Expressions are skipped and everything else still moves. Tested in Task 4.
5. **The service stops while Reachy is awake.** The head goes to sleep and the motors turn off, even if `goto_sleep` fails. Tested in Task 4 (`Body.shutdown`) and checked on the robot in Task 7.

---

### Task 1: Robot body probe (spike, with the user present)

**Files:**
- Create: `voice/tools/body_probe.py`
- Create: `voice/reachy_voice/body_calibration.py`, holding the measured constants
- Create: `voice/BODY_NOTES.md`, holding the findings

**Interfaces:**
- Produces: `reachy_voice.body_calibration` with these constants:
  - `DOA_FRONT_RAD: float`, the DoA angle when the speaker is straight in front
  - `DOA_SIGN: float`, which is +1 or −1 so that `yaw = DOA_SIGN * (angle − DOA_FRONT_RAD)` turns toward the speaker (positive yaw = left)
  - `MAX_TURN_RAD: float`
  - `ANTENNA_LISTEN: list[float]` and `ANTENNA_REST: list[float]`, each `[right, left]` in radians

  Task 2 imports these.

- [ ] **Step 1: Write the probe**

`voice/tools/body_probe.py`:
```python
"""Throwaway hardware probe for body-language design questions. Run on the robot with the
voice service stopped:  sudo systemctl stop reachy-voice
  .venv/bin/python tools/body_probe.py wake        # motors on + wake_up, timed
  .venv/bin/python tools/body_probe.py doa         # prints DoA for 15 s: speak from left, front, right
  .venv/bin/python tools/body_probe.py antennas    # cycles antenna positions
  .venv/bin/python tools/body_probe.py emotion thinking
  .venv/bin/python tools/body_probe.py noise       # mic RMS with head still vs moving (no speech)
  .venv/bin/python tools/body_probe.py track       # tracking 0.6 + wobble while a tone plays
  .venv/bin/python tools/body_probe.py sleep       # goto_sleep + motors off, timed
"""

import sys
import time

import numpy as np
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose


def rms_for(mini, seconds):
    vals, t = [], time.time()
    while time.time() - t < seconds:
        s = mini.media.get_audio_sample()
        if s is not None and len(s):
            vals.append(float(np.sqrt(np.mean(np.square(s[:, 0])))))
        else:
            time.sleep(0.005)
    return np.percentile(vals, 50), np.percentile(vals, 95)


def main(cmd, arg=None):
    with ReachyMini() as mini:
        if cmd == "wake":
            t = time.time(); mini.enable_motors(); mini.wake_up(); print(f"wake_up took {time.time()-t:.1f}s")
        elif cmd == "sleep":
            t = time.time(); mini.goto_sleep(); mini.disable_motors(); print(f"goto_sleep took {time.time()-t:.1f}s")
        elif cmd == "doa":
            mini.media.start_recording()
            t = time.time()
            while time.time() - t < 15:
                rms_for(mini, 0.2)
                print("doa", mini.media.get_DoA(), flush=True)
            mini.media.stop_recording()
        elif cmd == "antennas":
            mini.enable_motors()
            for a in ([0.0, 0.0], [0.4, -0.4], [-0.4, 0.4], [0.3, 0.3], [-0.3, -0.3]):
                print("antennas", a, flush=True); mini.goto_target(antennas=a, duration=0.6, body_yaw=None); time.sleep(1.5)
        elif cmd == "emotion":
            from reachy_mini.motion.recorded_move import RecordedMoves
            from reachy_mini_conversation_app.tools.play_emotion import resolve_emotion_name
            lib = RecordedMoves("pollen-robotics/reachy-mini-emotions-library")
            name = resolve_emotion_name(arg, lib.list_moves())
            mini.enable_motors()
            t = time.time(); mini.play_move(lib.get(name), sound=False); print(f"{arg}->{name} took {time.time()-t:.1f}s")
        elif cmd == "noise":
            mini.media.start_recording(); mini.enable_motors()
            print("still   p50/p95", rms_for(mini, 4))
            t = time.time()
            while time.time() - t < 4:
                mini.goto_target(create_head_pose(yaw=12 * np.sin(time.time() * 3)), duration=0.15, body_yaw=None)
            print("moving  p50/p95", rms_for(mini, 0.1), "(sampled after)")
            mini.media.stop_recording()
        elif cmd == "track":
            mini.enable_motors(); mini.media.start_playing()
            mini.start_head_tracking(weight=0.6); mini.enable_wobbling()
            tone = (0.15 * np.sin(2 * np.pi * 220 * np.arange(16000 * 5) / 16000) * (1 + np.sin(np.arange(16000 * 5) / 800))).astype(np.float32)
            mini.media.push_audio_sample(tone); time.sleep(6)
            mini.disable_wobbling(); mini.start_head_tracking(weight=0.0)
            print("track+wobble done; was the motion natural? (observe)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
```

- [ ] **Step 2: Deploy and run the probes (hand over to the user for the steps that need someone present)**

Run: `voice/deploy/deploy-voice.sh` (this restarts the service). Then `ssh -4 pollen@reachy-mini.local 'sudo systemctl stop reachy-voice'`.

Then run each probe with `ssh -4 -t pollen@reachy-mini.local 'cd ~/reachy-voice && .venv/bin/python tools/body_probe.py <cmd> [arg]'`, in this order:
1. `wake`: record the duration.
2. `doa`: the user speaks ~1 m away from the left, then the front, then the right, about 5 s each. Record the angle ranges.
3. `antennas`: the user says which pose reads as "listening/perked" and which as "relaxed".
4. `emotion thinking`, then `emotion welcoming`, then `emotion goodbye`: record durations and the user's impression.
5. `noise`: compare the still and moving RMS. Robot only, no speech.
6. `track`: the user watches and says whether the motion looks natural.
7. `sleep`: record the duration.

Finally `ssh -4 pollen@reachy-mini.local 'sudo systemctl start reachy-voice'`.

If the moving p95 in `noise` exceeds 2× the still p95, the listening-stillness rule stands. Otherwise note in BODY_NOTES.md that gentle motion while listening would be acceptable (the plan keeps stillness either way).

- [ ] **Step 3: Record the findings and calibration constants**

`voice/BODY_NOTES.md`: one short section per probe, with the measured numbers and the user's observations.

`voice/reachy_voice/body_calibration.py` (fill each value from the measurements, and keep the comment stating how it was derived):
```python
"""Body calibration measured on the robot (see voice/BODY_NOTES.md)."""

# DoA angle (radians) reported when the speaker is straight in front of Reachy.
DOA_FRONT_RAD = <measured front angle, e.g. 1.5708>
# +1.0 or -1.0 so that yaw = DOA_SIGN * (angle - DOA_FRONT_RAD) turns toward the speaker
# (positive yaw = Reachy's left).
DOA_SIGN = <+1.0 or -1.0 from the left/right test>
# Largest body turn toward a voice (radians, ~50 degrees).
MAX_TURN_RAD = 0.87
# Antenna joint targets [right, left] in radians.
ANTENNA_LISTEN = <pose the user picked as perked, e.g. [0.3, 0.3]>
ANTENNA_REST = <pose the user picked as relaxed, e.g. [0.0, 0.0]>
```

Every `<...>` must be replaced with a number or list before committing. If a probe failed, record the failure in BODY_NOTES.md and use these values:
- `DOA_FRONT_RAD = 1.5708`
- `DOA_SIGN = 1.0`
- `ANTENNA_LISTEN = [0.3, 0.3]`
- `ANTENNA_REST = [0.0, 0.0]`

Also set `DOA_ENABLED = False` in the file and add it as a constant, so Task 4 skips turning.

- [ ] **Step 4: Commit**

```bash
git add voice/tools/body_probe.py voice/reachy_voice/body_calibration.py voice/BODY_NOTES.md
git commit -m "reachy_voice: body hardware probe and calibration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Settings and body policy

**Files:**
- Modify: `voice/reachy_voice/config.py`
- Modify: `voice/tests/test_rv_config.py`
- Create: `voice/reachy_voice/body_policy.py`
- Test: `voice/tests/test_rv_body_policy.py`

**Interfaces:**
- Consumes: `reachy_voice.body_calibration` (Task 1): `DOA_FRONT_RAD`, `DOA_SIGN`, `MAX_TURN_RAD`, and `DOA_ENABLED` if present (default `True` via `getattr`).
- Produces:
  - `Settings` fields `body_enabled: bool` (True), `idle_awake_s: float` (300.0), `expression_min_gap_s: float` (8.0) and `tracking_weight: float` (0.6), from env `BODY_ENABLED`, `IDLE_AWAKE_S`, `EXPRESSION_MIN_GAP_S` and `TRACKING_WEIGHT`.
  - `body_policy.EMOTIONS: tuple[str, ...]`
  - `body_policy.CUES: dict[str, str]`, with event keys `wake`, `handoff_start`, `handoff_ok`, `handoff_failed` and `session_end`
  - `body_policy.LOOK_DIRECTIONS: tuple[str, ...]`
  - `body_policy.doa_to_yaw(angle: float | None) -> float | None`
  - `body_policy.AwakeTimer(idle_awake_s)` with `.awake: bool` (starts False), `.on_wake(now)`, `.on_session_end(now)`, `.should_sleep(now) -> bool` and `.on_sleep()`
  - `body_policy.ExpressionGate(min_gap_s=8.0, user_quiet_s=0.5, utterance_grace_s=1.0)` with `.allow(now, last_user_voice: float | None, utterance_started_at: float | None) -> bool`

- [ ] **Step 1: Write the failing tests**

Add to `voice/tests/test_rv_config.py`:
```python
def test_body_settings_defaults_and_overrides():
    s = load_settings(KEYS)
    assert (s.body_enabled, s.idle_awake_s, s.expression_min_gap_s, s.tracking_weight) == (True, 300.0, 8.0, 0.6)
    s = load_settings({**KEYS, "BODY_ENABLED": "false", "IDLE_AWAKE_S": "60", "TRACKING_WEIGHT": "0.4"})
    assert (s.body_enabled, s.idle_awake_s, s.tracking_weight) == (False, 60.0, 0.4)
    assert load_settings({**KEYS, "BODY_ENABLED": "1"}).body_enabled is True


def test_bad_body_flag_is_rejected():
    with pytest.raises(ValueError, match="BODY_ENABLED"):
        load_settings({**KEYS, "BODY_ENABLED": "maybe"})
```

`voice/tests/test_rv_body_policy.py`:
```python
import math

from reachy_voice import body_calibration as cal
from reachy_voice.body_policy import CUES, EMOTIONS, LOOK_DIRECTIONS, AwakeTimer, ExpressionGate, doa_to_yaw


def test_cues_use_known_emotions():
    assert set(CUES) == {"wake", "handoff_start", "handoff_ok", "handoff_failed", "session_end"}
    assert CUES["handoff_start"] == "thinking" and CUES["wake"] == "welcoming"
    assert all(v in EMOTIONS for v in CUES.values())
    assert "random" not in EMOTIONS and "at_person" in LOOK_DIRECTIONS


def test_doa_to_yaw_front_is_zero_and_clamped():
    assert doa_to_yaw(None) is None
    if getattr(cal, "DOA_ENABLED", True):
        assert abs(doa_to_yaw(cal.DOA_FRONT_RAD)) < 1e-9
        far = doa_to_yaw(cal.DOA_FRONT_RAD + cal.DOA_SIGN * math.pi)
        assert abs(far) == cal.MAX_TURN_RAD
        assert abs(doa_to_yaw(cal.DOA_FRONT_RAD + cal.DOA_SIGN * 0.3) - 0.3) < 1e-9
    else:
        assert doa_to_yaw(1.0) is None


def test_doa_to_yaw_wraps_around():
    if getattr(cal, "DOA_ENABLED", True):
        a = cal.DOA_FRONT_RAD + cal.DOA_SIGN * 0.2
        assert abs(doa_to_yaw(a + 2 * math.pi) - 0.2) < 1e-9


def test_awake_timer_lifecycle():
    t = AwakeTimer(idle_awake_s=300)
    assert not t.awake and not t.should_sleep(1000)
    t.on_wake(0)
    assert t.awake and not t.should_sleep(10_000)   # in a session: never sleeps
    t.on_session_end(100)
    assert not t.should_sleep(399) and t.should_sleep(400)
    t.on_wake(390)                                   # wake word while awake idle
    assert not t.should_sleep(1000)
    t.on_session_end(1000)
    t.on_sleep()
    assert not t.awake and not t.should_sleep(5000)


def test_gate_spacing_user_speech_and_utterance_grace():
    g = ExpressionGate(min_gap_s=8, user_quiet_s=0.5, utterance_grace_s=1.0)
    assert g.allow(now=10, last_user_voice=None, utterance_started_at=None)
    assert not g.allow(now=15, last_user_voice=None, utterance_started_at=None)       # within 8 s
    assert not g.allow(now=20, last_user_voice=19.8, utterance_started_at=None)       # person talking
    assert not g.allow(now=20, last_user_voice=None, utterance_started_at=19.5)       # utterance just began
    assert g.allow(now=20, last_user_voice=19.0, utterance_started_at=18.0)
    assert not g.allow(now=21, last_user_voice=None, utterance_started_at=None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_config.py tests/test_rv_body_policy.py`
Expected: failures. The config tests fail with `AttributeError: ... 'body_enabled'`, and the policy tests with `ModuleNotFoundError: reachy_voice.body_policy`.

- [ ] **Step 3: Implement**

In `voice/reachy_voice/config.py`, add these fields to `Settings`, after `log_dir` and before the key fields:
```python
    body_enabled: bool = True
    idle_awake_s: float = 300.0
    expression_min_gap_s: float = 8.0
    tracking_weight: float = 0.6
```
In `load_settings`, add a helper next to `number`:
```python
    def flag(name: str, default: bool) -> bool:
        value = (env.get(name) or "").strip().lower()
        if not value:
            return default
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{name} must be true or false, got {value!r}")
```
and pass these in the `Settings(...)` call:
```python
        body_enabled=flag("BODY_ENABLED", d.body_enabled),
        idle_awake_s=number("IDLE_AWAKE_S", d.idle_awake_s),
        expression_min_gap_s=number("EXPRESSION_MIN_GAP_S", d.expression_min_gap_s),
        tracking_weight=number("TRACKING_WEIGHT", d.tracking_weight),
```

`voice/reachy_voice/body_policy.py`:
```python
"""Pure decisions for Reachy's body: when to express, when to sleep, where to turn."""

import math
from dataclasses import dataclass

from reachy_voice import body_calibration as cal

# Pollen's emotion intents (reachy_mini_conversation_app.tools.play_emotion.EMOTION_INTENTS),
# minus "random", "dying" and "go_away", which don't suit a household assistant.
EMOTIONS: tuple[str, ...] = (
    "happy", "excited", "loving", "grateful", "success", "thinking", "attentive", "confused",
    "uncertain", "sad", "downcast", "lonely", "angry", "irritated", "displeased", "disgusted",
    "scared", "anxious", "surprised", "amazed", "calming", "relief", "impatient", "embarrassed",
    "bored", "tired", "sleepy", "yes", "yes_understanding", "no", "no_sad", "no_excited",
    "no_firm", "welcoming", "greeting", "goodbye", "helpful", "dance", "electric",
)

CUES: dict[str, str] = {
    "wake": "welcoming",
    "handoff_start": "thinking",
    "handoff_ok": "yes_understanding",
    "handoff_failed": "uncertain",
    "session_end": "goodbye",
}

LOOK_DIRECTIONS: tuple[str, ...] = ("left", "right", "up", "down", "front", "at_person")


def doa_to_yaw(angle: float | None) -> float | None:
    """Body yaw (radians, positive = left) that turns Reachy toward a voice, or None."""
    if angle is None or not getattr(cal, "DOA_ENABLED", True):
        return None
    delta = cal.DOA_SIGN * (angle - cal.DOA_FRONT_RAD)
    delta = (delta + math.pi) % (2 * math.pi) - math.pi  # wrap to [-pi, pi)
    return max(-cal.MAX_TURN_RAD, min(cal.MAX_TURN_RAD, delta))


@dataclass
class AwakeTimer:
    """Awake while in a conversation and for idle_awake_s after it; then sleep."""

    idle_awake_s: float = 300.0
    awake: bool = False
    _idle_since: float | None = None

    def on_wake(self, now: float) -> None:
        self.awake, self._idle_since = True, None

    def on_session_end(self, now: float) -> None:
        self._idle_since = now

    def should_sleep(self, now: float) -> bool:
        return self.awake and self._idle_since is not None and now - self._idle_since >= self.idle_awake_s

    def on_sleep(self) -> None:
        self.awake, self._idle_since = False, None


@dataclass
class ExpressionGate:
    """One rate limiter for automatic cues and model-chosen expressions alike."""

    min_gap_s: float = 8.0
    user_quiet_s: float = 0.5
    utterance_grace_s: float = 1.0
    _last: float | None = None

    def allow(self, now: float, last_user_voice: float | None, utterance_started_at: float | None) -> bool:
        if self._last is not None and now - self._last < self.min_gap_s:
            return False
        if last_user_voice is not None and now - last_user_voice < self.user_quiet_s:
            return False  # never move while the person is talking
        if utterance_started_at is not None and now - utterance_started_at < self.utterance_grace_s:
            return False
        self._last = now
        return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: everything passes with no warnings.

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/config.py voice/tests/test_rv_config.py voice/reachy_voice/body_policy.py voice/tests/test_rv_body_policy.py
git commit -m "reachy_voice: body settings, awake timer, expression gate and DoA mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Expression picker (OpenAI)

**Files:**
- Create: `voice/reachy_voice/expression_picker.py`
- Test: `voice/tests/test_rv_expression_picker.py`

**Interfaces:**
- Consumes: `body_policy.EMOTIONS` (Task 2).
- Produces: `reachy_voice.expression_picker.ExpressionPicker(api_key: str, model: str = "gpt-5.4-nano", transport=None, timeout_s: float = 3.0)` with `async .pick(text: str) -> str | None` and `async .aclose()`.

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_expression_picker.py`:
```python
import asyncio
import json

import httpx
import pytest

from reachy_voice.expression_picker import ExpressionPicker


def picker(handler):
    return ExpressionPicker("k", transport=httpx.MockTransport(handler))


def reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_picks_a_known_emotion_and_sends_the_line():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return reply(" Happy \n")

    assert asyncio.run(picker(handler).pick("That's wonderful news!")) == "happy"
    assert seen["auth"] == "Bearer k" and seen["body"]["model"] == "gpt-5.4-nano"
    assert "That's wonderful news!" in seen["body"]["messages"][-1]["content"]


@pytest.mark.parametrize("content", ["none", "ecstatic", "", "I think happy and sad"])
def test_none_or_unknown_gives_none(content):
    assert asyncio.run(picker(lambda r: reply(content)).pick("hello")) is None


def test_errors_and_blank_text_give_none():
    assert asyncio.run(picker(lambda r: httpx.Response(500)).pick("hello")) is None

    def boom(request):
        raise httpx.ConnectTimeout("slow")

    assert asyncio.run(picker(boom).pick("hello")) is None
    calls = []
    assert asyncio.run(picker(lambda r: calls.append(1) or reply("happy")).pick("   ")) is None
    assert calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_expression_picker.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.expression_picker'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/expression_picker.py`:
```python
"""For gpt-live-1 (no tool calling): pick an emotion for what Reachy just said, off the critical path."""

import httpx

from reachy_voice.body_policy import EMOTIONS

_PROMPT = (
    "You choose a body expression for a small friendly household robot, based on the line it just "
    "said. Reply with exactly one word from this list, or 'none' if no expression fits or the line "
    "is neutral (prefer 'none' most of the time): " + ", ".join(EMOTIONS)
)


class ExpressionPicker:
    def __init__(self, api_key: str, model: str = "gpt-5.4-nano", transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 3.0) -> None:
        self._key, self._model = api_key, model
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_s)

    async def pick(self, text: str) -> str | None:
        if not text.strip():
            return None
        try:
            response = await self._client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "messages": [
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": text.strip()[:500]},
                ]},
            )
            response.raise_for_status()
            word = str(response.json()["choices"][0]["message"]["content"]).strip().lower()
        except Exception:  # noqa: BLE001 - an expression is optional; never fail the conversation
            return None
        return word if word in EMOTIONS else None

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_expression_picker.py`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/expression_picker.py voice/tests/test_rv_expression_picker.py
git commit -m "reachy_voice: expression picker for gpt-live-1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Body controller

**Files:**
- Create: `voice/reachy_voice/body.py`
- Test: `voice/tests/test_rv_body.py`

**Interfaces:**
- Consumes:
  - `body_policy.doa_to_yaw` (Task 2)
  - `body_calibration.ANTENNA_LISTEN` and `ANTENNA_REST` (Task 1)
  - `JsonlLog`
- Produces:
  - `reachy_voice.body.Body(mini, log, tracking_weight=0.6, library_loader=None, resolver=None, head_pose=None)`. Its async methods never raise:
    - `wake(doa: float | None)`
    - `listening()`
    - `speaking()`
    - `express(intent: str) -> bool` (True if a move played)
    - `look(direction: str)`
    - `rest()`
    - `sleep()`
    - `shutdown()`
  - `reachy_voice.body.NullBody()`, with the same methods as no-ops. `express` returns False.
  - Injection points, so Mac tests don't need the SDK:
    - `library_loader() -> object` with `.list_moves()` and `.get(name)`. The default loads `RecordedMoves(...)`.
    - `resolver(intent, names) -> str | None`. The default is Pollen's `resolve_emotion_name`, or exact match.
    - `head_pose(yaw_deg=0, pitch_deg=0) -> pose`. The default is `reachy_mini.utils.create_head_pose`.

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_body.py`:
```python
import asyncio
import json

from reachy_voice.body import Body, NullBody
from reachy_voice.body_calibration import ANTENNA_LISTEN, ANTENNA_REST
from reachy_voice.log import JsonlLog


class FakeMini:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def _rec(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def enable_motors(self): self._rec("enable_motors")
    def disable_motors(self): self._rec("disable_motors")
    def wake_up(self): self._rec("wake_up")
    def goto_sleep(self): self._rec("goto_sleep")
    def goto_target(self, **kw): self._rec("goto_target", **kw)
    def start_head_tracking(self, weight=1.0): self._rec("start_head_tracking", weight=weight)
    def stop_head_tracking(self): self._rec("stop_head_tracking")
    def enable_wobbling(self): self._rec("enable_wobbling")
    def disable_wobbling(self): self._rec("disable_wobbling")

    async def async_play_move(self, move, sound=True):
        self._rec("async_play_move", move, sound=sound)


class FakeLibrary:
    def list_moves(self): return ["thoughtful1", "welcoming2"]
    def get(self, name): return f"move:{name}"


def make(tmp_path, mini=None, loader=FakeLibrary, resolver=None):
    log_path = tmp_path / "b.jsonl"
    body = Body(mini or FakeMini(), JsonlLog(str(log_path)), tracking_weight=0.6, library_loader=loader,
                resolver=resolver or (lambda intent, names: {"thinking": "thoughtful1", "welcoming": "welcoming2"}.get(intent)),
                head_pose=lambda yaw_deg=0, pitch_deg=0: ("pose", yaw_deg, pitch_deg))
    return body, log_path


def names(mini):
    return [c[0] for c in mini.calls]


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_wake_enables_motors_wakes_turns_and_pauses_tracking(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.wake(doa=None))
    assert names(mini)[:2] == ["enable_motors", "wake_up"]
    assert ("start_head_tracking", (), {"weight": 0.0}) in mini.calls


def test_speaking_and_listening_switch_tracking_wobble_and_antennas(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.speaking())
    asyncio.run(body.listening())
    assert ("start_head_tracking", (), {"weight": 0.6}) in mini.calls
    assert "enable_wobbling" in names(mini) and names(mini)[-1] in ("goto_target", "disable_wobbling", "start_head_tracking")
    antenna_targets = [c[2].get("antennas") for c in mini.calls if c[0] == "goto_target"]
    assert list(ANTENNA_REST) in antenna_targets and list(ANTENNA_LISTEN) in antenna_targets


def test_express_plays_resolved_move_silently_and_restores_mode(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)

    async def go():
        await body.speaking()
        mini.calls.clear()
        return await body.express("thinking")
    assert asyncio.run(go()) is True
    assert ("async_play_move", ("move:thoughtful1",), {"sound": False}) in mini.calls
    assert names(mini).index("disable_wobbling") < names(mini).index("async_play_move")
    assert names(mini)[-2:] == ["start_head_tracking", "enable_wobbling"] or "enable_wobbling" in names(mini)[-3:]


def test_unknown_emotion_or_missing_library_skips_but_body_still_moves(tmp_path):
    mini = FakeMini()
    body, path = make(tmp_path, mini)
    assert asyncio.run(body.express("ecstatic")) is False

    def broken_loader():
        raise OSError("dataset missing")
    mini2 = FakeMini()
    body2, path2 = make(tmp_path / "x", mini2, loader=broken_loader)
    (tmp_path / "x").mkdir(exist_ok=True)
    assert asyncio.run(body2.express("thinking")) is False
    assert asyncio.run(body2.express("welcoming")) is False      # disabled after first failure
    asyncio.run(body2.speaking())
    assert "enable_wobbling" in names(mini2)
    assert sum(1 for e in events(path2) if e["event"] == "body_error" and e["action"] == "load_library") == 1


def test_sdk_errors_are_swallowed_and_logged(tmp_path):
    mini = FakeMini(fail={"wake_up", "enable_wobbling"})
    body, path = make(tmp_path, mini)
    asyncio.run(body.wake(doa=0.0))
    asyncio.run(body.speaking())
    errs = [e for e in events(path) if e["event"] == "body_error"]
    assert {e["action"] for e in errs} >= {"wake", "speaking"}


def test_shutdown_disables_motors_even_if_sleep_fails(tmp_path):
    mini = FakeMini(fail={"goto_sleep"})
    body, _ = make(tmp_path, mini)
    asyncio.run(body.shutdown())
    assert "disable_motors" in names(mini)


def test_look_directions_and_null_body(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.look("left"))
    assert ("goto_target", (), {"head": ("pose", 25, 0), "duration": 0.6, "body_yaw": None}) in mini.calls
    asyncio.run(body.look("at_person"))
    assert ("start_head_tracking", (), {"weight": 0.6}) in mini.calls
    nb = NullBody()
    asyncio.run(nb.wake(None)); asyncio.run(nb.speaking()); asyncio.run(nb.shutdown())
    assert asyncio.run(nb.express("happy")) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_body.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.body'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/body.py`:
```python
"""The only code that moves Reachy. Blocking SDK calls run in a worker thread behind one lock;
every public method logs and swallows errors, so the body can never break the voice."""

import asyncio

from reachy_voice.body_calibration import ANTENNA_LISTEN, ANTENNA_REST
from reachy_voice.body_policy import doa_to_yaw
from reachy_voice.log import JsonlLog

LIBRARY = "pollen-robotics/reachy-mini-emotions-library"
_LOOK = {"left": (25, 0), "right": (-25, 0), "up": (0, -15), "down": (0, 15), "front": (0, 0)}


def _default_loader():
    from reachy_mini.motion.recorded_move import RecordedMoves

    return RecordedMoves(LIBRARY)


def _default_resolver(intent: str, names: list[str]) -> str | None:
    try:
        from reachy_mini_conversation_app.tools.play_emotion import resolve_emotion_name

        return resolve_emotion_name(intent, names)
    except ImportError:
        return intent if intent in names else None


def _default_head_pose(yaw_deg: float = 0, pitch_deg: float = 0):
    from reachy_mini.utils import create_head_pose

    return create_head_pose(yaw=yaw_deg, pitch=pitch_deg, degrees=True)


class Body:
    def __init__(self, mini, log: JsonlLog, tracking_weight: float = 0.6, library_loader=None, resolver=None,
                 head_pose=None) -> None:
        self._mini, self._log, self._weight = mini, log, tracking_weight
        self._loader = library_loader or _default_loader
        self._resolve = resolver or _default_resolver
        self._pose = head_pose or _default_head_pose
        self._lock = asyncio.Lock()
        self._library = None
        self._library_failed = False
        self._mode = "listening"

    async def _run(self, action: str, steps) -> bool:
        """Run blocking SDK steps in a thread under the motion lock. Never raises."""
        try:
            async with self._lock:
                for step in steps:
                    await asyncio.to_thread(step)
            return True
        except Exception as exc:  # noqa: BLE001 - motion is best-effort
            self._log.write("body_error", action=action, error=repr(exc))
            return False

    async def wake(self, doa: float | None) -> None:
        m, yaw = self._mini, doa_to_yaw(doa)
        steps = [m.enable_motors, m.wake_up]
        if yaw is not None:
            steps.append(lambda: m.goto_target(body_yaw=yaw, duration=0.8))
        steps.append(lambda: m.start_head_tracking(weight=0.0))
        if await self._run("wake", steps):
            self._log.write("body_event", action="wake", yaw=yaw)
        self._mode = "listening"

    async def listening(self) -> None:
        m = self._mini
        self._mode = "listening"
        await self._run("listening", [
            lambda: m.start_head_tracking(weight=0.0),
            m.disable_wobbling,
            lambda: m.goto_target(antennas=list(ANTENNA_LISTEN), duration=0.3, body_yaw=None),
        ])

    async def speaking(self) -> None:
        m = self._mini
        self._mode = "speaking"
        await self._run("speaking", [
            lambda: m.goto_target(antennas=list(ANTENNA_REST), duration=0.3, body_yaw=None),
            lambda: m.start_head_tracking(weight=self._weight),
            m.enable_wobbling,
        ])

    async def _ensure_library(self):
        if self._library is None and not self._library_failed:
            try:
                self._library = await asyncio.to_thread(self._loader)
            except Exception as exc:  # noqa: BLE001
                self._library_failed = True
                self._log.write("body_error", action="load_library", error=repr(exc))
        return self._library

    async def express(self, intent: str) -> bool:
        try:
            library = await self._ensure_library()
            if library is None:
                return False
            name = self._resolve(intent, library.list_moves())
            if name is None:
                self._log.write("expression_unresolved", intent=intent)
                return False
            m = self._mini
            async with self._lock:
                await asyncio.to_thread(lambda: m.start_head_tracking(weight=0.0))
                await asyncio.to_thread(m.disable_wobbling)
                await m.async_play_move(library.get(name), sound=False)
            self._log.write("body_event", action="express", intent=intent, move=name)
        except Exception as exc:  # noqa: BLE001
            self._log.write("body_error", action="express", error=repr(exc))
            return False
        finally:
            await (self.speaking() if self._mode == "speaking" else self.listening())
        return True

    async def look(self, direction: str) -> None:
        m = self._mini
        if direction == "at_person":
            await self._run("look", [lambda: m.start_head_tracking(weight=self._weight)])
        elif direction in _LOOK:
            yaw, pitch = _LOOK[direction]
            pose = self._pose(yaw_deg=yaw, pitch_deg=pitch)
            await self._run("look", [lambda: m.goto_target(head=pose, duration=0.6, body_yaw=None)])

    async def rest(self) -> None:
        m = self._mini
        await self._run("rest", [
            m.stop_head_tracking,
            m.disable_wobbling,
            lambda: m.goto_target(head=self._pose(), antennas=list(ANTENNA_REST), duration=1.0, body_yaw=0.0),
        ])

    async def sleep(self) -> None:
        m = self._mini
        await self._run("sleep_prepare", [m.stop_head_tracking, m.disable_wobbling])
        await self._run("sleep", [m.goto_sleep])
        await self._run("motors_off", [m.disable_motors])
        self._log.write("body_event", action="sleep")

    async def shutdown(self) -> None:
        await self.sleep()  # each step is independent, so motors go off even if goto_sleep fails


class NullBody:
    """BODY_ENABLED=false: voice-only, exactly as before."""

    async def wake(self, doa): pass
    async def listening(self): pass
    async def speaking(self): pass
    async def express(self, intent): return False
    async def look(self, direction): pass
    async def rest(self): pass
    async def sleep(self): pass
    async def shutdown(self): pass
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_body.py`
Expected: `7 passed`.

If an assertion about exact call ordering fails only because of an equivalent harmless reordering inside one method, make the assertion express the requirement precisely and explain it in the report. Requirements:
- wobbling is off before the emotion plays
- the previous mode is restored after it
- motors are disabled on shutdown

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/body.py voice/tests/test_rv_body.py
git commit -m "reachy_voice: Body controller (wake, track, wobble, express, sleep)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Gemini body tools

**Files:**
- Modify: `voice/reachy_voice/engines/base.py` (add a callback with a default)
- Modify: `voice/reachy_voice/engines/gemini.py`
- Modify: `voice/reachy_voice/persona.py`
- Test: `voice/tests/test_rv_gemini.py` (add tests)

**Interfaces:**
- Consumes: `body_policy.EMOTIONS` and `LOOK_DIRECTIONS` (Task 2).
- Produces:
  - `EngineCallbacks.on_body_tool: Callable[[str, dict], None]`, with a default no-op (`field(default=lambda name, args: None)`) so existing constructions keep working.
  - `persona.BODY_TOOLS: list[dict]`, the two tool specs `{name, description, parameters}` for `express` and `look`.
  - `persona.PERSONA` gains a sentence on expressing sparingly.

- [ ] **Step 1: Write the failing tests**

Add to `voice/tests/test_rv_gemini.py`:
```python
def test_config_declares_body_tools_non_blocking():
    cfg = GeminiLiveEngine("m", "Kore", connect=FakeConnect(FakeSession([]))).config()
    decls = {d.name: d for d in cfg.tools[0].function_declarations}
    assert set(decls) == {"ask_home_agent", "express", "look"}
    assert all(d.behavior == types.Behavior.NON_BLOCKING for d in decls.values())


def test_body_tool_call_is_reported_and_answered_silently():
    fc = NS(id="b1", name="express", args={"emotion": "happy"})
    session = FakeSession([[msg(tool_call=NS(function_calls=[fc]))]])
    body_calls = []
    got, cb = recorder()
    cb.on_body_tool = lambda name, args: body_calls.append((name, args))
    run(GeminiLiveEngine("m", "Kore", connect=FakeConnect(session)), cb)
    assert body_calls == [("express", {"emotion": "happy"})]
    assert got["delegations"] == []
    r = session.tool_responses[0]
    assert r.id == "b1" and r.response == {"ok": True}
    assert r.scheduling == types.FunctionResponseScheduling.SILENT
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_gemini.py`
Expected: the 2 new tests fail.

- [ ] **Step 3: Implement**

`voice/reachy_voice/engines/base.py`: add `from dataclasses import dataclass, field`, and add this as the last `EngineCallbacks` field:
```python
    on_body_tool: Callable[[str, dict], None] = field(default=lambda name, args: None)
```

`voice/reachy_voice/persona.py`: append to `PERSONA`, before its closing `"""`:
```
You have a small expressive body. Use the express tool now and then, at natural moments (a happy
moment, thinking hard, saying yes), never on every reply. Use look only when it adds something.
```
and add:
```python
from reachy_voice.body_policy import EMOTIONS, LOOK_DIRECTIONS

BODY_TOOLS = [
    {
        "name": "express",
        "description": "Show an emotion with your body for a moment. Use sparingly.",
        "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "enum": list(EMOTIONS)}},
                       "required": ["emotion"]},
    },
    {
        "name": "look",
        "description": "Turn your head: left, right, up, down, front, or back at the person.",
        "parameters": {"type": "object", "properties": {"direction": {"type": "string", "enum": list(LOOK_DIRECTIONS)}},
                       "required": ["direction"]},
    },
]
```

`voice/reachy_voice/engines/gemini.py`:
- In `config()`, append one `types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"], behavior=types.Behavior.NON_BLOCKING)` for each `t` in `BODY_TOOLS` to the same `function_declarations` list.
- In `_handle`'s tool-call loop, before the delegation code, add:
```python
                if fc.name in BODY_TOOL_NAMES:
                    cb.on_body_tool(fc.name, dict(fc.args or {}))
                    asyncio.get_running_loop().create_task(self._ack_body_tool(fc.id, fc.name))
                    continue
```
- Add the module constant `BODY_TOOL_NAMES = {t["name"] for t in BODY_TOOLS}`, and add this method:
```python
    async def _ack_body_tool(self, call_id: str, name: str) -> None:
        try:
            await self._session.send_tool_response(function_responses=[types.FunctionResponse(
                id=call_id, name=name, response={"ok": True}, scheduling=types.FunctionResponseScheduling.SILENT)])
        except Exception as exc:  # noqa: BLE001
            if self._cb:
                self._cb.on_error(f"gemini body tool ack failed: {exc!r}")
```
- Import `BODY_TOOLS` from `reachy_voice.persona`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: everything passes, including the existing Gemini and OpenAI tests.

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/engines/base.py voice/reachy_voice/engines/gemini.py voice/reachy_voice/persona.py voice/tests/test_rv_gemini.py
git commit -m "reachy_voice: Gemini express/look body tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Session body hooks

**Files:**
- Modify: `voice/reachy_voice/session.py`
- Test: `voice/tests/test_rv_session.py` (add tests)

**Interfaces:**
- Consumes:
  - `ExpressionGate` and `CUES` (Task 2)
  - the `Body`/`NullBody` interface (Task 4)
  - `ExpressionPicker.pick` (Task 3)
  - `EngineCallbacks.on_body_tool` (Task 5)
- Produces: `VoiceSession(..., body=None, gate=None, picker=None)` as new keyword-only params with these defaults:
  - `body=None` means `NullBody()`
  - `gate=None` means `ExpressionGate()`
  - `picker=None` means no picker

  Behaviour:
  - On each tick, a change in `self._out.is_speaking(now)` spawns `body.speaking()` or `body.listening()`.
  - On a speaking → not-speaking transition, if `picker` is set, the session spawns `picker.pick(<robot text since that utterance started>)`. A non-None result goes through the gate, then `body.express`.
  - Hand-off start, ok and failed each try their cue through the gate.
  - The `express` body tool goes through the gate; `look` calls `body.look` directly.
  - All body work runs in tracked tasks. Body tasks are not cancelled at session end; they finish on their own.

- [ ] **Step 1: Write the failing tests**

Add to `voice/tests/test_rv_session.py`:
```python
from reachy_voice.body_policy import ExpressionGate


class FakeBody:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def _rec(self, *call):
        self.calls.append(call)
        if self.fail:
            raise RuntimeError("motor fault")

    async def listening(self): await self._rec("listening")
    async def speaking(self): await self._rec("speaking")
    async def express(self, intent): await self._rec("express", intent); return True
    async def look(self, direction): await self._rec("look", direction)


class FakePicker:
    def __init__(self, answer):
        self.answer, self.texts = answer, []

    async def pick(self, text):
        self.texts.append(text)
        return self.answer


def make_body_session(engine, audio, hermes, tmp_path, body, picker=None, idle=0.3, gap=0.0):
    log = JsonlLog(str(tmp_path / "v.jsonl"))
    gate = ExpressionGate(min_gap_s=gap, user_quiet_s=0.0, utterance_grace_s=0.0)
    s = VoiceSession(engine, audio, hermes, SessionPolicy(idle, 5.0, 5.0), 0.015, log, "sess-1", tick_s=0.01,
                     body=body, gate=gate, picker=picker)
    return s, tmp_path / "v.jsonl"


def test_speaking_transitions_drive_body_and_picker(tmp_path):
    def speak(engine):
        engine.cb.on_robot_text("That's wonderful news!")
        engine.cb.on_audio(VOICED, 0.0)
    body, picker = FakeBody(), FakePicker("happy")
    s, _ = make_body_session(FakeEngine(on_start=speak), FakeAudio(), FakeHermes(), tmp_path, body, picker)
    asyncio.run(s.run())
    kinds = [c[0] for c in body.calls]
    assert "speaking" in kinds and "listening" in kinds[kinds.index("speaking"):]
    assert picker.texts == ["That's wonderful news!"] and ("express", "happy") in body.calls


def test_handoff_cues_and_gate_drops_extras(tmp_path):
    body = FakeBody()
    s, path = make_body_session(FakeEngine(on_start=delegate), FakeAudio(), FakeHermes(delay=0.05), tmp_path, body,
                                gap=60.0)
    asyncio.run(s.run())
    expresses = [c for c in body.calls if c[0] == "express"]
    assert expresses == [("express", "thinking")]                  # handoff_ok cue dropped by the 60 s gap
    assert any(e["event"] == "expression_dropped" for e in events(path))


def test_body_tools_from_engine(tmp_path):
    def tools(engine):
        engine.cb.on_body_tool("express", {"emotion": "happy"})
        engine.cb.on_body_tool("look", {"direction": "left"})
        engine.cb.on_body_tool("express", {"emotion": "not-a-thing"})
    body = FakeBody()
    s, _ = make_body_session(FakeEngine(on_start=tools), FakeAudio(), FakeHermes(), tmp_path, body)
    asyncio.run(s.run())
    assert ("express", "happy") in body.calls and ("look", "left") in body.calls
    assert ("express", "not-a-thing") not in body.calls


def test_failing_body_never_breaks_the_conversation(tmp_path):
    def speak(engine):
        engine.cb.on_audio(VOICED, 0.0)
        delegate(engine)
    engine = FakeEngine(on_start=speak)
    s, _ = make_body_session(engine, FakeAudio(), FakeHermes(), tmp_path, FakeBody(fail=True))
    assert asyncio.run(s.run()) == "idle"
    assert engine.delivered == [("c1", "Milk and eggs.")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_session.py`
Expected: the new tests fail with `TypeError: ... unexpected keyword argument 'body'`.

- [ ] **Step 3: Implement**

In `voice/reachy_voice/session.py`:
- Add the imports `from reachy_voice.body import NullBody` and `from reachy_voice.body_policy import CUES, EMOTIONS, ExpressionGate`.
- Add the keyword-only constructor params `body=None, gate=None, picker=None`, and set:
```python
        self._body = body or NullBody()
        self._gate = gate or ExpressionGate()
        self._picker = picker
        self._body_tasks: set[asyncio.Task] = set()
        self._was_speaking = False
        self._utterance_started: float | None = None
        self._utterance_text: list[str] = []
```
- Add these helpers:
```python
    def _spawn_body(self, coro, what: str) -> None:
        async def guarded():
            try:
                await coro
            except Exception as exc:  # noqa: BLE001 - the body never breaks the voice
                self._log.write("body_error", action=what, error=repr(exc))
        task = asyncio.create_task(guarded())
        self._body_tasks.add(task)
        task.add_done_callback(self._body_tasks.discard)

    def _try_express(self, intent: str, source: str) -> None:
        if intent not in EMOTIONS:
            self._log.write("expression_dropped", intent=intent, source=source, reason="unknown")
            return
        if not self._gate.allow(self._clock(), self._user.last_voice, self._utterance_started):
            self._log.write("expression_dropped", intent=intent, source=source, reason="gate")
            return
        self._log.write("expression", intent=intent, source=source)
        self._spawn_body(self._body.express(intent), "express")

    async def _pick_and_express(self, text: str) -> None:
        intent = await self._picker.pick(text)
        if intent:
            self._try_express(intent, "picker")
```
- In `run()`'s tick loop, before the policy check, add:
```python
                speaking = self._out.is_speaking(now)
                if speaking != self._was_speaking:
                    self._was_speaking = speaking
                    if speaking:
                        self._utterance_started = now  # keep text already received: it can precede the audio
                        self._spawn_body(self._body.speaking(), "speaking")
                    else:
                        self._spawn_body(self._body.listening(), "listening")
                        text = "".join(self._utterance_text).strip()
                        self._utterance_started, self._utterance_text = None, []
                        if self._picker is not None and text:
                            self._spawn_body(self._pick_and_express(text), "pick")
```
  Replace the `on_robot_text` callback with one that both logs (as now) and appends the text to `self._utterance_text`. The buffer is cleared only when an utterance ends, never when one starts, because an utterance's text can arrive slightly before its audio.
- Add `on_body_tool=self._on_body_tool` to `EngineCallbacks(...)`, with:
```python
    def _on_body_tool(self, name: str, args: dict) -> None:
        if self._closing:
            return
        if name == "express":
            self._try_express(str(args.get("emotion", "")), "model")
        elif name == "look":
            self._spawn_body(self._body.look(str(args.get("direction", "front"))), "look")
```
- In `_on_delegation`, after logging the delegation, call `self._try_express(CUES["handoff_start"], "cue")`.
- In `_handle_delegation`, after the result is known, call `self._try_express(CUES["handoff_ok" if ok else "handoff_failed"], "cue")`.
- In `run()`'s `finally`, after the engine close, wait for in-flight body tasks so motion isn't cut mid-move: `await asyncio.gather(*self._body_tasks, return_exceptions=True)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: everything passes, with no warnings. The earlier session tests are unchanged and use the `NullBody` default.

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/session.py voice/tests/test_rv_session.py
git commit -m "reachy_voice: session drives the body (speaking/listening, cues, picker, body tools)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Main lifecycle, deploy and on-robot acceptance

**Files:**
- Modify: `voice/reachy_voice/main.py`
- Modify: `voice/reachy_voice/robot_audio.py` (add `doa()`)
- Modify: `voice/README.md`

**Interfaces:**
- Consumes:
  - `Body` and `NullBody` (Task 4)
  - `AwakeTimer`, `ExpressionGate` and `CUES` (Task 2)
  - `ExpressionPicker` (Task 3)
  - `VoiceSession(..., body=, gate=, picker=)` (Task 6)
  - `Settings.body_enabled`, `idle_awake_s`, `expression_min_gap_s` and `tracking_weight` (Task 2)
- Produces: the running service with body language.

- [ ] **Step 1: Implement**

`voice/reachy_voice/robot_audio.py`: add
```python
    def doa(self) -> float | None:
        """Direction of arrival (radians) if the mic array heard speech, else None."""
        try:
            result = self._media.get_DoA()
        except Exception:  # noqa: BLE001
            return None
        if not result:
            return None
        angle, speech = result
        return float(angle) if speech else None
```

`voice/reachy_voice/main.py`, changes:
- Build the body once, inside the `ReachyMini()` context:
```python
body = (Body(mini, log, tracking_weight=settings.tracking_weight) if settings.body_enabled else NullBody())
timer = AwakeTimer(settings.idle_awake_s)
gate = ExpressionGate(min_gap_s=settings.expression_min_gap_s)
picker = ExpressionPicker(settings.openai_api_key) if settings.openai_api_key else None
```
  The same `gate` is shared across sessions, so the 8 s spacing holds across a session boundary.
- At startup, call `await body.shutdown()` so the robot starts asleep with motors off, regardless of how it was left.
- While waiting for the wake word, check `timer.should_sleep(time.monotonic())` about once a second. When it's true, run `await body.sleep()`, then `timer.on_sleep()`, then `log.write("body_sleep")`. Use a monotonic `next_check` comparison inside the `async for frame` loop; don't add another task.
- On the wake word:
```python
doa = audio.doa()
if not timer.awake:
    await body.wake(doa)
    timer.on_wake(time.monotonic())
    if gate.allow(time.monotonic(), None, None):
        asyncio.get_running_loop().create_task(body.express(CUES["wake"]))
else:
    timer.on_wake(time.monotonic())
```
- Pass `body=body, gate=gate` to `VoiceSession` (via `_run_session`). Pass `picker=picker` only when the engine is `openai`.
- After a session, if `reason != "error"` and `gate.allow(time.monotonic(), None, None)`, run `await body.express(CUES["session_end"])`. Then run `await body.rest()` and `timer.on_session_end(time.monotonic())`.
- In the outermost shutdown `finally`, before `audio.stop()`, run `await asyncio.wait_for(body.shutdown(), timeout=10)` inside try/except, so the service never stops with the head up and motors on. Then call `await picker.aclose()` if a picker exists.

`voice/README.md`: add a "Body language" section covering:
- the states: sleeping, awake in conversation, awake idle for `IDLE_AWAKE_S`, then sleep
- the settings: `BODY_ENABLED`, `IDLE_AWAKE_S`, `EXPRESSION_MIN_GAP_S`, `TRACKING_WEIGHT`
- that `BODY_ENABLED=false` in `~/reachy-voice/voice.env` gives voice-only
- that calibration lives in `reachy_voice/body_calibration.py` (see `BODY_NOTES.md`)

- [ ] **Step 2: Verify and deploy**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m py_compile reachy_voice/main.py reachy_voice/robot_audio.py && ../.venv/bin/python -m pytest -q`
Expected: compiles; all tests pass.

Run: `voice/deploy/deploy-voice.sh`
Expected: `active`, and a fresh `ready` line.

Then check the startup state:
```bash
curl -s http://192.168.68.87:8000/api/daemon/status | python3 -c "import json,sys; print(json.load(sys.stdin)['backend_status']['motor_control_mode'])"
```
Expected: `disabled` (asleep at startup).

- [ ] **Step 3: On-robot acceptance (hand over to the user)**

With the TV quiet, the user stands about 1 m to one side of Reachy:
1. **"Hey Jarvis."** Expected: motors on, the wake-up move, a turn toward the user, a welcoming expression, then the conversation starts.
2. Talk for about 2 minutes, including **"What's on the grocery list?"** Expected:
   - still and antennas perked while the user talks
   - head motion plus face tracking while Reachy talks
   - a *thinking* expression during the hand-off
   - at least one model-chosen expression
3. Stay quiet. Expected: the falling chime, a goodbye expression, then the head goes to neutral.
4. **"Hey Jarvis"** within 5 minutes. Expected: no wake-up move (already awake); the conversation runs on the other engine and expresses itself through the picker. End it.
5. Wait more than `IDLE_AWAKE_S`. For the test, set `IDLE_AWAKE_S=60` in `~/reachy-voice/voice.env` and restart the service, then restore it to 300 afterwards. Expected: the sleep move, then motors off (`motor_control_mode: disabled`).

Summarise the log:
```bash
ssh -4 pollen@reachy-mini.local 'cd ~/reachy-voice && f=$(ls -t logs/voice-*.jsonl | head -1); python3 -c "
import json
for l in open(\"$f\"):
    e=json.loads(l)
    if e[\"event\"] in (\"wake\",\"body_event\",\"expression\",\"expression_dropped\",\"body_error\",\"body_sleep\",\"session_end\",\"delegation_result\"): print({k:v for k,v in e.items() if k!=\"ts\"})
"'
```
Expected:
- `body_event` entries for wake, express and sleep
- `expression` entries with source `cue`, `model` (Gemini) and `picker` (OpenAI)
- no `body_error` (any that appear must be explained)

- [ ] **Step 4: Commit**

```bash
git add voice/reachy_voice/main.py voice/reachy_voice/robot_audio.py voice/README.md
git commit -m "reachy_voice: wake/rest/sleep lifecycle with body language

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
