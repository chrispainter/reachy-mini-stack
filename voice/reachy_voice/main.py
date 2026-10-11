"""Entry point on the robot: wake word -> voice session -> back to listening."""

import asyncio
import os
import time

from reachy_mini import ReachyMini

from reachy_voice.config import Settings, load_settings
from reachy_voice.engines import make_engine
from reachy_voice.hermes import HermesClient
from reachy_voice.log import JsonlLog
from reachy_voice.policy import EngineChooser, SessionPolicy, other_engine
from reachy_voice.robot_audio import RobotAudio
from reachy_voice.session import VoiceSession
from reachy_voice.wake import WakeWord, load_wake_model


async def _run_session(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient, log: JsonlLog) -> str:
    policy = SessionPolicy(settings.idle_timeout_s, settings.pending_max_s, settings.max_session_s)
    session = VoiceSession(make_engine(name, settings), audio, hermes, policy, settings.speech_threshold, log,
                           session_id=f"reachy-{name}-{int(time.time())}")
    return await session.run()


async def _session_with_fallback(name: str, settings: Settings, audio: RobotAudio, hermes: HermesClient,
                                 log: JsonlLog) -> str:
    candidates = [name] + ([other_engine(name)] if settings.has_engine(other_engine(name)) else [])
    for engine in candidates:
        try:
            return await _run_session(engine, settings, audio, hermes, log)
        except Exception as exc:  # noqa: BLE001 - connection/auth failures fall back to the other engine
            log.write("session_error", engine=engine, error=repr(exc))
    audio.chime("error")
    return "error"


async def amain(settings: Settings) -> None:
    log = JsonlLog(os.path.join(settings.log_dir, f"voice-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
    hermes = HermesClient(settings.home_agent_url, settings.home_agent_key, settings.quick_model, settings.quick_provider)
    chooser = EngineChooser(settings.engine)
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        wake = WakeWord(load_wake_model(settings.wake_model), settings.wake_threshold)
        log.write("ready", engine_mode=settings.engine, wake_model=settings.wake_model)
        try:
            while True:
                async for frame in audio.frames():
                    if wake.feed(frame, time.monotonic()):
                        break
                audio.chime("wake")
                name = chooser.next()
                log.write("wake", engine=name)
                reason = await _session_with_fallback(name, settings, audio, hermes, log)
                log.write("session_end", engine=name, reason=reason)
                audio.chime("sleep")
                wake.reset(time.monotonic())
        finally:
            audio.stop()
            await hermes.aclose()


def main() -> None:
    asyncio.run(amain(load_settings(os.environ)))


if __name__ == "__main__":
    main()
