# Reachy body language (Plan 3, part 1)

Date: 2026-10-11
Status: design approved in brainstorming; awaiting spec review

## Problem

`reachy_voice` (Plan 2) gives Reachy a fast, natural voice, but the body does
nothing. The daemon reports `motor_control_mode: disabled`, so the head rests in
its slumped position and never moves or reacts during a conversation. Pollen's
old conversation app enabled the motors and moved the head; `reachy_voice` only
uses the mic and speaker.

## Goals

- Reachy looks alive and attentive during a conversation:
  - it wakes up and turns toward the person
  - it follows their face while speaking
  - it moves its head with its own speech
  - it shows expressions at fitting moments
- Reachy is still and quiet between conversations, after a short awake period.
- Movement never makes Reachy worse at hearing people.
- The body never breaks the voice. Any motion failure degrades to voice-only.
- The Gemini vs OpenAI bake-off stays fair: same cues, same expression vocabulary.

## Non-goals

- Dances on request, choreography, and gestures beyond the emotion library.
- Recognising who is speaking, by face or voice.
- Changing the voice engines, the wake word or Hermes.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Between conversations | Awake and still for `IDLE_AWAKE_S` (default 300 s) after a conversation, then `goto_sleep` with motors off |
| Expressiveness | The engine decides, within limits. Automatic cues for key events, plus model-chosen expressions |
| Facing the person | Turn toward the voice (mic-array direction of arrival) on wake, then daemon-side camera face tracking |
| Approach | Our own `Body` controller over the `reachy_mini` SDK. Don't reuse Pollen's `MovementManager` |

## Behaviour

States:

```
SLEEPING --wake word--> WAKING --> IN_CONVERSATION --session ends--> AWAKE_IDLE --IDLE_AWAKE_S--> SLEEPING
head down,             motors on,     listening <-> speaking          head up, still,
motors off             wake_up move,                                   tracking off
                       turn to voice                                   --wake word--> IN_CONVERSATION
```

- **SLEEPING:** motors off, head down. Nothing moves.
- **WAKING**, on the wake word while asleep:
  - enable motors
  - play `wake_up()`
  - turn toward the direction of arrival captured when the wake word fired
  - start daemon face tracking
  - emit the automatic *welcoming* cue
- **IN_CONVERSATION**:
  - **Listening** (the person is speaking, or nobody is): face tracking paused (weight 0). Antennas raised as a listening cue. No expressions. Head held still so motor noise doesn't degrade the mic (Pollen #1334).
  - **Speaking** (Reachy's output is voiced): face tracking at `TRACKING_WEIGHT` (default 0.6). Speech-driven head motion via the SDK's `enable_wobbling()`. Antennas relaxed.
  - **Expression:** a recorded emotion move (2–4 s). Tracking and wobbling pause for its duration, then resume according to the current state.
- **AWAKE_IDLE**, after a session ends:
  - stop tracking and wobbling
  - head to neutral
  - motors stay on
  - a wake word goes straight to IN_CONVERSATION, with no wake-up move or turn
- **Back to SLEEPING**, after `IDLE_AWAKE_S` with no wake word: play `goto_sleep()`, then disable motors.

## Expressions

The layers below behave the same for both engines.

1. **Automatic cues** (event → emotion):

   | Event | Emotion |
   |---|---|
   | Wake from sleep | `welcoming` |
   | Hand-off to Hermes starts | `thinking` |
   | Hand-off result delivered | `yes_understanding` |
   | Hand-off failed (fallback reply) | `uncertain` |
   | Session ends (any reason except `error`) | `goodbye`, played before `rest()` |

2. **Model-chosen expressions:**
   - **Gemini** gets two more tools: `express(emotion)` and `look(direction)`. Both are declared non-blocking and answered immediately with `{"ok": true}` and `scheduling=SILENT`, so Gemini doesn't comment on them aloud.
     - `emotion` is one of Pollen's intent names (the `EMOTION_INTENTS` list).
     - `direction` is one of `left`, `right`, `up`, `down`, `front` or `at_person`.
     - The persona tells it to express sparingly, at natural moments.
   - **OpenAI** (gpt-live-1 has no tool calling): after each completed Reachy utterance, `ExpressionPicker` sends the utterance text to `gpt-5.4-nano`. It runs off the critical path, with a 3 s timeout. The model returns one emotion name from the same list, or `none`. Errors and timeouts mean `none`.
   - **Utterance boundary:** an utterance ends when `OutputActivity` goes from speaking to not speaking.

3. **Rate limiter** (`ExpressionGate`). It applies to automatic cues and model-chosen expressions alike:
   - at most one expression every `EXPRESSION_MIN_GAP_S` (default 8 s)
   - none while the person is speaking
   - none in the first 1.0 s of a Reachy utterance

   Automatic cues take priority over model-chosen expressions when both are eligible. Anything the gate rejects is dropped (logged), not queued.

Emotion names are resolved with Pollen's `resolve_emotion_name` logic: exact match, then a keyword match, then a curated fallback. The resolved name is played via `reachy_mini.motion.recorded_move.RecordedMoves("pollen-robotics/reachy-mini-emotions-library")`. That dataset is already cached on the robot.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `body.py` `Body` | The only code that drives the robot's motion. Wraps the SDK: `enable_motors`/`disable_motors`, `wake_up`, `goto_sleep`, `goto_target` (turn and neutral), `start_head_tracking(weight)`, `stop_head_tracking`, `enable_wobbling`/`disable_wobbling`, antenna targets, and `async_play_move` for emotions. Every public method catches exceptions, logs `body_error` and returns. | `reachy_mini` SDK, `JsonlLog` |
| `body_policy.py` | Pure logic, no SDK: `AwakeTimer` (awake → sleep), `ExpressionGate` (rate limiting and priority), the event → cue table, and `resolve_emotion(name)` | none |
| `expression_picker.py` `ExpressionPicker` | `async pick(text) -> str \| None` via `gpt-5.4-nano`, with a 3 s timeout | `httpx`, `OPENAI_API_KEY` |
| `session.py` (changed) | Calls body hooks on speaking/listening transitions, user speech, hand-off start/result/failure, utterance end (picker, OpenAI only), and Gemini `express`/`look` tool calls | `Body` (duck-typed; a `NullBody` when disabled) |
| `engines/gemini.py` (changed) | Declares `express` and `look` (non-blocking), answers them immediately, and reports them via a new `on_body_tool(name, args)` callback | — |
| `main.py` (changed) | Owns `Body` and `AwakeTimer`. Wake while asleep runs `body.wake(doa)`; wake while awake goes straight to the session. After a session, `body.rest()`; the timer then runs `body.sleep()`. On shutdown: `sleep()`, then motors off. | — |
| `config.py` (changed) | `BODY_ENABLED` (default true), `IDLE_AWAKE_S` (300), `EXPRESSION_MIN_GAP_S` (8), `TRACKING_WEIGHT` (0.6) | — |

**Direction of arrival:** captured from `mini.media.get_DoA()` when the wake word fires. It returns `(angle, speech_detected)` or `None`, and `None` means don't turn. Translating the angle into a body/head yaw target is verified in the spike (see Testing).

## Failure handling

| Failure | Behaviour |
|---|---|
| Any SDK motion call raises | `body_error` is logged; the call is skipped; the voice continues |
| `RecordedMoves` dataset unavailable | Expressions are disabled for this run (logged once); everything else works |
| Face tracking unavailable (vision extra missing, camera busy) | Logged once; the turn toward the voice still happens; the session runs without tracking |
| DoA unavailable or no speech detected | No turn; tracking only |
| Expression picker error or timeout | No expression |
| `BODY_ENABLED=false` | `NullBody`: voice-only, exactly as in Plan 2 |
| Service stops while awake | `goto_sleep` is attempted, then motors are disabled, so the head isn't left raised with motors on |

## Testing

1. **Spike on the robot first** (throwaway script, with the person present). It verifies:
   - `enable_motors` + `wake_up` / `goto_sleep` + `disable_motors` timing
   - the DoA angle convention: speak from left, front and right, and note how to convert the angle to a yaw target
   - `start_head_tracking(weight)` blending with `enable_wobbling` while audio plays
   - emotion playback duration and whether it conflicts with tracking
   - **whether head motion while the person is speaking measurably hurts recognition.** Compare the transcript quality of the same sentence with the head held still and with it moving.

   The results may change the listening-state rule or the tracking weight.
2. **Unit tests (Mac):**
   - `AwakeTimer`, `ExpressionGate`, the cue table and `resolve_emotion`
   - `ExpressionPicker` with httpx `MockTransport`: valid pick, `none`, garbage, timeout
   - `VoiceSession` body hooks with a fake body: speaking/listening transitions, hand-off cues, utterance-end picker for OpenAI only, gated expressions
   - Gemini `express`/`look` tool handling
3. **On-robot acceptance** (spoken, with the user):
   - wake from sleep: Reachy lifts its head, turns toward the voice and looks at you
   - Reachy stays still while you talk and moves while it speaks
   - a *thinking* cue during a Hermes hand-off
   - an expression appears at least once in a 2-minute chat on each engine
   - after 5 minutes idle it goes to sleep and the motors turn off
   - `BODY_ENABLED=false` restores voice-only behaviour

## Open questions resolved by the spike

- The DoA angle convention, and its mapping to body yaw or head yaw.
- Whether tracking at weight 0.6 combined with wobbling looks natural or fights itself.
- Whether listening-time stillness is necessary, or whether gentle tracking while the person speaks is acceptable for recognition.
