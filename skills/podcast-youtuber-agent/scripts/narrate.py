#!/usr/bin/env python3
"""Synthesise b-roll-slide narration with a personal voice and measured timing.

The default engine is Qwen3-TTS Base 0.6B on MLX (voice cloning, faster than
realtime on Apple Silicon). ``--engine chatterbox`` remains available, and
``--engine edge`` is a no-clone fallback for drafts.

Outputs, under ``--out``::

    audio/shot-XX.wav|mp3      one clip per slide
    audio/narration.json       cache manifest
    timing.json                measured durations and the exact timeline
    master.wav                 48 kHz stereo, peak-normalised
    captions.srt / captions.ass
    cues.txt

The timeline is always measured with ffprobe; it is never estimated.  The
renderer consumes ``timing.json`` and the shared card/caption code from the
podcast-avatar-commentary skill.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import pronunciation  # noqa: E402

SHARED = Path(__file__).resolve().parents[2] / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lib import (  # noqa: E402
    FPS,
    LEAD,
    LEAD_FIRST,
    TAIL,
    ffprobe_duration,
    load_json,
    quantize,
    save_json,
    write_ass,
    write_srt,
)

SAMPLE_RATE = 48_000
CHANNELS = 2
PEAK_TARGET = 0.708  # -3 dBFS
EDGE_VOICES = {
    "andrew": "en-US-AndrewNeural",
    "steffan": "en-US-SteffanNeural",
    "thomas": "en-GB-ThomasNeural",
    "eric": "en-US-EricNeural",
    "ava": "en-US-AvaNeural",
}
DEFAULT_EDGE_VOICE = "andrew"
DEFAULT_RATE = "-6%"
DEFAULT_VOICE_PROFILE = "voices/me"
QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"
DEFAULT_REF_TEXT = Path("skills/podcast-youtuber-agent/config/sample-passage.txt")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _fingerprint(
    text: str,
    engine: str,
    profile_hash: str,
    voice: str,
    rate: str,
    exaggeration: float,
    cfg_weight: float,
    turbo: bool = False,
) -> str:
    blob = "|".join(
        [
            engine,
            profile_hash,
            voice,
            rate,
            f"{exaggeration:.4f}",
            f"{cfg_weight:.4f}",
            "turbo" if turbo else "standard",
            text,
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _tts_text(shot: dict) -> str:
    """Spoken text, with an optional pronunciation-only override."""
    return str(shot.get("tts_text") or shot.get("narration") or "")


def _apply_pronunciation(shots: list[dict], config: str | None) -> list[dict]:
    """Add TTS-only pronunciation text without changing captions."""
    report: list[dict] = []
    for shot in shots:
        narration = str(shot.get("narration") or "")
        if not narration:
            continue
        explicit = str(shot.get("tts_text") or "").strip()
        if explicit:
            tts_text = explicit
            applied: list[dict] = []
            source = "explicit"
        else:
            tts_text, applied = pronunciation.prepare_tts_text(narration, config)
            source = "lexicon"
        if tts_text and tts_text != narration:
            shot["tts_text"] = tts_text
            report.append({
                "id": str(shot.get("id") or ""),
                "original": narration,
                "tts_text": tts_text,
                "source": source,
                "applied": applied,
            })
    return report


def _profile(args) -> dict:
    profile_dir = Path(args.voice_profile)
    reference = profile_dir / "reference.wav"
    metadata = profile_dir / "voice.json"
    if not reference.exists():
        raise FileNotFoundError(
            f"voice reference not found: {reference}\n"
            "record a sample and run voice_sample.py prepare first"
        )
    data = {}
    if metadata.exists():
        try:
            data = json.loads(metadata.read_text())
        except json.JSONDecodeError:
            data = {}
    consent = data.get("consent")
    if consent not in ("self", "authorized"):
        raise ValueError(
            f"{metadata} must record consent='self' or 'authorized'; "
            "do not clone a voice without permission"
        )
    return {
        "name": data.get("name") or profile_dir.name,
        "reference": reference,
        "sha256": _sha(reference),
        "metadata": data,
    }


def _decode_to_wav(src: Path, dst: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        check=True,
    )
    return dst


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != CHANNELS:
            raise RuntimeError(f"{path} is not {SAMPLE_RATE} Hz stereo")
        frames = handle.readframes(handle.getnframes())
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, CHANNELS)


def _trim_tail_artifact(
    path: Path,
    *,
    window_seconds: float = 0.10,
    threshold_db: float = 12.0,
    min_tail_seconds: float = 1.0,
    keep_seconds: float = 0.25,
) -> float:
    """Trim a long low-level hallucinated tail from a generated WAV.

    Qwen3-TTS can finish the words and then keep emitting quiet, speech-like
    noise for several seconds.  Ordinary silence trimming is not enough because
    the artifact is above the silence floor.  Compare short-frame RMS with the
    speech level: if more than ``min_tail_seconds`` remains below
    ``threshold_db`` relative to the 95th percentile, keep only a short natural
    pause and discard the rest.  Returns the number of seconds removed.
    """
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        if width != 2:
            return 0.0
        raw = handle.readframes(handle.getnframes())
    data = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        mono = data.reshape(-1, channels).astype(np.float32).mean(axis=1)
    else:
        mono = data.astype(np.float32)
    mono /= 32768.0
    window = max(1, int(window_seconds * sample_rate))
    frames = len(mono) // window
    if frames < 10:
        return 0.0
    blocks = mono[: frames * window].reshape(frames, window)
    rms = 20.0 * np.log10(
        np.maximum(1e-9, np.sqrt(np.mean(blocks * blocks, axis=1)))
    )
    threshold = float(np.percentile(rms, 95)) - threshold_db
    active = np.flatnonzero(rms > threshold)
    if not len(active):
        return 0.0
    speech_end = (int(active[-1]) + 1) * window / sample_rate
    tail = len(mono) / sample_rate - speech_end
    if tail < min_tail_seconds:
        return 0.0
    keep = min(len(mono), int((speech_end + keep_seconds) * sample_rate))
    trimmed = data.reshape(-1, channels)[:keep] if channels > 1 else data[:keep]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(trimmed.astype("<i2").tobytes())
    return round(tail, 3)


def _build_master(timeline: list[dict], out_wav: Path, out_dir: Path,
                  work_dir: Path, total: float) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    total_frames = int(np.ceil(total * SAMPLE_RATE)) + 1
    bed = np.zeros((total_frames, CHANNELS), dtype=np.float32)

    for shot in timeline:
        wav = _decode_to_wav(out_dir / shot["audio"], work_dir / f"{shot['id']}.wav")
        clip = _read_wav(wav)
        start = int(round((shot["start"] + shot["lead"]) * SAMPLE_RATE))
        end = min(start + len(clip), total_frames)
        if end - start != len(clip):
            raise RuntimeError(
                f"slide {shot['id']} would be truncated: speech ends after the video"
            )
        bed[start:end] += clip

    peak = float(np.max(np.abs(bed))) if bed.size else 0.0
    if peak > 0:
        bed *= PEAK_TARGET / peak
    pcm = np.clip(bed * 32767.0, -32768, 32767).astype("<i2")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())

    return {
        "duration": round(total_frames / SAMPLE_RATE, 3),
        "peak_before_normalise": round(peak, 4),
        "peak_after_normalise": round(PEAK_TARGET if peak else 0.0, 4),
        "clipped_samples": int(np.sum(np.abs(bed) >= 0.999)),
    }


async def _edge_synth(jobs: list[tuple[str, Path, str, str]]) -> None:
    import edge_tts

    semaphore = asyncio.Semaphore(4)

    async def one(text: str, path: Path, voice: str, rate: str) -> None:
        async with semaphore:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(path))

    await asyncio.gather(*(one(text, path, voice, rate) for text, path, voice, rate in jobs))


def _reference_text(args, profile: dict) -> str:
    if getattr(args, "ref_text_file", None):
        path = Path(args.ref_text_file)
        if not path.exists():
            raise ValueError(f"reference transcript not found: {path}")
        return path.read_text().strip()
    text = (profile.get("metadata") or {}).get("reference_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    if DEFAULT_REF_TEXT.exists():
        return DEFAULT_REF_TEXT.read_text().strip()
    raise ValueError(
        "Qwen3 voice cloning needs the exact reference transcript; "
        "pass --ref-text-file or add reference_text to voice.json"
    )


def _chatterbox_jobs(shots: list[dict], audio_dir: Path, cached: dict[str, dict],
                     fingerprints: dict[str, str], force: bool) -> list[dict]:
    jobs = []
    for shot in shots:
        sid = str(shot["id"])
        path = audio_dir / f"shot-{sid}.wav"
        cached_entry = cached.get(sid)
        reusable = (
            not force
            and path.exists()
            and cached_entry
            and cached_entry.get("fingerprint") == fingerprints[sid]
            and cached_entry.get("file") == path.name
        )
        if not reusable:
            jobs.append({"id": sid, "text": _tts_text(shot), "out": str(path)})
    return jobs


def _run_chatterbox(args, jobs: list[dict], profile: dict) -> None:
    if not jobs:
        return
    voice_python = Path(args.voice_python)
    if not voice_python.exists():
        raise FileNotFoundError(
            f"voice python not found: {voice_python}\n"
            "create the voice environment with the commands in SKILL.md "
            "(uv venv --python 3.11 .venv-voice ...)"
        )
    worker = Path(__file__).with_name("chatterbox_worker.py")
    job_path = Path(args.out) / "tts" / "jobs.json"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(jobs, indent=2) + "\n")
    cmd = [
        str(voice_python),
        str(worker),
        "--jobs",
        str(job_path),
        "--reference",
        str(profile["reference"]),
        "--device",
        args.device,
        "--exaggeration",
        str(args.exaggeration),
        "--cfg-weight",
        str(args.cfg_weight),
        "--seed",
        str(args.seed),
        "--max-chars",
        str(args.max_chars),
    ]
    if args.turbo:
        cmd.append("--turbo")
    print(f"synthesising {len(jobs)} cues with Chatterbox on {args.device}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Chatterbox synthesis failed; see the worker output above. "
            "Run chatterbox_worker.py --check in the voice environment."
        )


def _qwen3_jobs(shots: list[dict], audio_dir: Path, cached: dict[str, dict],
                fingerprints: dict[str, str], force: bool) -> list[dict]:
    jobs = []
    for shot in shots:
        sid = str(shot["id"])
        path = audio_dir / f"shot-{sid}.wav"
        cached_entry = cached.get(sid)
        reusable = (
            not force
            and path.exists()
            and cached_entry
            and cached_entry.get("fingerprint") == fingerprints[sid]
            and cached_entry.get("file") == path.name
        )
        if not reusable:
            jobs.append({"id": sid, "text": _tts_text(shot), "out": str(path)})
    return jobs


def _run_qwen3(args, jobs: list[dict], profile: dict, ref_text: str) -> None:
    if not jobs:
        return
    voice_python = Path(args.voice_python)
    if not voice_python.exists():
        raise FileNotFoundError(
            f"voice python not found: {voice_python}\n"
            "create the voice environment with the commands in SKILL.md "
            "(uv venv --python 3.11 .venv-voice ...)"
        )
    worker = Path(__file__).with_name("qwen3_worker.py")
    out = Path(args.out)
    job_path = out / "tts" / "qwen3-jobs.json"
    ref_path = out / "tts" / "qwen3-ref.txt"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(jobs, indent=2) + "\n")
    ref_path.write_text(ref_text.strip() + "\n")
    cmd = [
        str(voice_python),
        str(worker),
        "--jobs", str(job_path),
        "--reference", str(profile["reference"]),
        "--ref-text-file", str(ref_path),
        "--model", args.qwen3_model,
        "--speed", str(args.speed),
        "--target-wpm", str(args.target_wpm),
        "--temperature", str(args.qwen3_temperature),
        "--seed", str(args.seed),
    ]
    print(f"synthesising {len(jobs)} cues with Qwen3-TTS on MLX")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Qwen3-TTS synthesis failed; see the worker output above. "
            "Run qwen3_worker.py --check in the voice environment."
        )

def build(args) -> int:
    slides_path = Path(args.slides)
    data = load_json(slides_path)
    if not isinstance(data, dict):
        print("error: slide list must be a JSON object", file=sys.stderr)
        return 1
    shots = data.get("shots") or []
    if not shots:
        print("error: slide list has no shots", file=sys.stderr)
        return 1

    out = Path(args.out)
    audio_dir = out / "audio"
    tmp_dir = out / "tts"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fps = int(data.get("fps") or FPS)
    engine = args.engine or data.get("engine") or "qwen3"
    if engine not in ("qwen3", "chatterbox", "edge"):
        print(f"error: unknown engine '{engine}'", file=sys.stderr)
        return 1

    pronunciation_report: list[dict] = []
    if not getattr(args, "no_pronunciation", False):
        pronunciation_report = _apply_pronunciation(
            shots, getattr(args, "pronunciation_config", None)
        )

    profile = None
    profile_hash = ""
    ref_text = ""
    if engine in ("qwen3", "chatterbox"):
        try:
            profile = _profile(args)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if engine == "qwen3":
            ref_text = _reference_text(args, profile)
            profile_hash = _sha_text(profile["sha256"] + "|" + ref_text)
            voice_name = f"qwen3:{profile['name']}"
        else:
            profile_hash = profile["sha256"]
            voice_name = f"chatterbox:{profile['name']}"
        voice_rate = "natural"
        edge_voice = ""
    else:
        if args.voice not in EDGE_VOICES:
            print(
                f"error: unknown edge voice '{args.voice}' "
                f"(choose from {', '.join(EDGE_VOICES)})",
                file=sys.stderr,
            )
            return 1
        voice_name = EDGE_VOICES[args.voice]
        voice_rate = args.rate
        edge_voice = args.voice

    manifest_path = audio_dir / "narration.json"
    previous: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            previous = {
                str(cue["id"]): cue
                for cue in json.loads(manifest_path.read_text()).get("cues", [])
            }
        except (json.JSONDecodeError, KeyError):
            previous = {}

    fingerprints = {
        str(shot["id"]): _fingerprint(
            shot["narration"] + "\n<TTS>\n" + _tts_text(shot),
            engine,
            profile_hash,
            edge_voice or str(profile["name"] if profile else ""),
            voice_rate if engine == "edge" else "",
            args.exaggeration,
            args.cfg_weight,
            args.turbo if engine == "chatterbox" else False,
        )
        for shot in shots
    }

    if engine == "qwen3":
        jobs = _qwen3_jobs(shots, audio_dir, previous, fingerprints, args.force)
        if args.dry_run:
            print(json.dumps(jobs, indent=2))
            return 0
        try:
            _run_qwen3(args, jobs, profile, ref_text)  # type: ignore[arg-type]
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        extension = ".wav"
    elif engine == "chatterbox":
        jobs = _chatterbox_jobs(shots, audio_dir, previous, fingerprints, args.force)
        if args.dry_run:
            print(json.dumps(jobs, indent=2))
            return 0
        try:
            _run_chatterbox(args, jobs, profile)  # type: ignore[arg-type]
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        extension = ".wav"
    else:
        jobs = []
        for shot in shots:
            sid = str(shot["id"])
            path = audio_dir / f"shot-{sid}.mp3"
            cached_entry = previous.get(sid)
            reusable = (
                not args.force
                and path.exists()
                and cached_entry
                and cached_entry.get("fingerprint") == fingerprints[sid]
                and cached_entry.get("file") == path.name
            )
            if not reusable:
                jobs.append((_tts_text(shot), path, voice_name, args.rate))
        if args.dry_run:
            print(json.dumps([
                {"text": text, "out": str(path)}
                for text, path, _, _ in jobs
            ], ensure_ascii=False, indent=2))
            return 0
        if jobs:
            print(f"synthesising {len(jobs)} cues with {voice_name} at {args.rate}")
            try:
                asyncio.run(_edge_synth(jobs))
            except Exception as exc:  # noqa: BLE001 - network/service errors vary
                print(f"error: edge-tts failed: {exc}", file=sys.stderr)
                print(
                    "hint: check network access, or use --engine chatterbox with a "
                    "personal voice profile",
                    file=sys.stderr,
                )
                return 1
        extension = ".mp3"

    if engine == "qwen3":
        for shot in shots:
            path = audio_dir / f"shot-{shot['id']}.wav"
            if path.exists():
                removed = _trim_tail_artifact(path)
                if removed:
                    print(
                        f"trimmed {removed:.1f}s of tail artifact from {path.name}",
                        flush=True,
                    )

    timeline: list[dict] = []
    cursor = 0.0
    for index, shot in enumerate(shots):
        sid = str(shot["id"])
        path = audio_dir / f"shot-{sid}{extension}"
        if not path.exists() or path.stat().st_size == 0:
            print(f"error: no audio for slide {sid} at {path}", file=sys.stderr)
            return 1
        duration = round(ffprobe_duration(path), 3)
        lead = LEAD_FIRST if index == 0 else LEAD
        shot_duration = quantize(lead + duration + TAIL, fps)
        override = float(shot.get("duration") or 0)
        if override > 0:
            shot_duration = max(shot_duration, quantize(override, fps))
        entry = {
            **{
                key: value
                for key, value in shot.items()
                if key not in {"narration", "tts_text"}
            },
            "narration": shot["narration"],
            "audio": f"audio/{path.name}",
            "audio_seconds": duration,
            "start": round(cursor, 3),
            "duration": round(shot_duration, 3),
            "lead": round(lead, 3),
            "tail": TAIL,
            "fingerprint": fingerprints[sid],
        }
        timeline.append(entry)
        cursor += shot_duration

    total = round(cursor, 3)
    language = data.get("language") or (
        "zh-Hans" if any("\u4e00" <= c <= "\u9fff" for c in "".join(
            str(shot.get("narration") or "") for shot in shots
        )) else "en"
    )
    if pronunciation_report:
        config_arg = getattr(args, "pronunciation_config", None)
        save_json(out / "pronunciation.json", {
            "language": language,
            "config": str(Path(config_arg).resolve())
            if config_arg else str(pronunciation.DEFAULT_CONFIG),
            "overrides": pronunciation_report,
        })
    save_json(
        manifest_path,
        {
            "engine": engine,
            "voice": {
                "name": voice_name,
                "rate": voice_rate,
                "profile": str(args.voice_profile) if engine == "chatterbox" else None,
                "profile_sha256": profile_hash,
                "exaggeration": args.exaggeration,
                "cfg_weight": args.cfg_weight,
            },
            "cues": [
                {
                    "id": shot["id"],
                    "file": shot["audio"].split("/")[-1],
                    "duration": shot["audio_seconds"],
                    "fingerprint": shot["fingerprint"],
                }
                for shot in timeline
            ],
        },
    )

    timing = {
        "slug": data.get("slug"),
        "title": data.get("title"),
        "format": "broll-slides",
        "language": language,
        "engine": engine,
        "voice": {
            "name": voice_name,
            "rate": voice_rate,
            "profile": str(args.voice_profile) if engine == "chatterbox" else None,
            "profile_sha256": profile_hash,
            "exaggeration": args.exaggeration,
            "cfg_weight": args.cfg_weight,
        },
        "fps": fps,
        "total_seconds": total,
        "shots": timeline,
    }
    save_json(out / "timing.json", timing)
    write_srt(timeline, out / "captions.srt")
    write_ass(timeline, out / "captions.ass")
    (out / "cues.txt").write_text(
        "".join(
            f"# {shot['id']}  {shot['start']:.2f}s + {shot['duration']:.2f}s\n"
            f"{shot['narration']}\n\n"
            for shot in timeline
        )
    )

    master = _build_master(timeline, out / "master.wav", out, tmp_dir, total)
    if master["clipped_samples"]:
        print("error: master.wav clips; lower the source or normalise manually", file=sys.stderr)
        return 1

    print(f"wrote {out / 'timing.json'}: {len(timeline)} slides, {total:.1f}s")
    print(
        f"wrote {out / 'master.wav'} "
        f"({master['duration']:.1f}s, peak {master['peak_after_normalise']:.2f} FS)"
    )
    print(f"wrote {out / 'captions.srt'} and {out / 'captions.ass'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--out", required=True, help="build directory, e.g. build/ep01")
    parser.add_argument("--engine", choices=["qwen3", "chatterbox", "edge"], default="qwen3", help="voice engine")
    parser.add_argument("--voice-profile", default=DEFAULT_VOICE_PROFILE)
    parser.add_argument("--voice-python", default=os.environ.get("VOICE_PYTHON", ".venv-voice/bin/python"))
    parser.add_argument("--device", default="mps", choices=["mps", "cpu"])
    parser.add_argument("--qwen3-model", default=QWEN3_MODEL)
    parser.add_argument("--qwen3-temperature", type=float, default=0.8)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--target-wpm", type=float, default=0.0, help="Qwen English post-speed target; 0 disables")
    parser.add_argument("--ref-text-file", help="exact transcript of the reference recording")
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--max-chars", type=int, default=280)
    parser.add_argument("--turbo", action="store_true", help="use Chatterbox no-CFG turbo inference")
    parser.add_argument("--voice", default=DEFAULT_EDGE_VOICE, help="edge-tts voice key")
    parser.add_argument("--rate", default=DEFAULT_RATE, help="edge-tts rate, use --rate=-6%%")
    parser.add_argument("--force", action="store_true", help="re-synthesise every cue")
    parser.add_argument("--dry-run", action="store_true", help="print pending jobs only")
    parser.add_argument(
        "--no-pronunciation", action="store_true",
        help="do not apply the finance/tech polyphone lexicon to TTS text",
    )
    parser.add_argument(
        "--pronunciation-config",
        help="alternate pronunciation lexicon JSON (default: config/pronunciation.zh.json)",
    )
    args = parser.parse_args(argv)
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
