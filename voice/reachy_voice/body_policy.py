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
