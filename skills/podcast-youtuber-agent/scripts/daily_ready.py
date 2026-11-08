#!/usr/bin/env python3
"""Daily readiness gate for the commentary channel.

The machine is not always on, so a cron job alone cannot guarantee the daily
work.  Every video skill calls ``ensure`` first: it converges the business day
(Asia/Shanghai, starting at 06:00) by running the cheap tasks that were missed
and reporting the expensive ones that still need a human or a long render.

Idempotent by design:

* one ledger per business day (``state/daily-ledger.json``)
* a file lock so a late cron tick and a user prompt cannot both run the scan
* a missed day is caught up **once**, not replayed for every missed day
* expensive work (long videos, WeChat posts) is reported, not silently started

Usage::

    python daily_ready.py status
    python daily_ready.py ensure --budget-min 15
    python daily_ready.py ensure --tasks scan,pick --json
    python daily_ready.py mark wechat --status done --note "债市定价的是放缓"
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATE = ROOT / "state"
LEDGER = STATE / "daily-ledger.json"
LOCK = STATE / "daily.lock"
STOP = ROOT / "build" / "autopilot" / "STOP"
AUTOPILOT = ROOT / "build" / "autopilot"
TZ = ZoneInfo("Asia/Shanghai")
DAY_START_HOUR = 6

CHEAP_TASKS = ("scan", "pick")
HEAVY_TASKS = ("long_en", "long_zh", "wechat", "shorts", "digest")
TASKS = CHEAP_TASKS + HEAVY_TASKS


def now() -> datetime:
    return datetime.now(TZ)


def business_day(moment: datetime | None = None) -> str:
    """Return the business date; a 02:00 run belongs to the previous day."""
    moment = moment or now()
    return (moment - timedelta(hours=DAY_START_HOUR)).date().isoformat()


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def load_ledger() -> dict:
    data = _load(LEDGER, {})
    data.setdefault("timezone", "Asia/Shanghai")
    data.setdefault("day_start_hour", DAY_START_HOUR)
    data.setdefault("days", {})
    data.setdefault("updated_at", "")
    return data


def save_ledger(data: dict) -> None:
    data["updated_at"] = now().isoformat(timespec="seconds")
    _save(LEDGER, data)


def day_record(data: dict, day: str) -> dict:
    record = data["days"].setdefault(day, {})
    for task in TASKS:
        record.setdefault(task, {"status": "pending"})
    return record


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _fresh(task: dict, max_age_hours: float | None) -> bool:
    if max_age_hours is None:
        return True
    stamp = task.get("at")
    if not stamp:
        return False
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    return (now() - at) < timedelta(hours=max_age_hours)


def _run(cmd: list[str], timeout: int = 600) -> int:
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    try:
        return subprocess.run(cmd, cwd=ROOT, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"timed out after {timeout}s", file=sys.stderr)
        return 124


def _scan() -> tuple[bool, dict]:
    """Metadata-only discovery scan. Never transcribes or renders."""
    day = business_day()
    detail: dict = {}
    ok = True
    out = AUTOPILOT / f"scan-{day}.json"
    code = _run([
        sys.executable,
        str(ROOT / "skills" / "podcast-content-agent" / "scripts" / "trending.py"),
        "list", "--skip-youtube", "--limit", "20", "--no-transcript-check",
        "--out", str(out),
    ])
    if code == 0 and out.exists():
        try:
            detail["trending"] = len(_load(out, []))
            detail["trending_out"] = str(out.relative_to(ROOT))
        except Exception:  # noqa: BLE001
            detail["trending"] = 0
    else:
        ok = False
        detail["trending_error"] = code

    rss = AUTOPILOT / f"scan-rss-{day}.json"
    code = _run([
        sys.executable,
        str(ROOT / "skills" / "podcast-content-agent" / "scripts" / "investment_sources.py"),
        "list", "--per-feed", "10", "--out", str(rss),
    ], timeout=900)
    if code == 0 and rss.exists():
        try:
            detail["rss"] = len(_load(rss, []))
            detail["rss_out"] = str(rss.relative_to(ROOT))
        except Exception:  # noqa: BLE001
            detail["rss"] = 0
    else:
        ok = False
        detail["rss_error"] = code
    return ok, detail


def _pick() -> tuple[bool, dict]:
    """Choose the next episode without building it."""
    sys.path.insert(0, str(HERE))
    try:
        import autopilot  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"cannot import autopilot: {exc}"}
    candidate = None
    errors = []
    for selector in (autopilot.select_candidate, autopilot.select_investment_candidate):
        try:
            candidate = selector()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{selector.__name__}: {exc}")
            candidate = None
        if candidate:
            break
    if not candidate:
        return False, {"errors": errors or ["no candidate"]}
    day = business_day()
    out = AUTOPILOT / "picks" / f"{day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
    age = candidate.get("published_at") or candidate.get("age_hours")
    return True, {
        "title": str(candidate.get("title") or "")[:120],
        "source_ids": candidate.get("source_ids") or [],
        "duration": candidate.get("duration"),
        "published_at": age,
        "file": str(out.relative_to(ROOT)),
    }


def _skip_stale_days(data: dict, day: str) -> list[str]:
    """Mark pending tasks from earlier business days as skipped (caught up once)."""
    skipped = []
    for old_day, record in data["days"].items():
        if old_day >= day:
            continue
        for task in TASKS:
            entry = record.get(task) or {}
            if entry.get("status") in ("pending", "running", "failed"):
                entry["status"] = "skipped"
                entry["at"] = now().isoformat(timespec="seconds")
                entry["note"] = f"missed business day; caught up once on {day}"
                record[task] = entry
                skipped.append(f"{old_day}:{task}")
    return skipped


def _heavy_advice(record: dict, day: str) -> list[dict]:
    """Report heavy tasks that are still worth doing, with freshness limits."""
    advice = []
    pick = record.get("pick") or {}
    if pick.get("status") == "done":
        if _fresh(pick, 48):
            advice.append({"task": "long", "why": "pick is <48h old; safe to build"})
        else:
            advice.append({"task": "long", "why": "pick is >48h old; skip or re-pick"})
    if (record.get("wechat") or {}).get("status") in ("pending", "failed"):
        advice.append({"task": "wechat", "why": "no post yet for this business day"})
    if (record.get("shorts") or {}).get("status") == "pending":
        advice.append({"task": "shorts", "why": "short slots not filled"})
    return advice


def ensure(tasks: list[str], budget_min: float, force: bool = False) -> dict:
    day = business_day()
    data = load_ledger()
    record = day_record(data, day)
    if STOP.exists():
        return {"status": "STOPPED", "day": day, "reason": f"stop file: {STOP}"}

    skipped = _skip_stale_days(data, day)
    started = time.monotonic()
    actions = []
    failed = []

    for task in tasks:
        if task not in TASKS:
            failed.append({"task": task, "error": "unknown task"})
            continue
        entry = record.get(task) or {"status": "pending"}
        if entry.get("status") == "done" and not force:
            continue
        if entry.get("status") == "running" and _pid_alive(int(entry.get("pid") or 0)):
            continue
        if time.monotonic() - started > budget_min * 60:
            actions.append({"task": task, "action": "deferred", "why": "budget exhausted"})
            continue
        entry.update({"status": "running", "pid": os.getpid(),
                      "started_at": now().isoformat(timespec="seconds")})
        record[task] = entry
        save_ledger(data)

        if task == "scan":
            ok, detail = _scan()
        elif task == "pick":
            ok, detail = _pick()
        else:
            actions.append({"task": task, "action": "manual",
                            "why": "heavy tasks are not auto-started by ensure"})
            entry["status"] = "pending"
            save_ledger(data)
            continue

        entry.update({
            "status": "done" if ok else "failed",
            "at": now().isoformat(timespec="seconds"),
            "pid": None,
            "detail": detail,
        })
        if not ok:
            entry["error"] = detail
            failed.append({"task": task, "error": detail})
        actions.append({"task": task, "action": "done" if ok else "failed"})
        save_ledger(data)

    data = load_ledger()
    record = day_record(data, day)
    save_ledger(data)
    pending = [t for t in TASKS if (record.get(t) or {}).get("status") not in ("done", "skipped")]
    status = "READY" if not pending else "CATCH_UP"
    if failed:
        status = "DEGRADED"
    return {
        "status": status,
        "day": day,
        "checked_at": now().isoformat(timespec="seconds"),
        "tasks": {t: (record.get(t) or {}).get("status", "pending") for t in TASKS},
        "actions": actions,
        "failed": failed,
        "pending": pending,
        "skipped_old_days": skipped,
        "heavy": _heavy_advice(record, day),
    }


def _bar(value: str) -> str:
    return {"done": "OK", "running": "RUN", "failed": "FAIL",
            "skipped": "SKIP", "pending": "--"}.get(value, value)


def status() -> dict:
    day = business_day()
    data = load_ledger()
    record = day_record(data, day)
    rows = []
    for task in TASKS:
        entry = record.get(task) or {}
        rows.append({
            "task": task,
            "status": entry.get("status", "pending"),
            "at": entry.get("at"),
            "note": entry.get("note"),
            "detail": entry.get("detail"),
        })
    return {"day": day, "timezone": "Asia/Shanghai",
            "day_start_hour": DAY_START_HOUR, "tasks": rows,
            "heavy": _heavy_advice(record, day)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="show today's readiness")
    p_status.add_argument("--json", action="store_true")

    p_ensure = sub.add_parser("ensure", help="run missed cheap tasks")
    p_ensure.add_argument("--tasks", default="scan,pick",
                          help="comma separated; default scan,pick")
    p_ensure.add_argument("--budget-min", type=float, default=15.0)
    p_ensure.add_argument("--force", action="store_true")
    p_ensure.add_argument("--json", action="store_true")

    p_mark = sub.add_parser("mark", help="record a task result")
    p_mark.add_argument("task", choices=TASKS)
    p_mark.add_argument("--status", required=True,
                        choices=["done", "failed", "skipped", "running", "pending"])
    p_mark.add_argument("--note", default="")
    p_mark.add_argument("--day", default=None)

    args = parser.parse_args(argv)

    if args.command == "status":
        report = status()
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        print(f"Business day {report['day']} ({report['timezone']}, starts {report['day_start_hour']:02d}:00)")
        for row in report["tasks"]:
            note = f" — {row['note']}" if row.get("note") else ""
            detail = ""
            if isinstance(row.get("detail"), dict) and row["detail"].get("title"):
                detail = f" ({row['detail']['title'][:60]})"
            print(f"  [{_bar(row['status']):4}] {row['task']:<8}{detail}{note}")
        for item in report["heavy"]:
            print(f"  advice: {item['task']} — {item['why']}")
        return 0

    if args.command == "mark":
        day = args.day or business_day()
        data = load_ledger()
        record = day_record(data, day)
        entry = record.get(args.task) or {}
        entry.update({"status": args.status, "at": now().isoformat(timespec="seconds")})
        if args.note:
            entry["note"] = args.note
        record[args.task] = entry
        save_ledger(data)
        print(f"{day} {args.task}: {args.status}")
        return 0

    if args.command == "ensure":
        with open(LOCK, "a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({"status": "BUSY", "day": business_day(),
                                  "reason": "another readiness check holds the lock"}))
                return 0
            tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
            report = ensure(tasks, args.budget_min, args.force)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(f"{report['status']} — business day {report['day']}")
                for task, state in report["tasks"].items():
                    print(f"  {task:<8} {state}")
                for action in report["actions"]:
                    print(f"  action: {action}")
                for item in report.get("failed", []):
                    print(f"  FAILED: {item}")
                for item in report.get("heavy", []):
                    print(f"  advice: {item['task']} — {item['why']}")
            return 0 if report["status"] in ("READY", "CATCH_UP", "BUSY") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
