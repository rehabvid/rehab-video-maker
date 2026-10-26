#!/usr/bin/env python3
"""Turn a visual plan into deterministic LinkZag.Show scenes and assets.

Only slides whose plan says they need a technical visual get a scene. Static
scenes are captured as one PNG; animated scenes are rendered as a short MP4
whose duration matches the measured narration. That keeps animation expensive
only where it earns attention.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_MODULE = Path("modules/linkZagShow")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "scene"


def _rel(path: Path, start: Path) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def _clip(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def _chart_unit(spec: dict, normalized: list[dict]) -> str:
    unit = spec.get("unit")
    if unit is not None:
        return str(unit).strip()
    names = " ".join(str(item.get("name") or "") for item in normalized).lower()
    if "%" in names or "percent" in names:
        return "%"
    return ""


def _chart_label_formatter(unit: str) -> str:
    return "{c}%" if unit == "%" else "{c}"


def _nice_interval(span: float, target_ticks: int = 5) -> float:
    """Choose a readable tick interval for a value axis."""
    if span <= 0:
        return 1.0
    raw = span / max(2, target_ticks)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    for step in (1.0, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        interval = step * magnitude
        if interval >= raw:
            return interval
    return 10.0 * magnitude


def _chart_option(spec: dict) -> dict | None:
    data = spec.get("data") or {}
    categories = data.get("categories") or data.get("labels") or []
    series = data.get("series") or []
    values = data.get("values")
    if values and not series:
        series = [{"name": data.get("name") or "Value", "data": values}]
    if not series:
        return None
    normalized = []
    for item in series:
        if isinstance(item, dict):
            normalized.append({
                "name": item.get("name") or "",
                "data": item.get("data") or item.get("values") or [],
                "type": item.get("type") or spec.get("chart_type") or "bar",
            })
        elif isinstance(item, list):
            normalized.append({
                "name": data.get("name") or "",
                "data": item,
                "type": spec.get("chart_type") or "bar",
            })
    if not normalized or not any(item["data"] for item in normalized):
        return None
    if not categories:
        categories = [str(i + 1) for i in range(max(len(item["data"]) for item in normalized))]
    chart_type = str(spec.get("chart_type") or normalized[0].get("type") or "bar").lower()
    numeric_values = [
        float(value)
        for item in normalized
        for value in item["data"]
        if isinstance(value, (int, float))
    ]
    axis_max = max(numeric_values) if numeric_values else None
    axis_min = min(numeric_values) if numeric_values else None
    if chart_type not in {"bar", "line", "area", "pie"}:
        chart_type = "bar"
    if chart_type == "area":
        chart_type = "line"
    unit = _chart_unit(spec, normalized)
    label_formatter = _chart_label_formatter(unit)
    # Give value labels breathing room above the largest bar/point and keep
    # the axis ticks on round numbers (avoid 16/15/-2.4528000000000003).
    raw_max = axis_max * 1.08 if axis_max is not None and axis_max >= 0 else axis_max
    raw_min = (
        0
        if axis_min is not None and axis_min >= 0
        else axis_min * 1.12 if axis_min is not None else axis_min
    )
    interval = 1.0
    if raw_max is not None and raw_min is not None:
        interval = _nice_interval(raw_max - raw_min)
        max_bound = math.ceil(raw_max / interval) * interval
        min_bound = math.floor(raw_min / interval) * interval
    else:
        max_bound = raw_max
        min_bound = raw_min
        interval = None
    option = {
        "grid": {
            "left": 86,
            "right": 60,
            "top": 72 if len(normalized) > 1 else 56,
            "bottom": 92,
            "containLabel": True,
        },
        **({"legend": {"top": 10, "right": 16, "textStyle": {"fontSize": 20}}} if len(normalized) > 1 else {}),
        "xAxis": {
            "type": "category",
            "data": categories,
            "axisLabel": {"fontSize": 20, "hideOverlap": True},
        },
        "yAxis": {
            "type": "value",
            **({"min": min_bound} if min_bound is not None else {}),
            **({"max": max_bound} if max_bound is not None else {}),
            **({"interval": interval} if interval is not None else {}),
            "axisLabel": {"fontSize": 20},
        },
        "labelLayout": {"hideOverlap": True},
        "series": [
            {
                "name": item["name"],
                "type": item["type"] if item["type"] in {"bar", "line", "pie"} else chart_type,
                "data": item["data"],
                "barMaxWidth": 150,
                "symbolSize": 10,
                "lineStyle": {"width": 4},
                "label": {
                    "show": True,
                    "position": "top",
                    "fontSize": 30,
                    "fontWeight": 600,
                    "formatter": label_formatter,
                },
                "smooth": item["type"] == "line",
                "areaStyle": {} if item["type"] == "line" and chart_type == "line" else None,
            }
            for item in normalized
        ],
    }
    # Two-point comparisons read better as direct-labelled dot/bar cards without
    # a redundant numeric axis.
    if len(categories) <= 2 and chart_type != "pie":
        option["yAxis"]["show"] = False
        option["grid"]["left"] = 74
    if chart_type == "pie":
        option = {
            "series": [{
                "type": "pie",
                "radius": ["28%", "72%"],
                "label": {
                    "show": True,
                    "fontSize": 26,
                    "formatter": "{b}\n{c}%",
                },
                "data": [
                    {"name": str(cat), "value": value}
                    for cat, value in zip(categories, normalized[0]["data"])
                ],
            }]
        }
    # Drop None values because ECharts treats an explicit null areaStyle as odd.
    for series_item in option.get("series", []):
        if series_item.get("areaStyle") is None:
            series_item.pop("areaStyle", None)
    return option


def _node_size(label: str) -> tuple[float, float]:
    """Keep generated flow nodes legible at 1080p instead of letting fitView
    shrink a wide graph into tiny labels."""
    width = max(220.0, min(320.0, 104.0 + len(label) * 8.0))
    height = 88.0 if len(label) > 34 else 76.0
    return width, height


def _sized_node(node: dict) -> dict:
    item = dict(node)
    label = str(item.get("label") or "")
    width, height = _node_size(label)
    item.setdefault("width", width)
    item.setdefault("height", height)
    return item


def _nodes_edges(spec: dict, kind: str) -> tuple[list[dict], list[dict]]:
    data = spec.get("data") or {}
    if isinstance(data.get("nodes"), list) and data["nodes"]:
        return [_sized_node(node) for node in data["nodes"]], data.get("edges") or []
    points = [str(p) for p in (spec.get("points") or []) if str(p).strip()]
    if not points:
        points = [spec.get("title") or "The idea"]
    nodes = []
    edges = []
    if kind == "petrinet":
        for index, point in enumerate(points):
            place = f"p{index}"
            nodes.append(_sized_node({"id": place, "label": f"● {_clip(point, 42)}", "kind": "input" if index == 0 else "default"}))
            if index < len(points) - 1:
                transition = f"t{index}"
                # A generated Petri net has no separate transition wording.
                # Reusing the place text made every idea appear twice; keep the
                # transition as a small silent marker instead.
                nodes.append({
                    "id": transition,
                    "label": "▢",
                    "kind": "accent",
                    "width": 64,
                    "height": 64,
                })
                edges.extend([
                    {"id": f"e{index}a", "source": place, "target": transition},
                    {"id": f"e{index}b", "source": transition, "target": f"p{index + 1}"},
                ])
    else:
        for index, point in enumerate(points):
            nodes.append(_sized_node({"id": f"n{index}", "label": _clip(point, 56), "kind": "input" if index == 0 else "default"}))
            if index:
                edges.append({"id": f"e{index}", "source": f"n{index - 1}", "target": f"n{index}"})
    return nodes, edges


def _svg(spec: dict) -> str:
    points = [str(p) for p in (spec.get("points") or []) if str(p).strip()] or [spec.get("title") or "The idea"]
    width = 1100
    row_h = 74
    height = max(260, 80 + row_h * len(points))
    rows = []
    for index, point in enumerate(points):
        y = 54 + index * row_h
        rows.append(f'<circle cx="44" cy="{y}" r="14" fill="#f2b84b"/>')
        if index < len(points) - 1:
            rows.append(f'<line x1="44" y1="{y + 14}" x2="44" y2="{y + row_h - 14}" stroke="#4ad0c8" stroke-width="4"/>')
        rows.append(f'<text x="86" y="{y + 8}" fill="#f4f1ea" font-family="Inter, sans-serif" font-size="30">{_xml_escape(_clip(point, 82))}</text>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="transparent"/>'
        + "".join(rows) + "</svg>"
    )


def _xml_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _markdown(spec: dict) -> str:
    points = spec.get("points") or []
    lines = [f"## {spec.get('title') or 'The idea'}", ""]
    lines.extend(f"- {point}" for point in points)
    return "\n".join(lines)


def _scene(
    slug: str,
    shot: dict,
    module: Path,
    episode: str = "COMMENTARY",
    language: str = "en",
) -> dict:
    visual = shot["visual"]
    kind = visual["type"]
    spec = visual.get("spec") or {}
    sid = _slug(str(shot.get("id") or "00"))
    scene_id = f"{_slug(slug)}-{sid}"
    scene_dir = module / "content" / "scenes" / "generated" / _slug(slug)
    asset_dir = module / "content" / "assets" / "generated" / _slug(slug)
    scene_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    title = spec.get("title") or shot.get("narration") or "The argument"
    points = spec.get("points") or []
    animated = bool(visual.get("animated"))
    items: list[dict] = []
    visual_item: dict | None = None

    if kind in {"dag", "petrinet"}:
        nodes, edges = _nodes_edges(spec, kind)
        asset = asset_dir / f"{sid}-{kind}.json"
        asset.write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=2) + "\n")
        visual_item = {
            "type": "xyflow",
            "x": 96,
            "y": 330,
            "width": 1728,
            "height": 600,
            "file": _rel(asset, scene_dir),
            "layout": "auto",
            "direction": "LR",
            "grid": True,
            "fitViewPadding": 0.08,
            "flowAnimation": {
                "delay": 0.35,
                "duration": 0.50,
                "stagger": 0.12,
                "edgeDuration": 0.70,
                "edgeStagger": 0.10,
            } if animated else {"enabled": False},
        }
    elif kind == "chart":
        option = _chart_option(spec)
        if option is None:
            kind = "markdown"
        else:
            asset = asset_dir / f"{sid}-chart.json"
            asset.write_text(json.dumps(option, indent=2) + "\n")
            visual_item = {
                "type": "echarts",
                "x": 96,
                "y": 330,
                "width": 1728,
                "height": 600,
                "file": _rel(asset, scene_dir),
                "chartAnimation": {
                    # Reveal the finished chart instead of scaling values:
                    # value-mode animates the labels too, briefly exposing
                    # long interpolated numbers such as 1.5274101046%.
                    "mode": "reveal",
                    "delay": 0.45,
                    "duration": 1.3,
                    "easing": "ease-out",
                } if animated else {"enabled": False},
            }
    if kind == "diagram" and visual_item is None:
        asset = asset_dir / f"{sid}-diagram.mmd"
        lines = ["flowchart LR"]
        for index, point in enumerate(points):
            lines.append(f'  n{index}["{point[:56].replace(chr(34), chr(39))}"]')
            if index:
                lines.append(f"  n{index - 1} --> n{index}")
        asset.write_text("\n".join(lines) + "\n")
        visual_item = {
            "type": "mermaid",
            "x": 96,
            "y": 330,
            "width": 1728,
            "height": 600,
            "file": _rel(asset, scene_dir),
            "enter": {"type": "draw", "delay": 0.45, "duration": 1.2} if animated else "none",
        }
    if kind == "svg" and visual_item is None:
        asset = asset_dir / f"{sid}-timeline.svg"
        asset.write_text(_svg(spec))
        visual_item = {
            "type": "image",
            "x": 96,
            "y": 330,
            "width": 1728,
            "height": 600,
            "src": _rel(asset, scene_dir),
            "fit": "contain",
            "alt": title,
        }
    if kind == "markdown" and visual_item is None:
        visual_item = {
            "type": "markdown",
            "x": 96,
            "y": 360,
            "width": 1728,
            "height": 520,
            "content": _markdown(spec),
            "size": "lg",
            "enter": {"type": "fade-up", "delay": 0.35, "duration": 0.8},
        }
    if visual_item is None:
        visual_item = {
            "type": "markdown",
            "x": 96,
            "y": 360,
            "width": 1728,
            "height": 520,
            "content": _markdown(spec),
            "size": "lg",
            "enter": {"type": "fade-up", "delay": 0.35, "duration": 0.8},
        }
    items.append(visual_item)

    scene = {
        "id": scene_id,
        "duration": max(3.0, float(shot.get("duration") or 8.0)),
        "width": 1920,
        "height": 1080,
        "theme": "dark",
        "background": "theme",
        "variant": "slide",
        "padding": 96,
        "eyebrow": f"{episode} · {str(shot.get('id') or '')}",
        "title": title,
        "subtitle": spec.get("subtitle") or "",
        "footer": spec.get("source")
        or f"{episode} · {'源音频' if language.lower().startswith('zh') else 'source audio'}",
        "items": items,
    }
    scene_path = scene_dir / f"{sid}.yaml"
    scene_path.write_text(yaml.safe_dump(scene, sort_keys=False, allow_unicode=True) + "\n")
    return {
        "id": shot.get("id"),
        "scene_id": scene_id,
        "scene": _rel(scene_path, module),
        "type": kind,
        "animated": animated,
        "duration": scene["duration"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--module", default=str(DEFAULT_MODULE))
    parser.add_argument("--out", help="manifest path (default: alongside the plan)")
    args = parser.parse_args(argv)

    plan_path = Path(args.plan)
    try:
        plan_data = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    module = Path(args.module).resolve()
    if not (module / "package.json").exists():
        print(f"error: LinkZag.Show not found at {module}", file=sys.stderr)
        return 1
    slug = plan_data.get("slug") or "episode"
    language = str(plan_data.get("language") or "en")
    title_text = str(plan_data.get("title") or "")
    title_prefix = title_text.split(":", 1)[0].strip() if ":" in title_text else ""
    episode = (
        "评论"
        if language.lower().startswith("zh")
        else (title_prefix if 0 < len(title_prefix) <= 14 else "COMMENTARY")
    )
    generated_scene_dir = module / "content" / "scenes" / "generated" / _slug(slug)
    generated_asset_dir = module / "content" / "assets" / "generated" / _slug(slug)
    for directory in (generated_scene_dir, generated_asset_dir):
        if directory.exists():
            for child in sorted(directory.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()

    scenes = []
    for shot in plan_data.get("shots", []):
        visual = shot.get("visual") or {}
        if visual.get("type") not in {"chart", "dag", "petrinet", "diagram", "svg", "markdown"}:
            continue
        scenes.append(_scene(slug, shot, module, episode=episode, language=language))

    manifest = {
        "slug": slug,
        "title": plan_data.get("title"),
        "module": str(module),
        "scenes": scenes,
    }
    out = Path(args.out) if args.out else plan_path.with_name("scenes.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out}: {len(scenes)} LinkZag scenes")
    for item in scenes:
        print(f"  {item['id']} {item['type']} {'animated' if item['animated'] else 'static'} {item['duration']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
