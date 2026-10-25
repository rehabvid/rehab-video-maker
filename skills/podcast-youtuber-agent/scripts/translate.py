#!/usr/bin/env python3
"""Translate a finished deck and its YouTube metadata into Simplified Chinese.

The editorial writer is already an OpenCode agent, so translation reuses the
same local agent rather than adding a cloud translation dependency.  The agent
writes two files next to the originals:

    slides.zh.json
    youtube.zh.json

Only human-visible text is translated.  Shot ids, kinds, visual/chart objects,
URLs, numbers, timestamps and render settings are preserved.  The caller should
run the normal JSON validators after this script succeeds.

Usage::

    uv run python skills/podcast-youtuber-agent/scripts/translate.py \
      --slides build/ep01/slides.json \
      --youtube build/ep01/youtube.json \
      --out-dir build/ep01 --model opencode-go/deepseek-v4.1-flash
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FIELDS = [
    "narration",
    "heading",
    "kicker",
    "on_screen",
    "subtitle",
    "quote",
    "attribution",
    "question",
    "next_text",
]


def _load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _prompt(slides: Path, youtube: Path, out_slides: Path, out_youtube: Path) -> str:
    return f"""You are a professional English-to-Simplified-Chinese translator and
localization editor. Work only on these files:

English deck: {slides}
English YouTube metadata: {youtube}

Write exactly two valid UTF-8 JSON files:

1. {out_slides}
2. {out_youtube}

For the deck:

- Preserve the complete JSON structure, every key, every shot id, `kind`,
  `fps`, `engine`, `voice_profile`, and the entire `visual` object exactly.
- Translate only human-visible strings in these fields when present:
  `title`, `narration`, `heading`, `bullets` (each item), `kicker`,
  `on_screen`, `subtitle`, `quote`, `attribution`, `question`, `next_text`.
- Do not translate names, ticker symbols, URLs, dates, numbers, units, or
  chart data. Keep chart `data.categories` and `series` labels readable in
  Chinese where they are plain labels, but never change numeric values.
- Use natural spoken Simplified Chinese, not a literal word-for-word gloss.
  Keep each `narration` suitable for about the same speaking time as the
  English source. Do not add facts, opinions, headings, or commentary.
- `attribution` may stay in the original language when it is a proper name.
- Keep every `bullets` array the same length.

For the YouTube metadata:

- Preserve the full structure and all non-text values.
- Translate `title`, `description`, each `chapters[].title`, and `tags` into
  Simplified Chinese. Keep URLs, timestamps, numbers, source names and the
  AI-disclosure meaning intact.
- Set `defaultLanguage` and `defaultAudioLanguage` to `zh-Hans`.
- Keep `privacyStatus` as `private` unless the source already says otherwise.
- Keep `containsSyntheticMedia` true.
- Do not put English-only boilerplate back into the Chinese title/description.

Write both files, then verify each parses as JSON. Do not run audio, render or
upload commands. Stop after both files are valid.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True, help="English slides.json")
    parser.add_argument("--youtube", required=True, help="English youtube.json")
    parser.add_argument("--out-dir", help="output directory; defaults to slides parent")
    parser.add_argument("--model", default="opencode-go/deepseek-v4.1-flash")
    parser.add_argument("--log")
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args(argv)

    slides = Path(args.slides).resolve()
    youtube = Path(args.youtube).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else slides.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_slides = out_dir / "slides.zh.json"
    out_youtube = out_dir / "youtube.zh.json"
    log_path = Path(args.log).resolve() if args.log else out_dir / "translate.log"

    _load(slides)
    _load(youtube)
    prompt = _prompt(slides, youtube, out_slides, out_youtube)

    for attempt in range(1, args.attempts + 1):
        with log_path.open("a") as handle:
            handle.write(f"\n=== translation attempt {attempt} ===\n")
            handle.flush()
            code = subprocess.run(
                [
                    "opencode", "run", "--auto", "--model", args.model,
                    "--title", f"translate-zh-{slides.parent.name}-{attempt}", prompt,
                ],
                cwd=slides.parent, stdout=handle, stderr=subprocess.STDOUT, text=True,
            ).returncode
        if code == 0 and out_slides.exists() and out_youtube.exists():
            try:
                zh_slides = _load(out_slides)
                zh_youtube = _load(out_youtube)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"translation produced invalid JSON: {exc}", file=sys.stderr)
                continue
            en_slides = _load(slides)
            en_shots = en_slides.get("shots") or []
            zh_shots = zh_slides.get("shots") or []
            if len(en_shots) != len(zh_shots):
                print("translation changed the number of shots", file=sys.stderr)
                continue
            if [str(s.get("id")) for s in en_shots] != [str(s.get("id")) for s in zh_shots]:
                print("translation changed shot ids", file=sys.stderr)
                continue
            if not str(zh_youtube.get("title") or "").strip():
                print("translation produced an empty Chinese title", file=sys.stderr)
                continue
            zh_slides["language"] = "zh-Hans"
            _save(out_slides, zh_slides)
            print(f"wrote {out_slides}")
            print(f"wrote {out_youtube}")
            return 0
        print(f"translation attempt {attempt} failed; see {log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
