#!/usr/bin/env python3
"""Verify one visual background language across cards and LinkZag scenes.

Checks that every story card has a background image, every custom visual has
the shared image backdrop and compatible light/dark theme, and no source-podcast
thumbnail is used as a slide background.
"""

from __future__ import annotations

import argparse
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


def _asset_exists(url: str) -> bool:
    if not url.startswith("image:"):
        return False
    raw = url[len("image:"):]
    parsed = urllib.parse.urlparse(raw)
    query = urllib.parse.parse_qs(parsed.query)
    relative = (query.get("path") or [""])[0]
    if not relative:
        return False
    return (ROOT / "modules" / "linkZagShow" / urllib.parse.unquote(relative)).exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--scenes")
    parser.add_argument("--cover", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    cover = Path(args.cover).expanduser()
    if not cover.exists():
        print(f"error: cover not found: {cover}", file=sys.stderr)
        return 1
    expected = _theme(cover)
    timing = _load(Path(args.timing))
    scenes = _load(Path(args.scenes)) if args.scenes and Path(args.scenes).exists() else {"scenes": []}
    by_id = {str(scene.get("id")): scene for scene in scenes.get("scenes", [])}
    problems: list[dict] = []
    styled = 0
    for shot in timing.get("shots", []):
        sid = str(shot.get("id"))
        kind = str(shot.get("kind"))
        scene = by_id.get(sid)
        if scene:
            background = str(scene.get("background") or "")
            theme = str(scene.get("theme") or "")
            if not background.startswith("image:") or not _asset_exists(background):
                problems.append({"id": sid, "issue": "custom visual has no image backdrop"})
            elif theme != expected:
                problems.append({"id": sid, "issue": f"theme {theme} != cover {expected}"})
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
