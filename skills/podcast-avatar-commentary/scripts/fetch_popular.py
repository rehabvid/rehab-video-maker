#!/usr/bin/env python3
"""Fetch popular podcast transcripts from PodcastTranscript.ai.

The commentary episode starts with an episode choice, not with a render. This
script is deliberately small: it lists candidates by category and fetches one
full transcript. Selection and scoring stay editorial decisions.

Usage:
    python3 fetch_popular.py list --category technology --limit 10
    python3 fetch_popular.py get <id> > build/ep01/source.json
    python3 fetch_popular.py get <id> --segments > build/ep01/source.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://backend.podcasttranscript.ai/api/v1/transcriptions"
USER_AGENT = "podcast-avatar-commentary/1.0"
CATEGORIES = ["business", "technology", "news", "education", "science"]


def _get(url: str, timeout: int) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        print(f"error: could not reach PodcastTranscript.ai: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except json.JSONDecodeError as exc:
        print(f"error: unexpected response from {url}", file=sys.stderr)
        raise SystemExit(1) from exc


def fetch(category: str, limit: int = 10, language: str = "English",
          sort: str = "popular") -> list[dict]:
    params = {
        "sort": sort,
        "category": category.lower(),
        "limit": str(limit),
        "language": language,
    }
    data = _get(f"{BASE}?{urllib.parse.urlencode(params)}", timeout=30)
    if not data.get("ok"):
        print(json.dumps(data, indent=2), file=sys.stderr)
        raise SystemExit(1)
    return data.get("data", []) or []


def fetch_one(tid: str, include_segments: bool = False) -> dict:
    url = f"{BASE}/{urllib.parse.quote(tid)}"
    if include_segments:
        url += "?include=segments"
    data = _get(url, timeout=60)
    if not data.get("ok"):
        print(json.dumps(data, indent=2), file=sys.stderr)
        raise SystemExit(1)
    return data.get("data") or {}


def _slim(item: dict) -> dict:
    """Keep the fields needed to score an episode, not the whole payload."""
    return {
        "id": item.get("id"),
        "slug": item.get("slug"),
        "title": item.get("title"),
        "description": (item.get("description") or "")[:300],
        "duration": item.get("duration"),
        "language": item.get("language"),
        "category": item.get("category"),
        "summary": (item.get("summary") or "")[:500],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list popular transcripts")
    p_list.add_argument("--category", required=True, choices=CATEGORIES)
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--language", default="English")

    p_get = sub.add_parser("get", help="get one full transcript by id")
    p_get.add_argument("id")
    p_get.add_argument("--segments", action="store_true", help="include timestamped segments")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        items = fetch(args.category, args.limit, args.language)
        print(json.dumps([_slim(item) for item in items], indent=2, ensure_ascii=False))
        return 0

    item = fetch_one(args.id, args.segments)
    print(json.dumps(item, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
