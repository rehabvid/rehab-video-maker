"""Normalise and place the generated patient cutouts into the 1280x720 scene.

The diffusion model does not keep an exact scale from frame to frame, so each
cutout is measured (head top, feet, pelvis) and placed with the same body
height and floor line. That keeps her from breathing in and out between shots.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DESIGN = (1280, 720)
TARGET_HEIGHT = 341  # head top to floor, design pixels
FLOOR_Y = 606
PELVIS_X = 492



def clean_alpha(img: Image.Image) -> Image.Image:
    a = np.array(img)
    alpha = a[:, :, 3].astype(np.float32)
    alpha[alpha < 45] = 0
    alpha[alpha > 235] = 255
    # small feather so the cutout does not look pasted
    from PIL import ImageFilter

    soft = Image.fromarray(alpha.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    a[:, :, 3] = np.asarray(soft)
    return Image.fromarray(a)


def measure(img: Image.Image) -> dict:
    a = np.array(img)[:, :, 3]
    rows = np.where(a.max(axis=1) > 40)[0]
    cols = np.where(a.max(axis=0) > 40)[0]
    widths = (a > 60).sum(axis=1)
    head_top = next((y for y in range(a.shape[0]) if widths[y] > 30), rows[0])
    bottom = rows[-1]
    height = bottom - head_top
    # pelvis = horizontal centre of the lower third (legs), robust against arms
    legs = a[bottom - int(height * 0.33): bottom]
    leg_cols = np.where(legs.max(axis=0) > 60)[0]
    pelvis = (leg_cols.min() + leg_cols.max()) / 2 if len(leg_cols) else (cols.min() + cols.max()) / 2
    return {
        "head_top": int(head_top),
        "bottom": int(bottom),
        "height": int(height),
        "pelvis": float(pelvis),
    }


def place(img: Image.Image, info: dict) -> Image.Image:
    scale = TARGET_HEIGHT / info["height"] * 2  # canvas is 2x
    fig = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.LANCZOS,
    )
    feet = info["bottom"] * scale
    pelvis = info["pelvis"] * scale
    canvas = Image.new("RGBA", (DESIGN[0] * 2, DESIGN[1] * 2), (0, 0, 0, 0))
    x = round(PELVIS_X * 2 - pelvis)
    y = round(FLOOR_Y * 2 - feet)
    canvas.paste(fig, (x, y), fig)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise", default="wall-climb")
    parser.add_argument("--work", default=None, help="default: build/<exercise>")
    args = parser.parse_args()
    work = Path(args.work) if args.work else ROOT / "build" / args.exercise
    persons = work / "persons"
    meta = json.loads((persons / "meta.json").read_text())
    report = {}
    for frame_id, item in meta.items():
        path = persons / item["cutout"]
        cut = clean_alpha(Image.open(path).convert("RGBA"))
        info = measure(cut)
        canvas = place(cut, info)
        out = persons / f"canvas-{frame_id}.png"
        canvas.save(out)
        report[frame_id] = {"pose": item["pose"], **info, "file": out.name}
        print(frame_id, item["pose"], info)
    (persons / "placements.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
