import numpy as np

from reachy_voice.activity import OutputActivity, UserSpeech

VOICED = np.full(1600, 0.2, np.float32)   # 0.1 s at 16 kHz
SILENT = np.zeros(1600, np.float32)


def test_silent_output_is_not_speaking():
    out = OutputActivity()
    assert out.accept(SILENT, 16000, now=0.0) == (True, None)
    assert not out.is_speaking(0.05)


def test_voiced_output_schedules_and_reports_start():
    out = OutputActivity()
    out.accept(SILENT, 16000, now=0.0)                 # queue ends at 0.1
    play, start = out.accept(VOICED, 16000, now=0.02)  # starts after the silence
    assert play and abs(start - 0.1) < 1e-9
    assert out.is_speaking(0.15) and not out.is_speaking(0.21)
    assert abs(out.voiced_end - 0.2) < 1e-9


def test_queue_is_bounded_for_faster_than_realtime_silence():
    out = OutputActivity(max_queue_s=0.3)
    accepted = [out.accept(SILENT, 16000, now=0.0)[0] for _ in range(10)]
    assert accepted[:3] == [True, True, True] and not any(accepted[3:])
    assert out.queued_s(0.0) <= 0.3 + 1e-9
    assert out.accept(VOICED, 16000, now=0.0)[0]       # speech is never dropped


def test_clear_stops_speaking():
    out = OutputActivity()
    out.accept(VOICED, 16000, now=0.0)
    out.clear(now=0.05)
    assert not out.is_speaking(0.06) and out.queued_s(0.06) == 0.0


def test_latency_from_last_user_voice_to_first_voiced_output():
    user = UserSpeech(threshold=0.015)
    user.on_mic(0.05, now=1.0, robot_speaking=False)
    user.on_mic(0.05, now=1.4, robot_speaking=False)
    user.on_mic(0.001, now=1.6, robot_speaking=False)
    assert user.on_voiced_output(2.5) == 1.1
    assert user.on_voiced_output(2.6) is None          # once per turn
    assert user.last_voice == 1.4


def test_mic_ignored_while_robot_speaks():
    user = UserSpeech()
    user.on_mic(0.5, now=1.0, robot_speaking=True)
    assert user.last_voice is None and user.on_voiced_output(1.2) is None
