#!/usr/bin/env python3
"""TTS-only Mandarin pronunciation overrides for finance and technology terms.

Chinese heteronyms are context sensitive.  Qwen3-TTS and Edge TTS sometimes
choose the wrong reading for common investment/technology phrases, for example
``重定价`` (chóng, not zhòng), ``行业`` (háng, not xíng), ``利差`` (chā, not
chà) or ``调用`` (diào, not tiáo).

The narration pipeline keeps the original Chinese in captions and metadata but
sends a pronunciation-only variant to the TTS engine.  The lexicon uses
same-sounding characters or an unambiguous paraphrase, so the spoken result is
correct without changing what viewers read.

Use a per-shot ``tts_text`` field for one-off names or terms that are not in the
shared lexicon.  The shared lexicon lives in
``config/pronunciation.zh.json``; entries are
``[original, spoken, pinyin, note]``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE.parent / "config" / "pronunciation.zh.json"
CJK = re.compile(r"[\u3400-\u9fff]")


def _as_term(item) -> dict | None:
    if isinstance(item, dict):
        match = str(item.get("match") or "").strip()
        say = str(item.get("say") or "").strip()
        pinyin = str(item.get("pinyin") or "").strip()
        note = str(item.get("note") or "").strip()
    elif isinstance(item, (list, tuple)) and len(item) >= 2:
        match = str(item[0] or "").strip()
        say = str(item[1] or "").strip()
        pinyin = str(item[2] or "").strip() if len(item) > 2 else ""
        note = str(item[3] or "").strip() if len(item) > 3 else ""
    else:
        return None
    if not match or not say or match == say:
        return None
    return {"match": match, "say": say, "pinyin": pinyin, "note": note}


@lru_cache(maxsize=8)
def _load_terms_cached(path: str) -> tuple[dict, ...]:
    data = json.loads(Path(path).read_text())
    raw_terms = data.get("terms") if isinstance(data, dict) else data
    if not isinstance(raw_terms, list):
        raise ValueError(f"{path}: terms must be a JSON list")
    by_match: dict[str, dict] = {}
    for item in raw_terms:
        term = _as_term(item)
        if term:
            # Last duplicate wins, matching a normal JSON merge expectation.
            by_match[term["match"]] = term
    terms = sorted(by_match.values(), key=lambda term: len(term["match"]), reverse=True)
    return tuple(terms)


def load_terms(config: str | Path | None = None) -> tuple[dict, ...]:
    path = Path(config).resolve() if config else DEFAULT_CONFIG.resolve()
    return _load_terms_cached(str(path))


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ""))


def _pattern(terms: tuple[dict, ...]) -> re.Pattern[str] | None:
    if not terms:
        return None
    # Longest first so 重定价 wins over 重, and 杠杆率 over 杠杆.
    return re.compile("|".join(re.escape(term["match"]) for term in terms))


@lru_cache(maxsize=8)
def _pattern_cached(path: str) -> re.Pattern[str] | None:
    return _pattern(_load_terms_cached(path))


def prepare_tts_text(
    text: str,
    config: str | Path | None = None,
) -> tuple[str, list[dict]]:
    """Return ``(tts_text, applied_terms)`` for one narration beat.

    Non-Chinese text is returned unchanged.  The original string is never used
    for captions; callers should retain it separately.
    """
    text = text or ""
    if not has_cjk(text):
        return text, []
    path = str(Path(config).resolve() if config else DEFAULT_CONFIG.resolve())
    pattern = _pattern_cached(path)
    terms = load_terms(path)
    if pattern is None:
        return text, []
    by_match = {term["match"]: term for term in terms}
    applied: list[dict] = []

    def replace(match: re.Match[str]) -> str:
        term = by_match[match.group(0)]
        applied.append(dict(term))
        return term["say"]

    return pattern.sub(replace, text), applied


def audit_text(text: str, config: str | Path | None = None) -> list[dict]:
    """Return the lexicon terms that would be applied to ``text``."""
    return prepare_tts_text(text, config)[1]


def _collect_shots(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list):
        raise ValueError(f"{path}: expected a slides object with a shots list")
    return shots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="text to inspect")
    parser.add_argument("--text-file", help="UTF-8 file containing text")
    parser.add_argument("--slides", help="slides.zh.json to inspect")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="lexicon JSON")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--list", action="store_true", help="list lexicon entries")
    args = parser.parse_args(argv)

    terms = load_terms(args.config)
    if args.list:
        print(json.dumps(list(terms), ensure_ascii=False, indent=2))
        return 0

    text = args.text or ""
    if args.text_file:
        text = Path(args.text_file).read_text()
    if args.slides:
        shots = _collect_shots(Path(args.slides))
        report = []
        for shot in shots:
            original = str(shot.get("narration") or "")
            explicit = str(shot.get("tts_text") or "").strip()
            if explicit:
                tts_text, applied, source = explicit, [], "explicit"
            else:
                tts_text, applied = prepare_tts_text(original, args.config)
                source = "lexicon"
            if applied or tts_text != original:
                report.append({
                    "id": str(shot.get("id") or ""),
                    "original": original,
                    "tts_text": tts_text,
                    "source": source,
                    "applied": applied,
                })
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            if not report:
                print("no pronunciation overrides")
            for item in report:
                print(f"[{item['id']}] {item['original']}")
                print(f"  -> {item['tts_text']}")
                for term in item["applied"]:
                    print(f"     {term['match']} -> {term['say']} ({term['pinyin']})")
        return 0

    if not text:
        parser.error("provide --text, --text-file or --slides")
    tts_text, applied = prepare_tts_text(text, args.config)
    if args.json:
        print(json.dumps({
            "original": text,
            "tts_text": tts_text,
            "applied": applied,
        }, ensure_ascii=False, indent=2))
    else:
        print(tts_text)
        for term in applied:
            print(f"  {term['match']} -> {term['say']} ({term['pinyin']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
