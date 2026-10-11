import json

import numpy as np
import soxr

from reachy_voice.audio import StreamResampler, mic_to_pcm16, pcm16_to_float, rms
from reachy_voice.log import JsonlLog


def test_mic_to_pcm16_first_channel_clipped():
    frame = np.array([[0.5, -1.0], [-0.5, 1.0], [2.0, 0.0]], dtype=np.float32)
    assert np.frombuffer(mic_to_pcm16(frame), dtype="<i2").tolist() == [16383, -16383, 32767]


def test_pcm16_to_float_passthrough_and_resample():
    pcm = np.array([0, 16384, -16384], dtype="<i2").tobytes()
    assert np.allclose(pcm16_to_float(pcm, 16000), [0.0, 0.5, -0.5])
    assert pcm16_to_float(np.zeros(2400, "<i2").tobytes(), 24000).shape == (1600,)


def test_rms_uses_first_channel():
    frame = np.stack([np.full(100, 0.1), np.zeros(100)], axis=1).astype(np.float32)
    assert abs(rms(frame) - 0.1) < 1e-6
    assert rms(np.zeros(0, np.float32)) == 0.0


def test_stream_resampler_matches_one_shot():
    t = np.arange(24000) / 24000
    sine = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    r = StreamResampler(24000, 16000)
    cuts = [0, 1000, 4100, 9000, 15000, 24000]
    out = np.concatenate([r.process(sine[a:b].tobytes()) for a, b in zip(cuts, cuts[1:])] + [r.flush()])
    assert abs(len(out) - 16000) <= 32
    ref = soxr.resample(sine.astype(np.float32) / 32768.0, 24000, 16000)
    assert np.allclose(out[2000:14000], ref[2000:14000], atol=1e-3)


def test_jsonl_log_creates_dir_and_appends(tmp_path):
    path = tmp_path / "sub" / "x.jsonl"
    log = JsonlLog(str(path))
    log.write("wake", engine="gemini")
    log.write("session_end", reason="idle")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["event"] for r in rows] == ["wake", "session_end"] and rows[0]["engine"] == "gemini"
    assert isinstance(rows[0]["ts"], float)


def test_jsonl_log_serialises_unknown_objects_via_str(tmp_path):
    path = tmp_path / "x.jsonl"
    JsonlLog(str(path)).write("odd", thing=object, path=tmp_path)
    row = json.loads(path.read_text())
    assert row["event"] == "odd" and isinstance(row["thing"], str)


def test_jsonl_log_write_never_raises(tmp_path, monkeypatch):
    log = JsonlLog(str(tmp_path / "x.jsonl"))

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", boom)
    log.write("wake")  # must not raise
    monkeypatch.undo()
    log.write("circular", bad=float("nan"))
    cyc = []
    cyc.append(cyc)
    log.write("cyclic", bad=cyc)  # ValueError from json: swallowed
