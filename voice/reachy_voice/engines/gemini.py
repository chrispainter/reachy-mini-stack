"""Gemini 3.8 Live: native audio, non-blocking tool calls delivered when idle."""

import asyncio
import time

import numpy as np
from google import genai
from google.genai import types

from reachy_voice.audio import StreamResampler, mic_to_pcm16
from reachy_voice.engines.base import Delegation, EngineCallbacks
from reachy_voice.persona import BODY_PERSONA_SUFFIX, BODY_TOOLS, PERSONA, TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMS
from reachy_voice.policy import choose_lane

BODY_TOOL_NAMES = {t["name"] for t in BODY_TOOLS}


class GeminiLiveEngine:
    name = "gemini"

    def __init__(self, model: str, voice: str, api_key: str = "", persona: str = PERSONA, connect=None,
                 body_tools: bool = True) -> None:
        self._model, self._voice, self._persona = model, voice, persona
        self._body_tools = body_tools
        self._connect = connect or genai.Client(api_key=api_key).aio.live.connect
        self._resampler = StreamResampler(24000, 16000)
        self._calls: dict[str, str] = {}
        self._ack_tasks: set[asyncio.Task] = set()
        self._cm = self._session = self._rx = None
        self._cb: EngineCallbacks | None = None
        self._closing = False
        self._ended = asyncio.Event()

    def config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                language_code="en-US",
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)),
            ),
            system_instruction=self._persona + (BODY_PERSONA_SUFFIX if self._body_tools else ""),
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=TOOL_NAME,
                            description=TOOL_DESCRIPTION,
                            parameters_json_schema=TOOL_PARAMS,
                            behavior=types.Behavior.NON_BLOCKING,  # explicit; the default was never verified
                        ),
                        *(
                            types.FunctionDeclaration(
                                name=t["name"],
                                description=t["description"],
                                parameters_json_schema=t["parameters"],
                                behavior=types.Behavior.NON_BLOCKING,
                            )
                            for t in (BODY_TOOLS if self._body_tools else ())
                        ),
                    ]
                )
            ],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def start(self, cb: EngineCallbacks) -> None:
        self._cb, self._ended = cb, asyncio.Event()
        cm = self._connect(model=self._model, config=self.config())
        self._session = await cm.__aenter__()
        self._cm = cm  # only once entered, so close() after a failed start is a no-op
        self._rx = asyncio.create_task(self._receive())

    async def send_audio(self, frame: np.ndarray) -> None:
        await self._session.send_realtime_input(audio=types.Blob(data=mic_to_pcm16(frame), mime_type="audio/pcm;rate=16000"))

    async def deliver(self, call_id: str, text: str) -> None:
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=call_id,
                    name=self._calls.pop(call_id, TOOL_NAME),
                    response={"result": text},
                    scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
                )
            ]
        )

    async def _ack_body_tool(self, call_id: str, name: str) -> None:
        try:
            await self._session.send_tool_response(function_responses=[types.FunctionResponse(
                id=call_id, name=name, response={"ok": True}, scheduling=types.FunctionResponseScheduling.SILENT)])
        except Exception as exc:  # noqa: BLE001
            if self._cb:
                self._cb.on_error(f"gemini body tool ack failed: {exc!r}")

    async def _receive(self) -> None:
        try:
            while not self._closing:
                got_any = False
                async for msg in self._session.receive():  # ends after each completed turn
                    got_any = True
                    self._handle(msg, time.monotonic())
                if not got_any:
                    return  # the session ended server-side
        except Exception as exc:  # noqa: BLE001 - surface, then end the session
            if not self._closing:
                self._cb.on_error(f"gemini receive failed: {exc!r}")
        finally:
            self._ended.set()

    def _handle(self, msg, now: float) -> None:
        cb = self._cb
        if msg.data:
            samples = self._resampler.process(msg.data)
            if len(samples):  # soxr primes with an empty chunk; never push empty audio
                cb.on_audio(samples, now)
        sc = msg.server_content
        if sc is not None:
            if sc.interrupted:
                cb.on_interrupted(now)
            if sc.input_transcription and sc.input_transcription.text:
                cb.on_user_text(sc.input_transcription.text)
            if sc.output_transcription and sc.output_transcription.text:
                cb.on_robot_text(sc.output_transcription.text)
        if msg.tool_call:
            for fc in msg.tool_call.function_calls:
                if fc.name in BODY_TOOL_NAMES:
                    cb.on_body_tool(fc.name, dict(fc.args or {}))
                    task = asyncio.get_running_loop().create_task(self._ack_body_tool(fc.id, fc.name))
                    self._ack_tasks.add(task)
                    task.add_done_callback(self._ack_tasks.discard)
                    continue
                args = dict(fc.args or {})
                request = str(args.get("request", "")).strip()
                lane = args.get("lane") if args.get("lane") in ("quick", "task") else choose_lane(request)
                self._calls[fc.id] = fc.name
                cb.on_delegation(Delegation(call_id=fc.id, request=request, lane=lane))
        if msg.usage_metadata:
            cb.on_usage({"total_tokens": msg.usage_metadata.total_token_count})

    async def close(self) -> None:
        self._closing = True
        try:
            if self._cm is not None:
                cm, self._cm = self._cm, None
                try:
                    await asyncio.wait_for(cm.__aexit__(None, None, None), timeout=5.0)
                except Exception as exc:  # noqa: BLE001 - includes TimeoutError; close() must not raise
                    if self._cb is not None:
                        self._cb.on_error(f"gemini close failed: {exc!r}")
        finally:
            pending = list(self._ack_tasks)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if self._rx is not None:
                self._rx.cancel()
                await asyncio.gather(self._rx, return_exceptions=True)

    async def wait_closed(self) -> None:
        await self._ended.wait()
