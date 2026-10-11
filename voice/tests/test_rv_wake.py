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
