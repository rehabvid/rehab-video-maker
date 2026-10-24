#!/usr/bin/env python3
"""Render a 1280x720 YouTube thumbnail from the slide list.

The thumbnail is intentionally a designed title card, not a frame grab: large
title text, a short kicker, and the podcast/episode image blurred behind it.

Usage::

    python3 scripts/thumbnail.py --slides build/ep01/slides.json \
        --out out/ep01/thumbnail.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

SHARED = Path(__file__).resolve().parents[2] / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lib import load_json, render_title_card  # noqa: E402

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
OUT_SIZE = (1280, 720)


def _first_image(slides: dict, root: Path) -> Path | None:
    for shot in slides.get("shots", []):
        for key in ("visual", "background"):
            value = shot.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = root / path
            if path.exists() and path.suffix.lower() in IMAGE_SUFFIXES:
                return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--title")
    parser.add_argument("--subtitle")
    parser.add_argument("--kicker")
    parser.add_argument("--background", help="still image; defaults to the first slide visual")
    args = parser.parse_args(argv)

    slides_path = Path(args.slides)
    try:
        data = load_json(slides_path)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {slides_path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("error: slide list must be a JSON object", file=sys.stderr)
        return 1

    title_shots = [s for s in data.get("shots", []) if s.get("kind") == "title"]
    title_shot = title_shots[0] if title_shots else {}
    title = args.title or data.get("title") or title_shot.get("on_screen") or "Podcast commentary"
    subtitle = (
        args.subtitle
        or title_shot.get("subtitle")
        or "A podcast commentary"
    )
    kicker = args.kicker or title_shot.get("kicker") or "PODCAST COMMENTARY"
    background = Path(args.background).expanduser() if args.background else _first_image(
        data, Path(args.root)
    )

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    master = out.with_name(out.stem + ".master.png")
    try:
        render_title_card(master, str(title), str(subtitle), str(kicker), background)
        with Image.open(master) as image:
            image.convert("RGB").resize(OUT_SIZE, Image.LANCZOS).save(out, "PNG")
    except (OSError, ValueError) as exc:
        print(f"error: cannot render thumbnail: {exc}", file=sys.stderr)
        return 1
    finally:
        master.unlink(missing_ok=True)

    print(f"wrote {out} ({OUT_SIZE[0]}x{OUT_SIZE[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
