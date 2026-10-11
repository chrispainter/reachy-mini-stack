"""Body calibration measured on the robot (see voice/BODY_NOTES.md)."""

# DoA angle (radians) reported when the speaker is straight in front of Reachy.
# Measured: steady 1.571-1.623 rad with the speaker in front (pi/2).
DOA_FRONT_RAD = 1.5708
# +1.0 or -1.0 so that yaw = DOA_SIGN * (angle - DOA_FRONT_RAD) turns toward the speaker
# (positive yaw = Reachy's left). Measured: the angle rises toward Reachy's left (~2.0 rad).
DOA_SIGN = 1.0
# Largest body turn toward a voice (radians, ~50 degrees).
MAX_TURN_RAD = 0.87
# Antenna joint targets [right, left] in radians.
# Listen: the user picked [-0.4, 0.4] as the perked/listening pose.
ANTENNA_LISTEN = [-0.4, 0.4]
# Rest: none of the probed poses looked relaxed to the user, so neutral.
ANTENNA_REST = [0.0, 0.0]
# DoA probe gave usable left/front/right readings, so turning toward a voice stays on.
DOA_ENABLED = True
# Speech-wobble offset scale (x, y, z, roll, pitch, yaw); z/pitch reduced: user saw too much bobbing.
WOBBLE_SCALE = (1.0, 1.0, 0.35, 1.0, 0.35, 1.0)
