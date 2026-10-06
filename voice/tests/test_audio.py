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
