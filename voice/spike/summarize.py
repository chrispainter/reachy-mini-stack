"""Turn a spike JSONL log into a few lines for RESULTS.md."""

import json
import statistics
import sys


def summarize(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    opened = next((e for e in events if e["event"] == "session_open"), {})
    latencies = [e["latency_s"] for e in events if e["event"] == "first_audio"]
    tools = [e for e in events if e["event"] == "tool_result"]
    interruptions = sum(1 for e in events if e["event"] in ("interrupted", "barge_in"))

    lines = [f"engine: {opened.get('engine', '?')} ({opened.get('model', '?')}, voice {opened.get('voice', '?')})"]
    if latencies:
        lines.append(
            f"first audio after user speech: n={len(latencies)}, "
            f"median {statistics.median(latencies):.2f} s, max {max(latencies):.2f} s"
        )
    for t in tools:
        lines.append(f"tool {t['call_id']}: {t['robot_audio_s_during']} s of speech during a {t['tool_s']} s tool")
    lines.append(f"interruptions: {interruptions}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(sys.argv[1]))
