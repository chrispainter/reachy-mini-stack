# Voice spike results

## Setup

- Date: 2026-10-11. Quiet room, TV off, speaker about 1 m from the mic.
- Calibration: quiet mic RMS p50 0.0016, p99 0.0083, max 0.0103; talking p50 0.0255, p75 0.0574, p90 0.0847.
- Chosen `--speech-threshold` 0.015. Earlier high ambient readings (0.03-0.08) came from TV and people in the room.

## Gemini 3.8 Live

Voice: Kore (log `logs/gemini-1791750854.jsonl`).

```
engine: gemini (gemini-3.8-live, voice Kore)
first audio after user speech: n=10, median 1.30 s, max 1.81 s
tool call_1385923: 8.288 s of speech during a 20.004 s tool
interruptions: 4
```

1. Talk during the tool: yes. It said "Sure, let me check the list for you", then answered the favourite-colour question during the 20 s tool.
2. Natural pause: yes. "By the way, the grocery list currently has milk, eggs, and coffee on it." Spoken 4.8 s after the result arrived (24.8 s from the request).
3. Barge-in: the story was cut off when interrupted; the listener said "it stopped pretty quickly".
4. Naturalness: 4/5 (listener).

Deviations and issues:
- Early on it misheard a garbled fragment ("escarne") as Spanish and replied in Spanish ("Perdona, no te entendí bien..."), then recovered. Plan 2 should pin English in the persona and in the Gemini speech config (`language_code` en-US).
- Voice comparison (Puck, Aoede) was not done; Kore was used throughout.

## OpenAI gpt-live-1

Voice: marin (rerun log `logs/openai-1791751209.jsonl`).

First attempt (`logs/openai-1791751108.jsonl`) was silent. The user's first words (level 0.24) tripped the local `BargeInDetector` at 0.08. The `ReplyDropper` then waited for a 0.3 s gap in `output_audio.delta` that never came, because gpt-live-1 streams audio continuously (including silence), so every reply was dropped. The rerun used `--barge-threshold 99`, which disables local barge-in; the model handles talk-over itself per OpenAI docs.

Summary of the rerun:

```
engine: openai (gpt-live-1, voice marin)
first audio after user speech: n=4, median 0.01 s, max 0.03 s
tool item_EXudlD3CvQvaWzAqVufVl: 19.4 s of speech during a 20.002 s tool
interruptions: 0 (local barge-in disabled)
```

INVALID numbers:
- First-audio latency (median 0.01 s, max 0.03 s) is invalid. The continuous audio stream keeps the `PlaybackClock` in the "speaking" state and defeats the speaker-side `TurnTimer`. Latency is not measurable from these logs: transcript timing is not comparable to Gemini, which emits its input transcript only at turn end. OpenAI publishes about 0.8 s turn-taking. The listener said response speed felt similar to Gemini.
- Speech during the tool (19.4 s of 20.002 s) is invalid as a number, because it is inflated by streamed silence. The transcript confirms it did talk during the tool.

1. Talk during the tool: yes. "Checking now. I'll be right back." Then it answered the colour question.
2. Natural pause: yes. "Okay, I've got it. The list has milk, eggs, and coffee." Spoken 2.4 s after the result arrived (22.4 s from the request).
3. Barge-in: the story was cut off mid-sentence ("...if the sunlight felt") and it moved to the joke. The model stopped itself.
4. Naturalness: 5/5 (listener).

Delegation timing: it fired at a sensible moment, right after "What's on the grocery list". However, the delegation request text was the whole rolling transcript since session start ("Hi Reachy, how are you today What's a good name for a goldfish ... What's on the grocery list"), because gpt-live-1 transcripts carry no turn boundaries. Plan 2 needs turn segmentation.

Deviations: local barge-in disabled (`--barge-threshold 99`). Voice comparison (cedar, vesper) was not done; marin was used throughout.

## Hermes quick lookups

Change: appended a "Household data" section to `household/hermes/SOUL.md` mapping the list/notes files in /opt/data, telling Hermes to go straight to the file instead of searching. Benchmark: `household/tools/hermes_bench.py`, run on the Pi (2026-10-05).

Before:

| Request | Wall s | Model calls | Model s | Answer |
|---|---:|---:|---:|---|
| What's on the grocery list? | 18.9 | 7 | 16.6 | The grocery list has milk and eggs. |
| Add bread to the grocery list. | 14.6 | 6 | 12.9 | Done — I added bread to the grocery list. |
| What's on the grocery list? | 16.3 | 7 | 15.5 | The grocery list has milk, eggs, and bread. |
| Remove bread from the grocery list. | 31.4 | 11 | 28.9 | Done, I removed bread from the grocery list. |

After:

| Request | Wall s | Model calls | Model s | Answer |
|---|---:|---:|---:|---|
| What's on the grocery list? | 7.2 | 2 | 4.9 | Milk and eggs. |
| Add bread to the grocery list. | 9.1 | 3 | 8.7 | Done — I added bread to the grocery list. |
| What's on the grocery list? | 7.4 | 3 | 7.1 | The grocery list has milk, eggs, and bread. |
| Remove bread from the grocery list. | 10.0 | 4 | 9.5 | Done — I removed bread from the grocery list. |

Near-miss: the second lookup took 3 model calls / 7.4 s against the 2-call / ~6 s target, and the remove edit took 4 calls.

## Decision

| | Gemini 3.8 Live | OpenAI gpt-live-1 |
|---|---|---|
| First-audio latency, median | 1.30 s | not measurable (see above) |
| First-audio latency, max | 1.81 s | not measurable (see above) |
| Speech during tool | yes (8.3 s of 20 s) | yes (transcript-confirmed; the 19.4 s figure is invalid) |
| Result at a natural pause | yes, 4.8 s after the result arrived | yes, 2.4 s after the result arrived |
| Barge-in | works; story stopped quickly | works; model stopped itself mid-sentence |
| Voice | Kore | marin |
| Naturalness (listener, 1-5) | 4 | 5 |
| Cost per minute | about $0.023 | $0.05 |

Listener note: response speed felt similar between the two. The shopping-list answer felt slower with OpenAI, but the timing data shows both waited the fake 20 s and OpenAI spoke the list sooner after it arrived (2.4 s vs 4.8 s). Real Hermes lookups now take about 7 s.

Rule outcome: both engines talk during the tool, deliver the result at a pause and handle barge-in. Rule "Both pass" applies, so Plan 2 builds the full bake-off as specified.

### Lessons for Plan 2

1. OpenAI: no local barge-in or reply-drop; rely on the model. Measure latency differently (for example server-side timing, or VAD on the mic against the first non-silent output sample).
2. OpenAI delegation needs turn-segmented request text (for example only text after the robot's last utterance, or transcript start_ms/end_ms gaps).
3. Gemini: pin English in the persona and speech config (`language_code` en-US).
4. Speech threshold 0.015 in a quiet room. TV noise is a real-world issue, so a wake word matters.
5. Cost: Gemini about $0.023/min (Google credits) vs gpt-live-1 $0.05/min.
