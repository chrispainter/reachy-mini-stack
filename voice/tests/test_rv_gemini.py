import asyncio
from types import SimpleNamespace as NS

import numpy as np
from google.genai import types

from reachy_voice.engines.base import EngineCallbacks
from reachy_voice.engines.gemini import GeminiLiveEngine


class FakeSession:
    def __init__(self, turns):
        self.turns = list(turns)
        self.audio = []
        self.tool_responses = []

    async def send_realtime_input(self, audio):
        self.audio.append(audio)

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        if self.turns:
            for msg in self.turns.pop(0):
                yield msg


class FakeConnect:
    def __init__(self, session):
        self.session, self.kwargs, self.exited = session, None, False

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        self.exited = True


def msg(data=None, server_content=None, tool_call=None, usage=None):
    return NS(data=data, server_content=server_content, tool_call=tool_call, usage_metadata=usage)


def recorder():
    got = {"audio": [], "user": [], "robot": [], "interrupted": [], "delegations": [], "usage": [], "errors": []}
    cb = EngineCallbacks(
        on_audio=lambda s, now: got["audio"].append(s),
        on_user_text=got["user"].append,
        on_robot_text=got["robot"].append,
        on_interrupted=got["interrupted"].append,
        on_delegation=got["delegations"].append,
        on_usage=got["usage"].append,
        on_error=got["errors"].append,
    )
    return got, cb


def run(engine, cb):
    async def go():
        await engine.start(cb)
        await asyncio.wait_for(engine.wait_closed(), 2)
        await engine.close()
    asyncio.run(go())


def test_config_pins_english_voice_and_non_blocking_tool():
    cfg = GeminiLiveEngine("gemini-3.8-live", "Kore", connect=FakeConnect(FakeSession([]))).config()
    assert cfg.speech_config.language_code == "en-US"
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    decl = cfg.tools[0].function_declarations[0]
    assert decl.name == "ask_home_agent" and decl.behavior == types.Behavior.NON_BLOCKING


def test_tool_call_becomes_delegation_and_result_is_delivered_when_idle():
    fc = NS(id="c1", name="ask_home_agent", args={"request": "what's on the grocery list", "lane": "bogus"})
    session = FakeSession([[msg(tool_call=NS(function_calls=[fc]))]])
    engine = GeminiLiveEngine("m", "Kore", connect=FakeConnect(session))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await asyncio.wait_for(engine.wait_closed(), 2)
        await engine.deliver("c1", "Milk and eggs.")
        await engine.close()
    asyncio.run(go())

    d = got["delegations"][0]
    assert (d.call_id, d.request, d.lane) == ("c1", "what's on the grocery list", "quick")  # bogus lane -> choose_lane
    r = session.tool_responses[0]
    assert r.id == "c1" and r.name == "ask_home_agent" and r.response == {"result": "Milk and eggs."}
    assert r.scheduling == types.FunctionResponseScheduling.WHEN_IDLE


def test_audio_is_resampled_to_16k_and_events_forwarded():
    pcm = (np.sin(np.arange(9600) / 10) * 8000).astype("<i2").tobytes()   # 0.4 s at 24 kHz
    content = NS(interrupted=True, input_transcription=NS(text="hi"), output_transcription=NS(text="hello"))
    session = FakeSession([[msg(data=pcm), msg(data=pcm), msg(server_content=content, usage=NS(total_token_count=42))]])
    got, cb = recorder()
    run(GeminiLiveEngine("m", "Kore", connect=FakeConnect(session)), cb)
    assert got["audio"] and all(a.dtype == np.float32 and len(a) > 0 for a in got["audio"])
    assert 12000 <= sum(len(a) for a in got["audio"]) <= 12800      # ~0.8 s at 16 kHz, minus resampler latency
    assert got["user"] == ["hi"] and got["robot"] == ["hello"] and len(got["interrupted"]) == 1
    assert got["usage"] == [{"total_tokens": 42}]


def test_session_end_finishes_receive_loop_and_close_exits_context():
    connect = FakeConnect(FakeSession([]))
    got, cb = recorder()
    run(GeminiLiveEngine("m", "Kore", connect=connect), cb)
    assert connect.exited and got["errors"] == []


def test_close_survives_failing_aexit_and_still_stops_receive_task():
    connect = FakeConnect(FakeSession([]))

    async def bad_exit(*exc):
        raise RuntimeError("boom")

    connect.__aexit__ = bad_exit  # instance attr is ignored by `async with`, but engine calls it directly
    engine = GeminiLiveEngine("m", "Kore", connect=connect)
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await engine.close()  # must not raise
        assert engine._rx.done()

    asyncio.run(go())
    assert any("close failed" in e for e in got["errors"])


def test_close_after_failed_start_is_a_noop():
    connect = FakeConnect(FakeSession([]))

    async def bad_enter():
        raise ConnectionError("no route")

    connect.__aenter__ = bad_enter
    engine = GeminiLiveEngine("m", "Kore", connect=connect)
    got, cb = recorder()

    async def go():
        try:
            await engine.start(cb)
        except ConnectionError:
            pass
        else:
            raise AssertionError("start should have raised")
        await engine.close()

    asyncio.run(go())
    assert connect.exited is False
