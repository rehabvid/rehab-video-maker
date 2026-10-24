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
    option = {
        "grid": {"left": 76, "right": 40, "top": 78 if len(normalized) > 1 else 54, "bottom": 64, "containLabel": True},
        **({"legend": {"top": 10, "right": 10, "textStyle": {"fontSize": 14}}} if len(normalized) > 1 else {}),
        "xAxis": {"type": "category", "data": categories, "axisLabel": {"hideOverlap": True}},
        "yAxis": {
            "type": "value",
            **({"min": 0 if axis_min is not None and axis_min >= 0 else axis_min} if axis_min is not None else {}),
            **({"max": axis_max} if axis_max is not None else {}),
        },
        "series": [
            {
                "name": item["name"],
                "type": item["type"] if item["type"] in {"bar", "line", "pie"} else chart_type,
                "data": item["data"],
                "smooth": item["type"] == "line",
                "areaStyle": {} if item["type"] == "line" and chart_type == "line" else None,
            }
            for item in normalized
        ],
    }
    if chart_type == "pie":
        option = {
            "series": [{
                "type": "pie",
                "radius": ["28%", "72%"],
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


def _nodes_edges(spec: dict, kind: str) -> tuple[list[dict], list[dict]]:
    data = spec.get("data") or {}
    if isinstance(data.get("nodes"), list) and data["nodes"]:
        return data["nodes"], data.get("edges") or []
    points = [str(p) for p in (spec.get("points") or []) if str(p).strip()]
    if not points:
        points = [spec.get("title") or "The idea"]
    nodes = []
    edges = []
    if kind == "petrinet":
        for index, point in enumerate(points):
            place = f"p{index}"
            nodes.append({"id": place, "label": f"● {_clip(point, 42)}", "kind": "input" if index == 0 else "default"})
            if index < len(points) - 1:
                transition = f"t{index}"
                nodes.append({"id": transition, "label": f"▢ {_clip(point, 30)}", "kind": "accent"})
                edges.extend([
                    {"id": f"e{index}a", "source": place, "target": transition},
                    {"id": f"e{index}b", "source": transition, "target": f"p{index + 1}"},
                ])
    else:
        for index, point in enumerate(points):
            nodes.append({"id": f"n{index}", "label": _clip(point, 56), "kind": "input" if index == 0 else "default"})
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


def _scene(slug: str, shot: dict, module: Path) -> dict:
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
            "width": 1200,
            "height": 600,
            "file": _rel(asset, scene_dir),
            "layout": "auto",
            "direction": "LR",
            "grid": True,
            "fitViewPadding": 0.14,
            "flowAnimation": {
                "delay": 0.35,
                "duration": 0.55,
                "stagger": 0.10,
                "edgeDuration": 0.65,
                "edgeStagger": 0.08,
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
                "width": 1200,
                "height": 600,
                "file": _rel(asset, scene_dir),
                "chartAnimation": {
                    "mode": "values" if option.get("series", [{}])[0].get("type") in {"bar", "pie"} else "reveal",
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
            "width": 1200,
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
            "width": 1200,
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
    if points and kind != "markdown":
        items.append({
            "type": "markdown",
            "x": 1340,
            "y": 360,
            "width": 484,
            "height": 520,
            "content": "### Why it matters\n\n" + "\n".join(f"- {p}" for p in points),
            "size": "sm",
            "enter": {"type": "fade-up", "delay": 0.55, "duration": 0.8},
        })

    scene = {
        "id": scene_id,
        "duration": max(3.0, float(shot.get("duration") or 8.0)),
        "width": 1920,
        "height": 1080,
        "theme": "dark",
        "background": "theme",
        "variant": "slide",
        "padding": 96,
        "eyebrow": f"TECH COMMENTARY · {str(shot.get('id') or '')}",
        "title": title,
        "subtitle": spec.get("subtitle") or "",
        "footer": spec.get("source") or "Technical commentary",
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
        scenes.append(_scene(slug, shot, module))

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
