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
import shutil
import subprocess
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
COMFY_INPUT = ROOT / "tools" / "ComfyUI" / "input"
W, H = 1920, 1080
ORIENTATION = "landscape"
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


def _overlay_for(text: str, config: dict) -> str:
    low = text.lower()
    overlays = config.get("overlays") or {}
    rules = [
        ("ai", ("ai", "model", "agent", "gpu", "chip", "compute", "data center",
                "数据中心", "算力", "芯片", "模型", "智能体")),
        ("venture", ("venture", "startup", "fund", "investor", "valuation",
                     "融资", "初创", "估值", "基金")),
        ("trading", ("bond", "yield", "fed", "inflation", "market", "stock",
                     "债券", "收益率", "美联储", "通胀", "市场", "股票")),
    ]
    for name, words in rules:
        if any(word in low for word in words):
            return str((overlays.get(name) or {}).get("prompt") or "")
    default = config.get("defaults", {}).get("overlay")
    return str((overlays.get(default) or {}).get("prompt") or "")


def _scene_prompt(text: str, style: dict, config: dict) -> str:
    subject = re.sub(r"\s+", " ", text).strip()[:220]
    aspect = "9:16" if H > W else "16:9"
    parts = [
        str(style.get("prefix") or "").replace("16:9", aspect),
        f"illustrating {subject}",
        _overlay_for(text, config),
        f"no people, no text, no logos, {aspect}",
    ]
    return ", ".join(part for part in parts if part)


def _reference(text: str, config: dict) -> str | None:
    refs = config.get("references") or {}
    names = refs.get(ORIENTATION) or refs.get("landscape") or []
    if not names:
        return None
    index = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16) % len(names)
    path = Path(refs.get("source_dir") or "") / names[index]
    return str(path) if path.exists() else None


def _generate_scene(prompt: str, out: Path, seed: int, comfy_url: str, timeout: float,
                    reference: str | None = None, theme: str = "dark") -> bool:
    try:
        urllib.request.urlopen(comfy_url.rstrip("/") + "/system_stats", timeout=4)
    except OSError:
        return False
    sys.path.insert(0, str(ROOT / "tools" / "gen"))
    import comfy  # noqa: PLC0415
    comfy.SERVER = comfy_url.rstrip("/")
    ipadapter = None
    if reference and Path(reference).exists():
        try:
            COMFY_INPUT.mkdir(parents=True, exist_ok=True)
            source = Path(reference)
            name = f"story-reference-{source.stem}{source.suffix.lower()}"
            if not (COMFY_INPUT / name).exists():
                shutil.copyfile(source, COMFY_INPUT / name)
            ipadapter = name
        except OSError:
            ipadapter = None
    graph = comfy.graph(
        prompt,
        SCENE_NEGATIVE,
        width=W,
        height=H,
        steps=24,
        cfg=5.2,
        seed=seed,
        ckpt="sd_xl_base_1.0.safetensors",
        init_image=ipadapter,
        denoise=0.7,
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


def _compose_portrait(background: Path, shot: dict, out: Path, language: str,
                      light: bool = True) -> None:
    """Native 9:16 card: light paper panel, dark ink, larger title."""
    image = _fit(background)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel = (247, 243, 234, 220) if light else (8, 10, 14, 228)
    bar = (178, 92, 48) if light else (242, 184, 75)
    draw.rounded_rectangle([44, 100, W - 44, H - 120], radius=40, fill=panel)
    draw.rectangle([88, 150, 100, 330], fill=bar)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    if light:
        ink, muted, accent, accent2 = (24, 26, 30), (78, 80, 84), (178, 92, 48), (24, 116, 112)
    else:
        ink, muted, accent, accent2 = (244, 241, 234), (166, 173, 184), (242, 184, 75), (79, 209, 197)
    x, width = 132, W - 264
    kicker = str(shot.get("kicker") or "INDEPENDENT COMMENTARY")
    draw.text((x, 164), kicker.upper(), font=find_font(30, bold=True, text=kicker), fill=accent)
    kind = str(shot.get("kind") or "chart")
    if kind == "title":
        title = str(shot.get("on_screen") or shot.get("title") or "")
        title_size = 104 if len(title) <= 12 else 92 if len(title) <= 18 else 80
        y = draw_paragraph(draw, title, find_font(title_size, bold=True, text=title),
                           (x, 270), width, ink, 12, 4)
        sub = str(shot.get("subtitle") or "")
        if sub:
            draw_paragraph(draw, sub, find_font(38, text=sub), (x, max(1080, y + 60)), width, muted, 10, 4)
    elif kind == "quote":
        quote = str(shot.get("quote") or "")
        y = draw_paragraph(draw, f"“{quote}”", find_font(54, bold=True, text=quote), (x, 360), width, ink, 12, 6)
        attr = str(shot.get("attribution") or "")
        if attr:
            draw.text((x, y + 40), attr, font=find_font(32, bold=True, text=attr), fill=accent2)
    elif kind == "end":
        heading = str(shot.get("heading") or "")
        y = draw_paragraph(draw, heading, find_font(70, bold=True, text=heading), (x, 320), width, ink, 12, 3)
        question = str(shot.get("question") or "")
        if question:
            draw_paragraph(draw, question, find_font(36, text=question), (x, max(700, y + 50)), width, muted, 10, 5)
        nxt = str(shot.get("next_text") or "")
        if nxt:
            draw.text((x, H - 260), nxt, font=find_font(28, text=nxt), fill=muted)
    else:
        heading = str(shot.get("heading") or "")
        y = draw_paragraph(draw, heading, find_font(66, bold=True, text=heading), (x, 300), width, ink, 10, 3)
        y += 70
        accent2 = (79, 209, 197)
        for bullet in (shot.get("bullets") or [])[:3]:
            draw.ellipse([x, y + 14, x + 22, y + 36], fill=accent2)
            y = draw_paragraph(draw, str(bullet), find_font(40, text=str(bullet)),
                               (x + 46, y), width - 46, ink, 10, 3) + 46
        source = str(shot.get("source") or "")
        if source:
            draw.text((x, H - 250), source[:80], font=find_font(22, text=source), fill=muted)
    disclosure = "AI 生成语音 · 独立评论" if language.lower().startswith("zh") else "AI-generated voice · independent commentary"
    draw.text((x, H - 150), disclosure, font=find_font(22, text=disclosure), fill=muted)
    draw.text((x, H - 112), "LINKZAG.SHOW", font=find_font(22, text="LINKZAG.SHOW"), fill=muted)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PNG")


def _compose(
    background: Path,
    shot: dict,
    out: Path,
    light: bool,
    language: str,
) -> None:
    if H > W:
        return _compose_portrait(background, shot, out, language, light=light)
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
    parser.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    parser.add_argument("--render-style", default=None,
                        help="style id from cover-styles.json (default: sketch_dark)")
    parser.add_argument("--max-scenes", type=int, default=6)
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--seed-base", type=int, default=1200)
    parser.add_argument("--reference", help="optional img2img reference (off by default)")
    parser.add_argument("--engine", choices=["photo", "night", "minimal", "sdxl"], default="sdxl")
    args = parser.parse_args(argv)

    global W, H, ORIENTATION
    config = load_json(CONFIG)
    ORIENTATION = args.orientation
    if ORIENTATION == "portrait":
        W, H = 1080, 1920
    render_id = args.render_style or config["defaults"].get("render_style", "sketch")
    style = config["render_styles"].get(render_id)
    if not style:
        print(f"error: unknown render style {render_id}", file=sys.stderr)
        return 1
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
    light = str(style.get("theme") or "dark") == "light"
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
            prompt = _scene_prompt(text, style, config)
            seed = args.seed_base + int(hashlib.sha1(str(shot.get("id")).encode()).hexdigest()[:6], 16) % 10000
            candidate = out_dir / f"scene-{shot['id']}.png"
            generated = False
            if args.engine == "photo":
                refs = (config.get("references") or {}).get("landscape") or []
                index = int(hashlib.sha1(str(shot.get("id")).encode()).hexdigest()[:6], 16) % max(1, len(refs))
                source = Path(config.get("references", {}).get("source_dir", "")) / refs[index]
                generated = subprocess.run([
                    sys.executable, str(ROOT / "tools" / "gen" / "photo_night.py"),
                    "--source", str(source), "--out", str(candidate),
                    "--orientation", ORIENTATION,
                ]).returncode == 0
            elif args.engine == "night":
                # draw the light sketch (known good), then grade the PNG to night
                light_style = config["render_styles"]["sketch"]
                light_prompt = _scene_prompt(text, light_style, config)
                temp = out_dir / f"scene-{shot['id']}-light.png"
                generated = _generate_scene(light_prompt, temp, seed, args.comfy_url,
                                            args.timeout, reference=None, theme="light")
                if generated:
                    graded = subprocess.run([
                        sys.executable, str(ROOT / "tools" / "gen" / "night_grade.py"),
                        "--in", str(temp), "--out", str(candidate),
                        "--warmth", "0.4", "--accent", "0.3", "--teal", "0.55",
                    ]).returncode == 0
                    generated = graded
            elif args.engine == "minimal":
                overlay = "none"
                low = text.lower()
                if any(w in low for w in ("ai", "gpu", "chip", "compute", "数据中心", "算力", "芯片")):
                    overlay = "ai"
                elif any(w in low for w in ("venture", "startup", "fund", "融资", "初创", "基金")):
                    overlay = "venture"
                elif any(w in low for w in ("bond", "yield", "fed", "债券", "收益率", "美联储")):
                    overlay = "trading"
                refs = (config.get("references") or {}).get("landscape") or []
                source = Path(config.get("references", {}).get("source_dir", "")) / (refs[1] if len(refs) > 1 else refs[0])
                generated = subprocess.run([
                    sys.executable, str(ROOT / "tools" / "gen" / "minimal_skyline.py"),
                    "--source", str(source), "--out", str(candidate),
                    "--orientation", ORIENTATION, "--overlay", overlay,
                ]).returncode == 0
            else:
                generated = _generate_scene(prompt, candidate, seed, args.comfy_url, args.timeout,
                                            reference=args.reference,
                                            theme=str(style.get("theme") or "dark"))
            if generated:
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
