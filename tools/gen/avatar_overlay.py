#!/usr/bin/env python3
"""Animated 2D host overlay from a flat SVG portrait.

The avatar is composited bottom-right; the caller sets the square edge from the
video orientation. Animation is cheap and deterministic: idle bob, periodic
blink, and mouth openness driven by the narration envelope. No VRM or diffusion.

Output is a VP9 WebM with alpha, ready for ffmpeg overlay.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parent))
import visemes as viseme_track

ROOT = Path(__file__).resolve().parents[2]
SVG_SHOT = Path(__file__).resolve().parent / "svg_shot.js"

# Facial coordinates in the 1254x1254 source portrait
EYE_L = (515, 483)
EYE_R = (735, 483)
MOUTH = (630, 742)
MOUTH_W = 190


def _raster(svg: Path, png: Path, size: int) -> None:
    subprocess.run(["node", str(SVG_SHOT), str(svg), str(png), str(size)], check=True)


def _mouth(draw: ImageDraw.ImageDraw, viseme: str | None, x: int, y: int, s: float) -> None:
    import math
    lip = (196, 120, 108, 255)
    lip_dark = (150, 82, 72, 255)
    inner = (60, 26, 26, 255)
    teeth = (242, 236, 226, 255)
    tongue = (150, 78, 78, 255)
    if not viseme:
        w = int(64 * s)
        draw.line([x - w, y, x + w, y], fill=lip_dark, width=max(1, int(3 * s)))
        return

    w, h = {"aa": (98, 42), "ih": (110, 16), "ee": (106, 22),
            "oh": (74, 38), "ou": (58, 32)}.get(viseme, (88, 26))
    w, h = int(w * s), int(h * s)
    h = max(3, h)
    n = 18

    def curve(width: int, top: float, bottom: float, corner_lift: float):
        upper, lower = [], []
        for i in range(n + 1):
            t = i / n
            xx = x - width + 2 * width * t
            arch = math.sin(math.pi * t) ** 0.7
            upper.append((xx, y - top * arch + corner_lift * (1 - arch)))
            lower.append((xx, y + bottom * arch + corner_lift * (1 - arch)))
        return upper, lower

    lift = -0.10 * h if viseme in {"ee", "ih"} else 0.0
    # outer lips
    up, low = curve(w, 0.55 * h, 0.80 * h, lift)
    draw.polygon(up + list(reversed(low)), fill=lip)
    # inner mouth
    iu, il = curve(int(w * 0.86), 0.28 * h, 0.52 * h, lift)
    draw.polygon(iu + list(reversed(il)), fill=inner)
    # teeth along the upper inner edge
    if viseme in {"aa", "ee", "ih"}:
        tu, tl = curve(int(w * 0.68), 0.28 * h, 0.10 * h, lift)
        draw.polygon(tu + list(reversed(tl)), fill=teeth)
    # tongue for open vowels
    if viseme in {"aa", "oh", "ou"}:
        tw, th = max(2, int(w * 0.42)), max(2, int(h * 0.30))
        draw.ellipse([x - tw, y + int(h * 0.18) - th, x + tw, y + int(h * 0.18) + th], fill=tongue)
    # lip lines
    draw.line(up, fill=lip_dark, width=max(1, int(2 * s)), joint="curve")
    draw.line(low, fill=lip_dark, width=max(1, int(2 * s)), joint="curve")


def _envelope(audio: Path, fps: int, frames: int) -> np.ndarray:
    try:
        with wave.open(str(audio), "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        window = max(1, rate // fps)
        values = []
        for index in range(frames):
            chunk = data[index * window:(index + 1) * window]
            values.append(float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0)
        values = np.array(values)
        peak = np.percentile(values, 95) or 1.0
        return np.clip(values / peak, 0, 1)
    except Exception:  # noqa: BLE001
        return np.zeros(frames)


def render(svg: Path, audio: Path, out: Path, height: int, fps: int = 12,
           visemes: list[str | None] | None = None) -> Path:
    with tempfile.TemporaryDirectory(prefix="avatar-") as tmpdir:
        tmp = Path(tmpdir)
        base_png = tmp / "base.png"
        _raster(svg, base_png, 1254)
        render_h = max(height, int(height * 2))
        base = Image.open(base_png).convert("RGBA").resize((render_h, render_h), Image.LANCZOS)
        frames = max(1, int(round(_audio_duration(audio) * fps)))
        env = _envelope(audio, fps, frames)
        # Natural blink: 3-5s apart, 0.18s closure, ~12% double blinks.
        rng = random.Random(20261105)
        blink_frames: set[int] = set()
        hold = max(1, round(0.18 * fps))
        t = 1.8 + rng.random() * 2.0
        while int(t * fps) < frames:
            start = int(t * fps)
            blink_frames.update(range(start, min(frames, start + hold)))
            if rng.random() < 0.12:
                s2 = start + hold + round(0.12 * fps)
                blink_frames.update(range(s2, min(frames, s2 + hold)))
            t += 3.0 + rng.random() * 2.0
        for index in range(frames):
            frame = Image.new("RGBA", (render_h, render_h), (0, 0, 0, 0))
            bob = 0  # keep the host anchored; no vertical drift
            frame.alpha_composite(base, (0, bob))
            draw = ImageDraw.Draw(frame)
            if index in blink_frames:
                for eye in (EYE_L, EYE_R):
                    x = int(eye[0] / 1254 * render_h)
                    y = int((eye[1] + bob) / 1254 * render_h)
                    w = max(3, int(36 / 1254 * render_h))
                    h = max(2, int(25 / 1254 * render_h))
                    # eyelid: skin-toned patch shaped like the eye, then lash arc
                    draw.ellipse([x - w, y - h, x + w, y + h], fill=(232, 184, 146, 255))
                    draw.arc([x - w, y - h, x + w, y + h], 200, 340,
                             fill=(88, 60, 48, 255), width=max(1, render_h // 260))
            # syllable viseme, falling back to the envelope
            vis = visemes[index] if visemes and index < len(visemes) else None
            if vis is None and env[index] > 0.18:
                vis = "aa"
            mx = int(MOUTH[0] / 1254 * render_h)
            my = int((MOUTH[1] + bob) / 1254 * render_h)
            _mouth(draw, vis, mx, my, render_h / 1254 * (0.78 + 0.22 * env[index]))
            frame.resize((height, height), Image.LANCZOS).save(tmp / f"f-{index:05d}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-framerate", str(fps), "-i", str(tmp / "f-%05d.png"),
            "-c:v", "png", "-pix_fmt", "rgba", "-an", str(out),
        ], check=True)
    return out


def _audio_duration(path: Path) -> float:
    try:
        return float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ], text=True).strip())
    except Exception:  # noqa: BLE001
        return 12.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args(argv)
    print(render(Path(args.svg), Path(args.audio), Path(args.out), args.height, args.fps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
