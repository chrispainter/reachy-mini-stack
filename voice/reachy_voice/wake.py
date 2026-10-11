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
