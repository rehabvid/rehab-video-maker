---
name: podcast-avatar-commentary
description: Build a reusable AI presenter from your photos, then produce a ~15-minute YouTube commentary video about a trending Business or Technology podcast. Covers the MacBook M2 32GB model choice (EchoMimicV3 vs InfiniteTalk vs LivePortrait), a one-time ComfyUI character pack, per-shot talking A-roll, b-roll and quote cards, measured TTS timing, captions, assembly, QA, and YouTube disclosure. Use when the user wants a talking-head podcast commentary channel, a reusable AI avatar of themselves, or a ComfyUI avatar workflow that fits Apple Silicon.
---

# Podcast Avatar Commentary

Turn a trending podcast into a ~15-minute YouTube commentary video with a
reusable AI presenter built from your own photos.

The output is not "an AI reads a summary." It is a produced commentary segment:
a short, specific argument, your own insight, a paced edit, and a presenter who
looks and sounds consistent from episode to episode.

## Target output

- One 1920x1080 (or 1280x720) MP4, 24–30 fps, H.264 + AAC 48 kHz stereo.
- 13.5–16.5 minutes, with a hook in the first 20 seconds and a real question at
  the end.
- 30–60 seconds of talking A-roll on a 32 GB Mac, plus 14–14.5 minutes of
  b-roll, quote cards, charts, screen recordings and title/end cards. On a
  rented GPU, 2–3 minutes of A-roll is a good stretch target. This ratio is
  deliberate; see [Why not 15 minutes of avatar](#why-not-15-minutes-of-avatar).
- Burned-in captions plus a sidecar SRT, a review sheet, a thumbnail brief, a
  description, chapters and the AI disclosure.
- A reusable `characters/<name>/` pack: photos, canonical portraits, prompts,
  seed, workflow and voice reference.

## Non-goals

- Do not clone a voice or face you do not have written permission to use.
- Do not impersonate a podcast host, guest, public figure or colleague.
- Do not present invented quotes, numbers or episode claims. Every factual
  claim must trace to the transcript, the episode page, or a cited public source.
- Do not re-upload a full podcast episode or a long excerpt. Commentary is the
  point; clips are short, credited and transformative.
- Do not publish a realistic AI avatar without disclosure. YouTube requires the
  altered/synthetic content label for realistic synthetic media.

---

## The stack decision for a MacBook M2 / 32 GB

The short version:

> **Use EchoMimicV3-Flash (1.3B) in ComfyUI for the talking A-roll, build the
> presenter once with SDXL + IPAdapter, and use LivePortrait only for a reusable
> idle loop. Use InfiniteTalk for a short hero shot on a rented GPU or cloud, not
> for a 15-minute local render.**

### Comparison

| Model | What it actually does | Input | Fit on M2 / 32 GB | Rough 15-min cost | Verdict |
| --- | --- | --- | --- | --- | --- |
| **EchoMimicV3 / V3-Flash** | Audio-driven half-body talking video with lip sync, expression and gestures; V3 non-Flash supports chunking, Flash renders one shot per job | one image + audio + prompt | **Good.** 1.3B, 8-step Flash, bf16; ComfyUI node exists; text encoder is fp8 and may need the fp16 fallback on MPS; do not use mmgp | **~100 h** for 15 min at 768×432 on M2 Pro (measured ~7 h per 1 min of 1 s shots); use 30–60 s of avatar | **Recommended local A-roll engine** |
| **InfiniteTalk** (Wan2.1 I2V 14B) | Audio-driven full/half-body dubbing, unlimited length, strong identity and lip sync | one image or video + audio | **Poor for long-form.** 14B; fp8 does not run on MPS without patches; bf16/GGUF is tight in 32 GB | ~20–40+ h at 480p (community reports ~10 min per 5 s) | **Best quality; hero shots only, or cloud** |
| **LongCat-Video-Avatar 1.5** | 2026 audio-driven long-form avatar, 8-step distilled, Whisper-Large lip sync | image/video + audio | **Poor.** 13B-class; not a laptop model | Days | **Best 2026 quality if you rent a GPU** |
| **LivePortrait** | Face reenactment / portrait animation from a **driving video** | photo + driving video | **Excellent.** Official Apple Silicon support, ~20× slower than an RTX 4090 | Fast, but not audio-driven | **Idle loop / reaction shots, not the main engine** |
| **MuseTalk / LatentSync** | Lip-sync only, applied to a base video | video + audio | **Mixed.** MuseTalk is light but CUDA-oriented; LatentSync 1.6 wants 18 GB VRAM | Fast-ish on CUDA; painful on Mac | **Only if you already have a base performance** |
| **Cloud avatar** (Hedra, HeyGen, Kling, Runway, Comfy Cloud) | Managed image/video-to-talking-avatar | photo/video + audio | N/A | Minutes | **Fastest path; good for hero shots and deadlines** |

### Why EchoMimicV3 is the local default

- It is **1.3B parameters**, not 14B. That is the difference between an overnight
  job and a multi-day job on a laptop GPU.
- It is **audio-driven** and **half-body**, so it gives you lips, expression,
  head motion and hand gestures from a single photo, not just a moving mouth.
- The **Flash** variant is distilled to **8 steps** and was designed for 12 GB
  VRAM at 768×768. A 32 GB M2 runs it in bf16 at 768×432 at about **38 s per
  step** (measured: 1.0 s / 25 frames, 8 steps, 6:52 wall including model load).
  The Flash path renders one shot up to `length`; keep each shot short rather
  than relying on the V3 chunked/partial-video path.
- It has a **ComfyUI node** and an example V3 workflow, so the character pack and
  the render graph can be reused without writing a new inference stack.
- The non-Flash **V3** path supports **long video** via partial chunks and
  overlap; the Flash path trades that for speed. Either way, the production
  model here is one narration shot per render, cut on sentence boundaries.

Its weaknesses are real: it is less photoreal than InfiniteTalk, hands can morph,
and long continuous renders drift. The workflow below is built around those
weaknesses: short shots, fixed seed, medium framing, hands at rest, and a hard
cut on sentence boundaries.

### Why not InfiniteTalk for the whole video

InfiniteTalk is the quality leader in the open-source, image+audio space. It
preserves identity, syncs lips, and moves the body naturally for long stretches.
But it is built on **Wan2.1-I2V-14B**, and an M2 is not an RTX 4090:

- fp8 weights crash on MPS; you need bf16/GGUF or the Apple Silicon patch sets.
- Even when it runs, community benchmarks put a 5-second 480p clip in the
  ~10-minute range on a 32 GB Mac. A 15-minute video is 180 such clips.
- The 14B model plus text encoder, VAE and audio encoder leaves little headroom
  in 32 GB of unified memory, especially with macOS and a browser open.

Use InfiniteTalk for a **20–40 second hero intro** on a rented GPU or Comfy
Cloud, then bring the MP4 back into the same edit. Use EchoMimic for the rest.

### Why not LivePortrait as the main engine

LivePortrait is a face **reenactment** model. It transfers expressions and head
pose from a driving video. It does not take text or audio and invent a
performance. If you use it for a script, you need either:

- a driving video of someone speaking those exact words (in which case you
  already have a performance), or
- a separate audio-driven lip-sync model such as MuseTalk or LatentSync.

That is a two-model pipeline with more moving parts and a weaker result than
EchoMimic for this use case. LivePortrait is still excellent for a reusable
**10–20 second idle/listening loop**, which the edit can use for reactions and
transitions.

### Why not 15 minutes of avatar

A 15-minute continuous talking head is:

- expensive to render,
- hard to keep identity-consistent,
- and boring to watch.

The stronger format is **30–60 seconds of A-roll** on a 32 GB Mac plus
**14–14.5 minutes of supporting visuals**: podcast cover, episode page, guest
photo, one chart, one quote card, one screen recording, one framework diagram,
and an end card. On a rented GPU you can stretch the A-roll to 2–3 minutes. The
avatar appears when you are making a point; the b-roll carries the evidence.
This is also how successful commentary channels actually edit.

---

## Prerequisites

- Python 3.10+ managed by `uv` (`.venv` in this repo already has Pillow, numpy
  and edge-tts).
- FFmpeg and ffprobe with libx264, AAC and the core `overlay` filter. `libass`
  and `drawtext` are **not** required; captions are rendered with Pillow.
- Network access for edge-tts (no key required).
- ComfyUI with the EchoMimicV3-Flash-Pro node and model files for Phase 3.
  The tested Apple Silicon install, the node fixes and the
  `workflows/download_models.sh` script are in
  [`workflows/README.md`](workflows/README.md#0-install-comfyui-on-apple-silicon).
  Phases 1, 2, 4 and 5 run without a GPU.
- About 10 GB free for build artefacts, plus roughly 16 GB for the avatar
  models if you render locally.

Run the commands from the repository root after activating the environment:

```bash
source .venv/bin/activate
# or use .venv/bin/python in place of python3 below
```

---

## Related skills

- [`../podcast-youtuber-agent/SKILL.md`](../podcast-youtuber-agent/SKILL.md) —
  episode selection, research, scoring and spoken-script structure. This skill
  reuses that loop and adds the production layer (shot list, avatar, assembly).
- [`../rehab-narrated-slideshow/SKILL.md`](../rehab-narrated-slideshow/SKILL.md)
  — the repository's first-version narrated slideshow pipeline: measured TTS,
  frame timing, burned plus soft captions, and a review sheet. This skill keeps
  the same conventions at 1920×1080, with a talking A-roll instead of one
  illustration per cue.

---

## Repository layout

This skill lives inside the `rehab-video-maker` repository, but it is
self-contained under `skills/podcast-avatar-commentary/`:

```text
skills/podcast-avatar-commentary/
  SKILL.md
  scripts/
    fetch_popular.py     # PodcastTranscript.ai candidate fetch
    shotlist.py          # draft / validate / plan the production
    tts.py               # edge-tts, measured timing, master.wav, captions
    comfy_client.py      # run a ComfyUI API workflow once per avatar shot
    assemble.py          # cards, segments, concat, captions, loudness, review
    lib.py               # shared timing, caption and card helpers
  workflows/
    README.md            # ComfyUI install, character sheet, EchoMimic, InfiniteTalk
    download_models.sh   # fetch the ~16 GB V3-Flash-Pro model set
    echomimic_v3_flash.api.json  # tested API graph for comfy_client.py
    echomimic_v3_flash_cfg1.api.json  # cfg=1.0 draft variant (about 2x faster)
characters/
  me/                    # your private character pack (photos gitignored)
build/
  ep01/                  # timing.json, audio/, avatar/, cards/, segments/
out/
  ep01/final.mp4
  ep01/review.md
```

`build/`, `out/`, and the private parts of `characters/` are gitignored. The
character pack is the one asset you cannot regenerate exactly; back it up.

---

## Phase 0 — build the presenter once

Do this once, carefully. Every episode after this reuses the same canonical
portrait, prompt, seed and voice.

### 0.1 Photos

Use 6–10 photos of the same person:

- front, 3/4 left, 3/4 right
- neutral expression, eyes open
- no sunglasses, no hat, no heavy filter
- even lighting, simple background
- at least 1024 px on the short side
- one person per photo

You need **written consent** from anyone whose face or voice you use. For your
own photos, record `consent: "self"` in `character.json`. For anyone else, keep
the signed release outside the repo.

### 0.2 Character sheet in ComfyUI

**Fast path:** if one photo is sharp, front-facing and evenly lit, crop it to
**16:9** and use it directly as `canonical/front.png`. This is enough to test
EchoMimic and to produce a first episode; it preserves the real background and
identity. The SDXL + IPAdapter sheet is for a cleaner, consistent set and
multiple poses, and it is optional for the first render.

Build the SDXL + IPAdapter graph described in
[`workflows/README.md`](workflows/README.md#1-character-sheet-one-time-reusable).
The short version:

- SDXL base + `IPAdapterUnifiedLoader` (`PLUS (high strength)`) +
  `IPAdapterAdvanced` (weight `0.75`, `concat`).
- 1344×768, 30 steps, cfg 7.0, `dpmpp_2m` / `karras`, fixed seed.
- Generate a small pose sheet: front, three-quarter, listening,
  making-a-point, thinking, smiling.
- Pick the best **front** and **three-quarter** as canonical.

Do not regenerate the face per episode. If you change hair, wardrobe or studio,
create a new version (`me-v2`) and keep `me-v1` for old videos.

### 0.3 Character pack

```text
characters/me/
  character.json
  photos/                 # private
  canonical/
    front.png
    three-quarter.png
    idle.mp4              # optional LivePortrait loop
  prompts/
    character.md
    scene.md
    negative.md
  echomimic.api.json      # API-format ComfyUI workflow
  voice.json
```

`character.json` should record the checkpoint, IPAdapter, seed, prompt,
canonical image hashes and consent. Treat it as a release manifest for the
character.

---

## Phase 1 — choose the episode and write the script

### 1.1 Fetch candidates

```bash
python3 skills/podcast-avatar-commentary/scripts/fetch_popular.py list \
  --category business --limit 10 --language English

python3 skills/podcast-avatar-commentary/scripts/fetch_popular.py list \
  --category technology --limit 10 --language English
```

### 1.2 Score and select

Score each candidate 1–10 on:

- relevance to current markets, AI systems, or the technology industry
- depth and uniqueness of ideas
- density: enough concrete frameworks, numbers or case studies for 15 minutes
- audience value for a busy professional

Prefer 25–60 minute episodes with multiple concrete claims. Avoid thin career
advice, basic tutorials, and episodes that are mostly promotion.

Select **one** episode when possible. Combine two only when they share a clear
thesis.

### 1.3 Research

```bash
python3 skills/podcast-avatar-commentary/scripts/fetch_popular.py get <id> \
  > build/ep01/source.json
```

Pull:

- the guest's background and current role
- verification of 2–3 key claims
- current context (markets, model releases, regulation)
- 3–5 non-obvious insights that go beyond the transcript summary
- one or two short, quotable lines with a timestamp and source URL

### 1.4 Write the spoken script

Write one continuous script of roughly 1,800–2,200 words (about 14–16 minutes at
150 wpm). No headings, no bullet points, no "first / second / third." Write for
the ear.

Flow:

1. A quiet, specific opening: a surprising number, a contradiction, or a
   personal stake. No "hey guys" and no "in today's video."
2. Who the guest is and why they matter now, woven into the story.
3. Three or four core ideas, each followed by your own research-backed insight,
   historical parallel, risk or practical implication.
4. A genuine question that the viewer will still be thinking about after the
   video stops.
5. A low-key close: comments, what they are testing, what to watch next.

Style: contractions, varied sentence length, occasional rhetorical questions,
short fragments. Sound like a smart friend who did the homework.

### 1.5 Turn the script into a shot list

The script stays continuous; the shot list is the production layer.

```bash
python3 skills/podcast-avatar-commentary/scripts/shotlist.py draft \
  --script build/ep01/script.txt \
  --out build/ep01/shots.json \
  --character me \
  --voice andrew \
  --fps 25
```

The draft splits the script at sentence boundaries into ~20–25 second avatar
beats (55 words by default, and never more than 340 characters). Now edit
`shots.json`:

- keep the **hook** and **your own insight** as `avatar`
- turn evidence into `quote`, `chart`, `broll` or `title`
- add `end` for the closing question
- give every `broll` a `visual` path
- give every `quote` an `attribution` and a `source`
- set `"fps": 25` if you are rendering EchoMimic at its native rate

Validate and plan:

```bash
python3 skills/podcast-avatar-commentary/scripts/shotlist.py validate build/ep01/shots.json
python3 skills/podcast-avatar-commentary/scripts/shotlist.py plan \
  build/ep01/shots.json --out build/ep01/plan.md
```

The validator warns when:

- runtime is outside 13.5–16.5 minutes
- avatar share is below 15% or above 65%
- there are four avatar shots in a row
- there are fewer than three non-avatar shots
- a quote has no source
- a shot is over the 340-character narration limit

Read `plan.md` before rendering. It includes a render-budget table.

---

## Phase 2 — voice and measured timing

```bash
python3 skills/podcast-avatar-commentary/scripts/tts.py \
  --shots build/ep01/shots.json \
  --out build/ep01 \
  --voice andrew \
  --rate=-6%
```

This produces:

- `build/ep01/audio/shot-XX.mp3` — one clip per shot
- `build/ep01/timing.json` — measured durations, start times, lead/tail
- `build/ep01/master.wav` — 48 kHz stereo, peak-normalised to -3 dBFS
- `build/ep01/captions.srt` and `captions.ass`
- `build/ep01/cues.txt`

Timing rules:

- never estimate durations; measure with ffprobe
- one narration cue per shot
- lead `0.6 s` on the first shot, `0.25 s` after that; tail `0.35 s`
- quantize every shot to the video frame grid
- if you change the script, re-run `tts.py`; the cache is keyed by text + voice +
  rate

Voice guidance:

- `edge-tts` is the default because it is free and needs no key. Use it for
  drafts and for a consistent, neutral presenter voice.
- For a personal brand, clone **your own** voice with consent (F5-TTS, XTTS-v2,
  Chatterbox or a licensed service). Keep the reference clip and settings in
  `voice.json`.
- Pace: `-5%` to `-8%`. Pause 0.3–0.6 s between beats. Pronounce numbers and
  names carefully; a mispronounced company name is an instant credibility leak.
- Do not clone a podcast host or guest. That is impersonation, even with a
  disclaimer.

---

## Phase 3 — render the avatar A-roll

### 3.1 Workflow

The tested API graph is
[`workflows/echomimic_v3_flash.api.json`](workflows/echomimic_v3_flash.api.json).
Point `comfy_client.py` at it directly, or copy it to
`characters/me/echomimic.api.json` if you want to customise the prompt,
resolution or sampler settings. The setup and model download steps are in
[`workflows/README.md`](workflows/README.md#0-install-comfyui-on-apple-silicon).

Dry-run first:

```bash
uv run python skills/podcast-avatar-commentary/scripts/comfy_client.py \
  --workflow skills/podcast-avatar-commentary/workflows/echomimic_v3_flash.api.json \
  --timing build/ep01/timing.json \
  --out build/ep01/avatar \
  --root . \
  --dry-run
```

Then render:

```bash
uv run python skills/podcast-avatar-commentary/scripts/comfy_client.py \
  --workflow skills/podcast-avatar-commentary/workflows/echomimic_v3_flash.api.json \
  --timing build/ep01/timing.json \
  --out build/ep01/avatar \
  --root . \
  --server http://127.0.0.1:8188 \
  --same-seed
```

The client:

- uploads the canonical image and the shot audio
- fills `{{IMAGE}}`, `{{AUDIO}}`, `{{PROMPT}}`, `{{NEGATIVE_PROMPT}}`,
  `{{SEED}}`, `{{LENGTH}}`, `{{PREFIX}}`
- queues one job per avatar shot
- polls ComfyUI, downloads the MP4, and writes a fingerprint
- skips unchanged shots on a re-run

The current `ComfyUI_EchoMimic` node has three separate nodes —
`Echo_LoadModel` → `Echo_Predata` → `Echo_Sampler` — plus
`VHS_VideoCombine`. Do not use the upstream example workflow unchanged; its
`Echo_LoadModel` widget order is stale.

**Long shots on 32 GB.** The Flash path renders the whole `length` in one job.
A 7-second / 177-frame job can wedge MPS on this machine; 49-frame chunks are
stable. Use `render_chunked.py` to split every avatar shot into ~1.96 s
(49-frame) chunks, render each with `comfy_client.py`, and stitch the result:
```bash
uv run python skills/podcast-avatar-commentary/scripts/render_chunked.py \
  --workflow characters/me/echomimic.api.json \
  --timing build/ep01/timing.json \
  --out build/ep01/avatar \
  --root . \
  --server http://127.0.0.1:8188 \
  --chunk-seconds 1.96
```
The chunk clips are video-only by the time `assemble.py` runs; `master.wav`
stays the audio source of truth. Expect a hard cut at each chunk boundary, so
keep the avatar share short and put the longer argument on b-roll.

### 3.2 Render settings that fit 32 GB

Start conservative, then raise quality after a successful benchmark:

| Setting | Start | Notes |
| --- | --- | --- |
| resolution | `768×432` | 16:9; the assembler scales to 1080p |
| steps | 8 | Flash-Pro is distilled for 8 |
| cfg | 3.5 | 3–6 |
| sample_rate | 16000 | Wav2Vec2 input rate |
| `lowvram` | true | harmless for Flash |
| `block_offload` | false | keeps inference on MPS |
| `use_mmgp` | None | CUDA-oriented |
| `teacache_offload` | false | Flash is already short |
| `partial_video_length` | 65 | unused by the Flash path |
| seed | one per character | identity stability |
| fps | 25 | EchoMimic native; keep the whole pipeline at 25 |

If ComfyUI is killed, set `block_offload` to `true` for one test, drop to
`640×360`, close the browser's GPU-heavy tabs, and keep 6–8 GB of unified memory
free for macOS.

### 3.3 Chunking rules

- one shot per narration beat, 20–40 seconds
- same canonical image, prompt and seed family for every shot
- hard cuts on sentence boundaries; crossfade only for idle loops
- if a shot fails, re-render only that shot
- never ask for a 15-minute continuous render; drift and one bad hand will cost
  you the whole job

### 3.4 QA every shot before assembly

Open each clip at 100% and check:

- same person as the canonical image
- lips match the consonants, no lag beyond ~80 ms
- five fingers, no fused or morphing hands
- eyes blink naturally, pupils stable
- no warping background, sliding chair or growing head
- no text/watermark artifacts on clothing
- camera framing stays inside the safe area

Reject and re-render any shot with identity drift, morphing hands or a warped
background. A 20-second re-render is cheaper than a comment section full of
"the hands are broken."

---

## Phase 4 — b-roll and graphics

For each non-avatar shot, provide a `visual`:

- `quote` — `quote`, `attribution`, `source`, optional background image
- `chart` — `heading`, `bullets`, optional background
- `broll` — an image or video path
- `title` — `on_screen`, `subtitle`, optional background
- `end` — `heading`, `question`, `next_text`

Recommended b-roll for a podcast commentary:

1. The podcast cover and episode page.
2. The guest's official headshot and role.
3. One chart or number that carries the argument.
4. One short quote card with attribution and a link.
5. One screen recording: the product, the paper, the market chart, the demo.
6. One framework/list card for your own insight.
7. An end card with a specific question.

Keep on-screen text short. The card renderer handles long text, but a viewer
reads 3–5 words, not a paragraph.

Third-party clips:

- keep them short (roughly 10–20 seconds)
- credit the show and link the episode
- make your commentary the reason the clip is there
- never re-upload a full episode or a long, unedited segment
- when in doubt, use the cover art and a quote card instead of audio/video

---

## Phase 5 — assemble

```bash
python3 skills/podcast-avatar-commentary/scripts/assemble.py \
  --timing build/ep01/timing.json \
  --out out/ep01/final.mp4
```

Optional music bed:

```bash
python3 skills/podcast-avatar-commentary/scripts/assemble.py \
  --timing build/ep01/timing.json \
  --out out/ep01/final.mp4 \
  --music assets/music/bed.mp3 \
  --music-volume 0.06
```

What it does:

- renders quote, chart, title and end cards at 2560×1440
- normalises every segment to 1920×1080 at the fps recorded in `timing.json`
- freezes the first/last frame of avatar clips to match the shot lead/tail
- renders caption overlays from the measured timing and burns them into each
  segment with FFmpeg's `overlay` filter (no `libass` or `drawtext` needed)
- concatenates, attaches `master.wav`, then stream-copies the captioned video
- mixes optional music, applies `loudnorm=I=-14:TP=-1.5:LRA=11`
- writes `build/ep01/review.md` with duration, shot table and checks

Deliverables:

```text
out/ep01/final.mp4
build/ep01/review.md
build/ep01/captions.srt
build/ep01/master.wav
```

The build is blocked if:

- a segment duration differs from the timeline by more than 0.15 s
- the final duration differs from the timeline by more than 0.25 s
- there is a black gap longer than 0.6 s
- the export is not 1920×1080 at the `fps` in `timing.json`, H.264 + AAC 48 kHz
  stereo
- an avatar clip is missing
- captions are missing

Fix the failed check; do not bypass it.

---

## Phase 6 — YouTube packaging

### Title

Specific, curiosity + stakes, under ~60 characters. Examples:

- "The AI Capex Story Nobody Is Pricing"
- "Why the Best AI Product Is Boring"
- "The Podcast Take That Made Me Change My Mind"

Avoid "in today's video," all-caps, and promises the video does not keep.

### Thumbnail

- your face (from the canonical shoot), left or right third
- 3–5 words of high-contrast text
- the podcast cover or a single striking number
- no fake charts, no fake quotes, no misleading before/after

### Description

Include:

- a 2–3 sentence summary
- the episode title, guest and link
- timestamps/chapters
- the sources you used
- the AI disclosure
- sponsor/affiliate disclosure if applicable
- a note that the commentary is opinion, not financial advice (when relevant)

Suggested disclosure:

```text
Disclosure: This video uses an AI-generated avatar of the creator. The script,
research and opinions are the creator's own. The original podcast is credited
and linked below; excerpts are used for commentary and criticism.
```

YouTube's altered/synthetic content disclosure is separate from the description.
Use it when the avatar is realistic enough to be mistaken for a real person.

### Chapters

```text
0:00 The number that surprised me
0:45 What the episode actually argues
3:10 The part everyone skipped
6:20 Where I think the guest is wrong
9:40 What this means if you are building
12:30 The question I cannot answer
14:50 What to watch next
```

### End screen

20 seconds: the question, a subscribe prompt, and one specific next video. Do
not end on a black frame.

---

## QA and release checklist

### Identity and performance

- [ ] The presenter is the same person in every avatar shot
- [ ] Lips match consonants; no persistent lag
- [ ] Hands are five-fingered and stable
- [ ] Eyes blink; no dead stare
- [ ] No warped background, sliding chair or growing head
- [ ] Framing leaves room for captions and lower-thirds

### Editorial

- [ ] The first 20 seconds contain a specific hook
- [ ] Every factual claim traces to the transcript or a cited source
- [ ] Quotes are exact and attributed
- [ ] Your own insight appears at least twice
- [ ] The ending asks a real question
- [ ] No fabricated guest position or invented number

### Audio

- [ ] Narration is intelligible at 1× and 1.5×
- [ ] No clipped samples; master peak ≈ -3 dBFS
- [ ] Final loudness ≈ -14 LUFS integrated, -1.5 dBTP
- [ ] Music bed does not mask consonants
- [ ] No long silences or abrupt cut-offs

### Captions

- [ ] SRT matches the narration exactly
- [ ] Burned captions are inside the safe area
- [ ] No line exceeds two lines of 42 characters
- [ ] Names and companies are spelled correctly

### Legal and platform

- [ ] AI avatar/voice disclosure in the video or description
- [ ] YouTube altered/synthetic content label set when appropriate
- [ ] Consent for every face and voice used
- [ ] Podcast clips are short, credited and transformative
- [ ] Music is licensed
- [ ] No impersonation, defamation or fabricated quote
- [ ] Sponsor/affiliate disclosure if applicable

### Export

- [ ] 1920×1080 (or 1280×720), 24–30 fps
- [ ] H.264, AAC 48 kHz stereo, fast start
- [ ] Duration matches the timeline within 0.25 s
- [ ] `review.md` status is "ready for upload"

**Reject and rebuild on:** identity drift, morphing hands, a different person
between cuts, lip-sync lag, a fabricated quote, an unlicensed clip, or a missing
AI disclosure.

---

## Render budget

Benchmark a **1-second** clip first; that is the stable production unit on this
machine. Time it from queue to downloaded MP4, then multiply:

```text
1 minute of avatar  = 60  × the 1-second wall time
15 minutes          = 900 × the 1-second wall time
```

| Render unit | Measured wall | 1 min avatar | 15 min avatar | Decision |
| --- | --- | --- | --- | --- |
| 1 s (25 frames) | 6:52 | ~7 h | ~103 h | 30–60 s avatar = 3.5–7 h; overnight run |
| 2 s (49 frames) | ~31 min | ~15.5 h | ~230 h | only for occasional holds; close apps |
| 3 s | ≥31 min | ≥10 h 20 | ≥155 h | avoid locally; use b-roll or cloud |

**Measured on this machine** (Apple M2 Pro, 32 GB, bf16 on MPS, 8 steps,
768×432, 25 fps):

- 1.0 s (25 frames): **38.4 s per step**, 5:06 sampling, 6:52 wall including
  model load and audio/text preprocessing.
- 2.0 s (49 frames): **24:28 sampling, about 31 min queue-to-file**. The first
  five steps held 99 s, then degraded to 173 / 231 / 255 s per step as memory
  pressure built. The output was clean, but this is not a reliable production
  unit on a 32 GB machine with a browser open.
- The macOS GPU watchdog can kill a command buffer at higher resolutions. Keep
  the Flash resolution at 768×432 or lower; a 768×768 or 1024×576 render hit
  `Impacting Interactivity` and stalled after step 4.

The hybrid format is the only practical local plan. A 30–60 second avatar share
in **1-second units** is about 3.5–7 hours, which fits an overnight run. A
3–5 minute avatar share belongs on a rented GPU or a cloud avatar service. Fill
the rest of the 15 minutes with b-roll, quote cards, charts and screen
recordings.

For a rough draft, use `workflows/echomimic_v3_flash_cfg1.api.json`
(`cfg: 1.0`; disables the audio-guidance branch) and/or `steps: 6`. Measured
`cfg: 1.0` at 1 s / 768×432: **19.4 s per step, 2:36 sampling, about 4 min
wall** — roughly half the default. The frame is clean, but mouth motion is
visibly weaker than the `cfg: 3.5` output, so use it only for timing and
storyboard drafts. The measured 8-step, `cfg: 3.5` numbers above are the safe
baseline for a final.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `MPSNDArrayMatrixMultiplication: unsupported input/output datatypes` | fp8 weights on MPS | use bf16/fp16, or the Apple Silicon fp8→bf16 patch set |
| ComfyUI killed, Mac swaps | unified memory exhausted | lower resolution to 640×360, set `block_offload=true` for one test, close apps |
| `Placeholder {{...}} has no value` | API workflow has a key the client did not fill | add it to the shot or edit the workflow |
| EchoMimic nodes missing after install | custom node import failed | check the startup log; see the setup fixes in `workflows/README.md` |
| `module 'mediapipe' has no attribute 'solutions'` | mediapipe 1.x removed the legacy API | `uv pip install "mediapipe==0.10.21"` |
| `No module named 'librosa'` / `'pyloudnorm'` | omitted from the node requirements | install both in the ComfyUI venv |
| `No module named 'torchcodec'` | torchaudio 2.11 `save` path | apply the `soundfile` patch in `workflows/README.md` |
| `'NoneType' object is not subscriptable` in `get_audio_embed` | transformers 5 removed Wav2Vec2 hidden states | apply the Wav2Vec2 hook patch in `workflows/README.md` |
| `Cannot convert a MPS Tensor to float64 dtype` | RoPE/timestep tables are float64 | cast them to float32; see `workflows/README.md` section 0.3 |
| `MPSNDArrayMatrixMultiplication ... different datatype` | bf16 weights with float32 latents; CUDA autocast is a no-op on MPS | cast latents/timestep to `weight_dtype`; see `workflows/README.md` section 0.3 |
| `Impacting Interactivity` / very slow steps | GPU watchdog; Flash path ignored `width`/`height` | apply the `(width, height)` patch; render 768×432 or lower |
| 7 s avatar job stalls at `0/8` with 0% CPU | Flash path wedged MPS on a long 177-frame job | kill ComfyUI, restart, and use `render_chunked.py --chunk-seconds 1.96` |
| `No module named '...echomimic_v3.src.dist'` | upstream `.gitignore` excluded `dist/` | copy `src/dist` from `antgroup/echomimic_v3` |
| `No module named 'decord'` | no macOS arm64 wheel; unused by Flash | use the guarded import in `workflows/README.md` |
| No avatar clips | `kind` is not `avatar` or the render was skipped | check `timing.json` and `build/ep01/avatar/` |
| Face changes between shots | different reference, prompt or seed | reuse the character pack; keep prompt/seed fixed |
| Hands morph | model limitation | medium shot, hands at rest, negative prompt, or crop hands |
| Background warps | busy background / long render | use a plain studio background; render per shot |
| Lip sync drifts | one long render | generate per shot; cut on sentence boundaries |
| EchoMimic outputs 25 fps, timeline says 30 | native rate | set `"fps": 25` in `shots.json` |
| Captions missing or clipped | font not found / safe area | install Arial/DejaVu; check `find_font` and `render_caption_overlay` in `lib.py` |
| `ffmpeg failed` on concat | mixed timebases | the assembler falls back to re-encoding; read the first error |
| Audio and video drift | durations estimated, not measured | re-run `tts.py`; use `timing.json` |
| `voice synthesis produced no audio` | network blocked or voice name changed | check connectivity, `--force`, rerun |

---

## Ethics and legal

- **Consent.** Use your own face and voice, or get written permission. Do not
  build an avatar of a public figure, a guest, a colleague or an ex-partner.
- **Disclosure.** Tell the audience the avatar is AI-generated. Use YouTube's
  altered/synthetic content label for realistic synthetic media. Put the
  disclosure in the description even when the label is not required.
- **No impersonation.** Do not make the avatar say things the real person did
  not say, and do not imply endorsement.
- **Copyright.** Podcast audio and video are third-party works. Use short,
  credited, transformative excerpts. Link the episode. Do not re-upload the
  episode or a long segment.
- **Quotes.** Exact words, attribution, timestamp, link. If you cannot verify a
  quote, paraphrase and say so.
- **Privacy.** Photos, voice references, canonical renders and character packs
  are personal data. Keep them out of git and back them up securely.
- **Advice.** Business/tech commentary is opinion. Add "not financial advice"
  when you discuss markets or trades.
- **Sponsorship.** Disclose paid placements and affiliate links.

---

## Appendix A — full command sequence

```bash
# 0. one-time: install ComfyUI, fix the EchoMimic node, download models
skills/podcast-avatar-commentary/workflows/download_models.sh tools/ComfyUI
# build the character sheet, then either use the shipped API graph or copy it
cp skills/podcast-avatar-commentary/workflows/echomimic_v3_flash.api.json \
  characters/me/echomimic.api.json

# 1. candidates and source
uv run python skills/podcast-avatar-commentary/scripts/fetch_popular.py list \
  --category technology --limit 10 --language English
uv run python skills/podcast-avatar-commentary/scripts/fetch_popular.py get <id> \
  > build/ep01/source.json

# 2. write build/ep01/script.txt, then draft the shot list
uv run python skills/podcast-avatar-commentary/scripts/shotlist.py draft \
  --script build/ep01/script.txt --out build/ep01/shots.json \
  --character me --voice andrew --fps 25

# 3. edit shots.json: avatar / broll / quote / chart / title / end
uv run python skills/podcast-avatar-commentary/scripts/shotlist.py validate build/ep01/shots.json
uv run python skills/podcast-avatar-commentary/scripts/shotlist.py plan \
  build/ep01/shots.json --out build/ep01/plan.md

# 4. voice, measured timing, master, captions
uv run python skills/podcast-avatar-commentary/scripts/tts.py \
  --shots build/ep01/shots.json --out build/ep01 --voice andrew --rate=-6%

# 5. avatar A-roll
uv run python skills/podcast-avatar-commentary/scripts/comfy_client.py \
  --workflow characters/me/echomimic.api.json \
  --timing build/ep01/timing.json --out build/ep01/avatar --root . --dry-run
uv run python skills/podcast-avatar-commentary/scripts/comfy_client.py \
  --workflow characters/me/echomimic.api.json \
  --timing build/ep01/timing.json --out build/ep01/avatar --root . --same-seed

# 6. assemble
uv run python skills/podcast-avatar-commentary/scripts/assemble.py \
  --timing build/ep01/timing.json --out out/ep01/final.mp4

# 7. review out/ep01/final.mp4 and build/ep01/review.md, then upload
```

---

## Appendix B — shot list schema

```json
{
  "slug": "ep01-ai-capex",
  "title": "The AI Capex Story Nobody Is Pricing",
  "character": "me",
  "voice": "andrew",
  "fps": 25,
  "shots": [
    {
      "id": "01",
      "kind": "avatar",
      "narration": "The number everyone quoted this week was not the one that mattered.",
      "on_screen": "The number everyone missed",
      "visual": "characters/me/canonical/front.png",
      "prompt": "A person sitting at a wooden desk in a warm home studio, speaking casually to the camera, natural hand gestures, medium shot, hands visible, soft window light, photorealistic.",
      "negative_prompt": "bad hands, extra fingers, fused fingers, distorted face, warped background, text, watermark",
      "seed": 43,
      "transition": "cut"
    },
    {
      "id": "02",
      "kind": "quote",
      "narration": "Here is the line that stuck with me.",
      "quote": "We are not short on demand. We are short on power.",
      "attribution": "Guest Name, Episode Title",
      "source": "https://example.com/episode",
      "visual": "assets/podcast-cover.jpg",
      "transition": "cut"
    },
    {
      "id": "03",
      "kind": "chart",
      "narration": "Look at what happened to the cost of the bottleneck.",
      "heading": "The bottleneck moved",
      "bullets": [
        "Demand is still accelerating.",
        "The constraint is now physical, not financial.",
        "The market is pricing the old constraint."
      ],
      "visual": "assets/chart.png",
      "transition": "cut"
    },
    {
      "id": "04",
      "kind": "broll",
      "narration": "This is the part the headline skipped.",
      "visual": "assets/screen-recording.mp4",
      "on_screen": "What the headline skipped",
      "transition": "cut"
    },
    {
      "id": "05",
      "kind": "end",
      "narration": "So here is the question I keep coming back to.",
      "heading": "What would change your mind?",
      "question": "If the bottleneck is physical, what does a rational capex cycle look like from here?",
      "next_text": "Tell me in the comments. Subscribe for the next breakdown.",
      "visual": "assets/podcast-cover.jpg",
      "transition": "cut"
    }
  ]
}
```

Field notes:

- `kind`: `avatar` | `broll` | `quote` | `chart` | `title` | `end`
- `narration`: the exact spoken text, max 340 characters per shot
- `on_screen`: optional lower-third or card headline
- `visual`: canonical image for avatar; image/video for broll; background for
  quote/chart/title/end
- `prompt` / `negative_prompt`: per-shot override; otherwise the client uses its
  defaults
- `seed`: optional; otherwise `--seed + shot index`
- `duration`: optional fixed hold; otherwise measured from the audio
- `fps`: set to `25` for EchoMimic, `30` for a 30 fps pipeline

---

## Appendix C — prompt templates

### Character sheet

Positive:

```text
A 35-year-old person with short dark hair, wearing a charcoal knit sweater,
sitting at a wooden desk in a warm home studio, medium shot, hands resting on
the desk, looking at the camera, soft window light from the left, shallow depth
of field, 35mm lens, natural skin texture, photorealistic, 16:9
```

Negative:

```text
cartoon, illustration, 3d render, plastic skin, extra fingers, deformed hands,
distorted face, text, watermark, logo, busy background, harsh flash,
oversaturated, low resolution
```

Pose variants: `front`, `three-quarter`, `listening`, `making-a-point`,
`thinking`, `smiling`.

### EchoMimic scene

Positive:

```text
A person sitting at a wooden desk in a warm home studio, speaking casually to
the camera, natural hand gestures, medium shot, hands visible, soft window light
from the left, shallow depth of field, photorealistic, calm and thoughtful
```

Negative:

```text
bad hands, extra fingers, fused fingers, distorted face, warped background,
text, watermark, cartoon, 3d render, fast jerky motion, exaggerated gestures,
duplicate person
```

### Thumbnail

```text
Close-up of the presenter, three-quarter view, warm studio light, high contrast,
clean dark background, space on the right for three words of bold text, sharp
eyes, natural skin texture, YouTube thumbnail, 16:9
```

Negative:

```text
text, logo, watermark, extra fingers, distorted face, plastic skin, busy
background, low contrast, blurry
```

---

## Appendix D — model and time reference

| Model | Params | Native resolution | Mac fit | Main risk |
| --- | --- | --- | --- | --- |
| EchoMimicV3-Flash | 1.3B | 768×768 | good in bf16 | hands, long-render drift |
| InfiniteTalk | 14B | 480p/720p | poor | memory, speed |
| LongCat-Video-Avatar 1.5 | 13B-class | 480p/720p | poor | memory, speed |
| LivePortrait | ~100M | 512×512 face | excellent | not audio-driven |
| MuseTalk | ~0.5B | 256×256 face | mixed | CUDA-oriented setup |
| LatentSync 1.6 | ~1B | 512×512 face | poor | 18 GB VRAM, CUDA |

Numbers are for planning, not promises. Benchmark your own machine; thermals,
macOS version, PyTorch version and background apps all change the result.

---

## Design principles

- **The character is an asset, not a prompt.** Build it once, freeze it, version
  it. Reusing a canonical portrait is what makes the channel feel like a channel.
- **The edit is the product.** A 15-minute talking head is a render problem; a
  4-minute A-roll plus b-roll is a video.
- **Measure, never estimate.** Audio duration drives the timeline; the timeline
  drives the render and the captions.
- **One source of truth per artefact.** `shots.json` for the plan,
  `timing.json` for time, `master.wav` for audio, `review.md` for release.
- **Fail closed.** A missing avatar clip, a quote without a source, or an export
  that does not match the timeline stops the build.
- **Disclose and credit.** The avatar is a production tool, not a licence to
  pretend. Consent, attribution and AI disclosure are part of the format.
