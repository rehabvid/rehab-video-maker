#!/usr/bin/env python3
"""Render LinkZag.Show scenes produced by make_scenes.py.

Static scenes become one PNG. Animated scenes become one MP4 at the measured
narration duration. This is the efficiency boundary: charts and process diagrams
can animate, but text/quote/end slides are not encoded as video unless needed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "scene"


def _run(cmd: list[str], cwd: Path) -> None:
    print("+ " + " ".join(str(part) for part in cmd))
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"command failed with exit {result.returncode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--visuals", required=True)
    parser.add_argument("--module", default="modules/linkZagShow")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--base-url", help="reuse a running LinkZag renderer")
    parser.add_argument("--keep-scenes", action="store_true", help="keep generated YAML/assets")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    module = Path(args.module).resolve()
    if not (module / "package.json").exists():
        print(f"error: LinkZag.Show not found at {module}", file=sys.stderr)
        return 1
    if not shutil.which("npm"):
        print("error: npm is required; install Node 22.22.2 or newer", file=sys.stderr)
        return 1
    visuals = Path(args.visuals).resolve()
    visuals.mkdir(parents=True, exist_ok=True)
    slug = _slug(manifest.get("slug") or "episode")
    npm = ["npm", "run", "linkzag", "--"]
    base = ["--project-root", str(module)]
    if args.base_url:
        base += ["--base-url", args.base_url]

    failures = []
    for scene in manifest.get("scenes", []):
        sid = str(scene.get("id"))
        scene_path = scene.get("scene")
        duration = float(scene.get("duration") or 8.0)
        if scene.get("animated"):
            cmd = npm + [
                "video",
                "--scene", scene_path,
                "--format", "mp4",
                "--fps", str(args.fps),
                "--out", str(visuals),
            ] + base
            if args.dry_run:
                print("+ " + " ".join(cmd))
                continue
            try:
                _run(cmd, module)
                produced = visuals / f"{scene.get('scene_id')}.mp4"
                target = visuals / f"shot-{sid}.mp4"
                if not produced.exists():
                    candidates = sorted(visuals.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
                    if not candidates:
                        raise RuntimeError(f"no MP4 produced for shot {sid}")
                    produced = candidates[-1]
                if produced != target:
                    produced.replace(target)
                print(f"visual {sid}: {target.name} ({duration:.1f}s)")
            except Exception as exc:  # noqa: BLE001 - report all, keep prior renders
                failures.append(f"shot {sid}: {exc}")
        else:
            target = visuals / f"shot-{sid}.png"
            cmd = npm + [
                "render",
                "--scene", scene_path,
                "--time", f"{duration:.3f}",
                "--out", str(target),
            ] + base
            if args.dry_run:
                print("+ " + " ".join(cmd))
                continue
            try:
                _run(cmd, module)
                print(f"visual {sid}: {target.name} (static)")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"shot {sid}: {exc}")

    if not args.keep_scenes and not args.dry_run:
        scene_dir = module / "content" / "scenes" / "generated" / slug
        asset_dir = module / "content" / "assets" / "generated" / slug
        for directory in (scene_dir, asset_dir):
            if directory.exists():
                shutil.rmtree(directory)
    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    print(f"rendered {len(manifest.get('scenes', []))} visuals into {visuals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
