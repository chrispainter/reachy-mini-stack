"""One wake-word conversation: robot audio <-> engine, with background Hermes hand-offs."""

import asyncio
import time

import numpy as np

from reachy_voice.activity import OutputActivity, UserSpeech
from reachy_voice.audio import rms
from reachy_voice.body import NullBody
from reachy_voice.body_policy import CUES, EMOTIONS, ExpressionGate
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.hermes import HermesError
from reachy_voice.log import JsonlLog
from reachy_voice.persona import FALLBACK_REPLY
from reachy_voice.policy import SessionPolicy

RATE = 16000
BODY_TEARDOWN_TIMEOUT_S = 15.0
MIC_STATS_WINDOW_S = 5.0
SPEAKING_HANGOVER_S = 0.3  # playback underruns between words must not flap the body's speaking state


class EngineStartError(Exception):
    """The engine failed to connect/start (as opposed to failing mid-session)."""


class VoiceSession:
    def __init__(self, engine, audio, hermes, policy: SessionPolicy, speech_threshold: float, log: JsonlLog,
                 session_id: str, clock=time.monotonic, tick_s: float = 0.25, *, body=None, gate=None,
                 picker=None) -> None:
        self._engine, self._audio, self._hermes = engine, audio, hermes
        self._policy, self._log, self._session_id = policy, log, session_id
        self._clock, self._tick_s = clock, tick_s
        self._out = OutputActivity()
        self._user = UserSpeech(threshold=speech_threshold)
        self._pending: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()
        self._last_delivery: float | None = None
        self._closing = False
        self._body = body or NullBody()
        self._gate = gate or ExpressionGate()
        self._picker = picker
        self._body_tasks: set[asyncio.Task] = set()
        self._was_speaking = False
        self._utterance_started: float | None = None
        self._utterance_text: list[str] = []
        self._mic_levels: list[float] = []
        self._mic_window_start: float | None = None

    async def run(self) -> str:
        opened = self._clock()
        try:
            await self._engine.start(self._callbacks())
        except Exception as exc:  # noqa: BLE001
            raise EngineStartError(repr(exc)) from exc
        self._log.write("session_open", engine=self._engine.name, session_id=self._session_id)
        self._spawn_body(self._body.listening(), "listening")  # perk the antennas even if already awake
        mic = asyncio.create_task(self._pump_mic())
        engine_done = asyncio.create_task(self._engine.wait_closed())
        try:
            while True:
                await asyncio.sleep(self._tick_s)
                if engine_done.done():
                    return "engine_closed"
                if mic.done():
                    if mic.exception() is not None:
                        self._log.write("mic_error", error=repr(mic.exception()))
                    return "mic_closed"
                now = self._clock()
                speaking = now < self._out.voiced_end + SPEAKING_HANGOVER_S
                if speaking != self._was_speaking:
                    self._was_speaking = speaking
                    if speaking:
                        self._utterance_started = now  # keep text already received: it can precede the audio
                        self._spawn_body(self._body.speaking(), "speaking")
                    else:
                        self._spawn_body(self._body.listening(), "listening")
                        text = "".join(self._utterance_text).strip()
                        self._utterance_started, self._utterance_text = None, []
                        if self._picker is not None and text:
                            self._spawn_body(self._pick_and_express(text), "pick")
                last = max(opened, self._user.last_voice or opened, self._out.voiced_end,
                           self._last_delivery or opened)
                pending_since = min(self._pending.values()) if self._pending else None
                reason = self._policy.should_close(now, opened, last, pending_since)
                if reason:
                    return reason
        finally:
            self._closing = True
            mic.cancel()
            engine_done.cancel()
            for task in list(self._tasks):
                task.cancel()
            try:
                await asyncio.gather(mic, engine_done, *self._tasks, return_exceptions=True)
            finally:
                try:
                    await self._engine.close()
                finally:
                    await self._finish_body_tasks()

    def _callbacks(self) -> EngineCallbacks:
        name = self._engine.name
        return EngineCallbacks(
            on_audio=self._on_audio,
            on_user_text=lambda text: self._log.write("user_text", engine=name, text=text),
            on_robot_text=self._on_robot_text,
            on_interrupted=self._on_interrupted,
            on_delegation=self._on_delegation,
            on_usage=lambda usage: self._log.write("usage", engine=name, usage=usage),
            on_body_tool=self._on_body_tool,
            on_error=lambda message: self._log.write("engine_error", engine=name, message=message),
        )

    def _spawn_body(self, coro, what: str) -> None:
        if self._closing:
            coro.close()
            self._log.write("body_error", action=what, error="session closing")
            return
        async def guarded():
            try:
                await coro
            except Exception as exc:  # noqa: BLE001 - the body never breaks the voice
                self._log.write("body_error", action=what, error=repr(exc))
        task = asyncio.create_task(guarded())
        self._body_tasks.add(task)
        task.add_done_callback(self._body_tasks.discard)

    async def _finish_body_tasks(self) -> None:
        """Let in-flight motion finish, but never let a stuck body hang teardown."""
        if not self._body_tasks:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*self._body_tasks, return_exceptions=True),
                                   timeout=BODY_TEARDOWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._log.write("body_error", action="teardown_timeout", error="body tasks still running")

    def _try_express(self, intent: str, source: str) -> None:
        if self._closing:
            self._log.write("expression_dropped", intent=intent, source=source, reason="closing")
            return
        if intent not in EMOTIONS:
            self._log.write("expression_dropped", intent=intent, source=source, reason="unknown")
            return
        if not self._gate.allow(self._clock(), self._user.last_voice, self._utterance_started):
            self._log.write("expression_dropped", intent=intent, source=source, reason="gate")
            return
        self._log.write("expression", intent=intent, source=source)
        self._spawn_body(self._body.express(intent), "express")

    async def _pick_and_express(self, text: str) -> None:
        intent = await self._picker.pick(text)
        if intent:
            self._try_express(intent, "picker")

    def _on_robot_text(self, text: str) -> None:
        try:
            self._log.write("robot_text", engine=self._engine.name, text=text)
            self._utterance_text.append(text)
        except Exception as exc:  # noqa: BLE001
            self._log.write("callback_error", where="on_robot_text", error=repr(exc))

    def _on_body_tool(self, name: str, args: dict) -> None:
        try:
            if self._closing:
                return
            if name == "express":
                self._try_express(str(args.get("emotion", "")), "model")
            elif name == "look":
                self._spawn_body(self._body.look(str(args.get("direction", "front"))), "look")
        except Exception as exc:  # noqa: BLE001
            self._log.write("callback_error", where="on_body_tool", error=repr(exc))

    async def _pump_mic(self) -> None:
        async for frame in self._audio.frames():
            now = self._clock()
            level = rms(frame)
            self._user.on_mic(level, now, self._out.is_speaking(now))
            self._record_mic_level(level, now)
            await self._engine.send_audio(frame)

    def _record_mic_level(self, level: float, now: float) -> None:
        """Diagnostic: one mic_level event per MIC_STATS_WINDOW_S of session clock."""
        if self._mic_window_start is None:
            self._mic_window_start = now
        self._mic_levels.append(level)
        if now - self._mic_window_start < MIC_STATS_WINDOW_S:
            return
        levels = np.asarray(self._mic_levels)
        last = self._user.last_voice
        self._log.write("mic_level", p50=round(float(np.percentile(levels, 50)), 4),
                        p90=round(float(np.percentile(levels, 90)), 4),
                        voiced_frac=round(float(np.mean(levels >= self._user.threshold)), 3),
                        sustained=last is not None and last >= self._mic_window_start)
        self._mic_levels, self._mic_window_start = [], now

    def _on_audio(self, samples: np.ndarray, now: float) -> None:
        if self._closing:
            return
        try:
            self._handle_audio(samples)
        except Exception as exc:  # noqa: BLE001 - never kill the engine's receive loop
            self._log.write("callback_error", where="on_audio", error=repr(exc))

    def _handle_audio(self, samples: np.ndarray) -> None:
        play, voiced_start = self._out.accept(samples, RATE, self._clock())
        if not play:
            return
        self._audio.play(samples)
        if voiced_start is not None:
            latency = self._user.on_voiced_output(voiced_start)
            if latency is not None:
                self._log.write("first_audio", engine=self._engine.name, latency_s=latency)

    def _on_interrupted(self, now: float) -> None:
        try:
            self._audio.clear()
            self._out.clear(self._clock())
            self._log.write("interrupted", engine=self._engine.name)
        except Exception as exc:  # noqa: BLE001
            self._log.write("callback_error", where="on_interrupted", error=repr(exc))

    def _on_delegation(self, d: Delegation) -> None:
        try:
            if self._closing:
                self._log.write("delegation_ignored", call_id=d.call_id, reason="session closing")
                return
            self._start_delegation(d)
        except Exception as exc:  # noqa: BLE001
            self._log.write("callback_error", where="on_delegation", error=repr(exc))

    def _start_delegation(self, d: Delegation) -> None:
        started = self._clock()
        self._pending[d.call_id] = started
        self._log.write("delegation", engine=self._engine.name, call_id=d.call_id, lane=d.lane, request=d.request)
        self._try_express(CUES["handoff_start"], "cue")
        task = asyncio.create_task(self._handle_delegation(d, started))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_delegation(self, d: Delegation, started: float) -> None:
        ok = True
        try:
            if not d.request or not d.request.strip():
                raise HermesError("empty request")
            text = await self._hermes.ask(d.request, "unknown", d.lane, self._session_id)
        except HermesError as exc:
            ok, text = False, FALLBACK_REPLY
            self._log.write("delegation_error", call_id=d.call_id, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - CancelledError is BaseException and still propagates
            ok, text = False, FALLBACK_REPLY
            self._log.write("delegation_error", call_id=d.call_id, error=repr(exc))
        self._try_express(CUES["handoff_ok" if ok else "handoff_failed"], "cue")
        try:
            await self._engine.deliver(d.call_id, text)
        except Exception as exc:  # noqa: BLE001 - a failed delivery must not leave the session pending
            ok = False
            self._log.write("delivery_error", call_id=d.call_id, error=repr(exc))
        finally:
            self._pending.pop(d.call_id, None)
            self._last_delivery = self._clock()
            self._log.write("delegation_result", call_id=d.call_id, lane=d.lane, ok=ok,
                            seconds=round(self._clock() - started, 2))
