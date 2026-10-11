# Reachy Voice App Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working household voice assistant on the robot. A local wake word ("Hey Jarvis" for now) opens a natural, fast conversation on Gemini 3.8 Live or OpenAI gpt-live-1 (chosen by config, or alternating per conversation for the bake-off). Real work goes to Hermes without dead air, quick household lookups take a faster lane, and the whole thing runs as a systemd service on the robot.

**Architecture:** A new `reachy_voice` Python package in `voice/` runs on the robot in its own venv, layered over `/venvs/apps_venv` the same way the spike's was. A main loop feeds mic frames to an openWakeWord detector. On a wake word, it opens a `VoiceSession` that wires the robot's audio to a `VoiceEngine` (Gemini or OpenAI, behind one interface) and runs Hermes hand-offs in the background. Small, pure units decide speaking state, latency, lanes, turn segmentation and when to close, and these are unit-tested on the Mac. The engines and the session are tested against fakes.

**Tech Stack:** Python 3.12 on the robot (uv-managed CPython; `/opt/uv/uv`), `google-genai==2.28.0`, `websockets` 15 and `httpx` 0.28 (both from apps_venv), `soxr==1.1.0`, `openwakeword==0.6.0` (ONNX inference via the robot's onnxruntime 1.27), numpy/scipy, `reachy_mini` SDK 1.11.0, and systemd. Mac tests run in the repo `.venv` (Python 3.13) with pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-reachy-voice-bakeoff-design.md`, plus the spike results and the "Lessons for Plan 2" in `voice/spike/RESULTS.md`.

**Scope split (agreed with the user 2026-10-11):**
- **Plan 2 (this plan):** wake word, both engines, the Hermes hand-off and fast lane, metrics logging, and the robot service.
- **Plan 3:** body language (emotions, speech-driven head motion, face tracking), the bake-off scorecard and spoken verdicts, packaging as an installable Reachy app, a custom "Hey Reachy" wake model, and re-opening a session for late answers.

**Deliberate simplification vs the spec:** the spec has a PendingAnswers component that re-opens a session to speak late answers. This plan doesn't build it. Instead, a session stays open while any hand-off is pending, capped by `PENDING_MAX_S` (default 300 s). Re-opening moves to Plan 3.

Also deferred to Plan 3, which owns the body and the bake-off:
- On a failed connection, the spec says retry once, then fall back. This plan falls back to the other engine straight away.
- The spoken "I lost my train of thought" line and the sad antenna pose are replaced by an error chime.
- The "use the other voice" voice command is not built.
- The scorecard and spoken verdicts are not built. The JSONL logs written here are their input.

## Global Constraints

- The repo is **public**. Never commit API keys, household names or personal details. Keys live only on the robot in `~/reachy-voice/voice.env` (mode 600), which is built on the robot from the conversation app's `.env` at `/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env` (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `HOME_AGENT_URL`, `HOME_AGENT_KEY`).
- Do not install or upgrade anything in `/venvs/apps_venv`. The app's venv is `~/reachy-voice/.venv`, layered on apps_venv with a `.pth` that runs `import site; site.addsitedir('/venvs/apps_venv/lib/python3.12/site-packages')`.
- `voice/spike/` is a frozen record. `reachy_voice` must not import from `spike`; port the code instead.
- Robot audio: mic and speaker run at 16 kHz float32 with 2 identical channels. Mic frames are `(1024, 2)`. `push_audio_sample` plays, and `media.audio.clear_player()` flushes. **Never push an empty array** (it segfaults GStreamer).
- Engines:
  - **Gemini:** `gemini-3.8-live`, input `audio/pcm;rate=16000`, output 24 kHz (resample with soxr streaming). Declare the tool with **explicit** `behavior=NON_BLOCKING` and deliver results with `scheduling=WHEN_IDLE`. Pin English with `SpeechConfig(language_code="en-US")` and in the persona.
  - **OpenAI:** `gpt-live-1` at `wss://api.openai.com/v1/live/sessions`, `audio/pcm` at 16000 both ways, client delegation, results via `session.commentary.append`, and close with `session.close`, then wait up to 5 s for `session.closed`.
- **No local barge-in or reply dropping for OpenAI.** The model handles being talked over. Gemini's `interrupted` event clears the speaker.
- **"Robot is speaking" comes from voiced output samples, never from audio arriving.** gpt-live-1 streams silence continuously. A chunk is voiced if its RMS is ≥ 0.01.
- **One latency metric for both engines:** from the last voiced mic frame (RMS ≥ `SPEECH_THRESHOLD`, default 0.015, calibrated 2026-10-11) to the scheduled start of the first voiced output chunk.
- Hermes is at `HOME_AGENT_URL` (`http://<pi>:8642`) and is called with `POST /v1/chat/completions`, `model: "hermes-agent"`, `Authorization: Bearer <HOME_AGENT_KEY>`, `X-Hermes-Session-Id` and `X-Hermes-Session-Key: reachy-household`.
  - **Quick lane:** also send `"model": QUICK_MODEL` (default `gpt-5.4-nano`) and `"provider": QUICK_PROVIDER` (default `openai-api`). Hermes always honours an explicit provider. The quick lane times out after 90 s.
  - **Task lane:** the default model, with a 300 s timeout.
- **Wake word:** openWakeWord 0.6.0 on ONNX (`inference_framework="onnx"`), model `hey_jarvis`, threshold 0.5. It takes int16 at 16 kHz in 1280-sample (80 ms) chunks.
- The robot runs one media owner at a time. The service's `ExecStartPre` stops the daemon's current app. The conversation app stays off (startup app `null`).
- SSH: `ssh -4 pollen@reachy-mini.local` (robot) and `ssh -4 behindtheproduct@reachy-pi.local` (Pi).
- Mac tests: `cd voice && ../.venv/bin/python -m pytest -q`. New test files are named `voice/tests/test_rv_*.py` so their basenames don't collide with the spike's tests.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **TV or background speech after a wake word keeps the session alive forever.** A hard `MAX_SESSION_S` cap (default 600) closes it. Tested in Task 3 (policy) and Task 9 (session).
2. **Hermes is down or slow.** Reachy says a spoken fallback instead of hanging, and a pending hand-off can't hold a session open past `PENDING_MAX_S`. Tested in Task 5 (client errors), Task 3 (pending timeout) and Task 9 (fallback delivered).
3. **The engine connection drops mid-conversation.** The session ends cleanly and the robot goes back to listening for the wake word, with no crash loop. Tested in Tasks 7 and 8 (receive loop ends) and Task 9 (`engine_closed`).
4. **OpenAI audio arrives faster than real time.** The speaker queue stays bounded by dropping silent chunks once 3 s are queued. Tested in Task 3 (`OutputActivity`).
5. **The wake word re-triggers on Reachy's own goodbye chime or speech.** A cooldown after each session ignores detections for 1.5 s. Tested in Task 6.

---

### Task 1: De-risk the wake word on the robot

**Files:**
- Create: `voice/reachy_voice/requirements.txt`
- Create: `voice/deploy/deploy-voice.sh`
- Create: `voice/tools/wake_check.py`

**Interfaces:**
- Produces:
  - `voice/deploy/deploy-voice.sh` (run from the Mac; idempotent). It creates `~/reachy-voice/{reachy_voice,tools,logs}` on the robot, rsyncs code, builds `~/reachy-voice/.venv` layered on apps_venv, installs requirements and openWakeWord, and downloads the `hey_jarvis` model.
  - `voice/tools/wake_check.py`, run on the robot, which reports wake scores for a synthesised phrase.
  - Task 10 extends `deploy-voice.sh` with the service install.

- [ ] **Step 1: Write the requirements and deploy script**

`voice/reachy_voice/requirements.txt`:
```
google-genai==2.28.0
soxr==1.1.0
tqdm
requests
```

`voice/deploy/deploy-voice.sh`:
```bash
#!/usr/bin/env bash
# Deploy reachy_voice to the robot and build its venv. Run from the Mac; idempotent.
# The venv layers on /venvs/apps_venv (reachy_mini, numpy, scipy, httpx, websockets,
# onnxruntime, GStreamer) without installing anything into it.
set -euo pipefail
ROBOT="${ROBOT:-pollen@reachy-mini.local}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # voice/

ssh -4 "$ROBOT" 'mkdir -p ~/reachy-voice/reachy_voice ~/reachy-voice/tools ~/reachy-voice/logs'
rsync -a --delete --exclude '__pycache__' -e "ssh -4" "$HERE/reachy_voice/" "$ROBOT:reachy-voice/reachy_voice/"
rsync -a --delete --exclude '__pycache__' -e "ssh -4" "$HERE/tools/" "$ROBOT:reachy-voice/tools/"
ssh -4 "$ROBOT" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/reachy-voice
PY=$(ls -d /home/pollen/.local/share/uv/python/cpython-3.12.*-linux-aarch64-gnu/bin/python3 | tail -1)
[ -x .venv/bin/python ] || /opt/uv/uv venv --python "$PY" .venv
echo "import site; site.addsitedir('/venvs/apps_venv/lib/python3.12/site-packages')" \
  > .venv/lib/python3.12/site-packages/zz_apps_venv.pth
/opt/uv/uv pip install --quiet --python .venv/bin/python -r reachy_voice/requirements.txt
# openwakeword 0.6.0 pins tflite-runtime on Linux, which has no cp312 aarch64 wheel; we use ONNX.
/opt/uv/uv pip install --quiet --python .venv/bin/python --no-deps openwakeword==0.6.0
.venv/bin/python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])"
.venv/bin/python -c "import google.genai, soxr, openwakeword, reachy_mini; print('voice venv ok')"
df -h / | tail -1
REMOTE
```

- [ ] **Step 2: Write the wake check tool**

`voice/tools/wake_check.py`:
```python
"""Synthesise a phrase with OpenAI TTS and report openWakeWord scores for it.
Run on the robot:  .venv/bin/python tools/wake_check.py "Hey Jarvis, what's the weather?"
Needs OPENAI_API_KEY in the environment."""

import os
import sys
import time

import httpx
import numpy as np
from scipy.signal import resample_poly
from openwakeword.model import Model


def synthesise(text: str) -> np.ndarray:
    r = httpx.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": "gpt-4o-mini-tts", "voice": "alloy", "input": text, "response_format": "pcm"},
        timeout=60,
    )
    r.raise_for_status()
    pcm24 = np.frombuffer(r.content, dtype="<i2").astype(np.float32)
    return resample_poly(pcm24, 2, 3).astype(np.int16)  # 24 kHz -> 16 kHz


def main(text: str) -> None:
    model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    name = next(iter(model.models))
    audio = np.concatenate([np.zeros(16000, np.int16), synthesise(text), np.zeros(16000, np.int16)])
    scores, times = [], []
    for i in range(0, len(audio) - 1279, 1280):
        start = time.perf_counter()
        scores.append(model.predict(audio[i : i + 1280])[name])
        times.append((time.perf_counter() - start) * 1000)
    print(f"model={name} text={text!r} max_score={max(scores):.3f} ms_per_80ms_frame={np.mean(times):.1f}")


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 3: Deploy and run the checks**

Run: `chmod +x voice/deploy/deploy-voice.sh && voice/deploy/deploy-voice.sh`
Expected: ends with `voice venv ok` and a `df` line.

If the `openwakeword` import fails with a missing module, add exactly that module to `requirements.txt` and re-run. For example, `scikit-learn` would need `scikit-learn==<latest with cp312 aarch64 wheel>`. If `download_models` doesn't accept a list, run `u.download_models()` instead. If the model still won't load on ONNX, STOP and report BLOCKED with the error.

Run:
```bash
ssh -4 pollen@reachy-mini.local 'cd ~/reachy-voice && set -a && . /venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env && set +a && .venv/bin/python tools/wake_check.py "Hey Jarvis, what is the weather today?" && .venv/bin/python tools/wake_check.py "Hey there, what is the weather today?" && .venv/bin/python tools/wake_check.py "Turn the volume down on the television please."'
```
Expected:
- The first line has `max_score` ≥ 0.5.
- The other two lines have `max_score` < 0.5.
- `ms_per_80ms_frame` is well under 80 (target < 20).

Record the three lines in the commit message body.

- [ ] **Step 4: Commit**

```bash
git add voice/reachy_voice/requirements.txt voice/deploy/deploy-voice.sh voice/tools/wake_check.py
git commit -m "reachy_voice: deploy script, venv and wake-word check

<paste the three wake_check result lines here>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Package foundation (config, audio, log)

**Files:**
- Create: `voice/reachy_voice/__init__.py` (empty), `voice/reachy_voice/config.py`, `voice/reachy_voice/audio.py`, `voice/reachy_voice/log.py`
- Test: `voice/tests/test_rv_config.py`, `voice/tests/test_rv_audio.py`

**Interfaces:**
- Produces:
  - `reachy_voice.config.Settings`, a frozen dataclass with fields:
    - `engine` (`"gemini" | "openai" | "alternate"`)
    - `gemini_model`, `gemini_voice`, `openai_model`, `openai_voice`
    - `wake_model`, `wake_threshold`, `speech_threshold`
    - `idle_timeout_s`, `pending_max_s`, `max_session_s`
    - `home_agent_url`, `home_agent_key`, `quick_model`, `quick_provider`
    - `log_dir`, `gemini_api_key`, `openai_api_key`
    - `.has_engine(name: str) -> bool`
  - `reachy_voice.config.load_settings(env: Mapping[str, str]) -> Settings`, which raises `ValueError` on a bad engine or missing keys.
  - `reachy_voice.audio.mic_to_pcm16(frame) -> bytes`
  - `reachy_voice.audio.pcm16_to_float(data: bytes, src_rate: int, dst_rate: int = 16000) -> np.ndarray`
  - `reachy_voice.audio.rms(frame) -> float`
  - `reachy_voice.audio.StreamResampler(src_rate, dst_rate=16000)` with `.process(bytes) -> np.ndarray` and `.flush() -> np.ndarray`
  - `reachy_voice.log.JsonlLog(path)` with `.write(event: str, **fields)`. It creates the parent directory.

- [ ] **Step 1: Install the Mac test dependencies**

Run: `/Users/painter/palettepal/reachy-mini-stack/.venv/bin/python -m pip install -q "google-genai==2.28.0" "soxr==1.1.0" "websockets>=15,<16"`
Expected: exit 0.

- [ ] **Step 2: Write the failing tests**

`voice/tests/test_rv_config.py`:
```python
import pytest

from reachy_voice.config import load_settings

KEYS = {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"}


def test_defaults_with_both_keys():
    s = load_settings(KEYS)
    assert s.engine == "alternate"
    assert s.gemini_model == "gemini-3.8-live" and s.openai_model == "gpt-live-1"
    assert s.wake_model == "hey_jarvis" and s.wake_threshold == 0.5
    assert s.speech_threshold == 0.015
    assert (s.idle_timeout_s, s.pending_max_s, s.max_session_s) == (30.0, 300.0, 600.0)
    assert (s.quick_model, s.quick_provider) == ("gpt-5.4-nano", "openai-api")


def test_overrides_from_env():
    s = load_settings({**KEYS, "VOICE_ENGINE": " OpenAI ", "SPEECH_THRESHOLD": "0.02", "IDLE_TIMEOUT_S": "45",
                       "HOME_AGENT_URL": "http://pi:8642/", "HOME_AGENT_KEY": "k"})
    assert s.engine == "openai" and s.speech_threshold == 0.02 and s.idle_timeout_s == 45.0
    assert s.home_agent_url == "http://pi:8642/" and s.home_agent_key == "k"


def test_bad_engine_is_rejected():
    with pytest.raises(ValueError, match="VOICE_ENGINE"):
        load_settings({**KEYS, "VOICE_ENGINE": "alexa"})


def test_missing_key_for_chosen_engine_is_rejected():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_settings({"GEMINI_API_KEY": "g", "VOICE_ENGINE": "alternate"})
    assert load_settings({"GEMINI_API_KEY": "g", "VOICE_ENGINE": "gemini"}).engine == "gemini"


def test_has_engine_reflects_keys():
    s = load_settings({"GEMINI_API_KEY": "g", "VOICE_ENGINE": "gemini"})
    assert s.has_engine("gemini") and not s.has_engine("openai")
```

`voice/tests/test_rv_audio.py`:
```python
import json

import numpy as np
import soxr

from reachy_voice.audio import StreamResampler, mic_to_pcm16, pcm16_to_float, rms
from reachy_voice.log import JsonlLog


def test_mic_to_pcm16_first_channel_clipped():
    frame = np.array([[0.5, -1.0], [-0.5, 1.0], [2.0, 0.0]], dtype=np.float32)
    assert np.frombuffer(mic_to_pcm16(frame), dtype="<i2").tolist() == [16383, -16383, 32767]


def test_pcm16_to_float_passthrough_and_resample():
    pcm = np.array([0, 16384, -16384], dtype="<i2").tobytes()
    assert np.allclose(pcm16_to_float(pcm, 16000), [0.0, 0.5, -0.5])
    assert pcm16_to_float(np.zeros(2400, "<i2").tobytes(), 24000).shape == (1600,)


def test_rms_uses_first_channel():
    frame = np.stack([np.full(100, 0.1), np.zeros(100)], axis=1).astype(np.float32)
    assert abs(rms(frame) - 0.1) < 1e-6
    assert rms(np.zeros(0, np.float32)) == 0.0


def test_stream_resampler_matches_one_shot():
    t = np.arange(24000) / 24000
    sine = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    r = StreamResampler(24000, 16000)
    cuts = [0, 1000, 4100, 9000, 15000, 24000]
    out = np.concatenate([r.process(sine[a:b].tobytes()) for a, b in zip(cuts, cuts[1:])] + [r.flush()])
    assert abs(len(out) - 16000) <= 32
    ref = soxr.resample(sine.astype(np.float32) / 32768.0, 24000, 16000)
    assert np.allclose(out[2000:14000], ref[2000:14000], atol=1e-3)


def test_jsonl_log_creates_dir_and_appends(tmp_path):
    path = tmp_path / "sub" / "x.jsonl"
    log = JsonlLog(str(path))
    log.write("wake", engine="gemini")
    log.write("session_end", reason="idle")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["event"] for r in rows] == ["wake", "session_end"] and rows[0]["engine"] == "gemini"
    assert isinstance(rows[0]["ts"], float)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_config.py tests/test_rv_audio.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice'`

- [ ] **Step 4: Implement**

`voice/reachy_voice/__init__.py`: an empty file.

`voice/reachy_voice/config.py`:
```python
"""Settings from the environment (on the robot: ~/reachy-voice/voice.env)."""

from collections.abc import Mapping
from dataclasses import dataclass

ENGINES = ("gemini", "openai", "alternate")


@dataclass(frozen=True)
class Settings:
    engine: str = "alternate"
    gemini_model: str = "gemini-3.8-live"
    gemini_voice: str = "Kore"
    openai_model: str = "gpt-live-1"
    openai_voice: str = "marin"
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.5
    speech_threshold: float = 0.015
    idle_timeout_s: float = 30.0
    pending_max_s: float = 300.0
    max_session_s: float = 600.0
    home_agent_url: str = ""
    home_agent_key: str = ""
    quick_model: str = "gpt-5.4-nano"
    quick_provider: str = "openai-api"
    log_dir: str = "logs"
    gemini_api_key: str = ""
    openai_api_key: str = ""

    def has_engine(self, name: str) -> bool:
        return bool(self.gemini_api_key if name == "gemini" else self.openai_api_key if name == "openai" else False)


def load_settings(env: Mapping[str, str]) -> Settings:
    d = Settings()

    def text(name: str, default: str) -> str:
        value = env.get(name, "")
        return value.strip() if value and value.strip() else default

    def number(name: str, default: float) -> float:
        value = env.get(name, "")
        return float(value) if value and value.strip() else default

    s = Settings(
        engine=text("VOICE_ENGINE", d.engine).lower(),
        gemini_model=text("GEMINI_MODEL", d.gemini_model),
        gemini_voice=text("GEMINI_VOICE", d.gemini_voice),
        openai_model=text("OPENAI_LIVE_MODEL", d.openai_model),
        openai_voice=text("OPENAI_VOICE", d.openai_voice),
        wake_model=text("WAKE_MODEL", d.wake_model),
        wake_threshold=number("WAKE_THRESHOLD", d.wake_threshold),
        speech_threshold=number("SPEECH_THRESHOLD", d.speech_threshold),
        idle_timeout_s=number("IDLE_TIMEOUT_S", d.idle_timeout_s),
        pending_max_s=number("PENDING_MAX_S", d.pending_max_s),
        max_session_s=number("MAX_SESSION_S", d.max_session_s),
        home_agent_url=text("HOME_AGENT_URL", d.home_agent_url),
        home_agent_key=text("HOME_AGENT_KEY", d.home_agent_key),
        quick_model=text("QUICK_MODEL", d.quick_model),
        quick_provider=text("QUICK_PROVIDER", d.quick_provider),
        log_dir=text("VOICE_LOG_DIR", d.log_dir),
        gemini_api_key=text("GEMINI_API_KEY", ""),
        openai_api_key=text("OPENAI_API_KEY", ""),
    )
    if s.engine not in ENGINES:
        raise ValueError(f"VOICE_ENGINE must be one of {ENGINES}, got {s.engine!r}")
    needed = {"gemini": ["gemini"], "openai": ["openai"], "alternate": ["gemini", "openai"]}[s.engine]
    missing = [f"{n.upper()}_API_KEY" for n in needed if not s.has_engine(n)]
    if missing:
        raise ValueError(f"missing required settings: {', '.join(missing)}")
    return s
```

`voice/reachy_voice/audio.py`:
```python
"""Audio format conversion between the robot SDK and the voice engines."""

import numpy as np
from scipy.signal import resample_poly


def _mono(frame: np.ndarray) -> np.ndarray:
    # The robot mic delivers two identical channels; take the first.
    return frame[:, 0] if frame.ndim == 2 else frame


def mic_to_pcm16(frame: np.ndarray) -> bytes:
    """Robot mic float32 in [-1, 1], shape (n,) or (n, ch) -> mono 16-bit little-endian PCM."""
    return (np.clip(_mono(frame), -1.0, 1.0) * 32767).astype("<i2").tobytes()


def pcm16_to_float(data: bytes, src_rate: int, dst_rate: int = 16000) -> np.ndarray:
    """16-bit PCM -> float32 mono at dst_rate (one-shot; use StreamResampler for streams)."""
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if src_rate != dst_rate:
        g = int(np.gcd(src_rate, dst_rate))
        samples = resample_poly(samples, dst_rate // g, src_rate // g).astype(np.float32)
    return samples


def rms(frame: np.ndarray) -> float:
    mono = _mono(frame)
    return float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0


class StreamResampler:
    """Click-free streaming resampling of an engine's PCM16 output to the robot's rate."""

    def __init__(self, src_rate: int, dst_rate: int = 16000) -> None:
        self._passthrough = src_rate == dst_rate
        if not self._passthrough:
            import soxr

            self._stream = soxr.ResampleStream(src_rate, dst_rate, 1, dtype="float32")

    def process(self, data: bytes) -> np.ndarray:
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        if self._passthrough:
            return samples
        return np.asarray(self._stream.resample_chunk(samples), dtype=np.float32)

    def flush(self) -> np.ndarray:
        if self._passthrough:
            return np.zeros(0, dtype=np.float32)
        return np.asarray(self._stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True), dtype=np.float32)
```

`voice/reachy_voice/log.py`:
```python
"""One JSON object per line: the raw material for latency and bake-off analysis."""

import json
import os
import time


class JsonlLog:
    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def write(self, event: str, **fields) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, "ts": time.time(), **fields}) + "\n")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_config.py tests/test_rv_audio.py`
Expected: `10 passed`

- [ ] **Step 6: Commit**

```bash
git add voice/reachy_voice/__init__.py voice/reachy_voice/config.py voice/reachy_voice/audio.py voice/reachy_voice/log.py voice/tests/test_rv_config.py voice/tests/test_rv_audio.py
git commit -m "reachy_voice: settings, audio conversion and JSONL log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Speaking state, latency and session policy

**Files:**
- Create: `voice/reachy_voice/activity.py`, `voice/reachy_voice/policy.py`
- Test: `voice/tests/test_rv_activity.py`, `voice/tests/test_rv_policy.py`

**Interfaces:**
- Consumes: `reachy_voice.audio.rms`
- Produces:
  - `reachy_voice.activity.VOICED_RMS = 0.01`
  - `reachy_voice.activity.OutputActivity(voiced_rms=0.01, max_queue_s=3.0)` with:
    - `.accept(samples: np.ndarray, rate: int, now: float) -> tuple[bool, float | None]` returning (play it?, scheduled start if voiced)
    - `.is_speaking(now) -> bool`
    - `.voiced_end: float` (property)
    - `.queued_s(now) -> float`
    - `.clear(now)`
  - `reachy_voice.activity.UserSpeech(threshold=0.015)` with `.on_mic(level, now, robot_speaking)`, `.last_voice: float | None` and `.on_voiced_output(start: float) -> float | None` (the latency, once per user turn)
  - `reachy_voice.policy.SessionPolicy(idle_timeout_s=30.0, pending_max_s=300.0, max_session_s=600.0)` with `.should_close(now, opened_at, last_activity, pending_since: float | None) -> str | None`, which returns `"max_duration" | "pending_timeout" | "idle" | None`
  - `reachy_voice.policy.EngineChooser(mode)` with `.next() -> str`
  - `reachy_voice.policy.other_engine(name) -> str`
  - `reachy_voice.policy.choose_lane(request: str) -> str` (`"quick" | "task"`)

- [ ] **Step 1: Write the failing tests**

`voice/tests/test_rv_activity.py`:
```python
import numpy as np

from reachy_voice.activity import OutputActivity, UserSpeech

VOICED = np.full(1600, 0.2, np.float32)   # 0.1 s at 16 kHz
SILENT = np.zeros(1600, np.float32)


def test_silent_output_is_not_speaking():
    out = OutputActivity()
    assert out.accept(SILENT, 16000, now=0.0) == (True, None)
    assert not out.is_speaking(0.05)


def test_voiced_output_schedules_and_reports_start():
    out = OutputActivity()
    out.accept(SILENT, 16000, now=0.0)                 # queue ends at 0.1
    play, start = out.accept(VOICED, 16000, now=0.02)  # starts after the silence
    assert play and abs(start - 0.1) < 1e-9
    assert out.is_speaking(0.15) and not out.is_speaking(0.21)
    assert abs(out.voiced_end - 0.2) < 1e-9


def test_queue_is_bounded_for_faster_than_realtime_silence():
    out = OutputActivity(max_queue_s=0.3)
    accepted = [out.accept(SILENT, 16000, now=0.0)[0] for _ in range(10)]
    assert accepted[:3] == [True, True, True] and not any(accepted[3:])
    assert out.queued_s(0.0) <= 0.3 + 1e-9
    assert out.accept(VOICED, 16000, now=0.0)[0]       # speech is never dropped


def test_clear_stops_speaking():
    out = OutputActivity()
    out.accept(VOICED, 16000, now=0.0)
    out.clear(now=0.05)
    assert not out.is_speaking(0.06) and out.queued_s(0.06) == 0.0


def test_latency_from_last_user_voice_to_first_voiced_output():
    user = UserSpeech(threshold=0.015)
    user.on_mic(0.05, now=1.0, robot_speaking=False)
    user.on_mic(0.05, now=1.4, robot_speaking=False)
    user.on_mic(0.001, now=1.6, robot_speaking=False)
    assert user.on_voiced_output(2.5) == 1.1
    assert user.on_voiced_output(2.6) is None          # once per turn
    assert user.last_voice == 1.4


def test_mic_ignored_while_robot_speaks():
    user = UserSpeech()
    user.on_mic(0.5, now=1.0, robot_speaking=True)
    assert user.last_voice is None and user.on_voiced_output(1.2) is None
```

`voice/tests/test_rv_policy.py`:
```python
from reachy_voice.policy import EngineChooser, SessionPolicy, choose_lane, other_engine


def test_idle_close_after_quiet():
    p = SessionPolicy(idle_timeout_s=30, pending_max_s=300, max_session_s=600)
    assert p.should_close(now=40, opened_at=0, last_activity=20, pending_since=None) is None
    assert p.should_close(now=50, opened_at=0, last_activity=20, pending_since=None) == "idle"


def test_pending_handoff_keeps_session_open_until_cap():
    p = SessionPolicy(idle_timeout_s=30, pending_max_s=300, max_session_s=600)
    assert p.should_close(now=100, opened_at=0, last_activity=10, pending_since=50) is None
    assert p.should_close(now=360, opened_at=0, last_activity=10, pending_since=50) == "pending_timeout"


def test_max_duration_wins_even_with_constant_activity():
    p = SessionPolicy(idle_timeout_s=30, pending_max_s=300, max_session_s=600)
    assert p.should_close(now=600, opened_at=0, last_activity=599.9, pending_since=None) == "max_duration"


def test_engine_chooser_alternates_or_sticks():
    alt = EngineChooser("alternate")
    assert [alt.next() for _ in range(4)] == ["gemini", "openai", "gemini", "openai"]
    assert [EngineChooser("openai").next() for _ in range(2)] == ["openai", "openai"]
    assert other_engine("gemini") == "openai" and other_engine("openai") == "gemini"


def test_choose_lane():
    assert choose_lane("What's on the grocery list?") == "quick"
    assert choose_lane("add bread to the shopping list") == "quick"
    assert choose_lane("Plan a weekend trip to the coast with the kids") == "task"
    assert choose_lane("") == "task"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_activity.py tests/test_rv_policy.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.activity'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/activity.py`:
```python
"""What the robot and the person are doing, from audio levels.

Speaking state comes from voiced output samples, never from audio arriving:
gpt-live-1 streams silence continuously (spike lesson, voice/spike/RESULTS.md)."""

from dataclasses import dataclass

import numpy as np

from reachy_voice.audio import rms

VOICED_RMS = 0.01


@dataclass
class OutputActivity:
    voiced_rms: float = VOICED_RMS
    max_queue_s: float = 3.0
    _queue_end: float = 0.0
    _voiced_end: float = 0.0

    def queued_s(self, now: float) -> float:
        return max(0.0, self._queue_end - now)

    def accept(self, samples: np.ndarray, rate: int, now: float) -> tuple[bool, float | None]:
        """Decide whether to play a chunk. Silent chunks are dropped once max_queue_s is
        queued, which bounds the speaker queue if a stream runs faster than real time.
        Returns (play, scheduled start time if the chunk is voiced)."""
        voiced = rms(samples) >= self.voiced_rms
        if not voiced and self.queued_s(now) >= self.max_queue_s:
            return False, None
        start = max(self._queue_end, now)
        self._queue_end = start + len(samples) / rate
        if voiced:
            self._voiced_end = self._queue_end
            return True, start
        return True, None

    def is_speaking(self, now: float) -> bool:
        return now < self._voiced_end

    @property
    def voiced_end(self) -> float:
        return self._voiced_end

    def clear(self, now: float) -> None:
        self._queue_end = self._voiced_end = now


@dataclass
class UserSpeech:
    """The person's voice on the mic, and the one latency metric used for both engines:
    last voiced mic frame -> scheduled start of the robot's first voiced output."""

    threshold: float = 0.015
    last_voice: float | None = None
    _awaiting_reply: bool = False

    def on_mic(self, level: float, now: float, robot_speaking: bool) -> None:
        if robot_speaking or level < self.threshold:
            return
        self.last_voice = now
        self._awaiting_reply = True

    def on_voiced_output(self, start: float) -> float | None:
        if not self._awaiting_reply or self.last_voice is None:
            return None
        self._awaiting_reply = False
        return round(max(0.0, start - self.last_voice), 3)
```

`voice/reachy_voice/policy.py`:
```python
"""Small decisions: when a session ends, which engine runs next, which Hermes lane."""

import re
from dataclasses import dataclass

_QUICK = re.compile(r"\b(list|lists|note|notes|grocer\w*|shopping|what'?s on|add|remove)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SessionPolicy:
    idle_timeout_s: float = 30.0
    pending_max_s: float = 300.0
    max_session_s: float = 600.0

    def should_close(self, now: float, opened_at: float, last_activity: float, pending_since: float | None) -> str | None:
        if now - opened_at >= self.max_session_s:
            return "max_duration"  # a TV left on must not hold the session open forever
        if pending_since is not None:
            return "pending_timeout" if now - pending_since >= self.pending_max_s else None
        if now - last_activity >= self.idle_timeout_s:
            return "idle"
        return None


def other_engine(name: str) -> str:
    return "openai" if name == "gemini" else "gemini"


class EngineChooser:
    def __init__(self, mode: str) -> None:
        self._mode = mode
        self._next = "gemini"

    def next(self) -> str:
        if self._mode != "alternate":
            return self._mode
        name, self._next = self._next, other_engine(self._next)
        return name


def choose_lane(request: str) -> str:
    """Quick lane for household list/note lookups and edits; everything else is a task."""
    return "quick" if _QUICK.search(request or "") else "task"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_activity.py tests/test_rv_policy.py`
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/activity.py voice/reachy_voice/policy.py voice/tests/test_rv_activity.py voice/tests/test_rv_policy.py
git commit -m "reachy_voice: speaking state, latency metric and session policy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Engine interface, persona and OpenAI turn segmentation

**Files:**
- Create: `voice/reachy_voice/engines/__init__.py` (empty for now; Task 8 adds `make_engine`), `voice/reachy_voice/engines/base.py`, `voice/reachy_voice/persona.py`, `voice/reachy_voice/segment.py`
- Test: `voice/tests/test_rv_segment.py`

**Interfaces:**
- Produces:
  - `reachy_voice.engines.base.Delegation(call_id: str, request: str, lane: str)`, a dataclass
  - `reachy_voice.engines.base.EngineCallbacks`, a dataclass with callable fields:
    - `on_audio(samples: np.ndarray, now: float)` (float32, 16 kHz)
    - `on_user_text(text: str)`
    - `on_robot_text(text: str)`
    - `on_interrupted(now: float)`
    - `on_delegation(d: Delegation)`
    - `on_usage(usage: dict)`
    - `on_error(message: str)`
  - `reachy_voice.engines.base.VoiceEngine`, a Protocol with `name: str` and the async methods `start(cb: EngineCallbacks)`, `send_audio(frame: np.ndarray)`, `deliver(call_id: str, text: str)`, `close()` and `wait_closed()`
  - `reachy_voice.persona`: `PERSONA: str`, `TOOL_NAME = "ask_home_agent"`, `TOOL_DESCRIPTION: str`, `TOOL_PARAMS: dict` and `FALLBACK_REPLY: str`
  - `reachy_voice.segment.TurnSegmenter(max_chars=500)` with `.on_user_text(delta)`, `.on_robot_text(delta)` and `.request() -> str`

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_segment.py`:
```python
from reachy_voice.segment import TurnSegmenter


def test_request_is_users_words_since_robot_last_spoke():
    s = TurnSegmenter()
    s.on_user_text(" Hi Reachy")
    s.on_robot_text(" Hello!")
    s.on_user_text(" What's on")
    s.on_user_text(" the grocery list")
    assert s.request() == "What's on the grocery list"


def test_robot_acknowledgement_before_delegation_keeps_the_request():
    s = TurnSegmenter()
    s.on_user_text(" What's on the grocery list")
    s.on_robot_text(" Checking now.")   # gpt-live-1 acks before the delegation event
    assert s.request() == "What's on the grocery list"


def test_blank_robot_text_does_not_split_turns():
    s = TurnSegmenter()
    s.on_user_text(" add")
    s.on_robot_text("  ")
    s.on_user_text(" bread")
    assert s.request() == "add bread"


def test_request_is_capped():
    s = TurnSegmenter(max_chars=10)
    s.on_user_text("x" * 50)
    assert len(s.request()) == 10
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_segment.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.segment'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/engines/__init__.py`: an empty file.

`voice/reachy_voice/engines/base.py`:
```python
"""The interface every voice engine implements, so the session doesn't care which runs."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Delegation:
    call_id: str
    request: str
    lane: str  # "quick" | "task"


@dataclass
class EngineCallbacks:
    on_audio: Callable[[np.ndarray, float], None]   # float32 mono @16 kHz, monotonic now
    on_user_text: Callable[[str], None]
    on_robot_text: Callable[[str], None]
    on_interrupted: Callable[[float], None]
    on_delegation: Callable[[Delegation], None]
    on_usage: Callable[[dict], None]
    on_error: Callable[[str], None]


class VoiceEngine(Protocol):
    name: str

    async def start(self, cb: EngineCallbacks) -> None: ...
    async def send_audio(self, frame: np.ndarray) -> None: ...
    async def deliver(self, call_id: str, text: str) -> None: ...
    async def close(self) -> None: ...
    async def wait_closed(self) -> None: ...
```

`voice/reachy_voice/persona.py`:
```python
"""One persona and tool for both engines, so the bake-off compares engines only."""

PERSONA = """You are Reachy, a small, friendly robot on a desk in a family home. You talk with the
people who live here and their guests.
Always speak English, even if what you heard sounded like another language. If you didn't catch
something, ask the person to repeat it.
Keep replies short and warm: one or two sentences. If someone talks over you, stop and listen.
For the household's lists, notes and reminders, and for research or planning, hand the request
to the home agent. When you do, say a brief acknowledgement straight away (for example "Sure,
let me check") and keep the conversation going. When the answer arrives, share it at a natural
pause. Never invent the answer.
Never send messages, buy or book anything, or share personal details without a clear spoken
yes from the person."""

TOOL_NAME = "ask_home_agent"
TOOL_DESCRIPTION = (
    "Hand a request to the household's home agent, which keeps the household's lists and notes "
    "and can research, plan and set reminders. It can take up to a minute; keep talking while it works."
)
TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "request": {"type": "string", "description": "What the person wants, in their own words."},
        "lane": {
            "type": "string",
            "enum": ["quick", "task"],
            "description": "quick: look up or change a household list or note. task: research, planning or anything with several steps.",
        },
    },
    "required": ["request"],
}

FALLBACK_REPLY = "I couldn't reach the home agent just now. Want me to try again in a minute?"
```

`voice/reachy_voice/segment.py`:
```python
"""gpt-live-1 transcripts carry no turn boundaries, and its delegation event carries no task
text. The request is what the person said since the robot last spoke."""


class TurnSegmenter:
    def __init__(self, max_chars: int = 500) -> None:
        self._max = max_chars
        self._current = ""
        self._robot_spoke = False

    def on_user_text(self, delta: str) -> None:
        if self._robot_spoke:  # the person has started a new turn
            self._current = ""
            self._robot_spoke = False
        self._current = (self._current + delta)[-self._max:]

    def on_robot_text(self, delta: str) -> None:
        if delta.strip():
            self._robot_spoke = True

    def request(self) -> str:
        return self._current.strip()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_segment.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/engines/__init__.py voice/reachy_voice/engines/base.py voice/reachy_voice/persona.py voice/reachy_voice/segment.py voice/tests/test_rv_segment.py
git commit -m "reachy_voice: engine interface, shared persona and OpenAI turn segmentation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Hermes client with quick and task lanes

**Files:**
- Create: `voice/reachy_voice/hermes.py`
- Test: `voice/tests/test_rv_hermes.py`

**Interfaces:**
- Produces:
  - `reachy_voice.hermes.HermesError(Exception)`
  - `reachy_voice.hermes.HermesClient(url: str, key: str, quick_model: str, quick_provider: str, transport: httpx.AsyncBaseTransport | None = None)` with `async .ask(request: str, asked_by: str, lane: str, session_id: str) -> str` and `async .aclose()`
  - `QUICK_TIMEOUT_S = 90.0` and `TASK_TIMEOUT_S = 300.0`

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_hermes.py`:
```python
import asyncio
import json

import httpx
import pytest

from reachy_voice.hermes import HermesClient, HermesError


def make(handler, url="http://pi:8642/", key="k"):
    return HermesClient(url, key, "gpt-5.4-nano", "openai-api", transport=httpx.MockTransport(handler))


def reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": f"  {text}  "}}]})


def test_quick_lane_sends_model_and_provider_and_headers():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return reply("Milk and eggs.")

    out = asyncio.run(make(handler).ask("what's on the list", "Sam", "quick", "sess-1"))
    assert out == "Milk and eggs."
    assert seen["url"] == "http://pi:8642/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer k"
    assert seen["headers"]["x-hermes-session-id"] == "sess-1"
    assert seen["headers"]["x-hermes-session-key"] == "reachy-household"
    assert seen["body"]["model"] == "gpt-5.4-nano" and seen["body"]["provider"] == "openai-api"
    assert seen["body"]["messages"][0]["content"] == "[Asked by Sam, via Reachy] what's on the list"


def test_task_lane_uses_gateway_default_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return reply("Planned.")

    asyncio.run(make(handler).ask("plan a trip", "", "task", "s"))
    assert seen["body"]["model"] == "hermes-agent" and "provider" not in seen["body"]
    assert seen["body"]["messages"][0]["content"].startswith("[Asked by unknown, via Reachy]")


@pytest.mark.parametrize("response", [httpx.Response(500, text="boom"), httpx.Response(200, json={"oops": 1})])
def test_bad_responses_raise_hermes_error(response):
    with pytest.raises(HermesError):
        asyncio.run(make(lambda r: response).ask("x", "a", "quick", "s"))


def test_connection_failure_raises_hermes_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(HermesError, match="ConnectError"):
        asyncio.run(make(handler).ask("x", "a", "task", "s"))


def test_unconfigured_client_raises():
    with pytest.raises(HermesError, match="not configured"):
        asyncio.run(make(lambda r: reply("x"), url="", key="").ask("x", "a", "quick", "s"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_hermes.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.hermes'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/hermes.py`:
```python
"""Client for the household's Hermes agent on the Pi (LAN only, bearer key)."""

import httpx

QUICK_TIMEOUT_S = 90.0
TASK_TIMEOUT_S = 300.0


class HermesError(Exception):
    pass


class HermesClient:
    def __init__(self, url: str, key: str, quick_model: str, quick_provider: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = url.rstrip("/")
        self._key = key
        self._quick_model = quick_model
        self._quick_provider = quick_provider
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(TASK_TIMEOUT_S, connect=5.0))

    async def ask(self, request: str, asked_by: str, lane: str, session_id: str) -> str:
        if not self._url or not self._key:
            raise HermesError("home agent not configured")
        body: dict = {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": f"[Asked by {asked_by or 'unknown'}, via Reachy] {request}"}],
        }
        if lane == "quick":
            # An explicit provider makes Hermes honour the per-request model (fast lane).
            body.update(model=self._quick_model, provider=self._quick_provider)
        headers = {
            "Authorization": f"Bearer {self._key}",
            "X-Hermes-Session-Id": session_id,
            "X-Hermes-Session-Key": "reachy-household",
        }
        timeout = QUICK_TIMEOUT_S if lane == "quick" else TASK_TIMEOUT_S
        try:
            response = await self._client.post(f"{self._url}/v1/chat/completions", json=body, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise HermesError(f"{type(exc).__name__}: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_hermes.py`
Expected: `6 passed`

- [ ] **Step 5: Check the quick lane against the real Pi**

Run:
```bash
ssh -4 behindtheproduct@reachy-pi.local 'K=$(grep ^API_SERVER_KEY= ~/.config/household/agent.env | cut -d= -f2-); for body in "{\"model\":\"gpt-5.4-nano\",\"provider\":\"openai-api\",\"messages\":[{\"role\":\"user\",\"content\":\"[Asked by a tester, via Reachy] What is on the grocery list?\"}]}" "{\"model\":\"hermes-agent\",\"messages\":[{\"role\":\"user\",\"content\":\"[Asked by a tester, via Reachy] What is on the grocery list?\"}]}"; do curl -s -o /tmp/r.json -w "%{time_total}s\n" -m 120 http://127.0.0.1:8642/v1/chat/completions -H "Authorization: Bearer $K" -H "Content-Type: application/json" -H "X-Hermes-Session-Id: lane-check-$RANDOM" -d "$body"; python3 -c "import json;print(json.load(open(\"/tmp/r.json\"))[\"choices\"][0][\"message\"][\"content\"][:120])"; done'
```
Expected: both answers list the grocery items. Record both times in the commit body.

If the quick lane is not faster, or gives a wrong answer, say so in the commit body and set the default `QUICK_MODEL` to `gpt-5.4-mini` in `config.py` and in its test.

- [ ] **Step 6: Commit**

```bash
git add voice/reachy_voice/hermes.py voice/tests/test_rv_hermes.py
git commit -m "reachy_voice: Hermes client with quick and task lanes

<quick lane: Xs, task lane: Ys on the Pi>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Wake word detector

**Files:**
- Create: `voice/reachy_voice/wake.py`
- Test: `voice/tests/test_rv_wake.py`

**Interfaces:**
- Produces:
  - `reachy_voice.wake.WakeWord(model, threshold=0.5, cooldown_s=1.5)`, where `model` has `.predict(np.int16[1280]) -> dict[str, float]` and `.reset()`
  - `WakeWord.feed(frame: np.ndarray, now: float) -> bool`
  - `WakeWord.reset(now: float)`, which starts the cooldown
  - `reachy_voice.wake.load_wake_model(name: str)`, an openWakeWord ONNX model (imported lazily)

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_wake.py`:
```python
import numpy as np

from reachy_voice.wake import WakeWord


class FakeModel:
    def __init__(self, scores):
        self.scores = list(scores)
        self.chunks = []
        self.resets = 0

    def predict(self, chunk):
        self.chunks.append(chunk)
        return {"hey_jarvis": self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        self.resets += 1


def frame(value=0.1):
    return np.full((1024, 2), value, np.float32)


def test_buffers_1024_sample_frames_into_1280_int16_chunks():
    m = FakeModel([])
    w = WakeWord(m)
    for _ in range(5):          # 5 * 1024 = 5120 = 4 * 1280
        w.feed(frame(0.5), now=0.0)
    assert len(m.chunks) == 4
    assert all(c.dtype == np.int16 and c.shape == (1280,) for c in m.chunks)
    assert m.chunks[0][0] == int(0.5 * 32767)


def test_detection_resets_model_and_buffer():
    m = FakeModel([0.1, 0.9])
    w = WakeWord(m, threshold=0.5)
    assert not w.feed(frame(), now=0.0)   # 1024 buffered, no chunk scored yet
    assert not w.feed(frame(), now=0.1)   # 2048 -> chunk 1 scored 0.1 (< 0.5)
    assert w.feed(frame(), now=0.2)       # 3072 -> chunk 2 scored 0.9 -> detected
    assert m.resets == 1
    assert not w.feed(frame(), now=0.3)   # buffer was cleared; 1024 buffered, nothing scored


def test_cooldown_ignores_detections_after_reset():
    m = FakeModel([0.9, 0.9, 0.9, 0.9])
    w = WakeWord(m, threshold=0.5, cooldown_s=1.5)
    w.reset(now=10.0)
    hits = [w.feed(frame(), now=t) for t in (10.1, 10.5, 11.0)]
    assert not any(hits)
    m.scores = [0.9]
    assert any(w.feed(frame(), now=12.0) for _ in range(2))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_wake.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.wake'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/wake.py`:
```python
"""Local wake-word detection: nothing leaves the robot until it fires."""

import numpy as np

CHUNK = 1280  # openWakeWord expects 80 ms of 16 kHz int16


class WakeWord:
    def __init__(self, model, threshold: float = 0.5, cooldown_s: float = 1.5) -> None:
        self._model = model
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._quiet_until = 0.0
        self._buf = np.zeros(0, dtype=np.int16)

    def feed(self, frame: np.ndarray, now: float) -> bool:
        mono = frame[:, 0] if frame.ndim == 2 else frame
        self._buf = np.concatenate([self._buf, (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)])
        hit = False
        while len(self._buf) >= CHUNK:
            chunk, self._buf = self._buf[:CHUNK], self._buf[CHUNK:]
            if max(self._model.predict(chunk).values(), default=0.0) >= self._threshold:
                hit = True
        if not hit:
            return False
        self._model.reset()
        self._buf = np.zeros(0, dtype=np.int16)
        return now >= self._quiet_until  # ignore Reachy's own goodbye/chime right after a session

    def reset(self, now: float) -> None:
        self._model.reset()
        self._buf = np.zeros(0, dtype=np.int16)
        self._quiet_until = now + self._cooldown_s


def load_wake_model(name: str):
    from openwakeword.model import Model

    return Model(wakeword_models=[name], inference_framework="onnx")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_wake.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/wake.py voice/tests/test_rv_wake.py
git commit -m "reachy_voice: wake-word detector with post-session cooldown

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Gemini Live engine

**Files:**
- Create: `voice/reachy_voice/engines/gemini.py`
- Test: `voice/tests/test_rv_gemini.py`

**Interfaces:**
- Consumes:
  - `Delegation` and `EngineCallbacks` (Task 4)
  - `PERSONA`, `TOOL_NAME`, `TOOL_DESCRIPTION` and `TOOL_PARAMS` (Task 4)
  - `choose_lane` (Task 3)
  - `mic_to_pcm16` and `StreamResampler` (Task 2)
- Produces: `reachy_voice.engines.gemini.GeminiLiveEngine(model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None)` implementing `VoiceEngine` with `name = "gemini"` and `.config() -> types.LiveConnectConfig`. `connect(model=..., config=...)` returns an async context manager yielding a session with `send_realtime_input`, `send_tool_response` and the async generator `receive()`.

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_gemini.py`:
```python
import asyncio
from types import SimpleNamespace as NS

import numpy as np
from google.genai import types

from reachy_voice.engines.base import EngineCallbacks
from reachy_voice.engines.gemini import GeminiLiveEngine


class FakeSession:
    def __init__(self, turns):
        self.turns = list(turns)
        self.audio = []
        self.tool_responses = []

    async def send_realtime_input(self, audio):
        self.audio.append(audio)

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        if self.turns:
            for msg in self.turns.pop(0):
                yield msg


class FakeConnect:
    def __init__(self, session):
        self.session, self.kwargs, self.exited = session, None, False

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        self.exited = True


def msg(data=None, server_content=None, tool_call=None, usage=None):
    return NS(data=data, server_content=server_content, tool_call=tool_call, usage_metadata=usage)


def recorder():
    got = {"audio": [], "user": [], "robot": [], "interrupted": [], "delegations": [], "usage": [], "errors": []}
    cb = EngineCallbacks(
        on_audio=lambda s, now: got["audio"].append(s),
        on_user_text=got["user"].append,
        on_robot_text=got["robot"].append,
        on_interrupted=got["interrupted"].append,
        on_delegation=got["delegations"].append,
        on_usage=got["usage"].append,
        on_error=got["errors"].append,
    )
    return got, cb


def run(engine, cb):
    async def go():
        await engine.start(cb)
        await asyncio.wait_for(engine.wait_closed(), 2)
        await engine.close()
    asyncio.run(go())


def test_config_pins_english_voice_and_non_blocking_tool():
    cfg = GeminiLiveEngine("gemini-3.8-live", "Kore", connect=FakeConnect(FakeSession([]))).config()
    assert cfg.speech_config.language_code == "en-US"
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    decl = cfg.tools[0].function_declarations[0]
    assert decl.name == "ask_home_agent" and decl.behavior == types.Behavior.NON_BLOCKING


def test_tool_call_becomes_delegation_and_result_is_delivered_when_idle():
    fc = NS(id="c1", name="ask_home_agent", args={"request": "what's on the grocery list", "lane": "bogus"})
    session = FakeSession([[msg(tool_call=NS(function_calls=[fc]))]])
    engine = GeminiLiveEngine("m", "Kore", connect=FakeConnect(session))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await asyncio.wait_for(engine.wait_closed(), 2)
        await engine.deliver("c1", "Milk and eggs.")
        await engine.close()
    asyncio.run(go())

    d = got["delegations"][0]
    assert (d.call_id, d.request, d.lane) == ("c1", "what's on the grocery list", "quick")  # bogus lane -> choose_lane
    r = session.tool_responses[0]
    assert r.id == "c1" and r.name == "ask_home_agent" and r.response == {"result": "Milk and eggs."}
    assert r.scheduling == types.FunctionResponseScheduling.WHEN_IDLE


def test_audio_is_resampled_to_16k_and_events_forwarded():
    pcm = (np.sin(np.arange(9600) / 10) * 8000).astype("<i2").tobytes()   # 0.4 s at 24 kHz
    content = NS(interrupted=True, input_transcription=NS(text="hi"), output_transcription=NS(text="hello"))
    session = FakeSession([[msg(data=pcm), msg(data=pcm), msg(server_content=content, usage=NS(total_token_count=42))]])
    got, cb = recorder()
    run(GeminiLiveEngine("m", "Kore", connect=FakeConnect(session)), cb)
    assert got["audio"] and all(a.dtype == np.float32 and len(a) > 0 for a in got["audio"])
    assert 12000 <= sum(len(a) for a in got["audio"]) <= 12800      # ~0.8 s at 16 kHz, minus resampler latency
    assert got["user"] == ["hi"] and got["robot"] == ["hello"] and len(got["interrupted"]) == 1
    assert got["usage"] == [{"total_tokens": 42}]


def test_session_end_finishes_receive_loop_and_close_exits_context():
    connect = FakeConnect(FakeSession([]))
    got, cb = recorder()
    run(GeminiLiveEngine("m", "Kore", connect=connect), cb)
    assert connect.exited and got["errors"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_gemini.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.engines.gemini'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/engines/gemini.py`:
```python
"""Gemini 3.8 Live: native audio, non-blocking tool calls delivered when idle."""

import asyncio
import time

import numpy as np
from google import genai
from google.genai import types

from reachy_voice.audio import StreamResampler, mic_to_pcm16
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.persona import PERSONA, TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMS
from reachy_voice.policy import choose_lane


class GeminiLiveEngine:
    name = "gemini"

    def __init__(self, model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None) -> None:
        self._model, self._voice, self._persona = model, voice, persona
        self._connect = connect or genai.Client(api_key=api_key).aio.live.connect
        self._resampler = StreamResampler(24000, 16000)
        self._calls: dict[str, str] = {}
        self._cm = self._session = self._rx = None
        self._cb: EngineCallbacks | None = None
        self._closing = False
        self._ended = asyncio.Event()

    def config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                language_code="en-US",
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)),
            ),
            system_instruction=self._persona,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=TOOL_NAME,
                            description=TOOL_DESCRIPTION,
                            parameters_json_schema=TOOL_PARAMS,
                            behavior=types.Behavior.NON_BLOCKING,  # explicit; the default was never verified
                        )
                    ]
                )
            ],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def start(self, cb: EngineCallbacks) -> None:
        self._cb, self._ended = cb, asyncio.Event()
        self._cm = self._connect(model=self._model, config=self.config())
        self._session = await self._cm.__aenter__()
        self._rx = asyncio.create_task(self._receive())

    async def send_audio(self, frame: np.ndarray) -> None:
        await self._session.send_realtime_input(audio=types.Blob(data=mic_to_pcm16(frame), mime_type="audio/pcm;rate=16000"))

    async def deliver(self, call_id: str, text: str) -> None:
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=call_id,
                    name=self._calls.pop(call_id, TOOL_NAME),
                    response={"result": text},
                    scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
                )
            ]
        )

    async def _receive(self) -> None:
        try:
            while not self._closing:
                got_any = False
                async for msg in self._session.receive():  # ends after each completed turn
                    got_any = True
                    self._handle(msg, time.monotonic())
                if not got_any:
                    return  # the session ended server-side
        except Exception as exc:  # noqa: BLE001 - surface, then end the session
            if not self._closing:
                self._cb.on_error(f"gemini receive failed: {exc!r}")
        finally:
            self._ended.set()

    def _handle(self, msg, now: float) -> None:
        cb = self._cb
        if msg.data:
            samples = self._resampler.process(msg.data)
            if len(samples):  # soxr primes with an empty chunk; never push empty audio
                cb.on_audio(samples, now)
        sc = msg.server_content
        if sc is not None:
            if sc.interrupted:
                cb.on_interrupted(now)
            if sc.input_transcription and sc.input_transcription.text:
                cb.on_user_text(sc.input_transcription.text)
            if sc.output_transcription and sc.output_transcription.text:
                cb.on_robot_text(sc.output_transcription.text)
        if msg.tool_call:
            for fc in msg.tool_call.function_calls:
                args = dict(fc.args or {})
                request = str(args.get("request", "")).strip()
                lane = args.get("lane") if args.get("lane") in ("quick", "task") else choose_lane(request)
                self._calls[fc.id] = fc.name
                cb.on_delegation(Delegation(call_id=fc.id, request=request, lane=lane))
        if msg.usage_metadata:
            cb.on_usage({"total_tokens": msg.usage_metadata.total_token_count})

    async def close(self) -> None:
        self._closing = True
        if self._cm is not None:
            cm, self._cm = self._cm, None
            await cm.__aexit__(None, None, None)
        if self._rx is not None:
            self._rx.cancel()
            await asyncio.gather(self._rx, return_exceptions=True)

    async def wait_closed(self) -> None:
        await self._ended.wait()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_gemini.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/engines/gemini.py voice/tests/test_rv_gemini.py
git commit -m "reachy_voice: Gemini 3.8 Live engine (English pinned, non-blocking hand-off)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: OpenAI gpt-live-1 engine and engine factory

**Files:**
- Create: `voice/reachy_voice/engines/openai_live.py`
- Modify: `voice/reachy_voice/engines/__init__.py` (add `make_engine`)
- Test: `voice/tests/test_rv_openai.py`

**Interfaces:**
- Consumes:
  - `Delegation` and `EngineCallbacks` (Task 4)
  - `PERSONA` (Task 4)
  - `TurnSegmenter` (Task 4)
  - `choose_lane` (Task 3)
  - `mic_to_pcm16` and `pcm16_to_float` (Task 2)
  - `Settings` (Task 2)
- Produces:
  - `reachy_voice.engines.openai_live.OpenAILiveEngine(model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None)` implementing `VoiceEngine` with `name = "openai"` and `.close_info: dict | None`. `connect()` is awaitable and returns a websocket with `send(str)`, async iteration over str messages, and `close()`.
  - `reachy_voice.engines.make_engine(name: str, settings: Settings) -> VoiceEngine`

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_openai.py`:
```python
import asyncio
import base64
import json

import numpy as np
import pytest

from reachy_voice.config import load_settings
from reachy_voice.engines import make_engine
from reachy_voice.engines.base import EngineCallbacks
from reachy_voice.engines.openai_live import OpenAILiveEngine


class FakeWS:
    def __init__(self, events, ack_close=True):
        self.sent, self.closed, self._ack = [], False, ack_close
        self._q = asyncio.Queue()
        for e in events:
            self._q.put_nowait(json.dumps(e))

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg["type"] == "session.close" and self._ack:
            self._q.put_nowait(json.dumps({"type": "session.closed", "reason": "close_requested", "usage": {"seconds": 3}}))

    def push(self, event):
        self._q.put_nowait(json.dumps(event))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self):
        self.closed = True
        self._q.put_nowait(None)


def connect_to(ws):
    async def connect():
        return ws
    return connect


def recorder():
    got = {"audio": [], "user": [], "robot": [], "delegations": [], "usage": [], "errors": []}
    cb = EngineCallbacks(
        on_audio=lambda s, now: got["audio"].append(s),
        on_user_text=got["user"].append,
        on_robot_text=got["robot"].append,
        on_interrupted=lambda now: None,
        on_delegation=got["delegations"].append,
        on_usage=got["usage"].append,
        on_error=got["errors"].append,
    )
    return got, cb


def test_start_sends_session_start_and_waits_for_started():
    ws = FakeWS([{"type": "session.started", "session": {"id": "s"}}])
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await engine.close()
    asyncio.run(go())

    start = ws.sent[0]
    assert start["type"] == "session.start"
    s = start["session"]
    assert s["model"] == "gpt-live-1" and s["delegation"] == {"type": "client"}
    assert s["audio"] == {"format": {"type": "audio/pcm", "rate": 16000}, "output": {"voice": "marin"}}
    assert ws.sent[-1] == {"type": "session.close"} and ws.closed
    assert engine.close_info == {"reason": "close_requested", "usage": {"seconds": 3}}


def test_start_times_out_if_session_never_starts():
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(FakeWS([])))
    with pytest.raises(RuntimeError, match="did not start"):
        asyncio.run(engine.start(recorder()[1], start_timeout_s=0.1))


def test_events_audio_transcripts_delegation_and_delivery():
    pcm = (np.full(1600, 4000)).astype("<i2").tobytes()
    ws = FakeWS([
        {"type": "session.started"},
        {"type": "session.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "session.input_transcript.delta", "delta": " What's on the grocery list"},
        {"type": "session.output_transcript.delta", "delta": " Checking now."},
        {"type": "session.delegation.created", "delegation": {"id": "item_1", "type": "delegation", "target": "client"}},
        {"type": "session.usage.updated", "usage": {"seconds": 2}},
        {"type": "error", "error": {"message": "bad"}},
    ])
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        while not got["errors"]:
            await asyncio.sleep(0.01)
        await engine.send_audio(np.zeros((1024, 2), np.float32))
        await engine.deliver("item_1", "Milk and eggs.")
        await engine.close()
    asyncio.run(go())

    assert len(got["audio"]) == 1 and got["audio"][0].dtype == np.float32 and len(got["audio"][0]) == 1600
    d = got["delegations"][0]
    assert (d.call_id, d.request, d.lane) == ("item_1", "What's on the grocery list", "quick")
    assert got["usage"] == [{"seconds": 2}] and "bad" in got["errors"][0]
    append = [m for m in ws.sent if m["type"] == "session.input_audio.append"][0]
    assert len(base64.b64decode(append["audio"])) == 2048
    commentary = [m for m in ws.sent if m["type"] == "session.commentary.append"][0]
    assert commentary["delegation_id"] == "item_1" and commentary["content"] == "Milk and eggs."


def test_server_closing_ends_wait_closed_and_close_tolerates_no_ack():
    ws = FakeWS([{"type": "session.started"}], ack_close=False)
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))

    async def go():
        await engine.start(recorder()[1])
        ws.push({"type": "session.closed", "reason": "expired"})
        await asyncio.wait_for(engine.wait_closed(), 1)
        await asyncio.wait_for(engine.close(close_timeout_s=0.1), 1)
    asyncio.run(go())
    assert ws.closed and engine.close_info["reason"] == "expired"


def test_make_engine_builds_each_engine():
    s = load_settings({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"})
    assert make_engine("openai", s).name == "openai"
    assert make_engine("gemini", s).name == "gemini"
    with pytest.raises(ValueError):
        make_engine("alexa", s)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_openai.py`
Expected: `ImportError: cannot import name 'make_engine'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/engines/openai_live.py`:
```python
"""OpenAI gpt-live-1: full-duplex, client delegation. The model handles being talked over,
so there is no local barge-in (spike lesson, voice/spike/RESULTS.md)."""

import asyncio
import base64
import json
import time

import numpy as np
import websockets

from reachy_voice.audio import mic_to_pcm16, pcm16_to_float
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.persona import PERSONA
from reachy_voice.policy import choose_lane
from reachy_voice.segment import TurnSegmenter

URL = "wss://api.openai.com/v1/live/sessions"


class OpenAILiveEngine:
    name = "openai"

    def __init__(self, model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None) -> None:
        self._model, self._voice, self._persona = model, voice, persona
        self._connect = connect or (
            lambda: websockets.connect(URL, additional_headers={"Authorization": f"Bearer {api_key}"}, max_size=None)
        )
        self._segmenter = TurnSegmenter()
        self._ws = self._rx = None
        self._cb: EngineCallbacks | None = None
        self._started = asyncio.Event()
        self._ended = asyncio.Event()
        self.close_info: dict | None = None

    async def start(self, cb: EngineCallbacks, start_timeout_s: float = 10.0) -> None:
        self._cb, self._started, self._ended = cb, asyncio.Event(), asyncio.Event()
        self._ws = await self._connect()
        await self._ws.send(json.dumps({
            "type": "session.start",
            "event_id": "start",
            "session": {
                "model": self._model,
                "instructions": self._persona,
                "audio": {"format": {"type": "audio/pcm", "rate": 16000}, "output": {"voice": self._voice}},
                "delegation": {"type": "client"},
            },
        }))
        self._rx = asyncio.create_task(self._receive())
        try:
            await asyncio.wait_for(self._started.wait(), timeout=start_timeout_s)
        except asyncio.TimeoutError:
            await self._shutdown()
            raise RuntimeError("gpt-live-1 session did not start") from None

    async def send_audio(self, frame: np.ndarray) -> None:
        await self._ws.send(json.dumps({"type": "session.input_audio.append",
                                        "audio": base64.b64encode(mic_to_pcm16(frame)).decode()}))

    async def deliver(self, call_id: str, text: str) -> None:
        await self._ws.send(json.dumps({"type": "session.commentary.append", "event_id": f"result-{call_id}",
                                        "delegation_id": call_id, "content": text}))

    async def _receive(self) -> None:
        cb = self._cb
        try:
            async for raw in self._ws:
                event = json.loads(raw)
                kind, now = event.get("type"), time.monotonic()
                if kind == "session.started":
                    self._started.set()
                elif kind == "session.output_audio.delta":
                    samples = pcm16_to_float(base64.b64decode(event["delta"]), 16000, 16000)
                    if len(samples):
                        cb.on_audio(samples, now)
                elif kind == "session.input_transcript.delta":
                    self._segmenter.on_user_text(event.get("delta", ""))
                    cb.on_user_text(event.get("delta", ""))
                elif kind == "session.output_transcript.delta":
                    self._segmenter.on_robot_text(event.get("delta", ""))
                    cb.on_robot_text(event.get("delta", ""))
                elif kind == "session.delegation.created":
                    request = self._segmenter.request()
                    cb.on_delegation(Delegation(call_id=event["delegation"]["id"], request=request, lane=choose_lane(request)))
                elif kind == "session.usage.updated":
                    cb.on_usage(event.get("usage") or {})
                elif kind == "error":
                    cb.on_error(json.dumps(event)[:500])
                elif kind == "session.closed":
                    self.close_info = {"reason": event.get("reason"), "usage": event.get("usage")}
                    return
        except websockets.ConnectionClosed as exc:
            cb.on_error(f"gpt-live-1 connection closed: {exc!r}")
        finally:
            self._ended.set()

    async def close(self, close_timeout_s: float = 5.0) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "session.close"}))
            await asyncio.wait_for(self._ended.wait(), timeout=close_timeout_s)
        except (websockets.ConnectionClosed, asyncio.TimeoutError):
            pass
        await self._shutdown()

    async def _shutdown(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            await ws.close()
        if self._rx is not None:
            self._rx.cancel()
            await asyncio.gather(self._rx, return_exceptions=True)

    async def wait_closed(self) -> None:
        await self._ended.wait()
```

`voice/reachy_voice/engines/__init__.py`:
```python
"""Engine factory: one name per engine, built from Settings."""

from reachy_voice.config import Settings


def make_engine(name: str, settings: Settings):
    if name == "gemini":
        from reachy_voice.engines.gemini import GeminiLiveEngine

        return GeminiLiveEngine(settings.gemini_model, settings.gemini_voice, api_key=settings.gemini_api_key)
    if name == "openai":
        from reachy_voice.engines.openai_live import OpenAILiveEngine

        return OpenAILiveEngine(settings.openai_model, settings.openai_voice, api_key=settings.openai_api_key)
    raise ValueError(f"unknown engine {name!r}")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_openai.py`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add voice/reachy_voice/engines/openai_live.py voice/reachy_voice/engines/__init__.py voice/tests/test_rv_openai.py
git commit -m "reachy_voice: OpenAI gpt-live-1 engine and engine factory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Voice session orchestrator

**Files:**
- Create: `voice/reachy_voice/session.py`
- Test: `voice/tests/test_rv_session.py`

**Interfaces:**
- Consumes:
  - `OutputActivity` and `UserSpeech` (Task 3)
  - `SessionPolicy` (Task 3)
  - `EngineCallbacks` and `Delegation` (Task 4)
  - `FALLBACK_REPLY` (Task 4)
  - `HermesError` (Task 5)
  - `JsonlLog` (Task 2)
  - `rms` (Task 2)
- Produces: `reachy_voice.session.VoiceSession(engine, audio, hermes, policy: SessionPolicy, speech_threshold: float, log: JsonlLog, session_id: str, clock=time.monotonic, tick_s: float = 0.25)` with `async .run() -> str`. The returned close reason is one of `idle`, `pending_timeout`, `max_duration`, `engine_closed` or `mic_closed`.
  - `audio` must provide `async frames()`, `play(samples)` and `clear()`.
  - `hermes` must provide `async ask(request, asked_by, lane, session_id) -> str`.

- [ ] **Step 1: Write the failing test**

`voice/tests/test_rv_session.py`:
```python
import asyncio
import json

import numpy as np

from reachy_voice.engines.base import Delegation
from reachy_voice.hermes import HermesError
from reachy_voice.log import JsonlLog
from reachy_voice.persona import FALLBACK_REPLY
from reachy_voice.policy import SessionPolicy
from reachy_voice.session import VoiceSession

VOICED = np.full(1600, 0.2, np.float32)


class FakeEngine:
    name = "fake"

    def __init__(self, on_start=None):
        self.sent, self.delivered, self.closed = [], [], False
        self._done = asyncio.Event()
        self._on_start = on_start

    async def start(self, cb):
        self.cb = cb
        if self._on_start:
            asyncio.get_running_loop().call_soon(self._on_start, self)

    async def send_audio(self, frame):
        self.sent.append(frame)

    async def deliver(self, call_id, text):
        self.delivered.append((call_id, text))

    async def close(self):
        self.closed = True
        self._done.set()

    async def wait_closed(self):
        await self._done.wait()


class FakeAudio:
    def __init__(self, level=0.0, count=3, forever=False):
        self.level, self.count, self.forever = level, count, forever
        self.played, self.cleared = [], 0

    async def frames(self):
        n = 0
        while self.forever or n < self.count:
            n += 1
            yield np.full((1024, 2), self.level, np.float32)
            await asyncio.sleep(0.005)
        await asyncio.Event().wait()   # mic stays open, silent

    def play(self, samples):
        self.played.append(samples)

    def clear(self):
        self.cleared += 1


class FakeHermes:
    def __init__(self, answer="Milk and eggs.", delay=0.0, fail=False):
        self.answer, self.delay, self.fail, self.calls = answer, delay, fail, []

    async def ask(self, request, asked_by, lane, session_id):
        self.calls.append((request, lane, session_id))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise HermesError("ConnectError: refused")
        return self.answer


def make(engine, audio, hermes, tmp_path, idle=0.1, pending=5.0, max_s=5.0):
    log = JsonlLog(str(tmp_path / "v.jsonl"))
    s = VoiceSession(engine, audio, hermes, SessionPolicy(idle, pending, max_s), 0.015, log, "sess-1", tick_s=0.01)
    return s, tmp_path / "v.jsonl"


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def delegate(engine):
    engine.cb.on_delegation(Delegation("c1", "what's on the grocery list", "quick"))


def test_idle_session_closes_and_closes_engine(tmp_path):
    engine = FakeEngine()
    s, path = make(engine, FakeAudio(), FakeHermes(), tmp_path)
    assert asyncio.run(s.run()) == "idle"
    assert engine.closed and len(engine.sent) == 3
    assert [e["event"] for e in events(path)][0] == "session_open"


def test_pending_handoff_holds_session_then_delivers(tmp_path):
    engine, hermes = FakeEngine(on_start=delegate), FakeHermes(delay=0.3)
    s, path = make(engine, FakeAudio(), hermes, tmp_path, idle=0.05)
    loop_start = asyncio.run(_timed(s))
    assert loop_start[0] == "idle" and loop_start[1] >= 0.3
    assert hermes.calls == [("what's on the grocery list", "quick", "sess-1")]
    assert engine.delivered == [("c1", "Milk and eggs.")]
    result = [e for e in events(path) if e["event"] == "delegation_result"][0]
    assert result["ok"] is True


def test_hermes_failure_delivers_spoken_fallback(tmp_path):
    engine = FakeEngine(on_start=delegate)
    s, path = make(engine, FakeAudio(), FakeHermes(fail=True), tmp_path)
    asyncio.run(s.run())
    assert engine.delivered == [("c1", FALLBACK_REPLY)]
    assert any(e["event"] == "delegation_error" for e in events(path))


def test_constant_background_speech_is_capped_by_max_duration(tmp_path):
    s, _ = make(FakeEngine(), FakeAudio(level=0.5, forever=True), FakeHermes(), tmp_path, idle=0.1, max_s=0.3)
    assert asyncio.run(s.run()) == "max_duration"


def test_engine_dropping_ends_session(tmp_path):
    engine = FakeEngine(on_start=lambda e: e._done.set())
    s, _ = make(engine, FakeAudio(), FakeHermes(), tmp_path, idle=5.0)
    assert asyncio.run(s.run()) == "engine_closed"


def test_voiced_audio_is_played_and_interrupt_clears(tmp_path):
    def speak(engine):
        engine.cb.on_audio(VOICED, 0.0)
        engine.cb.on_interrupted(0.0)
    engine, audio = FakeEngine(on_start=speak), FakeAudio(level=0.5, count=1)
    s, path = make(engine, audio, FakeHermes(), tmp_path)
    asyncio.run(s.run())
    assert len(audio.played) == 1 and audio.cleared == 1


async def _timed(session):
    loop = asyncio.get_running_loop()
    start = loop.time()
    reason = await session.run()
    return reason, loop.time() - start
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_session.py`
Expected: `ModuleNotFoundError: No module named 'reachy_voice.session'`

- [ ] **Step 3: Implement**

`voice/reachy_voice/session.py`:
```python
"""One wake-word conversation: robot audio <-> engine, with background Hermes hand-offs."""

import asyncio
import time

import numpy as np

from reachy_voice.activity import OutputActivity, UserSpeech
from reachy_voice.audio import rms
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.hermes import HermesError
from reachy_voice.log import JsonlLog
from reachy_voice.persona import FALLBACK_REPLY
from reachy_voice.policy import SessionPolicy

RATE = 16000


class VoiceSession:
    def __init__(self, engine, audio, hermes, policy: SessionPolicy, speech_threshold: float, log: JsonlLog,
                 session_id: str, clock=time.monotonic, tick_s: float = 0.25) -> None:
        self._engine, self._audio, self._hermes = engine, audio, hermes
        self._policy, self._log, self._session_id = policy, log, session_id
        self._clock, self._tick_s = clock, tick_s
        self._out = OutputActivity()
        self._user = UserSpeech(threshold=speech_threshold)
        self._pending: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> str:
        opened = self._clock()
        await self._engine.start(self._callbacks())
        self._log.write("session_open", engine=self._engine.name, session_id=self._session_id)
        mic = asyncio.create_task(self._pump_mic())
        engine_done = asyncio.create_task(self._engine.wait_closed())
        try:
            while True:
                await asyncio.sleep(self._tick_s)
                if engine_done.done():
                    return "engine_closed"
                if mic.done():
                    if mic.exception() is not None:
                        self._log.write("mic_error", error=repr(mic.exception()))
                    return "mic_closed"
                now = self._clock()
                last = max(opened, self._user.last_voice or opened, self._out.voiced_end)
                pending_since = min(self._pending.values()) if self._pending else None
                reason = self._policy.should_close(now, opened, last, pending_since)
                if reason:
                    return reason
        finally:
            mic.cancel()
            engine_done.cancel()
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(mic, engine_done, *self._tasks, return_exceptions=True)
            await self._engine.close()

    def _callbacks(self) -> EngineCallbacks:
        name = self._engine.name
        return EngineCallbacks(
            on_audio=self._on_audio,
            on_user_text=lambda text: self._log.write("user_text", engine=name, text=text),
            on_robot_text=lambda text: self._log.write("robot_text", engine=name, text=text),
            on_interrupted=self._on_interrupted,
            on_delegation=self._on_delegation,
            on_usage=lambda usage: self._log.write("usage", engine=name, usage=usage),
            on_error=lambda message: self._log.write("engine_error", engine=name, message=message),
        )

    async def _pump_mic(self) -> None:
        async for frame in self._audio.frames():
            now = self._clock()
            self._user.on_mic(rms(frame), now, self._out.is_speaking(now))
            await self._engine.send_audio(frame)

    def _on_audio(self, samples: np.ndarray, now: float) -> None:
        play, voiced_start = self._out.accept(samples, RATE, self._clock())
        if not play:
            return
        self._audio.play(samples)
        if voiced_start is not None:
            latency = self._user.on_voiced_output(voiced_start)
            if latency is not None:
                self._log.write("first_audio", engine=self._engine.name, latency_s=latency)

    def _on_interrupted(self, now: float) -> None:
        self._audio.clear()
        self._out.clear(self._clock())
        self._log.write("interrupted", engine=self._engine.name)

    def _on_delegation(self, d: Delegation) -> None:
        started = self._clock()
        self._pending[d.call_id] = started
        self._log.write("delegation", engine=self._engine.name, call_id=d.call_id, lane=d.lane, request=d.request)
        task = asyncio.create_task(self._handle_delegation(d, started))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_delegation(self, d: Delegation, started: float) -> None:
        ok = True
        try:
            text = await self._hermes.ask(d.request, "unknown", d.lane, self._session_id)
        except HermesError as exc:
            ok, text = False, FALLBACK_REPLY
            self._log.write("delegation_error", call_id=d.call_id, error=str(exc))
        try:
            await self._engine.deliver(d.call_id, text)
        except Exception as exc:  # noqa: BLE001 - a failed delivery must not leave the session pending
            ok = False
            self._log.write("delivery_error", call_id=d.call_id, error=repr(exc))
        finally:
            self._pending.pop(d.call_id, None)
            self._log.write("delegation_result", call_id=d.call_id, lane=d.lane, ok=ok,
                            seconds=round(self._clock() - started, 2))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q tests/test_rv_session.py`
Expected: `6 passed`

- [ ] **Step 5: Run the whole voice suite**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: all pass (the spike's 19 plus this plan's 49), with no warnings.

- [ ] **Step 6: Commit**

```bash
git add voice/reachy_voice/session.py voice/tests/test_rv_session.py
git commit -m "reachy_voice: voice session orchestrator

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Robot audio, main loop, service and on-robot acceptance

**Files:**
- Create: `voice/reachy_voice/robot_audio.py`, `voice/reachy_voice/main.py`, `voice/deploy/reachy-voice.service`, `voice/README.md`
- Modify: `voice/deploy/deploy-voice.sh` (append the env file and service install)
- Modify: `household/README.md` (add a "Voice app" pointer section)

**Interfaces:**
- Consumes: everything above. Task 2's `load_settings`; Task 3's `EngineChooser`, `SessionPolicy` and `other_engine`; Task 5's `HermesClient`; Task 6's `WakeWord` and `load_wake_model`; Task 8's `make_engine`; Task 9's `VoiceSession`; Task 2's `JsonlLog`.
- Produces:
  - `python -m reachy_voice.main`, run on the robot
  - the `reachy-voice.service` systemd unit, installed but not enabled at boot unless `deploy-voice.sh --enable` is used

- [ ] **Step 1: Write the robot audio wrapper and main loop**

`voice/reachy_voice/robot_audio.py`:
```python
"""Robot mic and speaker through the SDK's local media path, plus short earcons."""

import asyncio
from collections.abc import AsyncIterator

import numpy as np

RATE = 16000


def _tones(freqs: list[float], seconds: float = 0.12) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return np.concatenate([(0.15 * np.sin(2 * np.pi * f * t)).astype(np.float32) for f in freqs])


CHIMES = {"wake": _tones([660, 880]), "sleep": _tones([880, 660]), "error": _tones([440, 330, 220])}


class RobotAudio:
    def __init__(self, media) -> None:
        self._media = media

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

    def play(self, samples: np.ndarray) -> None:
        if len(samples):  # an empty push segfaults GStreamer
            self._media.push_audio_sample(samples.astype(np.float32, copy=False))

    def clear(self) -> None:
        self._media.audio.clear_player()

    def chime(self, kind: str) -> None:
        self.play(CHIMES[kind])
```

`voice/reachy_voice/main.py`:
```python
"""Entry point on the robot: wake word -> voice session -> back to listening."""

import asyncio
import os
import time

from reachy_mini import ReachyMini

from reachy_voice.config import Settings, load_settings
from reachy_voice.engines import make_engine
from reachy_voice.hermes import HermesClient
from reachy_voice.log import JsonlLog
from reachy_voice.policy import EngineChooser, SessionPolicy, other_engine
from reachy_voice.robot_audio import RobotAudio
from reachy_voice.session import VoiceSession
from reachy_voice.wake import WakeWord, load_wake_model


async def _run_session(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient, log: JsonlLog) -> str:
    policy = SessionPolicy(settings.idle_timeout_s, settings.pending_max_s, settings.max_session_s)
    session = VoiceSession(make_engine(name, settings), audio, hermes, policy, settings.speech_threshold, log,
                           session_id=f"reachy-{name}-{int(time.time())}")
    return await session.run()


async def _session_with_fallback(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient,
                                 log: JsonlLog) -> str:
    candidates = [name] + ([other_engine(name)] if settings.has_engine(other_engine(name)) else [])
    for engine in candidates:
        try:
            return await _run_session(engine, settings, audio, hermes, log)
        except Exception as exc:  # noqa: BLE001 - connection/auth failures fall back to the other engine
            log.write("session_error", engine=engine, error=repr(exc))
    audio.chime("error")
    return "error"


async def amain(settings: Settings) -> None:
    log = JsonlLog(os.path.join(settings.log_dir, f"voice-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
    hermes = HermesClient(settings.home_agent_url, settings.home_agent_key, settings.quick_model, settings.quick_provider)
    chooser = EngineChooser(settings.engine)
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        wake = WakeWord(load_wake_model(settings.wake_model), settings.wake_threshold)
        log.write("ready", engine_mode=settings.engine, wake_model=settings.wake_model)
        try:
            while True:
                async for frame in audio.frames():
                    if wake.feed(frame, time.monotonic()):
                        break
                audio.chime("wake")
                name = chooser.next()
                log.write("wake", engine=name)
                reason = await _session_with_fallback(name, settings, audio, hermes, log)
                log.write("session_end", engine=name, reason=reason)
                audio.chime("sleep")
                wake.reset(time.monotonic())
        finally:
            audio.stop()
            await hermes.aclose()


def main() -> None:
    asyncio.run(amain(load_settings(os.environ)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the service unit and extend the deploy script**

`voice/deploy/reachy-voice.service`:
```ini
[Unit]
Description=Reachy voice assistant (wake word + live voice + Hermes)
After=reachy-mini-daemon.service network-online.target
Wants=network-online.target

[Service]
User=pollen
WorkingDirectory=/home/pollen/reachy-voice
EnvironmentFile=/home/pollen/reachy-voice/voice.env
# Free the mic: the daemon runs one media owner at a time. A 400 (no app running) is fine.
ExecStartPre=-/usr/bin/curl -s -m 30 -X POST http://127.0.0.1:8000/api/apps/stop-current-app
ExecStart=/home/pollen/reachy-voice/.venv/bin/python -m reachy_voice.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Append to `voice/deploy/deploy-voice.sh`, after the existing remote block:
```bash
scp -4 -q "$HERE/deploy/reachy-voice.service" "$ROBOT:reachy-voice/reachy-voice.service"
ssh -4 "$ROBOT" "ENABLE=${1:-} bash -s" <<'REMOTE'
set -euo pipefail
cd ~/reachy-voice
APP_ENV=/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/.env
umask 077
# Keys never leave the robot: copy the four needed lines, keep any local VOICE_* overrides.
{ grep -E '^(GEMINI_API_KEY|OPENAI_API_KEY|HOME_AGENT_URL|HOME_AGENT_KEY)=' "$APP_ENV"
  [ -f voice.env ] && grep -vE '^(GEMINI_API_KEY|OPENAI_API_KEY|HOME_AGENT_URL|HOME_AGENT_KEY)=' voice.env || true
} > voice.env.new
grep -q '^VOICE_ENGINE=' voice.env.new || echo 'VOICE_ENGINE=alternate' >> voice.env.new
grep -q '^VOICE_LOG_DIR=' voice.env.new || echo 'VOICE_LOG_DIR=/home/pollen/reachy-voice/logs' >> voice.env.new
mv voice.env.new voice.env && chmod 600 voice.env
sudo install -m 644 reachy-voice.service /etc/systemd/system/reachy-voice.service
sudo systemctl daemon-reload
if [ "$ENABLE" = "--enable" ]; then sudo systemctl enable reachy-voice; fi
sudo systemctl restart reachy-voice
sleep 8
systemctl is-active reachy-voice
tail -n 3 "$(ls -t logs/voice-*.jsonl | head -1)"
REMOTE
```

- [ ] **Step 3: Run the full suite and deploy**

Run: `cd /Users/painter/palettepal/reachy-mini-stack/voice && ../.venv/bin/python -m pytest -q`
Expected: all pass.

Run: `voice/deploy/deploy-voice.sh`
Expected:
- `voice venv ok`
- `active`
- a log tail containing `{"event": "ready", ... "wake_model": "hey_jarvis"}`

If it shows `failed`, run `ssh -4 pollen@reachy-mini.local 'journalctl -u reachy-voice -n 50 --no-pager'`, fix the cause, and redeploy.

- [ ] **Step 4: On-robot acceptance (hand over to the user: someone must speak)**

With the TV quiet, the user says each of these in turn (about 1 m from Reachy):
1. **"Hey Jarvis"**. Expected: the wake chime, then the first conversation (Gemini, since `alternate` starts with Gemini).
2. **"What's on the grocery list?"** Expected: an immediate acknowledgement, then the real list from Hermes via the quick lane.
3. Silence for about 35 s. Expected: the sleep chime (idle close).
4. **"Hey Jarvis"** again. Expected: the second conversation runs on OpenAI. Ask **"Add bread to the grocery list"**, then **"Thanks, that's all"** and wait for the sleep chime.
5. Optional: with the TV on at normal volume for 2 minutes and nobody saying the wake word, Reachy should stay silent.

Then summarise the log:
```bash
ssh -4 pollen@reachy-mini.local 'cd ~/reachy-voice && f=$(ls -t logs/voice-*.jsonl | head -1); python3 -c "
import json
for l in open(\"$f\"):
    e=json.loads(l)
    if e[\"event\"] in (\"wake\",\"session_open\",\"first_audio\",\"delegation\",\"delegation_result\",\"session_end\",\"session_error\",\"engine_error\",\"delegation_error\"): print({k:v for k,v in e.items() if k!=\"ts\"})
"'
```
Expected:
- two `wake` events (gemini, then openai)
- `first_audio` latencies for both engines
- `delegation` with `lane: quick` and `delegation_result ok: true` for both requests
- `session_end` with `reason: idle`
- no `session_error`

Remove "bread" from the list afterwards by saying "Hey Jarvis, remove bread from the grocery list", or with `ssh -4 behindtheproduct@reachy-pi.local "docker exec hermes sed -i '/^- *bread/Id' /opt/data/household-grocery-list.md"`.

Ask the user whether to start the service at boot. If yes, run `voice/deploy/deploy-voice.sh --enable`.

- [ ] **Step 5: Write the docs**

`voice/README.md`:
```markdown
# reachy_voice

Household voice assistant for the Reachy Mini Wireless. Say **"Hey Jarvis"** (a custom
"Hey Reachy" model comes in Plan 3), talk naturally, and Reachy hands real work to the
household's Hermes agent on the Pi without going silent.

- Engines: Gemini 3.8 Live and OpenAI gpt-live-1. Set `VOICE_ENGINE` in `~/reachy-voice/voice.env`
  on the robot to `gemini`, `openai` or `alternate` (alternates per conversation for the bake-off).
- Wake word: openWakeWord (`WAKE_MODEL`, `WAKE_THRESHOLD`); nothing leaves the robot until it fires.
- Hand-offs: Hermes at `HOME_AGENT_URL`. List and note requests use the quick lane (`QUICK_MODEL`).
- Sessions close after `IDLE_TIMEOUT_S` (30) of quiet. While a hand-off is pending they stay open
  up to `PENDING_MAX_S` (300). They never run past `MAX_SESSION_S` (600).
- Logs: `~/reachy-voice/logs/voice-*.jsonl` (first_audio latency, delegations, session ends).

## Deploy and operate (from the Mac)

    voice/deploy/deploy-voice.sh            # deploy + restart the service
    voice/deploy/deploy-voice.sh --enable   # also start at boot
    ssh pollen@reachy-mini.local 'journalctl -u reachy-voice -f'
    ssh pollen@reachy-mini.local 'sudo systemctl stop reachy-voice'   # silence Reachy

The service stops the daemon's current app when it starts, because only one owner can hold the mic.
Don't start Pollen's conversation app while `reachy-voice` is running.

`voice/spike/` is the frozen measurement spike that chose these engines (see `spike/RESULTS.md`).
```

Append to `household/README.md`:
```markdown

## Voice app

Reachy's voice now comes from `voice/reachy_voice` (wake word, Gemini or OpenAI live voice, and a
non-blocking Hermes hand-off), not from Pollen's conversation app. See `voice/README.md`. The
`robot-profile/` and `robot-tools/` here belong to the older conversation-app setup and are kept
as a fallback.
```

- [ ] **Step 6: Commit**

```bash
git add voice/reachy_voice/robot_audio.py voice/reachy_voice/main.py voice/deploy/reachy-voice.service voice/deploy/deploy-voice.sh voice/README.md household/README.md
git commit -m "reachy_voice: robot audio, main loop, systemd service and docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
