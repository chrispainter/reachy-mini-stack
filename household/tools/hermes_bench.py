"""Benchmark Hermes on quick household requests. Run on the Pi:
    python3 hermes_bench.py --label before
Reads the API key from ~/.config/household/agent.env and per-call timings from
Hermes' agent.log (via docker exec). Prints a Markdown table.
"""

import argparse
import json
import pathlib
import re
import subprocess
import time
import urllib.request

URL = "http://127.0.0.1:8642/v1/chat/completions"
REQUESTS = [
    "What's on the grocery list?",
    "Add bread to the grocery list.",
    "What's on the grocery list?",
    "Remove bread from the grocery list.",
]
_CALL = re.compile(r"\[(?P<sid>[^\]]+)\] agent\.conversation_loop: API call #\d+: .*?latency=(?P<lat>[\d.]+)s")


def parse_agent_log(lines: list[str], session_id: str) -> dict:
    calls = [float(m["lat"]) for line in lines if (m := _CALL.search(line)) and m["sid"] == session_id]
    return {"api_calls": len(calls), "llm_s": round(sum(calls), 1)}


def _api_key() -> str:
    env = pathlib.Path.home() / ".config/household/agent.env"
    for line in env.read_text().splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("API_SERVER_KEY not found")


def _ask(key: str, session_id: str, text: str) -> tuple[float, str]:
    body = json.dumps({"model": "hermes-agent", "messages": [{"role": "user", "content": f"[Asked by a tester, via Reachy] {text}"}]})
    req = urllib.request.Request(
        URL,
        data=body.encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Hermes-Session-Id": session_id},
    )
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as resp:
        answer = json.load(resp)["choices"][0]["message"]["content"].strip()
    return round(time.monotonic() - start, 1), answer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="run")
    args = p.parse_args()
    key, rows = _api_key(), []
    for i, text in enumerate(REQUESTS):
        sid = f"bench-{args.label}-{int(time.time())}-{i}"
        wall, answer = _ask(key, sid, text)
        log = subprocess.run(
            ["docker", "exec", "hermes", "cat", "/opt/data/logs/agent.log"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
        rows.append((text, wall, parse_agent_log(log, sid), answer))
    print(f"\n### Hermes benchmark: {args.label}\n")
    print("| Request | Wall s | Model calls | Model s | Answer |\n|---|---:|---:|---:|---|")
    for text, wall, stats, answer in rows:
        print(f"| {text} | {wall} | {stats['api_calls']} | {stats['llm_s']} | {answer[:80]} |")


if __name__ == "__main__":
    main()
