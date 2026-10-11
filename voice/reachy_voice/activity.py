"""What the robot and the person are doing, from audio levels.

Speaking state comes from voiced output samples, never from audio arriving:
gpt-live-1 streams silence continuously (spike lesson, voice/spike/RESULTS.md)."""

from collections import deque
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
    window: int = 5
    min_voiced: int = 3
    last_voice: float | None = None
    _awaiting_reply: bool = False

    def __post_init__(self) -> None:
        self._recent: deque[bool] = deque(maxlen=self.window)

    def on_mic(self, level: float, now: float, robot_speaking: bool) -> None:
        """The person counts as speaking only on sustained voice (min_voiced of the last
        window frames): isolated spikes and distant chatter must not look like a turn."""
        voiced = not robot_speaking and level >= self.threshold
        self._recent.append(voiced)
        # the current frame must itself be voiced, so trailing quiet frames don't extend the turn
        if not voiced or sum(self._recent) < self.min_voiced:
            return
        self.last_voice = now
        self._awaiting_reply = True

    def on_voiced_output(self, start: float) -> float | None:
        if not self._awaiting_reply or self.last_voice is None:
            return None
        self._awaiting_reply = False
        return round(max(0.0, start - self.last_voice), 3)
