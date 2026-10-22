"""Generate storyboard illustrations with SDXL + OpenPose ControlNet + IPAdapter.

Pipeline per storyboard frame:

  1. render the OpenPose skeleton from the parametric pose model (fixed camera)
  2. generate a portrait of the patient following that skeleton
  3. cut her out by background distance (flat studio background)
  4. save the cutout; `composite.py` normalises and places it in the scene

The same seed, prompt and IPAdapter reference are used for every frame, so the
patient, clothing and style stay consistent.

Usage:
    tools/ComfyUI/.venv/bin/python tools/ComfyUI/main.py --port 8188 &
    .venv/bin/python tools/gen/gen_frames.py --exercise wall-climb
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
sys.path.insert(0, str(ROOT))

import comfy  # noqa: E402
import pose_render  # noqa: E402

COMFY_INPUT = ROOT / "tools" / "ComfyUI" / "input"

PROMPT = (
    "full body flat illustration of a woman standing in profile facing right, "
    "wearing a teal long-sleeve top and dark trousers, dark hair in a low bun, "
    "calm friendly expression, looking straight ahead, "
    "{action}, "
    "plain solid light warm grey studio background, soft shadow, clean vector look, no text"
)
ACTION = {
    "intro": "arms relaxed at her sides",
    "stance": "her right arm extended forward with the hand flat against a wall at shoulder height",
    "hands": "her right arm extended forward with the hand flat against a wall at shoulder height",
    "climb": "her right arm raised forward and up, fingers on the wall, a little above shoulder height",
    "high": "her right arm raised forward and up, fingers high on the wall above her shoulder",
    "hold": "her right arm reaching up with the hand flat on the wall above her head",
    "lower": "her right arm extended forward with the hand flat against the wall at shoulder height",
    "close": "arms relaxed at her sides",
}
NEGATIVE = (
    "walking, striding, photograph, 3d render, text, watermark, logo, extra limbs, extra arms, "
    "deformed hands, fused fingers, missing arm, cropped, out of frame, nude, cluttered background, "
    "holding object, bar, pole"
)


def key_background(raw: Image.Image, threshold: float = 26.0) -> Image.Image:
    """Cut the figure out of a flat studio background.

    The background is a smooth vertical gradient, so it is estimated per row from
    the outer columns and removed by colour distance. This is far more reliable
    on flat illustrations than a segmentation network, which occasionally drops
    a thin raised arm.
    """
    rgb = np.asarray(raw.convert("RGB")).astype(np.float32)
    edge = np.concatenate([rgb[:, :20], rgb[:, -20:]], axis=1)
    bg = np.median(edge, axis=1)[:, None, :]
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    mask = Image.fromarray(((dist > threshold) * 255).astype("uint8"))
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(5))
    mask = mask.filter(ImageFilter.GaussianBlur(1.0))
    out = raw.convert("RGBA")
    out.putalpha(mask)
    return out


def _skeleton_dir(work: Path, name: str) -> Path:
    """Render a skeleton and copy it into ComfyUI's input directory.

    ComfyUI caches by filename, so the copy carries a content hash; reusing a
    bare name makes it silently serve a stale pose.
    """
    src = work / "persons" / "skeletons" / f"{name}.png"
    pose_render.render(name, src)
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:8]
    dst = COMFY_INPUT / f"pose_{name}_{digest}.png"
    shutil.copyfile(src, dst)
    return Path(dst.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise", default="wall-climb")
    parser.add_argument("--work", default=None, help="default: build/<exercise>")
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--steps", type=int, default=26)
    parser.add_argument("--control-strength", type=float, default=1.05)
    parser.add_argument("--ipadapter-weight", type=float, default=0.55)
    parser.add_argument("--reference", default=None,
                        help="IPAdapter reference image (default: <work>/persons/reference.png)")
    parser.add_argument("--only", nargs="*", default=None, help="frame ids, e.g. 04 05")
    args = parser.parse_args()

    if not COMFY_INPUT.exists():
        raise SystemExit(
            f"ComfyUI input directory not found: {COMFY_INPUT}\n"
            "Install ComfyUI under tools/ComfyUI (see README section 'GPU (optional)')."
        )

    work = Path(args.work) if args.work else ROOT / "build" / args.exercise
    reference = Path(args.reference) if args.reference else work / "persons" / "reference.png"
    if not reference.exists():
        reference = None
        print("warning: no IPAdapter reference; frames may drift in appearance")

    storyboard = json.loads((ROOT / "storyboards" / f"{args.exercise}.json").read_text())
    raw_dir = work / "persons" / "raw"
    out_dir = work / "persons"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    for frame in storyboard["frames"]:
        if args.only and frame["id"] not in args.only:
            continue
        pose = frame["pose"]
        control = _skeleton_dir(work, pose)
        graph = comfy.graph(
            PROMPT.format(action=ACTION[pose]), NEGATIVE,
            width=pose_render.GEN_W, height=pose_render.GEN_H,
            steps=args.steps, cfg=6.0, seed=args.seed,
            control_image=str(control), control_strength=args.control_strength,
            ipadapter_image=reference.name if reference else None,
            ipadapter_weight=args.ipadapter_weight,
        )
        raw = raw_dir / f"frame-{frame['id']}.png"
        comfy.generate(graph, raw)
        cut = key_background(Image.open(raw))
        cut.save(out_dir / f"person-{frame['id']}.png")
        meta[frame["id"]] = {"pose": pose, "raw": str(raw.relative_to(work)),
                             "cutout": f"person-{frame['id']}.png"}
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        print(f"frame {frame['id']} {pose} done")


if __name__ == "__main__":
    main()
