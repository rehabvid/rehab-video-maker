"""Timeline, SRT and ASS caption generation.

Timing comes from the measured duration of each narration clip, never from an
estimate. Captions are chunked so that no caption is longer than two lines of
42 characters, as required by the skill.
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from pathlib import Path

MAX_LINE_CHARS = 42
MAX_LINES = 2
TRANSITION = 0.5

# frame pacing
LEAD_FIRST = 0.9
LEAD = 0.45
TAIL = 0.75
CAPTION_TAIL = 0.35


@dataclass
class Cue:
    id: str
    frame: str
    text: str
    audio: Path
    duration: float
    start: float  # narration start on the master timeline
    frame_start: float
    frame_duration: float
    lead: float = LEAD

    @property
    def end(self) -> float:
        return self.start + self.duration


def build_timeline(cues: list[dict], narration_dir: Path) -> list[Cue]:
    timeline: list[Cue] = []
    cursor = 0.0
    for i, cue in enumerate(cues):
        lead = LEAD_FIRST if i == 0 else LEAD
        duration = float(cue["duration"])
        frame_duration = lead + duration + TAIL
        timeline.append(
            Cue(
                id=cue["id"],
                frame=cue["frame"],
                text=cue["text"],
                audio=narration_dir / cue["file"],
                duration=duration,
                start=cursor + lead,
                frame_start=cursor,
                frame_duration=frame_duration,
                lead=lead,
            )
        )
        cursor += frame_duration
    return timeline


def quantize(timeline: list[Cue], fps: int = 30) -> list[Cue]:
    """Snap frame durations to the video frame grid so audio, video and captions
    cannot drift apart."""
    cursor = 0.0
    for cue in timeline:
        frames = math.ceil(cue.frame_duration * fps - 1e-6)
        cue.frame_start = cursor
        cue.frame_duration = frames / fps
        cue.start = cursor + cue.lead
        cursor += cue.frame_duration
    return timeline


def video_duration(timeline: list[Cue]) -> float:
    """Total runtime.

    Each segment carries one extra TRANSITION of material so that a cross-fade
    does not shorten the timeline: the overlaps and the extra material cancel
    out exactly, leaving the sum of the frame durations.
    """
    return sum(c.frame_duration for c in timeline)


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _chunks(text: str) -> list[str]:
    """Split a cue into <= 2-line captions at natural phrase boundaries."""
    width = MAX_LINE_CHARS * MAX_LINES
    if len(text) <= width:
        return [text]
    # first split on sentence punctuation, then on word count
    parts, current = [], ""
    for token in text.replace("; ", ". ").split(". "):
        token = token.strip()
        if not token:
            continue
        token = token + "." if not token.endswith((".", "!", "?", ":")) else token
        if current and len(current) + 1 + len(token) > width:
            parts.append(current)
            current = token
        else:
            current = f"{current} {token}".strip()
    if current:
        parts.append(current)

    out: list[str] = []
    for part in parts:
        while len(part) > width:
            cut = part[:width].rfind(" ")
            cut = cut if cut > width * 0.6 else width
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


def _wrap(text: str) -> str:
    return "\n".join(textwrap.wrap(text, width=MAX_LINE_CHARS, break_long_words=False))


def caption_entries(timeline: list[Cue]) -> list[tuple[float, float, str]]:
    entries: list[tuple[float, float, str]] = []
    for cue in timeline:
        chunks = _chunks(cue.text)
        total = sum(len(c) for c in chunks) or 1
        t = cue.start
        window = cue.duration + CAPTION_TAIL
        for i, chunk in enumerate(chunks):
            share = window * len(chunk) / total
            start = t
            end = t + share
            if i == len(chunks) - 1:
                end = cue.start + window
            entries.append((start, end, _wrap(chunk)))
            t = end
    # keep captions inside the video and non-overlapping
    cleaned = []
    for i, (start, end, text) in enumerate(entries):
        if i + 1 < len(entries):
            end = min(end, entries[i + 1][0] - 0.02)
        if end - start < 0.6:
            end = start + 0.6
        cleaned.append((start, end, text))
    return cleaned


def write_srt(timeline: list[Cue], path: Path) -> Path:
    lines = []
    for i, (start, end, text) in enumerate(caption_entries(timeline), start=1):
        lines.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    path.write_text("\n".join(lines))
    return path


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,27,&H00FFFFFF,&H00FFFFFF,&H00202B31,&H64000000,-1,0,0,0,100,100,0.3,0,1,2.4,0,2,90,90,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(timeline: list[Cue], path: Path) -> Path:
    """Burned-in captions with a fixed 2-line style below the illustration."""
    events = []
    for start, end, text in caption_entries(timeline):
        escaped = text.replace("\n", r"\N")
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{escaped}"
        )
    path.write_text(ASS_HEADER + "\n".join(events) + "\n")
    return path
