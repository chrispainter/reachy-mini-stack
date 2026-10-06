"""Gemini 3.8 Live on the robot: latency, talk-while-tool and barge-in."""

import argparse
import asyncio
import os
import time

from google import genai
from google.genai import types
from reachy_mini import ReachyMini

from spike.audio import StreamResampler, mic_to_pcm16, rms
from spike.fake_agent import fake_home_agent
from spike.log import JsonlLog
from spike.persona import PERSONA, TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMS
from spike.robot_audio import RobotAudio
from spike.timing import DeadAirMeter, TurnTimer


def build_config(voice: str) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
        system_instruction=PERSONA,
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=TOOL_NAME,
                        description=TOOL_DESCRIPTION,
                        parameters_json_schema=TOOL_PARAMS,
                        behavior=types.Behavior.NON_BLOCKING,
                    )
                ]
            )
        ],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )


async def pump_mic(session, audio: RobotAudio, timer: TurnTimer) -> None:
    async for frame in audio.frames():
        now = time.monotonic()
        timer.on_mic(rms(frame), now, audio.is_speaking(now))
        await session.send_realtime_input(
            audio=types.Blob(data=mic_to_pcm16(frame), mime_type="audio/pcm;rate=16000")
        )


async def answer_tool(session, fc, dead_air: DeadAirMeter, log: JsonlLog, delay_s: float) -> None:
    result = await fake_home_agent((fc.args or {}).get("request", ""), delay_s=delay_s)
    log.write("tool_result", **dead_air.end(fc.id, time.monotonic()))
    await session.send_tool_response(
        function_responses=[
            types.FunctionResponse(
                id=fc.id,
                name=fc.name,
                response={"result": result},
                scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
            )
        ]
    )


def _tool_done(task: asyncio.Task, pending: set, log: JsonlLog) -> None:
    pending.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.write("tool_error", error=repr(exc))
        print(f"tool error: {exc!r}")


async def pump_server(session, audio, timer, dead_air, log, delay_s) -> None:
    pending: set[asyncio.Task] = set()
    resampler = StreamResampler(24000, 16000)
    try:
        await _serve(session, audio, timer, dead_air, log, delay_s, pending, resampler)
    finally:
        for t in list(pending):
            t.cancel()


async def _serve(session, audio, timer, dead_air, log, delay_s, pending, resampler) -> None:
    while True:  # receive() ends after each completed turn
        async for msg in session.receive():
            now = time.monotonic()
            samples = resampler.process(msg.data) if msg.data else None
            if samples is not None and samples.size:  # soxr returns empty chunks while priming; pushing one segfaults GStreamer
                latency = timer.on_robot_audio(now)
                if latency is not None:
                    log.write("first_audio", latency_s=latency)
                    print(f"first audio {latency:.2f} s after speech")
                dead_air.on_audio(now, len(samples) / 16000)
                audio.play(samples, now)
            sc = msg.server_content
            if sc is not None:
                if sc.interrupted:
                    audio.clear(now)
                    log.write("interrupted")
                if sc.input_transcription and sc.input_transcription.text:
                    log.write("user_text", text=sc.input_transcription.text)
                if sc.output_transcription and sc.output_transcription.text:
                    log.write("robot_text", text=sc.output_transcription.text)
                if sc.turn_complete:
                    log.write("turn_complete")
            if msg.tool_call:
                for fc in msg.tool_call.function_calls:
                    dead_air.start(fc.id, now)
                    log.write("tool_call", call_id=fc.id, name=fc.name, args=dict(fc.args or {}))
                    print(f"tool call {fc.name} {dict(fc.args or {})}")
                    task = asyncio.create_task(answer_tool(session, fc, dead_air, log, delay_s))
                    pending.add(task)
                    task.add_done_callback(lambda t: _tool_done(t, pending, log))
            if msg.usage_metadata:
                log.write("usage", total_tokens=msg.usage_metadata.total_token_count)


async def main(args) -> None:
    log = JsonlLog(f"logs/gemini-{int(time.time())}.jsonl")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    timer, dead_air = TurnTimer(speech_threshold=args.speech_threshold), DeadAirMeter()
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        try:
            async with client.aio.live.connect(model=args.model, config=build_config(args.voice)) as session:
                log.write("session_open", engine="gemini", model=args.model, voice=args.voice)
                print("listening; Ctrl-C to stop")
                await asyncio.wait_for(
                    asyncio.gather(
                        pump_mic(session, audio, timer),
                        pump_server(session, audio, timer, dead_air, log, args.tool_delay),
                    ),
                    timeout=args.minutes * 60,
                )
        except asyncio.TimeoutError:
            pass
        finally:
            audio.stop()
            log.write("session_close")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gemini-3.8-live")
    p.add_argument("--voice", default="Kore")
    p.add_argument("--tool-delay", type=float, default=20.0)
    p.add_argument("--minutes", type=float, default=6.0)
    p.add_argument("--speech-threshold", type=float, default=0.02)
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
