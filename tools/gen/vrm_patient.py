"""Render the full-body VRM patient layer for one build.

Wraps ``tools/vrm/render_rehab.mjs``. The scene is calibrated to the same
1280x720 design space as ``rehab_slideshow.illustrations``: floor line 612,
wall line 596, 0.00448 m per pixel. The alpha PNGs are composited under the
text overlay by ``rehab_slideshow.video``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DESIGN_W, DESIGN_H = 1280, 720
FLOOR_PX = 612
WALL_PX = 596
METRES_PER_PX = 0.00448
DEFAULT_VRM = "assets/avatar/me.vrm"


def available(root: Path) -> bool:
    return (root / "tools/vrm/render_rehab.mjs").exists() and shutil.which("node") is not None


def render(root: Path, track: Path, out_dir: Path, fps: int = 30,
           vrm: str = DEFAULT_VRM, k: float = METRES_PER_PX,
           floor: int = FLOOR_PX, wall: int = WALL_PX) -> Path:
    model = Path(vrm)
    if not model.is_absolute():
        model = root / model
    if not model.exists():
        raise FileNotFoundError(f"VRM model not found: {model}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("p-*.png"):
        stale.unlink()
    cmd = [
        "node", str(root / "tools/vrm/render_rehab.mjs"),
        "--vrm", str(model),
        "--track", str(track),
        "--out", str(out_dir),
        "--fps", str(fps),
        "--w", str(DESIGN_W), "--h", str(DESIGN_H),
        "--k", str(k),
        "--floor", str(floor), "--wall", str(wall),
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "VRM patient render failed:\n" + (result.stderr or result.stdout)[-4000:]
        )
    frames = sorted(out_dir.glob("p-*.png"))
    if not frames:
        raise RuntimeError("VRM patient render produced no frames")
    return out_dir
