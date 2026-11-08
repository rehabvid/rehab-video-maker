#!/usr/bin/env python3
"""Turn channel evidence into a short promotion strategy brief.

Run before any "generate videos" request.  It never publishes and never spends
YouTube quota unless ``--api`` is passed (one channels.list + one videos.list).

Evidence sources:

* ``state/marketing-ledger.json`` — WeChat posts and YouTube promos already made
* ``out/autopilot/*/youtube-*.json`` — upload receipts
* ``state/channel-metrics.json`` — follower snapshots (YouTube via API,
  WeChat via ``--wechat-followers``; WeChat has no public API)
* ``build/autopilot/daily-ledger.json`` — whether today's scan/pick are done

The brief separates **facts** from **recommendations** and states what evidence
would change the plan.  With too little data it says so instead of inventing a
pivot.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATE = ROOT / "state"
MARKETING = STATE / "marketing-ledger.json"
METRICS = STATE / "channel-metrics.json"
DAILY = STATE / "daily-ledger.json"
OUT = ROOT / "build" / "autopilot" / "strategy-brief"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "podcast-youtuber-agent"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        value = ts.replace("Z", "+00:00")
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _receipts(days: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = {"youtube_en": 0, "youtube_zh": 0, "wechat": 0, "shorts": 0}
    for path in (ROOT / "out" / "autopilot").glob("*/youtube-en.json"):
        stamp = _parse(_load(path, {}).get("uploaded_at", ""))
        if stamp and stamp >= cutoff:
            result["youtube_en"] += 1
    for path in (ROOT / "out" / "autopilot").glob("*/youtube-zh.json"):
        stamp = _parse(_load(path, {}).get("uploaded_at", ""))
        if stamp and stamp >= cutoff:
            result["youtube_zh"] += 1
    marketing = _load(MARKETING, {})
    for item in marketing.get("wechat", []):
        stamp = _parse(str(item.get("published_at") or ""))
        if stamp and stamp >= cutoff and item.get("status") == "published":
            result["wechat"] += 1
    for item in marketing.get("promotions", []):
        stamp = _parse(str(item.get("published_at") or ""))
        if stamp and stamp >= cutoff and "short" in str(item.get("format", "")):
            result["shorts"] += 1
    return result


def _snapshots() -> dict:
    data = _load(METRICS, {"snapshots": []})
    data.setdefault("snapshots", [])
    return data


def _record(platform: str, followers: int, plays: int | None = None) -> None:
    data = _snapshots()
    today = datetime.now(timezone.utc).date().isoformat()
    for item in reversed(data["snapshots"]):
        if item.get("platform") == platform and item.get("date") == today:
            item["followers"] = followers
            item["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if plays is not None:
                item["plays"] = plays
            break
    else:
        data["snapshots"].append({
            "platform": platform, "date": today, "followers": followers,
            "plays": plays, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    _save(METRICS, data)


def _delta(platform: str, days: int) -> tuple[int | None, int | None]:
    snaps = [s for s in _snapshots().get("snapshots", []) if s.get("platform") == platform]
    if not snaps:
        return None, None
    snaps.sort(key=lambda s: s.get("date", ""))
    latest = snaps[-1]
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    older = [s for s in snaps if s.get("date", "") <= cutoff.isoformat()]
    base = older[-1] if older else (snaps[0] if len(snaps) > 1 else None)
    if base is None:
        return None, int(latest.get("followers") or 0)
    return int(latest.get("followers") or 0) - int(base.get("followers") or 0), int(latest.get("followers") or 0)


def _yt_api() -> dict:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return {"error": "google api client not installed"}
    token = CONFIG / "token.json"
    if not token.exists():
        return {"error": "no OAuth token"}
    try:
        creds = Credentials.from_authorized_user_file(str(token))
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        me = yt.channels().list(part="statistics", mine=True).execute()["items"][0]
        stats = me["statistics"]
        return {
            "subscribers": int(stats.get("subscriberCount") or 0),
            "views": int(stats.get("viewCount") or 0),
            "videos": int(stats.get("videoCount") or 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def _daily_status() -> dict:
    data = _load(DAILY, {})
    days = data.get("days", {})
    if not days:
        return {"day": None, "tasks": {}}
    day = sorted(days)[-1]
    # Days also hold audit-only lists such as "episodes"; only task records
    # are dicts with a status.
    return {"day": day, "tasks": {
        k: v.get("status")
        for k, v in days[day].items()
        if isinstance(v, dict) and "status" in v
    }}


def build_brief(days: int = 7, use_api: bool = True,
                wechat_followers: int | None = None,
                wechat_plays: int | None = None) -> dict:
    if wechat_followers is not None:
        _record("wechat", wechat_followers, wechat_plays)
    yt = _yt_api() if use_api else {"error": "api disabled"}
    if "subscribers" in yt:
        _record("youtube", yt["subscribers"], yt.get("views"))

    yt_delta, yt_total = _delta("youtube", days)
    wx_delta, wx_total = _delta("wechat", days)
    counts = _receipts(days)
    daily = _daily_status()

    evidence = {
        "window_days": days,
        "youtube": {"followers": yt_total, "delta": yt_delta,
                    "uploads": counts["youtube_en"] + counts["youtube_zh"],
                    "long_en": counts["youtube_en"], "long_zh_on_yt": counts["youtube_zh"]},
        "wechat": {"followers": wx_total, "delta": wx_delta, "posts": counts["wechat"]},
        "shorts": counts["shorts"],
        "api": yt,
        "daily": daily,
    }

    # ---- recommendation rules (explicit, conservative) ----
    confidence = "low"
    mix = "balanced"
    if wx_delta is not None and yt_delta is not None:
        if wx_delta >= 3 and wx_delta >= 2 * max(yt_delta, 0):
            mix = "wechat_primary"
            confidence = "medium" if counts["wechat"] >= 4 else "low"
        elif yt_delta >= 3 and yt_delta >= 2 * max(wx_delta, 0):
            mix = "youtube_primary"
            confidence = "medium" if evidence["youtube"]["uploads"] >= 4 else "low"
    recommendations = []
    if mix == "wechat_primary":
        recommendations += [
            "Make Mandarin the primary product: 5 vertical WeChat clips/week (Mon-Fri, 19:30 CST).",
            "Keep YouTube at 1 English long/week + 3 repurposed shorts; do not chase daily there.",
            "Create 合集 (series) for AI资本开支 / 美联储与债市 / 播客拆解 to give a follow reason.",
        ]
    elif mix == "youtube_primary":
        recommendations += [
            "Keep YouTube as the primary surface: 1 long + 3 shorts/week.",
            "Use WeChat as a 2-3/week Mandarin mirror, not a daily obligation.",
        ]
    else:
        recommendations += [
            "Hold a balanced split: 1 long + 3 shorts on YouTube, 3 Mandarin posts on WeChat per week.",
            "Collect at least two follower snapshots per platform before changing cadence.",
        ]

    if counts["wechat"] and counts["wechat"] >= 2:
        recommendations.append(
            "Check whether WeChat posts are horizontal masters; if so, test 9:16 60-90s cuts before adding volume."
        )
    if confidence == "low":
        recommendations.append(
            "Evidence is thin (fewer than two weekly snapshots). Run one more week before a permanent pivot."
        )

    change_mind = [
        "Two consecutive weeks where the other platform grows >=2x faster.",
        "A format test (horizontal vs vertical) with >=8 posts per arm.",
        "YouTube retention below 30% at 30s on three consecutive longs.",
    ]

    brief = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evidence": evidence,
        "decision": {"mix": mix, "confidence": confidence},
        "recommendations": recommendations,
        "what_would_change_the_plan": change_mind,
        "preflight": {
            "daily_ready": daily,
            "required": "run daily_ready.py ensure before generating",
        },
    }
    return brief


def render_markdown(brief: dict) -> str:
    e = brief["evidence"]
    yt, wx = e["youtube"], e["wechat"]
    def fmt(value):
        return "n/a" if value is None else str(value)
    daily = brief["preflight"]["daily_ready"]
    if daily.get("day"):
        done = [k for k, v in daily["tasks"].items() if v == "done"]
        open_tasks = [k for k, v in daily["tasks"].items() if v != "done"]
        daily_line = (f"{daily['day']} — done: {', '.join(done) or 'none'}; "
                      f"open: {', '.join(open_tasks) or 'none'}")
    else:
        daily_line = "not recorded — run daily_ready.py ensure"
    lines = [
        "# Promotion strategy brief",
        "",
        f"Generated: {brief['generated_at']} · window {e['window_days']} days",
        "",
        "## Evidence",
        "",
        "| Platform | Followers | Change | Posts in window |",
        "|---|---|---|---|",
        f"| YouTube | {fmt(yt['followers'])} | {fmt(yt['delta'])} | {yt['uploads']} |",
        f"| WeChat 视频号 | {fmt(wx['followers'])} | {fmt(wx['delta'])} | {wx['posts']} |",
        f"| Shorts (YouTube) | — | — | {e['shorts']} |",
        "",
        f"Daily readiness: {daily_line}",
        "",
        "## Decision",
        "",
        f"**{brief['decision']['mix']}** (confidence: {brief['decision']['confidence']})",
        "",
        "## Recommendations",
        "",
    ]
    lines += [f"- {item}" for item in brief["recommendations"]]
    lines += ["", "## What would change the plan", ""]
    lines += [f"- {item}" for item in brief["what_would_change_the_plan"]]
    lines += [
        "",
        "## Before generating",
        "",
        "1. `python skills/podcast-youtuber-agent/scripts/daily_ready.py ensure`",
        "2. Re-read this brief and state the split in one sentence.",
        "3. Generate, then mark `long_en` / `long_zh` / `wechat` / `shorts` in the ledger.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--wechat-followers", type=int, default=None,
                        help="record a WeChat follower snapshot (there is no public API)")
    parser.add_argument("--wechat-plays", type=int, default=None)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    brief = build_brief(args.days, not args.no_api, args.wechat_followers, args.wechat_plays)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n")
    text = render_markdown(brief)
    out.with_suffix(".md").write_text(text + "\n")
    print(json.dumps(brief, ensure_ascii=False, indent=2) if args.json else text)
    print(f"\nwrote {out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
