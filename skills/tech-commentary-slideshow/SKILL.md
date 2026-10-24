---
name: tech-commentary-slideshow
description: Turn slide-by-slide podcast commentary transcripts into deterministic technical slideshows. Plans which beats deserve a chart, diagram, SVG, XYFlow DAG or PetriNet; renders only those scenes through LinkZag.Show; leaves ordinary beats as captioned cards; assembles narration, captions and MP4. Use for AI, startup, markets and technology commentary where animation should earn its render cost.
---

# Tech Commentary Slideshow

This is the **preferred visual layer** for podcast commentary. It consumes the
content skill's slide-by-slide transcript and builds a technical slideshow with
charts, diagrams, SVG explainers, XYFlow DAGs and Petri nets.

Animation is optional per slide. The default is deliberately mixed:

| Slide | Output | Why |
| --- | --- | --- |
| plain claim, quote, title, end | one captioned card / still | animation adds nothing |
| chart | still PNG or short MP4 | reveal motion helps comparison |
| DAG / PetriNet / Mermaid | short MP4 | edge drawing explains process |
| timeline / SVG | still PNG | a static explainer is enough |

No avatar, no generated video model, no cloud renderer. LinkZag.Show produces
deterministic pixels locally; FFmpeg assembles the final video.

## Skill boundaries

1. **Content layer** — `podcast-content-agent` (or the shared content scripts in
   `../podcast-youtuber-agent/scripts`) selects a fresh episode, researches the
   people, and writes `slides.json` with one narration beat per slide.
2. **Optional AI video layer** — `podcast-avatar-commentary` for a talking
   presenter. It is heavier and should only be used when a face is essential.
3. **This skill** — the technical slideshow and final video. It is the default
   for AI, startup, stock-market and technology commentary.

The content layer owns truth and wording. This skill owns visual selection,
scene generation, rendering and assembly. Do not invent a chart series or a
process edge that is not supported by the transcript/source.

## Prerequisites

- Python environment: `uv sync --extra youtube`
- FFmpeg and ffprobe
- Node 22.22.2+, npm 10+
- LinkZag.Show installed at `modules/linkZagShow`:

```bash
cd modules/linkZagShow
npm install
npx playwright install chromium
cd ../..
```

Check the renderer once:

```bash
cd modules/linkZagShow
npm run render -- --scene demo-hook --out /tmp/linkzag-smoke.png
cd ../..
```

## Input contract

`slides.json` comes from the content skill. It is a normal
`format: "broll-slides"` deck:

```json
{
  "slug": "ai-capex",
  "title": "The AI Capex Story Nobody Is Pricing",
  "fps": 30,
  "shots": [
    {
      "id": "01",
      "kind": "title",
      "narration": "The number everyone quoted was not the one that mattered.",
      "on_screen": "The number everyone missed"
    },
    {
      "id": "02",
      "kind": "chart",
      "narration": "Revenue rose from twelve million to nineteen million while gross margin held near seventy percent.",
      "heading": "Revenue vs margin",
      "visual": {
        "type": "chart",
        "chart_type": "bar",
        "data": {
          "categories": ["2024", "2025"],
          "series": [{"name": "Revenue ($M)", "data": [12, 19]}]
        }
      }
    }
  ]
}
```

Optional `visual` fields:

```json
{
  "visual": {
    "type": "dag",
    "animated": true,
    "data": {
      "nodes": [
        {"id": "ingest", "label": "Ingest", "kind": "input"},
        {"id": "verify", "label": "Verify", "kind": "default"},
        {"id": "publish", "label": "Publish", "kind": "output"}
      ],
      "edges": [
        {"id": "e1", "source": "ingest", "target": "verify"},
        {"id": "e2", "source": "verify", "target": "publish"}
      ]
    }
  }
}
```

Supported `visual.type` values:

- `chart` — ECharts; requires `data`.
- `dag` — XYFlow directed acyclic graph; requires or derives nodes/edges.
- `petrinet` — XYFlow places/transitions; uses `●` places and `▢` transitions.
- `diagram` — Mermaid flowchart.
- `svg` — generated timeline/stack SVG.
- `markdown` — a technical text slide.
- `none` — keep the existing captioned card.
- `animated: false` forces a still even for a chart/DAG.

If a `kind: "chart"` slide has no `visual.data`, the planner deliberately
falls back to a text card. Do not fabricate numbers to satisfy the renderer.

## Workflow

### 1. Plan which slides deserve a visual

```bash
uv run python skills/tech-commentary-slideshow/scripts/plan_visuals.py \
  --slides build/ep01/slides.json \
  --timing build/ep01/timing.json \
  --out build/ep01/visual-plan.json
```

The planner scores each beat and selects at most
`config/visual-policy.json`'s `max_custom_visuals` (default **12**):

- explicit `visual` hints win;
- chart only when data exists;
- PetriNet for concurrency/state/retry language;
- DAG for pipelines, agents, loops and dependencies;
- Mermaid for framework/relationship explanations;
- SVG for timelines, 2×2s, funnels and before/after;
- everything else stays a normal card.

It also avoids animating short beats (`min_visual_duration`, default 7s).

### 2. Generate LinkZag scenes and assets

```bash
uv run python skills/tech-commentary-slideshow/scripts/make_scenes.py \
  --plan build/ep01/visual-plan.json \
  --module modules/linkZagShow \
  --out build/ep01/scenes.json
```

This writes YAML under
`modules/linkZagShow/content/scenes/generated/<slug>/` and assets under
`content/assets/generated/<slug>/`. They are transient build inputs; the
renderer removes them after a successful run unless `--keep-scenes` is passed.
No generated media belongs in git.

### 3. Render only the selected visuals

```bash
uv run python skills/tech-commentary-slideshow/scripts/render_scenes.py \
  --manifest build/ep01/scenes.json \
  --visuals build/ep01/visuals \
  --module modules/linkZagShow
```

- static scene → `shot-XX.png`
- animated scene → `shot-XX.mp4` at the measured narration duration
- ordinary cards → no new render; the shared assembler draws them

For iteration, reuse one renderer:

```bash
cd modules/linkZagShow
npm run dev:renderer -- --host 127.0.0.1 --port 5180 --strictPort
```

Then pass `--base-url http://127.0.0.1:5180` to `render_scenes.py` or
`build.py`.

### 4. Build the final video

```bash
uv run python skills/tech-commentary-slideshow/scripts/build.py \
  --slides build/ep01/slides.json \
  --out out/ep01/final.mp4 \
  --voice-profile voices/me \
  --engine chatterbox \
  --device mps
```

`build.py`:

1. runs `narrate.py` if `timing.json` is missing (shared content/voice layer);
2. plans and renders only the selected LinkZag visuals;
3. marks those timing shots as `kind: broll` with the rendered visual path;
4. runs the shared `assemble.py` for captions, loudness normalization, MP4 and
   `review.md`.

It generates `build/ep01/thumbnail.png` unless `--thumbnail` is supplied or
`--no-thumbnail` is used.

Optional upload:

```bash
uv run python skills/tech-commentary-slideshow/scripts/build.py \
  --slides build/ep01/slides.json \
  --out out/ep01/final.mp4 \
  --voice-profile voices/me \
  --upload --metadata build/ep01/youtube.json --privacy private
```

## LinkZag.Show mapping

| Plan type | LinkZag scene item | Motion |
| --- | --- | --- |
| chart | `echarts` | value animation or left-to-right reveal |
| dag | `xyflow` | nodes fade/scale, edges draw progressively |
| petrinet | `xyflow` | places/transitions appear in sequence |
| diagram | `mermaid` | deterministic draw reveal |
| svg | `image` + generated SVG | static |
| markdown | `markdown` | fade-up |
| none / quote / title / end | existing card renderer | existing caption/card motion |

LinkZag is deterministic: the same scene and time produce byte-identical PNGs
on the same machine. Use its `segment`/`video` only for the slides that need
motion. A static PNG is much cheaper and looks identical when nothing moves.

## Run visuals concurrently with narration

Narration and slide generation do not have to be sequential. The visual plan can
be built from word-count estimates while Chatterbox is still synthesising WAVs:

```bash
# Terminal 1: start narration in the background
nohup uv run python skills/podcast-youtuber-agent/scripts/narrate.py \
  --slides build/ep01/slides.json --out build/ep01 \
  --voice-profile voices/me --engine chatterbox > build/ep01/narrate.log 2>&1 &

# Terminal 2: build visuals from estimated durations
uv run python skills/tech-commentary-slideshow/scripts/plan_visuals.py \
  --slides build/ep01/slides.json --out build/ep01/visual-plan-pre.json
uv run python skills/tech-commentary-slideshow/scripts/make_scenes.py \
  --plan build/ep01/visual-plan-pre.json --out build/ep01/scenes-pre.json
uv run python skills/tech-commentary-slideshow/scripts/render_scenes.py \
  --manifest build/ep01/scenes-pre.json --visuals build/ep01/visuals-pre

# After narration finishes, assemble with the prebuilt visuals.
uv run python skills/tech-commentary-slideshow/scripts/build.py \
  --slides build/ep01/slides.json --out out/ep01/final.mp4 \
  --prebuilt-manifest build/ep01/scenes-pre.json \
  --prebuilt-visuals build/ep01/visuals-pre
```

The assembler trims a longer animation to the measured narration. If the
measured narration is **longer** than the pre-rendered animation, the assembler
would loop it, which can restart the reveal. `build.py` prints a warning; in
that case re-render only the affected scene with measured timing.

Static PNG visuals have no timing dependency at all. Animated scenes use the
estimated word-count duration as a safe upper bound; a fast voice usually makes
the measured duration shorter, so trimming is the common case.

## Efficiency rules

- Animate at most **8–12 slides** in a 15-minute video.
- Prefer a still for charts that only need to be read; animate if the change is
  the argument.
- Keep animated scenes at the measured narration duration; do not render a
  60-second animation for a 12-second beat.
- Reuse the LinkZag renderer with `--base-url` while iterating.
- Change one scene, then rerun `render_scenes.py`; do not rebuild the final MP4
  until the visual cut is settled.
- Use `--keep-scenes` only when debugging; generated scenes/assets are
  transient.
- The final assemble step is separate from visual rendering. Changes to
  narration/captions require a re-assemble; unchanged visuals do not need a
  re-render.

### Chart animation detail

LinkZag does **not** use ECharts' wall-clock animation engine. It sets
`animation:false`, scales the series values as a pure function of scene time,
and Playwright captures each frame. That makes the animation deterministic and
seekable. The catch is that ECharts may re-autoscale a value axis on every
snapshot, which looks like a shaking bar. `make_scenes.py` pins the value-axis
`min`/`max` from the final data, and LinkZag also preserves explicit axis bounds.
Keep those bounds when you edit a chart scene.

## Visual correctness

- Every chart value must come from the episode or a cited source.
- Every DAG edge must describe a real dependency or sequence.
- PetriNet transitions/places are a model, not a claim of implementation.
- Quotes keep exact wording, attribution and a source link.
- If the source is ambiguous, use a text card. A wrong diagram is worse than a
  plain slide.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `LinkZag.Show not found` | module path missing | clone/install `modules/linkZagShow` |
| `npm` not found | Node not installed | install Node 22.22.2+ |
| Playwright chromium missing | no browser | `npx playwright install chromium` |
| scene renders as a card, not a chart | no `visual.data` | add real data or accept the text card |
| DAG labels truncated | narration beats too long | put short node labels in `visual.data` |
| too many visuals | policy cap | lower `max_custom_visuals` or add `animated:false` |
| final video has old visuals | timing not refreshed | rerun `build.py`/`render_scenes.py` |
| LinkZag output in git | generated under module content | keep `content/scenes/generated` out of git; renderer cleans it |
| chart is misleading | fabricated or mismatched data | replace with source data or remove the visual |

## Related skills

- [`../podcast-content-agent/SKILL.md`](../podcast-content-agent/SKILL.md) —
  content selection, people research and slide-by-slide transcripts.
- [`../podcast-avatar-commentary/SKILL.md`](../podcast-avatar-commentary/SKILL.md)
  — optional talking-presenter pipeline; heavier, use sparingly.
- [`../podcast-youtuber-agent/SKILL.md`](../podcast-youtuber-agent/SKILL.md) —
  legacy end-to-end pipeline and shared TTS/assembly/upload scripts.
