import math

from reachy_voice import body_calibration as cal
from reachy_voice.body_policy import CUES, EMOTIONS, LOOK_DIRECTIONS, AwakeTimer, ExpressionGate, doa_to_yaw


def test_cues_use_known_emotions():
    assert set(CUES) == {"wake", "handoff_start", "handoff_ok", "handoff_failed", "session_end"}
    assert CUES["handoff_start"] == "thinking" and CUES["wake"] == "welcoming"
    assert all(v in EMOTIONS for v in CUES.values())
    assert "random" not in EMOTIONS and "at_person" in LOOK_DIRECTIONS


def test_doa_to_yaw_front_is_zero_and_clamped():
    assert doa_to_yaw(None) is None
    if getattr(cal, "DOA_ENABLED", True):
        assert abs(doa_to_yaw(cal.DOA_FRONT_RAD)) < 1e-9
        far = doa_to_yaw(cal.DOA_FRONT_RAD + cal.DOA_SIGN * math.pi)
        assert abs(far) == cal.MAX_TURN_RAD
        assert abs(doa_to_yaw(cal.DOA_FRONT_RAD + cal.DOA_SIGN * 0.3) - 0.3) < 1e-9
    else:
        assert doa_to_yaw(1.0) is None


def test_doa_to_yaw_wraps_around():
    if getattr(cal, "DOA_ENABLED", True):
        a = cal.DOA_FRONT_RAD + cal.DOA_SIGN * 0.2
        assert abs(doa_to_yaw(a + 2 * math.pi) - 0.2) < 1e-9


def test_awake_timer_lifecycle():
    t = AwakeTimer(idle_awake_s=300)
    assert not t.awake and not t.should_sleep(1000)
    t.on_wake(0)
    assert t.awake and not t.should_sleep(10_000)   # in a session: never sleeps
    t.on_session_end(100)
    assert not t.should_sleep(399) and t.should_sleep(400)
    t.on_wake(390)                                   # wake word while awake idle
    assert not t.should_sleep(1000)
    t.on_session_end(1000)
    t.on_sleep()
    assert not t.awake and not t.should_sleep(5000)


def test_gate_spacing_user_speech_and_utterance_grace():
    g = ExpressionGate(min_gap_s=8, user_quiet_s=0.5, utterance_grace_s=1.0)
    assert g.allow(now=10, last_user_voice=None, utterance_started_at=None)
    assert not g.allow(now=15, last_user_voice=None, utterance_started_at=None)       # within 8 s
    assert not g.allow(now=20, last_user_voice=19.8, utterance_started_at=None)       # person talking
    assert not g.allow(now=20, last_user_voice=None, utterance_started_at=19.5)       # utterance just began
    assert g.allow(now=20, last_user_voice=19.0, utterance_started_at=18.0)
    assert not g.allow(now=21, last_user_voice=None, utterance_started_at=None)


def test_median_recent_empty_is_none():
    from reachy_voice.body_policy import median_recent
    assert median_recent([], 10.0) is None


def test_median_recent_excludes_old_entries():
    from reachy_voice.body_policy import median_recent
    assert median_recent([(7.0, 3.0)], 10.0) is None
    assert median_recent([(7.0, 3.0), (9.0, 1.0)], 10.0) == 1.0


def test_median_recent_takes_median_of_several():
    from reachy_voice.body_policy import median_recent
    samples = [(9.0, 1.5), (9.5, 0.2), (9.8, 1.4), (9.9, 1.6)]
    assert median_recent(samples, 10.0) == 1.45
    assert median_recent([(9.0, 0.0), (9.5, 5.0), (9.9, 1.0)], 10.0) == 1.0


def test_median_recent_window_boundary_inclusive():
    from reachy_voice.body_policy import median_recent
    assert median_recent([(8.5, 2.0)], 10.0) == 2.0
