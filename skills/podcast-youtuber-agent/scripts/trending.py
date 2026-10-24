#!/usr/bin/env python3
"""Rank fresh podcast interviews from PodcastTranscript.ai and top YouTube channels.

The goal is not to scrape every podcast on the internet. It is to build a
short, defensible candidate list from sources that publish full interviews and
have retrievable transcripts:

* PodcastTranscript.ai (business and technology lists);
* a curated set of AI, technology, startup and markets YouTube channels that
  upload full episodes.  YouTube transcripts are checked with
  ``youtube-transcript-api``.

Ranking combines popularity (views or source rank), recency, topic fit
(AI/technology/markets), and whether a priority founder, investor, trader or
interviewer appears in the title/description.  The editorial score is a
shortlisting aid; the agent still verifies the guest and episode by web
research before writing the script.

Used sources are filtered from ``state/used-episodes.json`` by default.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from fetch_popular import fetch, fetch_one, load_used, used_source_ids  # noqa: E402

DEFAULT_SOURCES = HERE.parent / "config" / "trending-sources.json"
DEFAULT_PEOPLE = HERE.parent / "config" / "priority-people.json"
DEFAULT_USED = Path("state/used-episodes.json")
DEFAULT_TOKEN = Path.home() / ".config" / "podcast-youtuber-agent" / "token.json"

TOPIC_WEIGHTS = {
    "artificial intelligence": 6,
    "ai": 5,
    "machine learning": 5,
    "openai": 4,
    "nvidia": 4,
    "semiconductor": 4,
    "startup": 3,
    "founder": 3,
    "venture": 3,
    "stock": 4,
    "market": 2,
    "invest": 3,
    "trading": 3,
    "earnings": 3,
    "ipo": 3,
    "technology": 2,
    "tech": 2,
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _parse_duration(value: str | None) -> int:
    if not value:
        return 0
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?",
        value,
    )
    if not match:
        return 0
    parts = match.groupdict()
    return int(
        float(parts.get("days") or 0) * 86400
        + float(parts.get("hours") or 0) * 3600
        + float(parts.get("minutes") or 0) * 60
        + float(parts.get("seconds") or 0)
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(value: str | None, now: datetime) -> float:
    when = _parse_time(value)
    if when is None:
        return 9999.0
    return max(0.0, (now - when.astimezone(timezone.utc)).total_seconds() / 86400)


def _normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _similar_title(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.9


def _matches(text: str, people: list[dict]) -> list[dict]:
    haystack = f" {text.lower()} "
    hits = []
    for person in people:
        name = str(person.get("name") or "").lower()
        if name and name in haystack:
            hits.append(person)
    return hits


def _topic_hits(text: str) -> list[str]:
    haystack = text.lower()
    hits = []
    for term in TOPIC_WEIGHTS:
        if re.search(r"\b" + re.escape(term) + r"\b", haystack):
            hits.append(term)
    return hits


def _youtube_client(token_file: Path):
    if not token_file.exists():
        print(f"warning: no YouTube token at {token_file}; skipping YouTube sources", file=sys.stderr)
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        print(
            "warning: Google API libraries are not installed; run "
            "`uv sync --extra trending` or `uv sync --extra youtube`",
            file=sys.stderr,
        )
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_file))
        if not creds.valid:
            if not creds.refresh_token:
                raise RuntimeError("token has no refresh token; rerun youtube_upload.py --auth")
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)
    except Exception as exc:  # noqa: BLE001 - keep the PT fallback alive
        print(f"warning: YouTube auth failed: {exc}; skipping YouTube sources", file=sys.stderr)
        return None


def _youtube_candidates(yt, channels: list[dict], config: dict, now: datetime) -> list[dict]:
    candidates: list[dict] = []
    max_per_channel = int(config.get("max_per_channel") or 20)
    min_duration = int(config.get("min_duration_minutes") or 20) * 60
    max_age = timedelta(days=int(config.get("max_age_days") or 45))
    for channel in channels:
        channel_id = channel.get("id")
        if not channel_id:
            continue
        uploads = "UU" + channel_id[2:] if channel_id.startswith("UC") else channel_id
        try:
            listing = yt.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads,
                maxResults=max_per_channel,
            ).execute()
            video_ids = [
                item["contentDetails"]["videoId"]
                for item in listing.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            if not video_ids:
                continue
            details = yt.videos().list(
                part="snippet,contentDetails,statistics",
                id=",".join(video_ids[:50]),
            ).execute()
        except Exception as exc:  # noqa: BLE001 - one bad channel should not stop the run
            print(f"warning: YouTube channel {channel.get('name')}: {exc}", file=sys.stderr)
            continue

        for item in details.get("items", []):
            published = _parse_time(item.get("snippet", {}).get("publishedAt"))
            if published is None or published < now - max_age:
                continue
            duration = _parse_duration(item.get("contentDetails", {}).get("duration"))
            if duration < min_duration:
                continue
            snippet = item.get("snippet", {})
            title = snippet.get("title") or ""
            description = snippet.get("description") or ""
            candidates.append({
                "source": "youtube",
                "source_ids": [item.get("id")],
                "title": title,
                "channel": snippet.get("channelTitle") or channel.get("name") or "",
                "url": f"https://www.youtube.com/watch?v={item.get('id')}",
                "published_at": snippet.get("publishedAt"),
                "duration_seconds": duration,
                "views": int(item.get("statistics", {}).get("viewCount") or 0),
                "description": description[:1200],
                "tier": int(channel.get("tier") or 2),
                "transcript": None,
            })
    return candidates


def _podcast_candidates(category: str, limit: int, now: datetime) -> list[dict]:
    items = fetch(category, limit, "English")
    out: list[dict] = []
    for rank, item in enumerate(items):
        created = item.get("created_at")
        age = _age_days(created, now)
        out.append({
            "source": "podcasttranscript",
            "source_ids": [item.get("id")],
            "title": item.get("title") or "",
            "channel": item.get("category") or category,
            "url": item.get("audio_url") or "",
            "published_at": created,
            "duration_seconds": int(item.get("duration") or 0),
            "views": 0,
            "description": (item.get("summary") or item.get("description") or "")[:1200],
            "tier": 2,
            "transcript": True,
            "source_rank": rank,
            "source_count": max(1, len(items)),
            "is_popular": bool(item.get("is_popular")),
            "age_days": age,
        })
    return out


def _score(candidate: dict, max_views: int, people: list[dict], now: datetime) -> dict:
    text = f"{candidate.get('title', '')} {candidate.get('description', '')}"
    person_hits = _matches(text, people)
    topics = _topic_hits(text)
    age = candidate.get("age_days")
    if age is None:
        age = _age_days(candidate.get("published_at"), now)
    recency = max(0.0, 20.0 - float(age) / 2.0)
    authority = 10 if candidate.get("tier") == 1 else 6
    topic_score = min(20.0, float(sum(TOPIC_WEIGHTS[t] for t in topics)))

    if candidate["source"] == "youtube":
        views = int(candidate.get("views") or 0)
        popularity = (
            35.0 * math.log10(views + 1) / math.log10(max_views + 1)
            if max_views > 0
            else 0.0
        )
    else:
        rank = int(candidate.get("source_rank") or 0)
        count = max(1, int(candidate.get("source_count") or 1))
        popularity = 22.0 * (1.0 - rank / count)
        if candidate.get("is_popular"):
            popularity += 4.0

    person_score = min(24.0, sum(8.0 if p.get("tier") == 1 else 4.0 for p in person_hits))
    transcript_bonus = 4.0 if candidate.get("transcript") is True else 0.0
    total = popularity + recency + topic_score + person_score + authority + transcript_bonus
    reasons = []
    if person_hits:
        reasons.append("people: " + ", ".join(p["name"] for p in person_hits[:4]))
    if topics:
        reasons.append("topics: " + ", ".join(topics[:5]))
    if candidate["source"] == "youtube" and candidate.get("views"):
        reasons.append(f"{candidate['views']:,} views")
    if candidate.get("is_popular"):
        reasons.append("PodcastTranscript popular")
    candidate["score"] = round(total, 2)
    candidate["reasons"] = reasons
    candidate["people"] = [p["name"] for p in person_hits]
    candidate["topics"] = topics
    candidate["age_days"] = round(float(age), 1)
    return candidate


def _transcript_available(video_id: str) -> bool:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return False
    try:
        api = YouTubeTranscriptApi()
        list(api.fetch(video_id, languages=["en"]))
        return True
    except Exception:  # noqa: BLE001 - some videos disable captions
        return False


def _check_transcripts(candidates: list[dict], limit: int) -> None:
    checked = 0
    for candidate in candidates:
        if checked >= limit:
            break
        if candidate["source"] != "youtube" or candidate.get("transcript") is not None:
            continue
        video_id = candidate["source_ids"][0]
        print(f"checking transcript: {candidate['title'][:70]}", file=sys.stderr)
        candidate["transcript"] = _transcript_available(video_id)
        checked += 1


def _merge_duplicates(candidates: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for candidate in candidates:
        key = _normalise_title(candidate.get("title") or "")
        if not key:
            continue
        if key not in seen:
            seen[key] = candidate
            continue
        existing = seen[key]
        merged_ids = list(dict.fromkeys(existing["source_ids"] + candidate["source_ids"]))
        existing["source_ids"] = merged_ids
        existing["transcript"] = bool(existing.get("transcript") or candidate.get("transcript"))
        if candidate.get("score", 0) > existing.get("score", 0):
            candidate["source_ids"] = merged_ids
            seen[key] = candidate
    return list(seen.values())


def _public_candidate(candidate: dict) -> dict:
    keys = [
        "source", "source_ids", "title", "channel", "url", "published_at",
        "duration_seconds", "views", "transcript", "score", "reasons",
        "people", "topics", "age_days", "description",
    ]
    return {key: candidate.get(key) for key in keys}


def list_candidates(args) -> int:
    now = datetime.now(timezone.utc)
    sources = _load_json(Path(args.sources_config), {})
    people = _load_json(Path(args.people_config), {}).get("people", [])
    used_records = load_used(Path(args.used_file))
    used = used_source_ids(used_records)
    used_titles = [_normalise_title(str(r.get("title") or "")) for r in used_records]
    candidates: list[dict] = []

    if not args.skip_podcasttranscript:
        for category in ("business", "technology"):
            candidates.extend(_podcast_candidates(category, args.podcast_limit, now))
    if not args.skip_youtube:
        yt = _youtube_client(Path(args.token_file).expanduser())
        if yt is not None:
            candidates.extend(_youtube_candidates(yt, sources.get("channels", []), sources, now))

    candidates = [c for c in candidates if c.get("title") and c.get("source_ids")]
    if not args.include_used:
        candidates = [
            c for c in candidates
            if not (set(c["source_ids"]) & used)
            and not any(_similar_title(_normalise_title(c.get("title", "")), title) for title in used_titles if title)
        ]

    max_views = max((int(c.get("views") or 0) for c in candidates), default=0)
    candidates = [
        _score(c, max_views, people, now)
        for c in candidates
    ]
    candidates = _merge_duplicates(candidates)
    if not args.allow_off_topic:
        candidates = [c for c in candidates if c.get("topics") or c.get("people")]
    candidates.sort(
        key=lambda c: (float(c.get("score") or 0), int(c.get("views") or 0), c.get("published_at") or ""),
        reverse=True,
    )

    if not args.no_transcript_check:
        _check_transcripts(candidates, args.transcript_check_limit)
    if args.require_transcripts:
        candidates = [c for c in candidates if c.get("transcript") is True]

    result = [_public_candidate(c) for c in candidates[: args.limit]]
    for index, candidate in enumerate(result, start=1):
        candidate["rank"] = index
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
        print(f"wrote {out}: {len(result)} candidates")
    else:
        print(text)
    return 0


def transcript(args) -> int:
    if args.source == "podcasttranscript":
        item = fetch_one(args.id)
        text = json.dumps(item, indent=2, ensure_ascii=False)
    else:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            print("error: install youtube-transcript-api (`uv sync --extra trending`)", file=sys.stderr)
            return 1
        try:
            fetched = YouTubeTranscriptApi().fetch(args.id, languages=["en"])
            segments = [
                {"start": s.start, "duration": s.duration, "text": s.text}
                for s in fetched
            ]
        except Exception as exc:  # noqa: BLE001
            print(f"error: cannot fetch transcript for {args.id}: {exc}", file=sys.stderr)
            return 1
        text = json.dumps(
            {"source": "youtube", "id": args.id, "segments": segments},
            indent=2,
            ensure_ascii=False,
        )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="rank fresh podcast candidates")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--podcast-limit", type=int, default=20)
    p_list.add_argument("--sources-config", default=str(DEFAULT_SOURCES))
    p_list.add_argument("--people-config", default=str(DEFAULT_PEOPLE))
    p_list.add_argument("--used-file", default=str(DEFAULT_USED))
    p_list.add_argument("--token-file", default=str(DEFAULT_TOKEN))
    p_list.add_argument("--out")
    p_list.add_argument("--include-used", action="store_true")
    p_list.add_argument("--skip-youtube", action="store_true")
    p_list.add_argument("--skip-podcasttranscript", action="store_true")
    p_list.add_argument("--no-transcript-check", action="store_true")
    p_list.add_argument("--transcript-check-limit", type=int, default=10)
    p_list.add_argument(
        "--require-transcripts",
        action="store_true",
        help="drop candidates whose transcript could not be verified",
    )
    p_list.add_argument(
        "--allow-off-topic",
        action="store_true",
        help="keep candidates with no AI/tech/markets keyword or priority person",
    )

    p_get = sub.add_parser("transcript", help="save a full transcript for one source id")
    p_get.add_argument("--source", choices=["youtube", "podcasttranscript"], required=True)
    p_get.add_argument("--id", required=True)
    p_get.add_argument("--out")

    args = parser.parse_args(argv)
    if args.command == "list":
        return list_candidates(args)
    return transcript(args)


if __name__ == "__main__":
    raise SystemExit(main())
