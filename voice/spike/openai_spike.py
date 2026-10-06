"""OpenAI gpt-live-1 on the robot: latency, delegation while talking, local barge-in."""

import argparse
import asyncio
import base64
import json
import os
import time

import websockets
from reachy_mini import ReachyMini

from spike.audio import mic_to_pcm16, pcm16_to_float, rms
from spike.fake_agent import fake_home_agent
from spike.log import JsonlLog
from spike.persona import PERSONA
from spike.robot_audio import RobotAudio
from spike.timing import BargeInDetector, DeadAirMeter, ReplyDropper, TurnTimer

URL = "wss://api.openai.com/v1/live/sessions"


def start_event(model: str, voice: str) -> dict:
    return {
        "type": "session.start",
        "event_id": "start",
        "session": {
            "model": model,
            "instructions": PERSONA,
            "audio": {"format": {"type": "audio/pcm", "rate": 16000}, "output": {"voice": voice}},
            "delegation": {"type": "client"},
        },
    }


async def pump_mic(ws, audio, timer, barge, log, started: asyncio.Event, mic: dict, dropper: ReplyDropper) -> None:
    await started.wait()
    async for frame in audio.frames():
        now = time.monotonic()
        level, speaking = rms(frame), audio.is_speaking(now)
        mic["level"] = round(level, 4)
        timer.on_mic(level, now, speaking)
        if barge.on_frame(level, speaking):
            audio.clear(now)
            dropper.start(now)
            log.write("barge_in", level=mic["level"], robot_speaking=speaking)
        await ws.send(
            json.dumps({"type": "session.input_audio.append", "audio": base64.b64encode(mic_to_pcm16(frame)).decode()})
        )


async def answer_delegation(ws, delegation_id, request, dead_air, log, delay_s) -> None:
    result = await fake_home_agent(request, delay_s=delay_s)
    log.write("tool_result", **dead_air.end(delegation_id, time.monotonic()))
    await ws.send(
        json.dumps(
            {
                "type": "session.commentary.append",
                "event_id": f"result-{delegation_id}",
                "delegation_id": delegation_id,
                "content": result,
            }
        )
    )


def _tool_done(task: asyncio.Task, pending: set, log: JsonlLog) -> None:
    pending.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.write("tool_error", error=repr(exc))
        print(f"tool error: {exc!r}")


async def pump_server(ws, audio, timer, dead_air, log, delay_s, started: asyncio.Event, mic: dict, dropper: ReplyDropper) -> None:
    pending: set[asyncio.Task] = set()
    try:
        await _serve(ws, audio, timer, dead_air, log, delay_s, started, pending, mic, dropper)
    finally:
        for t in list(pending):
            t.cancel()


async def _serve(ws, audio, timer, dead_air, log, delay_s, started, pending, mic, dropper) -> None:
    user_text = ""  # recent user transcript; the delegation event carries no task text
    async for raw in ws:
        event = json.loads(raw)
        kind, now = event.get("type"), time.monotonic()
        if kind == "session.started":
            started.set()
            log.write("session_started")
        elif kind == "session.output_audio.delta":
            samples = pcm16_to_float(base64.b64decode(event["delta"]), 16000, 16000)
            if not samples.size:  # never push an empty array: it segfaults GStreamer
                continue
            was_dropping = dropper.active
            if dropper.should_drop(now):  # in-flight reply from before a local barge-in
                continue
            if was_dropping:
                log.write("barge_drop", chunks=dropper.dropped)
            latency = timer.on_robot_audio(now)
            if latency is not None:
                log.write("first_audio", latency_s=latency, level=mic["level"], robot_speaking=audio.is_speaking(now))
                print(f"first audio {latency:.2f} s after speech")
            dead_air.on_audio(now, len(samples) / 16000)
            audio.play(samples, now)
        elif kind == "session.input_transcript.delta":
            user_text = (user_text + event.get("delta", ""))[-500:]
            log.write("user_text", text=event.get("delta", ""))
        elif kind == "session.output_transcript.delta":
            log.write("robot_text", text=event.get("delta", ""))
        elif kind == "session.delegation.created":
            delegation_id = event["delegation"]["id"]
            dead_air.start(delegation_id, now)
            log.write("tool_call", call_id=delegation_id, request=user_text)
            print(f"delegation {delegation_id}: {user_text!r}")
            task = asyncio.create_task(answer_delegation(ws, delegation_id, user_text, dead_air, log, delay_s))
            pending.add(task)
            task.add_done_callback(lambda t: _tool_done(t, pending, log))
            user_text = ""
        elif kind == "error":
            log.write("error", detail=event)
            print("error:", event)
        elif kind == "session.closed":
            log.write("session_closed", usage=event.get("usage"), reason=event.get("reason"))
            return
        else:
            log.write("server_event", type=kind)


async def main(args) -> None:
    log = JsonlLog(f"logs/openai-{int(time.time())}.jsonl")
    timer = TurnTimer(speech_threshold=args.speech_threshold)
    dead_air, barge = DeadAirMeter(), BargeInDetector(threshold=args.barge_threshold)
    started, mic, dropper = asyncio.Event(), {"level": 0.0}, ReplyDropper()
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        try:
            async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
                await ws.send(json.dumps(start_event(args.model, args.voice)))
                log.write("session_open", engine="openai", model=args.model, voice=args.voice)
                print("listening; Ctrl-C to stop")
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            pump_mic(ws, audio, timer, barge, log, started, mic, dropper),
                            pump_server(ws, audio, timer, dead_air, log, args.tool_delay, started, mic, dropper),
                        ),
                        timeout=args.minutes * 60,
                    )
                except asyncio.TimeoutError:
                    pass
                finally:
                    try:
                        await ws.send(json.dumps({"type": "session.close"}))
                    except websockets.ConnectionClosed:
                        pass
        finally:
            audio.stop()
            log.write("session_close")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gpt-live-1")
    p.add_argument("--voice", default="marin")
    p.add_argument("--tool-delay", type=float, default=20.0)
    p.add_argument("--minutes", type=float, default=6.0)
    p.add_argument("--speech-threshold", type=float, default=0.02)
    p.add_argument("--barge-threshold", type=float, default=0.08)
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
