"""Pose track for the full-body VRM patient.

The vector renderer draws each storyboard pose once. The VRM renderer needs a
timeline: wrist targets on the wall plane, in metres, at absolute seconds. This
module turns the storyboard poses into that track. It never invents a pose the
storyboard does not ask for; it only times the transitions.

Geometry (side view, model faces +Z, camera on its right):

* the wall plane is ``Z_WALL`` metres in front of the hips,
* on the wall the wrist sits ``WRIST_Z``, the palm just short of the surface,
* ``ON_WALL_Y`` is shoulder height, ``HIGH_Y`` the comfortable top of the
  climb. Both stay inside the arm's 0.426 m reach, so the IK never has to
  hyperextend the elbow to keep contact.
"""

from __future__ import annotations

import json
from pathlib import Path

Z_WALL = 0.30
WRIST_Z = 0.200
ON_WALL_Y = 1.24
LEFT_REST_Y = 1.16  # unaffected hand rests a little lower
HIGH_Y = 1.50

STAND_RIGHT = {"dir": [-0.10, -1.0, 0.10], "fore": [-0.10, -1.0, 0.16]}
STAND_LEFT = {"dir": [0.10, -1.0, 0.10], "fore": [0.10, -1.0, 0.16]}


def _stand() -> dict:
    return {"right": dict(STAND_RIGHT), "left": dict(STAND_LEFT)}


def _wall(right_y: float, left_y: float = LEFT_REST_Y, lean: float = 0.0,
          head: float = 0.0) -> dict:
    return {
        "right": {"y": right_y, "z": WRIST_Z},
        "left": {"y": left_y, "z": WRIST_Z},
        "lean": lean,
        "headTurn": head,
    }


def _climb_steps(t: float, y0: float, y1: float, steps: int = 5,
                 step_time: float = 0.30, hold: float = 0.10) -> tuple[list, float]:
    """Finger-walk upward: five small targets, each held briefly."""
    events = []
    span = y1 - y0
    for i in range(1, steps + 1):
        y = y0 + span * i / steps
        events.append((t, _wall(y0 + span * (i - 1) / steps, head=0.05)))
        events.append((t + step_time, _wall(y, head=0.05)))
        t += step_time + hold
    return events, t


def build_track(frames: list[dict], timeline: list, fps: int = 30) -> list[dict]:
    """Return ``[{t, pose}, ...]`` for the VRM renderer."""
    by_id = {f["id"]: f for f in frames}
    events: list[dict] = []
    state = _stand()

    def put(t: float, pose: dict) -> None:
        nonlocal state
        state = pose
        events.append({"t": round(max(0.0, t), 3), "pose": pose})

    for index, cue in enumerate(timeline):
        frame = by_id.get(cue.frame, {})
        pose_name = frame.get("pose", "stance")
        start = cue.frame_start
        duration = cue.frame_duration
        end = start + duration
        ramp = 1.1 if index else 0.6

        if pose_name in ("intro", "close"):
            begin = state
            put(start, begin)
            put(start + ramp, _stand())
            continue

        if pose_name in ("stance", "hands"):
            begin = state
            put(start, begin)
            lean = -0.012 if pose_name == "hands" else 0.0
            # both hands at shoulder level before the climb starts
            put(start + ramp, _wall(ON_WALL_Y, left_y=ON_WALL_Y, lean=lean))
            continue

        if pose_name == "climb":
            if not state.get("right", {}).get("y"):
                put(start, _wall(ON_WALL_Y))
            cycle = 3.3
            cycles = max(1, int((duration - ramp) // cycle))
            t = start + ramp * 0.6
            for _ in range(cycles):
                steps, t = _climb_steps(t, ON_WALL_Y, HIGH_Y - 0.02)
                put(t, _wall(HIGH_Y - 0.02))
                t += 0.45
                put(t, _wall(HIGH_Y - 0.02))
                t += 0.75
                put(t, _wall(ON_WALL_Y + 0.02))
                t += 0.55
            put(max(end - 0.3, t), _wall(ON_WALL_Y))
            continue

        if pose_name == "high":
            put(start, state)
            put(start + 1.2, _wall(HIGH_Y, head=0.10))
            continue

        if pose_name == "hold":
            put(start, _wall(HIGH_Y, head=0.10))
            # settle, not a statue: three shallow breaths at the top
            t = start + 0.8
            while t < end - 0.4:
                put(t, _wall(HIGH_Y - 0.004, head=0.10))
                put(t + 1.3, _wall(HIGH_Y, head=0.08))
                t += 2.6
            put(end, _wall(HIGH_Y, head=0.08))
            continue

        if pose_name == "lower":
            begin = state
            put(start, begin)
            # three deliberate steps back down, then rest on the wall
            t = start + 0.8
            for i in range(3):
                y = HIGH_Y - (HIGH_Y - ON_WALL_Y) * (i + 1) / 3
                put(t, _wall(y, head=0.08))
                t += 0.9
            put(min(t + 0.4, end), _wall(ON_WALL_Y))
            continue

        put(start, state)

    # final idempotent guard: the last cue must end on a defined pose
    if events and events[-1]["t"] < timeline[-1].frame_start + timeline[-1].frame_duration:
        events.append({"t": timeline[-1].frame_start + timeline[-1].frame_duration,
                       "pose": state})
    return events


def write_track(path: Path, frames: list[dict], timeline: list, fps: int = 30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_track(frames, timeline, fps), indent=1) + "\n")
    return path
