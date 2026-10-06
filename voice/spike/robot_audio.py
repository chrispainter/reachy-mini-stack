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
