#!/usr/bin/env python3
"""One-at-a-time autonomous channel cycle.

Select a fresh long-form investment/AI episode, generate English + Mandarin,
publish the Mandarin master to WeChat once, and leave/upload the English master
through the quota-aware YouTube pending queue. Selection is pinned to a
candidate file so autopilot cannot silently reuse a different episode.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AUTOPILOT = HERE / "autopilot.py"
PUBLISH = ROOT / "skills" / "podcast-marketing-agent" / "scripts" / "publish_next.py"
UPLOAD_PENDING = HERE / "upload_pending.py"
INVESTMENT = ROOT / "build" / "autopilot" / "investment.json"
USED = ROOT / "state" / "used-episodes.json"
RESERVATIONS = ROOT / "state" / "autopilot-reservations.json"
STOP = ROOT / "build" / "autopilot" / "STOP"
CANDIDATE = ROOT / "build" / "autopilot" / "auto-candidate.json"


def log(message: str) -> None:
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}", flush=True)


def _load(path: Path):
    return json.loads(path.read_text())


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:52] or "episode"


def _used_ids() -> set[str]:
    if not USED.exists():
        return set()
    used = _load(USED).get("used", [])
    return {str(x) for entry in used for x in (entry.get("source_ids") or [])}


def _reserved_ids() -> set[str]:
    if not RESERVATIONS.exists():
        return set()
    return {str(x.get("source_id")) for x in _load(RESERVATIONS).get("active", [])}


def _reserve(source_id: str, title: str) -> None:
    data = _load(RESERVATIONS) if RESERVATIONS.exists() else {"active": []}
    data.setdefault("active", []).append({
        "source_id": source_id, "title": title,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    RESERVATIONS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _release(source_id: str) -> None:
    if not RESERVATIONS.exists():
        return
    data = _load(RESERVATIONS)
    data["active"] = [x for x in data.get("active", []) if x.get("source_id") != source_id]
    RESERVATIONS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _refresh_candidates() -> None:
    age = time.time() - INVESTMENT.stat().st_mtime if INVESTMENT.exists() else 10**9
    if age > 6 * 3600:
        log("refreshing curated investment feeds")
        subprocess.run([
            sys.executable, str(ROOT / "skills" / "podcast-content-agent" / "scripts" / "investment_sources.py"),
            "list", "--per-feed", "3", "--out", str(INVESTMENT),
        ], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pick() -> dict | None:
    _refresh_candidates()
    if not INVESTMENT.exists():
        return None
    used = _used_ids()
    reserved = _reserved_ids()
    items = []
    for item in _load(INVESTMENT):
        ids = [str(x) for x in (item.get("source_ids") or []) if x]
        if not ids or set(ids) & used or set(ids) & reserved:
            continue
        try:
            duration = int(float(item.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0
        if duration < 40 * 60:
            continue
        title = str(item.get("title") or "")
        if not title:
            continue
        # Prefer recent, high-tier investment/markets conversations.
        tier = int(item.get("tier") or 9)
        score = (10 - min(tier, 9)) * 100 + duration / 60.0
        if any(k in title.lower() for k in ("ai", "market", "invest", "stock", "fed", "bond", "energy", "macro")):
            score += 50
        items.append((score, item))
    items.sort(key=lambda pair: pair[0], reverse=True)
    return items[0][1] if items else None


def _active_generation() -> bool:
    result = subprocess.run(["pgrep", "-fl", "autopilot.py|bilingual.py|narrate.py"], capture_output=True, text=True)
    lines = [line for line in result.stdout.splitlines() if "auto_cycle.py" not in line and "pgrep" not in line]
    return bool(lines)


def main() -> int:
    log("autonomous channel cycle starting")
    while not STOP.exists():
        if _active_generation():
            log("another generation is active; waiting")
            time.sleep(600)
            continue
        candidate = pick()
        if candidate is None:
            log("no fresh >=40 minute candidate; waiting for feeds")
            time.sleep(1800)
            continue
        source_id = str((candidate.get("source_ids") or [""])[0])
        title = str(candidate.get("title") or "")
        if not source_id:
            log("candidate has no source id; waiting")
            time.sleep(1800)
            continue
        CANDIDATE.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
        _reserve(source_id, title)
        slug = _slugify(title)
        log(f"selected {source_id}: {title}")
        code = subprocess.run([
            sys.executable, str(AUTOPILOT), "--episodes", "1",
            "--candidate-file", str(CANDIDATE),
            "--language", "both", "--generate-only",
        ], cwd=ROOT).returncode
        log(f"generation exit={code}")
        out = ROOT / "out" / "autopilot" / slug
        complete = (out / "final.zh.mp4").exists() and (out / "final.en.mp4").exists()
        if code == 0 and complete:
            # Do not auto-publish WeChat. The creator UI can double-submit a
            # single click, so the safe autonomous boundary is: generate, QA,
            # queue English, and leave a one-command Mandarin publish.
            if os.environ.get("AUTO_WECHAT") == "1":
                subprocess.run([sys.executable, str(PUBLISH), "--wechat", "--slug", slug], cwd=ROOT)
            else:
                log(f"Mandarin ready for explicit publish: {slug}")
            subprocess.run([sys.executable, str(PUBLISH), "--queue"], cwd=ROOT)
            subprocess.run([sys.executable, str(UPLOAD_PENDING), "--limit", "1"], cwd=ROOT)
            _release(source_id)
        else:
            log("generation did not produce both verified masters; marking source as failed")
            used = _load(USED) if USED.exists() else {"used": []}
            used.setdefault("used", []).append({
                "source_ids": [source_id], "title": title, "video_id": "failed",
                "url": "", "note": "autonomous generation failed verification; skipped",
            })
            USED.write_text(json.dumps(used, ensure_ascii=False, indent=2) + "\n")
            _release(source_id)
        time.sleep(900)
    log("STOP file detected; autonomous cycle exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
