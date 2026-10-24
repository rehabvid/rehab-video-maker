#!/usr/bin/env python3
"""Run a ComfyUI API workflow once per avatar shot.

The workflow is an *API-format* export from ComfyUI (Workflow -> Export (API)).
Put placeholders in the JSON and this client fills them per shot:

    {{IMAGE}}            canonical portrait (uploaded)
    {{AUDIO}}            narration clip (uploaded)
    {{PROMPT}}           positive prompt
    {{NEGATIVE_PROMPT}}  negative prompt
    {{SEED}}             integer seed
    {{LENGTH}}           integer frame count
    {{FPS}}              integer fps
    {{PREFIX}}           shot id, e.g. 01

Example:
    python3 comfy_client.py \
      --workflow workflows/echomimic_v3.api.json \
      --timing build/ep01/timing.json \
      --out build/ep01/avatar \
      --server http://127.0.0.1:8188 \
      --root .
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from lib import ffprobe_duration, load_json, run_ffmpeg, save_json, sha256_file

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
UPLOAD_KEYS = {"IMAGE", "AUDIO", "VIDEO", "MASK"}


def _request(url: str, *, data: bytes | None = None, headers: dict | None = None,
             method: str | None = None, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{exc.code} {exc.reason} from {url}\n{detail[:4000]}") from exc


def _post_json(server: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    raw = _request(
        f"{server.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(raw)


def _get_json(server: str, path: str) -> dict:
    return json.loads(_request(f"{server.rstrip('/')}{path}"))


def upload(server: str, path: Path) -> str:
    """Upload an image/audio file to ComfyUI's input directory."""
    boundary = "----podcast-avatar-" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in (("type", "input"), ("overwrite", "true")):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    raw = _request(
        f"{server.rstrip('/')}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    data = json.loads(raw)
    name = data.get("name") or path.name
    subfolder = data.get("subfolder") or ""
    return f"{subfolder}/{name}" if subfolder else name


def _resolve(value, replacements: dict, unresolved: set[str]):
    if isinstance(value, dict):
        return {k: _resolve(v, replacements, unresolved) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, replacements, unresolved) for v in value]
    if isinstance(value, str):
        whole = PLACEHOLDER.fullmatch(value.strip())
        if whole:
            key = whole.group(1)
            if key in replacements:
                return replacements[key]
            unresolved.add(key)
            return value

        def replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in replacements:
                unresolved.add(key)
                return match.group(0)
            return str(replacements[key])

        return PLACEHOLDER.sub(replace, value)
    return value


def _collect_outputs(history: dict, prompt_id: str) -> list[dict]:
    entry = history.get(prompt_id) or {}
    outputs = entry.get("outputs") or {}
    items: list[dict] = []
    for node in outputs.values():
        for key in ("videos", "gifs", "images", "audio"):
            for item in node.get(key, []) or []:
                if isinstance(item, dict) and item.get("filename"):
                    items.append(item)
    return items


def _download(server: str, item: dict, dest: Path) -> Path:
    query = urllib.parse.urlencode(
        {
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        }
    )
    raw = _request(f"{server.rstrip('/')}/view?{query}", timeout=300)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def _images_to_video(frames: list[Path], out: Path, fps: int) -> Path:
    if not frames:
        raise RuntimeError("no output frames")
    if len(frames) == 1:
        run_ffmpeg(["-loop", "1", "-i", str(frames[0]), "-t", "3", "-r", str(fps),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
        return out
    # ComfyUI numbers frames unpredictably; use the concat demuxer instead.
    listing = out.parent / f"{out.stem}-frames.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\nduration {1 / fps:.6f}\n" for p in frames))
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-r", str(fps),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def _fingerprint(workflow: Path, image: Path | None, audio: Path | None, values: dict) -> str:
    h = hashlib.sha256()
    h.update(workflow.read_bytes())
    if image:
        h.update(sha256_file(image).encode())
    if audio:
        h.update(sha256_file(audio).encode())
    h.update(json.dumps(values, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def run(args) -> int:
    timing_path = Path(args.timing).resolve()
    timing = load_json(timing_path)
    fps = int(timing.get("fps") or 30)
    root = Path(args.root).resolve()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = Path(args.workflow).resolve()
    workflow = load_json(workflow_path)

    shots = [s for s in timing["shots"] if s.get("kind") == "avatar"]
    if not shots:
        print("no avatar shots; nothing to render")
        return 0
    if not args.server:
        print("error: --server is required unless --dry-run is used", file=sys.stderr)
        return 1

    for index, shot in enumerate(shots, start=1):
        sid = shot["id"]
        image_path = (root / shot["visual"]).resolve() if shot.get("visual") else None
        audio_path = (timing_path.parent / shot["audio"]).resolve()
        if image_path and not image_path.exists():
            print(f"error: shot {sid}: missing image {image_path}", file=sys.stderr)
            return 1
        if not audio_path.exists():
            print(f"error: shot {sid}: missing audio {audio_path}", file=sys.stderr)
            return 1

        frames = max(1, round(float(shot["audio_seconds"]) * fps))
        frames = ((frames - 1) // 4) * 4 + 1  # Wan VAE temporal stride
        explicit_seed = shot.get("seed")
        base_seed = int(explicit_seed if explicit_seed is not None else (args.seed or 43))
        seed = base_seed if (args.same_seed or explicit_seed is not None) else base_seed + index
        values: dict = {
            "PROMPT": shot.get("prompt") or args.prompt,
            "NEGATIVE_PROMPT": shot.get("negative_prompt") or args.negative_prompt,
            "SEED": seed,
            "LENGTH": frames,
            "FPS": fps,
            "PREFIX": sid,
        }
        image_hash = sha256_file(image_path) if image_path else "none"
        audio_hash = sha256_file(audio_path)
        fp = _fingerprint(workflow_path, image_path, audio_path, values)
        target = out_dir / f"shot-{sid}.mp4"
        sidecar = out_dir / f"shot-{sid}.json"
        if target.exists() and sidecar.exists() and not args.force:
            try:
                if json.loads(sidecar.read_text()).get("fingerprint") == fp:
                    print(f"[{index}/{len(shots)}] shot {sid}: cached")
                    continue
            except json.JSONDecodeError:
                pass

        if args.dry_run:
            resolved = _resolve(workflow, {**values, "IMAGE": str(image_path), "AUDIO": str(audio_path)}, set())
            print(f"[{index}/{len(shots)}] shot {sid}: {frames} frames, seed {seed}")
            print(json.dumps(resolved, indent=2)[:2500])
            continue

        print(f"[{index}/{len(shots)}] shot {sid}: uploading inputs")
        replacements = dict(values)
        if image_path:
            replacements["IMAGE"] = upload(args.server, image_path)
        replacements["AUDIO"] = upload(args.server, audio_path)

        unresolved: set[str] = set()
        resolved = _resolve(workflow, replacements, unresolved)
        if unresolved:
            print(
                f"error: workflow has placeholders with no value: {', '.join(sorted(unresolved))}",
                file=sys.stderr,
            )
            return 1

        print(f"[{index}/{len(shots)}] shot {sid}: queued ({frames} frames, seed {seed})")
        try:
            response = _post_json(args.server, "/prompt", {"prompt": resolved, "client_id": uuid.uuid4().hex})
        except RuntimeError as exc:
            print(f"error: ComfyUI rejected the workflow:\n{exc}", file=sys.stderr)
            return 1
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            print(f"error: no prompt_id in response: {response}", file=sys.stderr)
            return 1

        started = time.time()
        history = {}
        while time.time() - started < args.timeout:
            history = _get_json(args.server, f"/history/{prompt_id}")
            if prompt_id in history:
                break
            time.sleep(args.poll)
        if prompt_id not in history:
            print(f"error: shot {sid} timed out after {args.timeout}s", file=sys.stderr)
            return 1

        items = _collect_outputs(history, prompt_id)
        if not items:
            print(f"error: shot {sid} produced no output: {json.dumps(history, indent=2)[:2000]}", file=sys.stderr)
            return 1

        videos = [i for i in items if Path(i["filename"]).suffix.lower() in {".mp4", ".webm", ".mov", ".mkv", ".gif"}]
        images = [i for i in items if Path(i["filename"]).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        if videos:
            _download(args.server, videos[0], target)
            if len(videos) > 1:
                print(f"  warning: {len(videos)} videos returned; using {videos[0]['filename']}")
        elif images:
            tmp = out_dir / f".shot-{sid}-frames"
            tmp.mkdir(parents=True, exist_ok=True)
            downloaded = [_download(args.server, item, tmp / item["filename"]) for item in images]
            downloaded.sort(key=lambda p: p.name)
            _images_to_video(downloaded, target, fps)
        else:
            print(f"error: shot {sid} returned only unsupported outputs: {items}", file=sys.stderr)
            return 1

        duration = ffprobe_duration(target)
        save_json(
            sidecar,
            {
                "shot": sid,
                "fingerprint": fp,
                "image": str(image_path) if image_path else None,
                "audio": str(audio_path),
                "image_hash": image_hash,
                "audio_hash": audio_hash,
                "seed": seed,
                "frames": frames,
                "duration": duration,
                "prompt_id": prompt_id,
            },
        )
        print(f"  wrote {target} ({duration:.2f}s)")

    if not args.dry_run:
        print(f"done: {len(shots)} avatar shots in {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True, help="ComfyUI API-format workflow JSON")
    parser.add_argument("--timing", required=True, help="timing.json from tts.py")
    parser.add_argument("--out", required=True, help="avatar output directory")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--root", default=".", help="project root for visual paths")
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--same-seed", action="store_true", help="use the same seed for every shot")
    parser.add_argument("--prompt", default="A person sitting at a desk, speaking casually to the camera.")
    parser.add_argument(
        "--negative-prompt",
        default="bad hands, extra fingers, fused fingers, distorted face, warped background, text, watermark",
    )
    parser.add_argument("--timeout", type=int, default=7200, help="seconds per shot")
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
