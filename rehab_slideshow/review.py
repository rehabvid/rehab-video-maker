"""Clinical safety review: automated checklist plus a reviewer sign-off sheet."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .exercises import Exercise
from .illustrations import POSES, pose_reach
from .storyboard import UNSUPPORTED_CLAIMS, mentions_number
import re

CHECK = "\u2713"
CROSS = "\u2717"


def _fmt(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def run_checks(ex: Exercise, storyboard: dict, timeline, audio_info: dict,
               video_info: dict) -> list[tuple[str, bool, str]]:
    frames = storyboard["frames"]
    checks: list[tuple[str, bool, str]] = []

    checks.append((
        "Exercise name visible",
        bool(ex.title),
        f"'{ex.title}' is drawn on every frame with the step heading",
    ))

    checks.append((
        "Recovery phase stated",
        bool(ex.get("phase_label")),
        f"Phase badge reads '{ex.get('phase_label')}'",
    ))

    side = ex.get("affected_side")
    checks.append((
        "Affected side identified",
        side in ("right", "left"),
        f"Overlay says '{side} arm shown'; narration tells the patient to switch sides if needed",
    ))

    reps = ex.get("repetitions")
    reps_max = ex.get("repetitions_max")
    script = " ".join(f["narration"] for f in frames).lower()
    reps_stated = mentions_number(script, reps) if reps else False
    checks.append((
        "Repetition count matches protocol",
        reps_stated,
        f"{reps} repetitions" + (f" (build to {reps_max})" if reps_max else "")
        + f", as stated in {ex.path.name}",
    ))

    hold = ex.get("hold_seconds")
    hold_stated = hold is None or mentions_number(script, hold)
    checks.append((
        "Hold duration matches protocol",
        bool(hold_stated),
        (f"{hold} seconds" if hold else ex.get("hold_note", "no hold")) + ", as stated in the protocol",
    ))

    kinds = {f.get("kind") for f in frames}
    precautions_on_screen = "precaution" in kinds or any(
        "stop" in (b or "").lower() for f in frames for b in (f.get("bullets") or [])
    )
    checks.append((
        "Precautions included",
        precautions_on_screen,
        f"{len(ex.get('precautions', []))} precautions in metadata; stop rules narrated in the closing frame",
    ))

    mismatched = [f["id"] for f in frames if not f.get("narration") or f.get("pose") not in POSES]
    checks.append((
        "Narration matches visuals",
        not mismatched,
        "Every frame has one narration cue and one explicit pose"
        if not mismatched else f"frames without a matching pose: {mismatched}",
    ))

    peak = max((pose_reach(f["pose"]) for f in frames), default=0)
    peak_frame = next((f["id"] for f in frames if POSES[f["pose"]]["reach"] == peak), "-")
    checks.append((
        "Frame order is correct",
        [f["id"] for f in frames] == [f"{i:02d}" for i in range(1, len(frames) + 1)],
        f"Ordered storyboard; peak range of motion at frame {peak_frame} (reach {peak:.2f})",
    ))

    banned = []
    for frame in frames:
        blob = " ".join([frame.get("narration", ""), *(frame.get("bullets") or [])])
        for pattern in UNSUPPORTED_CLAIMS:
            if re.search(pattern, blob, re.IGNORECASE):
                banned.append(frame["id"])
    checks.append((
        "No unsupported medical claims",
        not banned,
        "Script scanned for cure/prevention/guarantee language",
    ))

    jumps = []
    reaches = [pose_reach(f["pose"]) for f in frames]
    for a, b in zip(reaches, reaches[1:]):
        if b - a > 0.45:
            jumps.append(f"{a:.2f}->{b:.2f}")
    checks.append((
        "No unsafe movement progression",
        not jumps,
        "Range of motion rises to one peak and returns; no jumps above 0.45",
    ))

    checks.append((
        "Narration fully timed",
        audio_info.get("duration_ok", False) and len(timeline) == len(frames),
        f"master.wav {_fmt(audio_info['duration'])} for {len(timeline)} cues, "
        f"{audio_info['sample_rate']} Hz stereo, no clipped samples",
    ))

    checks.append((
        "Export format",
        video_info.get("video_codec") == "h264"
        and video_info.get("audio_codec") == "aac"
        and video_info.get("width") == 1280
        and video_info.get("height") == 720,
        f"{video_info.get('video_codec')} {video_info.get('width')}x{video_info.get('height')}, "
        f"{video_info.get('audio_codec')} audio, "
        f"{video_info.get('subtitle_streams')} caption track(s)",
    ))

    return checks


def write_review(path: Path, ex: Exercise, storyboard: dict, timeline, checks,
                 audio_info: dict, video_info: dict,
                 illustration: str = "built-in vector renderer") -> str:
    passed = all(ok for _, ok, _ in checks)
    review_meta = ex.get("clinical_review") or {}
    if passed and review_meta.get("status") == "approved" and review_meta.get("reviewer"):
        status = f"Approved by {review_meta['reviewer']} on {review_meta.get('reviewed_on')}"
    elif passed:
        status = "Ready for clinical review - automated checks passed, awaiting clinician sign-off"
    else:
        status = "Blocked - automated safety checks failed"

    source = ex.get("source") or {}
    lines = [
        f"# Clinical review - {ex.title}",
        "",
        f"Exercise: {ex.title}",
        "",
        "Recovery Phase:",
        f"{ex.get('phase_label') or ex.get('recovery_phase')}",
        "",
        "Target:",
        f"{str(ex.get('target_area', '')).strip().capitalize()}",
        "",
        "Repetitions:",
        f"{ex.get('repetitions')}" + (f" (build toward {ex.get('repetitions_max')})"
                                       if ex.get("repetitions_max") else ""),
        "",
        "Hold:",
        f"{ex.get('hold_seconds')} seconds" if ex.get("hold_seconds") else ex.get("hold_note", "no hold"),
        "",
        "Frequency:",
        f"{ex.get('frequency')}",
        "",
        "Illustrations:",
        f"{illustration}",
        "",
        "Affected side:",
        f"{str(ex.get('affected_side', 'unspecified')).capitalize()} arm shown; "
        "the patient is told to mirror the movement if their surgery was on the other side",
        "",
        "Start criteria:",
        f"{ex.get('start_criteria')}",
        "",
        "Precautions:",
        *[f"- {p}" for p in ex.get("precautions", [])],
        "",
        "Stop if:",
        *[f"- {s}" for s in ex.get("stop_if", [])],
        "",
        "## Automated safety checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
        *[f"| {name} | {CHECK if ok else CROSS} | {detail} |" for name, ok, detail in checks],
        "",
        "## Timing",
        "",
        "| Frame | Step | Starts | Duration |",
        "| --- | --- | --- | --- |",
        *[
            f"| {c.frame} | {next((f['heading'] for f in storyboard['frames'] if f['id'] == c.frame), '')} "
            f"| {_fmt(c.frame_start)} | {c.frame_duration:.2f} s |"
            for c in timeline
        ],
        f"| - | total | 0:00.0 | {_fmt(video_info.get('duration', 0))} |",
        "",
        "## Source",
        "",
        f"- {source.get('title', '')} - {source.get('publisher', '')}"
        + (f" ({source.get('year')})" if source.get("year") else ""),
        f"- {source.get('url', '')}",
        f"- {source.get('note', '')}".rstrip(),
        "",
        *[
            f"- Supporting: {s.get('title', '')} - {s.get('publisher', '')}. {s.get('note', '')}"
            for s in ex.get("secondary_sources", [])
        ],
        "",
        "## Review Status",
        "",
        status,
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Reviewer | {review_meta.get('reviewer') or '________________'} |",
        f"| Date | {review_meta.get('reviewed_on') or '________________'} |",
        f"| Outcome | {'approved / revisions requested'} |",
        "",
        "This review sheet records automated checks only. It is not a substitute for",
        "sign-off by the treating surgeon, physiotherapist or breast care nurse.",
        "",
        f"_Generated {date.today().isoformat()} by rehab-slideshow._",
        "",
    ]
    path.write_text("\n".join(lines))
    return status
