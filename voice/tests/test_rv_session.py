import asyncio
import json

import numpy as np

from reachy_voice.engines.base import Delegation
from reachy_voice.hermes import HermesError
from reachy_voice.log import JsonlLog
from reachy_voice.persona import FALLBACK_REPLY
from reachy_voice.policy import SessionPolicy
from reachy_voice.session import VoiceSession

VOICED = np.full(1600, 0.2, np.float32)


class FakeEngine:
    name = "fake"

    def __init__(self, on_start=None):
        self.sent, self.delivered, self.closed = [], [], False
        self._done = asyncio.Event()
        self._on_start = on_start

    async def start(self, cb):
        self.cb = cb
        if self._on_start:
            asyncio.get_running_loop().call_soon(self._on_start, self)

    async def send_audio(self, frame):
        self.sent.append(frame)

    async def deliver(self, call_id, text):
        self.delivered.append((call_id, text))

    async def close(self):
        self.closed = True
        self._done.set()

    async def wait_closed(self):
        await self._done.wait()


class FakeAudio:
    def __init__(self, level=0.0, count=3, forever=False):
        self.level, self.count, self.forever = level, count, forever
        self.played, self.cleared = [], 0

    async def frames(self):
        n = 0
        while self.forever or n < self.count:
            n += 1
            yield np.full((1024, 2), self.level, np.float32)
            await asyncio.sleep(0.005)
        await asyncio.Event().wait()   # mic stays open, silent

    def play(self, samples):
        self.played.append(samples)

    def clear(self):
        self.cleared += 1


class FakeHermes:
    def __init__(self, answer="Milk and eggs.", delay=0.0, fail=False):
        self.answer, self.delay, self.fail, self.calls = answer, delay, fail, []

    async def ask(self, request, asked_by, lane, session_id):
        self.calls.append((request, lane, session_id))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise HermesError("ConnectError: refused")
        return self.answer


def make(engine, audio, hermes, tmp_path, idle=0.1, pending=5.0, max_s=5.0):
    log = JsonlLog(str(tmp_path / "v.jsonl"))
    s = VoiceSession(engine, audio, hermes, SessionPolicy(idle, pending, max_s), 0.015, log, "sess-1", tick_s=0.01)
    return s, tmp_path / "v.jsonl"


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def delegate(engine):
    engine.cb.on_delegation(Delegation("c1", "what's on the grocery list", "quick"))


def test_idle_session_closes_and_closes_engine(tmp_path):
    engine = FakeEngine()
    s, path = make(engine, FakeAudio(), FakeHermes(), tmp_path)
    assert asyncio.run(s.run()) == "idle"
    assert engine.closed and len(engine.sent) == 3
    assert [e["event"] for e in events(path)][0] == "session_open"


def test_pending_handoff_holds_session_then_delivers(tmp_path):
    engine, hermes = FakeEngine(on_start=delegate), FakeHermes(delay=0.3)
    s, path = make(engine, FakeAudio(), hermes, tmp_path, idle=0.05)
    loop_start = asyncio.run(_timed(s))
    assert loop_start[0] == "idle" and loop_start[1] >= 0.3
    assert hermes.calls == [("what's on the grocery list", "quick", "sess-1")]
    assert engine.delivered == [("c1", "Milk and eggs.")]
    result = [e for e in events(path) if e["event"] == "delegation_result"][0]
    assert result["ok"] is True


def test_hermes_failure_delivers_spoken_fallback(tmp_path):
    engine = FakeEngine(on_start=delegate)
    s, path = make(engine, FakeAudio(), FakeHermes(fail=True), tmp_path)
    asyncio.run(s.run())
    assert engine.delivered == [("c1", FALLBACK_REPLY)]
    assert any(e["event"] == "delegation_error" for e in events(path))


def test_constant_background_speech_is_capped_by_max_duration(tmp_path):
    s, _ = make(FakeEngine(), FakeAudio(level=0.5, forever=True), FakeHermes(), tmp_path, idle=0.1, max_s=0.3)
    assert asyncio.run(s.run()) == "max_duration"


def test_engine_dropping_ends_session(tmp_path):
    engine = FakeEngine(on_start=lambda e: e._done.set())
    s, _ = make(engine, FakeAudio(), FakeHermes(), tmp_path, idle=5.0)
    assert asyncio.run(s.run()) == "engine_closed"


def test_voiced_audio_is_played_and_interrupt_clears(tmp_path):
    def speak(engine):
        engine.cb.on_audio(VOICED, 0.0)
        engine.cb.on_interrupted(0.0)
    engine, audio = FakeEngine(on_start=speak), FakeAudio(level=0.5, count=1)
    s, path = make(engine, audio, FakeHermes(), tmp_path)
    asyncio.run(s.run())
    assert len(audio.played) == 1 and audio.cleared == 1


async def _timed(session):
    loop = asyncio.get_running_loop()
    start = loop.time()
    reason = await session.run()
    return reason, loop.time() - start
