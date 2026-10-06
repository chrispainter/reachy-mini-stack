"""Audio format conversion between the robot SDK and the voice engines."""

import numpy as np
from scipy.signal import resample_poly


def _mono(frame: np.ndarray) -> np.ndarray:
    # The robot mic delivers two identical channels; take the first.
    return frame[:, 0] if frame.ndim == 2 else frame


def mic_to_pcm16(frame: np.ndarray) -> bytes:
    """Robot mic float32 in [-1, 1], shape (n,) or (n, ch) -> mono 16-bit little-endian PCM."""
    clipped = np.clip(_mono(frame), -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


def pcm16_to_float(data: bytes, src_rate: int, dst_rate: int = 16000) -> np.ndarray:
    """16-bit PCM from an engine -> float32 mono at the robot's playback rate."""
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if src_rate != dst_rate:
        g = int(np.gcd(src_rate, dst_rate))
        samples = resample_poly(samples, dst_rate // g, src_rate // g).astype(np.float32)
    return samples


def rms(frame: np.ndarray) -> float:
    mono = _mono(frame)
    return float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
