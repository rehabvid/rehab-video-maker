"""Exercise metadata loading and validation.

Metadata is the clinical source of truth: the build fails closed when a required
field is missing, so a video can never be produced with invented repetitions,
hold times, phase or precautions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PHASE_RE = re.compile(r"^weeks-\d+-\d+$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

REQUIRED = [
    "id",
    "title",
    "recovery_phase",
    "target_area",
    "repetitions",
    "precautions",
    "stop_if",
    "source",
    "frequency",
    "start_criteria",
]


@dataclass
class Exercise:
    raw: dict
    path: Path
    warnings: list[str] = field(default_factory=list)

    def __getitem__(self, key):
        return self.raw[key]

    def get(self, key, default=None):
        return self.raw.get(key, default)

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def title(self) -> str:
        return self.raw["title"]


def exercises_dir(root: Path) -> Path:
    return root / "exercises"


def list_exercises(root: Path) -> list[Path]:
    return sorted(exercises_dir(root).glob("*.yaml"))


def load_exercise(root: Path, exercise_id: str) -> Exercise:
    path = exercises_dir(root) / f"{exercise_id}.yaml"
    if not path.exists():
        available = ", ".join(p.stem for p in list_exercises(root)) or "none"
        raise FileNotFoundError(f"unknown exercise '{exercise_id}' (available: {available})")
    raw = yaml.safe_load(path.read_text())
    ex = Exercise(raw=raw, path=path)
    errors, warnings = validate_exercise(ex)
    if errors:
        raise ValueError(f"{path.name} is not usable:\n  - " + "\n  - ".join(errors))
    ex.warnings = warnings
    return ex


def validate_exercise(ex: Exercise) -> tuple[list[str], list[str]]:
    raw = ex.raw
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(raw, dict):
        return ["file is not a YAML mapping"], []

    for key in REQUIRED:
        if key not in raw or raw[key] in (None, "", []):
            errors.append(f"missing required field '{key}'")

    if raw.get("id") and not ID_RE.match(str(raw["id"])):
        errors.append("id must be lowercase words separated by hyphens")
    if raw.get("recovery_phase") and not PHASE_RE.match(str(raw["recovery_phase"])):
        errors.append("recovery_phase must look like weeks-2-6")

    reps = raw.get("repetitions")
    if isinstance(reps, bool) or not isinstance(reps, int) or reps <= 0:
        errors.append("repetitions must be a positive integer")
    reps_max = raw.get("repetitions_max")
    if reps_max is not None:
        if not isinstance(reps_max, int) or reps_max < (reps or 0):
            errors.append("repetitions_max must be an integer >= repetitions")
    elif isinstance(reps, int) and reps > 0:
        warnings.append("no repetitions_max: the video will state a single repetition count")

    hold = raw.get("hold_seconds")
    if hold is None:
        if not raw.get("hold_note"):
            errors.append("hold_seconds is null but no hold_note explains the dynamic movement")
    elif isinstance(hold, bool) or not isinstance(hold, int) or hold <= 0:
        errors.append("hold_seconds must be a positive integer or null for dynamic exercises")

    source = raw.get("source") or {}
    for key in ("title", "publisher", "url"):
        if not source.get(key):
            errors.append(f"source.{key} is required: every exercise must cite a protocol")

    for key in ("precautions", "stop_if"):
        items = raw.get(key) or []
        if not isinstance(items, list) or not items:
            errors.append(f"{key} must be a non-empty list")

    side = raw.get("affected_side")
    if side not in ("right", "left"):
        warnings.append("affected_side is not set to right or left; the overlay will say 'affected arm'")

    review = raw.get("clinical_review") or {}
    status = review.get("status")
    if status != "approved":
        warnings.append(
            "clinical_review.status is "
            f"'{status or 'missing'}': the video is marked as awaiting clinician sign-off"
        )

    return errors, warnings
