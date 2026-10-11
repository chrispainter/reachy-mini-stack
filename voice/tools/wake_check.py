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
