"""The only code that moves Reachy. Blocking SDK calls run in a worker thread behind one lock;
every public method logs and swallows errors, so the body can never break the voice."""

import asyncio

from reachy_voice.body_calibration import ANTENNA_LISTEN, ANTENNA_REST, WOBBLE_SCALE
from reachy_voice.body_policy import doa_to_yaw
from reachy_voice.log import JsonlLog

LIBRARY = "pollen-robotics/reachy-mini-emotions-library"
_LOOK = {"left": (25, 0), "right": (-25, 0), "up": (0, -15), "down": (0, 15), "front": (0, 0)}


def _default_loader():
    from reachy_mini.motion.recorded_move import RecordedMoves

    return RecordedMoves(LIBRARY)


def _default_resolver(intent: str, names: list[str]) -> str | None:
    try:
        from reachy_mini_conversation_app.tools.play_emotion import resolve_emotion_name

        return resolve_emotion_name(intent, names)
    except ImportError:
        return intent if intent in names else None


def _default_head_pose(yaw_deg: float = 0, pitch_deg: float = 0):
    from reachy_mini.utils import create_head_pose

    return create_head_pose(yaw=yaw_deg, pitch=pitch_deg, degrees=True)


class Body:
    def __init__(self, mini, log: JsonlLog, tracking_weight: float = 0.6, library_loader=None, resolver=None,
                 head_pose=None) -> None:
        self._mini, self._log, self._weight = mini, log, tracking_weight
        self._loader = library_loader or _default_loader
        self._resolve = resolver or _default_resolver
        self._pose = head_pose or _default_head_pose
        self._lock = asyncio.Lock()
        self._library = None
        self._library_failed = False
        self._mode = "listening"

    async def _run(self, action: str, steps) -> bool:
        """Run blocking SDK steps in a thread under the motion lock. Never raises."""
        try:
            async with self._lock:
                for step in steps:
                    await asyncio.to_thread(step)
            return True
        except Exception as exc:  # noqa: BLE001 - motion is best-effort
            self._log.write("body_error", action=action, error=repr(exc))
            return False

    async def wake(self, doa: float | None) -> None:
        m, yaw = self._mini, doa_to_yaw(doa)
        steps = [m.enable_motors, m.wake_up]
        if yaw is not None:
            steps.append(lambda: m.goto_target(body_yaw=yaw, duration=0.8))
        steps.append(lambda: m.start_head_tracking(weight=0.0))
        if await self._run("wake", steps):
            self._log.write("body_event", action="wake", yaw=yaw)
        self._mode = "listening"

    async def listening(self) -> None:
        m = self._mini
        self._mode = "listening"
        await self._run("listening", [
            lambda: m.start_head_tracking(weight=0.0),
            m.disable_wobbling,
            lambda: m.goto_target(antennas=list(ANTENNA_LISTEN), duration=0.3, body_yaw=None),
        ])

    async def speaking(self) -> None:
        m = self._mini
        self._mode = "speaking"
        await self._run("speaking", [
            lambda: m.goto_target(antennas=list(ANTENNA_REST), duration=0.3, body_yaw=None),
            lambda: m.start_head_tracking(weight=self._weight),
            self._enable_scaled_wobble,
        ])

    def _enable_scaled_wobble(self) -> None:
        """Speech-driven head motion with reduced up/down (WOBBLE_SCALE), via the SDK's offset callback."""
        try:
            from reachy_mini.io.protocol import SetSpeechOffsetsCmd
        except ImportError:
            self._mini.enable_wobbling()  # unscaled fallback (e.g. SDK layout changed)
            return
        m = self._mini

        def send(offsets) -> None:
            try:
                m.client.send_command(SetSpeechOffsetsCmd(offsets=[v * s for v, s in zip(offsets, WOBBLE_SCALE)]))
            except ConnectionError:
                pass  # best-effort cosmetic motion

        m.media.enable_wobbling(send)

    async def _ensure_library(self):
        if self._library is None and not self._library_failed:
            try:
                self._library = await asyncio.to_thread(self._loader)
            except Exception as exc:  # noqa: BLE001
                self._library_failed = True
                self._log.write("body_error", action="load_library", error=repr(exc))
        return self._library

    async def express(self, intent: str) -> bool:
        try:
            library = await self._ensure_library()
            if library is None:
                return False
            name = self._resolve(intent, library.list_moves())
            if name is None:
                self._log.write("expression_unresolved", intent=intent)
                return False
            m = self._mini
            async with self._lock:
                await asyncio.to_thread(lambda: m.start_head_tracking(weight=0.0))
                await asyncio.to_thread(m.disable_wobbling)
                await m.async_play_move(library.get(name), sound=False)
            self._log.write("body_event", action="express", intent=intent, move=name)
        except Exception as exc:  # noqa: BLE001
            self._log.write("body_error", action="express", error=repr(exc))
            return False
        finally:
            await (self.speaking() if self._mode == "speaking" else self.listening())
        return True

    async def look(self, direction: str) -> None:
        m = self._mini
        if direction == "at_person":
            await self._run("look", [lambda: m.start_head_tracking(weight=self._weight)])
        elif direction in _LOOK:
            yaw, pitch = _LOOK[direction]
            pose = self._pose(yaw_deg=yaw, pitch_deg=pitch)
            await self._run("look", [lambda: m.goto_target(head=pose, duration=0.6, body_yaw=None)])

    async def rest(self) -> None:
        m = self._mini
        await self._run("rest", [
            m.stop_head_tracking,
            m.disable_wobbling,
            lambda: m.goto_target(head=self._pose(), antennas=list(ANTENNA_REST), duration=1.0, body_yaw=0.0),
        ])

    async def sleep(self) -> None:
        m = self._mini
        await self._run("sleep_prepare", [m.stop_head_tracking, m.disable_wobbling])
        await self._run("sleep", [m.goto_sleep])
        await self._run("motors_off", [m.disable_motors])
        self._log.write("body_event", action="sleep")

    async def shutdown(self) -> None:
        await self.sleep()  # each step is independent, so motors go off even if goto_sleep fails


class NullBody:
    """BODY_ENABLED=false: voice-only, exactly as before."""

    async def wake(self, doa): pass
    async def listening(self): pass
    async def speaking(self): pass
    async def express(self, intent): return False
    async def look(self, direction): pass
    async def rest(self): pass
    async def sleep(self): pass
    async def shutdown(self): pass
