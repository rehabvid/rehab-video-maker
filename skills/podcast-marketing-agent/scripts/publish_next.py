#!/usr/bin/env python3
"""Publish the next Mandarin master to WeChat and queue English YouTube uploads.

The WeChat step is deliberately one video per run. The English step only writes
pending manifests; YouTube's quota worker uploads them later.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WECHAT = ROOT / "skills" / "wechat-channels-agent" / "scripts"
PREPARE_COVER = WECHAT / "prepare_cover.py"
UPLOADER = WECHAT / "wechat_channels_upload.js"
LEDGER = ROOT / "state" / "marketing-ledger.json"


def _load(path: Path):
    return json.loads(path.read_text())


def _published_wechat() -> set[str]:
    if not LEDGER.exists():
        return set()
    data = _load(LEDGER)
    return {
        str(item.get("asset"))
        for item in data.get("wechat", [])
        if item.get("status") == "published"
    }


def _clean_title(value: str) -> str:
    # Prefer the first complete clause; long YouTube titles end in explanatory
    # tails such as "这是策略，不是错误" that make bad WeChat short titles.
    value = re.split(r"[，。！？：；,.:;!?|]", value or "", maxsplit=1)[0]
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value)
    if len(text) > 15:
        text = text[:15]
    if len(text) < 6:
        text = (text + "独立评论")[:15]
    return text


def _hashtags(metadata: dict) -> str:
    tags = [str(t) for t in (metadata.get("tags") or []) if t]
    picked = tags[:4] or ["播客评论", "独立评论"]
    return " ".join("#" + re.sub(r"[^\w\u4e00-\u9fff]", "", t) for t in picked if t)


def publish_wechat(only_slug: str | None = None) -> int:
    published = _published_wechat()
    ledger_data = _load(LEDGER) if LEDGER.exists() else {}
    published_titles = {
        str(item.get("title"))
        for item in ledger_data.get("wechat", [])
        if item.get("status") == "published" and item.get("title")
    }
    candidates = []
    for video in (ROOT / "out" / "autopilot").glob("*/final.zh.mp4"):
        slug = video.parent.name
        if only_slug and slug != only_slug:
            continue
        build = ROOT / "build" / "autopilot" / slug
        meta = build / "youtube.zh.json"
        cover = video.parent / "cover.zh.png"
        if not meta.exists() or not cover.exists():
            continue
        if str(video.relative_to(ROOT)) in published:
            continue
        candidates.append((video.stat().st_mtime, video, build, meta, cover))
    if not candidates:
        print("wechat: no unpublished Mandarin master")
        return 0
    candidates.sort(key=lambda item: item[0])
    _, video, build, meta_path, cover = candidates[0]
    slug = video.parent.name
    metadata = _load(meta_path)
    title = _clean_title(str(metadata.get("title") or slug))
    if title in published_titles:
        print(f"wechat: title already published, skipping: {title}")
        return 0
    description = " ".join(str(metadata.get("description") or "").split())
    description = description[:900].rstrip(" ,.;，。；") + " " + _hashtags(metadata)
    cover_out = ROOT / "build" / "marketing" / "wechat" / "linkZag" / "covers" / f"{slug}-final.png"
    cover_out.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run([sys.executable, str(PREPARE_COVER), "--cover", str(cover), "--out", str(cover_out)], cwd=ROOT).returncode:
        print(f"wechat: cover preparation failed for {slug}", file=sys.stderr)
        return 1
    manifest = ROOT / "build" / "marketing" / "wechat" / "linkZag" / f"manifest-{slug}-final.json"
    manifest.write_text(json.dumps({
        "account": "linkZag",
        "items": [{
            "video": str(video.relative_to(ROOT)),
            "cover": str(cover_out.relative_to(ROOT)),
            "title": title,
            "description": description,
        }],
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"wechat: publishing {slug} as {title}", flush=True)
    code = subprocess.run([
        "node", str(UPLOADER), "--manifest", str(manifest),
        "--publish", "--limit", "1",
    ], cwd=ROOT).returncode
    if code:
        print("wechat: publish failed; login may need a QR scan", file=sys.stderr)
        return code
    receipt = ROOT / "build" / "marketing" / "wechat" / "linkZag" / "upload-receipt.json"
    published_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        result = _load(receipt).get("results", [{}])[0]
        if result.get("status") == "published":
            published_at = str(_load(receipt).get("at") or published_at)
    except Exception:
        pass
    ledger = _load(LEDGER) if LEDGER.exists() else {"promotions": [], "wechat": []}
    ledger.setdefault("wechat", []).append({
        "account": "linkZag", "status": "published", "title": title,
        "platform_family": "wechat-channels", "published_at": published_at,
        "asset": str(video.relative_to(ROOT)),
        "cover": str(cover_out.relative_to(ROOT)),
        "manifest": str(manifest.relative_to(ROOT)),
    })
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
    print(f"wechat: published {title}", flush=True)
    return 0


def queue_english() -> int:
    queued = 0
    for video in sorted((ROOT / "out" / "autopilot").glob("*/final.en.mp4")):
        slug = video.parent.name
        build = ROOT / "build" / "autopilot" / slug
        meta = build / "youtube.json"
        captions = build / "captions.srt"
        pending = video.parent / "pending-upload.json"
        receipt = video.parent / "youtube-en.json"
        if pending.exists() or receipt.exists() or not meta.exists():
            continue
        cover = video.parent / "cover.en.png"
        if not cover.exists():
            cover = video.parent / "cover.zh.plate.png"
        if not cover.exists():
            cover = video.parent / "thumbnail.en.png"
        if not cover.exists():
            continue
        meta_data = _load(meta)
        pending.write_text(json.dumps({
            "video": str(video), "metadata": str(meta), "thumbnail": str(cover),
            "captions": [["en", str(captions), "English"]] if captions.exists() else [],
            "localizations": None, "source_id": "", "title": meta_data.get("title"),
            "language": "en", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2) + "\n")
        queued += 1
        print(f"youtube: queued {slug}", flush=True)
    print(f"youtube: queued {queued} new pending manifest(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wechat", action="store_true", help="publish one Mandarin master to WeChat")
    parser.add_argument("--queue", action="store_true", help="queue English YouTube uploads")
    parser.add_argument("--slug", help="restrict WeChat publishing to one episode slug")
    args = parser.parse_args()
    if not args.wechat and not args.queue:
        args.wechat = args.queue = True
    code = 0
    if args.wechat:
        code = publish_wechat(args.slug) or code
    if args.queue:
        code = queue_english() or code
    return code


if __name__ == "__main__":
    raise SystemExit(main())
