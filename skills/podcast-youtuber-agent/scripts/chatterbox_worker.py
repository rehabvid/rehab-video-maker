#!/usr/bin/env python3
"""Batch voice-cloning worker for Resemble AI's Chatterbox TTS.

Run this with the *voice* virtual environment, not the main project venv:

    .venv-voice/bin/python scripts/chatterbox_worker.py --check
    .venv-voice/bin/python scripts/chatterbox_worker.py \
        --jobs build/ep01/tts/jobs.json \
        --reference voices/me/reference.wav \
        --device mps

The main ``narrate.py`` process calls this worker once per render, so the
model is loaded once and reused for every slide.  Chatterbox is MIT licensed;
the reference clip is your own voice, recorded with consent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _split_text(text: str, limit: int = 280) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            words = sentence.split()
            part = ""
            for word in words:
                candidate = f"{part} {word}".strip()
                if part and len(candidate) > limit:
                    chunks.append(part)
                    part = word
                else:
                    part = candidate
            if part:
                chunks.append(part)
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _check_perth() -> None:
    try:
        import perth
    except ImportError as exc:
        raise RuntimeError("resemble-perth is not installed") from exc
    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        raise RuntimeError(
            "PerthImplicitWatermarker is unavailable. This is usually caused by "
            "setuptools>=81 removing pkg_resources; run: "
            "uv pip install --python .venv-voice/bin/python 'setuptools<81'"
        )


def _load_model(device: str):
    import torch

    if device == "mps" and not torch.backends.mps.is_available():
        print("mps is not available; using cpu", file=sys.stderr)
        device = "cpu"
    if device == "mps":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    _check_perth()
    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device=device)
    return model, device


def _generate(model, text: str, reference: Path, exaggeration: float,
              cfg_weight: float, temperature: float):
    kwargs = {
        "audio_prompt_path": str(reference),
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "temperature": temperature,
    }
    try:
        return model.generate(text, **kwargs)
    except TypeError:
        # Older/newer Chatterbox releases expose slightly different controls.
        for key in ("temperature", "cfg_weight", "exaggeration"):
            kwargs.pop(key, None)
            try:
                return model.generate(text, **kwargs)
            except TypeError:
                continue
        return model.generate(text, audio_prompt_path=str(reference))


def check() -> int:
    try:
        import torch
    except ImportError as exc:
        print(f"error: torch is not installed in this interpreter: {exc}", file=sys.stderr)
        return 1
    try:
        import chatterbox
    except ImportError as exc:
        print(f"error: chatterbox-tts is not installed: {exc}", file=sys.stderr)
        return 1
    try:
        _check_perth()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"python:       {sys.executable}")
    print(f"torch:        {torch.__version__}")
    print(f"mps:          {torch.backends.mps.is_available()}")
    print(f"chatterbox:   {getattr(chatterbox, '__version__', 'installed')}")
    print("status: voice environment is importable")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", help="JSON list of {id, text, out} jobs")
    parser.add_argument("--reference", help="reference WAV")
    parser.add_argument("--device", default="mps", choices=["mps", "cpu"])
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--max-chars", type=int, default=280)
    parser.add_argument("--check", action="store_true", help="check imports only")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if not args.jobs or not args.reference:
        parser.error("--jobs and --reference are required unless --check is used")

    jobs_path = Path(args.jobs)
    reference = Path(args.reference)
    if not reference.exists():
        print(f"error: reference audio not found: {reference}", file=sys.stderr)
        return 1
    try:
        jobs = json.loads(jobs_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read jobs: {exc}", file=sys.stderr)
        return 1
    if not isinstance(jobs, list) or not jobs:
        print("error: jobs must be a non-empty JSON list", file=sys.stderr)
        return 1

    import torch
    import torchaudio

    model, device = _load_model(args.device)
    torch.manual_seed(args.seed)
    sample_rate = int(getattr(model, "sr", 24_000))
    failures: list[str] = []

    for index, job in enumerate(jobs, start=1):
        job_id = str(job.get("id") or index)
        text = (job.get("text") or "").strip()
        out = Path(job.get("out") or "")
        if not text or not out:
            failures.append(f"{job_id}: missing text or out")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        chunks = _split_text(text, args.max_chars)
        pieces = []
        print(f"[{index}/{len(jobs)}] {job_id}: {len(chunks)} chunk(s)", file=sys.stderr)
        for chunk_index, chunk in enumerate(chunks, start=1):
            try:
                wav = _generate(
                    model,
                    chunk,
                    reference,
                    args.exaggeration,
                    args.cfg_weight,
                    args.temperature,
                )
            except Exception as exc:  # noqa: BLE001 - model/runtime errors vary
                message = f"{job_id} chunk {chunk_index}: {exc}"
                print(f"error: {message}", file=sys.stderr)
                if device == "mps":
                    print("retrying the remaining job on cpu", file=sys.stderr)
                    model, device = _load_model("cpu")
                    try:
                        wav = _generate(
                            model,
                            chunk,
                            reference,
                            args.exaggeration,
                            args.cfg_weight,
                            args.temperature,
                        )
                    except Exception as second:  # noqa: BLE001
                        failures.append(f"{message}; cpu retry: {second}")
                        break
                else:
                    failures.append(message)
                    break
            if wav.dim() == 1:
                wav = wav.unsqueeze(0)
            pieces.append(wav.detach().cpu())
            print(f"  chunk {chunk_index}/{len(chunks)} done", file=sys.stderr)
        else:
            if not pieces:
                failures.append(f"{job_id}: no audio generated")
                continue
            if len(pieces) > 1:
                silence = torch.zeros(
                    (1, int(0.12 * sample_rate)), dtype=pieces[0].dtype
                )
                joined = [pieces[0]]
                for piece in pieces[1:]:
                    joined.extend([silence, piece])
                wav = torch.cat(joined, dim=1)
            else:
                wav = pieces[0]
            # Chatterbox can hit full scale on a few samples. Leave a little
            # headroom so the 16-bit master decode never has to hard-clip.
            peak = float(wav.abs().max())
            if peak > 0.98:
                wav = wav * (0.95 / peak)
            torchaudio.save(str(out), wav, sample_rate)
            print(f"  wrote {out}", file=sys.stderr)

    if failures:
        print(json.dumps({"ok": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"ok": True, "jobs": len(jobs), "device": device}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
