#!/usr/bin/env python3
"""Decide which narration slides deserve a technical visual.

Input is the slide-by-slide transcript produced by the content skill
(``slides.json``) plus, optionally, the measured ``timing.json``.  Output is a
visual plan consumed by ``make_scenes.py``.

The planner is deliberately conservative. A slide gets a chart only when the
content includes chart data; a DAG/PetriNet only when the narration describes a
process or state machine. Everything else stays a clean markdown slide. This
avoids inventing data merely to make the video look busy.

Visual hints can be supplied explicitly::

    "visual": {
      "type": "chart",
      "chart_type": "bar",
      "data": {
        "categories": ["2024", "2025"],
        "series": [{"name": "Revenue", "data": [12, 19]}]
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_POLICY = HERE.parent / "config" / "visual-policy.json"
VISUAL_TYPES = {"chart", "dag", "petrinet", "diagram", "svg", "markdown", "existing", "none", "quote"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _language(slides: dict) -> str:
    declared = str(slides.get("language") or "").strip()
    if declared:
        return declared
    sample = str(slides.get("title") or "") + " " + " ".join(
        str(shot.get("narration") or "") for shot in slides.get("shots", [])[:3]
    )
    return "zh-Hans" if any("\u4e00" <= char <= "\u9fff" for char in sample) else "en"


def _short(text: str, limit: int = 92) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def _duration(shot: dict, timing: dict[str, dict], policy: dict) -> float:
    measured = timing.get(str(shot.get("id")))
    if measured and measured.get("duration"):
        return float(measured["duration"])
    words = len(str(shot.get("narration") or "").split())
    return max(3.0, words / float(policy.get("words_per_second", 2.8)) + 0.6)


def _points(shot: dict, policy: dict) -> list[str]:
    visual = shot.get("visual")
    if isinstance(visual, dict):
        explicit_points = visual.get("points") or visual.get("points_override")
        if isinstance(explicit_points, list) and explicit_points:
            return [_short(str(item), 110) for item in explicit_points][: int(policy.get("max_points", 3))]
    bullets = shot.get("bullets")
    if isinstance(bullets, list):
        out = [_short(item, 110) for item in bullets if str(item).strip()]
        if out:
            return out[: int(policy.get("max_points", 3))]
    text = str(shot.get("narration") or "")
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|;\s+", text) if part.strip()]
    return [_short(part, 110) for part in parts[: int(policy.get("max_points", 3))]]


def _has_data(shot: dict) -> bool:
    visual = shot.get("visual")
    if isinstance(visual, dict) and visual.get("data"):
        return True
    return bool(shot.get("data") or shot.get("chart"))


def _detect_type(shot: dict, policy: dict) -> str:
    explicit = shot.get("visual")
    if isinstance(explicit, dict):
        kind = str(explicit.get("type") or "").lower()
        if kind in VISUAL_TYPES:
            if kind == "chart" and not (explicit.get("data") or shot.get("data")):
                return "markdown"
            return kind
    if isinstance(explicit, str) and explicit.strip():
        return "existing"

    kind = str(shot.get("kind") or "chart")
    if kind in {"title", "end"}:
        return "none"
    if kind == "quote":
        return "quote"
    if kind == "broll" and shot.get("visual"):
        return "existing"
    if _has_data(shot):
        return "chart"

    text = f" {shot.get('narration', '')} {shot.get('heading', '')} ".lower()

    def has(term: str) -> bool:
        return bool(re.search(r"\b" + re.escape(term.lower()) + r"\b", text))

    for word in policy.get("petrinet_keywords", []):
        if has(word):
            return "petrinet"
    for word in policy.get("dag_keywords", []):
        if has(word):
            return "dag"
    for word in policy.get("diagram_keywords", []):
        if has(word):
            return "diagram"
    for word in policy.get("svg_keywords", []):
        if has(word):
            return "svg"
    # Plain narration stays a normal text card. Do not make every slide a
    # Playwright scene just because the renderer is available.
    return "none"


def _data(shot: dict) -> dict:
    visual = shot.get("visual")
    if isinstance(visual, dict) and isinstance(visual.get("data"), dict):
        return visual["data"]
    if isinstance(shot.get("data"), dict):
        return shot["data"]
    if isinstance(shot.get("chart"), dict):
        return shot["chart"]
    return {}


def _spec(shot: dict, kind: str, duration: float, policy: dict) -> dict:
    title = (
        shot.get("heading")
        or shot.get("on_screen")
        or shot.get("quote")
        or "The argument"
    )
    explicit_animation = True
    if isinstance(shot.get("visual"), dict):
        explicit_animation = bool(shot["visual"].get("animated", True))
    animation = (
        duration >= float(policy.get("animate_after_seconds", 7))
        and kind in {"chart", "dag", "petrinet", "diagram", "svg"}
        and explicit_animation
    )
    return {
        "title": _short(title, 84),
        "subtitle": _short(shot.get("subtitle") or shot.get("attribution") or "", 120),
        "points": _points(shot, policy),
        "data": _data(shot),
        "chart_type": (shot.get("visual") or {}).get("chart_type")
        if isinstance(shot.get("visual"), dict)
        else shot.get("chart_type"),
        "source": shot.get("source") or "",
        "animation": animation,
    }


def plan(slides: dict, timing: dict, policy: dict) -> dict:
    timing_map = {
        str(shot.get("id")): shot
        for shot in timing.get("shots", [])
        if shot.get("id") is not None
    }
    planned = []
    for shot in slides.get("shots", []):
        duration = _duration(shot, timing_map, policy)
        visual_type = _detect_type(shot, policy)
        if visual_type == "existing":
            plan_entry = {
                "id": shot.get("id"),
                "kind": shot.get("kind"),
                "narration": shot.get("narration", ""),
                "duration": duration,
                "visual": {
                    "type": "existing",
                    "animated": bool(str(shot.get("visual", "")).lower().endswith((".mp4", ".mov", ".webm"))),
                    "path": shot.get("visual"),
                    "reason": "the content already supplies a b-roll asset",
                },
            }
        elif visual_type in {"none", "quote"}:
            plan_entry = {
                "id": shot.get("id"),
                "kind": shot.get("kind"),
                "narration": shot.get("narration", ""),
                "duration": duration,
                "visual": {
                    "type": visual_type,
                    "animated": False,
                    "reason": "use the existing title, quote or end card",
                },
            }
        else:
            spec = _spec(shot, visual_type, duration, policy)
            plan_entry = {
                "id": shot.get("id"),
                "kind": shot.get("kind"),
                "narration": shot.get("narration", ""),
                "duration": duration,
                "visual": {
                    "type": visual_type,
                    "animated": spec["animation"],
                    "explicit": isinstance(shot.get("visual"), dict),
                    "reason": f"{visual_type} fits the narration and duration",
                    "spec": spec,
                },
            }
        planned.append(plan_entry)

    # Keep only the strongest custom visuals. The rest remain ordinary cards,
    # which is cheaper and gives the animation room to breathe.
    max_visuals = int(policy.get("max_custom_visuals", 12))
    priority = {"chart": 5, "petrinet": 5, "dag": 4, "diagram": 4, "svg": 3, "markdown": 1}
    candidates = [p for p in planned if p["visual"]["type"] in priority]
    if len(candidates) > max_visuals:
        keep = {
            p["id"] for p in sorted(
                candidates,
                key=lambda p: (
                    bool(p["visual"].get("explicit")),
                    priority.get(p["visual"]["type"], 0),
                    float(p.get("duration") or 0),
                ),
                reverse=True,
            )[:max_visuals]
        }
        for item in planned:
            if item["visual"]["type"] in priority and item["id"] not in keep:
                item["visual"] = {
                    "type": "none",
                    "animated": False,
                    "reason": "kept as a text card to preserve pacing and render efficiency",
                }

    return {
        "slug": slides.get("slug") or "episode",
        "title": slides.get("title") or "Technical commentary",
        "language": _language(slides),
        "fps": int(slides.get("fps") or 30),
        "policy": policy,
        "shots": planned,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--timing", help="optional measured timing.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    args = parser.parse_args(argv)

    try:
        slides = _load(Path(args.slides))
        timing = _load(Path(args.timing)) if args.timing else {"shots": []}
        policy = _load(Path(args.policy))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not isinstance(slides, dict) or not slides.get("shots"):
        print("error: slides file has no shots", file=sys.stderr)
        return 1

    result = plan(slides, timing, policy)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    counts: dict[str, int] = {}
    for shot in result["shots"]:
        kind = shot["visual"]["type"]
        counts[kind] = counts.get(kind, 0) + 1
    summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    print(f"wrote {out}: {len(result['shots'])} slides ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
