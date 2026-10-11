# Body probe notes

Measured on the robot with a person present (`tools/body_probe.py`). Constants live in
`reachy_voice/body_calibration.py`.

## wake
`wake_up` took 2.6 s (motors enabled first).

## sleep
`goto_sleep` took 5.2 s; motors are disabled afterwards.

## noise (no person)
Mic RMS p95: 0.0059 with the head still vs 0.131 while moving (about 22x). The
listening-stillness rule is strongly confirmed: do not move the head while listening.

## doa
The probe's first version crashed (`rms_for` over 0.2 s could collect zero samples), so
measurements used a loop polling `get_DoA` every 0.25 s while the user spoke from each side:
- left: mostly 1.99-2.08 rad, mixed with ~1.55-1.6
- front: steady 1.571-1.623 rad
- right: 1.47-1.55 rad, plus readings around 0.61-0.65

So front = 1.5708 (pi/2) and the angle increases toward Reachy's left (`DOA_SIGN = +1`).
Single readings are noisy and often read "front". Recommendation: use the median of
speech-flagged readings over the last ~1.5 s, not a single sample.

## antennas
Poses tried: [0,0], [0.4,-0.4], [-0.4,0.4], [0.3,0.3], [-0.3,-0.3]. The user found
[-0.4, 0.4] reads as perked/listening; none looked relaxed, so rest is neutral [0, 0].

## emotions
Played silently (`sound=False`): thinking -> thoughtful1 5.9 s; welcoming -> welcoming2
4.3 s; goodbye -> loving1 5.6 s. Decision: expressions stay always silent.

## track
Daemon face tracking at weight 0.6 detects the face after ~2-3 s and follows it as the
user moves. The user found tracking itself fine.

## wobble
Speech-driven wobble produced too much up/down bobbing (tracking alone: none; wobble
alone: bobbing). Scaling the speech offsets (x, y, z, roll, pitch, yaw) by
(1, 1, 0.35, 1, 0.35, 1) was judged better, hence `WOBBLE_SCALE`. The test tone was 3 Hz
amplitude-modulated, which likely exaggerates the effect relative to real speech.
