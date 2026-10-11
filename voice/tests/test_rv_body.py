import asyncio
import json

from reachy_voice.body import Body, NullBody
from reachy_voice.body_calibration import ANTENNA_LISTEN, ANTENNA_REST
from reachy_voice.log import JsonlLog


class FakeMini:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def _rec(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def enable_motors(self): self._rec("enable_motors")
    def disable_motors(self): self._rec("disable_motors")
    def wake_up(self): self._rec("wake_up")
    def goto_sleep(self): self._rec("goto_sleep")
    def goto_target(self, **kw): self._rec("goto_target", **kw)
    def start_head_tracking(self, weight=1.0): self._rec("start_head_tracking", weight=weight)
    def stop_head_tracking(self): self._rec("stop_head_tracking")
    def enable_wobbling(self): self._rec("enable_wobbling")
    def disable_wobbling(self): self._rec("disable_wobbling")

    async def async_play_move(self, move, sound=True):
        self._rec("async_play_move", move, sound=sound)


class FakeLibrary:
    def list_moves(self): return ["thoughtful1", "welcoming2"]
    def get(self, name): return f"move:{name}"


def make(tmp_path, mini=None, loader=FakeLibrary, resolver=None):
    log_path = tmp_path / "b.jsonl"
    body = Body(mini or FakeMini(), JsonlLog(str(log_path)), tracking_weight=0.6, library_loader=loader,
                resolver=resolver or (lambda intent, names: {"thinking": "thoughtful1", "welcoming": "welcoming2"}.get(intent)),
                head_pose=lambda yaw_deg=0, pitch_deg=0: ("pose", yaw_deg, pitch_deg))
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
    import sys
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
