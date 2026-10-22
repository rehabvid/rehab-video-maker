"""Render OpenPose (COCO-18) skeletons from the storyboard pose model.

These skeletons are the ControlNet input: they pin the posture (which arm is
raised, how high, where the hand meets the wall) while the diffusion model
supplies the drawing.

One fixed transform maps the 1280x720 design space to the 832x1216 generation
canvas for every pose, so the patient is the same size and in the same place in
all frames.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rehab_slideshow.illustrations import POSES, _arm_pose  # noqa: E402

GEN_W, GEN_H = 896, 1216
K = 3.0
TX, TY = -1054.0, -693.0

# COCO-18 joint order
NOSE, NECK, RSHO, RELB, RWRI, LSHO, LELB, LWRI, RHIP, RKNEE, RANKLE, \
    LHIP, LKNEE, LANKLE, REYE, LEYE, REAR, LEAR = range(18)

LIMBS = [
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10),
    (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]
COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 255), (255, 0, 170),
]
JOINT_COLOR = (0, 0, 255)


def _joints(pose_name: str) -> dict[int, tuple[float, float]]:
    pose = POSES[pose_name]
    reach = pose["reach"]

    head = (498.0, 292.0)
    neck = (506.0, 330.0)
    r_sho = (516.0, 356.0)
    l_sho = (494.0, 352.0)
    r_hip = (494.0, 486.0)
    l_hip = (474.0, 486.0)

    if pose["arm"] == "wall":
        elbow, wrist = _arm_pose(reach)
    else:
        elbow, wrist = (528.0, 420.0), (524.0, 480.0)

    l_elb = (479.0, 420.0)
    l_wri = (483.0, 478.0)

    return {
        NOSE: (head[0] + 24, head[1] + 8),
        NECK: neck,
        REYE: (head[0] + 14, head[1] + 2),
        LEYE: (head[0] + 8, head[1] + 1),
        REAR: (head[0] + 2, head[1] + 6),
        LEAR: (head[0] - 4, head[1] + 6),
        RSHO: r_sho,
        RELB: elbow,
        RWRI: wrist,
        LSHO: l_sho,
        LELB: l_elb,
        LWRI: l_wri,
        RHIP: r_hip,
        RKNEE: (498.0, 548.0),
        RANKLE: (502.0, 604.0),
        LHIP: l_hip,
        LKNEE: (486.0, 548.0),
        LANKLE: (490.0, 604.0),
    }


def to_gen(point: tuple[float, float]) -> tuple[float, float]:
    return point[0] * K + TX, point[1] * K + TY


def render(pose_name: str, out_path: Path, stick: int = 7, radius: int = 5) -> Path:
    img = Image.new("RGB", (GEN_W, GEN_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    j = {k: to_gen(v) for k, v in _joints(pose_name).items()}

    for (a, b), color in zip(LIMBS, COLORS):
        draw.line([j[a], j[b]], fill=color, width=stick)
    for point in j.values():
        x, y = point
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=JOINT_COLOR)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    import sys

    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/pose-previews")
    for name in POSES:
        print(render(name, out_dir / f"{name}.png"))
