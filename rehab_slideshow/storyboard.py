"""Storyboard loading and clinical validation.

A storyboard is authored content: one frame per visible action, one narration
cue per frame. This module rejects storyboards that break the safety rules in
the skill (unsafe range-of-motion jumps, missing precautions, unsupported
medical claims, narration that does not match a known pose).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .exercises import Exercise
from .illustrations import POSES, pose_reach

FRAME_KINDS = {"intro", "action", "hold", "precaution", "close"}
MAX_NARRATION_CHARS = 340
MAX_BULLET_CHARS = 96
MAX_BULLETS = 3
MAX_REACH_JUMP = 0.45

# Claims a patient-education slide must never make.
UNSUPPORTED_CLAIMS = [
    r"\bcures?\b",
    r"\bprevents? (?:lymphedema|lymphoedema|cancer)\b",
    r"\bguarantee",
    r"\bpain[- ]free\b",
    r"\bno risk\b",
    r"\bwill heal\b",
    r"\bbest (?:exercise|treatment|way)\b",
    r"\bfastest recovery\b",
    r"\bproven to\b",
]


class StoryboardError(ValueError):
    pass


def load_storyboard(root: Path, exercise_id: str) -> dict:
    path = root / "storyboards" / f"{exercise_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no storyboard at {path.relative_to(root)}; author one before building"
        )
    return json.loads(path.read_text())


def validate_storyboard(sb: dict, ex: Exercise) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if sb.get("exercise") != ex.id:
        errors.append(f"storyboard.exercise '{sb.get('exercise')}' does not match '{ex.id}'")
    if sb.get("phase") and sb["phase"] != ex.get("recovery_phase"):
        errors.append(
            f"storyboard phase '{sb['phase']}' does not match exercise phase "
            f"'{ex.get('recovery_phase')}'"
        )

    frames = sb.get("frames") or []
    if len(frames) < 4:
        errors.append("a storyboard needs at least 4 frames (intro, actions, close)")
    if len(frames) > 20:
        errors.append("storyboards longer than 20 frames should be split into parts")

    ids = [str(f.get("id")) for f in frames]
    if len(set(ids)) != len(ids):
        errors.append("frame ids must be unique")
    expected = [f"{i:02d}" for i in range(1, len(frames) + 1)]
    if ids != expected:
        errors.append(f"frame ids must run 01..{len(frames):02d} in order")

    kinds = set()
    reaches: list[tuple[str, float]] = []
    for frame in frames:
        fid = frame.get("id", "?")
        kind = frame.get("kind", "action")
        kinds.add(kind)
        if kind not in FRAME_KINDS:
            errors.append(f"frame {fid}: unknown kind '{kind}'")

        pose = frame.get("pose")
        if pose not in POSES:
            errors.append(f"frame {fid}: unknown pose '{pose}'")
        else:
            reaches.append((fid, pose_reach(pose)))

        narration = (frame.get("narration") or "").strip()
        if not narration:
            errors.append(f"frame {fid}: narration is required (one cue per frame)")
        elif len(narration) > MAX_NARRATION_CHARS:
            errors.append(
                f"frame {fid}: narration is {len(narration)} characters "
                f"(limit {MAX_NARRATION_CHARS}); split the frame"
            )
        if not frame.get("heading"):
            errors.append(f"frame {fid}: heading is required for the on-screen step title")

        bullets = frame.get("bullets") or []
        if len(bullets) > MAX_BULLETS:
            errors.append(f"frame {fid}: at most {MAX_BULLETS} bullets fit on screen")
        for bullet in bullets:
            if len(bullet) > MAX_BULLET_CHARS:
                errors.append(
                    f"frame {fid}: bullet is {len(bullet)} characters "
                    f"(limit {MAX_BULLET_CHARS})"
                )

    if "precaution" not in kinds and "close" not in kinds:
        errors.append("no precaution or close frame: safety instructions must be shown")

    # range of motion must rise to a single peak and return, never jump
    if reaches:
        peak = max(range(len(reaches)), key=lambda i: reaches[i][1])
        for i in range(1, peak + 1):
            if reaches[i][1] - reaches[i - 1][1] > MAX_REACH_JUMP:
                errors.append(
                    f"frames {reaches[i-1][0]}->{reaches[i][0]}: range of motion jumps by "
                    f"{reaches[i][1] - reaches[i-1][1]:.2f} (max {MAX_REACH_JUMP})"
                )
        for i in range(peak + 1, len(reaches)):
            if reaches[i][1] > reaches[i - 1][1] + 0.05:
                errors.append(
                    f"frames {reaches[i-1][0]}->{reaches[i][0]}: range of motion increases "
                    "after the peak; the exercise must return gradually"
                )

    # protocol numbers must actually appear in the script
    text = " ".join((f.get("narration") or "") for f in frames).lower()
    reps = ex.get("repetitions")
    if reps and not mentions_number(text, reps):
        errors.append(f"narration never states the repetition count ({reps})")
    hold = ex.get("hold_seconds")
    if hold and not mentions_number(text, hold):
        errors.append(f"narration never states the hold duration ({hold} seconds)")

    # claims that need clinical evidence
    for frame in frames:
        blob = " ".join([frame.get("narration", ""), *(frame.get("bullets") or [])])
        for pattern in UNSUPPORTED_CLAIMS:
            if re.search(pattern, blob, flags=re.IGNORECASE):
                errors.append(
                    f"frame {frame.get('id')}: unsupported claim matches /{pattern}/"
                )

    if not any("stop" in (f.get("narration") or "").lower() for f in frames):
        warnings.append("no frame tells the patient when to stop; consider adding it")

    if sb.get("language") not in (None, "en", "en-US"):
        warnings.append("language is not en; check the chosen voice matches")

    return errors, warnings


def mentions_number(text: str, value: int) -> bool:
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
        7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    }
    if re.search(rf"\b{value}\b", text):
        return True
    word = words.get(value)
    return bool(word and re.search(rf"\b{word}\b", text))
