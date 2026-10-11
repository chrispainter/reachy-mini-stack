"""Robot mic and speaker through the SDK's local media path, plus short earcons."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator

import numpy as np

from reachy_voice.body_policy import median_recent

RATE = 16000


def _tones(freqs: list[float], seconds: float = 0.12) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return np.concatenate([(0.15 * np.sin(2 * np.pi * f * t)).astype(np.float32) for f in freqs])


CHIMES = {"wake": _tones([660, 880]), "sleep": _tones([880, 660]), "error": _tones([440, 330, 220])}


class RobotAudio:
    def __init__(self, media) -> None:
        self._media = media
        self._doa: deque[tuple[float, float]] = deque(maxlen=200)

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

    def sample_doa(self, now: float) -> None:
        """Record the mic array's direction of arrival if it currently flags speech."""
        try:
            result = self._media.get_DoA()
        except Exception:  # noqa: BLE001
            return
        if not result:
            return
        angle, speech = result
        if speech:
            self._doa.append((now, float(angle)))

    def doa(self, now: float) -> float | None:
        """Median direction of arrival (radians) over the last 1.5 s of speech readings, else None."""
        return median_recent(self._doa, now)
