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
