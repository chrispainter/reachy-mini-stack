import asyncio
import base64
import json

import numpy as np
import pytest

from reachy_voice.config import load_settings
from reachy_voice.engines import make_engine
from reachy_voice.engines.base import EngineCallbacks
from reachy_voice.engines.openai_live import OpenAILiveEngine


class FakeWS:
    def __init__(self, events, ack_close=True):
        self.sent, self.closed, self._ack = [], False, ack_close
        self._q = asyncio.Queue()
        for e in events:
            self._q.put_nowait(json.dumps(e))

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg["type"] == "session.close" and self._ack:
            self._q.put_nowait(json.dumps({"type": "session.closed", "reason": "close_requested", "usage": {"seconds": 3}}))

    def push(self, event):
        self._q.put_nowait(json.dumps(event))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self):
        self.closed = True
        self._q.put_nowait(None)


def connect_to(ws):
    async def connect():
        return ws
    return connect


def recorder():
    got = {"audio": [], "user": [], "robot": [], "delegations": [], "usage": [], "errors": []}
    cb = EngineCallbacks(
        on_audio=lambda s, now: got["audio"].append(s),
        on_user_text=got["user"].append,
        on_robot_text=got["robot"].append,
        on_interrupted=lambda now: None,
        on_delegation=got["delegations"].append,
        on_usage=got["usage"].append,
        on_error=got["errors"].append,
    )
    return got, cb


def test_start_sends_session_start_and_waits_for_started():
    ws = FakeWS([{"type": "session.started", "session": {"id": "s"}}])
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await engine.close()
    asyncio.run(go())

    start = ws.sent[0]
    assert start["type"] == "session.start"
    s = start["session"]
    assert s["model"] == "gpt-live-1" and s["delegation"] == {"type": "client"}
    assert s["audio"] == {"format": {"type": "audio/pcm", "rate": 16000}, "output": {"voice": "marin"}}
    assert ws.sent[-1] == {"type": "session.close"} and ws.closed
    assert engine.close_info == {"reason": "close_requested", "usage": {"seconds": 3}}


def test_start_times_out_if_session_never_starts():
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(FakeWS([])))
    with pytest.raises(RuntimeError, match="did not start"):
        asyncio.run(engine.start(recorder()[1], start_timeout_s=0.1))


def test_events_audio_transcripts_delegation_and_delivery():
    pcm = (np.full(1600, 4000)).astype("<i2").tobytes()
    ws = FakeWS([
        {"type": "session.started"},
        {"type": "session.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "session.input_transcript.delta", "delta": " What's on the grocery list"},
        {"type": "session.output_transcript.delta", "delta": " Checking now."},
        {"type": "session.delegation.created", "delegation": {"id": "item_1", "type": "delegation", "target": "client"}},
        {"type": "session.usage.updated", "usage": {"seconds": 2}},
        {"type": "error", "error": {"message": "bad"}},
    ])
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        while not got["errors"]:
            await asyncio.sleep(0.01)
        await engine.send_audio(np.zeros((1024, 2), np.float32))
        await engine.deliver("item_1", "Milk and eggs.")
        await engine.close()
    asyncio.run(go())

    assert len(got["audio"]) == 1 and got["audio"][0].dtype == np.float32 and len(got["audio"][0]) == 1600
    d = got["delegations"][0]
    assert (d.call_id, d.request, d.lane) == ("item_1", "What's on the grocery list", "quick")
    assert got["usage"] == [{"seconds": 2}] and "bad" in got["errors"][0]
    append = [m for m in ws.sent if m["type"] == "session.input_audio.append"][0]
    assert len(base64.b64decode(append["audio"])) == 2048
    commentary = [m for m in ws.sent if m["type"] == "session.commentary.append"][0]
    assert commentary["delegation_id"] == "item_1" and commentary["content"] == "Milk and eggs."


def test_server_closing_ends_wait_closed_and_close_tolerates_no_ack():
    ws = FakeWS([{"type": "session.started"}], ack_close=False)
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))

    async def go():
        await engine.start(recorder()[1])
        ws.push({"type": "session.closed", "reason": "expired"})
        await asyncio.wait_for(engine.wait_closed(), 1)
        await asyncio.wait_for(engine.close(close_timeout_s=0.1), 1)
    asyncio.run(go())
    assert ws.closed and engine.close_info["reason"] == "expired"


def test_make_engine_builds_each_engine():
    s = load_settings({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"})
    assert make_engine("openai", s).name == "openai"
    assert make_engine("gemini", s).name == "gemini"
    with pytest.raises(ValueError):
        make_engine("alexa", s)


def test_make_engine_propagates_body_enabled_to_gemini():
    on = load_settings({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"})
    off = load_settings({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o", "BODY_ENABLED": "false"})
    assert {d.name for d in make_engine("gemini", on).config().tools[0].function_declarations} >= {"express", "look"}
    assert {d.name for d in make_engine("gemini", off).config().tools[0].function_declarations} == {"ask_home_agent"}


def test_close_never_raises_when_ws_close_fails():
    class BadWS(FakeWS):
        async def close(self):
            raise RuntimeError("boom")

    ws = BadWS([{"type": "session.started"}])
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await engine.close()
    asyncio.run(go())
    assert any("close failed" in e for e in got["errors"])


def test_bad_event_is_reported_and_receive_loop_continues():
    ws = FakeWS([
        {"type": "session.started"},
        {"type": "session.output_audio.delta"},
        {"type": "session.input_transcript.delta", "delta": "hello"},
    ])
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        async def until_user():
            while not got["user"]:
                await asyncio.sleep(0.01)
        try:
            await asyncio.wait_for(until_user(), 1)
        finally:
            await engine.close()
    asyncio.run(go())
    assert any("bad event" in e for e in got["errors"])
    assert got["user"] == ["hello"]


def test_close_cancelled_during_wait_still_shuts_down():
    ws = FakeWS([{"type": "session.started"}], ack_close=False)
    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect_to(ws))

    async def go():
        await engine.start(recorder()[1])
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(engine.close(close_timeout_s=5), timeout=0.05)
    asyncio.run(go())
    assert ws.closed


def test_connect_failure_propagates_and_wait_closed_returns():
    async def connect():
        raise ConnectionError("nope")

    engine = OpenAILiveEngine("gpt-live-1", "marin", connect=connect)

    async def go():
        with pytest.raises(ConnectionError):
            await engine.start(recorder()[1])
        await engine.close()
        await asyncio.wait_for(engine.wait_closed(), 0.1)
    asyncio.run(go())
