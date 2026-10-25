#!/usr/bin/env python3
"""Draft, validate and plan a b-roll-only podcast slideshow.

This is the production layer for the script written by the
``podcast-youtuber-agent`` skill.  It deliberately has no avatar shot: every
beat becomes a b-roll clip/image or a generated title/chart/quote/end card.

Commands::

    python3 scripts/slides.py draft --script build/ep01/script.txt \
        --out build/ep01/slides.json --visuals assets/ep01
    python3 scripts/slides.py validate build/ep01/slides.json
    python3 scripts/slides.py plan build/ep01/slides.json \
        --out build/ep01/plan.md

The generated file is a starting point.  Replace the heuristic headings and
bullets with the real argument, add the podcast cover and guest images, and
verify every factual claim before rendering.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Share the measured-timeline and card renderer with the avatar skill.  Keeping
# one implementation avoids two subtly different caption/timing systems.
SHARED = Path(__file__).resolve().parents[2] / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lib import estimate_seconds, load_json, save_json, slugify  # noqa: E402

KINDS = {"broll", "quote", "chart", "title", "end"}
VISUAL_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".m4v",
}
MAX_NARRATION_CHARS = 340
TARGET_MIN_MINUTES = 10.0
TARGET_MAX_MINUTES = 15.0
TARGET_WPM = 160


def _clean_script(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"\*(.*?)\*", r"\1", line)
        lines.append(line)
    return " ".join(lines)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _split_long(sentence: str, limit: int = MAX_NARRATION_CHARS) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    parts: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _beats(sentences: list[str], max_words: int) -> list[str]:
    units: list[str] = []
    for sentence in sentences:
        units.extend(_split_long(sentence))
    chunks: list[str] = []
    current: list[str] = []
    for unit in units:
        candidate = current + [unit]
        text = " ".join(candidate)
        if current and (
            len(text.split()) > max_words or len(text) > MAX_NARRATION_CHARS
        ):
            chunks.append(" ".join(current))
            current = [unit]
        else:
            current = candidate
    if current:
        chunks.append(" ".join(current))
    return chunks


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _collect_visuals(directory: str | None) -> list[str]:
    if not directory:
        return []
    base = Path(directory)
    if not base.exists():
        raise FileNotFoundError(f"visuals directory not found: {base}")
    found: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VISUAL_SUFFIXES:
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        found.append(_relative(path))
    return found


def _s(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _short(text: str, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def _heading(text: str, words: int = 7) -> str:
    bits = re.sub(r"[^\w\s'’-]", "", text).split()
    return " ".join(bits[:words]).strip().title() or "The Idea"


def _bullets(text: str, limit: int = 3) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(parts) < limit:
        parts += [part.strip() for part in re.split(r";\s+|,\s+", text) if part.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        item = _short(part, 92)
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) == limit:
            break
    return out or ["The argument in one slide"]


def draft(args) -> int:
    script_path = Path(args.script)
    script = _clean_script(script_path.read_text())
    sentences = _sentences(script)
    if not sentences:
        print("error: script is empty", file=sys.stderr)
        return 1

    beats = _beats(sentences, args.max_words)
    visuals = _collect_visuals(args.visuals)
    title = args.title or _short(" ".join(script.split()[:10]), 64).title()
    slug = args.slug or slugify(script_path.stem)

    shots: list[dict] = []
    for index, beat in enumerate(beats):
        sid = f"{index + 1:02d}"
        first = index == 0
        last = index == len(beats) - 1

        if first:
            kind = "title"
            shot = {
                "id": sid,
                "kind": kind,
                "narration": beat,
                "on_screen": title,
                "subtitle": args.subtitle or "A podcast commentary",
                "kicker": args.kicker,
            }
        elif last:
            kind = "end"
            question = _short(beat, 180)
            shot = {
                "id": sid,
                "kind": kind,
                "narration": beat,
                "heading": "What do you think?",
                "question": question,
                "next_text": args.next_text,
            }
        elif visuals:
            kind = "broll"
            shot = {
                "id": sid,
                "kind": kind,
                "narration": beat,
                "on_screen": _heading(beat),
                "visual": visuals[(index - 1) % len(visuals)],
            }
        else:
            kind = "chart"
            shot = {
                "id": sid,
                "kind": kind,
                "narration": beat,
                "heading": _heading(beat),
                "bullets": _bullets(beat),
                "kicker": "THE IDEA",
            }

        shot["transition"] = "cut"
        if first and visuals:
            shot["visual"] = visuals[0]
        elif last and visuals:
            shot["visual"] = visuals[-1]
        shots.append(shot)

    data = {
        "slug": slug,
        "title": title,
        "voice": args.voice,
        "voice_profile": args.voice_profile,
        "engine": args.engine,
        "fps": args.fps,
        "format": "broll-slides",
        "shots": shots,
    }
    save_json(Path(args.out), data)

    total = sum(estimate_seconds(shot["narration"], args.wpm) for shot in shots)
    broll = sum(1 for shot in shots if shot["kind"] == "broll")
    print(
        f"wrote {args.out}: {len(shots)} slides, {broll} b-roll, "
        f"~{total / 60:.1f} min at {args.wpm} wpm"
    )
    print("next: edit headings, bullets and visuals; then run validate")
    return 0


def validate(
    data: dict, root: Path | None = None, wpm: float = TARGET_WPM
) -> tuple[list[str], list[str], dict]:
    root = root or Path(".")
    errors: list[str] = []
    warnings: list[str] = []
    shots = data.get("shots") or []

    for key in ("slug", "title", "fps"):
        if not data.get(key):
            errors.append(f"missing top-level field '{key}'")
    try:
        fps = int(data.get("fps") or 0)
    except (TypeError, ValueError):
        fps = 0
    if fps not in (24, 25, 30):
        errors.append("fps must be 24, 25 or 30")
    if data.get("format") not in (None, "broll-slides"):
        warnings.append("format is not 'broll-slides'; this skill renders visual slides only")
    if not shots:
        errors.append("slide list has no shots")
        return errors, warnings, {}

    ids: set[str] = set()
    total = 0.0
    broll = 0
    kinds: list[str] = []
    visual_paths: set[str] = set()

    for index, shot in enumerate(shots, start=1):
        sid = str(shot.get("id") or "")
        where = f"slide {sid or index}"
        if not sid:
            errors.append(f"{where}: missing id")
        elif sid in ids:
            errors.append(f"{where}: duplicate id")
        else:
            ids.add(sid)

        kind = shot.get("kind")
        kinds.append(str(kind))
        if kind == "avatar":
            errors.append(f"{where}: avatar is not allowed; this skill is b-roll slides only")
            continue
        if kind not in KINDS:
            errors.append(f"{where}: kind '{kind}' is not one of {sorted(KINDS)}")
            continue

        narration = _s(shot.get("narration"))
        if not narration:
            errors.append(f"{where}: narration is required")
        elif len(narration) > MAX_NARRATION_CHARS:
            errors.append(
                f"{where}: narration is {len(narration)} chars; "
                f"max is {MAX_NARRATION_CHARS}"
            )
        total += estimate_seconds(narration, wpm) if narration else 0.0

        if kind == "broll":
            broll += 1
            visual = _s(shot.get("visual"))
            if not visual:
                errors.append(f"{where}: broll needs a visual path")
            else:
                visual_paths.add(visual)
                path = Path(visual)
                if not path.is_absolute():
                    path = root / path
                if not path.exists():
                    errors.append(f"{where}: visual not found: {path}")
                elif path.suffix.lower() not in VISUAL_SUFFIXES:
                    errors.append(f"{where}: unsupported visual format: {path.suffix}")
        elif kind == "quote":
            for key in ("quote", "attribution", "source"):
                if not _s(shot.get(key)):
                    errors.append(f"{where}: quote needs '{key}'")
            source = _s(shot.get("source"))
            if source and not source.startswith(("http://", "https://")):
                warnings.append(f"{where}: source is not an http(s) URL")
        elif kind == "chart":
            bullets = shot.get("bullets") or []
            if not isinstance(bullets, list) or not bullets:
                errors.append(f"{where}: chart needs a non-empty bullets list")
            elif len(bullets) > 3:
                errors.append(f"{where}: chart supports at most 3 bullets")
            elif any(not isinstance(item, str) for item in bullets):
                errors.append(f"{where}: chart bullets must be strings")
            if not (_s(shot.get("heading")) or _s(shot.get("on_screen"))):
                errors.append(f"{where}: chart needs a heading")
        elif kind == "title":
            if not (_s(shot.get("on_screen")) or _s(data.get("title"))):
                errors.append(f"{where}: title needs on_screen text")
        elif kind == "end":
            if not (_s(shot.get("heading")) or _s(shot.get("question"))):
                errors.append(f"{where}: end card needs a heading or question")

    if kinds and kinds[0] != "title":
        warnings.append("first slide should be a title card")
    if kinds and kinds[-1] != "end":
        warnings.append("last slide should be an end card")
    if len(set(kinds)) < 3:
        warnings.append("fewer than three slide kinds; the edit may feel repetitive")
    if broll == 0:
        warnings.append("no b-roll visuals; the deck will use generated cards only")

    minutes = total / 60
    if minutes < TARGET_MIN_MINUTES:
        warnings.append(
            f"estimated runtime {minutes:.1f} min is under {TARGET_MIN_MINUTES:.0f} min"
        )
    if minutes > TARGET_MAX_MINUTES + 0.5:
        warnings.append(
            f"estimated runtime {minutes:.1f} min is over {TARGET_MAX_MINUTES:.0f} min"
        )

    summary = {
        "slides": len(shots),
        "broll": broll,
        "unique_visuals": len(visual_paths),
        "total_seconds": round(total, 1),
        "estimated_runtime": f"{int(total // 60)}:{int(total % 60):02d}",
        "estimated_minutes": round(minutes, 2),
    }
    return errors, warnings, summary


def plan(data: dict, summary: dict, wpm: float = TARGET_WPM) -> str:
    lines = [
        f"# {data.get('title', 'Untitled')}",
        "",
        f"- Format: b-roll slides only (no avatar)",
        f"- Voice: `{data.get('voice') or 'default'}` "
        f"({data.get('engine') or 'chatterbox'})",
        f"- Estimated runtime: **{summary.get('estimated_runtime', '?')}** "
        f"({summary.get('estimated_minutes', 0):.1f} min)",
        f"- Slides: **{summary.get('slides', 0)}** · "
        f"b-roll: **{summary.get('broll', 0)}** · "
        f"unique visuals: **{summary.get('unique_visuals', 0)}**",
        "",
        "| # | Kind | Est. | On screen / visual |",
        "| --- | --- | --- | --- |",
    ]
    for shot in data.get("shots", []):
        note = (
            shot.get("on_screen")
            or shot.get("heading")
            or shot.get("quote")
            or shot.get("visual")
            or ""
        )
        note = str(note).replace("|", "\\|")[:100]
        lines.append(
            f"| {shot.get('id')} | {shot.get('kind')} | "
            f"{estimate_seconds(shot.get('narration', ''), wpm):.0f}s | {note} |"
        )

    lines += [
        "",
        "## Before rendering",
        "",
        "- Replace heuristic headings and bullets with the real argument.",
        "- Add a podcast cover, guest image, chart and one screen recording if possible.",
        "- Verify every quote, number and name against the transcript or a cited source.",
        "- Keep each narration beat under 340 characters; split long beats.",
        "- Confirm the voice profile and consent in `voices/<name>/voice.json`.",
        "",
        "## Build",
        "",
        "```bash",
        "uv run python skills/podcast-youtuber-agent/scripts/build.py \\",
        "  --slides build/ep01/slides.json --out out/ep01/final.mp4 \\",
        "  --voice-profile voices/me --engine qwen3",
        "```",
        "",
        "## Upload",
        "",
        "```bash",
        "uv run python skills/podcast-youtuber-agent/scripts/youtube_upload.py \\",
        "  --video out/ep01/final.mp4 --metadata build/ep01/youtube.json \\",
        "  --thumbnail out/ep01/thumbnail.png --captions build/ep01/captions.srt \\",
        "  --privacy private",
        "```",
        "",
        "Upload private first, watch it end to end, then publish or schedule it.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_draft = sub.add_parser("draft", help="split a script into a b-roll slide list")
    p_draft.add_argument("--script", required=True)
    p_draft.add_argument("--out", required=True)
    p_draft.add_argument("--visuals", help="directory of b-roll images/videos")
    p_draft.add_argument("--title")
    p_draft.add_argument("--subtitle")
    p_draft.add_argument("--kicker", default="PODCAST COMMENTARY")
    p_draft.add_argument(
        "--next-text",
        default="AI voice narration. Tell me in the comments.",
    )
    p_draft.add_argument("--slug")
    p_draft.add_argument("--voice", default="me")
    p_draft.add_argument("--voice-profile", default="voices/me")
    p_draft.add_argument("--engine", default="qwen3", choices=["qwen3", "chatterbox", "edge"])
    p_draft.add_argument("--fps", type=int, default=30, choices=[24, 25, 30])
    p_draft.add_argument("--max-words", type=int, default=62)
    p_draft.add_argument(
        "--wpm",
        type=float,
        default=TARGET_WPM,
        help="words per minute for runtime estimate (Chatterbox often reads 180-210)",
    )
    p_draft.set_defaults(func=draft)

    p_validate = sub.add_parser("validate", help="validate a b-roll slide list")
    p_validate.add_argument("slides")
    p_validate.add_argument("--root", default=".")
    p_validate.add_argument("--wpm", type=float, default=TARGET_WPM)
    p_validate.set_defaults(func=None)

    p_plan = sub.add_parser("plan", help="write a human-readable production plan")
    p_plan.add_argument("slides")
    p_plan.add_argument("--out", required=True)
    p_plan.add_argument("--root", default=".")
    p_plan.add_argument("--wpm", type=float, default=TARGET_WPM)
    p_plan.set_defaults(func=None)

    args = parser.parse_args(argv)
    if args.command == "draft":
        return draft(args)

    path = Path(args.slides)
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"error: {path} must contain a JSON object", file=sys.stderr)
        return 1
    errors, warnings, summary = validate(data, Path(args.root), args.wpm)
    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if args.command == "plan":
        Path(args.out).write_text(plan(data, summary, args.wpm))
        print(f"wrote {args.out}")
    print(
        f"{path}: {summary['slides']} slides, {summary['broll']} b-roll, "
        f"~{summary['estimated_minutes']:.1f} min"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
