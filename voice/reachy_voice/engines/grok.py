"""xAI Grok speech-to-speech. The socket speaks the OpenAI Realtime protocol
(wss://api.x.ai/v1/realtime), not the gpt-live-1 session events.

Server VAD owns turn-taking. Tool calls come back as
response.function_call_arguments.done; we answer with function_call_output and
one response.create after that response has finished and every call is filled.
reasoning.effort is "none" so a spoken reply stays in the same latency band as
the other engines.
"""

import asyncio
import base64
import json
import time
from urllib.parse import quote

import numpy as np
import websockets

from reachy_voice.audio import mic_to_pcm16, pcm16_to_float
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.persona import BODY_PERSONA_SUFFIX, BODY_TOOLS, PERSONA, TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMS
from reachy_voice.policy import choose_lane

RATE = 16000
BODY_TOOL_NAMES = {tool["name"] for tool in BODY_TOOLS}


def realtime_url(model: str) -> str:
    return f"wss://api.x.ai/v1/realtime?model={quote(model, safe='')}"


def _usage(event: dict) -> dict | None:
    response = event.get("response")
    if isinstance(response, dict) and isinstance(response.get("usage"), dict):
        return response["usage"]
    usage = event.get("usage")
    return usage if isinstance(usage, dict) else None


class GrokLiveEngine:
    name = "grok"

    def __init__(self, model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None,
                 body_tools: bool = True) -> None:
        self._model, self._voice = model, voice
        self._persona = persona + (BODY_PERSONA_SUFFIX if body_tools else "")
        self._body_tools = body_tools
        self._connect = connect or (lambda: _open_socket(model, api_key))
        self._ws = self._rx = None
        self._cb: EngineCallbacks | None = None
        self._started = asyncio.Event()
        self._ended = asyncio.Event()
        self._closing = False
        self._lock = asyncio.Lock()
        self._user_transcript = ""
        self._open_calls: set[str] = set()
        self._need_continue = False
        self._model_responding = False

    def session_update(self) -> dict:
        tools = [{
            "type": "function",
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "parameters": TOOL_PARAMS,
        }]
        if self._body_tools:
            tools.extend(
                {"type": "function", "name": tool["name"], "description": tool["description"],
                 "parameters": tool["parameters"]}
                for tool in BODY_TOOLS
            )
        return {
            "type": "session.update",
            "session": {
                "voice": self._voice,
                "instructions": self._persona,
                "reasoning": {"effort": "none"},
                "turn_detection": {"type": "server_vad"},
                "tools": tools,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": RATE},
                        "transcription": {
                            "model": "grok-transcribe",
                            "language_hint": "en",
                            "keyterms": ["Reachy", "Jarvis"],
                        },
                    },
                    "output": {"format": {"type": "audio/pcm", "rate": RATE}},
                },
            },
        }

    async def start(self, cb: EngineCallbacks, start_timeout_s: float = 10.0) -> None:
        self._cb, self._started, self._ended = cb, asyncio.Event(), asyncio.Event()
        self._closing = False
        try:
            self._ws = await self._connect()
        except BaseException:
            self._ended.set()
            raise
        try:
            await self._ws.send(json.dumps(self.session_update()))
            self._rx = asyncio.create_task(self._receive())
            try:
                await asyncio.wait_for(self._started.wait(), timeout=start_timeout_s)
            except asyncio.TimeoutError:
                raise RuntimeError("grok voice session did not start") from None
        except BaseException:
            await self._shutdown()
            raise

    async def send_audio(self, frame: np.ndarray) -> None:
        payload = {"type": "input_audio_buffer.append",
                   "audio": base64.b64encode(mic_to_pcm16(frame)).decode()}
        async with self._lock:
            await self._send(payload)

    async def deliver(self, call_id: str, text: str) -> None:
        await self._send_function_output(call_id, json.dumps({"result": text}))

    async def _send_function_output(self, call_id: str, output: str) -> None:
        async with self._lock:
            await self._send({
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id, "output": output},
            })
            self._open_calls.discard(call_id)
            await self._continue_if_ready()

    async def _continue_if_ready(self) -> None:
        """Lock is held. One continue, only once every call in the finished response has an output."""
        if self._need_continue and not self._open_calls and not self._model_responding:
            self._need_continue = False
            await self._send({"type": "response.create"})

    async def _send(self, payload: dict) -> None:
        await self._ws.send(json.dumps(payload))

    async def _receive(self) -> None:
        cb = self._cb
        try:
            async for raw in self._ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    await self._handle(json.loads(raw), time.monotonic())
                except Exception as exc:  # noqa: BLE001 - one bad event must not kill the loop
                    cb.on_error(f"grok bad event: {exc!r}")
        except websockets.ConnectionClosed as exc:
            if not self._closing:
                cb.on_error(f"grok connection closed: {exc!r}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._closing:
                cb.on_error(f"grok receive failed: {exc!r}")
        finally:
            self._ended.set()

    async def _handle(self, event: dict, now: float) -> None:
        cb = self._cb
        kind = event.get("type")
        if kind == "session.updated":
            self._started.set()
        elif kind in ("response.output_audio.delta", "response.audio.delta"):
            samples = pcm16_to_float(base64.b64decode(event["delta"]), RATE, RATE)
            if len(samples):
                cb.on_audio(samples, now)
        elif kind in ("conversation.item.input_audio_transcription.updated",
                      "conversation.item.input_audio_transcription.completed"):
            self._emit_user_text(str(event.get("transcript") or ""))
        elif kind in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
            delta = event.get("delta") or ""
            if delta:
                cb.on_robot_text(delta)
        elif kind == "input_audio_buffer.speech_started":
            cb.on_interrupted(now)
        elif kind == "response.created":
            async with self._lock:
                self._model_responding = True
        elif kind == "response.done":
            usage = _usage(event)
            if usage:
                cb.on_usage(usage)
            async with self._lock:
                self._model_responding = False
                await self._continue_if_ready()
        elif kind == "response.function_call_arguments.done":
            await self._on_function_call(event)
        elif kind == "error":
            cb.on_error(json.dumps(event)[:500])

    def _emit_user_text(self, transcript: str) -> None:
        """updated/completed carry the cumulative transcript, including corrections."""
        if not transcript:
            return
        previous = self._user_transcript
        delta = transcript[len(previous):] if transcript.startswith(previous) else transcript
        self._user_transcript = transcript
        if delta:
            self._cb.on_user_text(delta)

    async def _on_function_call(self, event: dict) -> None:
        name = event.get("name") or ""
        call_id = event.get("call_id") or ""
        try:
            args = json.loads(event.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        async with self._lock:
            self._model_responding = True
            self._need_continue = True
            if call_id:
                self._open_calls.add(call_id)
        if name in BODY_TOOL_NAMES and self._body_tools:
            self._cb.on_body_tool(name, args)
            await self._send_function_output(call_id, json.dumps({"ok": True}))
            return
        request = str(args.get("request", "")).strip()
        lane = args.get("lane") if args.get("lane") in ("quick", "task") else choose_lane(request)
        self._cb.on_delegation(Delegation(call_id=call_id, request=request, lane=lane))

    async def close(self) -> None:
        self._closing = True
        if self._ws is None and self._rx is None:
            return
        try:
            await self._shutdown()
        except Exception as exc:  # noqa: BLE001 - close() must not raise
            self._report_close_failure(exc)

    def _report_close_failure(self, exc: Exception) -> None:
        if self._cb is not None:
            self._cb.on_error(f"grok close failed: {exc!r}")

    async def _shutdown(self) -> None:
        ws, self._ws = self._ws, None
        try:
            if ws is not None:
                await ws.close()
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            self._report_close_failure(exc)
        finally:
            if self._rx is not None:
                rx, self._rx = self._rx, None
                rx.cancel()
                await asyncio.gather(rx, return_exceptions=True)
            self._ended.set()

    async def wait_closed(self) -> None:
        await self._ended.wait()


async def _open_socket(model: str, api_key: str):
    return await websockets.connect(
        realtime_url(model),
        additional_headers={"Authorization": f"Bearer {api_key}"},
        max_size=None,
    )
