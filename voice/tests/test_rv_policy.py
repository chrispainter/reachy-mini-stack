from reachy_voice.policy import EngineChooser, SessionPolicy, choose_lane, other_engine


def test_idle_close_after_quiet():
    p = SessionPolicy(idle_timeout_s=30, pending_max_s=300, max_session_s=600)
    assert p.should_close(now=40, opened_at=0, last_activity=20, pending_since=None) is None
    assert p.should_close(now=50, opened_at=0, last_activity=20, pending_since=None) == "idle"


def test_pending_handoff_keeps_session_open_until_cap():
    p = SessionPolicy(idle_timeout_s=30, pending_max_s=300, max_session_s=600)
    assert p.should_close(now=100, opened_at=0, last_activity=10, pending_since=50) is None
    assert p.should_close(now=360, opened_at=0, last_activity=10, pending_since=50) == "pending_timeout"


def test_max_duration_wins_even_with_constant_activity():
    p = SessionPolicy(idle_timeout_s=30, pending_max_s=300, max_session_s=600)
    assert p.should_close(now=600, opened_at=0, last_activity=599.9, pending_since=None) == "max_duration"


def test_engine_chooser_alternates_or_sticks():
    alt = EngineChooser("alternate")
    assert [alt.next() for _ in range(4)] == ["gemini", "openai", "gemini", "openai"]
    assert [EngineChooser("openai").next() for _ in range(2)] == ["openai", "openai"]
    assert other_engine("gemini") == "openai" and other_engine("openai") == "gemini"


def test_choose_lane():
    assert choose_lane("What's on the grocery list?") == "quick"
    assert choose_lane("add bread to the shopping list") == "quick"
    assert choose_lane("Plan a weekend trip to the coast with the kids") == "task"
    assert choose_lane("") == "task"
