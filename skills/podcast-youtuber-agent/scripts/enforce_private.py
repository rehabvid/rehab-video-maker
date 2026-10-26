#!/usr/bin/env python3
"""Keep unattended uploads private even if YouTube processing flips visibility.

Usage::

    python enforce_private.py --latest --settle 180

The channel has shown a processing race where an insert marked private is
briefly reported public.  This verifies the newest upload receipt repeatedly
and re-applies the private status until it sticks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import youtube_upload  # noqa: E402


def _receipts() -> list[Path]:
    roots = [ROOT / "out", ROOT / "build"]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("**/youtube-zh.json", "**/youtube-upload.json", "**/youtube-en.json"):
            found.extend(root.glob(pattern))
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def _latest() -> Path | None:
    receipts = _receipts()
    return receipts[0] if receipts else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--settle", type=float, default=0.0, help="seconds before first check")
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args(argv)

    path = Path(args.receipt) if args.receipt else _latest()
    if path is None or not path.exists():
        print("no upload receipt found")
        return 0
    try:
        receipt = json.loads(path.read_text())
        video_id = receipt.get("video_id")
    except Exception as exc:  # noqa: BLE001
        print(f"cannot read receipt {path}: {exc}", file=sys.stderr)
        return 1
    if not video_id:
        print(f"no video id in {path}", file=sys.stderr)
        return 1

    auth = SimpleNamespace(
        token_file=str(youtube_upload.DEFAULT_TOKEN_FILE),
        client_secrets=str(youtube_upload.DEFAULT_CLIENT_SECRETS),
    )
    youtube = youtube_upload._youtube(auth, [youtube_upload.SCOPE_FORCE_SSL], False)
    if args.settle:
        time.sleep(args.settle)
    for attempt in range(max(1, args.attempts)):
        body = {
            "id": video_id,
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,
                "license": "youtube",
                "embeddable": False,
                "publicStatsViewable": False,
            },
        }
        try:
            youtube.videos().update(part="status", body=body).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"private update failed for {video_id}: {exc}", file=sys.stderr)
        time.sleep(5)
        status = youtube.videos().list(part="status", id=video_id).execute()
        items = status.get("items") or []
        visibility = items[0].get("status", {}).get("privacyStatus") if items else "missing"
        print(f"{video_id}: {visibility} (attempt {attempt + 1})")
        if visibility == "private":
            return 0
        time.sleep(60)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
