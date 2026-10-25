#!/usr/bin/env python3
"""Qwen3-TTS Base voice cloning worker for Apple Silicon (MLX).

This is the faster alternative to Chatterbox. It uses ``mlx-audio`` and the
0.6B Base model, which supports zero-shot cloning from ``ref_audio`` plus the
exact ``ref_text`` transcript.

Run inside the voice environment (``.venv-voice``)::

    .venv-voice/bin/python scripts/qwen3_worker.py --check

The worker accepts a JSON job list produced by ``narrate.py``. It keeps the
model loaded for the whole batch, which is important because cold load is
noticeably slower than warm generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"


def _load_model(model_name: str):
    from mlx_audio.tts.utils import load_model

    return load_model(model_name)


def check() -> int:
    try:
        import mlx_audio
    except ImportError as exc:
        print(f"error: mlx-audio is not installed: {exc}", file=sys.stderr)
        print("install it in .venv-voice: uv pip install mlx-audio", file=sys.stderr)
        return 1
    try:
        import mlx.core as mx
    except ImportError as exc:
        print(f"error: mlx is not installed: {exc}", file=sys.stderr)
        return 1
    print(f"python:       {sys.executable}")
    print(f"mlx:          {getattr(mx, '__version__', 'installed')}")
    print(f"mlx-audio:    {getattr(mlx_audio, '__version__', 'installed')}")
    print(f"model:        {DEFAULT_MODEL}")
    print("status: Qwen3-TTS MLX environment is importable")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", help="JSON list of {id, text, out} jobs")
    parser.add_argument("--reference", help="reference WAV")
    parser.add_argument("--ref-text-file", required=False, help="exact transcript of the reference WAV")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-tokens", type=int, help="override per-job token cap")
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--check", action="store_true", help="check imports only")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if not args.jobs or not args.reference or not args.ref_text_file:
        parser.error("--jobs, --reference and --ref-text-file are required unless --check is used")

    reference = Path(args.reference)
    ref_text_path = Path(args.ref_text_file)
    if not reference.exists():
        print(f"error: reference audio not found: {reference}", file=sys.stderr)
        return 1
    if not ref_text_path.exists():
        print(f"error: reference transcript not found: {ref_text_path}", file=sys.stderr)
        return 1
    try:
        jobs = json.loads(Path(args.jobs).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read jobs: {exc}", file=sys.stderr)
        return 1
    if not isinstance(jobs, list) or not jobs:
        print("error: jobs must be a non-empty JSON list", file=sys.stderr)
        return 1

    try:
        import mlx.core as mx
        from mlx_audio.audio_io import write as audio_write
    except ImportError as exc:
        print(f"error: mlx-audio is not installed: {exc}", file=sys.stderr)
        return 1

    ref_text = ref_text_path.read_text().strip()
    if not ref_text:
        print("error: reference transcript is empty", file=sys.stderr)
        return 1

    print(f"loading {args.model}", file=sys.stderr)
    model = _load_model(args.model)
    mx.random.seed(args.seed)
    failures: list[str] = []

    for index, job in enumerate(jobs, start=1):
        job_id = str(job.get("id") or index)
        text = (job.get("text") or "").strip()
        out = Path(job.get("out") or "")
        if not text or not out:
            failures.append(f"{job_id}: missing text or out")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{len(jobs)}] {job_id}", file=sys.stderr)
        try:
            words = max(1, len(text.split()))
            # Qwen3 emits roughly 12-13 tokens per second of audio. Cap the
            # generation at ~1.35x the expected duration so a bad sample cannot
            # loop for minutes.
            max_tokens = args.max_tokens or max(
                160,
                int(words / 160.0 * 60.0 * 13.0 * 1.35) + 48,
            )
            results = list(
                model.generate(
                    text=text,
                    ref_audio=str(reference),
                    ref_text=ref_text,
                    speed=args.speed,
                    temperature=args.temperature,
                    max_tokens=max_tokens,
                    stream=False,
                    verbose=False,
                )
            )
            if not results:
                raise RuntimeError("model returned no audio")
            result = results[0]
            audio_write(str(out), result.audio, result.sample_rate)
            duration = result.samples / result.sample_rate
            print(
                f"  wrote {out} ({duration:.2f}s, "
                f"{duration / max(result.processing_time_seconds, 1e-6):.2f}x realtime)",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001 - model/runtime errors vary
            failures.append(f"{job_id}: {exc}")
            print(f"error: {job_id}: {exc}", file=sys.stderr)

    if failures:
        print(json.dumps({"ok": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"ok": True, "jobs": len(jobs), "model": args.model}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
