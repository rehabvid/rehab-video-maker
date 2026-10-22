---
name: rehab-narrated-slideshow
description: Produce a narrated breast-cancer rehabilitation exercise video from storyboard frames. Uses static illustrations, synchronized narration, timed captions, and MP4 export. Intended for patient education, caregiver education, and clinician review.
---

# Rehab Narrated Slideshow

Create a clinically reviewed rehabilitation video from static illustrations,
synchronized voice narration, and captions. The core pipeline is deterministic
and runs on a CPU; an optional GPU backend improves the figure. Either way it
produces an MP4 plus a review sheet.

Primary goals: low compute cost, high clinical clarity, one consistent visual
style, easy clinician review, and easy localization.

Everything in this skill is implemented in this repository. Commands below are
run from the repository root.

```bash
uv sync
uv run rehab-slideshow list
uv run rehab-slideshow build --exercise wall-climb
```

---

## Repository layout

| Path | Purpose |
| --- | --- |
| `exercises/<id>.yaml` | Protocol-sourced exercise metadata (dose, phase, precautions) |
| `storyboards/<id>.json` | Authored frame-by-frame script and on-screen text |
| `rehab_slideshow/` | Pipeline: validation, illustration, TTS, captions, video, review |
| `build/<id>/` | Intermediate assets (keep these) |
| `out/<id>/` | Deliverables: `final.mp4`, `review.md` |

The pipeline reads metadata and storyboards from these paths. It does not
generate medical content: dose, phase, and precautions must already exist in
the YAML and be traceable to a source.

---

## 1. Exercise selection

Read `exercises/*.yaml`. Each file must contain:

| Field | Rule |
| --- | --- |
| `id` | lowercase hyphenated, matches the file name |
| `title`, `subtitle` | shown on every frame |
| `recovery_phase` | `weeks-<start>-<end>`, e.g. `weeks-2-6` |
| `phase_label` | human-readable phase badge, e.g. `Weeks 2-6 after surgery` |
| `target_area` | joint / movement trained |
| `affected_side` | `right` or `left` |
| `start_criteria` | when the patient may begin |
| `frequency` | e.g. `3 times a day` |
| `repetitions` | integer, the **lower** bound of the protocol range |
| `repetitions_max` | optional upper bound; narrated as "build up to" |
| `hold_seconds` | integer, or `null` for a dynamic movement |
| `hold_note` | required when `hold_seconds` is null |
| `precautions` | non-empty list |
| `stop_if` | non-empty list |
| `source` | `title`, `publisher`, `url` |
| `clinical_review` | `status` (`pending` / `approved`), `reviewer`, `reviewed_on` |

Validation is fail-closed: a missing source, precautions list, repetition count,
or hold duration stops the build. When a protocol gives a range, use the lower
bound in `repetitions` and state the upper bound in `repetitions_max`; never
pick a number that is not in the source.

Protocols differ (for example 5-10 repetitions in Canadian Cancer Society
material versus 2-4 in some Healthwise handouts). Record which protocol was
used in `source.note`; the treating team's prescription always overrides it.

```bash
uv run rehab-slideshow validate --exercise wall-climb
```

---

## 2. Storyboard

Author `storyboards/<id>.json`:

```json
{
  "exercise": "wall-climb",
  "phase": "weeks-2-6",
  "language": "en",
  "frames": [
    {
      "id": "01",
      "kind": "intro",
      "heading": "Before you begin",
      "pose": "intro",
      "narration": "Wall climbing helps you regain shoulder movement after breast surgery. Start around week two, once any drain or stitches have been removed.",
      "bullets": ["This exercise gently stretches the front of your shoulder."]
    }
  ]
}
```

Frame fields:

- `id` - `01`, `02`, ... in order, no gaps
- `kind` - `intro` | `action` | `hold` | `precaution` | `close`
- `heading` - short on-screen step title (required)
- `pose` - one of `intro`, `stance`, `hands`, `climb`, `high`, `hold`, `lower`, `close`
- `narration` - one cue per frame, patient-friendly, max 340 characters
- `bullets` - up to 3 lines, each max 96 characters (silent-viewing aid)
- `timer` - `true` on the hold frame to draw the hold countdown

Authoring rules:

- one visible action per frame; no frame may combine two movements
- narration describes what is on screen and states the repetition count and hold
  duration in words ("five times", "ten seconds")
- the last frames must include the stop rules; a `precaution` or `close` frame is
  mandatory
- one affected side is shown. Say in the starting-position narration that the
  patient should use the other arm if their surgery was on that side.

Automated checks (`uv run rehab-slideshow validate`):

- ids sequential, `pose` known, narration and heading present
- range of motion rises to exactly one peak and returns; no jump above 0.45 of
  the available reach between frames (`no sudden range-of-motion jumps`)
- repetition count and hold duration appear in the narration
- claim blocklist rejects "cures", "prevents lymphoedema", "guarantees",
  "pain-free", "will heal", "proven to", and similar
- no more than 3 bullets, no over-long bullets

---

## 3. Illustration

Two backends produce the same layout, text, and clinical furniture. Pick one per
project; do not mix them inside a video.

### 3a. Generated figures (recommended when a GPU is available)

`tools/gen/` drives ComfyUI with SDXL, an OpenPose ControlNet and IPAdapter. The
room, text panel, badges and captions still come from the vector renderer, so the
layout stays identical to 3b; only the patient is generated.

Why this split: diffusion is good at drawing a believable person and bad at
keeping a room and a layout identical for nine frames. The vector scene supplies
the parts that must be exact.

```
storyboard pose ──► OpenPose skeleton ──► SDXL + ControlNet + IPAdapter
                                              │
                                     background key (flat studio bg)
                                              │
                              measure + normalise (head, feet, pelvis)
                                              │
                          composite into the 1280x720 vector room
                                              │
                                   build --person-dir
```

Setup (one-off, ~13 GB of models):

```bash
git clone https://github.com/comfyanonymous/ComfyUI tools/ComfyUI
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus \
  tools/ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus
uv venv --python 3.12 tools/ComfyUI/.venv
uv pip install --python tools/ComfyUI/.venv/bin/python \
  torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
uv pip install --python tools/ComfyUI/.venv/bin/python -r tools/ComfyUI/requirements.txt
```

Models go in `tools/ComfyUI/models/`:

| File | Source |
| --- | --- |
| `checkpoints/sd_xl_base_1.0.safetensors` | `stabilityai/stable-diffusion-xl-base-1.0` |
| `controlnet/xinsir-openpose-sdxl.safetensors` | `xinsir/controlnet-openpose-sdxl-1.0` |
| `ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors` | `h94/IP-Adapter` |
| `clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `h94/IP-Adapter` (`models/image_encoder`) |

Generate and build:

```bash
tools/ComfyUI/.venv/bin/python tools/ComfyUI/main.py --listen 127.0.0.1 --port 8188 &
.venv/bin/python tools/gen/gen_frames.py --exercise wall-climb   # skeletons -> SDXL -> cutouts
.venv/bin/python tools/gen/composite.py --exercise wall-climb    # normalise + place in the scene
uv run rehab-slideshow build --exercise wall-climb --person-dir build/wall-climb/persons
```

Rules that make this reproducible:

- **one seed, one prompt template, one IPAdapter reference** for every frame
- the skeleton comes from the same `pose` model as 3b, at a **fixed transform**
  (`K=3.0`, `TX=-1054`, `TY=-693`), so she is the same size in the camera
- the generation canvas is 896x1216 (portrait): the raised hand must stay inside
  the frame, otherwise the cutout loses the arm
- **cut out by background distance, not segmentation**: the studio background is
  a flat vertical gradient; a per-row median from the outer columns and a colour
  distance threshold of 26 is reliable. `rembg` occasionally drops a thin raised
  arm, which is exactly the limb that matters here.
- **measure every cutout** (head top, feet, pelvis) and rescale to 341 px with
  the feet on the floor: the model does not hold scale between frames
- use a unique filename per skeleton build: ComfyUI caches by filename and will
  silently reuse a stale pose if the name does not change

Limits: hands are the weak point. Check every frame at 100%; a pointing hand is
acceptable, fused fingers are not. ControlNet follows the skeleton approximately
- the arm can land 20-30 px lower than requested, so verify that the hand still
meets the wall and that frame-to-frame height increases.

### 3b. Vector renderer (CPU fallback)

`rehab_slideshow/illustrations.py` draws the flat scene directly: room, wall, one
patient in profile, clinical overlay. It is deterministic, needs no models, and
renders in about a second per frame at 2x (2560x1440).

Its weakness is the figure itself: it is built from parametric primitives, so
proportions and hands look diagrammatic. Use it when there is no GPU, for drafts,
or for the layout-only preview (`--frames-dir` with generated frames also works).

Frames carry: exercise name and subtitle, recovery-phase badge, affected-side
badge, step counter and progress dots, the step heading with up to 3 bullets, the
repetition / hold / frequency line, a comfort-range reminder, and the hold
countdown ring.

Keep all text inside a 40 px safe margin: the camera move crops the outer edge.

---

## 4. Narration

Voices (Microsoft neural, via `edge-tts`, no API key):

| Key | Voice |
| --- | --- |
| andrew | en-US-AndrewNeural (default) |
| steffan | en-US-SteffanNeural |
| thomas | en-GB-ThomasNeural |
| eric | en-US-EricNeural |

```bash
uv run rehab-slideshow build --exercise wall-climb --voice andrew
# custom pace: use the = form, because argparse treats a leading "-" as an option
uv run rehab-slideshow build --exercise wall-climb --rate=-12%
```

- one cue per frame, written in `storyboards/<id>.json`
- default rate `-8%`: slower than conversational, easier to follow while moving
- clips are cached by a hash of text + voice + rate; `--force-tts` re-synthesises
- measured durations in `build/<id>/narration/narration.json` are authoritative;
  never estimate durations

Narration rules: short sentences, patient-friendly language, no jargon, no health
claims, no instructions that are not visible on screen.

`edge-tts` needs network access. If it is unavailable, synthesise the cues with a
local engine and place the files as `build/<id>/narration/cue-XX.mp3` with a
matching `narration.json`; the rest of the pipeline is unchanged.

---

## 5. Captions

Two artefacts, generated from the same timeline:

- `build/<id>/captions.srt` - delivery, translation, accessibility
- `build/<id>/captions.ass` - burned into the video, exact style and position

Rules:

- exact narration text, never paraphrased
- maximum 2 lines, maximum 42 characters per line
- long cues are split at sentence and then word boundaries, and the cue duration
  is divided between chunks by character count
- captions sit in the lower band with a dark outline; the illustration keeps that
  band clear

Do not rely on a subtitle renderer's default font size: the ASS file pins
PlayRes 1280x720, DejaVu Sans 27, margin 30.

---

## 6. Timeline

Frame duration is derived from audio, never guessed:

```text
frame_duration = lead + audio_duration + tail
lead           = 0.9 s for the first frame, then 0.45 s
tail           = 0.75 s
```

The timeline is quantized to the 30 fps grid, so audio, video, and captions
cannot drift. Total runtime equals the sum of frame durations.

Camera moves are rendered in Python, not with FFmpeg `zoompan`:

- each output frame is a bicubic affine crop of the 2560x1440 master, so motion
  is sub-pixel smooth. `zoompan` rounds its crop origin to whole pixels and
  twitches every few frames at these speeds.
- zoom runs 1.00 -> 1.05 and back, with smoothstep easing, alternating in/out so
  the zoom level matches across a cut
- pan amplitude is clamped to `(zoom - 1) * width / 2`, otherwise the crop runs
  off the master and leaves a black edge
- the affine coefficient is `master_scale / zoom`; forgetting the 2x master scale
  produces a 2x zoom on every shot

Cross-fades (0.5 s) are blended in the same pass, so the video duration is exactly
the timeline duration.

Text is a separate layer. The scene (room + patient) cross-fades; the text and
badges for the outgoing frame stay crisp and swap at the midpoint of the fade.
Blending text along with the artwork produces two superimposed headings for half
a second, which is the most visible artefact in this kind of video.

## 7. Audio master

`build/<id>/master.wav`:

- 48 kHz, stereo, PCM
- every cue placed at its measured start time; no overlap between cues
- single peak normalisation to -3 dBFS, then a clipping check
- length checked against the video duration (tolerance 0.1 s); truncation fails
  the build

`ffprobe master.wav` must show 48 kHz, 2 channels, and the expected duration.

---

## 8. Export

`out/<id>/final.mp4`:

- H.264 (libx264, CRF 19, yuv420p), 1280x720, 30 fps
- AAC 160 kbps, 48 kHz, stereo
- captions burned in **and** embedded as a `mov_text` track
- fast start

The export is rejected if the muxed duration differs from the timeline by more
than 0.25 s.

---

## 9. Clinical review

`out/<id>/review.md` is generated on every build. It contains the exercise card,
precautions, source, timing table, and the checklist:

```text
[ ] Exercise name visible
[ ] Recovery phase stated
[ ] Affected side identified
[ ] Repetition count matches protocol
[ ] Hold duration matches protocol
[ ] Precautions included
[ ] Narration matches visuals
[ ] Frame order is correct
[ ] No unsupported medical claims
[ ] No unsafe movement progression
[ ] Narration fully timed
[ ] Export format
```

Reject and rebuild on: excessive range of motion, unsafe shoulder elevation,
contradictory instructions, pain-inducing positioning, incorrect sequencing, or
narration that is not visible on screen.

Generated figures (3a) need one extra human check that automation cannot do:
open every frame at 100%, confirm the affected arm is the one shown, that the
hand meets the wall, that the arm height increases in the intended order, and
that no hand or shoulder is malformed. Regenerate and re-review any frame that
fails.

Status semantics:

- **Blocked** - an automated check failed; the video must not be published
- **Ready for clinical review** - automated checks passed; a clinician has not
  signed off yet
- **Approved by `<name>` on `<date>`** - only when `clinical_review.status` is
  `approved` and a reviewer is named in the YAML

Automation cannot approve a clinical artefact. Never present a build as approved
just because the checklist passed.

---

## 10. Adding or translating an exercise

```bash
cp exercises/wall-climb.yaml exercises/<new-id>.yaml     # edit dose, phase, source
cp storyboards/wall-climb.json storyboards/<new-id>.json # rewrite narration
uv run rehab-slideshow validate --exercise <new-id>
uv run rehab-slideshow build --exercise <new-id>
```

For localization: keep the storyboard structure and pose sequence, translate
`heading`, `bullets`, and `narration`, set `language`, choose a matching voice,
and re-check caption line lengths (42 characters is tuned for English; other
languages may need a smaller font or shorter chunks).

---

## Deliverables

Keep intermediates in `build/<id>/`:

```text
storyboard.json  cues.txt  captions.srt  captions.ass
master.wav  video-track.mp4  frames/  narration/  exercise.yaml
```

Deliver only:

```text
out/<id>/final.mp4
out/<id>/review.md
```

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every shot is zoomed in 2x | affine coefficient omitted the 2x master scale | use `master_scale / zoom` |
| Black bar on an edge | pan exceeded the zoomed window | clamp pan to `(zoom - 1) * width / 2` |
| Generated arm is missing | hand left the generation canvas, or the cutout used a segmenter | widen the canvas to 896x1216 and cut by background distance |
| Figure changes size between frames | the model does not hold scale | measure head/feet/pelvis and normalise every cutout |
| Audio and captions drift | frame durations not quantized to fps | quantize before building the master |
| `voice synthesis produced no audio` | network blocked or voice name changed | check connectivity, `--force-tts`, rerun |
| Old narration plays after editing | cached by text hash | `--force-tts` |
| `no usable TrueType font found` | fonts missing | install `fonts-dejavu` |
| `unrecognized arguments: -8%` | argparse reads the leading dash as an option | use `--rate=-8%` |
| Caption text clipped at the edge | burned from SRT with default styling | use the generated ASS file |
| Build refuses to start | metadata or storyboard validation failed | read the listed errors; do not bypass |

---

## Design principles

- Static illustrations beat motion generation here: lower compute, deterministic
  output, easier clinical review, faster iteration, reusable assets.
- Narration timing is measured, never estimated.
- One source of truth per artefact: YAML for dose, storyboard for script, audio
  for timing, review sheet for release.
- Fail closed: missing clinical input stops the build rather than inventing a
  default.
- This pipeline is the foundation for higher-compute skills such as
  `rehab-motion-video`, `rehab-animated-avatar`, `rehab-text-to-video`, and
  `rehab-personalized-coach`; reuse the storyboard, narration, caption, and
  review components rather than re-implementing them.
