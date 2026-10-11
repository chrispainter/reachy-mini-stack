"""Entry point on the robot: wake word -> voice session -> back to listening."""

import asyncio
import glob
import os
import signal
import time

from reachy_mini import ReachyMini

from reachy_voice.body import Body, NullBody
from reachy_voice.body_policy import CUES, AwakeTimer, ExpressionGate
from reachy_voice.config import Settings, load_settings
from reachy_voice.engines import make_engine
from reachy_voice.expression_picker import ExpressionPicker
from reachy_voice.hermes import HermesClient
from reachy_voice.log import JsonlLog
from reachy_voice.policy import EngineChooser, SessionPolicy, other_engine
from reachy_voice.robot_audio import RobotAudio
from reachy_voice.session import EngineStartError, VoiceSession
from reachy_voice.wake import WakeWord, load_wake_model


async def _run_session(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient, log: JsonlLog,
                       body=None, gate=None, picker=None) -> str:
    policy = SessionPolicy(settings.idle_timeout_s, settings.pending_max_s, settings.max_session_s)
    session = VoiceSession(make_engine(name, settings), audio, hermes, policy, settings.speech_threshold, log,
                           session_id=f"reachy-{name}-{int(time.time())}", body=body, gate=gate,
                           picker=picker if name == "openai" else None)
    return await session.run()


async def _session_with_fallback(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient,
                                 log: JsonlLog, body=None, gate=None, picker=None) -> tuple[str, str]:
    """Run a session; returns (end reason, engine that actually ran)."""
    candidates = [name] + ([other_engine(name)] if settings.has_engine(other_engine(name)) else [])
    for engine in candidates:
        try:
            return await _run_session(engine, settings, audio, hermes, log, body, gate, picker), engine
        except EngineStartError as exc:  # only a failure to start falls back to the other engine
            log.write("session_error", engine=engine, error=repr(exc), phase="start")
        except Exception as exc:  # noqa: BLE001 - mid-session failure: end the session, no engine swap
            log.write("session_error", engine=engine, error=repr(exc), phase="run")
            audio.chime("error")
            return "error", engine
    audio.chime("error")
    return "error", name


async def _listen_loop(mini, settings: Settings, hermes: HermesClient, log: JsonlLog, pruned_logs: int = 0) -> None:
    chooser = EngineChooser(settings.engine)
    body = Body(mini, log, tracking_weight=settings.tracking_weight) if settings.body_enabled else NullBody()
    timer = AwakeTimer(settings.idle_awake_s)
    gate = ExpressionGate(min_gap_s=settings.expression_min_gap_s)
    picker = ExpressionPicker(settings.openai_api_key) if settings.openai_api_key else None
    audio = RobotAudio(mini.media)
    audio.start()
    try:
        await body.shutdown()  # start asleep with motors off, however the robot was left
        wake = WakeWord(load_wake_model(settings.wake_model), settings.wake_threshold)
        log.write("ready", engine_mode=settings.engine, wake_model=settings.wake_model, pruned_logs=pruned_logs,
                  body_enabled=settings.body_enabled)
        while True:
            next_check = time.monotonic() + 1.0
            async for frame in audio.frames():
                now = time.monotonic()
                audio.sample_doa(now)
                if wake.feed(frame, now):
                    break
                if now >= next_check:
                    next_check = now + 1.0
                    if timer.should_sleep(now):
                        await body.sleep()
                        timer.on_sleep()
                        log.write("body_sleep")
            doa = audio.doa(time.monotonic())
            audio.chime("wake")
            if not timer.awake:
                await body.wake(doa)
                timer.on_wake(time.monotonic())
                # No welcome expression here: the person is usually still talking and head motion raises mic noise ~22x.
            else:
                timer.on_wake(time.monotonic())
            name = chooser.next()
            log.write("wake", engine=name, doa=doa)
            reason, engine_used = await _session_with_fallback(name, settings, audio, hermes, log, body, gate, picker)
            log.write("session_end", engine=engine_used, reason=reason)
            audio.chime("sleep")
            if reason != "error" and gate.allow(time.monotonic(), None, None):
                try:
                    await asyncio.wait_for(body.express(CUES["session_end"]), timeout=10)
                except asyncio.TimeoutError:
                    log.write("body_error", action="goodbye_timeout")
            await body.rest()
            timer.on_session_end(time.monotonic())
            wake.reset(time.monotonic())
    finally:
        cancelled = False
        try:
            await asyncio.wait_for(body.shutdown(), timeout=10)
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:  # noqa: BLE001
            log.write("body_error", action="main_shutdown", error=repr(exc))
        try:
            audio.stop()
        finally:
            try:
                if picker is not None:
                    await picker.aclose()
            finally:
                if cancelled:
                    raise asyncio.CancelledError


LOG_RETENTION_S = 30 * 24 * 3600


def prune_old_logs(log_dir: str, now: float, max_age_s: float = LOG_RETENTION_S) -> int:
    """Best-effort delete of voice-*.jsonl files older than max_age_s; returns how many went."""
    removed = 0
    try:
        for path in glob.glob(os.path.join(log_dir, "voice-*.jsonl")):
            try:
                if now - os.path.getmtime(path) > max_age_s:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


async def amain(settings: Settings) -> None:
    pruned_logs = prune_old_logs(settings.log_dir, time.time())
    log = JsonlLog(os.path.join(settings.log_dir, f"voice-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
    hermes = HermesClient(settings.home_agent_url, settings.home_agent_key, settings.quick_model, settings.quick_provider)
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        with ReachyMini() as mini:
            await _listen_loop(mini, settings, hermes, log, pruned_logs)
    except asyncio.CancelledError:
        log.write("shutdown")  # SIGTERM/SIGINT: a normal exit
    finally:
        await hermes.aclose()


def main() -> None:
    asyncio.run(amain(load_settings(os.environ)))


if __name__ == "__main__":
    main()
