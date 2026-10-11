"""Robot mic and speaker through the SDK's local media path, plus short earcons."""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator

import numpy as np

from reachy_voice.body_policy import median_recent

RATE = 16000
DOA_PERIOD_S = 0.1


def _tones(freqs: list[float], seconds: float = 0.12) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return np.concatenate([(0.15 * np.sin(2 * np.pi * f * t)).astype(np.float32) for f in freqs])


CHIMES = {"wake": _tones([660, 880]), "sleep": _tones([880, 660]), "error": _tones([440, 330, 220])}


class RobotAudio:
    def __init__(self, media, clock=time.monotonic) -> None:
        self._media = media
        self._clock = clock
        self._doa: deque[tuple[float, float]] = deque(maxlen=64)
        self._doa_task: asyncio.Task | None = None
        self._doa_last = float("-inf")

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

    def _read_doa(self) -> tuple[float, float] | None:
        """Blocking USB read (runs in a worker thread): (angle, speech) -> (angle,) if speech-flagged."""
        try:
            result = self._media.get_DoA()
        except Exception:  # noqa: BLE001
            return None
        if not result:
            return None
        angle, speech = result
        return (float(angle), 0.0) if speech else None

    def _doa_done(self, task: "asyncio.Task") -> None:
        self._doa_task = None
        try:
            reading = task.result()
        except BaseException:  # noqa: BLE001 - cancelled or failed: nothing to record
            return
        if reading is not None:
            self._doa.append((self._clock(), reading[0]))

    def sample_doa(self, now: float) -> None:
        """Never blocks: at most every 0.1 s, start one background read if none is in flight."""
        if self._doa_task is not None or now - self._doa_last < DOA_PERIOD_S:
            return
        try:
            task = asyncio.get_running_loop().create_task(asyncio.to_thread(self._read_doa))
        except RuntimeError:
            return
        self._doa_last = now
        self._doa_task = task  # strong ref while in flight
        task.add_done_callback(self._doa_done)

    def doa(self, now: float) -> float | None:
        """Median direction of arrival (radians) over the last 1.5 s of speech readings, else None."""
        return median_recent(self._doa, now)
