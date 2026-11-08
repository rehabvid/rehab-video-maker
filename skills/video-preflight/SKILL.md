---
name: video-preflight
description: Use before any request like "generate videos", "make a commentary video", "render the next episode", or "publish today's clip". Checks the daily readiness ledger, catches up missed days once, runs the promotion strategy brief, and states the YouTube/WeChat plan before any render starts.
---

# Video preflight (readiness + strategy)

Run this **before** invoking `autopilot.py`, `bilingual.py`, `build.py`,
`publish_next.py`, or any other render/publish script. The machine is not always
on, so "the user asked for a video" is also the moment to converge the business
day.

## 1. Readiness gate (always)

```bash
python skills/podcast-youtuber-agent/scripts/daily_ready.py ensure --budget-min 15
```

Behaviour:

- Business day is **Asia/Shanghai, starting 06:00**; a 02:00 run counts as the previous day.
- Runs the cheap missed tasks (`scan`, `pick`) once; a three-day outage does **not** replay three scans.
- Marks older missed days as `skipped` with a note.
- Never auto-starts a long render. Expensive tasks are reported as advice.
- Reuses a lock, so a late cron tick and the user prompt cannot run the scan twice.
- Returns `READY`, `CATCH_UP`, `DEGRADED`, `BUSY`, or `STOPPED`.

If the result is `BUSY`, wait for the existing run; do not force.
If `DEGRADED`, continue only if the failure is a feed, not the ledger.
`STOPPED` means the owner set `build/autopilot/STOP` — stop and report.

Catch-up policy:

| Task | If missed |
|---|---|
| `scan` | run once on next wake; older days marked skipped |
| `pick` | recompute from the fresh scan |
| `long_en` / `long_zh` | build only if the pick is <48h old, otherwise re-pick or skip |
| `wechat` | publish only if the slot is <24h old |
| `shorts` | batch up to 3, publish spaced |
| `digest` | weekly; run if within 72h (Friday) |

## 2. Strategy brief (always)

```bash
python skills/podcast-marketing-agent/scripts/strategy_brief.py --days 7
```

Read `build/autopilot/strategy-brief.md`. It contains facts (followers,
change, posts in window), a decision (`wechat_primary`, `youtube_primary`,
`balanced`), a confidence level, and what would change the plan.

- If the user gave WeChat follower numbers, record them:
  `--wechat-followers 14 --wechat-plays 1200`.
- If confidence is `low`, do not present a pivot as a conclusion; present it as
  a one-week test.
- If evidence contradicts the current plan, say so in one sentence **before**
  generating, with the number that supports it.

## 3. State the plan (one short paragraph)

Before the first render, print:

1. Today's readiness (what was caught up, what is pending).
2. The split: how many YouTube longs/shorts and how many WeChat vertical clips.
3. Any suggested adjustment and the evidence for it, or "no change; evidence thin".

Example:

> Readiness: scan done, pick ready, WeChat pending. Split: 1 English long → YouTube (private), 3 Mandarin 9:16 clips → 视频号. Evidence: WeChat +14 vs YouTube +3 in 4 days, low confidence — testing 5 clips this week, no permanent pivot.

## 4. Generate, then record

After each stage:

```bash
python skills/podcast-youtuber-agent/scripts/daily_ready.py mark long_zh --status done --note "<slug>"
python skills/podcast-youtuber-agent/scripts/daily_ready.py mark long_en --status done --note "<slug>"
python skills/podcast-youtuber-agent/scripts/daily_ready.py mark wechat   --status done --note "<title>"
python skills/podcast-youtuber-agent/scripts/daily_ready.py mark shorts   --status done --note "3 clips"
```

`publish_next.py` records `wechat` automatically; `autopilot.py` records `pick`,
`long_zh` and `long_en`.

## 4b. Theme and portrait rules

- Light ink/watercolour sketch is the default everywhere (`LINKZAG_THEME=light`).
  Night engines remain available with `--engine photo|night|minimal`.
- Portrait WeChat clips are composed natively at 1080x1920; charts are
  re-rendered for portrait, and text stays inside a 900x1400 safe box.
- Do not letterbox the 16:9 master; do not use photo references with watermarks.

## 5. Publishing rules

- YouTube: English long-form is the library; upload **private** unless the owner
  says otherwise. Mandarin does not go to YouTube.
- WeChat 视频号: Mandarin 9:16 clip first; publishing needs `--publish` and the
  owner's approval. `publish_next.py` defaults to the vertical cut.
- Never publish the same asset to both platforms under the wrong language.
- Mandarin is written from scratch from the source transcript, not translated
  sentence-by-sentence. Keep it conversational mainland Chinese, not 翻译体.
- Mandarin is never queued or uploaded to YouTube by default; only English is.
  `--allow-mandarin-youtube` is an explicit opt-in.
- Keep the synthetic-media disclosure on.

## 6. What not to do

- Do not start a long render inside `ensure`.
- Do not backfill every missed day.
- Do not claim a strategy change on fewer than two weekly snapshots.
- Do not use third-party audio/video clips in shorts; clip your own commentary.
