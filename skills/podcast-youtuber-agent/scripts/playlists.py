#!/usr/bin/env python3
"""Classify a video and add it to the channel's series playlists.

The channel uses a small fixed set of series playlists (AI, macro, energy,
Europe, investors, AI capex/power) instead of separate channels.  This helper
scores the video title, tags and description against the keyword rules in
``state/youtube-playlists.json`` and can add the video to the best matches.

Usage::

    # Inspect the classification first
    python playlists.py classify \
      --metadata build/ep01/youtube.zh.json

    # Add to the best 1-3 playlists
    python playlists.py add \
      --video-id <youtube-id> \
      --metadata build/ep01/youtube.zh.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONFIG = ROOT / "state" / "youtube-playlists.json"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import youtube_upload  # noqa: E402


def _load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("playlists"), list):
        raise ValueError(f"{path}: expected an object with a playlists list")
    return data


def _hit(text: str, keyword: str) -> bool:
    keyword = keyword.lower().strip()
    if not keyword:
        return False
    if re.search(r"[a-z0-9]", keyword):
        pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return keyword in text


def classify(metadata: dict, config: dict, limit: int = 3) -> list[dict]:
    title = str(metadata.get("title") or "").lower()
    tags = " ".join(str(tag) for tag in metadata.get("tags") or []).lower()
    description = str(metadata.get("description") or "").lower()
    scored: list[dict] = []
    for playlist in config["playlists"]:
        score = 0
        hits: list[str] = []
        for keyword in playlist.get("keywords") or []:
            if _hit(title, keyword):
                score += 3
                hits.append(keyword)
            if _hit(tags, keyword):
                score += 2
                if keyword not in hits:
                    hits.append(keyword)
            if _hit(description, keyword):
                score += 1
                if keyword not in hits:
                    hits.append(keyword)
        if score:
            scored.append({
                "name": playlist["name"],
                "id": playlist["id"],
                "score": score,
                "hits": hits,
            })
    scored.sort(key=lambda item: item["score"], reverse=True)
    selected = scored[: max(1, limit)]
    fallback = config.get("fallback")
    if not selected and fallback:
        for playlist in config["playlists"]:
            if playlist["name"] == fallback:
                selected = [{
                    "name": playlist["name"],
                    "id": playlist["id"],
                    "score": 0,
                    "hits": ["fallback"],
                }]
                break
    return selected


def _youtube(args):
    auth = SimpleNamespace(
        token_file=str(args.token_file),
        client_secrets=str(args.client_secrets),
    )
    return youtube_upload._youtube(
        auth, [youtube_upload.SCOPE_FORCE_SSL], allow_login=False
    )


def _already_in(youtube, playlist_id: str, video_id: str) -> bool:
    response = youtube.playlistItems().list(
        part="id", playlistId=playlist_id, videoId=video_id, maxResults=1
    ).execute()
    return bool(response.get("items"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["classify", "add"])
    parser.add_argument("--metadata", required=True, help="youtube.json or youtube.zh.json")
    parser.add_argument("--video-id", help="YouTube video id (required for add)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--token-file", default=str(youtube_upload.DEFAULT_TOKEN_FILE))
    parser.add_argument("--client-secrets", default=str(youtube_upload.DEFAULT_CLIENT_SECRETS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        metadata = json.loads(Path(args.metadata).read_text())
        config = _load(Path(args.config))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    selected = classify(metadata, config, args.limit)
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    if args.command == "classify" or args.dry_run:
        return 0
    if not args.video_id:
        parser.error("--video-id is required for add")

    youtube = _youtube(args)
    failures = 0
    for item in selected:
        if _already_in(youtube, item["id"], args.video_id):
            print(f"already in {item['name']}: {args.video_id}")
            continue
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": item["id"],
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": args.video_id,
                        },
                    }
                },
            ).execute()
            print(f"added {args.video_id} to {item['name']} ({item['id']})")
        except Exception as exc:  # noqa: BLE001 - report and keep other adds
            failures += 1
            print(f"error: {item['name']}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
