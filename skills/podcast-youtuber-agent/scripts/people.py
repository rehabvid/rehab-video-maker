#!/usr/bin/env python3
"""Collect short, cited biographies for the people in a podcast episode.

Usage::

    python3 scripts/people.py \
      --name "Lex Fridman" --name "Jensen Huang" \
      --out build/ep01/people.json

The output is intentionally a starting point, not a script.  Verify the roles,
company names and recent facts before recording.  For people without a
Wikipedia page, use the agent's web research and add a manual ``notes`` field.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "podcast-youtuber-agent/1.0 (editorial research)"
API = "https://en.wikipedia.org/api/rest_v1/page/summary/"


def fetch_person(name: str) -> dict:
    slug = urllib.parse.quote(name.strip().replace(" ", "_"))
    request = urllib.request.Request(
        API + slug,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        return {"name": name, "found": False, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"name": name, "found": False, "error": str(exc)}
    return {
        "name": name,
        "found": True,
        "title": data.get("title") or name,
        "description": data.get("description") or "",
        "extract": data.get("extract") or "",
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page", ""),
        "thumbnail": (data.get("thumbnail") or {}).get("source", ""),
        "source": "Wikipedia",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", action="append", required=True, help="person name; repeat")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    people = [fetch_person(name) for name in args.name]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"people": people}, indent=2, ensure_ascii=False) + "\n")
    for person in people:
        if person["found"]:
            print(f"found: {person['name']} — {person.get('description') or person.get('title')}")
        else:
            print(f"missing: {person['name']} ({person.get('error')})", file=sys.stderr)
    print(f"wrote {out}")
    return 0 if all(p["found"] for p in people) else 1


if __name__ == "__main__":
    raise SystemExit(main())
