#!/usr/bin/env python3
"""Fetch top popular transcripts from PodcastTranscript.ai by category.

The skill must not reuse a source episode across runs.  ``list --exclude-used``
filters against a local ledger, and ``mark`` records the source IDs after a
video is published.  The default ledger is ``state/used-episodes.json``.
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://backend.podcasttranscript.ai/api/v1/transcriptions"
DEFAULT_USED_FILE = Path("state/used-episodes.json")


def fetch(category: str, limit: int = 10, language: str = "English", sort: str = "popular"):
    params = {
        "sort": sort,
        "category": category.lower(),
        "limit": str(limit),
        "language": language,
    }
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "podcast-youtuber-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        print(json.dumps(data, indent=2), file=sys.stderr)
        sys.exit(1)
    return data.get("data", [])


def fetch_one(tid: str, include_segments: bool = False):
    url = f"{BASE}/{tid}"
    if include_segments:
        url += "?include=segments"
    req = urllib.request.Request(url, headers={"User-Agent": "podcast-youtuber-agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        print(json.dumps(data, indent=2), file=sys.stderr)
        sys.exit(1)
    return data.get("data")


def load_used(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read used-episode ledger {path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        records = data.get("used") or data.get("episodes") or []
        return records if isinstance(records, list) else []
    return []


def used_source_ids(records: list[dict]) -> set[str]:
    ids: set[str] = set()
    for record in records:
        for source_id in record.get("source_ids", []):
            if source_id:
                ids.add(str(source_id))
        if record.get("id"):
            ids.add(str(record["id"]))
    return ids


def save_used(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"used": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List popular transcripts")
    p_list.add_argument("--category", required=True, choices=["business", "technology", "news", "education", "science"])
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--language", default="English")
    p_list.add_argument("--exclude-used", action="store_true", help="drop episodes already in the ledger")
    p_list.add_argument("--used-file", default=str(DEFAULT_USED_FILE))
    p_list.add_argument("--newest", action="store_true", help="sort the fetched candidates newest first")

    p_get = sub.add_parser("get", help="Get full transcript by id")
    p_get.add_argument("id")
    p_get.add_argument("--segments", action="store_true")

    p_mark = sub.add_parser("mark", help="Record source episodes as used")
    p_mark.add_argument("--id", dest="ids", action="append", required=True, help="source episode id; repeat for a combined video")
    p_mark.add_argument("--title", required=True)
    p_mark.add_argument("--video-id", default="")
    p_mark.add_argument("--url", default="")
    p_mark.add_argument("--note", default="")
    p_mark.add_argument("--used-file", default=str(DEFAULT_USED_FILE))

    args = parser.parse_args()

    if args.cmd == "list":
        ledger_path = Path(args.used_file)
        used_ids = used_source_ids(load_used(ledger_path))
        items = fetch(args.category, args.limit, args.language)
        if args.newest:
            items = sorted(items, key=lambda x: x.get("created_at") or "", reverse=True)
        skipped = 0
        slim = []
        for x in items:
            is_used = str(x.get("id") or "") in used_ids
            if args.exclude_used and is_used:
                skipped += 1
                continue
            slim.append({
                "id": x.get("id"),
                "slug": x.get("slug"),
                "title": x.get("title"),
                "description": (x.get("description") or "")[:300],
                "duration": x.get("duration"),
                "language": x.get("language"),
                "category": x.get("category"),
                "created_at": x.get("created_at"),
                "is_popular": x.get("is_popular"),
                "audio_url": x.get("audio_url"),
                "image": x.get("image"),
                "summary": (x.get("summary") or "")[:500],
                "used": is_used,
            })
        print(json.dumps(slim, indent=2, ensure_ascii=False))
        if args.exclude_used:
            print(
                f"excluded {skipped} used episode(s) from {ledger_path}",
                file=sys.stderr,
            )
    elif args.cmd == "get":
        item = fetch_one(args.id, args.segments)
        print(json.dumps(item, indent=2, ensure_ascii=False))
    elif args.cmd == "mark":
        ledger_path = Path(args.used_file)
        records = load_used(ledger_path)
        ids = list(dict.fromkeys(args.ids))
        already = sorted(set(ids) & used_source_ids(records))
        if already:
            print(
                "error: source episode(s) already used: " + ", ".join(already),
                file=sys.stderr,
            )
            return 1
        records.append({
            "source_ids": ids,
            "title": args.title,
            "video_id": args.video_id,
            "url": args.url,
            "note": args.note,
            "used_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        save_used(ledger_path, records)
        print(f"marked {', '.join(ids)} used in {ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
