from spike.timing import BargeInDetector, DeadAirMeter, PlaybackClock, ReplyDropper, TurnTimer


def test_playback_clock_tracks_queued_audio():
    clock = PlaybackClock()
    assert not clock.is_speaking(0.0)
    clock.push(16000, 16000, now=0.0)  # 1 s queued
    clock.push(8000, 16000, now=0.2)   # +0.5 s appended after the first second
    assert clock.is_speaking(1.4)
    assert not clock.is_speaking(1.6)
    clock.reset(now=0.3)
    assert not clock.is_speaking(0.31)


def test_turn_timer_measures_from_last_user_speech_to_first_robot_audio():
    t = TurnTimer(speech_threshold=0.02)
    t.on_mic(0.10, now=1.0, robot_speaking=False)
    t.on_mic(0.10, now=1.5, robot_speaking=False)  # last loud frame
    t.on_mic(0.001, now=1.8, robot_speaking=False)
    assert t.on_robot_audio(now=2.6) == 1.1
    assert t.on_robot_audio(now=2.7) is None  # only the first chunk counts


def test_turn_timer_ignores_mic_while_robot_speaks():
    t = TurnTimer()
    t.on_mic(0.5, now=1.0, robot_speaking=True)
    assert t.on_robot_audio(now=1.2) is None


def test_dead_air_meter_reports_audio_during_tool():
    m = DeadAirMeter()
    m.start("c1", now=10.0)
    m.on_audio(now=11.0, seconds=1.5)
    m.on_audio(now=25.0, seconds=2.0)
    report = m.end("c1", now=30.0)
    assert report == {"call_id": "c1", "tool_s": 20.0, "robot_audio_s_during": 3.5}
    m.on_audio(now=31.0, seconds=1.0)  # after end: not counted anywhere


def test_barge_in_needs_consecutive_loud_frames_while_speaking():
    d = BargeInDetector(threshold=0.08, frames=3)
    assert not d.on_frame(0.2, robot_speaking=True)
    assert not d.on_frame(0.2, robot_speaking=True)
    assert d.on_frame(0.2, robot_speaking=True)
    assert not d.on_frame(0.2, robot_speaking=False)  # resets when silent
    assert not d.on_frame(0.01, robot_speaking=True)


def test_reply_dropper_idle_by_default():
    assert ReplyDropper().should_drop(1.0) is False


def test_reply_dropper_drops_consecutive_deltas_after_start():
    d = ReplyDropper()
    d.start(10.0)
    assert d.should_drop(10.1) is True
    assert d.should_drop(10.2) is True
    assert d.should_drop(10.3) is True


def test_reply_dropper_stops_after_gap():
    d = ReplyDropper()
    d.start(10.0)
    assert d.should_drop(10.1) is True
    assert d.should_drop(10.45) is False
    assert d.should_drop(10.5) is False  # drop window is over


def test_reply_dropper_counts_dropped_chunks():
    d = ReplyDropper()
    d.start(0.0)
    d.should_drop(0.1)
    d.should_drop(0.2)
    assert d.dropped == 2
    d.should_drop(0.6)
    assert d.dropped == 2
