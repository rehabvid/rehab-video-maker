#!/usr/bin/env python3
"""Render a QR PNG as a compact block QR for a remote TUI.

The WeChat login page can fail to render its embedded QR even though the
session UUID and image URL are present.  ``wechat_channels_upload.js`` saves
that image; this helper turns it into a terminal-safe 2x2-module rendering.

One character cell represents a 2x2 module block.  White modules use a small
dot so leading quiet-zone space is not stripped by TUI renderers.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

WHITE = (0, 0, 0, 0)
QUADRANTS = {
    WHITE: "·",
    (1, 0, 0, 0): "▘",
    (0, 1, 0, 0): "▝",
    (0, 0, 1, 0): "▖",
    (0, 0, 0, 1): "▗",
    (1, 1, 0, 0): "▀",
    (0, 0, 1, 1): "▄",
    (1, 0, 1, 0): "▌",
    (0, 1, 0, 1): "▐",
    (1, 1, 1, 0): "▛",
    (1, 1, 0, 1): "▜",
    (1, 0, 1, 1): "▙",
    (0, 1, 1, 1): "▟",
    (1, 1, 1, 1): "█",
    (1, 0, 0, 1): "▚",
    (0, 1, 1, 0): "▞",
}


def _module_count(size: int) -> int:
    """Pick a valid QR version whose module size divides the content box."""
    valid = [n for n in range(21, 178, 4) if size % n == 0]
    if valid:
        return max(valid)
    # Fallback for anti-aliased / resized images: nearest valid version.
    guess = max(21, min(177, round(size / 10)))
    return min(range(21, 178, 4), key=lambda n: abs(n - guess))


def _matrix(path: Path, quiet: int = 2) -> list[list[bool]]:
    image = Image.open(path).convert("L")
    mask = image.point(lambda value: 255 if value < 128 else 0)
    bbox = mask.getbbox()
    if not bbox:
        raise ValueError(f"no dark pixels in {path}")
    x0, y0, x1, y1 = bbox
    size = min(x1 - x0, y1 - y0)
    n = _module_count(size)
    step = size / n
    rows: list[list[bool]] = []
    for row in range(n):
        values: list[bool] = []
        y = int(y0 + (row + 0.5) * step)
        for col in range(n):
            x = int(x0 + (col + 0.5) * step)
            values.append(image.getpixel((x, y)) < 128)
        rows.append(values)
    if quiet > 0:
        width = n + quiet * 2
        rows = [[False] * width for _ in range(quiet)] + [
            [False] * quiet + row + [False] * quiet for row in rows
        ] + [[False] * width for _ in range(quiet)]
    return rows


def render(path: Path, quiet: int = 2) -> str:
    matrix = _matrix(path, quiet)
    height = len(matrix)
    width = len(matrix[0])
    if height % 2:
        matrix.append([False] * width)
        height += 1
    if width % 2:
        matrix = [row + [False] for row in matrix]
        width += 1
    lines: list[str] = []
    for y in range(0, height, 2):
        line: list[str] = []
        for x in range(0, width, 2):
            key = (
                int(matrix[y][x]),
                int(matrix[y][x + 1]),
                int(matrix[y + 1][x]),
                int(matrix[y + 1][x + 1]),
            )
            line.append(QUADRANTS[key])
        lines.append("".join(line))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="QR PNG saved from the WeChat login iframe")
    parser.add_argument("--quiet", type=int, default=2,
                        help="quiet-zone modules per side (default: 2)")
    args = parser.parse_args(argv)
    print(render(Path(args.image).expanduser(), args.quiet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
