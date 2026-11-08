#!/usr/bin/env python3
"""Detect suspicious TTS cues with speech recognition and timing checks.

This is a gate, not a pronunciation oracle. It catches truncated/looping cues,
dropped or extra words, repeated words/phrases, extreme pace and bad levels.
A human still has to judge accent, timbre and naturalness.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


_ZH_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_ZH_UNITS = {"十": 10, "百": 100, "千": 1000}


def _zh_int(value: str) -> int:
    total = 0
    number = 0
    for char in value:
        if char in _ZH_DIGITS:
            number = _ZH_DIGITS[char]
        else:
            total += (number or 1) * _ZH_UNITS[char]
            number = 0
    return total + number


def _zh_compact(value: str) -> str:
    """Keep magnitudes compact so both sides normalize to e.g. 25亿, not 2500000000."""
    for unit in ("亿", "万"):
        if unit in value:
            left, right = value.split(unit, 1)
            head = _zh_compact(left) if left else "1"
            return head + unit + (_zh_compact(right) if right else "")
    return str(_zh_int(value))


_EN_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_EN_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_EN_DECADES = {
    "twenties": "20s", "thirties": "30s", "forties": "40s", "fifties": "50s",
    "sixties": "60s", "seventies": "70s", "eighties": "80s", "nineties": "90s",
}


def _en_number_words(text: str) -> str:
    """Turn spelled-out numbers into digits so ASR ("75%") and the script
    ("seventy-five percent") are not scored as a long substitution run."""
    text = text.replace("$", " ").replace(",", "")
    # "three-point-four" and "three point four" must both become "3.4".
    text = re.sub(r"[- ]point[- ]", " point ", text)
    # "a hundred and eighty-four" is one number, not 100 + 84.
    text = re.sub(r"\ba\s+hundred\b", "one hundred", text)
    text = re.sub(
        r"\b(one|two|three|four|five|six|seven|eight|nine|\d+)\s+hundred\s+and\s+",
        r"\1 hundred ",
        text,
    )
    def century_decade(match: re.Match) -> str:
        prefix = "19" if match.group(1) == "nineteen" else "18"
        return prefix + _EN_DECADES[match.group(2)]

    text = re.sub(
        r"\b(nineteen|eighteen)[- ](" + "|".join(_EN_DECADES) + r")\b",
        century_decade,
        text,
    )
    for word, digits in _EN_DECADES.items():
        text = re.sub(rf"\b{word}\b", digits, text)

    def compound(match: re.Match) -> str:
        return str(_EN_TENS[match.group(1)] + _EN_UNITS[match.group(2)])

    text = re.sub(
        r"\b(" + "|".join(_EN_TENS) + r")[- ](" + "|".join(_EN_UNITS) + r")\b",
        compound, text,
    )

    def hundred(match: re.Match) -> str:
        return str(int(match.group(1)) * 100)

    text = re.sub(r"\b(\d+)\s+hundred\b", hundred, text)
    text = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine)\s+hundred\b",
                  lambda m: str(_EN_UNITS[m.group(1)] * 100), text)
    for word, value in sorted(_EN_TENS.items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b{word}\b", str(value), text)
    for word, value in sorted(_EN_UNITS.items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b{word}\b", str(value), text)
    text = re.sub(r"(\d+)\s+point\s+(\d+)", r"\1.\2", text)

    def combine_hundreds(match: re.Match) -> str:
        head, tail = int(match.group(1)), int(match.group(2))
        return str(head + tail) if head % 100 == 0 else match.group(0)

    text = re.sub(r"\b(\d+)[- ]hundred\b", lambda m: str(int(m.group(1)) * 100)
                  if int(m.group(1)) < 10 else m.group(0), text)
    text = re.sub(r"\b(\d{3})\s+(\d{1,2})\b", combine_hundreds, text)

    def scale_numbers(match: re.Match) -> str:
        return str(int(match.group(1)) * int(match.group(3)))

    for unit, factor in (("thousand", 1000), ("million", 1_000_000),
                         ("billion", 1_000_000_000), ("trillion", 1_000_000_000_000)):
        text = re.sub(
            rf"(\d+(?:\.\d+)?)[- ]{unit}\b",
            lambda m, f=factor: str(int(float(m.group(1)) * f)),
            text,
        )
    text = re.sub(r"\bper ?cent\b", " ", text)
    # Currency units add/remove a token depending on the ASR; the number is
    # what matters, so drop the unit words on both sides.
    text = re.sub(r"\b(dollars?|cents?|bucks?)\b", " ", text)
    # ASR commonly writes the near-homophone for this company
    text = re.sub(r"\b(exxon|exon)\b", "axon", text)
    return text


def _normalise(text: str, language: str) -> list[str]:
    text = text.lower()
    if language.lower().startswith(("zh", "cmn", "mandarin")):
        # Whisper usually writes Arabic digits while the deck uses Chinese
        # numerals. Normalize both sides so a correct "二十五亿" is not scored
        # as three substitutions against "25亿". Keep the magnitude suffix
        # compact; expanding it produces long runs of zeros that look like a
        # repeated-word artifact to the stutter check.
        text = text.replace("百分之", "")
        text = re.sub(
            r"(?<!\d)[零〇一二两三四五六七八九十百千万亿]+",
            lambda match: _zh_compact(match.group(0)),
            text,
        )
        # Mixed-script names are transliterated inconsistently by Whisper
        # (Casado/Karsado, Anderson/Andreason). Ignore Latin runs for the
        # Chinese CER so a correct Chinese line is not failed by name spelling,
        # while keeping every Chinese character and digit under test.
        text = re.sub(r"[A-Za-z]+", " ", text)
        return list(re.sub(r"[^\u3400-\u9fff0-9]", "", text))
    return re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?", _en_number_words(text))


def _distance(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, item in enumerate(a, start=1):
        current = [i]
        for j, other in enumerate(b, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (item != other)))
        previous = current
    return previous[-1]


def _duration(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ])
        return float(out.decode().strip())
    except Exception:
        return 0.0


def _levels(path: Path) -> tuple[float, float]:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        mean = re.search(r"mean_volume: ([-\d.]+)", result.stderr)
        peak = re.search(r"max_volume: ([-\d.]+)", result.stderr)
        return (float(mean.group(1)) if mean else -99.0, float(peak.group(1)) if peak else -99.0)
    except Exception:
        return (-99.0, -99.0)


def _asr(path: Path, voice_python: Path, language: str, model: str, temp: Path) -> str:
    out = temp / (path.stem + "-asr")
    cmd = [
        str(voice_python), "-m", "mlx_audio.stt.generate",
        "--model", model, "--audio", str(path), "--output-path", str(out),
        "--format", "json", "--language", "zh" if language.lower().startswith(("zh", "cmn", "mandarin")) else "en",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    data = json.loads(out.with_suffix(".json").read_text())
    return str(data.get("text") or "")


def _repeat_flags(tokens: list[str], language: str) -> list[str]:
    flags: list[str] = []
    zh = language.lower().startswith(("zh", "cmn", "mandarin"))
    if not zh:
        # "earnings, earnings lift..." is grammatical; only flag a double
        # repeat of a function word, or any three-in-a-row stutter.
        stutter_words = {
            "the", "and", "a", "an", "to", "of", "in", "is", "it", "that",
            "this", "for", "on", "with", "as", "at", "but", "or", "if",
            "was", "were", "be", "been", "so", "we", "i",
        }
        for i in range(len(tokens) - 2):
            if tokens[i] == tokens[i + 1] == tokens[i + 2]:
                flags.append("three repeated words: " + tokens[i])
                break
        else:
            for i in range(len(tokens) - 1):
                if tokens[i] == tokens[i + 1] and tokens[i] in stutter_words:
                    flags.append("consecutive repeated word: " + tokens[i])
                    break
    else:
        # Chinese reduplication is normal; only flag three identical characters.
        for i in range(len(tokens) - 2):
            if tokens[i] == tokens[i + 1] == tokens[i + 2] and re.fullmatch(r"[\u3400-\u9fff]", tokens[i]):
                flags.append("three repeated characters: " + tokens[i])
                break
    # Repeated two- or three-token phrase, e.g. "it is it is".
    # Two-word rhetorical repetition ("share prices, share prices") is common
    # in English; only a three-token repeat is a reliable stutter signal.
    for size in (3,):
        if zh and size == 2 and all(len(t) == 1 for t in tokens):
            # Two repeated Chinese characters are common; require a 3-char run
            # or a longer repeated phrase instead.
            continue
        for i in range(0, len(tokens) - size * 2 + 1):
            first = tokens[i:i + size]
            second = tokens[i + size:i + size * 2]
            if all(token.isdigit() for token in first):
                continue
            if first == second:
                flags.append("repeated phrase: " + " ".join(first))
                return flags
    return flags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", required=True)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--voice-python", default=".venv-voice/bin/python")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", required=True)
    parser.add_argument("--wer-threshold", type=float, default=0.30)
    parser.add_argument("--cer-threshold", type=float, default=0.15)
    parser.add_argument("--min-wpm", type=float, default=105)
    parser.add_argument("--max-wpm", type=float, default=220)
    parser.add_argument("--min-cps", type=float, default=2.0)
    parser.add_argument("--max-cps", type=float, default=7.5)
    parser.add_argument("--limit", type=int, default=0, help="debug: check only first N cues")
    args = parser.parse_args(argv)

    slides = _load(Path(args.slides))
    by_id = {str(s.get("id")): s for s in slides.get("shots", [])}
    audio_dir = Path(args.audio_dir)
    voice_python = Path(args.voice_python)
    if not voice_python.exists():
        print(f"error: voice python not found: {voice_python}", file=sys.stderr)
        return 1
    ids = sorted(by_id)
    if args.limit:
        ids = ids[:args.limit]
    results = []
    problems = 0
    for index, sid in enumerate(ids, start=1):
        path = audio_dir / f"shot-{sid}.wav"
        if not path.exists():
            results.append({"id": sid, "errors": ["missing audio"], "warnings": []})
            problems += 1
            continue
        expected_text = str(by_id[sid].get("narration") or "")
        if not expected_text:
            continue
        try:
            with tempfile.TemporaryDirectory(prefix=f"qa-{sid}-") as tmp:
                actual_text = _asr(path, voice_python, args.language, args.model, Path(tmp))
            expected = _normalise(expected_text, args.language)
            actual = _normalise(actual_text, args.language)
            distance = _distance(expected, actual)
            error_rate = distance / max(1, len(expected))
            duration = _duration(path)
            words = len(re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", expected_text))
            wpm = words / duration * 60 if duration > 0 else 0
            is_zh = args.language.lower().startswith(("zh", "cmn", "mandarin"))
            cjk_chars = len(re.findall(r"[\u3400-\u9fff]", expected_text)) if is_zh else 0
            cps = cjk_chars / duration if duration > 0 else 0
            mean_db, peak_db = _levels(path)
            errors = []
            warnings = []
            if duration < 1.0:
                errors.append(f"audio too short ({duration:.2f}s)")
            if not actual:
                errors.append("ASR returned no speech")
            if error_rate > (args.cer_threshold if args.language.lower().startswith(("zh", "cmn", "mandarin")) else args.wer_threshold):
                errors.append(f"ASR mismatch {error_rate:.1%}: {actual_text[:160]}")
            elif error_rate > 0.25:
                warnings.append(f"possible ASR/pronunciation mismatch {error_rate:.1%}")
            if duration:
                if is_zh and cjk_chars >= 12:
                    if cps < args.min_cps or cps > args.max_cps:
                        errors.append(f"character pace outside range ({cps:.2f} chars/s, {duration:.2f}s)")
                elif words >= 8 and (wpm < args.min_wpm or wpm > (args.max_wpm if duration >= 8 else max(args.max_wpm, 240))):
                    errors.append(f"pace outside range ({wpm:.0f} wpm, {duration:.2f}s)")
            if not is_zh:
                # Tokens must stay separated: joining "5" and "2026" with no
                # space creates a fake 52026 and reports the year as missing.
                expected_numbers = re.findall(r"\d+(?:\.\d+)?", " ".join(expected))
                actual_numbers = re.findall(r"\d+(?:\.\d+)?", " ".join(actual))
                if expected_numbers:
                    missing_numbers = [n for n in expected_numbers if n not in actual_numbers]
                    if missing_numbers:
                        errors.append("missing/misread numbers: " + ", ".join(missing_numbers[:6]))
            flags = _repeat_flags(actual, args.language)
            if flags:
                errors.extend(flags)
            if peak_db > -0.15:
                warnings.append(f"peak near full scale ({peak_db:.1f} dBFS)")
            if mean_db < -32:
                warnings.append(f"very quiet cue ({mean_db:.1f} dBFS)")
            if words >= 8 and actual and len(actual) < words * 0.55:
                errors.append(f"possible truncation: {len(actual)} ASR tokens vs {words} expected")
            status = "fail" if errors else "pass"
            if errors:
                problems += 1
            results.append({
                "id": sid, "status": status, "wer": round(error_rate, 4),
                "duration": round(duration, 2), "wpm": round(wpm, 1), "cps": round(cps, 2),
                "mean_dbfs": mean_db, "peak_dbfs": peak_db,
                "expected": expected_text, "asr": actual_text,
                "errors": errors, "warnings": warnings,
            })
            print(f"[{index}/{len(ids)}] {sid}: {status} wer={error_rate:.1%} {duration:.1f}s", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            problems += 1
            results.append({"id": sid, "status": "error", "errors": [str(exc)], "warnings": []})
            print(f"[{index}/{len(ids)}] {sid}: error {exc}", file=sys.stderr)
    report = {
        "language": args.language, "audio_dir": str(audio_dir),
        "slides": str(args.slides), "checked": len(results),
        "problems": problems, "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checked": len(results), "problems": problems, "out": str(out)}, ensure_ascii=False))
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
