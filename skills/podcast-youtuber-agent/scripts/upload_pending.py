#!/usr/bin/env python3
"""Upload videos that were generated while YouTube quota was unavailable.

The generate-only autopilot writes ``pending-upload.json`` beside each finished
video.  This worker uploads one or more, updates the ledger, assigns playlists,
and keeps the video private.  On quota exhaustion it leaves the remaining
manifests in place for the next cooldown cycle.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UPLOAD = HERE / "youtube_upload.py"
PRIVATE = HERE / "enforce_private.py"
PLAYLISTS = HERE / "playlists.py"
LEDGER = ROOT / "state" / "used-episodes.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _pending() -> list[Path]:
    return sorted(
        (ROOT / "out").glob("**/pending-upload.json"),
        key=lambda path: path.stat().st_mtime,
    )


def _ensure_cover(manifest: dict, manifest_path: Path) -> Path | None:
    """Return a real Marina Bay cover; never fall back to the source podcast art."""
    thumbnail = Path(manifest.get("thumbnail") or "") if manifest.get("thumbnail") else None
    if thumbnail and thumbnail.exists() and thumbnail.name != "thumbnail.zh.png":
        return thumbnail
    metadata = Path(manifest.get("metadata") or "")
    if not metadata.exists():
        return None
    cover = manifest_path.parent / "cover.zh.png"
    if not cover.exists():
        cmd = [
            sys.executable,
            str(ROOT / "skills" / "podcast-cover-agent" / "scripts" / "cover.py"),
            "--metadata", str(metadata),
            "--out", str(cover),
            "--candidates", "1",
            "--timeout", "1200",
        ]
        print("+ " + " ".join(cmd), flush=True)
        if subprocess.run(cmd, cwd=ROOT).returncode:
            print(f"cover generation failed for {manifest_path}", file=sys.stderr)
            return None
    if not cover.exists():
        return None
    manifest["thumbnail"] = str(cover)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return cover


def _mark_uploaded(source_id: str, title: str, video_id: str, note: str) -> None:
    ledger = _load(LEDGER) if LEDGER.exists() else {"used": []}
    entries = ledger.setdefault("used", [])
    for entry in entries:
        if source_id in (entry.get("source_ids") or []):
            entry.update({
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "note": note,
            })
            break
    else:
        entries.append({
            "source_ids": [source_id],
            "title": title,
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "note": note,
        })
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--no-private-wait", action="store_true")
    args = parser.parse_args(argv)

    pending = _pending()
    if not pending:
        print("no pending uploads")
        return 0
    uploaded = 0
    for manifest_path in pending[: max(1, args.limit)]:
        try:
            manifest = _load(manifest_path)
        except Exception as exc:  # noqa: BLE001
            print(f"bad manifest {manifest_path}: {exc}", file=sys.stderr)
            continue
        video = Path(manifest.get("video") or "")
        metadata = Path(manifest.get("metadata") or "")
        if not video.exists() or not metadata.exists():
            print(f"missing video/metadata for {manifest_path}", file=sys.stderr)
            continue
        cover = _ensure_cover(manifest, manifest_path)
        if cover is None:
            print(f"no approved cover for {manifest_path}; leaving pending", file=sys.stderr)
            continue
        lang = str(manifest.get("language") or "zh-Hans")
        receipt = manifest_path.parent / ("youtube-en.json" if lang == "en" else "youtube-zh.json")
        cmd = [
            sys.executable, str(UPLOAD),
            "--video", str(video),
            "--metadata", str(metadata),
            "--privacy", "private",
            "--no-notify",
            "--receipt", str(receipt),
        ]
        for language, path, name in manifest.get("captions") or []:
            if Path(path).exists():
                cmd += ["--caption-track", f"{language}={path}|{name}"]
        cmd += ["--thumbnail", str(cover)]
        localizations = manifest.get("localizations")
        if localizations and Path(localizations).exists():
            cmd += ["--localizations", str(localizations)]
        print("+ " + " ".join(cmd), flush=True)
        code = subprocess.run(cmd, cwd=ROOT).returncode
        if code:
            print(f"upload failed for {manifest_path}; leaving pending", file=sys.stderr)
            # Quota errors are expected during cooldown; do not try the rest.
            return 2
        try:
            video_id = _load(receipt).get("video_id")
        except Exception:
            video_id = None
        if not video_id:
            print(f"no receipt video id for {manifest_path}", file=sys.stderr)
            return 2
        private = [
            sys.executable, str(PRIVATE),
            "--receipt", str(receipt), "--attempts", "3",
        ]
        if not args.no_private_wait:
            private[private.index("--attempts"):private.index("--attempts")] = [
                "--settle", "120"
            ]
        subprocess.run(private, cwd=ROOT)
        subprocess.run([
            sys.executable, str(PLAYLISTS), "add",
            "--video-id", video_id, "--metadata", str(metadata),
        ], cwd=ROOT)
        _mark_uploaded(
            str(manifest.get("source_id") or ""),
            str(manifest.get("title") or ""),
            video_id,
            str(manifest.get("note") or "generated in cooldown; uploaded after quota reset"),
        )
        done = manifest_path.with_name("pending-upload.uploaded.json")
        manifest_path.replace(done)
        uploaded += 1
        print(f"uploaded pending {video_id}: {done}", flush=True)
    print(f"uploaded {uploaded} pending video(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
