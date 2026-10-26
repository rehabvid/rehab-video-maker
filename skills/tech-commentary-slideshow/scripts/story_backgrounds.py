#!/usr/bin/env python3
"""Give card slides a semi-transparent story background.

The default video look used dark studio cards.  This pass keeps the cover-page
art direction but lets it live behind the text:

* abstract pages use the approved cover image as a semi-transparent backdrop;
* concrete pages get one generated sketch illustration in the same visual
  language (price tags, refineries, data centres, bond certificates, etc.);
* title/quote/end cards are composed as full-frame b-roll images so the
  assembler does not paint the old dark card over them.

Use ``--no-generate`` to use the cover only, or ``--no-scene-backgrounds`` at
the caller to disable the whole pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
from lib import find_font, draw_paragraph, load_json, save_json, wrap_by_width  # noqa: E402

CONFIG = ROOT / "skills" / "podcast-cover-agent" / "config" / "cover-styles.json"
W, H = 1920, 1080
SCENE_WORDS = {
    "price tag", "grocery", "egg", "basket", "agent", "server", "data center",
    "data centre", "chip", "robot", "oil", "tanker", "refinery", "pipeline",
    "diesel", "france", "national assembly", "euro", "bond", "bank", "amazon",
    "walmart", "meta", "microphone", "boardroom", "japan", "church", "camera",
    "film", "factory", "grid", "power", "coal", "nuclear", "hormuz", "store",
    "价格", "鸡蛋", "购物", "价签", "智能体", "服务器", "数据中心", "芯片",
    "机器人", "石油", "油轮", "炼油", "柴油", "法国", "欧元", "债券",
    "银行", "亚马逊", "沃尔玛", "麦克风", "日本", "教堂", "电影", "工厂",
    "电网", "电力", "核能", "霍尔木兹", "商店",
}
ABSTRACT = {
    "my analysis", "the question", "what i would watch", "three tests",
    "the framework", "conclusion", "the close", "what can still",
    "我的分析", "结论", "三个检验", "我会盯什么", "问题",
}
SCENE_NEGATIVE = (
    "text, letters, typography, watermark, logo, signature, caption, deformed, "
    "distorted, extra fingers, bad anatomy, low quality, blurry, oversaturated, "
    "cartoon, anime, 3d render, cluttered, hud, infographic, chart, graph, "
    "people, faces, photograph, photorealistic, neon, glossy"
)


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


def _light(image: Image.Image) -> bool:
    small = image.resize((64, 64)).convert("L")
    return sum(small.getdata()) / (64 * 64) > 145


def _scene_worthy(text: str) -> bool:
    low = text.lower()
    if any(word in low for word in ABSTRACT):
        return False
    return any(word in low for word in SCENE_WORDS)


def _scene_prompt(text: str, style: str) -> str:
    subject = re.sub(r"\s+", " ", text).strip()[:220]
    if style == "photo":
        return (
            "cinematic editorial photograph illustrating "
            f"{subject}, dramatic side light, shallow depth of field, muted teal "
            "and amber palette, photorealistic, 35mm, premium finance magazine, "
            "no people, no text, no logos, 16:9"
        )
    return (
        "architectural ink and watercolour sketch illustrating "
        f"{subject}, fine linework, cross-hatching, muted teal and amber "
        "watercolour washes, cream paper, editorial magazine illustration, "
        "no people, no text, no logos, 16:9"
    )


def _generate_scene(prompt: str, out: Path, seed: int, comfy_url: str, timeout: float) -> bool:
    try:
        urllib.request.urlopen(comfy_url.rstrip("/") + "/system_stats", timeout=4)
    except OSError:
        return False
    sys.path.insert(0, str(ROOT / "tools" / "gen"))
    import comfy  # noqa: PLC0415
    comfy.SERVER = comfy_url.rstrip("/")
    graph = comfy.graph(
        prompt,
        SCENE_NEGATIVE,
        width=1216,
        height=704,
        steps=24,
        cfg=5.2,
        seed=seed,
        ckpt="sd_xl_base_1.0.safetensors",
    )
    try:
        comfy.generate(graph, out, timeout=timeout)
    except Exception:
        return False
    return out.exists()


def _panel(draw: ImageDraw.ImageDraw, light: bool) -> None:
    box = [60, 54, 1170, 1026]
    if light:
        draw.rounded_rectangle(box, radius=34, fill=(247, 243, 234, 220))
        draw.rectangle([96, 112, 106, 240], fill=(178, 92, 48))
    else:
        draw.rounded_rectangle(box, radius=34, fill=(10, 12, 16, 215))
        draw.rectangle([96, 112, 106, 240], fill=(242, 184, 75))


def _compose(
    background: Path,
    shot: dict,
    out: Path,
    light: bool,
    language: str,
) -> None:
    image = _fit(background)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _panel(draw, light)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    ink = (24, 26, 30) if light else (244, 241, 234)
    muted = (78, 80, 84) if light else (166, 173, 184)
    accent = (178, 92, 48) if light else (242, 184, 75)
    accent2 = (24, 116, 112) if light else (79, 209, 197)
    x = 132
    kicker = str(shot.get("kicker") or "INDEPENDENT COMMENTARY")
    draw.text((x, 108), kicker.upper(), font=find_font(28, bold=True, text=kicker), fill=accent)
    kind = str(shot.get("kind") or "chart")
    if kind == "title":
        title = str(shot.get("on_screen") or shot.get("title") or "")
        font = find_font(92 if len(title) <= 16 else 76, bold=True, text=title)
        y = draw_paragraph(draw, title, font, (x, 180), 960, ink, 10, 3)
        sub = str(shot.get("subtitle") or "")
        if sub:
            draw_paragraph(draw, sub, find_font(36, text=sub), (x, max(700, y + 40)), 900, muted, 8, 2)
    elif kind == "quote":
        quote = str(shot.get("quote") or "")
        y = draw_paragraph(draw, f"“{quote}”", find_font(52, bold=True, text=quote), (x, 220), 940, ink, 10, 6)
        attr = str(shot.get("attribution") or "")
        if attr:
            draw.text((x, y + 30), attr, font=find_font(30, bold=True, text=attr), fill=accent2)
        source = str(shot.get("source") or "")
        if source:
            draw.text((x, y + 90), source, font=find_font(22, text=source), fill=muted)
    elif kind == "end":
        heading = str(shot.get("heading") or "")
        draw_paragraph(draw, heading, find_font(80, bold=True, text=heading), (x, 250), 940, ink, 10, 3)
        question = str(shot.get("question") or "")
        if question:
            draw_paragraph(draw, question, find_font(36, text=question), (x, 600), 920, muted, 8, 4)
        nxt = str(shot.get("next_text") or "")
        if nxt:
            draw.text((x, 930), nxt, font=find_font(24, text=nxt), fill=muted)
    else:
        heading = str(shot.get("heading") or "")
        draw_paragraph(draw, heading, find_font(74, bold=True, text=heading), (x, 190), 960, ink, 8, 3)
        bullets = shot.get("bullets") or []
        y = 560
        for bullet in bullets[:4]:
            draw.ellipse([x, y + 12, x + 20, y + 32], fill=accent2)
            y = draw_paragraph(draw, str(bullet), find_font(34, text=str(bullet)), (x + 40, y), 900, ink, 8, 2) + 22
        source = str(shot.get("source") or "")
        if source:
            draw.text((x, 960), source, font=find_font(20, text=source), fill=muted)
    disclosure = "AI 生成语音 · 独立评论" if language.lower().startswith("zh") else "AI-generated voice · independent commentary"
    draw.text((W - 430, H - 46), disclosure, font=find_font(20, text=disclosure), fill=muted)
    draw.text((W - 210, H - 46), "LINKZAG.SHOW", font=find_font(20, text="LINKZAG.SHOW"), fill=muted)
    image.save(out, "PNG")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--scene-slides", help="English deck for scene prompts")
    parser.add_argument("--timing", required=True)
    parser.add_argument("--cover", required=True)
    parser.add_argument("--out", required=True, help="output timing JSON")
    parser.add_argument("--language", default="en")
    parser.add_argument("--render-style", choices=["sketch", "photo"], default="sketch")
    parser.add_argument("--max-scenes", type=int, default=6)
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--seed-base", type=int, default=1200)
    args = parser.parse_args(argv)

    slides = load_json(Path(args.slides))
    scene_slides = load_json(Path(args.scene_slides)) if args.scene_slides else slides
    timing = load_json(Path(args.timing))
    cover = Path(args.cover).expanduser()
    if not cover.exists():
        print(f"error: cover not found: {cover}", file=sys.stderr)
        return 1
    # A finished cover has its title/stat baked in.  For a video background we
    # want the raw plate so the old cover text does not ghost through the panel.
    if not cover.stem.endswith(".plate"):
        plate = cover.with_name(cover.stem + ".plate.png")
        if plate.exists():
            cover = plate
    by_id = {str(s.get("id")): s for s in slides.get("shots", [])}
    scene_by_id = {str(s.get("id")): s for s in scene_slides.get("shots", [])}
    light = _light(_fit(cover))
    out_dir = Path(args.out).parent / "story-cards"
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = 0
    for shot in timing.get("shots", []):
        if shot.get("kind") not in {"title", "chart", "quote", "end"}:
            continue
        if isinstance(shot.get("visual"), str) and shot.get("visual"):
            continue
        src = by_id.get(str(shot.get("id"))) or {}
        scene_src = scene_by_id.get(str(shot.get("id"))) or src
        text = " ".join([
            str(scene_src.get("heading") or ""),
            str(scene_src.get("quote") or ""),
            " ".join(str(x) for x in scene_src.get("bullets") or []),
            str(scene_src.get("narration") or "")[:400],
        ])
        background = cover
        if (
            not args.no_generate
            and scenes < args.max_scenes
            and _scene_worthy(text)
        ):
            prompt = _scene_prompt(text, args.render_style)
            seed = args.seed_base + int(hashlib.sha1(str(shot.get("id")).encode()).hexdigest()[:6], 16) % 10000
            candidate = out_dir / f"scene-{shot['id']}.png"
            if _generate_scene(prompt, candidate, seed, args.comfy_url, args.timeout):
                background = candidate
                scenes += 1
                print(f"scene background {shot['id']}: {candidate.name}", flush=True)
            else:
                print(f"scene unavailable {shot['id']}; using cover", flush=True)
        card = out_dir / f"shot-{shot['id']}.png"
        _compose(background, src or shot, card, light, args.language)
        shot["kind"] = "broll"
        shot["visual"] = os.path.relpath(card, ROOT).replace(os.sep, "/")
        shot["visual_type"] = "story_card"
        print(f"story card {shot['id']}: {card.name}", flush=True)
    save_json(Path(args.out), timing)
    print(f"wrote {args.out}: {scenes} generated scenes", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
