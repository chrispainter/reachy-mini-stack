from hermes_bench import parse_agent_log

LINES = [
    "2026-10-05 05:26:21,899 INFO [s1] agent.turn_context: conversation turn: session=s1 model=gpt-5.4-mini",
    "2026-10-05 05:26:24,383 INFO [s1] agent.conversation_loop: API call #1: model=gpt-5.4-mini provider=openai-api in=11762 out=105 total=11867 latency=2.4s id=resp_a",
    "2026-10-05 05:26:24,463 INFO agent.tool_executor: tool skill_view completed (0.06s, 2513 chars)",
    "2026-10-05 05:26:27,255 INFO [s1] agent.conversation_loop: API call #2: model=gpt-5.4-mini provider=openai-api in=13532 out=144 total=13676 latency=2.8s cache=11776/13532 (87%) id=resp_b",
    "2026-10-05 05:26:30,000 INFO [s2] agent.conversation_loop: API call #1: model=gpt-5.4-mini provider=openai-api in=1 out=1 total=2 latency=9.9s id=resp_c",
]


def test_parse_agent_log_counts_calls_and_latency_for_one_session():
    assert parse_agent_log(LINES, "s1") == {"api_calls": 2, "llm_s": 5.2}


def test_parse_agent_log_unknown_session_is_zero():
    assert parse_agent_log(LINES, "nope") == {"api_calls": 0, "llm_s": 0.0}
