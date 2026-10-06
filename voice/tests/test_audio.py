import numpy as np

from spike.audio import mic_to_pcm16, pcm16_to_float, rms


def test_mic_to_pcm16_takes_first_channel_and_scales():
    frame = np.array([[0.5, -1.0], [-0.5, 1.0], [2.0, 0.0]], dtype=np.float32)
    out = np.frombuffer(mic_to_pcm16(frame), dtype="<i2")
    assert out.tolist() == [16383, -16383, 32767]  # clipped at +1.0


def test_mic_to_pcm16_accepts_mono():
    frame = np.zeros(1024, dtype=np.float32)
    assert len(mic_to_pcm16(frame)) == 2048


def test_pcm16_to_float_same_rate_roundtrip():
    pcm = (np.array([0, 16384, -16384], dtype="<i2")).tobytes()
    out = pcm16_to_float(pcm, 16000, 16000)
    assert out.dtype == np.float32
    assert np.allclose(out, [0.0, 0.5, -0.5])


def test_pcm16_to_float_resamples_24k_to_16k():
    pcm = np.zeros(2400, dtype="<i2").tobytes()  # 100 ms at 24 kHz
    out = pcm16_to_float(pcm, 24000, 16000)
    assert out.shape == (1600,)  # 100 ms at 16 kHz


def test_rms_of_stereo_frame_uses_first_channel():
    frame = np.stack([np.full(100, 0.1), np.zeros(100)], axis=1).astype(np.float32)
    assert abs(rms(frame) - 0.1) < 1e-6


def _sine_pcm(n_total=24000, f=440.0, rate=24000):
    t = np.arange(n_total) / rate
    return (np.sin(2 * np.pi * f * t) * 16000).astype("<i2")


def _chunks(pcm):
    cuts = [0, 1000, 4100, 7300, 11000, 15555, 20000, len(pcm)]
    return [pcm[a:b].tobytes() for a, b in zip(cuts, cuts[1:])]


def test_stream_resampler_total_length():
    from spike.audio import StreamResampler

    r = StreamResampler(24000, 16000)
    out = np.concatenate([r.process(c) for c in _chunks(_sine_pcm())] + [r.flush()])
    assert out.dtype == np.float32
    assert abs(len(out) - 16000) <= 32


def test_stream_resampler_matches_single_call():
    import soxr

    from spike.audio import StreamResampler

    pcm = _sine_pcm()
    r = StreamResampler(24000, 16000)
    out = np.concatenate([r.process(c) for c in _chunks(pcm)])
    ref = soxr.resample(pcm.astype(np.float32) / 32768.0, 24000, 16000)
    np.testing.assert_allclose(out[2000:14000], ref[2000:14000], atol=1e-3)
