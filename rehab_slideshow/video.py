"""Slideshow video assembly.

Camera moves are rendered frame by frame in Python with a bicubic affine
transform, then piped to FFmpeg. Doing the move here (instead of with FFmpeg's
`zoompan`) keeps motion sub-pixel smooth: `zoompan` rounds its crop origin to
whole pixels, which shows up as a 1 px twitch every few frames at slow speeds.

Cross-fades are blended in the same pass, so the timeline is exact and the
video duration always equals the sum of the storyboard frame durations.
"""

from __future__ import annotations

import math
import subprocess
from bisect import bisect_right
from pathlib import Path

from PIL import Image

from .captions import TRANSITION, Cue

FPS = 30
WIDTH, HEIGHT = 1280, 720
MASTER_SCALE = 2  # illustrations are rendered at 2560x1440
ZOOM_IN = 1.0
ZOOM_OUT = 1.05
PAN = 18.0  # design pixels of lateral drift
CRF = "19"
MAX_ZOOM = 1.05


def _ease(t: float) -> float:
    """Smoothstep: no velocity discontinuity at frame boundaries."""
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _camera(frame_index: int, progress: float) -> tuple[float, float, float]:
    """Zoom and pan for one frame at `progress` (0..1)."""
    e = _ease(progress)
    zoom_in = frame_index % 2 == 0
    zoom = ZOOM_IN + (ZOOM_OUT - ZOOM_IN) * e if zoom_in else ZOOM_OUT - (ZOOM_OUT - ZOOM_IN) * e
    direction = 1.0 if (frame_index // 2) % 2 == 0 else -1.0
    # never pan further than the zoomed window allows, otherwise the crop runs
    # off the master and leaves a black edge
    room = max(0.0, (zoom - 1.0) * WIDTH / 2 - 2)
    pan_x = direction * min(PAN, room) * (2 * e - 1)
    return zoom, pan_x, 0.0


def _render(master: Image.Image, zoom: float, pan_x: float, pan_y: float) -> Image.Image:
    """Crop a zoomed window from the master with sub-pixel precision."""
    # a maps output pixels to master pixels: master = a * output + offset
    a = MASTER_SCALE / zoom
    cx = WIDTH / 2 - (WIDTH / 2) / zoom + pan_x
    cy = HEIGHT / 2 - (HEIGHT / 2) / zoom + pan_y
    cx = min(max(cx, 0.0), WIDTH - WIDTH / zoom)
    cy = min(max(cy, 0.0), HEIGHT - HEIGHT / zoom)
    return master.transform(
        (WIDTH, HEIGHT),
        Image.AFFINE,
        (a, 0, cx * MASTER_SCALE, 0, a, cy * MASTER_SCALE),
        resample=Image.BICUBIC,
    )


def build_track(frame_paths: list[Path], timeline: list[Cue], out_path: Path,
                work_dir: Path | None = None,
                overlays: list[Path] | None = None) -> dict:
    if len(frame_paths) != len(timeline):
        raise ValueError("frames and timeline must have the same length")

    overlay_layers = [Image.open(p).convert("RGBA") for p in overlays] if overlays else None
    if overlay_layers is not None and len(overlay_layers) != len(frame_paths):
        raise ValueError("one overlay per frame is required")

    masters: list[Image.Image] = []
    for path in frame_paths:
        with Image.open(path) as img:
            master = img.convert("RGB")
        if master.width < WIDTH * MASTER_SCALE:
            master = master.resize((WIDTH * MASTER_SCALE, HEIGHT * MASTER_SCALE), Image.LANCZOS)
        masters.append(master)

    starts = [c.frame_start for c in timeline]
    end = timeline[-1].frame_start + timeline[-1].frame_duration
    total_frames = int(round(end * FPS))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
            str(out_path),
        ],
        stdin=subprocess.PIPE,
    )
    assert encoder.stdin is not None

    try:
        for n in range(total_frames):
            t = n / FPS
            index = min(bisect_right(starts, t) - 1, len(timeline) - 1)
            index = max(index, 0)
            cue = timeline[index]
            progress = (t - cue.frame_start) / cue.frame_duration
            zoom, px, py = _camera(index, progress)
            current = _render(masters[index], zoom, px, py)

            overlay_index = index
            if index > 0 and t - cue.frame_start < TRANSITION:
                alpha = (t - cue.frame_start) / TRANSITION
                prev = timeline[index - 1]
                prev_progress = (t - prev.frame_start) / prev.frame_duration
                p_zoom, p_px, p_py = _camera(index - 1, prev_progress)
                previous = _render(masters[index - 1], p_zoom, p_px, p_py)
                current = Image.blend(previous, current, alpha)
                # text stays crisp: it swaps at the midpoint instead of ghosting
                overlay_index = index - 1 if alpha < 0.5 else index

            if overlay_layers is not None:
                framed = current.convert("RGBA")
                framed.alpha_composite(overlay_layers[overlay_index])
                current = framed.convert("RGB")

            encoder.stdin.write(current.tobytes())
    finally:
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding the video track")

    return {
        "segments": len(frame_paths),
        "duration": total_frames / FPS,
        "frames": total_frames,
    }


def finish(track: Path, master_wav: Path, ass: Path, srt: Path, out_path: Path,
           expected_duration: float) -> dict:
    """Burn captions, attach narration and a soft subtitle track."""
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-i", str(track),
            "-i", str(master_wav),
            "-i", str(srt),
            "-i", str(ass),
            "-filter_complex", f"[0:v]ass='{ass.as_posix()}'[v]",
            "-map", "[v]", "-map", "1:a", "-map", "2:s",
            "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
            "-metadata", "title=Rehabilitation exercise: narrated slideshow",
            "-movflags", "+faststart",
            "-t", f"{expected_duration:.3f}",
            str(out_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed while muxing:\n" + result.stderr[-4000:])
    return probe(out_path)


def probe(path: Path) -> dict:
    import json

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    subs = [s for s in data["streams"] if s["codec_type"] == "subtitle"]
    return {
        "duration": round(float(data["format"]["duration"]), 3),
        "size_bytes": int(data["format"]["size"]),
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("r_frame_rate"),
        "pix_fmt": video.get("pix_fmt"),
        "audio_codec": audio.get("codec_name"),
        "audio_channels": audio.get("channels"),
        "audio_rate": audio.get("sample_rate"),
        "subtitle_streams": len(subs),
    }
