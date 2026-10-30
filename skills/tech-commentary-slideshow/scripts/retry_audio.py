#!/usr/bin/env python3
"""Regenerate only cues that fail the ASR/timing audio QA gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QA = HERE / "qa_audio.py"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slides", required=True)
    p.add_argument("--audio-dir", required=True)
    p.add_argument("--language", required=True)
    p.add_argument("--model", default="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16")
    p.add_argument("--voice-python", default=str(ROOT / ".venv-voice" / "bin" / "python"))
    p.add_argument("--reference", default=str(ROOT / "voices" / "me" / "reference.wav"))
    p.add_argument("--ref-text", default=str(ROOT / "voices" / "me" / "reference.txt"))
    p.add_argument("--attempts", type=int, default=4)
    p.add_argument("--seed", type=int, default=43)
    p.add_argument("--target-wpm", type=float, default=0.0)
    p.add_argument("--target-syllables", type=float, default=0.0)
    p.add_argument("--qa-out", required=True)
    args = p.parse_args(argv)
    slides = _load(Path(args.slides))
    shots = {str(s.get("id")): s for s in slides.get("shots", [])}
    audio_dir = Path(args.audio_dir); audio_dir.mkdir(parents=True, exist_ok=True)
    voice_python = Path(args.voice_python)
    qa_out = Path(args.qa_out)
    for attempt in range(args.attempts):
        qa_code = subprocess.run([
            sys.executable, str(QA), "--audio-dir", str(audio_dir),
            "--slides", args.slides, "--language", args.language,
            "--voice-python", str(voice_python), "--out", str(qa_out),
        ]).returncode
        if qa_code == 0:
            print(f"QA PASS on attempt {attempt + 1}")
            return 0
        report = _load(qa_out)
        failed = {str(r["id"]) for r in report.get("results", []) if r.get("status") != "pass"}
        if not failed:
            return 1
        print(f"attempt {attempt + 1}: regenerate {len(failed)} cue(s): {sorted(failed)}", flush=True)
        jobs = []
        for sid in sorted(failed):
            text = str((shots.get(sid) or {}).get("narration") or "").strip()
            if not text:
                continue
            out = audio_dir / f"shot-{sid}.wav"
            if out.exists():
                out.unlink()
            jobs.append({"id": sid, "text": text, "out": str(out)})
        if not jobs:
            return 1
        job_file = Path(tempfile.mkstemp(prefix="retry-jobs-", suffix=".json")[1])
        job_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2) + "\n")
        cmd = [
            str(voice_python), str(ROOT / "skills" / "podcast-youtuber-agent" / "scripts" / "qwen3_worker.py"),
            "--jobs", str(job_file), "--reference", args.reference,
            "--ref-text-file", args.ref_text, "--model", args.model,
            "--speed", "1.0", "--target-wpm", str(args.target_wpm),
            "--target-syllables-per-sec", str(args.target_syllables),
            "--seed", str(args.seed + attempt + 1), "--temperature", "0.8",
        ]
        subprocess.run(cmd)
        job_file.unlink(missing_ok=True)
    # The last attempt still needs a verdict; otherwise a good final sample is
    # reported as failed simply because the loop ended.
    qa_code = subprocess.run([
        sys.executable, str(QA), "--audio-dir", str(audio_dir),
        "--slides", args.slides, "--language", args.language,
        "--voice-python", str(voice_python), "--out", str(qa_out),
    ]).returncode
    if qa_code == 0:
        print(f"QA PASS on final attempt {args.attempts + 1}")
        return 0
    print("QA did not pass after retries", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
