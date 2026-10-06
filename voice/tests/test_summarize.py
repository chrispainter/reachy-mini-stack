import json

from spike.summarize import summarize


def test_summarize_reports_latency_and_dead_air(tmp_path):
    path = tmp_path / "run.jsonl"
    events = [
        {"event": "session_open", "ts": 0, "engine": "gemini", "model": "gemini-3.8-live"},
        {"event": "first_audio", "ts": 1, "latency_s": 0.8},
        {"event": "first_audio", "ts": 2, "latency_s": 1.2},
        {"event": "tool_result", "ts": 3, "call_id": "c1", "tool_s": 20.0, "robot_audio_s_during": 3.5},
        {"event": "interrupted", "ts": 4},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events))
    text = summarize(str(path))
    assert "gemini" in text
    assert "median 1.00 s" in text
    assert "max 1.20 s" in text
    assert "3.5 s of speech during a 20.0 s tool" in text
    assert "interruptions: 1" in text
