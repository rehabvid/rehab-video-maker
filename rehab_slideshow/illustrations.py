"""Deterministic vector illustrations for rehabilitation storyboard frames.

Why vector instead of a diffusion model:

* the same patient, clothing, room and camera angle are guaranteed on every frame
* posture is parametric, so range of motion can be validated (no invented joints)
* renders in well under a second on any CPU
* no licence or consent issues, and no photorealistic wound depiction

The renderer draws a flat, poster-style scene: a patient standing at a wall in
right profile, plus a clinical overlay with the exercise name, recovery phase,
step, affected side, repetition and hold counts.

All geometry below is expressed in a 1280x720 design space and rasterised at
2x for anti-aliasing.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DESIGN_W, DESIGN_H = 1280, 720
SUPERSAMPLE = 2
W, H = DESIGN_W * SUPERSAMPLE, DESIGN_H * SUPERSAMPLE

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------
INK = "#23343C"
INK_SOFT = "#5A6B72"
INK_FAINT = "#93A2A7"
PAPER = "#F7F3EC"
WALL = "#FCF9F3"
WALL_EDGE = "#E4D8C6"
FLOOR = "#E7DCCA"
ACCENT = "#2F6F6A"
ACCENT_LIGHT = "#DCEBE8"
WARM = "#E9BFA1"
WARM_SHADE = "#D9A98A"
WARM_LINE = "#CFA083"
TOP = "#4C8C86"
TOP_SHADE = "#3E7A75"
TROUSER = "#4B5568"
TROUSER_SHADE = "#3F4859"
HAIR = "#463530"
SHOE = "#5E5147"
WHITE = "#FFFFFF"
ALERT = "#A9532F"

# --------------------------------------------------------------------------
# scene geometry
# --------------------------------------------------------------------------
FLOOR_Y = 612
WALL_X = 596  # left edge of the wall the patient faces
HAND_X = WALL_X + 16

SHOULDER = (510.0, 356.0)
HIP = (490.0, 486.0)
HEAD = (498.0, 292.0)
UPPER_ARM = 64.0
FOREARM = 58.0
REACH_TOP = 266.0  # hand height at full comfortable reach
REACH_START = 352.0  # hand at shoulder level

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    "/System/Library/Fonts",
]
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(style: str, size: int) -> ImageFont.FreeTypeFont:
    key = (style, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    names = {
        "regular": ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"],
        "bold": ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"],
        "italic": ["DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf", "Arial Italic.ttf"],
    }[style]
    for folder in FONT_DIRS:
        for name in names:
            path = Path(folder) / name
            if path.exists():
                font = ImageFont.truetype(str(path), size * SUPERSAMPLE)
                _FONT_CACHE[key] = font
                return font
    raise RuntimeError("no usable TrueType font found; install fonts-dejavu")


# --------------------------------------------------------------------------
# poses
# --------------------------------------------------------------------------
POSES: dict[str, dict] = {
    "intro": {"reach": 0.0, "arm": "down", "trail": False},
    "stance": {"reach": 0.0, "arm": "wall", "trail": False},
    "hands": {"reach": 0.03, "arm": "wall", "trail": False},
    "climb": {"reach": 0.42, "arm": "wall", "trail": True},
    "high": {"reach": 0.72, "arm": "wall", "trail": True},
    "hold": {"reach": 0.9, "arm": "wall", "trail": True, "timer": True},
    "lower": {"reach": 0.18, "arm": "wall", "trail": True, "down": True},
    "close": {"reach": 0.0, "arm": "down", "trail": False},
}


def pose_reach(name: str) -> float:
    return POSES[name]["reach"]


class Pen:
    """Thin wrapper that scales every coordinate into the supersampled canvas."""

    def __init__(self, image: Image.Image):
        self.image = image
        self.draw = ImageDraw.Draw(image, "RGBA")

    # -- primitives ------------------------------------------------------
    def line(self, points, fill, width, cap=True):
        pts = [(x * SUPERSAMPLE, y * SUPERSAMPLE) for x, y in points]
        w = width * SUPERSAMPLE
        self.draw.line(pts, fill=fill, width=int(w), joint="curve")
        if cap:
            for x, y in (pts[0], pts[-1]):
                r = w / 2
                self.draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    def ellipse(self, box, fill=None, outline=None, width=1):
        b = [v * SUPERSAMPLE for v in box]
        self.draw.ellipse(b, fill=fill, outline=outline, width=int(width * SUPERSAMPLE))

    def rect(self, box, fill=None, outline=None, width=1, radius=0):
        b = [v * SUPERSAMPLE for v in box]
        if radius:
            self.draw.rounded_rectangle(
                b, radius=radius * SUPERSAMPLE, fill=fill, outline=outline,
                width=int(width * SUPERSAMPLE),
            )
        else:
            self.draw.rectangle(b, fill=fill, outline=outline, width=int(width * SUPERSAMPLE))

    def polygon(self, points, fill=None, outline=None):
        pts = [(x * SUPERSAMPLE, y * SUPERSAMPLE) for x, y in points]
        self.draw.polygon(pts, fill=fill, outline=outline)

    def arc(self, box, start, end, fill, width):
        b = [v * SUPERSAMPLE for v in box]
        self.draw.arc(b, start=start, end=end, fill=fill, width=int(width * SUPERSAMPLE))

    def dashed(self, p0, p1, fill, width=2, dash=7, gap=6):
        x0, y0 = p0
        x1, y1 = p1
        total = math.hypot(x1 - x0, y1 - y0)
        if total == 0:
            return
        ux, uy = (x1 - x0) / total, (y1 - y0) / total
        pos = 0.0
        while pos < total:
            end = min(pos + dash, total)
            self.line(
                [(x0 + ux * pos, y0 + uy * pos), (x0 + ux * end, y0 + uy * end)],
                fill, width, cap=False,
            )
            pos = end + gap

    def text(self, xy, s, size=16, style="regular", fill=INK, anchor="la", spacing=0):
        font = _font(style, size)
        x, y = xy[0] * SUPERSAMPLE, xy[1] * SUPERSAMPLE
        if spacing:
            widths = [font.getlength(ch) + spacing * SUPERSAMPLE for ch in s]
            total = sum(widths)
            if anchor[0] == "m":
                x -= total / 2
            elif anchor[0] == "r":
                x -= total
            for ch, w in zip(s, widths):
                self.draw.text((x, y), ch, font=font, fill=fill, anchor="l" + anchor[1])
                x += w
            return
        self.draw.text((x, y), s, font=font, fill=fill, anchor=anchor)


def text_width(s: str, size: int, style: str = "regular", spacing: float = 0) -> float:
    font = _font(style, size)
    return sum(font.getlength(ch) for ch in s) / SUPERSAMPLE + spacing * len(s)


# --------------------------------------------------------------------------
# scene layers
# --------------------------------------------------------------------------
def _background(pen: Pen):
    top = (247, 243, 236)
    bottom = (240, 233, 221)
    for y in range(DESIGN_H):
        t = y / DESIGN_H
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        pen.rect([0, y, DESIGN_W, y + 1], fill=color)

    # the wall the patient faces: soft tonal plane with no hard card edge
    pen.rect([WALL_X, 0, DESIGN_W, FLOOR_Y], fill=WALL)
    for i in range(46):
        alpha = int(46 * (1 - i / 46))
        pen.rect([WALL_X + i, 0, WALL_X + i + 1, FLOOR_Y], fill=(206, 192, 171, alpha))
    pen.rect([WALL_X, FLOOR_Y - 14, DESIGN_W, FLOOR_Y], fill="#F1E9DC")
    pen.rect([WALL_X, FLOOR_Y - 14, DESIGN_W, FLOOR_Y - 12], fill="#E6D9C4")

    # soft portrait arch behind the patient
    pen.ellipse([214, 166, 646, 598], fill="#FAF0E8")

    # floor
    pen.rect([0, FLOOR_Y, DESIGN_W, DESIGN_H], fill=FLOOR)
    pen.rect([0, FLOOR_Y, DESIGN_W, FLOOR_Y + 2], fill="#D8CBB6")

    # contact shadow on the floor
    pen.ellipse([398, 590, 594, 622], fill=(202, 188, 166, 110))


def _arm_pose(reach: float):
    """Two-bone IK: shoulder -> elbow -> hand on the wall.

    The elbow is placed on the lower of the two IK solutions, which reads as a
    natural elbow-down posture in profile. When the reach exceeds arm length the
    hand stops just short of the wall and the drawn fingers bridge the gap.
    """
    hand = (HAND_X, REACH_START - (REACH_START - REACH_TOP) * reach)
    sx, sy = SHOULDER
    dx, dy = hand[0] - sx, hand[1] - sy
    dist = min(max(math.hypot(dx, dy), 1e-3), UPPER_ARM + FOREARM - 0.5)
    a = (UPPER_ARM**2 - FOREARM**2 + dist**2) / (2 * dist)
    h = math.sqrt(max(0.0, UPPER_ARM**2 - a**2))
    ux, uy = dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)
    base = (sx + a * ux, sy + a * uy)
    candidates = [
        (base[0] - h * uy, base[1] + h * ux),
        (base[0] + h * uy, base[1] - h * ux),
    ]
    elbow = max(candidates, key=lambda p: p[1])
    elbow = (min(elbow[0], WALL_X - 14), elbow[1])
    wrist = (sx + dist * ux, sy + dist * uy)
    return elbow, wrist


def _figure(pen: Pen, pose: dict):
    reach = pose["reach"]
    wall_arm = pose["arm"] == "wall"

    # ---- far leg (slightly shaded, behind) ----
    pen.line([(486, 486), (472, 548), (464, 604)], TROUSER_SHADE, 30)
    pen.line([(486, 486), (472, 548)], TROUSER_SHADE, 34)
    pen.rect([444, 598, 484, 614], fill="#4F443B", radius=5)  # far shoe

    # ---- near leg ----
    pen.line([(500, 486), (512, 548), (516, 604)], TROUSER, 30)
    pen.line([(500, 486), (512, 548)], TROUSER, 34)
    pen.rect([498, 598, 540, 614], fill=SHOE, radius=5)  # near shoe

    # ---- far arm, relaxed behind the torso ----
    if wall_arm:
        pen.line([(486, 356), (478, 420), (482, 478)], WARM_SHADE, 20)
        pen.ellipse([474, 472, 492, 490], fill=WARM_SHADE)

    # ---- torso ----
    torso = [
        (524, 346), (530, 360), (532, 380), (527, 400), (520, 422),
        (512, 446), (507, 468), (501, 486), (477, 486), (471, 468),
        (465, 444), (461, 418), (459, 390), (463, 366), (468, 350),
    ]
    pen.polygon(torso, fill=TOP)
    pen.polygon(
        [(524, 346), (530, 360), (532, 380), (527, 400), (520, 422),
         (512, 446), (507, 468), (501, 486), (492, 486), (496, 450),
         (500, 420), (502, 388), (500, 358)],
        fill=TOP_SHADE,
    )
    pen.rect([473, 474, 506, 486], fill=TROUSER)  # waistband

    # ---- neck and head ----
    pen.line([(496, 320), (504, 352)], WARM, 21)
    pen.ellipse([473, 263, 523, 321], fill=WARM)
    pen.ellipse([505, 294, 517, 310], fill=WARM_SHADE)     # ear
    pen.polygon([(521, 300), (528, 306), (521, 311)], fill=WARM)  # nose
    # hair: same styling on every frame
    pen.polygon([(473, 300), (475, 278), (484, 266), (500, 262),
                 (514, 268), (520, 280), (519, 292), (508, 296),
                 (492, 298), (478, 302)], fill=HAIR)
    pen.ellipse([455, 280, 478, 303], fill=HAIR)  # low bun
    pen.arc([479, 264, 522, 314], 190, 330, fill=HAIR, width=5)
    pen.ellipse([510, 292, 517, 299], fill=INK)                 # eye
    pen.arc([508, 306, 520, 316], 20, 140, fill=INK_SOFT, width=1.6)  # mouth

    # ---- affected arm ----
    if wall_arm:
        elbow, wrist = _arm_pose(reach)

        # outline pass keeps the arm readable against the torso and the wall
        pen.line([SHOULDER, elbow], WARM_LINE, 27)
        pen.line([elbow, wrist], WARM_LINE, 24)
        pen.line([SHOULDER, elbow], WARM, 22)
        sleeve_end = (
            SHOULDER[0] + (elbow[0] - SHOULDER[0]) * 0.30,
            SHOULDER[1] + (elbow[1] - SHOULDER[1]) * 0.30,
        )
        pen.line([SHOULDER, sleeve_end], TOP, 27)
        pen.line([elbow, wrist], WARM, 19)

        # palm flat on the wall, fingers pointing up the wall
        cx, cy = wrist
        pen.ellipse([cx - 14, cy - 16, cx + 14, cy + 16], fill=(47, 111, 106, 26))
        pen.ellipse([cx - 9, cy - 12, cx + 9, cy + 12], fill=WARM)
        pen.ellipse([cx - 9, cy - 12, cx + 9, cy + 12], outline=WARM_LINE, width=1.4)
        for i, dx in enumerate((-6.0, -2.0, 2.0, 6.0)):
            length = 13 if i in (1, 2) else 10
            pen.line([(cx + dx, cy - 9), (cx + dx, cy - 9 - length)], WARM, 3.2)
        pen.line([(cx - 9, cy - 2), (cx - 16, cy + 7)], WARM, 4.2)  # thumb
        return wrist

    # relaxed arm
    pen.line([SHOULDER, (522, 416), (518, 480)], WARM_LINE, 24)
    pen.line([SHOULDER, (522, 416), (518, 480)], WARM, 20)
    pen.line([SHOULDER, (515, 388)], TOP, 26)
    pen.ellipse([509, 474, 529, 494], fill=WARM)
    return None


def _timer(pen: Pen, seconds: int):
    cx, cy, r = 1128, 468, 48
    pen.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7], fill=WHITE)
    pen.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7],
                outline=ACCENT_LIGHT, width=2)
    pen.arc([cx - r, cy - r, cx + r, cy + r], -90, 270, fill=ACCENT, width=7)
    pen.text((cx, cy - 12), str(seconds), size=32, style="bold", fill=INK, anchor="mm")
    pen.text((cx, cy + 24), "SECONDS", size=9, style="bold", fill=INK_SOFT,
             anchor="mm", spacing=1.4)


def _wrap(text: str, max_width: float, size=16, style="regular") -> list[str]:
    font = _font(style, size)
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) / SUPERSAMPLE <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _overlay(pen: Pen, exercise: dict, frame: dict):
    title = exercise["title"]
    phase = exercise.get("phase_label") or exercise["recovery_phase"]
    reps = exercise["repetitions"]
    reps_max = exercise.get("repetitions_max")
    hold = exercise.get("hold_seconds")
    freq = exercise.get("frequency", "as advised")
    side = (exercise.get("affected_side") or "right").capitalize()
    x0 = WALL_X + 34

    pen.text((x0, 76), title, size=38, style="bold", fill=INK)
    pen.text((x0, 122), exercise.get("subtitle", ""), size=17, fill=INK_SOFT)

    # step counter + progress dots
    total = frame.get("_total", 1)
    index = frame.get("_index", 1)
    # keep 40 px of safe margin: the Ken Burns move crops the outer edge
    pen.text((1206, 76), f"STEP {index} OF {total}", size=11, style="bold",
             fill=INK_FAINT, anchor="ra", spacing=1.4)
    dots_x = 1206 - (total * 14 - 6)
    for i in range(total):
        cx = dots_x + i * 14
        fill = ACCENT if i == index - 1 else ("#C9D8D4" if i < index else "#E4DCCF")
        pen.ellipse([cx, 98, cx + 7, 105], fill=fill)

    # phase chip
    label = phase.upper()
    w1 = text_width(label, 12, "bold", 0.8) + 28
    pen.rect([x0, 158, x0 + w1, 188], fill=ACCENT, radius=15)
    pen.text((x0 + 14, 166), label, size=12, style="bold", fill=WHITE, spacing=0.8)

    # affected-side chip
    side_label = f"{side.upper()} ARM SHOWN"
    w2 = text_width(side_label, 11, "bold", 0.6) + 36
    pen.rect([x0 + w1 + 10, 158, x0 + w1 + 10 + w2, 188], fill="#F3E7D9", radius=15)
    pen.ellipse([x0 + w1 + 22, 169, x0 + w1 + 30, 177], fill=ALERT)
    pen.text((x0 + w1 + 38, 166), side_label, size=11, style="bold", fill="#7A4A2C",
             spacing=0.6)

    # heading
    pen.text((x0, 214), frame.get("heading") or frame["title"], size=27, style="bold", fill=INK)

    # bullets
    y = 258
    for bullet in frame.get("bullets", [])[:3]:
        first = True
        for line in _wrap(bullet, 556):
            if first:
                pen.ellipse([x0, y + 7, x0 + 6, y + 13], fill=ACCENT)
                pen.text((x0 + 16, y), line, size=16, fill=INK_SOFT)
                first = False
            else:
                pen.text((x0 + 16, y), line, size=16, fill=INK_SOFT)
            y += 24
        y += 4

    # protocol line
    reps_text = f"{reps} repetitions"
    if reps_max and reps_max != reps:
        reps_text += f" (build to {reps_max})"
    hold_text = f"hold {hold} s" if hold else (exercise.get("hold_note") or "no hold")
    pen.text((x0, 548), f"{reps_text}  ·  {hold_text}  ·  {freq}",
             size=15, style="bold", fill=INK)
    pen.text((x0, 572), "Move within a comfortable stretch. Stop if pain increases.",
             size=13, fill=INK_FAINT)

    if frame.get("timer"):
        _timer(pen, hold or 10)


def render_overlay(exercise: dict, frame: dict) -> Image.Image:
    """Text and badges only, on a transparent 1280x720 layer."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _overlay(Pen(layer), exercise, frame)
    return layer.resize((DESIGN_W, DESIGN_H), Image.LANCZOS)


def render_scene(exercise: dict, frame: dict, hi_res: bool = False,
                 with_figure: bool = True, person: Image.Image | None = None,
                 with_overlay: bool = True) -> Image.Image:
    """Render a single storyboard frame as 1280x720 or its 2x master.

    `person` is an optional full-canvas RGBA illustration (for example a
    diffusion-generated figure) that replaces the built-in vector figure.
    """
    image = Image.new("RGB", (W, H), PAPER)
    pen = Pen(image)
    _background(pen)
    if person is not None:
        layer = person.convert("RGBA")
        if layer.size != (W, H):
            layer = layer.resize((W, H), Image.LANCZOS)
        image.paste(layer, (0, 0), layer)
    elif with_figure:
        pose = POSES[frame["pose"]]
        _figure(pen, pose)
    if with_overlay:
        _overlay(pen, exercise, frame)
    if hi_res:
        return image
    return image.resize((DESIGN_W, DESIGN_H), Image.LANCZOS)


def render_frame(exercise: dict, frame: dict, out_path: Path, hi_res: bool = False,
                 person: Image.Image | None = None, with_overlay: bool = True) -> Path:
    image = render_scene(exercise, frame, hi_res=hi_res, person=person,
                         with_overlay=with_overlay)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return out_path
