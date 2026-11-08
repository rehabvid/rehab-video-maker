#!/usr/bin/env python3
"""Syllable-aware viseme track for the SVG host.

Distributes each narration syllable across its shot duration and maps it to a
small viseme set. No forced alignment required; the track stays inside the
measured shot timing, so it cannot drift across scenes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CJK = re.compile(r"[\u3400-\u9fff]")
LATIN = re.compile(r"[A-Za-z]+")

# Mandarin finals / initials -> viseme
ZH_VOWEL = {
    "a": "aa", "ai": "aa", "ao": "aa", "an": "aa", "ang": "aa",
    "o": "oh", "ou": "ou", "ong": "oh",
    "e": "oh", "ei": "ee", "en": "oh", "eng": "oh", "er": "oh",
    "i": "ih", "ia": "ih", "ie": "ih", "iao": "ih", "iu": "ou",
    "ian": "ih", "in": "ih", "iang": "ih", "ing": "ih", "iong": "ih",
    "u": "ou", "ua": "aa", "uo": "oh", "uai": "aa", "ui": "ou",
    "uan": "aa", "un": "ou", "uang": "aa", "ueng": "oh",
    "v": "ou", "ve": "oh", "van": "aa", "vn": "ou",
}
EN_VOWEL = {
    "a": "aa", "e": "ee", "i": "ih", "o": "oh", "u": "ou", "y": "ih",
}


def _zh_viseme(char: str) -> str:
    # Cheap but stable: derive from pinyin if available, else the character's
    # Unicode order is meaningless, so default to a middle vowel.
    try:
        from pypinyin import lazy_pinyin  # type: ignore
        pinyin = lazy_pinyin(char)[0]
    except Exception:  # noqa: BLE001
        return "aa"
    pinyin = pinyin.lower().replace("ü", "v")
    for final in sorted(ZH_VOWEL, key=len, reverse=True):
        if pinyin.endswith(final):
            return ZH_VOWEL[final]
    return "aa"


def _en_syllables(word: str) -> list[str]:
    groups = re.findall(r"[aeiouy]+", word.lower())
    return [g[0] for g in groups] or ["e"]


def _syllables(text: str) -> list[str]:
    """Return visemes in spoken order, one per syllable."""
    out: list[str] = []
    for chunk in re.split(r"([\u3400-\u9fff])", text):
        if not chunk:
            continue
        if CJK.match(chunk):
            out.append(_zh_viseme(chunk))
        else:
            for word in LATIN.findall(chunk):
                out.extend(EN_VOWEL.get(v, "aa") for v in _en_syllables(word))
    return out


def build(slides_path: Path, timing_path: Path, fps: int,
          offset: float = 0.0, frames: int | None = None) -> list[str | None]:
    slides = json.loads(slides_path.read_text())
    timing = json.loads(timing_path.read_text())
    by_id = {str(s.get("id")): s for s in slides.get("shots", [])}
    total = float(timing.get("duration") or 0) or max(
        (float(s.get("start", 0)) + float(s.get("duration", 0)) for s in timing.get("shots", [])),
        default=0,
    )
    n = frames or int(total * fps)
    track: list[str | None] = [None] * (n + 1)
    for shot in timing.get("shots", []):
        sid = str(shot.get("id"))
        text = str((by_id.get(sid) or {}).get("narration") or "")
        visemes = _syllables(text)
        if not visemes:
            continue
        start = float(shot.get("start") or 0)
        dur = float(shot.get("duration") or 0)
        step = dur / len(visemes)
        for i, viseme in enumerate(visemes):
            t0 = start + i * step
            t1 = t0 + step * 0.92  # brief closure between syllables
            a = max(0, int((t0 - offset) * fps))
            b = max(a, int((t1 - offset) * fps))
            for f in range(a, min(n, b + 1)):
                track[f] = viseme
    return track
