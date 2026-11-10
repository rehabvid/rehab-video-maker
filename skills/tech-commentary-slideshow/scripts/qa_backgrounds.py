#!/usr/bin/env python3
"""Verify one visual background language across cards and LinkZag scenes.

Checks that every story card has a background image, every custom visual has
the shared image backdrop and compatible light/dark theme, and no source-podcast
thumbnail is used as a slide background.
"""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

from PIL import Image
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _theme(path: Path) -> str:
    with Image.open(path) as image:
        gray = image.convert("L").resize((64, 64))
        average = sum(gray.getdata()) / 4096.0
    return "light" if average > 145 else "dark"


def _mean_luminance(path: Path) -> float:
    with Image.open(path) as image:
        gray = image.convert("L").resize((64, 64))
        return sum(gray.getdata()) / 4096.0


# A real light watercolour plate measures ~135-175; the night skyline engine
# paints ~9. The 145 cut used for theme labelling is too high for plates, so
# the dark-plate guard gets its own floor.
DARK_PLATE_LUMINANCE = 95.0


def _asset_path(url: str) -> Path | None:
    if not url.startswith("image:"):
        return None
    raw = url[len("image:"):]
    parsed = urllib.parse.urlparse(raw)
    query = urllib.parse.parse_qs(parsed.query)
    relative = (query.get("path") or [""])[0]
    if not relative:
        return None
    path = ROOT / "modules" / "linkZagShow" / urllib.parse.unquote(relative)
    return path if path.exists() else None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--scenes")
    parser.add_argument("--cover", required=True)
    parser.add_argument("--out")
    parser.add_argument(
        "--allow-custom-no-backdrop",
        action="store_true",
        help="allow LinkZag custom visuals without a photo backdrop "
             "(intentional with --no-generate)",
    )
    args = parser.parse_args(argv)

    cover = Path(args.cover).expanduser()
    if not cover.exists():
        print(f"error: cover not found: {cover}", file=sys.stderr)
        return 1
    # One channel-wide theme; matches make_scenes/story_backgrounds.
    expected = os.environ.get("LINKZAG_THEME", "light")
    # Callers pass either the composited cover or the raw plate; accept both.
    if cover.stem.endswith(".plate"):
        plate = cover
    else:
        plate = cover.with_name(cover.stem + ".plate.png")
    expected_hash = _sha(plate) if plate.exists() else None
    plate_luminance = _mean_luminance(plate) if plate.exists() else None
    timing = _load(Path(args.timing))
    scenes = _load(Path(args.scenes)) if args.scenes and Path(args.scenes).exists() else {"scenes": []}
    by_id = {str(scene.get("id")): scene for scene in scenes.get("scenes", [])}
    problems: list[dict] = []
    styled = 0
    # A dark plate under the light theme is washed to grey haze by the cream
    # card panels. Catch that here instead of in the finished video: the plate
    # must belong to the same channel-wide theme as the cards.
    if (
        expected == "light"
        and plate_luminance is not None
        and plate_luminance < DARK_PLATE_LUMINANCE
    ):
        problems.append({
            "id": "background",
            "issue": f"cover plate is a night image (mean luminance "
                     f"{plate_luminance:.0f}) but the theme is light; "
                     "regenerate it with cover.py --engine ink",
        })
    for shot in timing.get("shots", []):
        sid = str(shot.get("id"))
        kind = str(shot.get("kind"))
        scene = by_id.get(sid)
        if scene:
            background = str(scene.get("background") or "")
            theme = str(scene.get("theme") or "")
            asset = _asset_path(background)
            scene_sha = str(scene.get("background_sha") or "")
            if not background.startswith("image:"):
                if args.allow_custom_no_backdrop:
                    styled += 1
                    continue
                problems.append({"id": sid, "issue": "custom visual has no image backdrop"})
            elif theme != expected:
                problems.append({"id": sid, "issue": f"theme {theme} != cover {expected}"})
            elif asset is None:
                # render_scenes deletes the generated scene/assets for its slug
                # once the visuals are rendered. The manifest keeps the plate
                # hash, so an approved plate still verifies after cleanup.
                if expected_hash and scene_sha == expected_hash:
                    styled += 1
                else:
                    problems.append({"id": sid, "issue": "custom visual has no image backdrop"})
            elif expected_hash and _sha(asset) != expected_hash:
                problems.append({"id": sid, "issue": "backdrop is not the approved cover plate"})
            else:
                styled += 1
            continue
        if shot.get("visual_type") == "story_card":
            visual = shot.get("visual")
            if not visual or not (ROOT / str(visual)).exists():
                problems.append({"id": sid, "issue": "story card image missing"})
            else:
                styled += 1
            continue
        if kind == "broll":
            # A source b-roll is allowed once; it is not a generated card.
            continue
        if kind in {"title", "chart", "quote", "end"}:
            problems.append({"id": sid, "issue": "card has no story background"})

    report = {
        "expected_theme": expected,
        "styled_slides": styled,
        "problems": problems,
        "consistent": not problems,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
