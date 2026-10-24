#!/usr/bin/env python3
"""Analyse and prepare a personal voice reference for zero-shot TTS.

A good reference is 45-90 seconds of clean, natural speech in the tone you
want on the channel.  This script does not clone a voice by itself; it checks
the recording, trims leading/trailing silence, converts to a predictable
48 kHz mono PCM WAV, and writes a consent/voice profile for the renderer.

Commands::

    python3 scripts/voice_sample.py analyze my-take.wav
    python3 scripts/voice_sample.py prepare my-take.wav \
        --out voices/me --consent self --name me

Use ``prepare`` only for your own voice, or for a voice you have explicit
written permission to clone.  The profile is personal data; ``voices/`` is
gitignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48_000
FRAME_SECONDS = 0.02
MIN_SECONDS = 10.0
IDEAL_MIN_SECONDS = 45.0
IDEAL_MAX_SECONDS = 120.0
MIN_SAMPLE_RATE = 24_000
CLIP_LIMIT = 0.999
NOISE_FLOOR_WARN = -50.0
SNR_WARN = 20.0


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({' '.join(cmd[:2])} ...):\n{result.stderr[-3000:]}"
        )
    return result


def probe(path: Path) -> dict:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(result.stdout)
    audio = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
        {},
    )
    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "codec": audio.get("codec_name"),
    }


def decode_mono(path: Path) -> np.ndarray:
    """Decode any input to 48 kHz mono float32 samples."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg could not decode the sample:\n" + result.stderr.decode()[-3000:])
    data = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0
    if data.size == 0:
        raise RuntimeError("the decoded sample is empty")
    return data


def _db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def analyze_array(samples: np.ndarray, info: dict) -> dict:
    frame_len = max(1, int(FRAME_SECONDS * SAMPLE_RATE))
    usable = samples[: (len(samples) // frame_len) * frame_len]
    if usable.size == 0:
        raise RuntimeError("sample is shorter than one analysis frame")
    frames = usable.reshape(-1, frame_len)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    frame_db = np.array([_db(float(value)) for value in rms])
    peak = float(np.max(np.abs(samples)))
    peak_db = _db(peak)
    rms_db = _db(float(np.sqrt(np.mean(samples * samples))))
    noise_db = float(np.percentile(frame_db, 10))
    speech_db = float(np.percentile(frame_db, 90))
    snr_db = speech_db - noise_db
    clipped = int(np.sum(np.abs(samples) >= CLIP_LIMIT))
    silence_ratio = float(np.mean(frame_db < -50.0))

    errors: list[str] = []
    warnings: list[str] = []
    duration = float(info.get("duration") or len(samples) / SAMPLE_RATE)

    if duration < MIN_SECONDS:
        errors.append(f"sample is {duration:.1f}s; record at least {MIN_SECONDS:.0f}s")
    elif duration < IDEAL_MIN_SECONDS:
        warnings.append(
            f"sample is {duration:.1f}s; {IDEAL_MIN_SECONDS:.0f}-{IDEAL_MAX_SECONDS:.0f}s "
            "is the recommended range"
        )
    if duration > IDEAL_MAX_SECONDS + 90:
        warnings.append(
            f"sample is {duration:.1f}s; a 45-90s clean excerpt is usually better than "
            "a long recording with room noise"
        )
    if int(info.get("sample_rate") or 0) < MIN_SAMPLE_RATE:
        errors.append(
            f"sample rate is {info.get('sample_rate')} Hz; use at least {MIN_SAMPLE_RATE} Hz"
        )
    if int(info.get("channels") or 0) > 2 or int(info.get("channels") or 0) < 1:
        errors.append("sample must be mono or stereo")
    if clipped:
        errors.append(f"{clipped} clipped samples; lower the input gain and re-record")
    if peak_db > -1.0:
        warnings.append(f"peak is {peak_db:.1f} dBFS; aim for about -6 dBFS to leave headroom")
    if peak_db < -24.0:
        warnings.append(f"peak is only {peak_db:.1f} dBFS; raise the input gain")
    if noise_db > NOISE_FLOOR_WARN:
        warnings.append(
            f"noise floor is {noise_db:.1f} dBFS; aim below {NOISE_FLOOR_WARN:.0f} dBFS "
            "(quiet room, closer mic, no fan)"
        )
    if snr_db < SNR_WARN:
        warnings.append(f"speech-to-noise ratio is {snr_db:.1f} dB; aim for 25 dB or more")
    if silence_ratio > 0.45:
        warnings.append(
            f"{silence_ratio:.0%} of the sample is near-silent; trim pauses or record closer"
        )

    return {
        "duration": round(duration, 3),
        "sample_rate": int(info.get("sample_rate") or SAMPLE_RATE),
        "channels": int(info.get("channels") or 1),
        "codec": info.get("codec"),
        "peak_dbfs": round(peak_db, 2),
        "rms_dbfs": round(rms_db, 2),
        "noise_floor_dbfs": round(noise_db, 2),
        "speech_dbfs": round(speech_db, 2),
        "snr_db": round(snr_db, 2),
        "silence_ratio": round(silence_ratio, 3),
        "clipped_samples": clipped,
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def analyze(path: Path) -> dict:
    info = probe(path)
    samples = decode_mono(path)
    return analyze_array(samples, info)


def trim_bounds(samples: np.ndarray, threshold_db: float = -45.0) -> tuple[float, float]:
    """Return start/end seconds for the speech region, with a small margin.

    Trimming in Python avoids ``silenceremove``'s surprising stop-period
    semantics, which can cut at the first internal pause instead of only at
    the end of the file.
    """
    frame_len = max(1, int(FRAME_SECONDS * SAMPLE_RATE))
    usable = samples[: (len(samples) // frame_len) * frame_len]
    if usable.size == 0:
        return 0.0, len(samples) / SAMPLE_RATE
    frames = usable.reshape(-1, frame_len)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    active = np.where(np.array([_db(float(value)) for value in rms]) > threshold_db)[0]
    if active.size == 0:
        return 0.0, len(samples) / SAMPLE_RATE
    start = max(0.0, active[0] * frame_len / SAMPLE_RATE - 0.15)
    end = min(
        len(samples) / SAMPLE_RATE,
        (active[-1] + 1) * frame_len / SAMPLE_RATE + 0.25,
    )
    return round(start, 3), round(end, 3)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(args) -> int:
    source = Path(args.sample)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = out_dir / "reference.wav"

    if reference.exists() and not args.force:
        print(f"error: {reference} exists; use --force to replace it", file=sys.stderr)
        return 1

    source_info = analyze(source)
    if source_info["clipped_samples"]:
        print("error: the source clips; re-record with more headroom", file=sys.stderr)
        return 1
    if not source_info["ready"]:
        for error in source_info["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return 1
    for warning in source_info["warnings"]:
        print(f"warning: {warning}")

    filters: list[str] = []
    if args.trim:
        samples = decode_mono(source)
        start, end = trim_bounds(samples)
        if end - start < MIN_SECONDS:
            print(
                f"error: trimming would leave only {end - start:.1f}s of speech; "
                "record at least 10s without long pauses",
                file=sys.stderr,
            )
            return 1
        filters.append(f"atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS")
    if math.isfinite(source_info["peak_dbfs"]):
        gain = -3.0 - source_info["peak_dbfs"]
        if abs(gain) >= 0.1:
            filters.append(f"volume={gain:.2f}dB")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-c:a",
        "pcm_s24le",
    ]
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd.append(str(reference))
    _run(cmd)

    reference_info = analyze(reference)
    if not reference_info["ready"]:
        for error in reference_info["errors"]:
            print(f"error: {error}", file=sys.stderr)
        print(f"kept the converted file for inspection: {reference}", file=sys.stderr)
        return 1

    profile = {
        "name": args.name or out_dir.name,
        "consent": args.consent,
        "consent_note": args.consent_note,
        "synthetic_use_allowed": True,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference": reference.name,
        "reference_sha256": sha256_file(reference),
        "source": str(source),
        "source_sha256": sha256_file(source),
        "engine": args.engine,
        "settings": {
            "exaggeration": args.exaggeration,
            "cfg_weight": args.cfg_weight,
        },
        "analysis": reference_info,
    }
    (out_dir / "voice.json").write_text(json.dumps(profile, indent=2) + "\n")
    (out_dir / "voice.json").chmod(0o600)

    print(f"wrote {reference} ({reference_info['duration']:.1f}s, "
          f"{reference_info['peak_dbfs']:.1f} dBFS peak)")
    print(f"wrote {out_dir / 'voice.json'}")
    for warning in reference_info["warnings"]:
        print(f"warning: {warning}")
    print("next: run narrate.py with --voice-profile " + str(out_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="check a recording")
    p_analyze.add_argument("sample")
    p_analyze.add_argument("--json", action="store_true", help="print machine-readable JSON")

    p_prepare = sub.add_parser("prepare", help="convert and write a voice profile")
    p_prepare.add_argument("sample")
    p_prepare.add_argument("--out", default="voices/me")
    p_prepare.add_argument("--name")
    p_prepare.add_argument("--consent", required=True, choices=["self", "authorized"])
    p_prepare.add_argument("--consent-note", default="")
    p_prepare.add_argument("--engine", default="chatterbox", choices=["chatterbox", "edge"])
    p_prepare.add_argument("--exaggeration", type=float, default=0.5)
    p_prepare.add_argument("--cfg-weight", type=float, default=0.5)
    p_prepare.add_argument("--no-trim", dest="trim", action="store_false")
    p_prepare.add_argument("--force", action="store_true")
    p_prepare.set_defaults(trim=True)

    args = parser.parse_args(argv)
    if args.command == "analyze":
        try:
            result = analyze(Path(args.sample))
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"duration:       {result['duration']:.1f}s")
            print(f"format:         {result['sample_rate']} Hz, {result['channels']} ch, {result['codec']}")
            print(f"peak / RMS:     {result['peak_dbfs']:.1f} / {result['rms_dbfs']:.1f} dBFS")
            print(f"noise / speech: {result['noise_floor_dbfs']:.1f} / {result['speech_dbfs']:.1f} dBFS")
            print(f"SNR:            {result['snr_db']:.1f} dB")
            print(f"silence:        {result['silence_ratio']:.0%}")
            print(f"clipped:        {result['clipped_samples']}")
            for warning in result["warnings"]:
                print(f"warning: {warning}")
            for error in result["errors"]:
                print(f"error: {error}", file=sys.stderr)
            print("status: ready" if result["ready"] else "status: needs work")
        return 0 if result["ready"] else 1

    return prepare(args)


if __name__ == "__main__":
    raise SystemExit(main())
