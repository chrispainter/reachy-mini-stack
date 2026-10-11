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
