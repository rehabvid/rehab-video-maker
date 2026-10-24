#!/usr/bin/env python3
"""Validate and plan a podcast-avatar shot list.

A shot list is the production layer between the spoken script and the renderer:
every beat of the script becomes one shot, and every shot has a kind (avatar,
b-roll, quote card, chart, title, end). Keeping the script continuous and the
shot list separate means the narration can still read like a fireside talk while
the edit cuts on sentence boundaries.

Commands:
    python3 shotlist.py draft --script script.txt --out shots.json
    python3 shotlist.py validate shots.json
    python3 shotlist.py plan shots.json --out plan.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lib import estimate_seconds, load_json, save_json, slugify

KINDS = {"avatar", "broll", "quote", "chart", "title", "end"}
TARGET_MIN = 13.5
TARGET_MAX = 16.5
MAX_NARRATION_CHARS = 340

DEFAULT_PROMPT = (
    "A person sitting at a wooden desk in a warm home studio, speaking casually "
    "to the camera, natural hand gestures, medium shot, hands visible, soft "
    "window light from the left, shallow depth of field, photorealistic, 16:9."
)
DEFAULT_NEGATIVE = (
    "bad hands, extra fingers, fused fingers, distorted face, warped background, "
    "text, watermark, cartoon, 3d render, fast jerky motion"
)


def _clean_script(text: str) -> str:
    lines = []
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
    return [p.strip() for p in parts if p.strip()]


def _split_long(sentence: str) -> list[str]:
    """Split one over-long sentence on word boundaries."""
    if len(sentence) <= MAX_NARRATION_CHARS:
        return [sentence]
    parts: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > MAX_NARRATION_CHARS:
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
        if current and (len(text.split()) > max_words or len(text) > MAX_NARRATION_CHARS):
            chunks.append(" ".join(current))
            current = [unit]
        else:
            current = candidate
    if current:
        chunks.append(" ".join(current))
    return chunks


def draft(args) -> int:
    script = _clean_script(Path(args.script).read_text())
    sentences = _sentences(script)
    if not sentences:
        print("error: script is empty", file=sys.stderr)
        return 1

    chunks = _beats(sentences, args.max_words)

    visual = f"characters/{args.character}/canonical/front.png"
    shots = []
    for i, chunk in enumerate(chunks, start=1):
        words = " ".join(chunk.split()[:8])
        shots.append(
            {
                "id": f"{i:02d}",
                "kind": "avatar",
                "narration": chunk,
                "on_screen": words + ("..." if len(chunk.split()) > 8 else ""),
                "visual": visual,
                "prompt": DEFAULT_PROMPT,
                "negative_prompt": DEFAULT_NEGATIVE,
                "transition": "cut",
            }
        )

    data = {
        "slug": args.slug or slugify(Path(args.script).stem),
        "title": args.title or Path(args.script).stem.replace("-", " ").title(),
        "character": args.character,
        "voice": args.voice,
        "fps": args.fps,
        "shots": shots,
    }
    save_json(Path(args.out), data)
    total = sum(estimate_seconds(s["narration"]) for s in shots)
    print(f"wrote {args.out}: {len(shots)} avatar shots, ~{total / 60:.1f} min")
    print("next: change some shots to broll/quote/chart/title/end, then run validate")
    return 0


def validate(data: dict) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    shots = data.get("shots") or []

    for key in ("slug", "title", "character", "voice"):
        if not data.get(key):
            errors.append(f"missing top-level field '{key}'")
    if not shots:
        errors.append("shot list has no shots")
        return errors, warnings, {}

    ids: set[str] = set()
    total = 0.0
    avatar = 0.0
    kinds: list[str] = []
    for i, shot in enumerate(shots, start=1):
        sid = shot.get("id")
        where = f"shot {sid or i}"
        if not sid:
            errors.append(f"{where}: missing id")
        elif sid in ids:
            errors.append(f"{where}: duplicate id")
        else:
            ids.add(sid)
        kind = shot.get("kind")
        kinds.append(kind)
        if kind not in KINDS:
            errors.append(f"{where}: kind '{kind}' is not one of {sorted(KINDS)}")
            continue
        narration = (shot.get("narration") or "").strip()
        if not narration:
            errors.append(f"{where}: narration is required")
        if len(narration) > MAX_NARRATION_CHARS:
            errors.append(
                f"{where}: narration is {len(narration)} chars; max is {MAX_NARRATION_CHARS}"
            )
        duration = estimate_seconds(narration) if narration else 0.0
        total += duration
        if kind == "avatar":
            avatar += duration
            if not shot.get("prompt"):
                warnings.append(f"{where}: avatar shot has no prompt; the character default will be used")
            if not shot.get("visual"):
                warnings.append(f"{where}: avatar shot has no canonical image")
        elif kind == "broll":
            if not shot.get("visual"):
                errors.append(f"{where}: broll shot needs a visual path")
        elif kind == "quote":
            for key in ("quote", "attribution", "source"):
                if not shot.get(key):
                    errors.append(f"{where}: quote shot needs '{key}'")
            if shot.get("source") and not str(shot["source"]).startswith("http"):
                warnings.append(f"{where}: source is not an http(s) URL")
        elif kind == "chart":
            if not shot.get("bullets"):
                errors.append(f"{where}: chart shot needs a non-empty bullets list")
        elif kind in ("title", "end"):
            if not (shot.get("on_screen") or narration):
                errors.append(f"{where}: {kind} shot needs on_screen text or narration")

    if kinds and kinds[0] not in ("title", "avatar"):
        warnings.append("first shot should be a title card or an avatar hook")
    if kinds and kinds[-1] not in ("end", "avatar"):
        warnings.append("last shot should be an end card or an avatar close")

    if total < TARGET_MIN * 60:
        warnings.append(f"estimated runtime {total / 60:.1f} min is under {TARGET_MIN} min")
    if total > TARGET_MAX * 60:
        warnings.append(f"estimated runtime {total / 60:.1f} min is over {TARGET_MAX} min")

    share = avatar / total if total else 0.0
    if share < 0.15:
        warnings.append(f"avatar share is {share:.0%}; the presenter may feel absent")
    if share > 0.65:
        warnings.append(f"avatar share is {share:.0%}; render time and talking-head fatigue will be high")

    run = 0
    for kind in kinds:
        run = run + 1 if kind == "avatar" else 0
        if run == 4:
            warnings.append("four avatar shots in a row; cut to b-roll to keep the edit moving")
    if sum(1 for k in kinds if k != "avatar") < 3:
        warnings.append("fewer than three non-avatar shots; add quote cards, charts or b-roll")

    summary = {
        "shots": len(shots),
        "total_seconds": round(total, 1),
        "avatar_seconds": round(avatar, 1),
        "avatar_share": round(share, 4),
        "estimated_runtime": f"{int(total // 60)}:{int(total % 60):02d}",
    }
    return errors, warnings, summary


def plan(data: dict, summary: dict) -> str:
    lines = [
        f"# {data.get('title', 'Untitled')}",
        "",
        f"Character: `{data.get('character')}` · Voice: `{data.get('voice')}` · "
        f"Estimated runtime: **{summary.get('estimated_runtime', '?')}** · "
        f"Avatar share: **{summary.get('avatar_share', 0):.0%}**",
        "",
        "| # | Kind | Est. | On screen / note |",
        "| --- | --- | --- | --- |",
    ]
    for shot in data["shots"]:
        note = shot.get("on_screen") or shot.get("quote") or shot.get("visual") or ""
        note = str(note).replace("|", "\\|")[:90]
        lines.append(
            f"| {shot.get('id')} | {shot.get('kind')} | "
            f"{estimate_seconds(shot.get('narration', '')):.0f}s | {note} |"
        )

    avatar_seconds = summary.get("avatar_seconds", 0)
    lines += [
        "",
        "## Render budget",
        "",
        "Avatar seconds are the only expensive part. Benchmark a 1-second clip first.",
        "",
        "| Measured 1 s render | 1 min avatar | This video's avatar |",
        "| --- | --- | --- |",
    ]
    for per_1s in (1, 3, 5, 7, 10):
        per_min = per_1s * 60
        total_h = avatar_seconds / 60 * per_min / 60
        lines.append(f"| {per_1s} min | {per_min} min | {total_h:.1f} h |")

    lines += [
        "",
        "## B-roll checklist",
        "",
        "- [ ] Podcast cover and episode page screenshot",
        "- [ ] Guest photo / episode title card",
        "- [ ] One chart or number that carries the argument",
        "- [ ] One short quote card with attribution and link",
        "- [ ] One screen recording or article screenshot",
        "- [ ] One framework / list card for your own insight",
        "- [ ] End card with a specific question",
    ]
    return "\n".join(lines) + "\n"


def cmd_validate(args) -> int:
    data = load_json(Path(args.shots))
    errors, warnings, summary = validate(data)
    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"{data.get('slug')}: {summary['shots']} shots, "
        f"{summary['estimated_runtime']}, avatar {summary['avatar_share']:.0%}, valid"
    )
    return 0


def cmd_plan(args) -> int:
    data = load_json(Path(args.shots))
    errors, warnings, summary = validate(data)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    text = plan(data, summary)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_draft = sub.add_parser("draft", help="split a continuous script into avatar beats")
    p_draft.add_argument("--script", required=True)
    p_draft.add_argument("--out", required=True)
    p_draft.add_argument("--character", default="me")
    p_draft.add_argument("--voice", default="andrew")
    p_draft.add_argument("--slug", default="")
    p_draft.add_argument("--title", default="")
    p_draft.add_argument(
        "--max-words",
        type=int,
        default=55,
        help="target words per shot (55 ~ 22 s; the 340-character cap also applies)",
    )
    p_draft.add_argument(
        "--fps",
        type=int,
        default=30,
        choices=[24, 25, 30],
        help="output frame rate; EchoMimicV3 renders natively at 25",
    )
    p_draft.set_defaults(func=draft)

    p_val = sub.add_parser("validate", help="check a shot list")
    p_val.add_argument("shots")
    p_val.set_defaults(func=cmd_validate)

    p_plan = sub.add_parser("plan", help="write a production plan and render budget")
    p_plan.add_argument("shots")
    p_plan.add_argument("--out")
    p_plan.set_defaults(func=cmd_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
