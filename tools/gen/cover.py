#!/usr/bin/env python3
"""Generate a photorealistic editorial cover plate with ComfyUI and overlay text.

The diffusion model supplies the background only.  Text is drawn with PIL so
Chinese/English titles stay sharp and never turn into garbled glyphs.

Typical use::

    tools/ComfyUI/.venv/bin/python tools/ComfyUI/main.py --port 8188 &
    .venv/bin/python tools/gen/cover.py \
      --style energy \
      --title "柴油瓶颈与法国的账单" \
      --stat "25–35%" \
      --subtitle "独立评论 · MacroVoices #554" \
      --out out/ep01/cover.zh.png

The default SDXL graph is 1216x704, which keeps generation under a minute on
an M2 Pro for 24-30 steps.  The final cover is 1280x720.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import comfy  # noqa: E402
from lib import (  # noqa: E402
    ACCENT,
    ACCENT_2,
    MUTED,
    PAPER,
    contains_cjk,
    draw_paragraph,
    find_font,
    wrap_by_width,
)

W, H = 1280, 720
COMFY_INPUT = ROOT / "tools" / "ComfyUI" / "input"


NEGATIVE = (
    "text, letters, typography, watermark, logo, signature, caption, "
    "deformed, distorted, extra fingers, bad anatomy, low quality, blurry, "
    "oversaturated, cartoon, anime, 3d render, illustration, cluttered, "
    "hud, infographic, chart, graph"
)

STYLES = {
    "energy": (
        "cinematic editorial photograph of a vast oil refinery and diesel "
        "storage tanks at blue hour, pipelines and distillation towers, wet "
        "ground reflections, distant flare, dramatic side light, shallow "
        "depth of field, muted teal and amber palette, premium financial "
        "magazine cover, no people, no text, 16:9"
    ),
    "france": (
        "cinematic editorial photograph of the French National Assembly "
        "exterior at dusk, French tricolour, limestone architecture, rain "
        "and dramatic sky, blurred euro banknotes in the foreground, muted "
        "blue and gold palette, premium financial magazine cover, no text, "
        "16:9"
    ),
    "ai": (
        "cinematic editorial photograph inside a modern AI data centre, long "
        "aisle of server racks, amber and cyan status lights, cooling pipes, "
        "shallow depth of field, dramatic side light, premium technology "
        "magazine cover, no people, no text, 16:9"
    ),
    "macro": (
        "cinematic still life of bond certificates, euro banknotes, a brass "
        "oil canister and a dark wooden table, dramatic chiaroscuro light, "
        "shallow depth of field, muted teal and gold palette, premium "
        "financial magazine cover, no text, 16:9"
    ),
    "default": (
        "cinematic editorial photograph of a global financial market at "
        "dusk, abstract city skyline and trading screens, dramatic light, "
        "muted teal and amber palette, premium financial magazine cover, "
        "no people, no text, 16:9"
    ),
}


def _check_server(url: str) -> None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/system_stats", timeout=3):
            return
    except OSError as exc:
        raise RuntimeError(
            f"ComfyUI is not reachable at {url}. Start it with:\n"
            "  tools/ComfyUI/.venv/bin/python tools/ComfyUI/main.py --port 8188"
        ) from exc


def _fit(path: Path) -> Image.Image:
    with Image.open(path) as raw:
        image = raw.convert("RGB")
    scale = max(W / image.width, H / image.height)
    resized = image.resize(
        (max(W, int(image.width * scale)), max(H, int(image.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - W) // 2
    top = (resized.height - H) // 2
    return resized.crop((left, top, left + W, top + H))


def _left_gradient(image: Image.Image, theme: str = "dark") -> Image.Image:
    x = np.arange(W, dtype=np.float32)[None, :]
    if theme == "light":
        # A cream paper panel across the text safe zone, with a soft right edge.
        edge = W * 0.56
        fade = W * 0.24
        alpha = np.where(
            x < edge,
            248.0,
            np.clip(248.0 * (1.0 - (x - edge) / fade), 0, 248),
        ).astype(np.uint8)
        color = (247, 243, 234, 0)
    else:
        alpha = np.clip(232.0 * (1.0 - x / (W * 0.74)), 0, 232).astype(np.uint8)
        color = (4, 7, 12, 0)
    alpha = np.repeat(alpha, H, axis=0)
    overlay = Image.new("RGBA", (W, H), color)
    overlay.putalpha(Image.fromarray(alpha, mode="L"))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _balanced_title(text: str, font, max_width: int) -> list[str]:
    lines = wrap_by_width(text, font, max_width)
    if len(lines) <= 1:
        return lines
    last = lines[-1].strip()
    if len(last) > 2 and not all(ch in "？?！!。,.，、" for ch in last):
        return lines
    flat = " ".join(text.split())
    if len(flat) < 4:
        return lines
    cut = len(flat) // 2
    spaces = [i for i, ch in enumerate(flat) if ch == " "]
    if spaces:
        cut = min(spaces, key=lambda i: abs(i - cut))
    first, second = flat[:cut].strip(), flat[cut:].strip()
    if not first or not second:
        return lines
    if (
        len(wrap_by_width(first, font, max_width)) == 1
        and len(wrap_by_width(second, font, max_width)) == 1
    ):
        return [first, second]
    return lines


def _cover_text(
    image: Image.Image,
    *,
    title: str,
    stat: str,
    subtitle: str,
    kicker: str,
    language: str,
    theme: str = "dark",
) -> Image.Image:
    image = _left_gradient(image, theme)
    draw = ImageDraw.Draw(image)
    margin = 72
    if theme == "light":
        text_color, muted, accent, accent2 = (18, 20, 24), (78, 80, 84), (178, 92, 48), (24, 116, 112)
    else:
        text_color, muted, accent, accent2 = PAPER, MUTED, ACCENT, ACCENT_2
    title_size = 78 if len(title) <= 12 else 70 if len(title) <= 18 else 60
    title_font = find_font(title_size, bold=True, text=title)
    kicker_font = find_font(28, bold=True, text=kicker)
    stat_font = find_font(92, bold=True)
    subtitle_font = find_font(32, text=subtitle)
    small_font = find_font(22, text=subtitle)

    draw.rectangle([margin, 78, margin + 9, 300], fill=accent)
    draw.text((margin + 26, 72), kicker.upper(), font=kicker_font, fill=accent)
    title_y = 126
    for line in _balanced_title(title, title_font, 820)[:3]:
        draw.text((margin + 26, title_y), line, font=title_font, fill=text_color)
        title_y += int(title_size * 1.22) + 10
    if stat:
        draw.text((margin + 26, 478), stat, font=stat_font, fill=accent2)
    if subtitle:
        draw_paragraph(
            draw, subtitle, subtitle_font, (margin + 26, 600), 820, muted, 6, 2
        )
    disclosure = (
        "AI 生成语音 · 独立评论"
        if language.lower().startswith("zh")
        else "AI-generated voice · independent commentary"
    )
    draw.text((margin, H - 44), disclosure, font=small_font, fill=muted)
    draw.text((W - 198, H - 44), "LINKZAG.SHOW", font=small_font, fill=muted)
    return image


def _generate(args) -> Path:
    _check_server(args.comfy_url)
    comfy.SERVER = args.comfy_url.rstrip("/")
    prompt = args.prompt or STYLES[args.style]
    ipadapter = None
    if args.reference:
        source = Path(args.reference).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        COMFY_INPUT.mkdir(parents=True, exist_ok=True)
        name = f"cover-reference-{source.stem}{source.suffix.lower()}"
        shutil.copyfile(source, COMFY_INPUT / name)
        ipadapter = name
    graph = comfy.graph(
        prompt,
        args.negative or NEGATIVE,
        width=args.width,
        height=args.height,
        steps=args.steps,
        cfg=args.cfg,
        seed=args.seed,
        ckpt=args.checkpoint,
        ipadapter_image=ipadapter,
        ipadapter_weight=args.reference_weight,
    )
    return comfy.generate(
        graph, Path(args.out).with_suffix(".plate.png"), timeout=args.timeout
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--stat", default="")
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--kicker", default="INDEPENDENT COMMENTARY")
    parser.add_argument("--language", choices=["zh-Hans", "en"], default=None)
    parser.add_argument("--theme", choices=["light", "dark"], default="dark")
    parser.add_argument("--style", choices=sorted(STYLES), default="default")
    parser.add_argument("--prompt", help="override the style prompt")
    parser.add_argument("--negative", help="override the negative prompt")
    parser.add_argument("--reference", help="optional IPAdapter style reference image")
    parser.add_argument("--reference-weight", type=float, default=0.65)
    parser.add_argument("--background", help="skip generation and use this image")
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1216)
    parser.add_argument("--height", type=int, default=704)
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--cfg", type=float, default=5.5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--checkpoint", default="sd_xl_base_1.0.safetensors")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--metadata", help="read title/subtitle from youtube metadata")
    args = parser.parse_args(argv)

    if args.metadata:
        data = json.loads(Path(args.metadata).read_text())
        args.title = args.title or data.get("title")
        if not args.subtitle:
            args.subtitle = "独立评论" if contains_cjk(args.title) else "Independent commentary"
    if not args.title:
        parser.error("--title or --metadata is required")
    if args.language is None:
        args.language = "zh-Hans" if contains_cjk(args.title) else "en"

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.background:
        source = Path(args.background).expanduser()
    else:
        source = _generate(args)
    image = _fit(source)
    cover = _cover_text(
        image,
        title=args.title,
        stat=args.stat,
        subtitle=args.subtitle,
        kicker=args.kicker,
        language=args.language,
        theme=args.theme,
    )
    cover.save(out, "PNG")
    print(f"wrote {out} ({cover.width}x{cover.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
