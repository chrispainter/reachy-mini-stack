"""Throwaway hardware probe for body-language design questions. Run on the robot with the
voice service stopped:  sudo systemctl stop reachy-voice
  .venv/bin/python tools/body_probe.py wake        # motors on + wake_up, timed
  .venv/bin/python tools/body_probe.py doa         # prints DoA for 15 s: speak from left, front, right
  .venv/bin/python tools/body_probe.py antennas    # cycles antenna positions
  .venv/bin/python tools/body_probe.py emotion thinking
  .venv/bin/python tools/body_probe.py noise       # mic RMS with head still vs moving (no speech)
  .venv/bin/python tools/body_probe.py track       # tracking 0.6 + wobble while a tone plays
  .venv/bin/python tools/body_probe.py sleep       # goto_sleep + motors off, timed
"""

import sys
import time

import numpy as np
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose


def rms_for(mini, seconds):
    vals, t = [], time.time()
    while time.time() - t < seconds:
        s = mini.media.get_audio_sample()
        if s is not None and len(s):
            vals.append(float(np.sqrt(np.mean(np.square(s[:, 0])))))
        else:
            time.sleep(0.005)
    if not vals:
        return 0.0, 0.0
    return np.percentile(vals, 50), np.percentile(vals, 95)


def main(cmd, arg=None):
    with ReachyMini() as mini:
        if cmd == "wake":
            t = time.time(); mini.enable_motors(); mini.wake_up(); print(f"wake_up took {time.time()-t:.1f}s")
        elif cmd == "sleep":
            t = time.time(); mini.goto_sleep(); mini.disable_motors(); print(f"goto_sleep took {time.time()-t:.1f}s")
        elif cmd == "doa":
            mini.media.start_recording()
            t = time.time()
            while time.time() - t < 15:
                doa = mini.media.get_DoA()
                if doa is not None and doa[1]:
                    print("doa", doa, flush=True)
                time.sleep(0.25)
            mini.media.stop_recording()
        elif cmd == "antennas":
            mini.enable_motors()
            for a in ([0.0, 0.0], [0.4, -0.4], [-0.4, 0.4], [0.3, 0.3], [-0.3, -0.3]):
                print("antennas", a, flush=True); mini.goto_target(antennas=a, duration=0.6, body_yaw=None); time.sleep(1.5)
        elif cmd == "emotion":
            from reachy_mini.motion.recorded_move import RecordedMoves
            from reachy_mini_conversation_app.tools.play_emotion import resolve_emotion_name
            lib = RecordedMoves("pollen-robotics/reachy-mini-emotions-library")
            name = resolve_emotion_name(arg, lib.list_moves())
            mini.enable_motors()
            t = time.time(); mini.play_move(lib.get(name), sound=False); print(f"{arg}->{name} took {time.time()-t:.1f}s")
        elif cmd == "noise":
            mini.media.start_recording(); mini.enable_motors()
            print("still   p50/p95", rms_for(mini, 4))
            t = time.time()
            while time.time() - t < 4:
                mini.goto_target(create_head_pose(yaw=12 * np.sin(time.time() * 3)), duration=0.15, body_yaw=None)
            print("moving  p50/p95", rms_for(mini, 0.1), "(sampled after)")
            mini.media.stop_recording()
        elif cmd == "track":
            mini.enable_motors(); mini.media.start_playing()
            mini.start_head_tracking(weight=0.6); mini.enable_wobbling()
            tone = (0.15 * np.sin(2 * np.pi * 220 * np.arange(16000 * 5) / 16000) * (1 + np.sin(np.arange(16000 * 5) / 800))).astype(np.float32)
            mini.media.push_audio_sample(tone); time.sleep(6)
            mini.disable_wobbling(); mini.start_head_tracking(weight=0.0)
            print("track+wobble done; was the motion natural? (observe)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
