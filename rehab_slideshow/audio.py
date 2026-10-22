"""Audio master assembly: place every cue on an exact timeline.

Cue clips are decoded to 48 kHz stereo PCM, summed into a silent bed at their
measured start times, peak-normalised once, and written as master.wav.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .captions import Cue

SAMPLE_RATE = 48_000
CHANNELS = 2
PEAK_TARGET = 0.708  # -3 dBFS


def decode_to_wav(src: Path, dst: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ar", str(SAMPLE_RATE),
         "-ac", str(CHANNELS), "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )
    return dst


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != CHANNELS:
            raise RuntimeError(f"{path} is not {SAMPLE_RATE} Hz stereo")
        frames = w.readframes(w.getnframes())
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, CHANNELS)


def build_master(timeline: list[Cue], out_wav: Path, total_seconds: float,
                 work_dir: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    total_frames = int(np.ceil(total_seconds * SAMPLE_RATE)) + 1
    bed = np.zeros((total_frames, CHANNELS), dtype=np.float32)

    for cue in timeline:
        wav = decode_to_wav(cue.audio, work_dir / f"{cue.id}.wav")
        clip = _read_wav(wav)
        start = int(round(cue.start * SAMPLE_RATE))
        end = min(start + len(clip), total_frames)
        if end - start != len(clip):
            raise RuntimeError(
                f"{cue.id} would be truncated: ends at {cue.end:.2f}s "
                f"but the video ends at {total_seconds:.2f}s"
            )
        bed[start:end] += clip

    peak = float(np.max(np.abs(bed))) if bed.size else 0.0
    if peak > 0:
        bed *= PEAK_TARGET / peak
        peak_out = PEAK_TARGET
    else:
        peak_out = 0.0

    pcm = np.clip(bed * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    return {
        "duration": round(total_frames / SAMPLE_RATE, 3),
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "peak_before_normalise": round(peak, 4),
        "peak_after_normalise": round(peak_out, 4),
        "cue_count": len(timeline),
    }


def probe(path: Path) -> dict:
    import json

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    stream = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    return {
        "duration": float(data["format"].get("duration", 0)),
        "sample_rate": int(stream.get("sample_rate", 0)),
        "channels": int(stream.get("channels", 0)),
        "codec": stream.get("codec_name"),
    }


def check_master(path: Path, expected_seconds: float) -> dict:
    info = probe(path)
    info["expected_duration"] = round(expected_seconds, 3)
    info["duration_ok"] = abs(info["duration"] - expected_seconds) < 0.1
    info["format_ok"] = info["sample_rate"] == SAMPLE_RATE and info["channels"] == CHANNELS
    # sample-domain clipping check
    data = _read_wav(path)
    info["clipped_samples"] = int(np.sum(np.abs(data) >= 0.999))
    if not info["duration_ok"]:
        raise RuntimeError(
            f"master.wav is {info['duration']:.2f}s but the timeline is "
            f"{expected_seconds:.2f}s"
        )
    if not info["format_ok"]:
        raise RuntimeError("master.wav is not 48 kHz stereo")
    if info["clipped_samples"]:
        raise RuntimeError(f"master.wav has {info['clipped_samples']} clipped samples")
    return info
