"""The only code that moves Reachy. Blocking SDK calls run in a worker thread behind one lock;
every public method logs and swallows errors, so the body can never break the voice."""

import asyncio

from reachy_voice.body_calibration import ANTENNA_LISTEN, ANTENNA_REST, WOBBLE_SCALE
from reachy_voice.body_policy import doa_to_yaw
from reachy_voice.log import JsonlLog

LIBRARY = "pollen-robotics/reachy-mini-emotions-library"
ANTENNA_IDS = ["left_antenna", "right_antenna"]
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
                 head_pose=None, step_timeout_s: float = 8.0, move_timeout_s: float = 15.0) -> None:
        self._mini, self._log, self._weight = mini, log, tracking_weight
        self._loader = library_loader or _default_loader
        self._resolve = resolver or _default_resolver
        self._pose = head_pose or _default_head_pose
        self._lock = asyncio.Lock()
        self._library = None
        self._library_failed = False
        self._mode = "listening"
        self._step_timeout = step_timeout_s
        self._move_timeout = move_timeout_s
        self._motors_off = False
        self._inflight = None  # a timed-out SDK step whose thread is still running

    async def _step(self, step) -> None:
        """Run one blocking SDK step in a thread. On timeout the thread keeps running; remember it so the
        next lock holder waits for it instead of issuing overlapping motion."""
        task = asyncio.ensure_future(asyncio.to_thread(step))
        task.add_done_callback(lambda f: f.cancelled() or f.exception())  # mark exception retrieved
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._step_timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._inflight = task
            raise

    async def _idle(self) -> bool:
        """Wait (bounded) for a timed-out step's thread to finish. False means still busy: skip motion."""
        task = self._inflight
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._step_timeout)
            except Exception:  # noqa: BLE001 - timeout or the step's own error; done() decides
                pass
            if not task.done():
                self._log.write("body_error", action="busy", error="previous SDK step still running")
                return False
        return True

    async def _guarded(self, action: str, step) -> bool:
        """One blocking SDK step in a thread with a timeout. Logs and swallows errors."""
        try:
            if not await self._idle():
                return False
            await self._step(step)
            return True
        except Exception as exc:  # noqa: BLE001 - motion is best-effort
            self._log.write("body_error", action=action, error=repr(exc))
            return False

    async def _run(self, action: str, steps) -> bool:
        """Run blocking SDK steps in a thread under the motion lock. Never raises."""
        try:
            async with self._lock:
                for step in steps:
                    if not await self._idle():
                        return False
                    await self._step(step)
            return True
        except Exception as exc:  # noqa: BLE001 - motion is best-effort
            self._log.write("body_error", action=action, error=repr(exc))
            return False

    async def wake(self, doa: float | None) -> None:
        m = self._mini
        self._mode = "listening"  # only wake() leaves "asleep"
        try:
            yaw = doa_to_yaw(doa)
        except Exception as exc:  # noqa: BLE001 - treat as no turn
            self._log.write("body_error", action="wake_yaw", error=repr(exc))
            yaw = None
        steps = [m.enable_motors, m.wake_up]
        if yaw is not None:
            steps.append(lambda: m.goto_target(body_yaw=yaw, duration=0.8))
        steps.append(lambda: m.start_head_tracking(weight=0.0))
        steps.append(lambda: m.goto_target(antennas=list(ANTENNA_LISTEN), duration=0.3, body_yaw=None))
        if await self._run("wake", steps):
            self._log.write("body_event", action="wake", yaw=yaw)
        self._mode = "listening"

    async def listening(self) -> None:
        m = self._mini
        if self._mode == "asleep":
            return
        self._mode = "listening"
        await self._run("listening", [
            lambda: m.enable_motors(ids=list(ANTENNA_IDS)),
            lambda: m.start_head_tracking(weight=0.0),
            m.disable_wobbling,
            lambda: m.goto_target(antennas=list(ANTENNA_LISTEN), duration=0.3, body_yaw=None),
        ])

    async def speaking(self) -> None:
        m = self._mini
        if self._mode == "asleep":
            return
        self._mode = "speaking"
        await self._run("speaking", [
            lambda: m.enable_motors(ids=list(ANTENNA_IDS)),
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
            except Exception:  # noqa: BLE001 - cosmetic motion must never kill the SDK's wobble thread
                pass

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
        started = False
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
                if self._mode == "asleep":
                    return False
                if not await self._idle():
                    return False
                started = True
                await self._step(lambda: m.enable_motors(ids=list(ANTENNA_IDS)))
                await self._step(lambda: m.start_head_tracking(weight=0.0))
                await self._step(m.disable_wobbling)
                try:
                    await asyncio.wait_for(m.async_play_move(library.get(name), sound=False),
                                           timeout=self._move_timeout)
                except asyncio.TimeoutError:
                    try:
                        await asyncio.wait_for(asyncio.to_thread(m.cancel_move), timeout=3)
                    except Exception as exc:  # noqa: BLE001
                        self._log.write("body_error", action="express_cancel", error=repr(exc))
                    self._log.write("body_error", action="express_timeout", error="move did not finish")
                    return False
            self._log.write("body_event", action="express", intent=intent, move=name)
        except Exception as exc:  # noqa: BLE001
            self._log.write("body_error", action="express", error=repr(exc))
            return False
        finally:
            if started and self._mode in ("speaking", "listening"):
                await (self.speaking() if self._mode == "speaking" else self.listening())
        return True

    async def look(self, direction: str) -> None:
        m = self._mini
        if direction == "at_person":
            await self._run("look", [lambda: m.start_head_tracking(weight=self._weight)])
        elif direction in _LOOK:
            yaw, pitch = _LOOK[direction]
            await self._run("look", [
                lambda: m.goto_target(head=self._pose(yaw_deg=yaw, pitch_deg=pitch), duration=0.6, body_yaw=None)])

    async def rest(self) -> None:
        m = self._mini
        await self._run("rest", [
            m.stop_head_tracking,
            m.disable_wobbling,
            lambda: m.goto_target(head=self._pose(), antennas=list(ANTENNA_REST), duration=1.0, body_yaw=0.0),
            lambda: m.disable_motors(ids=list(ANTENNA_IDS)),  # relaxed while awake-idle: a held servo dithers
        ])

    async def _force_motors_off(self) -> None:
        """Best effort, deliberately without the motion lock (it may be held by a hung step)."""
        try:
            await asyncio.wait_for(asyncio.to_thread(self._mini.disable_motors), timeout=3)
            self._motors_off = True
        except Exception as exc:  # noqa: BLE001
            self._log.write("body_error", action="motors_off_fallback", error=repr(exc))

    async def sleep(self) -> bool:
        """Mode goes to "asleep" first and the lock is held throughout, so no expression restore can interleave."""
        m = self._mini
        self._mode = "asleep"
        self._motors_off = False
        try:
            async with self._lock:
                await self._guarded("sleep_antennas_on", lambda: m.enable_motors(ids=list(ANTENNA_IDS)))
                await self._guarded("sleep_stop_tracking", m.stop_head_tracking)
                await self._guarded("sleep_disable_wobbling", m.disable_wobbling)
                await self._guarded("sleep_goto_sleep", m.goto_sleep)
                if await self._guarded("sleep_disable_motors", m.disable_motors):
                    self._motors_off = True
            self._log.write("body_event", action="sleep")
        except Exception as exc:  # noqa: BLE001
            self._log.write("body_error", action="sleep", error=repr(exc))
        finally:
            if not self._motors_off:  # also on cancellation (caller timeout); _force_motors_off is self-bounded
                await self._force_motors_off()
        return self._motors_off

    async def shutdown(self) -> None:
        """Always attempts motors-off, even if cancelled or an SDK call hangs. Re-raises only CancelledError."""
        self._motors_off = False
        try:
            await asyncio.wait_for(asyncio.shield(self.sleep()), timeout=12)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.write("body_error", action="shutdown", error=repr(exc))
        finally:
            if not self._motors_off:
                await self._force_motors_off()


class NullBody:
    """BODY_ENABLED=false: voice-only, exactly as before."""

    async def wake(self, doa): pass
    async def listening(self): pass
    async def speaking(self): pass
    async def express(self, intent): return False
    async def look(self, direction): pass
    async def rest(self): pass
    async def sleep(self): return True
    async def shutdown(self): pass
