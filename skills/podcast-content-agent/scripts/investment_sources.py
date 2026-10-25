#!/usr/bin/env python3
"""Discover and transcribe investment podcasts from RSS feeds.

Apple Podcasts itself exposes transcripts in its apps, but there is no public
Apple transcript API. Apple's iTunes Search API can return the show's RSS
``feedUrl``; the RSS enclosure gives the audio, and local Whisper/MLX can
transcribe it.

This utility covers a curated set of investment/macro shows without depending
on a proprietary transcript provider:

    python scripts/investment_sources.py list --out build/investment.json
    python scripts/investment_sources.py transcript --audio-url URL --out text

The transcript command runs in the voice environment and uses
``mlx-audio``'s Whisper CLI. The first run downloads the ASR model.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE.parent / "config" / "investment-sources.json"
ITUNES = "https://itunes.apple.com/search"
DEFAULT_ASR_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _text(item: ET.Element, tag: str) -> str:
    found = item.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _episode(item: ET.Element, show: dict) -> dict:
    enclosure = item.find("enclosure")
    audio = enclosure.get("url") if enclosure is not None else ""
    link = _text(item, "link")
    if not link.startswith(("http://", "https://")) or "localhost" in link:
        link = audio
    duration = _text(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
    published = _text(item, "pubDate")
    return {
        "source": "rss",
        "source_ids": [f"rss:{urllib.parse.urlparse(show.get('feed', '')).netloc}:{_text(item, 'guid') or link}"],
        "title": _text(item, "title"),
        "channel": show.get("name") or "",
        "url": link,
        "audio_url": audio,
        "published_at": published,
        "duration": duration,
        "feed": show.get("feed", ""),
        "topics": show.get("topics", []),
        "tier": show.get("tier", 2),
        "transcript": "asr-required",
    }


def fetch_feed(show: dict, limit: int) -> list[dict]:
    url = show["feed"]
    req = urllib.request.Request(url, headers={"User-Agent": "podcast-youtuber-agent/1.0"})
    with urllib.request.urlopen(req, timeout=40) as response:
        raw = response.read()
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        return []
    return [_episode(item, show) for item in channel.findall("item")[:limit]]


def list_episodes(args) -> int:
    config = _load(Path(args.config))
    episodes = []
    failures = []
    for show in config.get("feeds", []):
        try:
            episodes.extend(fetch_feed(show, args.per_feed))
        except Exception as exc:  # noqa: BLE001 - one feed should not stop the rest
            failures.append(f"{show.get('name')}: {exc}")
    text = json.dumps(episodes, indent=2, ensure_ascii=False)
    out = Path(args.out) if args.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
        print(f"wrote {out}: {len(episodes)} episodes")
    else:
        print(text)
    for failure in failures:
        print(f"warning: {failure}", file=sys.stderr)
    return 0


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    print(f"downloading {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "podcast-youtuber-agent/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response, dest.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    return dest


def transcribe(args) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio = Path(args.audio_cache) if args.audio_cache else out.with_suffix(".mp3")
    if args.audio_url.startswith(("http://", "https://")):
        audio = _download(args.audio_url, audio)
    else:
        audio = Path(args.audio_url)
    model = args.model or DEFAULT_ASR_MODEL
    cmd = [
        args.voice_python,
        "-m", "mlx_audio.stt.generate",
        "--model", model,
        "--audio", str(audio),
        "--output-path", str(out.with_suffix("")),
        "--format", "txt",
        "--language", args.language,
    ]
    print("+ " + " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode:
        return result.returncode
    # mlx-audio appends .txt when --format txt is used.
    produced = out if out.exists() else out.with_suffix(".txt")
    if produced != out and produced.exists():
        produced.replace(out)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list latest investment episodes")
    p_list.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_list.add_argument("--per-feed", type=int, default=3)
    p_list.add_argument("--out")

    p_tr = sub.add_parser("transcript", help="download audio and run local ASR")
    p_tr.add_argument("--audio-url", required=True)
    p_tr.add_argument("--out", required=True)
    p_tr.add_argument("--model", default=DEFAULT_ASR_MODEL)
    p_tr.add_argument("--language", default="en")
    p_tr.add_argument("--voice-python", default=".venv-voice/bin/python")
    p_tr.add_argument("--audio-cache", help="download the enclosure here instead of next to the transcript")

    args = parser.parse_args(argv)
    if args.command == "list":
        return list_episodes(args)
    return transcribe(args)


if __name__ == "__main__":
    raise SystemExit(main())
