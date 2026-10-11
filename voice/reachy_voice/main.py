"""Entry point on the robot: wake word -> voice session -> back to listening."""

import asyncio
import glob
import os
import signal
import time

from reachy_mini import ReachyMini

from reachy_voice.config import Settings, load_settings
from reachy_voice.engines import make_engine
from reachy_voice.hermes import HermesClient
from reachy_voice.log import JsonlLog
from reachy_voice.policy import EngineChooser, SessionPolicy, other_engine
from reachy_voice.robot_audio import RobotAudio
from reachy_voice.session import EngineStartError, VoiceSession
from reachy_voice.wake import WakeWord, load_wake_model


async def _run_session(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient, log: JsonlLog) -> str:
    policy = SessionPolicy(settings.idle_timeout_s, settings.pending_max_s, settings.max_session_s)
    session = VoiceSession(make_engine(name, settings), audio, hermes, policy, settings.speech_threshold, log,
                           session_id=f"reachy-{name}-{int(time.time())}")
    return await session.run()


async def _session_with_fallback(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient,
                                 log: JsonlLog) -> tuple[str, str]:
    """Run a session; returns (end reason, engine that actually ran)."""
    candidates = [name] + ([other_engine(name)] if settings.has_engine(other_engine(name)) else [])
    for engine in candidates:
        try:
            return await _run_session(engine, settings, audio, hermes, log), engine
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
    audio = RobotAudio(mini.media)
    audio.start()
    try:
        wake = WakeWord(load_wake_model(settings.wake_model), settings.wake_threshold)
        log.write("ready", engine_mode=settings.engine, wake_model=settings.wake_model, pruned_logs=pruned_logs)
        while True:
            async for frame in audio.frames():
                if wake.feed(frame, time.monotonic()):
                    break
            audio.chime("wake")
            name = chooser.next()
            log.write("wake", engine=name)
            reason, engine_used = await _session_with_fallback(name, settings, audio, hermes, log)
            log.write("session_end", engine=engine_used, reason=reason)
            audio.chime("sleep")
            wake.reset(time.monotonic())
    finally:
        audio.stop()


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
