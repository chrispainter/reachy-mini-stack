"""OpenAI gpt-live-1: full-duplex, client delegation. The model handles being talked over,
so there is no local barge-in (spike lesson, voice/spike/RESULTS.md)."""

import asyncio
import base64
import json
import time

import numpy as np
import websockets

from reachy_voice.audio import mic_to_pcm16, pcm16_to_float
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.persona import PERSONA
from reachy_voice.policy import choose_lane
from reachy_voice.segment import TurnSegmenter

URL = "wss://api.openai.com/v1/live/sessions"


class OpenAILiveEngine:
    name = "openai"

    def __init__(self, model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None) -> None:
        self._model, self._voice, self._persona = model, voice, persona
        self._connect = connect or (
            lambda: websockets.connect(URL, additional_headers={"Authorization": f"Bearer {api_key}"}, max_size=None)
        )
        self._segmenter = TurnSegmenter()
        self._ws = self._rx = None
        self._cb: EngineCallbacks | None = None
        self._started = asyncio.Event()
        self._ended = asyncio.Event()
        self.close_info: dict | None = None

    async def start(self, cb: EngineCallbacks, start_timeout_s: float = 10.0) -> None:
        self._cb, self._started, self._ended = cb, asyncio.Event(), asyncio.Event()
        try:
            self._ws = await self._connect()
        except BaseException:
            self._ended.set()
            raise
        try:
            await self._ws.send(json.dumps({
                "type": "session.start",
                "event_id": "start",
                "session": {
                    "model": self._model,
                    "instructions": self._persona,
                    "audio": {"format": {"type": "audio/pcm", "rate": 16000}, "output": {"voice": self._voice}},
                    "delegation": {"type": "client"},
                },
            }))
            self._rx = asyncio.create_task(self._receive())
            try:
                await asyncio.wait_for(self._started.wait(), timeout=start_timeout_s)
            except asyncio.TimeoutError:
                raise RuntimeError("gpt-live-1 session did not start") from None
        except BaseException:
            await self._shutdown()
            raise

    async def send_audio(self, frame: np.ndarray) -> None:
        await self._ws.send(json.dumps({"type": "session.input_audio.append",
                                        "audio": base64.b64encode(mic_to_pcm16(frame)).decode()}))

    async def deliver(self, call_id: str, text: str) -> None:
        await self._ws.send(json.dumps({"type": "session.commentary.append", "event_id": f"result-{call_id}",
                                        "delegation_id": call_id, "content": text}))

    async def _receive(self) -> None:
        cb = self._cb
        try:
            async for raw in self._ws:
                try:
                    if self._handle(json.loads(raw), time.monotonic()):
                        return
                except Exception as exc:  # noqa: BLE001 - one bad event must not kill the loop
                    cb.on_error(f"gpt-live-1 bad event: {exc!r}")
        except websockets.ConnectionClosed as exc:
            cb.on_error(f"gpt-live-1 connection closed: {exc!r}")
        except Exception as exc:  # noqa: BLE001
            cb.on_error(f"gpt-live-1 receive failed: {exc!r}")
        finally:
            self._ended.set()

    def _handle(self, event: dict, now: float) -> bool:
        """Dispatch one event; return True when the session is closed."""
        cb = self._cb
        kind = event.get("type")
        if kind == "session.started":
            self._started.set()
        elif kind == "session.output_audio.delta":
            samples = pcm16_to_float(base64.b64decode(event["delta"]), 16000, 16000)
            if len(samples):
                cb.on_audio(samples, now)
        elif kind == "session.input_transcript.delta":
            self._segmenter.on_user_text(event.get("delta", ""))
            cb.on_user_text(event.get("delta", ""))
        elif kind == "session.output_transcript.delta":
            self._segmenter.on_robot_text(event.get("delta", ""))
            cb.on_robot_text(event.get("delta", ""))
        elif kind == "session.delegation.created":
            request = self._segmenter.request()
            cb.on_delegation(Delegation(call_id=event["delegation"]["id"], request=request, lane=choose_lane(request)))
        elif kind == "session.usage.updated":
            cb.on_usage(event.get("usage") or {})
        elif kind == "error":
            cb.on_error(json.dumps(event)[:500])
        elif kind == "session.closed":
            self.close_info = {"reason": event.get("reason"), "usage": event.get("usage")}
            return True
        return False

    async def close(self, close_timeout_s: float = 5.0) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "session.close"}))
            await asyncio.wait_for(self._ended.wait(), timeout=close_timeout_s)
        except (websockets.ConnectionClosed, asyncio.TimeoutError):
            pass
        except Exception as exc:  # noqa: BLE001 - close() must not raise
            self._report_close_failure(exc)
        finally:
            await self._shutdown()

    def _report_close_failure(self, exc: Exception) -> None:
        if self._cb is not None:
            self._cb.on_error(f"gpt-live-1 close failed: {exc!r}")

    async def _shutdown(self) -> None:
        ws, self._ws = self._ws, None
        try:
            if ws is not None:
                await ws.close()
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            self._report_close_failure(exc)
        finally:
            if self._rx is not None:
                self._rx.cancel()
                await asyncio.gather(self._rx, return_exceptions=True)

    async def wait_closed(self) -> None:
        await self._ended.wait()
