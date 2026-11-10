# Agent instructions

## Before generating or publishing video

Read `skills/video-preflight/SKILL.md` and follow it. In short:

1. Converge the business day:
   `python skills/podcast-youtuber-agent/scripts/daily_ready.py ensure --budget-min 15`
2. Produce/read the strategy brief:
   `python skills/podcast-marketing-agent/scripts/strategy_brief.py --days 7`
3. State the readiness, the YouTube/WeChat split, and any evidence-based
   adjustment in one short paragraph **before** starting a render.
4. Mark `long_en`, `long_zh`, `wechat` and `shorts` in `state/daily-ledger.json`
   as they finish.

The readiness gate is idempotent and lock-protected. Missed days are caught up
once, not replayed. It never starts a long render by itself.

## Publishing split

- English long-form → YouTube, **private** unless the owner says otherwise.
- Mandarin is **composed natively** from the source podcast transcript, not
  translated from the English deck (`mandarin.py`, autopilot default). Avoid
  翻译体; use mainland conversational Chinese.
- Mandarin → WeChat 视频号 as a **9:16, 60–90s** clip (`publish_next.py --wechat`).
- Do not upload the Mandarin master to YouTube. `autopilot.py` never queues or
  uploads Mandarin there unless `--allow-mandarin-youtube` is passed explicitly.
- Keep the synthetic-media disclosure on both platforms.
- WeChat publishing requires the owner's approval; a draft/dry run is
  `publish_next.py --wechat --slug <episode> --dry-run`.

## Theme and layout

- Default background is the original **light ink/watercolour sketch** (Marina
  Bay, sketch style, light theme). Night engines remain available with
  `--engine photo|night|minimal` but are not the default.
- One theme everywhere: `LINKZAG_THEME` (default `light`) governs covers, story
  cards, LinkZag scenes and portrait cards. Do not auto-pick theme from image
  brightness.
- If ComfyUI is not running, start it first: `bash tools/gen/start_comfyui.sh`
  (idempotent; `autopilot.py` calls it automatically). Only if it cannot start,
  generate covers with `cover.py --engine ink` (CPU light ink/watercolour
  sketch). Never fall back to `--engine minimal`: that engine paints a *night*
  palette and the light card compositor turns a dark plate into grey haze.
  `qa_backgrounds.py` fails a light build whose cover plate is a night image.
- Add one quiet motif: `trading` (candles/yield curve), `venture` (valuation
  staircase), or `ai` (node lattice). No window-level detail; hundreds of small
  lights are noise.
- YouTube/landscape: 1920x1080. WeChat/portrait: **1080x1920 native**, never a
  letterboxed 16:9 frame.
- Portrait safe zone: keep text inside a centred 900x1400 box; avoid the top
  10-15% and bottom 18-20%. Headline 64-120px, supporting 32-48px, burned
  captions ~46px with `MarginV` above the bottom UI.
- Re-render charts for portrait at 1080x1920 with the dark theme; do not crop a
  16:9 chart.
- Protect readability: charts sit on their own near-opaque dark card, captions
  get a bottom band, and the photo stays visible only at the top and side edges
  (top/bottom gradient scrim, not a full dark panel).

## Host avatar

- Every video gets the LinkZag host at the **bottom-right**, above captions and
  the footer. Landscape: **1/3 of the video height**. Portrait: **1/3 of the
  video width**.
- Default engine is **VRM**: `tools/gen/apply_avatar.py` renders the rigged
  model `assets/avatar/me.vrm` and overlays it. If that file is absent, it
  falls back to `assets/avatar/host.vrm`, then `sample.vrm`.
- The VRM host is driven by the same syllable visemes as the SVG fallback
  (`tools/gen/visemes.py`, requires `pypinyin`) and blinks naturally: one every
  3–5s with jitter, ~0.18s closure, ~12% double blinks. The host is anchored
  (no vertical bob).
- Keep it above the footer (`margin_bottom ≈ 9%` of landscape height) and
  inside the portrait safe area (22% from the bottom).
- SVG fallback remains available: `AVATAR_ENGINE=svg` with
  `AVATAR_SVG=/Users/zhaoli/Downloads/lee.svg`.
- Disable the overlay with `AVATAR_SVG=0` if a variant must be host-free.
- See `docs/VRM_HOST.md` for the renderer, orientation, and viseme track.

## Voice and QA

- The reference transcript must match the reference WAV. For `voices/me` that
  is `voices/me/reference.txt`, not the generic `config/sample-passage.txt`.
- `qa_audio` normalizes spelled-out numbers against ASR digits; keep that
  behaviour when changing the gate.
- `_split_chunks` must preserve every sentence; long cues are split, never
  dropped.
- Mandarin is gated by `skills/podcast-youtuber-agent/scripts/mandarin_style.py`
  (spoken rhythm, 翻译腔 phrases, Taiwan word forms, single-character quotes).
  English coverage verbs must not compress into `看 + 大领域`: write
  `负责基础设施领域的投资` or `主要看基础设施赛道`, not `合伙人，看基础设施`;
  that pattern is a hard failure.
  Hard issues trigger one rewrite with the report as feedback; see
  `docs/MANDARIN_STYLE.md`.
- `pypinyin` is required for syllable visemes. Without it every Chinese vowel
  silently falls back to `aa` and the mouth stops tracking syllables.

## Tests

```bash
.venv/bin/python -m unittest tests.test_daily_ready -v
```
