import asyncio
import json
import sys
import time

import pytest

from reachy_voice.body import Body, NullBody
from reachy_voice.body_calibration import ANTENNA_LISTEN, ANTENNA_REST
from reachy_voice.log import JsonlLog


@pytest.fixture(autouse=True)
def _no_sdk_protocol(monkeypatch):
    # force the unscaled-wobble fallback so tests behave the same where reachy_mini is installed
    monkeypatch.setitem(sys.modules, "reachy_mini.io.protocol", None)


class FakeMini:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def _rec(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def enable_motors(self, ids=None): self._rec("enable_motors", ids=ids)
    def disable_motors(self, ids=None):
        self._rec("disable_motors", ids=ids)
        if getattr(self, "motors_fail_once", False) and names(self).count("disable_motors") == 1:
            raise RuntimeError("disable_motors failed once")
    def cancel_move(self): self._rec("cancel_move")
    def wake_up(self): self._rec("wake_up")
    def goto_sleep(self):
        self._rec("goto_sleep")
        time.sleep(getattr(self, "sleep_s", 0))
    def goto_target(self, **kw): self._rec("goto_target", **kw)
    def start_head_tracking(self, weight=1.0): self._rec("start_head_tracking", weight=weight)
    def stop_head_tracking(self): self._rec("stop_head_tracking")
    def enable_wobbling(self): self._rec("enable_wobbling")
    def disable_wobbling(self): self._rec("disable_wobbling")

    async def async_play_move(self, move, sound=True):
        self._rec("async_play_move", move, sound=sound)
        if getattr(self, "hang_move", False):
            await asyncio.sleep(60)


class FakeLibrary:
    def list_moves(self): return ["thoughtful1", "welcoming2"]
    def get(self, name): return f"move:{name}"


def make(tmp_path, mini=None, loader=FakeLibrary, resolver=None, head_pose=None, **kw):
    log_path = tmp_path / "b.jsonl"
    body = Body(mini or FakeMini(), JsonlLog(str(log_path)), tracking_weight=0.6, library_loader=loader,
                resolver=resolver or (lambda intent, names: {"thinking": "thoughtful1", "welcoming": "welcoming2"}.get(intent)),
                head_pose=head_pose or (lambda yaw_deg=0, pitch_deg=0: ("pose", yaw_deg, pitch_deg)), **kw)
    return body, log_path


def names(mini):
    return [c[0] for c in mini.calls]


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_wake_enables_motors_wakes_turns_and_pauses_tracking(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.wake(doa=None))
    assert names(mini)[:2] == ["enable_motors", "wake_up"]
    assert ("start_head_tracking", (), {"weight": 0.0}) in mini.calls


def test_speaking_and_listening_switch_tracking_wobble_and_antennas(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.speaking())
    asyncio.run(body.listening())
    assert ("start_head_tracking", (), {"weight": 0.6}) in mini.calls
    assert "enable_wobbling" in names(mini) and names(mini)[-1] in ("goto_target", "disable_wobbling", "start_head_tracking")
    antenna_targets = [c[2].get("antennas") for c in mini.calls if c[0] == "goto_target"]
    assert list(ANTENNA_REST) in antenna_targets and list(ANTENNA_LISTEN) in antenna_targets


def test_express_plays_resolved_move_silently_and_restores_mode(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)

    async def go():
        await body.speaking()
        mini.calls.clear()
        return await body.express("thinking")
    assert asyncio.run(go()) is True
    assert ("async_play_move", ("move:thoughtful1",), {"sound": False}) in mini.calls
    assert names(mini).index("disable_wobbling") < names(mini).index("async_play_move")
    assert names(mini)[-2:] == ["start_head_tracking", "enable_wobbling"] or "enable_wobbling" in names(mini)[-3:]


def test_unknown_emotion_or_missing_library_skips_but_body_still_moves(tmp_path):
    mini = FakeMini()
    body, path = make(tmp_path, mini)
    assert asyncio.run(body.express("ecstatic")) is False

    def broken_loader():
        raise OSError("dataset missing")
    mini2 = FakeMini()
    body2, path2 = make(tmp_path / "x", mini2, loader=broken_loader)
    (tmp_path / "x").mkdir(exist_ok=True)
    assert asyncio.run(body2.express("thinking")) is False
    assert asyncio.run(body2.express("welcoming")) is False      # disabled after first failure
    asyncio.run(body2.speaking())
    assert "enable_wobbling" in names(mini2)
    assert sum(1 for e in events(path2) if e["event"] == "body_error" and e["action"] == "load_library") == 1


def test_sdk_errors_are_swallowed_and_logged(tmp_path):
    mini = FakeMini(fail={"wake_up", "enable_wobbling"})
    body, path = make(tmp_path, mini)
    asyncio.run(body.wake(doa=0.0))
    asyncio.run(body.speaking())
    errs = [e for e in events(path) if e["event"] == "body_error"]
    assert {e["action"] for e in errs} >= {"wake", "speaking"}


def test_shutdown_disables_motors_even_if_sleep_fails(tmp_path):
    mini = FakeMini(fail={"goto_sleep"})
    body, _ = make(tmp_path, mini)
    asyncio.run(body.shutdown())
    assert "disable_motors" in names(mini)


def test_look_directions_and_null_body(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.look("left"))
    assert ("goto_target", (), {"head": ("pose", 25, 0), "duration": 0.6, "body_yaw": None}) in mini.calls
    asyncio.run(body.look("at_person"))
    assert ("start_head_tracking", (), {"weight": 0.6}) in mini.calls
    nb = NullBody()
    asyncio.run(nb.wake(None)); asyncio.run(nb.speaking()); asyncio.run(nb.shutdown())
    assert asyncio.run(nb.express("happy")) is False


def test_speaking_uses_scaled_wobble_when_sdk_protocol_available(tmp_path, monkeypatch):
    import types

    class SetSpeechOffsetsCmd:
        def __init__(self, offsets):
            self.offsets = offsets

    for name in ("reachy_mini", "reachy_mini.io", "reachy_mini.io.protocol"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setattr(sys.modules["reachy_mini.io.protocol"], "SetSpeechOffsetsCmd", SetSpeechOffsetsCmd, raising=False)

    mini = FakeMini()
    callbacks, sent = [], []
    mini.media = types.SimpleNamespace(enable_wobbling=callbacks.append)
    mini.client = types.SimpleNamespace(send_command=sent.append)
    body, _ = make(tmp_path, mini)
    asyncio.run(body.speaking())
    assert "enable_wobbling" not in names(mini)
    assert len(callbacks) == 1
    callbacks[0]((1, 1, 1, 1, 1, 1))
    assert sent[0].offsets == [1.0, 1.0, 0.35, 1.0, 0.35, 1.0]
    # any exception from the send must not escape into the SDK's wobble thread
    def boom(cmd):
        raise RuntimeError("bus error")
    mini.client.send_command = boom
    callbacks[0]((1, 1, 1, 1, 1, 1))


def test_sleep_wins_over_in_flight_expression_restore(tmp_path):
    release = None

    class SlowMini(FakeMini):
        async def async_play_move(self, move, sound=True):
            self._rec("async_play_move", move, sound=sound)
            await release.wait()

    async def go():
        nonlocal release
        release = asyncio.Event()
        mini = SlowMini()
        body, _ = make(tmp_path, mini)
        await body.speaking()
        mini.calls.clear()
        expr = asyncio.create_task(body.express("thinking"))
        while "async_play_move" not in names(mini):
            await asyncio.sleep(0.01)
        slp = asyncio.create_task(body.sleep())
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.gather(expr, slp)
        return mini

    mini = asyncio.run(go())
    after = mini.calls[names(mini).index("goto_sleep"):]
    assert ("start_head_tracking", (), {"weight": 0.6}) not in after
    assert "enable_wobbling" not in [c[0] for c in after]
    assert "disable_motors" in names(mini)


def test_unresolved_express_does_not_restore_mode(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    assert asyncio.run(body.express("ecstatic")) is False
    assert mini.calls == []


def test_sleep_steps_are_individually_guarded(tmp_path):
    mini = FakeMini(fail={"stop_head_tracking", "goto_sleep"})
    body, path = make(tmp_path, mini)
    asyncio.run(body.sleep())
    assert "disable_motors" in names(mini)
    assert {e["action"] for e in events(path) if e["event"] == "body_error"} >= {"sleep_stop_tracking", "sleep_goto_sleep"}


def test_shutdown_returns_promptly_and_cuts_motors_when_sdk_call_hangs(tmp_path):
    mini = FakeMini()
    mini.sleep_s = 1.0
    body, _ = make(tmp_path, mini, step_timeout_s=0.1)
    async def go():
        start = time.monotonic()
        await body.shutdown()
        return time.monotonic() - start
    assert asyncio.run(go()) < 0.9  # measured inside the loop; asyncio.run itself joins the hung thread
    assert "disable_motors" in names(mini)


def test_cancelled_shutdown_still_turns_motors_off(tmp_path):
    mini = FakeMini()
    mini.sleep_s = 0.5
    body, _ = make(tmp_path, mini)

    async def go():
        task = asyncio.create_task(body.shutdown())
        while "goto_sleep" not in names(mini):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert "disable_motors" in names(mini)


def test_value_computation_failures_are_guarded(tmp_path):
    def bad_pose(yaw_deg=0, pitch_deg=0):
        raise ValueError("bad pose")
    mini = FakeMini()
    body, path = make(tmp_path, mini, head_pose=bad_pose)
    asyncio.run(body.look("left"))
    assert any(e["event"] == "body_error" and e["action"] == "look" for e in events(path))
    body2, path2 = make(tmp_path / "w", FakeMini())
    (tmp_path / "w").mkdir(exist_ok=True)
    import reachy_voice.body as bodymod
    orig = bodymod.doa_to_yaw
    bodymod.doa_to_yaw = lambda d: 1 / 0
    try:
        asyncio.run(body2.wake(doa=1.0))
    finally:
        bodymod.doa_to_yaw = orig
    assert any(e["event"] == "body_error" and e["action"] == "wake_yaw" for e in events(path2))


def test_step_after_timeout_never_overlaps_the_still_running_thread(tmp_path):
    spans = []

    def slow():
        spans.append(["slow", time.monotonic(), None])
        time.sleep(0.3)
        spans[-1][2] = time.monotonic()

    def quick():
        spans.append(["quick", time.monotonic(), time.monotonic()])

    async def go():
        body, _ = make(tmp_path, FakeMini(), step_timeout_s=0.2)
        assert await body._run("a", [slow]) is False       # times out, thread keeps running
        assert await body._run("b", [quick]) is True       # waits for it (0.2 s more), then runs
    asyncio.run(go())
    slow_span, quick_span = spans
    assert quick_span[1] >= slow_span[2]


def test_step_is_skipped_as_busy_while_previous_thread_is_still_running(tmp_path):
    ran = []

    async def go():
        body, path = make(tmp_path, FakeMini(), step_timeout_s=0.1)
        assert await body._run("a", [lambda: time.sleep(0.6)]) is False
        assert await body._run("b", [lambda: ran.append(1)]) is False
        return path
    path = asyncio.run(go())
    assert ran == []
    assert any(e["event"] == "body_error" and e["action"] == "busy" for e in events(path))


def test_speaking_and_listening_are_noops_after_sleep(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.sleep())
    mini.calls.clear()
    asyncio.run(body.speaking())
    asyncio.run(body.listening())
    assert mini.calls == []
    asyncio.run(body.wake(doa=None))
    asyncio.run(body.speaking())
    assert "enable_wobbling" in names(mini)


def test_sleep_retries_motors_off_without_lock_and_returns_true(tmp_path):
    mini = FakeMini()
    mini.motors_fail_once = True
    body, _ = make(tmp_path, mini)
    assert asyncio.run(body.sleep()) is True
    assert names(mini).count("disable_motors") == 2


def test_sleep_busy_step_still_attempts_motors_off(tmp_path):
    mini = FakeMini()
    mini.sleep_s = 1.0
    body, _ = make(tmp_path, mini, step_timeout_s=0.1)
    assert asyncio.run(body.sleep()) is True
    assert "disable_motors" in names(mini)


def test_sleep_reports_false_when_motors_cannot_be_turned_off(tmp_path):
    body, _ = make(tmp_path, FakeMini(fail={"disable_motors"}))
    assert asyncio.run(body.sleep()) is False


def test_express_move_that_never_finishes_times_out_and_cancels(tmp_path):
    mini = FakeMini()
    mini.hang_move = True
    body, path = make(tmp_path, mini, move_timeout_s=0.1)

    async def go():
        start = time.monotonic()
        ok = await body.express("thinking")
        return ok, time.monotonic() - start

    ok, took = asyncio.run(go())
    assert ok is False and took < 2
    assert "cancel_move" in names(mini)
    assert any(e["event"] == "body_error" and e["action"] == "express_timeout" for e in events(path))


def test_wake_ends_with_antennas_perked(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.wake(doa=None))
    last = [c for c in mini.calls if c[0] == "goto_target"][-1]
    assert last[2]["antennas"] == list(ANTENNA_LISTEN)


ANTENNAS = ["left_antenna", "right_antenna"]


def _idx(mini, name, **kw):
    return next(i for i, c in enumerate(mini.calls) if c[0] == name and all(c[2].get(k) == v for k, v in kw.items()))


def test_rest_ends_by_relaxing_antenna_torque(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    asyncio.run(body.rest())
    assert mini.calls[-1] == ("disable_motors", (), {"ids": ANTENNAS})
    assert names(mini)[-2] == "goto_target"


def test_listening_and_speaking_re_enable_antenna_torque_first(tmp_path):
    for fn in ("listening", "speaking"):
        mini = FakeMini()
        body, _ = make(tmp_path, mini)
        asyncio.run(getattr(body, fn)())
        assert mini.calls[0] == ("enable_motors", (), {"ids": ANTENNAS}), fn


def test_express_re_enables_antenna_torque_before_the_move(tmp_path):
    mini = FakeMini()
    body, _ = make(tmp_path, mini)
    assert asyncio.run(body.express("thinking")) is True
    assert _idx(mini, "enable_motors", ids=ANTENNAS) < names(mini).index("async_play_move")


def test_cancelled_sleep_still_attempts_motors_off(tmp_path):
    mini = FakeMini()
    mini.sleep_s = 1.5
    body, _ = make(tmp_path, mini, step_timeout_s=0.4)

    async def go():
        await asyncio.wait_for(body.sleep(), 0.5)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(go())
    assert "disable_motors" in names(mini)
