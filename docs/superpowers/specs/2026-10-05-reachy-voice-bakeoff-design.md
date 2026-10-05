# Reachy Voice: fast, natural conversation with an engine bake-off

Date: 2026-10-05
Status: design approved in brainstorming; awaiting spec review

## Problem

Reachy is the household's voice interface. Hermes on the Pi does the real work
(see `household/README.md`). Talking to Reachy today is slow and stilted.
These turn times were measured on the robot with Pollen's conversation app
v1.0.1 and its Hugging Face realtime backend:

| Turn | Time to first audio | Cause |
|---|---|---|
| "What time is it?" | 6.7 s | Remote time tool; silence until it returned |
| "What's on the grocery list?" | 17.5 s | Hermes took 16.7 s; silence the whole time |

Three causes:

1. The Hugging Face backend never speaks while a tool runs, so every tool call
   produces dead air.
2. That backend is a cascade (speech-to-text, LLM, text-to-speech), which is
   slower and less natural than native speech-to-speech models.
3. Hermes takes about 17 s even for trivial lookups.

Pollen's app removed its OpenAI and Gemini backends in v0.9.0 (PR #444).
Better models therefore mean running our own voice app.

## Goals

- Reachy responds as fast and naturally as current models allow. Target: under
  1.5 s to first audio for turns without a tool.
- No dead air during delegated work. Reachy acknowledges straight away, keeps
  conversing, and speaks Hermes' answer at a natural pause.
- Compare Gemini 3.8 Live and OpenAI `gpt-live-1` by ear in daily use, then keep
  the winner.
- Quick household lookups through Hermes answer in 2–4 s.

## Non-goals

- Telegram or other messaging channels, Home Assistant, identifying speakers by
  face, and new camera features.
- Replacing Hermes or changing its role.
- Always-on listening.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Priority | Responsiveness and natural feel first; any provider allowed |
| How a conversation starts | Local wake word ("Hey Reachy"). A session closes after ~30 s of quiet |
| Cost | Quality first. Use the Google AI plan's Cloud credits ($10 or $100/mo) for Gemini, and OpenAI pay-as-you-go for `gpt-live-1`. Revisit once usage is known |
| Engines | Bake-off between Gemini 3.8 Live (`gemini-3.8-live`) and OpenAI `gpt-live-1` |
| Where it runs | On the robot (Reachy Mini Wireless, CM4), installed as a Reachy app |
| Memory | Hermes is the only household memory. Pollen's `remember`/`forget` are not used |

Rejected options:

- **ElevenLabs Agents:** best voice selection, but a cascade with unverified
  async-tool semantics. Keep in reserve as a third engine.
- **Hume EVI:** shuts down 2026-11-13.
- **Grok voice and Ultravox:** no native talk-while-tool-runs.
- **Fully local stacks:** not natural enough on the hardware we own.

Claude Pro can't be used. Anthropic restricts subscription logins to its own
apps.

## Architecture

```
 "Hey Reachy" ─► WakeWord (openWakeWord on the robot; nothing leaves the house before this)
                   │ opens a session; closes after ~30 s of quiet or a spoken goodbye
                   ▼
   reachy_voice app (new; runs on the robot under the daemon like any Reachy app)
   ├─ AudioIO: robot mic and speaker via the SDK's local media path (no WebRTC);
   │           keeps the XVF3800 hardware echo cancellation
   ├─ VoiceEngine (interface)
   │    ├─ GeminiLiveEngine  gemini-3.8-live, non-blocking function calls,
   │    │                    results delivered with scheduling WHEN_IDLE
   │    └─ OpenAILiveEngine  gpt-live-1, client delegation; results returned
   │                         via session.commentary.append
   ├─ Body: Pollen conversation-app modules used as a library (movement manager,
   │        emotions, dances, speech head-wobble, face tracking). Pinned to the
   │        installed version
   ├─ HermesClient: async; lanes "quick" and "task"; one Hermes session per
   │                conversation (X-Hermes-Session-Id)
   ├─ PendingAnswers: holds Hermes results that arrive after a session closed,
   │                  and speaks them proactively ("By the way…")
   └─ Metrics: one JSON line per turn, sent to the Pi; nightly scorecard
```

### Units and interfaces

- **WakeWord:** `async for event in wake.listen()`. Yields an event when "Hey
  Reachy" is detected. Depends only on mic frames.
- **AudioIO:** `frames()` yields 16 kHz PCM from the mic. `play(pcm, rate)` and
  `clear()` drive the speaker; `clear()` is for barge-in. Wraps the SDK media
  calls and resamples to each engine's rate (Gemini: 16 kHz in, 24 kHz out;
  OpenAI: 24 kHz).
- **VoiceEngine:**
  - `open(persona, tools)` and `close()`
  - `send_audio(frame)`
  - events: `audio_out`, `user_speech_started`, `delegate(request, lane, call_id)`, `turn_metrics`
  - `deliver(call_id, text, when="idle")` returns a delegated result to the engine
- **HermesClient:** `ask(request, asked_by, lane, session_id) -> str`. Raises a
  typed error on timeout or unreachable. Quick lane: 90 s timeout. Task lane:
  5 min.
- **Body:** `listening()`, `thinking()`, `speaking(level)`, `emotion(name)`,
  `move_head(direction)`, `sleep()`. Exposes the same body tool specs to both
  engines.
- **Orchestrator:** owns the session lifecycle, connects the units together,
  and holds the engine choice.

Each unit lives in its own module and is tested with fakes of its
neighbours.

## Conversation flow

1. Idle. The wake word listens locally.
2. Wake word fires. Reachy wiggles its antennas and orients toward the sound.
   The engine session opens (~0.5 s). Mic audio is buffered meanwhile and
   flushed once the session is up, so the first words aren't lost.
3. Free-flowing conversation with native barge-in. While the user talks, the
   head stays still, because motion noise degrades the Wireless mic
   (Pollen #1334). The head wobbles only while Reachy speaks.
4. When work is needed, the engine delegates (`lane` is `quick` or `task`).
   Reachy acknowledges in its own words and keeps conversing. HermesClient runs
   in the background, and the result goes back with `deliver(..., when="idle")`.
5. A result that arrives after the session closed goes into PendingAnswers.
   Reachy then briefly re-opens a session to say it.
6. After ~30 s of quiet, or a goodbye, Reachy says a short farewell, closes the
   session, and returns to idle.

## Hermes fast lane

- First, measure where Hermes' 16.7 s goes: model calls, tool loop, prompt
  size, and startup. Add timing from Hermes' logs to the metrics.
- `quick` lane requests use a lighter configuration: a smaller or faster model
  and minimal reasoning. If Hermes' per-request overrides allow it, also a
  trimmed toolset; otherwise use a second Hermes profile. Target is 2–4 s.
- If the measurement shows the cost is mostly prompt size or cache misses, fix
  that first. That may remove the need for a separate lane.

## Bake-off

- `ENGINE=gemini|openai|alternate`. In `alternate`, the engine switches on each
  wake-word session. The spoken command "use the other voice" switches
  mid-conversation.
- Both engines get identical persona, safety rules, and tools. Each uses its
  best-sounding voice, chosen by a quick listen before the bake-off starts.
- Every turn is logged: engine, time to first audio, interruptions, delegation
  lane and Hermes duration, and estimated session cost.
- Spoken verdicts ("that was great" / "that was awkward") tag the session.
- A nightly scorecard (Markdown) is written on the Pi.
- After a few days, choose the winner by scorecard plus verdicts. Set `ENGINE`
  to it and drop the loser's key.

## Failure handling

| Failure | Behaviour |
|---|---|
| Engine connect fails or the session drops | Say "Sorry, I lost my train of thought", retry once, then fall back to the other engine |
| Both engines down | Short spoken notice plus a sad antenna pose. The wake word keeps working |
| Hermes timeout or unreachable | Engine tells the person plainly. It never invents a result |
| Credits exhausted or key rejected | Treated as an engine failure. Logged and flagged on the scorecard |
| App crash | The daemon marks the app as errored. Pollen's app remains installed as a fallback |

## Safety and privacy

- No audio leaves the robot before the wake word. An antenna pose shows when
  Reachy is listening.
- The shared persona keeps the hard rule: nothing outward-facing (messages,
  purchases, bookings, sharing personal details) without an explicit spoken
  yes. Hermes keeps `approvals.unattended_mode: deny`.
- Gemini runs on paid-tier billing, funded by the plan credits. On the free
  tier, inputs may be read by human reviewers and used for training.
- Keys live in the app's `.env` on the robot (mode 600) and in the Pi's
  `~/.config/household/agent.env`. Nothing secret, and no household names, go in
  git: the repo is public.

## Prerequisites

- Robot software 1.11.0 (done 2026-10-05). Pollen's app 1.0.1 needs SDK ≥ 1.10.
- A Gemini API key on a paid-tier project, with the Google AI plan's Cloud
  credits activated (developers.google.com/program/my-benefits).
- A new OpenAI API key. The current one was flagged in May for replacement.
  The new key replaces it for Hermes as well.
- Disk on the robot: ~1.4 GB free after cache cleanup. The new dependencies
  are ~150 MB.

## Testing and rollout

1. **Spike (first).** One bare script per engine, run on the robot. It checks
   three things:
   - Does the model keep talking during a fake 20 s tool, and does the result
     land at a natural pause?
   - Time to first audio.
   - Barge-in over the robot's own speaker.

   The Gemini docs disagree about non-blocking calls on 3.8; this resolves it.
   If an engine fails, revisit this design before building further.
2. **Unit tests (Mac, no robot):**
   - engine interface, using fake engines
   - HermesClient lanes and timeouts
   - session timing
   - PendingAnswers
3. **On-robot checks (scripted from the Mac):**
   - the app installs and starts from the dashboard
   - the wake word triggers
   - a canned "what's on the grocery list?" round trip on each engine, with
     latency recorded
4. **Rollout:**
   1. Install alongside Pollen's app.
   2. Bake-off for a few days.
   3. Pick the winner.
   4. Make it the startup app.

## Open questions resolved by the spike

- Gemini 3.8 Live: is `NON_BLOCKING` actually the default, and does
  `WHEN_IDLE` scheduling behave as described?
- `gpt-live-1`: how predictable is delegation timing? Developers report it
  isn't. Is there a usable way to end the session?
- Which voices sound best on Reachy's small speaker.
