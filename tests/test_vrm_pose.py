"""The VRM pose track must stay inside the rig's reach and the storyboard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools/gen"))

import vrm_pose  # noqa: E402

ARM_REACH = 0.2013 + 0.2252  # me.vrm upper arm + forearm
SHOULDER_Y = 1.283
SHOULDER_Z = -0.027


def _cue(frame: str, start: float, duration: float):
    class Cue:
        pass

    cue = Cue()
    cue.frame = frame
    cue.frame_start = start
    cue.frame_duration = duration
    return cue


def _frames():
    return [
        {"id": "01", "pose": "intro"},
        {"id": "02", "pose": "stance"},
        {"id": "03", "pose": "hands"},
        {"id": "04", "pose": "climb"},
        {"id": "05", "pose": "high"},
        {"id": "06", "pose": "hold"},
        {"id": "07", "pose": "lower"},
        {"id": "08", "pose": "close"},
        {"id": "09", "pose": "close"},
    ]


class VrmPoseTest(unittest.TestCase):
    def setUp(self):
        frames = _frames()
        timeline = []
        t = 0.0
        for f in frames:
            duration = 10.0
            timeline.append(_cue(f["id"], t, duration))
            t += duration
        self.track = vrm_pose.build_track(frames, timeline)
        self.end = t

    def test_track_is_monotonic_and_covers_the_timeline(self):
        times = [e["t"] for e in self.track]
        self.assertEqual(times, sorted(times))
        self.assertGreaterEqual(times[-1], self.end - 1e-6)
        self.assertGreaterEqual(times[0], 0.0)

    def test_wrist_targets_stay_within_the_arm(self):
        for event in self.track:
            for side in ("right", "left"):
                target = event["pose"].get(side, {})
                if "y" not in target:
                    continue
                dy = target["y"] - SHOULDER_Y
                dz = target["z"] - SHOULDER_Z
                distance = (dy * dy + dz * dz) ** 0.5
                self.assertLessEqual(distance, ARM_REACH * 0.999,
                                     f"unreachable target at t={event['t']}")

    def test_climb_ends_higher_than_it_starts_then_returns(self):
        climb = [e for e in self.track if 10.0 <= e["t"] <= 40.0]
        heights = [e["pose"]["right"].get("y") for e in climb
                   if "y" in e["pose"].get("right", {})]
        self.assertTrue(heights)
        self.assertGreater(max(heights), vrm_pose.ON_WALL_Y + 0.1)
        self.assertAlmostEqual(heights[-1], vrm_pose.ON_WALL_Y, places=2)

    def test_no_pose_before_the_storyboard_allows_it(self):
        # frame 01 is intro: the hands stay off the wall for its whole cue
        for event in self.track:
            if event["t"] < 10.0 - 1e-6:
                self.assertNotIn("y", event["pose"].get("right", {}))


if __name__ == "__main__":
    unittest.main()
