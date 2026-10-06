"""Check the spike venv can import everything and drive the mic and speaker."""

import asyncio
import time

import numpy as np
from google import genai  # noqa: F401  (import check only)
from reachy_mini import ReachyMini

from spike.audio import rms
from spike.robot_audio import RobotAudio


async def main() -> None:
    with ReachyMini() as mini:
        audio = RobotAudio(mini.media)
        audio.start()
        try:
            levels, start = [], time.monotonic()
            async for frame in audio.frames():
                levels.append(rms(frame))
                if time.monotonic() - start > 3:
                    break
            print(f"mic: {len(levels)} frames, max rms {max(levels):.3f}")
            tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.float32)
            audio.play(tone, time.monotonic())
            await asyncio.sleep(0.5)
            print("speaking:", audio.is_speaking(time.monotonic()))
            audio.clear(time.monotonic())
            print("cleared; speaking:", audio.is_speaking(time.monotonic()))
        finally:
            audio.stop()


if __name__ == "__main__":
    asyncio.run(main())
