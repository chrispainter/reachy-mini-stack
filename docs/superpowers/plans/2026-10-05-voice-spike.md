# Voice Spike and Hermes Latency Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, on the real robot, whether Gemini 3.8 Live and OpenAI `gpt-live-1` respond fast, keep talking while a slow tool runs, and handle barge-in. Separately, cut Hermes' time on simple household lookups. The results gate Plan 2, the full `reachy_voice` app.

**Architecture:** Two standalone spike scripts run on the robot in their own venv, one per engine. They share small, unit-tested helpers: audio conversion, turn timing, dead-air metering, a fake 20 s home agent, and a JSONL log. A wrapper stops Pollen's conversation app while a spike holds the mic and restarts it afterwards. The Hermes work adds a "household data" map to `SOUL.md` and a benchmark that reads Hermes' own per-call timings.

**Tech Stack:** Python 3.12 on the robot (uv-managed CPython, `/opt/uv/uv`); `google-genai==2.28.0`; raw `websockets` 15 for OpenAI; the `reachy_mini` SDK 1.11.0 (local media path); numpy and scipy; pytest on the Mac (repo `.venv`, Python 3.13); Python 3.11 stdlib on the Pi for the benchmark.

## Global Constraints

- The repo is **public**. No API keys, household names or other personal details go in committed files. Keys are read at runtime from the robot app's `.env` at `/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env` (`GEMINI_API_KEY`, `OPENAI_API_KEY`).
- Do not install or upgrade packages in `/venvs/apps_venv`. The spike gets its own venv at `~/voice-spike/.venv` on the robot, which layers on top of apps_venv.
- Robot audio facts, verified 2026-10-05:
  - mic and speaker both run at 16 kHz, float32, 2 channels
  - mic frames arrive as `(1024, 2)` arrays, and the two channels are identical
  - `mini.media.push_audio_sample(np.float32 array)` plays audio
  - `mini.media.audio.clear_player()` flushes queued playback
  - a standalone script can open media directly once no app is running
- The robot runs one app at a time. Always restart Pollen's app (`reachy_mini_conversation_app`) after a spike, using the wrapper's trap.
- Models: `gemini-3.8-live`, and `gpt-live-1` at `wss://api.openai.com/v1/live/sessions`. OpenAI audio is `audio/pcm` at 16000 for both directions. Gemini input is `audio/pcm;rate=16000`; Gemini output is 24 kHz.
- SSH: `ssh -4 pollen@reachy-mini.local` (robot) and `ssh -4 behindtheproduct@reachy-pi.local` (Pi). The `-4` flag is needed because mDNS names resolve to IPv6 link-local first.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Spike runs (Tasks 3 and 4) need a person in the room speaking the protocol lines. The executor must hand over to the user at those steps.

## File Structure

```
voice/
  pytest.ini                  # pythonpath = . so tests import `spike`
  spike/
    __init__.py
    audio.py                  # mic frame -> PCM16 bytes; PCM16 bytes -> float32 @16k; rms()
    timing.py                 # PlaybackClock, TurnTimer, DeadAirMeter, BargeInDetector (pure)
    log.py                    # JsonlLog: one JSON object per line with a timestamp
    fake_agent.py             # fake_home_agent(): sleeps, returns a fixed list
    persona.py                # shared persona text and tool spec for both engines
    robot_audio.py            # RobotAudio: async mic frames, play, clear (robot only)
    gemini_spike.py           # Gemini 3.8 Live spike entry point
    openai_spike.py           # gpt-live-1 spike entry point
    summarize.py              # turns a JSONL log into a short Markdown summary
    requirements.txt          # google-genai==2.28.0
    deploy.sh                 # rsync to the robot, build the spike venv
    run.sh                    # on robot: stop Pollen's app, load keys, run spike, restart app
    RESULTS.md                # filled in during Tasks 3, 4 and 6
  tests/
    test_audio.py
    test_timing.py
    test_log_and_fake_agent.py
    test_summarize.py
household/
  hermes/SOUL.md              # + "Household data" section (Task 5)
  tools/hermes_bench.py       # benchmark of quick requests plus log parsing (stdlib only)
  tools/test_hermes_bench.py
```

---

### Task 1: Pure spike helpers (audio, timing, log, fake agent, summary)

**Files:**
- Create: `voice/pytest.ini`, `voice/spike/__init__.py`, `voice/spike/audio.py`, `voice/spike/timing.py`, `voice/spike/log.py`, `voice/spike/fake_agent.py`, `voice/spike/summarize.py`
- Test: `voice/tests/test_audio.py`, `voice/tests/test_timing.py`, `voice/tests/test_log_and_fake_agent.py`, `voice/tests/test_summarize.py`

**Interfaces:**
- Produces:
  - `spike.audio.mic_to_pcm16(frame: np.ndarray) -> bytes`
  - `spike.audio.pcm16_to_float(data: bytes, src_rate: int, dst_rate: int = 16000) -> np.ndarray`
  - `spike.audio.rms(frame: np.ndarray) -> float`
  - `spike.timing.PlaybackClock` with `.push(n_samples: int, rate: int, now: float)`, `.is_speaking(now: float) -> bool` and `.reset(now: float)`
  - `spike.timing.TurnTimer(speech_threshold=0.02)` with `.on_mic(level: float, now: float, robot_speaking: bool)` and `.on_robot_audio(now: float) -> float | None`
  - `spike.timing.DeadAirMeter` with `.start(call_id: str, now: float)`, `.on_audio(now: float, seconds: float)` and `.end(call_id: str, now: float) -> dict`
  - `spike.timing.BargeInDetector(threshold=0.08, frames=3)` with `.on_frame(level: float, robot_speaking: bool) -> bool`
  - `spike.log.JsonlLog(path: str)` with `.write(event: str, **fields)`
  - `spike.fake_agent.fake_home_agent(request: str, delay_s: float = 20.0) -> Awaitable[str]` and the constant `FAKE_ANSWER: str`
  - `spike.summarize.summarize(path: str) -> str`

- [ ] **Step 1: Install scipy in the Mac test venv**

Run: `/Users/painter/palettepal/reachy-mini-stack/.venv/bin/python -m pip install -q "scipy>=1.14"`
Expected: exits 0. The robot already has scipy 1.18.0 in apps_venv.

- [ ] **Step 2: Write the failing tests**

`voice/pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
```

`voice/spike/__init__.py`: an empty file.

`voice/tests/test_audio.py`:
```python
import numpy as np

from spike.audio import mic_to_pcm16, pcm16_to_float, rms


def test_mic_to_pcm16_takes_first_channel_and_scales():
    frame = np.array([[0.5, -1.0], [-0.5, 1.0], [2.0, 0.0]], dtype=np.float32)
    out = np.frombuffer(mic_to_pcm16(frame), dtype="<i2")
    assert out.tolist() == [16383, -16383, 32767]  # clipped at +1.0


def test_mic_to_pcm16_accepts_mono():
    frame = np.zeros(1024, dtype=np.float32)
    assert len(mic_to_pcm16(frame)) == 2048


def test_pcm16_to_float_same_rate_roundtrip():
    pcm = (np.array([0, 16384, -16384], dtype="<i2")).tobytes()
    out = pcm16_to_float(pcm, 16000, 16000)
    assert out.dtype == np.float32
    assert np.allclose(out, [0.0, 0.5, -0.5])


def test_pcm16_to_float_resamples_24k_to_16k():
    pcm = np.zeros(2400, dtype="<i2").tobytes()  # 100 ms at 24 kHz
    out = pcm16_to_float(pcm, 24000, 16000)
    assert out.shape == (1600,)  # 100 ms at 16 kHz


def test_rms_of_stereo_frame_uses_first_channel():
    frame = np.stack([np.full(100, 0.1), np.zeros(100)], axis=1).astype(np.float32)
    assert abs(rms(frame) - 0.1) < 1e-6
```

`voice/tests/test_timing.py`:
```python
from spike.timing import BargeInDetector, DeadAirMeter, PlaybackClock, TurnTimer


def test_playback_clock_tracks_queued_audio():
    clock = PlaybackClock()
    assert not clock.is_speaking(0.0)
    clock.push(16000, 16000, now=0.0)  # 1 s queued
    clock.push(8000, 16000, now=0.2)   # +0.5 s appended after the first second
    assert clock.is_speaking(1.4)
    assert not clock.is_speaking(1.6)
    clock.reset(now=0.3)
    assert not clock.is_speaking(0.31)


def test_turn_timer_measures_from_last_user_speech_to_first_robot_audio():
    t = TurnTimer(speech_threshold=0.02)
    t.on_mic(0.10, now=1.0, robot_speaking=False)
    t.on_mic(0.10, now=1.5, robot_speaking=False)  # last loud frame
    t.on_mic(0.001, now=1.8, robot_speaking=False)
    assert t.on_robot_audio(now=2.6) == 1.1
    assert t.on_robot_audio(now=2.7) is None  # only the first chunk counts


def test_turn_timer_ignores_mic_while_robot_speaks():
    t = TurnTimer()
    t.on_mic(0.5, now=1.0, robot_speaking=True)
    assert t.on_robot_audio(now=1.2) is None


def test_dead_air_meter_reports_audio_during_tool():
    m = DeadAirMeter()
    m.start("c1", now=10.0)
    m.on_audio(now=11.0, seconds=1.5)
    m.on_audio(now=25.0, seconds=2.0)
    report = m.end("c1", now=30.0)
    assert report == {"call_id": "c1", "tool_s": 20.0, "robot_audio_s_during": 3.5}
    m.on_audio(now=31.0, seconds=1.0)  # after end: not counted anywhere


def test_barge_in_needs_consecutive_loud_frames_while_speaking():
    d = BargeInDetector(threshold=0.08, frames=3)
    assert not d.on_frame(0.2, robot_speaking=True)
    assert not d.on_frame(0.2, robot_speaking=True)
    assert d.on_frame(0.2, robot_speaking=True)
    assert not d.on_frame(0.2, robot_speaking=False)  # resets when silent
    assert not d.on_frame(0.01, robot_speaking=True)
```

`voice/tests/test_log_and_fake_agent.py`:
```python
import asyncio
import json

from spike.fake_agent import FAKE_ANSWER, fake_home_agent
from spike.log import JsonlLog


def test_jsonl_log_appends_events_with_timestamp(tmp_path):
    path = tmp_path / "x.jsonl"
    log = JsonlLog(str(path))
    log.write("first_audio", latency_s=0.8)
    log.write("turn_complete")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["event"] for line in lines] == ["first_audio", "turn_complete"]
    assert lines[0]["latency_s"] == 0.8
    assert isinstance(lines[0]["ts"], float)


def test_fake_home_agent_returns_fixed_answer_after_delay():
    result = asyncio.run(fake_home_agent("what's on the list", delay_s=0.01))
    assert result == FAKE_ANSWER
```

`voice/tests/test_summarize.py`:
```python
import json

from spike.summarize import summarize


def test_summarize_reports_latency_and_dead_air(tmp_path):
    path = tmp_path / "run.jsonl"
    events = [
        {"event": "session_open", "ts": 0, "engine": "gemini", "model": "gemini-3.8-live"},
        {"event": "first_audio", "ts": 1, "latency_s": 0.8},
        {"event": "first_audio", "ts": 2, "latency_s": 1.2},
        {"event": "tool_result", "ts": 3, "call_id": "c1", "tool_s": 20.0, "robot_audio_s_during": 3.5},
        {"event": "interrupted", "ts": 4},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events))
    text = summarize(str(path))
    assert "gemini" in text
    assert "median 1.00 s" in text
    assert "max 1.20 s" in text
    assert "3.5 s of speech during a 20.0 s tool" in text
    assert "interruptions: 1" in text
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: collection errors such as `ModuleNotFoundError: No module named 'spike.audio'`

- [ ] **Step 4: Write the implementations**

`voice/spike/audio.py`:
```python
"""Audio format conversion between the robot SDK and the voice engines."""

import numpy as np
from scipy.signal import resample_poly


def _mono(frame: np.ndarray) -> np.ndarray:
    # The robot mic delivers two identical channels; take the first.
    return frame[:, 0] if frame.ndim == 2 else frame


def mic_to_pcm16(frame: np.ndarray) -> bytes:
    """Robot mic float32 in [-1, 1], shape (n,) or (n, ch) -> mono 16-bit little-endian PCM."""
    clipped = np.clip(_mono(frame), -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


def pcm16_to_float(data: bytes, src_rate: int, dst_rate: int = 16000) -> np.ndarray:
    """16-bit PCM from an engine -> float32 mono at the robot's playback rate."""
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if src_rate != dst_rate:
        g = int(np.gcd(src_rate, dst_rate))
        samples = resample_poly(samples, dst_rate // g, src_rate // g).astype(np.float32)
    return samples


def rms(frame: np.ndarray) -> float:
    mono = _mono(frame)
    return float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
```

`voice/spike/timing.py`:
```python
"""Engine-agnostic measurements, so both spikes are judged the same way."""

from dataclasses import dataclass, field


@dataclass
class PlaybackClock:
    """Knows when queued robot speech will have finished playing."""

    _until: float = 0.0

    def push(self, n_samples: int, rate: int, now: float) -> None:
        self._until = max(self._until, now) + n_samples / rate

    def is_speaking(self, now: float) -> bool:
        return now < self._until

    def reset(self, now: float) -> None:
        self._until = now


@dataclass
class TurnTimer:
    """Time from the end of the user's speech to the robot's first audio."""

    speech_threshold: float = 0.02
    _last_speech: float | None = None
    _awaiting: bool = False

    def on_mic(self, level: float, now: float, robot_speaking: bool) -> None:
        if robot_speaking:
            return
        if level >= self.speech_threshold:
            self._last_speech = now
            self._awaiting = True

    def on_robot_audio(self, now: float) -> float | None:
        if not self._awaiting or self._last_speech is None:
            return None
        self._awaiting = False
        return round(now - self._last_speech, 3)


@dataclass
class DeadAirMeter:
    """How much the robot spoke while each tool call was running."""

    _open: dict[str, list[float]] = field(default_factory=dict)  # call_id -> [start, audio_s]

    def start(self, call_id: str, now: float) -> None:
        self._open[call_id] = [now, 0.0]

    def on_audio(self, now: float, seconds: float) -> None:
        for entry in self._open.values():
            entry[1] += seconds

    def end(self, call_id: str, now: float) -> dict:
        start, audio_s = self._open.pop(call_id)
        return {"call_id": call_id, "tool_s": round(now - start, 3), "robot_audio_s_during": round(audio_s, 3)}


@dataclass
class BargeInDetector:
    """Local barge-in for engines that don't signal it: N loud frames while the robot speaks."""

    threshold: float = 0.08
    frames: int = 3
    _count: int = 0

    def on_frame(self, level: float, robot_speaking: bool) -> bool:
        if robot_speaking and level >= self.threshold:
            self._count += 1
        else:
            self._count = 0
        if self._count >= self.frames:
            self._count = 0
            return True
        return False
```

`voice/spike/log.py`:
```python
"""One JSON object per line, so runs can be summarised and compared later."""

import json
import time


class JsonlLog:
    def __init__(self, path: str) -> None:
        self._path = path

    def write(self, event: str, **fields) -> None:
        record = {"event": event, "ts": time.time(), **fields}
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
```

`voice/spike/fake_agent.py`:
```python
"""Stands in for Hermes so talk-while-tool behaviour can be tested deterministically."""

import asyncio

FAKE_ANSWER = "The grocery list has milk, eggs and coffee."


async def fake_home_agent(request: str, delay_s: float = 20.0) -> str:
    await asyncio.sleep(delay_s)
    return FAKE_ANSWER
```

`voice/spike/summarize.py`:
```python
"""Turn a spike JSONL log into a few lines for RESULTS.md."""

import json
import statistics
import sys


def summarize(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    opened = next((e for e in events if e["event"] == "session_open"), {})
    latencies = [e["latency_s"] for e in events if e["event"] == "first_audio"]
    tools = [e for e in events if e["event"] == "tool_result"]
    interruptions = sum(1 for e in events if e["event"] in ("interrupted", "barge_in"))

    lines = [f"engine: {opened.get('engine', '?')} ({opened.get('model', '?')}, voice {opened.get('voice', '?')})"]
    if latencies:
        lines.append(
            f"first audio after user speech: n={len(latencies)}, "
            f"median {statistics.median(latencies):.2f} s, max {max(latencies):.2f} s"
        )
    for t in tools:
        lines.append(f"tool {t['call_id']}: {t['robot_audio_s_during']} s of speech during a {t['tool_s']} s tool")
    lines.append(f"interruptions: {interruptions}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(sys.argv[1]))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: `13 passed`

- [ ] **Step 6: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack
git add voice/pytest.ini voice/spike/__init__.py voice/spike/audio.py voice/spike/timing.py voice/spike/log.py voice/spike/fake_agent.py voice/spike/summarize.py voice/tests
git commit -m "voice spike: audio, timing, log and fake-agent helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Robot spike environment, RobotAudio and a smoke test

**Files:**
- Create: `voice/spike/robot_audio.py`, `voice/spike/persona.py`, `voice/spike/requirements.txt`, `voice/spike/deploy.sh`, `voice/spike/run.sh`, `voice/spike/smoke.py`

**Interfaces:**
- Consumes: `spike.timing.PlaybackClock`
- Produces:
  - `spike.robot_audio.RobotAudio(media)` with `.start()`, `.stop()`, `async .frames() -> AsyncIterator[np.ndarray]`, `.play(samples: np.ndarray, now: float)`, `.clear(now: float)` and `.is_speaking(now: float) -> bool`
  - `spike.persona.PERSONA: str`, `TOOL_NAME = "ask_home_agent"`, `TOOL_DESCRIPTION: str` and `TOOL_PARAMS: dict` (JSON schema)
  - `voice/spike/run.sh <module> [args...]`, run on the robot from `~/voice-spike`

- [ ] **Step 1: Write the robot-only modules**

`voice/spike/robot_audio.py`:
```python
"""Robot mic and speaker through the SDK's local media path (no WebRTC)."""

import asyncio
from collections.abc import AsyncIterator

import numpy as np

from spike.timing import PlaybackClock

RATE = 16000


class RobotAudio:
    def __init__(self, media) -> None:
        self._media = media
        self._clock = PlaybackClock()

    def start(self) -> None:
        self._media.start_recording()
        self._media.start_playing()

    def stop(self) -> None:
        self._media.stop_recording()
        self._media.stop_playing()

    async def frames(self) -> AsyncIterator[np.ndarray]:
        while True:
            frame = await asyncio.to_thread(self._media.get_audio_sample)
            if frame is None or len(frame) == 0:
                await asyncio.sleep(0.01)
                continue
            yield frame

    def play(self, samples: np.ndarray, now: float) -> None:
        self._media.push_audio_sample(samples.astype(np.float32))
        self._clock.push(len(samples), RATE, now)

    def clear(self, now: float) -> None:
        self._media.audio.clear_player()
        self._clock.reset(now)

    def is_speaking(self, now: float) -> bool:
        return self._clock.is_speaking(now)
```

`voice/spike/persona.py`:
```python
"""Identical persona and tool for both engines, so the bake-off compares engines only."""

PERSONA = """You are Reachy, a small, friendly household robot on a desk. You talk with the
people who live here and their guests. Keep replies short and warm: one or two sentences.
You can be interrupted; if someone talks over you, stop and listen.
For anything that needs household knowledge, lists, reminders, research or planning, use
the home agent. When you hand something to the home agent, say a brief natural
acknowledgement right away (for example "Sure, let me check") and keep the conversation
going. When the answer arrives, share it at a natural pause. Never invent the answer."""

TOOL_NAME = "ask_home_agent"
TOOL_DESCRIPTION = (
    "Hand a request to the household's home agent, which knows the household's lists and notes "
    "and can research, plan and set reminders. It can take up to a minute. Keep talking while it works."
)
TOOL_PARAMS = {
    "type": "object",
    "properties": {"request": {"type": "string", "description": "What the person wants, in their words."}},
    "required": ["request"],
}
```

`voice/spike/requirements.txt`:
```
google-genai==2.28.0
```

`voice/spike/smoke.py`:
```python
"""Check the spike venv can import everything and drive the mic and speaker."""

import asyncio
import time

import numpy as np
from google import genai  # noqa: F401  (import check only)
from reachy_mini import ReachyMini

from spike.audio import rms
from spike.robot_audio import RobotAudio


async def main() -> None:
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        try:
            levels, start = [], time.monotonic()
            async for frame in audio.frames():
                levels.append(rms(frame))
                if time.monotonic() - start > 3:
                    break
            print(f"mic: {len(levels)} frames, max rms {max(levels):.3f}")
            tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.float32)
            audio.play(tone, time.monotonic())
            await asyncio.sleep(0.5)
            print("speaking:", audio.is_speaking(time.monotonic()))
            audio.clear(time.monotonic())
            print("cleared; speaking:", audio.is_speaking(time.monotonic()))
        finally:
            audio.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write the deploy and run scripts**

`voice/spike/deploy.sh`:
```bash
#!/usr/bin/env bash
# Copy the spike to the robot and build its venv. Run from the Mac; idempotent.
# The venv layers on top of /venvs/apps_venv (for reachy_mini, numpy, scipy, GStreamer)
# without installing anything into it.
set -euo pipefail
ROBOT="${ROBOT:-pollen@reachy-mini.local}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # voice/

rsync -a --delete --exclude '.venv' --exclude 'logs' --exclude '__pycache__' \
  -e "ssh -4" "$HERE/spike/" "$ROBOT:voice-spike/spike/"
ssh -4 "$ROBOT" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/voice-spike
mkdir -p logs
PY=/home/pollen/.local/share/uv/python/cpython-3.12.12-linux-aarch64-gnu/bin/python3
[ -x .venv/bin/python ] || /opt/uv/uv venv --python "$PY" .venv
# addsitedir also processes apps_venv's own .pth files (GStreamer bundle setup).
echo "import site; site.addsitedir('/venvs/apps_venv/lib/python3.12/site-packages')" \
  > .venv/lib/python3.12/site-packages/zz_apps_venv.pth
/opt/uv/uv pip install --quiet --python .venv/bin/python -r spike/requirements.txt
cp spike/run.sh ./run.sh && chmod +x run.sh
.venv/bin/python -c "import google.genai, reachy_mini, scipy; print('spike venv ok')"
df -h / | tail -1
REMOTE
```

`voice/spike/run.sh`:
```bash
#!/usr/bin/env bash
# On the robot: free the mic from Pollen's app, run one spike, always restore the app.
#   ~/voice-spike/run.sh spike.gemini_spike --voice Kore
set -euo pipefail
cd ~/voice-spike
API=http://127.0.0.1:8000
APP_ENV=/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env

restore() {
  curl -s -m 30 -X POST "$API/api/apps/start-app/reachy_mini_conversation_app" >/dev/null || true
  echo "restored reachy_mini_conversation_app"
}
trap restore EXIT

curl -s -m 30 -X POST "$API/api/apps/stop-current-app" >/dev/null || true
for _ in $(seq 1 20); do
  curl -s -m 5 "$API/api/apps/current-app-status" | grep -q '"state":"running"' || break
  sleep 1
done

set -a; . "$APP_ENV"; set +a      # GEMINI_API_KEY / OPENAI_API_KEY, never printed
module="$1"; shift
.venv/bin/python -m "$module" "$@"
```

- [ ] **Step 3: Deploy**

Run: `chmod +x voice/spike/deploy.sh voice/spike/run.sh && voice/spike/deploy.sh`
Expected: the last lines are `spike venv ok` and a `df` line showing more than 4 GB available.

- [ ] **Step 4: Run the smoke test (someone should talk near the robot for 3 s)**

Run: `ssh -4 -t pollen@reachy-mini.local '~/voice-spike/run.sh spike.smoke'`
Expected:
- `mic: ~45 frames, max rms` above 0.02 while someone talks
- a 1 s tone audibly cut short at about 0.5 s
- `speaking: True`, then `cleared; speaking: False`
- `restored reachy_mini_conversation_app`

If `max rms` stays below 0.02 while someone talks, record the observed speaking level in `RESULTS.md` and use roughly half of it as `--speech-threshold` in Tasks 3 and 4.

- [ ] **Step 5: Commit**

```bash
git add voice/spike/robot_audio.py voice/spike/persona.py voice/spike/requirements.txt voice/spike/deploy.sh voice/spike/run.sh voice/spike/smoke.py
git commit -m "voice spike: robot audio wrapper, shared persona, deploy and run scripts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Gemini 3.8 Live spike

**Files:**
- Create: `voice/spike/gemini_spike.py`
- Create: `voice/spike/RESULTS.md` (Gemini section)

**Interfaces:**
- Consumes: everything from Tasks 1 and 2
- Produces: `python -m spike.gemini_spike [--model gemini-3.8-live] [--voice Kore] [--tool-delay 20] [--minutes 6] [--speech-threshold 0.02]`, which writes `~/voice-spike/logs/gemini-<epoch>.jsonl`

- [ ] **Step 1: Confirm the SDK has the non-blocking types (on the robot)**

Run:
```bash
ssh -4 pollen@reachy-mini.local '~/voice-spike/.venv/bin/python -c "
from google.genai import types
types.FunctionDeclaration(name=\"x\", description=\"y\", behavior=types.Behavior.NON_BLOCKING)
types.FunctionResponse(id=\"1\", name=\"x\", response={}, scheduling=types.FunctionResponseScheduling.WHEN_IDLE)
print(\"types ok\")"'
```
Expected: `types ok`. If `scheduling` is rejected, put `"scheduling": "WHEN_IDLE"` inside the `response` dict instead (the docs-page form) in Step 2, and note the change in RESULTS.md.

- [ ] **Step 2: Write the spike**

`voice/spike/gemini_spike.py`:
```python
"""Gemini 3.8 Live on the robot: latency, talk-while-tool and barge-in."""

import argparse
import asyncio
import os
import time

from google import genai
from google.genai import types
from reachy_mini import ReachyMini

from spike.audio import mic_to_pcm16, pcm16_to_float, rms
from spike.fake_agent import fake_home_agent
from spike.log import JsonlLog
from spike.persona import PERSONA, TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMS
from spike.robot_audio import RobotAudio
from spike.timing import DeadAirMeter, TurnTimer


def build_config(voice: str) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
        system_instruction=PERSONA,
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=TOOL_NAME,
                        description=TOOL_DESCRIPTION,
                        parameters_json_schema=TOOL_PARAMS,
                        behavior=types.Behavior.NON_BLOCKING,
                    )
                ]
            )
        ],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )


async def pump_mic(session, audio: RobotAudio, timer: TurnTimer) -> None:
    async for frame in audio.frames():
        now = time.monotonic()
        timer.on_mic(rms(frame), now, audio.is_speaking(now))
        await session.send_realtime_input(
            audio=types.Blob(data=mic_to_pcm16(frame), mime_type="audio/pcm;rate=16000")
        )


async def answer_tool(session, fc, dead_air: DeadAirMeter, log: JsonlLog, delay_s: float) -> None:
    result = await fake_home_agent((fc.args or {}).get("request", ""), delay_s=delay_s)
    log.write("tool_result", **dead_air.end(fc.id, time.monotonic()))
    await session.send_tool_response(
        function_responses=[
            types.FunctionResponse(
                id=fc.id,
                name=fc.name,
                response={"result": result},
                scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
            )
        ]
    )


async def pump_server(session, audio, timer, dead_air, log, delay_s) -> None:
    pending: set[asyncio.Task] = set()
    while True:  # receive() ends after each completed turn
        async for msg in session.receive():
            now = time.monotonic()
            if msg.data:
                samples = pcm16_to_float(msg.data, 24000, 16000)
                latency = timer.on_robot_audio(now)
                if latency is not None:
                    log.write("first_audio", latency_s=latency)
                    print(f"first audio {latency:.2f} s after speech")
                dead_air.on_audio(now, len(samples) / 16000)
                audio.play(samples, now)
            sc = msg.server_content
            if sc is not None:
                if sc.interrupted:
                    audio.clear(now)
                    log.write("interrupted")
                if sc.input_transcription and sc.input_transcription.text:
                    log.write("user_text", text=sc.input_transcription.text)
                if sc.output_transcription and sc.output_transcription.text:
                    log.write("robot_text", text=sc.output_transcription.text)
                if sc.turn_complete:
                    log.write("turn_complete")
            if msg.tool_call:
                for fc in msg.tool_call.function_calls:
                    dead_air.start(fc.id, now)
                    log.write("tool_call", call_id=fc.id, name=fc.name, args=dict(fc.args or {}))
                    print(f"tool call {fc.name} {dict(fc.args or {})}")
                    task = asyncio.create_task(answer_tool(session, fc, dead_air, log, delay_s))
                    pending.add(task)
                    task.add_done_callback(pending.discard)
            if msg.usage_metadata:
                log.write("usage", total_tokens=msg.usage_metadata.total_token_count)


async def main(args) -> None:
    log = JsonlLog(f"logs/gemini-{int(time.time())}.jsonl")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    timer, dead_air = TurnTimer(speech_threshold=args.speech_threshold), DeadAirMeter()
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        try:
            async with client.aio.live.connect(model=args.model, config=build_config(args.voice)) as session:
                log.write("session_open", engine="gemini", model=args.model, voice=args.voice)
                print("listening; Ctrl-C to stop")
                await asyncio.wait_for(
                    asyncio.gather(
                        pump_mic(session, audio, timer),
                        pump_server(session, audio, timer, dead_air, log, args.tool_delay),
                    ),
                    timeout=args.minutes * 60,
                )
        except asyncio.TimeoutError:
            pass
        finally:
            audio.stop()
            log.write("session_close")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gemini-3.8-live")
    p.add_argument("--voice", default="Kore")
    p.add_argument("--tool-delay", type=float, default=20.0)
    p.add_argument("--minutes", type=float, default=6.0)
    p.add_argument("--speech-threshold", type=float, default=0.02)
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 3: Deploy, then run the protocol (hand over to the user: someone must speak)**

Run: `voice/spike/deploy.sh && ssh -4 -t pollen@reachy-mini.local '~/voice-spike/run.sh spike.gemini_spike --voice Kore'`

Protocol, spoken at normal distance (~1 m), waiting for each reply before the next line:
1. "Hi Reachy, how are you today?"
2. "What's a good name for a goldfish?"
3. "Tell me something interesting about octopuses."
4. "What's on the grocery list?" This triggers the 20 s fake tool. Keep chatting during it: "While you check, what's your favourite colour?"
5. "Tell me a long story about a cat." Interrupt after ~3 s with "Stop, stop. Actually, tell me a joke."
6. Ctrl-C.

Expected:
- the console shows `first audio … s after speech` for each turn and one `tool call ask_home_agent`
- the robot speaks during the tool window and later says the fake list
- the story stops when interrupted
- `restored reachy_mini_conversation_app`

- [ ] **Step 4: Summarise and record**

Run: `ssh -4 pollen@reachy-mini.local 'cd ~/voice-spike && .venv/bin/python -m spike.summarize $(ls -t logs/gemini-*.jsonl | head -1)'`

Create `voice/spike/RESULTS.md` with:
- a `## Gemini 3.8 Live` section pasting the summary output
- answers to these four questions:
  1. Did it acknowledge and keep talking during the tool (`robot_audio_s_during` > 0)?
  2. Did the fake answer arrive at a natural pause, without cutting anyone off?
  3. Did barge-in stop the story within ~0.5 s?
  4. How natural did it sound? Give a 1–5 score from the listener.
- the date, voice and any deviations (e.g. the `scheduling` fallback)

Also try `--voice Puck` and `--voice Aoede` for one or two lines each and note which sounds best on the small speaker.

- [ ] **Step 5: Commit**

```bash
git add voice/spike/gemini_spike.py voice/spike/RESULTS.md
git commit -m "voice spike: Gemini 3.8 Live run and results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: OpenAI gpt-live-1 spike

**Files:**
- Create: `voice/spike/openai_spike.py`
- Modify: `voice/spike/RESULTS.md` (add an OpenAI section)

**Interfaces:**
- Consumes: everything from Tasks 1 and 2, including `BargeInDetector`. gpt-live-1 sends no speech-started event, so barge-in is detected locally.
- Produces: `python -m spike.openai_spike [--model gpt-live-1] [--voice marin] [--tool-delay 20] [--minutes 6] [--speech-threshold 0.02] [--barge-threshold 0.08]`, which writes `logs/openai-<epoch>.jsonl`

- [ ] **Step 1: Verify the wire event names against the SDK (on the Mac)**

Run:
```bash
cd /tmp && rm -rf oa && mkdir oa && cd oa && /Users/painter/palettepal/reachy-mini-stack/.venv/bin/python -m pip download -q --no-deps "openai==3.24.0" && unzip -q openai-3.24.0-*.whl && grep -rhoE '"session\.[a-z_.]+"' openai/types | sort -u
```
Expected: the list includes `"session.start"`, `"session.input_audio.append"`, `"session.close"`, `"session.commentary.append"`, `"session.started"`, `"session.output_audio.delta"`, `"session.input_transcript.delta"`, `"session.output_transcript.delta"`, `"session.delegation.created"` and `"session.closed"`. If any name differs, use the SDK's spelling in Step 2.

- [ ] **Step 2: Write the spike**

`voice/spike/openai_spike.py`:
```python
"""OpenAI gpt-live-1 on the robot: latency, delegation while talking, local barge-in."""

import argparse
import asyncio
import base64
import json
import os
import time

import websockets
from reachy_mini import ReachyMini

from spike.audio import mic_to_pcm16, pcm16_to_float, rms
from spike.fake_agent import fake_home_agent
from spike.log import JsonlLog
from spike.persona import PERSONA
from spike.robot_audio import RobotAudio
from spike.timing import BargeInDetector, DeadAirMeter, TurnTimer

URL = "wss://api.openai.com/v1/live/sessions"


def start_event(model: str, voice: str) -> dict:
    return {
        "type": "session.start",
        "event_id": "start",
        "session": {
            "model": model,
            "instructions": PERSONA,
            "audio": {"format": {"type": "audio/pcm", "rate": 16000}, "output": {"voice": voice}},
            "delegation": {"type": "client"},
        },
    }


async def pump_mic(ws, audio, timer, barge, log, started: asyncio.Event) -> None:
    await started.wait()
    async for frame in audio.frames():
        now = time.monotonic()
        level, speaking = rms(frame), audio.is_speaking(now)
        timer.on_mic(level, now, speaking)
        if barge.on_frame(level, speaking):
            audio.clear(now)
            log.write("barge_in")
        await ws.send(
            json.dumps({"type": "session.input_audio.append", "audio": base64.b64encode(mic_to_pcm16(frame)).decode()})
        )


async def answer_delegation(ws, delegation_id, request, dead_air, log, delay_s) -> None:
    result = await fake_home_agent(request, delay_s=delay_s)
    log.write("tool_result", **dead_air.end(delegation_id, time.monotonic()))
    await ws.send(
        json.dumps(
            {
                "type": "session.commentary.append",
                "event_id": f"result-{delegation_id}",
                "delegation_id": delegation_id,
                "content": result,
            }
        )
    )


async def pump_server(ws, audio, timer, dead_air, log, delay_s, started: asyncio.Event) -> None:
    pending: set[asyncio.Task] = set()
    user_text = ""  # recent user transcript; the delegation event carries no task text
    async for raw in ws:
        event = json.loads(raw)
        kind, now = event.get("type"), time.monotonic()
        if kind == "session.started":
            started.set()
            log.write("session_started")
        elif kind == "session.output_audio.delta":
            samples = pcm16_to_float(base64.b64decode(event["delta"]), 16000, 16000)
            latency = timer.on_robot_audio(now)
            if latency is not None:
                log.write("first_audio", latency_s=latency)
                print(f"first audio {latency:.2f} s after speech")
            dead_air.on_audio(now, len(samples) / 16000)
            audio.play(samples, now)
        elif kind == "session.input_transcript.delta":
            user_text = (user_text + event.get("delta", ""))[-500:]
            log.write("user_text", text=event.get("delta", ""))
        elif kind == "session.output_transcript.delta":
            log.write("robot_text", text=event.get("delta", ""))
        elif kind == "session.delegation.created":
            delegation_id = event["delegation"]["id"]
            dead_air.start(delegation_id, now)
            log.write("tool_call", call_id=delegation_id, request=user_text)
            print(f"delegation {delegation_id}: {user_text!r}")
            task = asyncio.create_task(answer_delegation(ws, delegation_id, user_text, dead_air, log, delay_s))
            pending.add(task)
            task.add_done_callback(pending.discard)
            user_text = ""
        elif kind == "error":
            log.write("error", detail=event)
            print("error:", event)
        elif kind == "session.closed":
            log.write("session_closed", usage=event.get("usage"), reason=event.get("reason"))
            return


async def main(args) -> None:
    log = JsonlLog(f"logs/openai-{int(time.time())}.jsonl")
    timer = TurnTimer(speech_threshold=args.speech_threshold)
    dead_air, barge = DeadAirMeter(), BargeInDetector(threshold=args.barge_threshold)
    started = asyncio.Event()
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        try:
            async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
                await ws.send(json.dumps(start_event(args.model, args.voice)))
                log.write("session_open", engine="openai", model=args.model, voice=args.voice)
                print("listening; Ctrl-C to stop")
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            pump_mic(ws, audio, timer, barge, log, started),
                            pump_server(ws, audio, timer, dead_air, log, args.tool_delay, started),
                        ),
                        timeout=args.minutes * 60,
                    )
                except asyncio.TimeoutError:
                    pass
                finally:
                    await ws.send(json.dumps({"type": "session.close"}))
        finally:
            audio.stop()
            log.write("session_close")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gpt-live-1")
    p.add_argument("--voice", default="marin")
    p.add_argument("--tool-delay", type=float, default=20.0)
    p.add_argument("--minutes", type=float, default=6.0)
    p.add_argument("--speech-threshold", type=float, default=0.02)
    p.add_argument("--barge-threshold", type=float, default=0.08)
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 3: Deploy, then run the same protocol (hand over to the user)**

Run: `voice/spike/deploy.sh && ssh -4 -t pollen@reachy-mini.local '~/voice-spike/run.sh spike.openai_spike --voice marin'`

Use the same six protocol lines as Task 3, Step 3.

Expected:
- `first audio …` lines appear
- a `delegation …` line appears whose request text mentions the grocery list
- the robot keeps talking during the delegation and later says the fake list
- the story stops on interruption: either the model stops, or a `barge_in` event clears the speaker
- `restored reachy_mini_conversation_app`

If interruptions don't work, re-run with `--barge-threshold 0.05`. If the robot's own voice triggers false barge-ins, re-run with `0.12`. Record the value that worked.

- [ ] **Step 4: Summarise and record**

Run: `ssh -4 pollen@reachy-mini.local 'cd ~/voice-spike && .venv/bin/python -m spike.summarize $(ls -t logs/openai-*.jsonl | head -1)'`

Add a `## OpenAI gpt-live-1` section to `RESULTS.md`. Paste the summary and answer the same four questions. Also note whether delegation fired at a sensible moment, which developers report as unreliable. Try `--voice cedar` and `--voice vesper` briefly and note the best voice.

- [ ] **Step 5: Commit**

```bash
git add voice/spike/openai_spike.py voice/spike/RESULTS.md
git commit -m "voice spike: OpenAI gpt-live-1 run and results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Hermes household data map and lookup benchmark

Measured on 2026-10-05, "What's on the grocery list?" took 16.7 s. That was 5 sequential model calls (2–5 s each, about 13k input tokens each) while Hermes searched for where it had stored the list. The tools themselves took under 0.3 s. The list lives at `/opt/data/household-grocery-list.md` inside the container.

**Files:**
- Create: `household/tools/hermes_bench.py`, `household/tools/test_hermes_bench.py`
- Modify: `household/hermes/SOUL.md` (append a "Household data" section)

**Interfaces:**
- Produces:
  - `hermes_bench.parse_agent_log(lines: list[str], session_id: str) -> dict` returning `{"api_calls": int, "llm_s": float}`
  - the CLI `python3 hermes_bench.py [--label NAME]`, run on the Pi, which prints a Markdown table

- [ ] **Step 1: Write the failing test**

`household/tools/test_hermes_bench.py`:
```python
from hermes_bench import parse_agent_log

LINES = [
    "2026-10-05 05:26:21,899 INFO [s1] agent.turn_context: conversation turn: session=s1 model=gpt-5.4-mini",
    "2026-10-05 05:26:24,383 INFO [s1] agent.conversation_loop: API call #1: model=gpt-5.4-mini provider=openai-api in=11762 out=105 total=11867 latency=2.4s id=resp_a",
    "2026-10-05 05:26:24,463 INFO agent.tool_executor: tool skill_view completed (0.06s, 2513 chars)",
    "2026-10-05 05:26:27,255 INFO [s1] agent.conversation_loop: API call #2: model=gpt-5.4-mini provider=openai-api in=13532 out=144 total=13676 latency=2.8s cache=11776/13532 (87%) id=resp_b",
    "2026-10-05 05:26:30,000 INFO [s2] agent.conversation_loop: API call #1: model=gpt-5.4-mini provider=openai-api in=1 out=1 total=2 latency=9.9s id=resp_c",
]


def test_parse_agent_log_counts_calls_and_latency_for_one_session():
    assert parse_agent_log(LINES, "s1") == {"api_calls": 2, "llm_s": 5.2}


def test_parse_agent_log_unknown_session_is_zero():
    assert parse_agent_log(LINES, "nope") == {"api_calls": 0, "llm_s": 0.0}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/household/tools && ../../.venv/bin/python -m pytest -q test_hermes_bench.py`
Expected: `ModuleNotFoundError: No module named 'hermes_bench'`

- [ ] **Step 3: Implement the benchmark (stdlib only; it runs on the Pi's Python 3.11)**

`household/tools/hermes_bench.py`:
```python
"""Benchmark Hermes on quick household requests. Run on the Pi:
    python3 hermes_bench.py --label before
Reads the API key from ~/.config/household/agent.env and per-call timings from
Hermes' agent.log (via docker exec). Prints a Markdown table.
"""

import argparse
import json
import pathlib
import re
import subprocess
import time
import urllib.request

URL = "http://127.0.0.1:8642/v1/chat/completions"
REQUESTS = [
    "What's on the grocery list?",
    "Add bread to the grocery list.",
    "What's on the grocery list?",
    "Remove bread from the grocery list.",
]
_CALL = re.compile(r"\[(?P<sid>[^\]]+)\] agent\.conversation_loop: API call #\d+: .*?latency=(?P<lat>[\d.]+)s")


def parse_agent_log(lines: list[str], session_id: str) -> dict:
    calls = [float(m["lat"]) for line in lines if (m := _CALL.search(line)) and m["sid"] == session_id]
    return {"api_calls": len(calls), "llm_s": round(sum(calls), 1)}


def _api_key() -> str:
    env = pathlib.Path.home() / ".config/household/agent.env"
    for line in env.read_text().splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("API_SERVER_KEY not found")


def _ask(key: str, session_id: str, text: str) -> tuple[float, str]:
    body = json.dumps({"model": "hermes-agent", "messages": [{"role": "user", "content": f"[Asked by a tester, via Reachy] {text}"}]})
    req = urllib.request.Request(
        URL,
        data=body.encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Hermes-Session-Id": session_id},
    )
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as resp:
        answer = json.load(resp)["choices"][0]["message"]["content"].strip()
    return round(time.monotonic() - start, 1), answer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="run")
    args = p.parse_args()
    key, rows = _api_key(), []
    for i, text in enumerate(REQUESTS):
        sid = f"bench-{args.label}-{int(time.time())}-{i}"
        wall, answer = _ask(key, sid, text)
        log = subprocess.run(
            ["docker", "exec", "hermes", "cat", "/opt/data/logs/agent.log"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
        rows.append((text, wall, parse_agent_log(log, sid), answer))
    print(f"\n### Hermes benchmark: {args.label}\n")
    print("| Request | Wall s | Model calls | Model s | Answer |\n|---|---:|---:|---:|---|")
    for text, wall, stats, answer in rows:
        print(f"| {text} | {wall} | {stats['api_calls']} | {stats['llm_s']} | {answer[:80]} |")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/household/tools && ../../.venv/bin/python -m pytest -q test_hermes_bench.py`
Expected: `2 passed`

- [ ] **Step 5: Benchmark before the change**

Run: `scp -4 -q household/tools/hermes_bench.py behindtheproduct@reachy-pi.local:~/ && ssh -4 behindtheproduct@reachy-pi.local 'python3 ~/hermes_bench.py --label before'`
Expected: a 4-row table. Lookups are likely around 10–17 s with 4–5 model calls. Save the table for RESULTS.md.

- [ ] **Step 6: Add the household data map to SOUL.md**

Append to `household/hermes/SOUL.md`:
```markdown
## Household data
Household lists and notes are plain Markdown files in /opt/data, one item per line:
- Grocery list: /opt/data/household-grocery-list.md
- General notes: /opt/data/household-notes.md
- Any other list: /opt/data/household-<name>-list.md (create it when first asked)
For list and note requests, go straight to the file: read it, or edit it, then answer. Do not search for the files, list directories or open skills first. A list lookup should take one file read and one reply.
```

- [ ] **Step 7: Deploy and benchmark after the change**

Run: `household/deploy/deploy-pi.sh && ssh -4 behindtheproduct@reachy-pi.local 'python3 ~/hermes_bench.py --label after'`
Expected: lookups take 2 model calls and about 6 s or less. Edits take 2–3 calls. If lookups still take 4+ calls, check `docker exec hermes grep -h "bench-after" /opt/data/logs/agent.log` to see which tools it still reaches for, tighten the SOUL.md wording, and re-run. Record both tables in `voice/spike/RESULTS.md` under `## Hermes quick lookups`.

- [ ] **Step 8: Commit**

```bash
git add household/tools/hermes_bench.py household/tools/test_hermes_bench.py household/hermes/SOUL.md voice/spike/RESULTS.md
git commit -m "Hermes: household data map in SOUL.md and a quick-lookup benchmark

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Results and decision gate

**Files:**
- Modify: `voice/spike/RESULTS.md` (add a decision section)
- Modify: `docs/superpowers/specs/2026-10-05-reachy-voice-bakeoff-design.md` (the "Open questions resolved by the spike" section)

- [ ] **Step 1: Write the comparison and the gate decision**

Append to `RESULTS.md` a `## Decision` section with a table. Rows: median and max first-audio latency, speech during the tool, natural pause on result, barge-in, voice chosen, naturalness score and cost per minute (Gemini ≈ $0.023, gpt-live-1 $0.05). Columns: Gemini and OpenAI. Then apply these rules:
- **Both pass** (both talk during the tool, results land at a pause, barge-in works): Plan 2 builds the full bake-off as specified.
- **One fails**: Plan 2 builds only the passing engine behind the `VoiceEngine` interface. The other is retested in a month.
- **Both fail talk-while-tool**: stop. Revisit the design with the user before Plan 2. The fallback is our own filler speech plus deferred delivery.

- [ ] **Step 2: Update the spec's open questions with answers**

Replace each bullet under "Open questions resolved by the spike" with the measured answer and a link to `voice/spike/RESULTS.md`.

- [ ] **Step 3: Commit and push**

```bash
git add voice/spike/RESULTS.md docs/superpowers/specs/2026-10-05-reachy-voice-bakeoff-design.md
git commit -m "voice spike: results and Plan 2 gate decision

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 4: Hand back to the user**

Report the decision table and recommendation, and ask for approval to write Plan 2.
