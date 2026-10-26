"""Shared helpers for the podcast-avatar-commentary skill.

Everything here is deliberately dependency-light: standard library, Pillow and
numpy only. FFmpeg/ffprobe are called as subprocesses, exactly like the rest of
this repository.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
LEAD_FIRST = 0.6
LEAD = 0.25
TAIL = 0.35
TARGET_WPM = 150.0
CAPTION_LINE = 42
CAPTION_LINE_CJK = 34
CAPTION_LINES = 2
CAPTION_TAIL = 0.35

MASTER_W, MASTER_H = 2560, 1440
OUT_W, OUT_H = 1920, 1080

INK = (14, 17, 22)
PAPER = (244, 241, 234)
MUTED = (166, 173, 184)
ACCENT = (242, 184, 75)
ACCENT_2 = (79, 209, 197)
PANEL = (24, 29, 38)


# ---------------------------------------------------------------------------
# files and process helpers
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def save_json(path: Path, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return round(float(out.stdout.strip()), 3)


def ffprobe_streams(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def run_ffmpeg(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *args]
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + (result.stderr or "")[-6000:])
    return result


def quantize(seconds: float, fps: int = FPS) -> float:
    return math.ceil(seconds * fps - 1e-6) / fps


def estimate_seconds(text: str, wpm: float = TARGET_WPM) -> float:
    if contains_cjk(text):
        chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        # Measured Qwen3 Mandarin pace is roughly 260-300 characters/minute.
        return max(1.0, chars / 270.0 * 60.0)
    words = len(re.findall(r"\S+", text))
    return max(1.0, words / wpm * 60.0)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "episode"


# ---------------------------------------------------------------------------
# fonts and text drawing
# ---------------------------------------------------------------------------

FONT_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONT_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONT_CJK_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]
FONT_CJK_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text or "")


def find_font(size: int, bold: bool = False, text: str = "") -> ImageFont.FreeTypeFont:
    candidates = FONT_CJK_BOLD if bold else FONT_CJK_REGULAR
    if not contains_cjk(text):
        candidates = FONT_BOLD if bold else FONT_REGULAR
    for path in candidates:
        p = Path(path)
        if not p.exists():
            continue
        try:
            if p.suffix.lower() == ".ttc":
                return ImageFont.truetype(str(p), size=size, index=0)
            return ImageFont.truetype(str(p), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_by_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if contains_cjk(text):
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and font.getlength(candidate) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or font.getlength(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_paragraph(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    xy: tuple[int, int],
    max_width: int,
    fill: tuple[int, int, int] = PAPER,
    line_gap: int = 12,
    max_lines: int | None = None,
) -> int:
    if contains_cjk(text):
        font = find_font(font.size, text=text)
    x, y = xy
    lines = wrap_by_width(text, font, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    line_h = int(font.size * 1.22)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_gap
    return y


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / img.width, target_h / img.height)
    resized = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def background_from(path: Path | None, size: tuple[int, int] = (MASTER_W, MASTER_H)) -> Image.Image:
    """A dark studio background, optionally using a still as a blurred backdrop."""
    if path and Path(path).exists():
        try:
            with Image.open(path) as raw:
                bg = _cover(raw.convert("RGB"), size)
            bg = bg.filter(ImageFilter.GaussianBlur(18))
            veil = Image.new("RGB", size, INK)
            bg = Image.blend(bg, veil, 0.62)
            return bg
        except (OSError, ValueError):
            pass
    bg = Image.new("RGB", size, INK)
    draw = ImageDraw.Draw(bg)
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        color = (
            int(18 + 10 * t),
            int(22 + 12 * t),
            int(29 + 16 * t),
        )
        draw.line([(0, y), (size[0], y)], fill=color)
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse(
        (-size[0] // 5, -size[1] // 3, size[0] // 2, size[1] // 2),
        fill=(242, 184, 75, 26),
    )
    gdraw.ellipse(
        (size[0] // 2, size[1] // 2, size[0] + size[0] // 4, size[1] + size[1] // 3),
        fill=(79, 209, 197, 18),
    )
    bg = Image.alpha_composite(bg.convert("RGBA"), glow).convert("RGB")
    return bg


def save_card(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------


def render_title_card(
    path: Path,
    title: str,
    subtitle: str,
    kicker: str = "PODCAST COMMENTARY",
    background: Path | None = None,
) -> Path:
    img = background_from(background)
    draw = ImageDraw.Draw(img)
    margin = 180
    draw.rectangle([margin, 150, margin + 12, 430], fill=ACCENT)
    kicker_font = find_font(38, bold=True, text=kicker)
    draw.text((margin + 44, 156), kicker.upper(), font=kicker_font, fill=ACCENT)
    title_font = find_font(112, bold=True)
    draw_paragraph(draw, title, title_font, (margin + 44, 230), MASTER_W - 2 * margin - 44, PAPER, 18)
    sub_font = find_font(48)
    draw_paragraph(draw, subtitle, sub_font, (margin + 44, 760), MASTER_W - 2 * margin - 44, MUTED, 12)
    # Keep the disclosure out of the lower third: burned captions live there.
    disclosure = (
        "独立评论 · AI 生成语音"
        if contains_cjk(title) else
        "Independent commentary · AI-generated voice"
    )
    draw.text(
        (margin + 44, 92),
        disclosure,
        font=find_font(30, text=disclosure),
        fill=MUTED,
    )
    return save_card(img, path)


def render_quote_card(
    path: Path,
    quote: str,
    attribution: str,
    source: str,
    background: Path | None = None,
) -> Path:
    img = background_from(background)
    draw = ImageDraw.Draw(img)
    margin = 180
    draw.text((margin, 170), "“", font=find_font(220, bold=True), fill=ACCENT)
    quote_font = find_font(82, bold=True)
    y = draw_paragraph(draw, quote, quote_font, (margin + 24, 360), MASTER_W - 2 * margin - 48, PAPER, 18, 6)
    draw.rectangle([margin + 24, y + 50, margin + 24 + 120, y + 58], fill=ACCENT_2)
    draw_paragraph(draw, attribution, find_font(42, bold=True), (margin + 24, y + 90), 1500, PAPER, 8, 2)
    draw_paragraph(draw, source, find_font(28), (margin + 24, y + 200), 1700, MUTED, 6, 2)
    return save_card(img, path)


def render_list_card(
    path: Path,
    heading: str,
    bullets: list[str],
    kicker: str = "THE IDEA",
    background: Path | None = None,
) -> Path:
    img = background_from(background)
    draw = ImageDraw.Draw(img)
    margin = 180
    draw.text((margin, 150), kicker.upper(), font=find_font(36, bold=True, text=kicker), fill=ACCENT)
    draw_paragraph(draw, heading, find_font(88, bold=True), (margin, 230), MASTER_W - 2 * margin, PAPER, 16, 3)
    y = 570
    for i, bullet in enumerate(bullets[:5], start=1):
        draw.ellipse([margin, y + 14, margin + 22, y + 36], fill=ACCENT_2)
        y = draw_paragraph(
            draw,
            bullet,
            find_font(44),
            (margin + 62, y),
            MASTER_W - 2 * margin - 80,
            PAPER,
            10,
            2,
        )
        y += 30
    return save_card(img, path)


def render_end_card(
    path: Path,
    heading: str,
    question: str,
    next_text: str = "Subscribe for the next breakdown.",
    background: Path | None = None,
    disclosure: str | None = None,
) -> Path:
    img = background_from(background)
    draw = ImageDraw.Draw(img)
    margin = 180
    your_turn = "轮到你了" if contains_cjk(heading) else "YOUR TURN"
    draw.text((margin, 170), your_turn, font=find_font(38, bold=True, text=your_turn), fill=ACCENT)
    draw_paragraph(draw, heading, find_font(96, bold=True), (margin, 250), MASTER_W - 2 * margin, PAPER, 14, 3)
    draw_paragraph(draw, question, find_font(50), (margin, 590), MASTER_W - 2 * margin, PAPER, 12, 4)
    draw.rectangle([margin, 870, margin + 140, 878], fill=ACCENT_2)
    draw_paragraph(draw, next_text, find_font(40, bold=True), (margin, 930), 1500, PAPER, 8, 2)
    # Keep disclosure out of the lower third where burned captions sit.
    draw.text(
        (margin + 44, 92),
        disclosure or "This video uses an AI-generated avatar of the creator. The script, research and opinions are the creator's own.",
        font=find_font(30),
        fill=MUTED,
    )
    return save_card(img, path)


def render_lower_third(path: Path, text: str) -> Path:
    """Transparent 2560x1440 overlay with a short lower-third label."""
    img = Image.new("RGBA", (MASTER_W, MASTER_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = find_font(40, bold=True, text=text)
    pad_x, pad_y = 34, 18
    text_w = int(font.getlength(text))
    x, y = 120, MASTER_H - 190
    draw.rounded_rectangle(
        [x, y, x + text_w + 2 * pad_x, y + 40 + 2 * pad_y],
        radius=14,
        fill=(14, 17, 22, 200),
        outline=(242, 184, 75, 220),
        width=3,
    )
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=(244, 241, 234, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


def render_caption_overlay(path: Path, text: str, size: tuple[int, int] = (OUT_W, OUT_H)) -> Path:
    """Transparent caption PNG at output resolution.

    Burning ASS requires FFmpeg built with libass, which is not universal (the
    Homebrew build used here has neither libass nor drawtext). Rendering the
    caption to a PNG and compositing it with the `overlay` filter works on any
    FFmpeg with the core overlay filter.
    """
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = find_font(46, bold=True, text=text)
    lines = text.split("\n") or [text]
    line_h = int(font.size * 1.28)
    y = size[1] - 64 - line_h * len(lines)
    for line in lines:
        width = font.getlength(line)
        x = max(24.0, (size[0] - width) / 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=4,
            stroke_fill=(10, 12, 16, 235),
        )
        y += line_h
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


# ---------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------


def _wrap_mixed(text: str, width: int) -> list[str]:
    """Wrap mixed CJK/Latin text without splitting Latin words or URLs."""
    tokens = re.findall(r"\s+|[A-Za-z0-9][A-Za-z0-9.'’/%+\-:]*|[\u4e00-\u9fff]|[^\s]", text)
    lines: list[str] = []
    current = ""
    for token in tokens:
        if token.isspace() and not current:
            continue
        candidate = current + token
        if current and len(candidate) > width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
        while len(current) > width:
            lines.append(current[:width])
            current = current[width:]
    if current.strip():
        lines.append(current.rstrip())
    return lines


def caption_chunks(text: str, max_line: int = CAPTION_LINE, max_lines: int = CAPTION_LINES) -> list[str]:
    if contains_cjk(text):
        lines = _wrap_mixed(text, CAPTION_LINE_CJK)
        return ["\n".join(lines[i:i + max_lines]) for i in range(0, len(lines), max_lines)]
    width = max_line * max_lines
    text = text.strip()
    if len(text) <= width:
        return [text]
    parts: list[str] = []
    current = ""
    for token in re.split(r"(?<=[.!?])\s+", text):
        token = token.strip()
        if not token:
            continue
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


def _wrap_caption(text: str) -> str:
    if "\n" in text:
        return text
    if contains_cjk(text):
        lines = _wrap_mixed(text, CAPTION_LINE_CJK)
        return "\n".join(lines[:CAPTION_LINES])
    return "\n".join(textwrap.wrap(text, width=CAPTION_LINE, break_long_words=False))


def caption_entries(timeline: list[dict]) -> list[tuple[float, float, str]]:
    entries: list[tuple[float, float, str]] = []
    for shot in timeline:
        chunks = caption_chunks(shot["narration"])
        total = sum(len(c) for c in chunks) or 1
        lead = float(shot.get("lead", 0.0))
        t = shot["start"] + lead
        window = float(shot.get("audio_seconds", shot["duration"])) + CAPTION_TAIL
        for i, chunk in enumerate(chunks):
            share = window * len(chunk) / total
            start = t
            end = t + share
            if i == len(chunks) - 1:
                end = shot["start"] + shot["lead"] + window
            entries.append((start, end, _wrap_caption(chunk)))
            t = end
    cleaned: list[tuple[float, float, str]] = []
    for i, (start, end, text) in enumerate(entries):
        if i + 1 < len(entries):
            end = min(end, entries[i + 1][0] - 0.02)
        if end - start < 0.6:
            end = start + 0.6
        cleaned.append((start, end, text))
    return cleaned


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


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,42,&H00FFFFFF,&H00FFFFFF,&H00202B31,&H64000000,-1,0,0,0,100,100,0.3,0,1,3,0,2,120,120,48,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_srt(timeline: list[dict], path: Path) -> Path:
    lines = []
    for i, (start, end, text) in enumerate(caption_entries(timeline), start=1):
        lines.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    path.write_text("\n".join(lines))
    return path


def write_ass(timeline: list[dict], path: Path) -> Path:
    events = []
    for start, end, text in caption_entries(timeline):
        escaped = text.replace("\n", r"\N")
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{escaped}")
    path.write_text(ASS_HEADER + "\n".join(events) + "\n")
    return path
