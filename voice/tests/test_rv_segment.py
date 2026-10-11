from reachy_voice.segment import TurnSegmenter


def test_request_is_users_words_since_robot_last_spoke():
    s = TurnSegmenter()
    s.on_user_text(" Hi Reachy")
    s.on_robot_text(" Hello!")
    s.on_user_text(" What's on")
    s.on_user_text(" the grocery list")
    assert s.request() == "What's on the grocery list"


def test_robot_acknowledgement_before_delegation_keeps_the_request():
    s = TurnSegmenter()
    s.on_user_text(" What's on the grocery list")
    s.on_robot_text(" Checking now.")   # gpt-live-1 acks before the delegation event
    assert s.request() == "What's on the grocery list"


def test_blank_robot_text_does_not_split_turns():
    s = TurnSegmenter()
    s.on_user_text(" add")
    s.on_robot_text("  ")
    s.on_user_text(" bread")
    assert s.request() == "add bread"


def test_request_is_capped():
    s = TurnSegmenter(max_chars=10)
    s.on_user_text("x" * 50)
    assert len(s.request()) == 10
