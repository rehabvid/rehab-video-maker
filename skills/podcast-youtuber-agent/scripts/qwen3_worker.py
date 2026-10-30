#!/usr/bin/env python3
"""Qwen3-TTS Base voice cloning worker for Apple Silicon (MLX).

This is the faster alternative to Chatterbox. It uses ``mlx-audio`` and the
1.7B Base model, which supports zero-shot cloning from ``ref_audio`` plus the
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
import re
import subprocess
import sys

import numpy as np
from pathlib import Path

DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"


def _load_model(model_name: str):
    from mlx_audio.tts.utils import load_model

    return load_model(model_name)


def _split_chunks(text: str, max_chars: int = 180) -> list[str]:
    """Split long English narration at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            words = sentence.split()
            part = ""
            for word in words:
                candidate = f"{part} {word}".strip()
                if part and len(candidate) > max_chars:
                    chunks.append(part)
                    part = word
                else:
                    part = candidate
            if part:
                chunks.append(part)
            current = ""
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _audio_duration(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ])
        return float(out.decode().strip())
    except Exception:
        return 0.0


EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
           "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
           "seventeen", "eighteen", "nineteen"]
EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _en_int(n: int) -> str:
    if n < 20:
        return EN_ONES[n]
    if n < 100:
        return EN_TENS[n // 10] + (("-" + EN_ONES[n % 10]) if n % 10 else "")
    if n < 1000:
        return EN_ONES[n // 100] + " hundred" + ((" " + _en_int(n % 100)) if n % 100 else "")
    for value, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")):
        if n >= value:
            return _en_int(n // value) + " " + name + ((" " + _en_int(n % value)) if n % value else "")
    return str(n)


def _en_number(number: str, unit: str, currency: bool, percent: bool, year: bool) -> str:
    integer, _, decimal = number.partition(".")
    value = int(integer.replace(",", ""))
    if year and 1900 <= value <= 2099 and not decimal and not unit:
        first = value // 100
        last = value % 100
        words = _en_int(first) + " " + (("oh " + EN_ONES[last]) if last < 10 else _en_int(last))
    else:
        words = _en_int(value)
    if decimal:
        words += " point " + " ".join(EN_ONES[int(c)] for c in decimal)
    if unit:
        words += " " + unit
    if currency:
        words += " dollars"
    if percent:
        words += " percent"
    return words


def _verbalize_english(text: str) -> str:
    pattern = re.compile(r"(\$)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(billion|million|trillion|thousand|percent|%)?", re.I)
    def replace(match: re.Match) -> str:
        currency = bool(match.group(1))
        number = match.group(2) + (("." + match.group(3)) if match.group(3) else "")
        unit = (match.group(4) or "").lower()
        percent = unit == "percent" or unit == "%"
        if unit in {"percent", "%"}:
            unit = ""
        year = not unit and not currency and not percent
        return " " + _en_number(number, unit, currency, percent, year) + " "
    return re.sub(r"\s+", " ", pattern.sub(replace, text)).strip()


ZH_DIGITS = "零一二三四五六七八九"
ZH_UNITS = ["", "十", "百", "千"]


def _zh_int(n: int) -> str:
    if n == 0:
        return "零"
    parts = []
    for unit_index in range(3, -1, -1):
        divisor = 10 ** unit_index
        digit = (n // divisor) % 10
        if digit:
            parts.append(ZH_DIGITS[digit] + ZH_UNITS[unit_index])
        elif parts and n % divisor and (n // divisor) % 10 != 0:
            parts.append("零")
    return "".join(parts) or "零"


def _zh_number(number: str, unit: str, percent: bool, year: bool) -> str:
    integer, _, decimal = number.partition(".")
    value = int(integer)
    if year and not decimal and not unit and 1900 <= value <= 2099:
        words = "".join(ZH_DIGITS[int(c)] for c in integer)
    else:
        words = _zh_int(value)
    if decimal:
        words += "点" + "".join(ZH_DIGITS[int(c)] for c in decimal)
    if unit:
        words += unit
    if percent:
        words = "百分之" + words
    return words


def _verbalize_chinese(text: str) -> str:
    pattern = re.compile(r"(\d+(?:,\d{3})*)(?:\.(\d+))?\s*(亿|万|%|年)?")
    def replace(match: re.Match) -> str:
        number = match.group(1).replace(",", "") + (("." + match.group(2)) if match.group(2) else "")
        unit = match.group(3) or ""
        percent = unit == "%"
        year = unit == "年"
        if percent or year:
            unit = ""
        result = _zh_number(number, unit, percent, year)
        if year:
            result += "年"
        return result
    return pattern.sub(replace, text)


def verbalize_numbers(text: str) -> str:
    if re.search(r"[\u3400-\u9fff]", text):
        return _verbalize_chinese(text)
    return _verbalize_english(text)


def _syllables(text: str) -> int:
    total = 0
    for word in re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", text):
        w = word.lower()
        groups = re.findall(r"[aeiouy]+", w)
        count = len(groups)
        if w.endswith("e") and count > 1 and not w.endswith(("le", "ee")):
            count -= 1
        total += max(1, count)
    return total


def _speech_seconds(path: Path) -> float:
    duration = _audio_duration(path)
    if duration <= 0:
        return 0.0
    try:
        log = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "silencedetect=noise=-35dB:d=0.08", "-f", "null", "-",
        ], capture_output=True, text=True).stderr
        silence = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log))
        return max(0.1, duration - silence)
    except Exception:
        return duration


def _token_cap(text: str) -> int:
    """Estimate a safe generation cap for English or CJK text.

    Qwen3 emits roughly 12-13 audio tokens per second. Chinese has no spaces,
    so a word count would collapse to one and truncate the sample; estimate
    Mandarin duration from CJK character count instead (about 4.5 chars/sec).
    """
    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_words = max(1, len(text.split()))
    seconds = max(
        latin_words / 160.0 * 60.0,
        cjk_chars / 4.5 if cjk_chars else 0.0,
    )
    return max(160, int(seconds * 13.0 * 1.35) + 48)


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
    parser.add_argument("--target-wpm", type=float, default=0.0, help="post-process to this English WPM; 0 disables")
    parser.add_argument("--target-syllables-per-sec", type=float, default=0.0, help="normalize speech-only syllable rate")
    parser.add_argument("--max-chunk-chars", type=int, default=180)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-tokens", type=int, help="override per-job token cap")
    parser.add_argument("--seed", type=int, default=44)
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
        text = re.sub(r"\ba16z\b", "Andreessen Horowitz", text, flags=re.IGNORECASE)
        text = verbalize_numbers(text)
        out = Path(job.get("out") or "")
        if not text or not out:
            failures.append(f"{job_id}: missing text or out")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{len(jobs)}] {job_id}", file=sys.stderr)
        try:
            # Cap generation at ~1.35x the expected duration so a bad sample
            # cannot loop for minutes. CJK text is measured by characters.
            chunks = _split_chunks(text, args.max_chunk_chars)
            pieces = []
            sample_rate = None
            for chunk in chunks:
                max_tokens = args.max_tokens or _token_cap(chunk)
                results = list(
                    model.generate(
                        text=chunk,
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
                sample_rate = result.sample_rate
                pieces.append(np.asarray(result.audio).reshape(-1))
            if sample_rate is None or not pieces:
                raise RuntimeError("model returned no audio")
            if len(pieces) > 1:
                silence = np.zeros(int(0.12 * sample_rate), dtype=pieces[0].dtype)
                joined = [pieces[0]]
                for piece in pieces[1:]:
                    joined.extend([silence, piece])
                audio = np.concatenate(joined)
            else:
                audio = pieces[0]
            audio_write(str(out), audio, sample_rate)
            # Normalize every cue to a common broadcast loudness. This also
            # prevents one Qwen cue from sitting much hotter than its neighbour.
            try:
                loud_tmp = out.with_suffix(".loud.wav")
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(out),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
                    "-ar", str(sample_rate), "-ac", "1", str(loud_tmp),
                ], check=True)
                loud_tmp.replace(out)
            except Exception as exc:  # noqa: BLE001
                print(f"warning: loudness normalization failed: {exc}", file=sys.stderr)
                try: loud_tmp.unlink()
                except OSError: pass
            duration = _audio_duration(out)
            if args.target_wpm > 0:
                words = len(re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", text))
                for pass_index in range(2):
                    if words < 8 or duration <= 0:
                        break
                    current = words / duration * 60.0
                    if current > 260 or current < 80:
                        raise RuntimeError(f"invalid TTS pace ({current:.0f} wpm); refusing extreme stretch")
                    factor = args.target_wpm / current
                    if factor < 0.5 or factor > 2.0:
                        raise RuntimeError(f"invalid TTS pace correction {factor:.2f}x")
                    if abs(factor - 1.0) < 0.01:
                        break
                    tmp = out.with_suffix(f".pace{pass_index}.wav")
                    try:
                        subprocess.run([
                            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(out),
                            "-filter:a", f"atempo={max(0.5, min(2.0, factor)):.6f}",
                            "-ar", str(sample_rate), "-ac", "1", str(tmp),
                        ], check=True)
                        tmp.replace(out)
                        duration = _audio_duration(out)
                        print(f"  pace {current:.1f} -> {args.target_wpm:.1f} wpm ({factor:.3f}x, pass {pass_index + 1})", file=sys.stderr)
                    except Exception as exc:  # noqa: BLE001
                        print(f"warning: pace adjustment failed: {exc}", file=sys.stderr)
                        try: tmp.unlink()
                        except OSError: pass
                        break
            if args.target_syllables_per_sec > 0:
                syllables = _syllables(text)
                for pass_index in range(2):
                    speech = _speech_seconds(out)
                    if syllables < 8 or speech <= 0:
                        break
                    current = syllables / speech
                    if current > 7.8 or current < 3.0:
                        raise RuntimeError(f"invalid syllable rate ({current:.2f}/s); refusing extreme stretch")
                    factor = args.target_syllables_per_sec / current
                    if factor < 0.5 or factor > 2.0:
                        raise RuntimeError(f"invalid syllable correction {factor:.2f}x")
                    if abs(factor - 1.0) < 0.01:
                        break
                    tmp = out.with_suffix(f".syl{pass_index}.wav")
                    try:
                        subprocess.run([
                            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(out),
                            "-filter:a", f"atempo={max(0.5, min(2.0, factor)):.6f}",
                            "-ar", str(sample_rate), "-ac", "1", str(tmp),
                        ], check=True)
                        tmp.replace(out)
                        duration = _audio_duration(out)
                        print(f"  syllables {current:.2f} -> {args.target_syllables_per_sec:.2f}/s ({factor:.3f}x, pass {pass_index + 1})", file=sys.stderr)
                    except Exception as exc:  # noqa: BLE001
                        print(f"warning: syllable pacing failed: {exc}", file=sys.stderr)
                        try: tmp.unlink()
                        except OSError: pass
                        break
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
