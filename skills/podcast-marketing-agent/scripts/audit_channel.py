#!/usr/bin/env python3
"""Audit a YouTube channel's uploads with the Data API.

This intentionally uses only the upload token's force-ssl scope.  It cannot see
impressions/CTR/watch time; re-authorise with yt-analytics.readonly for those.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN = Path(os.path.expanduser("~/.config/podcast-youtuber-agent/token.json"))
CJK = re.compile(r"[\u3400-\u9fff]")


def _duration(text: str) -> int:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not match:
        return 0
    h, m, s = (int(group or 0) for group in match.groups())
    return h * 3600 + m * 60 + s


def _client(token: Path):
    if not token.exists():
        raise SystemExit(f"missing OAuth token: {token}")
    creds = Credentials.from_authorized_user_file(str(token))
    if not creds.valid:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def _channel(yt):
    response = yt.channels().list(
        part="snippet,statistics,contentDetails", mine=True
    ).execute()
    if not response.get("items"):
        raise SystemExit("token has no channel")
    return response["items"][0]


def _ids(yt, uploads: str) -> list[str]:
    ids: list[str] = []
    token = None
    while True:
        response = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token
        ).execute()
        ids.extend(item["contentDetails"]["videoId"] for item in response.get("items", []))
        token = response.get("nextPageToken")
        if not token:
            return ids


def _videos(yt, ids: list[str]) -> list[dict]:
    rows = []
    for start in range(0, len(ids), 50):
        response = yt.videos().list(
            part="snippet,status,statistics,contentDetails",
            id=",".join(ids[start:start + 50]),
        ).execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            title = snippet.get("title", "")
            rows.append({
                "id": item["id"],
                "title": title,
                "published_at": snippet.get("publishedAt", ""),
                "privacy": item.get("status", {}).get("privacyStatus", ""),
                "views": int(stats.get("viewCount") or 0),
                "likes": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
                "duration_seconds": _duration(item.get("contentDetails", {}).get("duration", "")),
                "title_script": "cjk" if CJK.search(title) else "latin",
                "url": f"https://youtu.be/{item['id']}",
            })
    return sorted(rows, key=lambda row: row["published_at"])


def _script_summary(rows: list[dict]) -> dict:
    summary = {}
    for script in ("cjk", "latin"):
        group = [row for row in rows if row["title_script"] == script]
        if not group:
            continue
        views = [row["views"] for row in group]
        summary[script] = {
            "videos": len(group),
            "views": sum(views),
            "median_views": statistics.median(views),
            "zero_view_videos": sum(1 for value in views if value == 0),
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", default=str(TOKEN))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    yt = _client(Path(args.token_file).expanduser())
    channel = _channel(yt)
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    rows = _videos(yt, _ids(yt, uploads))
    stats = channel.get("statistics", {})
    public = [row for row in rows if row["privacy"] == "public"]
    views = [row["views"] for row in rows]
    dates = Counter(row["published_at"][:10] for row in rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channel": {
            "id": channel["id"],
            "title": channel["snippet"].get("title", ""),
            "subscribers": int(stats.get("subscriberCount") or 0),
            "views": int(stats.get("viewCount") or 0),
            "videos": int(stats.get("videoCount") or 0),
        },
        "summary": {
            "videos_in_playlist": len(rows),
            "public": sum(1 for row in rows if row["privacy"] == "public"),
            "private": sum(1 for row in rows if row["privacy"] == "private"),
            "unlisted": sum(1 for row in rows if row["privacy"] == "unlisted"),
            "total_video_views": sum(views),
            "median_views": statistics.median(views) if views else 0,
            "zero_view_videos": sum(1 for value in views if value == 0),
            "upload_days": len(dates),
            "max_uploads_in_one_day": max(dates.values(), default=0),
            "title_script": _script_summary(rows),
        },
        "videos": rows,
        "top_videos": sorted(rows, key=lambda row: row["views"], reverse=True)[:10],
        "uploads_by_day": dict(sorted(dates.items())),
        "note": "Impressions, CTR and watch time need yt-analytics.readonly; this audit uses Data API counts only.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "channel": report["channel"],
        "summary": report["summary"],
        "top": [(v["views"], v["title"]) for v in report["top_videos"][:5]],
    }, ensure_ascii=False, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
