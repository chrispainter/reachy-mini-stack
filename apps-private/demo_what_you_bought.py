"""demo_what_you_bought.py — A guided tour of Reachy Mini's expressive moves.

Connects to a running daemon (sim or physical) on localhost:8000 and runs
through the things you actually pay $449 for: head movement, look-at, antenna
expressions, body rotation, and an improvised wobble.

Watch in browser:  http://reachy-pi.local:8000  (the daemon dashboard 3D view)
Run:               python ~/reachy-mini-stack/apps-private/demo_what_you_bought.py
                   (with ~/reachy-venv activated)

When the physical Reachy arrives, pass --host reachy-mini.local to target it
instead of the sim — same script, real robot.
"""
import argparse
import math
import time

import numpy as np
from reachy_mini import ReachyMini


def banner(text: str) -> None:
    print(f"\n{'─' * 64}\n  {text}\n{'─' * 64}")


def head_pose_rpy(roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0,
                  z_offset: float = 0.0) -> np.ndarray:
    """Build a 4x4 head pose from roll/pitch/yaw radians (intrinsic XYZ)."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    pose = np.eye(4)
    pose[:3, :3] = R
    pose[2, 3] = z_offset
    return pose


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost",
                   help="Daemon host (default: localhost; use reachy-mini.local for real robot)")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    print(f"Connecting to Reachy Mini daemon at {args.host}:{args.port} ...")
    robot = ReachyMini(host=args.host, port=args.port)
    print("Connected. Open http://reachy-pi.local:8000 to watch.")
    time.sleep(1.0)

    try:
        # ── 1. Wake up ────────────────────────────────────────────────
        banner("1. Wake up")
        robot.wake_up()
        time.sleep(1.5)

        # ── 2. Look around the room ───────────────────────────────────
        banner("2. Look around")
        # look_at_world(x_forward, y_left, z_up) in meters from robot frame
        spots = [
            (0.6, 0.0, 0.5, "straight ahead"),
            (0.6, 0.4, 0.5, "left"),
            (0.6, -0.4, 0.5, "right"),
            (0.6, 0.0, 0.9, "up"),
            (0.6, 0.0, 0.1, "down"),
            (0.6, 0.0, 0.5, "back to center"),
        ]
        for x, y, z, label in spots:
            print(f"  → looking {label}")
            robot.look_at_world(x, y, z, duration=1.0)

        # ── 3. Antenna expressions ────────────────────────────────────
        banner("3. Antenna expressions (the personality buttons)")
        looks = [
            ([1.2, 1.2], "Both ears UP — alert"),
            ([-1.2, -1.2], "Both ears DOWN — bummed"),
            ([1.2, -0.6], "Lopsided — confused"),
            ([0.8, -0.8], "Lopsided the other way — sus"),
            ([0.0, 0.0], "Neutral"),
        ]
        for ant, label in looks:
            print(f"  → {label}")
            robot.goto_target(antennas=ant, duration=0.7)
            time.sleep(0.4)

        # ── 4. Head tilts (roll/pitch/yaw) ────────────────────────────
        banner("4. Head tilts")
        tilts = [
            (0.3, 0, 0, "tilt right (curious)"),
            (-0.3, 0, 0, "tilt left"),
            (0, 0.25, 0, "look down (thinking)"),
            (0, -0.2, 0, "look up (idea!)"),
            (0, 0, 0.3, "head turn left"),
            (0, 0, -0.3, "head turn right"),
            (0, 0, 0, "neutral"),
        ]
        for r, p_, y, label in tilts:
            print(f"  → {label}")
            robot.goto_target(head=head_pose_rpy(r, p_, y), duration=0.8)

        # ── 5. Body yaw — the 360 swivel ──────────────────────────────
        banner("5. Body rotation")
        for deg in [45, -45, 90, -90, 0]:
            print(f"  → body yaw {deg}°")
            robot.set_target_body_yaw(math.radians(deg))
            time.sleep(0.9)

        # ── 6. Improvised wobble dance ────────────────────────────────
        banner("6. Improvised wobble (the dance you came for)")
        beats = 12
        beat_period = 0.35
        for i in range(beats):
            phase = i * (2 * math.pi / beats)
            roll = 0.25 * math.sin(phase)
            yaw = 0.4 * math.cos(phase * 0.5)
            ant = [0.8 * math.sin(phase + 0.3), 0.8 * math.cos(phase)]
            body = math.radians(15 * math.sin(phase * 1.5))
            robot.set_target_body_yaw(body)
            robot.goto_target(head=head_pose_rpy(roll, 0, yaw),
                              antennas=ant, duration=beat_period * 0.95)

        # ── 7. Reset and sleep ────────────────────────────────────────
        banner("7. Stand down")
        robot.set_target_body_yaw(0.0)
        robot.goto_target(head=head_pose_rpy(), antennas=[0.0, 0.0], duration=1.0)
        time.sleep(1.5)
        print("  → goto_sleep()")
        robot.goto_sleep()
        time.sleep(2.0)
        print("\n✓ Demo complete. Same script, same call sites, will run on the physical robot.\n")

    except KeyboardInterrupt:
        print("\nInterrupted — sleeping the robot.")
        try:
            robot.goto_sleep()
        except Exception:
            pass


if __name__ == "__main__":
    main()
