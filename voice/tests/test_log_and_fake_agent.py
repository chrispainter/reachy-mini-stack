import asyncio
import json

from spike.fake_agent import FAKE_ANSWER, fake_home_agent
from spike.log import JsonlLog


def test_jsonl_log_appends_events_with_timestamp(tmp_path):
    path = tmp_path / "x.jsonl"
    log = JsonlLog(str(path))
    log.write("first_audio", latency_s=0.8)
    log.write("turn_complete")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["event"] for line in lines] == ["first_audio", "turn_complete"]
    assert lines[0]["latency_s"] == 0.8
    assert isinstance(lines[0]["ts"], float)


def test_fake_home_agent_returns_fixed_answer_after_delay():
    result = asyncio.run(fake_home_agent("what's on the list", delay_s=0.01))
    assert result == FAKE_ANSWER
