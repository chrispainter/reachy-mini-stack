import asyncio
import base64
import json

import numpy as np
import pytest
import websockets

from reachy_voice.config import load_settings
from reachy_voice.engines import make_engine
from reachy_voice.engines.base import EngineCallbacks
from reachy_voice.engines.grok import GrokLiveEngine


class FakeWS:
    def __init__(self, events):
        self.sent, self.closed = [], False
        self._q = asyncio.Queue()
        for event in events:
            self._q.put_nowait(json.dumps(event))

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def push(self, event):
        self._q.put_nowait(None if event is None else json.dumps(event))

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
    got = {"audio": [], "user": [], "robot": [], "interrupted": [], "delegations": [],
           "body": [], "usage": [], "errors": []}
    cb = EngineCallbacks(
        on_audio=lambda samples, now: got["audio"].append(samples),
        on_user_text=got["user"].append,
        on_robot_text=got["robot"].append,
        on_interrupted=got["interrupted"].append,
        on_delegation=got["delegations"].append,
        on_usage=got["usage"].append,
        on_error=got["errors"].append,
        on_body_tool=lambda name, args: got["body"].append((name, args)),
    )
    return got, cb


def types_of(ws):
    return [message["type"] for message in ws.sent]


async def until(predicate, timeout=1.0):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


def test_start_configures_session_and_waits_for_updated():
    ws = FakeWS([{"type": "session.created"}, {"type": "session.updated"}])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await engine.close()
    asyncio.run(go())

    update = ws.sent[0]
    assert update["type"] == "session.update"
    session = update["session"]
    assert session["voice"] == "eve"
    assert session["reasoning"] == {"effort": "none"}
    assert session["turn_detection"] == {"type": "server_vad"}
    assert "You are Reachy" in session["instructions"]
    audio = session["audio"]
    assert audio["input"]["format"] == {"type": "audio/pcm", "rate": 16000}
    assert audio["output"]["format"] == {"type": "audio/pcm", "rate": 16000}
    assert audio["input"]["transcription"]["model"] == "grok-transcribe"
    assert [tool["name"] for tool in session["tools"]] == ["ask_home_agent", "express", "look"]
    assert "response.create" not in types_of(ws)
    assert ws.closed and not got["errors"]


def test_body_tools_can_be_left_off():
    ws = FakeWS([{"type": "session.updated"}])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws), body_tools=False)

    async def go():
        await engine.start(recorder()[1])
        await engine.close()
    asyncio.run(go())

    assert [tool["name"] for tool in ws.sent[0]["session"]["tools"]] == ["ask_home_agent"]
    assert "expressive body" not in ws.sent[0]["session"]["instructions"]


def test_start_times_out_if_session_never_updates():
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(FakeWS([])))
    with pytest.raises(RuntimeError, match="did not start"):
        asyncio.run(engine.start(recorder()[1], start_timeout_s=0.1))


def test_audio_transcripts_barge_in_and_usage():
    pcm = np.full(1600, 4000).astype("<i2").tobytes()
    ws = FakeWS([
        {"type": "session.updated"},
        {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "response.audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "conversation.item.input_audio_transcription.updated", "transcript": "What's"},
        {"type": "conversation.item.input_audio_transcription.updated", "transcript": "What's on the list"},
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "What's on the list"},
        {"type": "conversation.item.input_audio_transcription.updated", "transcript": "What's on their list"},
        {"type": "response.output_audio_transcript.delta", "delta": "Checking."},
        {"type": "response.audio_transcript.delta", "delta": " One moment."},
        {"type": "input_audio_buffer.speech_started"},
        {"type": "response.done", "response": {"usage": {"total_tokens": 12}}},
        {"type": "error", "error": {"message": "bad"}},
    ])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await until(lambda: got["errors"])
        await engine.send_audio(np.zeros((1024, 2), np.float32))
        await engine.close()
    asyncio.run(go())

    assert len(got["audio"]) == 2 and got["audio"][0].dtype == np.float32 and len(got["audio"][0]) == 1600
    assert got["user"] == ["What's", " on the list", "What's on their list"]
    assert got["robot"] == ["Checking.", " One moment."]
    assert got["interrupted"] and got["usage"] == [{"total_tokens": 12}]
    assert "bad" in got["errors"][0]
    append = [message for message in ws.sent if message["type"] == "input_audio_buffer.append"][0]
    assert len(base64.b64decode(append["audio"])) == 2048
    assert "response.create" not in types_of(ws)


def test_function_call_is_delivered_back_with_one_continue():
    ws = FakeWS([
        {"type": "session.updated"},
        {"type": "response.created"},
        {"type": "response.function_call_arguments.done", "name": "ask_home_agent", "call_id": "item_1",
         "arguments": json.dumps({"request": "What's on the grocery list", "lane": "quick"})},
        {"type": "response.done"},
    ])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await until(lambda: bool(got["delegations"]))
        # The server has finished the turn. Continue must wait for the tool result.
        await asyncio.sleep(0.05)
        assert "response.create" not in types_of(ws)
        await engine.deliver("item_1", "Milk and eggs.")
        await until(lambda: "response.create" in types_of(ws))
        await engine.close()
    asyncio.run(go())

    delegation = got["delegations"][0]
    assert (delegation.call_id, delegation.request, delegation.lane) == (
        "item_1", "What's on the grocery list", "quick")
    output = [message for message in ws.sent if message["type"] == "conversation.item.create"][0]
    assert output["item"] == {
        "type": "function_call_output", "call_id": "item_1", "output": json.dumps({"result": "Milk and eggs."}),
    }
    assert types_of(ws).count("response.create") == 1


def test_body_tool_is_acked_without_continuing_before_the_response_finishes():
    ws = FakeWS([
        {"type": "session.updated"},
        {"type": "response.created"},
        {"type": "response.function_call_arguments.done", "name": "express", "call_id": "body_1",
         "arguments": json.dumps({"emotion": "happy"})},
        {"type": "response.function_call_arguments.done", "name": "ask_home_agent", "call_id": "item_2",
         "arguments": json.dumps({"request": "Plan a weekend trip"})},
        {"type": "response.done"},
    ])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await until(lambda: got["delegations"] and any(
            message["type"] == "conversation.item.create" for message in ws.sent))
        await asyncio.sleep(0.05)
        assert "response.create" not in types_of(ws)
        await engine.deliver("item_2", "Saturday looks clear.")
        await until(lambda: "response.create" in types_of(ws))
        await engine.close()
    asyncio.run(go())

    assert got["body"] == [("express", {"emotion": "happy"})]
    outputs = [message["item"] for message in ws.sent if message["type"] == "conversation.item.create"]
    assert {"type": "function_call_output", "call_id": "body_1", "output": json.dumps({"ok": True})} in outputs
    assert types_of(ws).count("response.create") == 1
    assert got["delegations"][0].lane == "task"


def test_server_hangup_ends_wait_closed():
    ws = FakeWS([{"type": "session.updated"}])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))

    async def go():
        await engine.start(recorder()[1])
        ws.push(None)
        await asyncio.wait_for(engine.wait_closed(), 1)
        await asyncio.wait_for(engine.close(), 1)
    asyncio.run(go())
    assert ws.closed


def test_make_engine_builds_grok_from_settings():
    on = load_settings({"XAI_API_KEY": "x", "VOICE_ENGINE": "grok"})
    off = load_settings({"XAI_API_KEY": "x", "VOICE_ENGINE": "grok", "BODY_ENABLED": "false"})
    assert make_engine("grok", on).name == "grok"
    assert [tool["name"] for tool in make_engine("grok", on).session_update()["session"]["tools"]] == [
        "ask_home_agent", "express", "look"]
    assert [tool["name"] for tool in make_engine("grok", off).session_update()["session"]["tools"]] == [
        "ask_home_agent"]


def test_default_connect_uses_xai_realtime_url(monkeypatch):
    seen = {}

    async def fake_connect(url, additional_headers=None, max_size=None):
        seen["url"] = url
        seen["headers"] = additional_headers
        seen["max_size"] = max_size
        raise ConnectionError("stop")

    monkeypatch.setattr(websockets, "connect", fake_connect)
    engine = GrokLiveEngine("grok-voice-latest", "eve", api_key="secret")

    async def go():
        with pytest.raises(ConnectionError):
            await engine.start(recorder()[1])
        await engine.wait_closed()
    asyncio.run(go())
    assert seen["url"] == "wss://api.x.ai/v1/realtime?model=grok-voice-latest"
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["max_size"] is None


def test_close_never_raises_when_ws_close_fails():
    class BadWS(FakeWS):
        async def close(self):
            raise RuntimeError("boom")

    ws = BadWS([{"type": "session.updated"}])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await engine.close()
    asyncio.run(go())
    assert any("close failed" in error for error in got["errors"])


def test_bad_event_is_reported_and_receive_loop_continues():
    ws = FakeWS([
        {"type": "session.updated"},
        {"type": "response.output_audio.delta"},
        {"type": "response.output_audio_transcript.delta", "delta": "hello"},
    ])
    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect_to(ws))
    got, cb = recorder()

    async def go():
        await engine.start(cb)
        await until(lambda: got["robot"])
        await engine.close()
    asyncio.run(go())
    assert any("bad event" in error for error in got["errors"])
    assert got["robot"] == ["hello"]


def test_connect_failure_propagates_and_wait_closed_returns():
    async def connect():
        raise ConnectionError("nope")

    engine = GrokLiveEngine("grok-voice-latest", "eve", connect=connect)

    async def go():
        with pytest.raises(ConnectionError):
            await engine.start(recorder()[1])
        await engine.close()
        await asyncio.wait_for(engine.wait_closed(), 0.1)
    asyncio.run(go())
