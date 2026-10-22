# Rehab narrated slideshow

Builds a narrated, captioned rehabilitation exercise video for patients after
breast cancer surgery: static illustrations, measured narration timing, burned-in
captions, and an MP4 that is safe to hand to a clinical reviewer.

The core pipeline runs on a CPU. An optional GPU backend replaces the
diagrammatic vector patient with a generated illustration (SDXL + OpenPose
ControlNet + IPAdapter); the layout, narration, timing and review steps are the
same either way.

```bash
uv sync
uv run rehab-slideshow list
uv run rehab-slideshow validate --exercise wall-climb
uv run rehab-slideshow build --exercise wall-climb
```

Output (not committed; see `.gitignore`):

```
out/wall-climb/final.mp4     # 1280x720, H.264 + AAC, burned + soft captions
out/wall-climb/review.md     # clinical review sheet and automated checks
build/wall-climb/            # storyboard, cues, frames, narration, master.wav
```

## What it does

1. **Validates** exercise metadata and the storyboard. Missing precautions, a
   missing source, or a repetition count that never appears in the script stops
   the build.
2. **Draws** one 1280x720 frame per storyboard step. The default backend is a
   deterministic vector renderer; the GPU backend generates the patient and
   composites her into the same room, text and badge layout.
3. **Narrates** each frame with edge-tts (`en-US-AndrewNeural` by default) and
   measures the real duration of every clip.
4. **Times** frames from the measured audio, snaps them to the 30 fps grid, and
   generates SRT and ASS captions that never exceed two lines of 42 characters.
5. **Assembles** a 48 kHz stereo master and a 30 fps video track: sub-pixel
   camera moves, 0.5 s cross-fades, and a text layer that swaps at the midpoint
   so headings never ghost.
6. **Reviews** the result against the clinical checklist and writes `review.md`.

## Layout

```
exercises/           protocol-sourced exercise metadata (YAML)
storyboards/         authored frame-by-frame scripts (JSON)
rehab_slideshow/     the pipeline (validation, render, TTS, video, review)
tools/gen/           GPU illustration backend (ComfyUI client + compositor)
tests/               clinical guards and timing math
skills/rehab-narrated-slideshow/SKILL.md   the procedure this repo implements
```

## Adding an exercise

1. Copy an existing file in `exercises/`, change the values, and cite the
   protocol you took them from.
2. Author `storyboards/<id>.json` with one narration cue per frame.
3. Run `uv run rehab-slideshow validate --exercise <id>`.
4. Run `uv run rehab-slideshow build --exercise <id>`.
5. Have a clinician review `out/<id>/review.md`, then set
   `clinical_review.status: approved` with the reviewer's name.

## Illustration backends

### CPU (default)

`rehab_slideshow/illustrations.py` draws the flat scene directly: room, wall,
one patient in profile, clinical overlay. Deterministic, no downloads, about a
second per frame. The figure is built from parametric primitives, so it reads as
a diagram rather than an illustration.

### GPU (optional)

`tools/gen/` drives ComfyUI with SDXL, an OpenPose ControlNet and IPAdapter. The
pose skeleton comes from the same parametric model, so the clinical posture is
unchanged; only the drawing is generated. The cutout is normalised (same height,
feet on the floor) and composited into the vector room.

Requires a CUDA GPU (tested on an RTX 3060 Ti, 8 GB) and about 20 GB of models
and tooling, installed under `tools/ComfyUI/` and gitignored:

```bash
git clone https://github.com/comfyanonymous/ComfyUI tools/ComfyUI
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus \
  tools/ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus
uv venv --python 3.12 tools/ComfyUI/.venv
uv pip install --python tools/ComfyUI/.venv/bin/python \
  torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
uv pip install --python tools/ComfyUI/.venv/bin/python -r tools/ComfyUI/requirements.txt
```

Then generate figures and build:

```bash
tools/ComfyUI/.venv/bin/python tools/ComfyUI/main.py --port 8188 &
.venv/bin/python tools/gen/gen_frames.py --exercise wall-climb
.venv/bin/python tools/gen/composite.py --exercise wall-climb
uv run rehab-slideshow build --exercise wall-climb \
  --person-dir build/wall-climb/persons
```

See `skills/rehab-narrated-slideshow/SKILL.md` section 3 for the model list,
the fixed pose transform, and the review rules.

### Pre-rendered frames from any other tool

```bash
uv run rehab-slideshow build --exercise wall-climb --frames-dir my-frames/
# expects frame-01.png, frame-02.png, ... at 1280x720 or larger
```

## Requirements

- Python 3.10+ managed by `uv`
- FFmpeg with libx264, AAC and libass
- A TrueType font (DejaVu Sans is the default)
- Network access for edge-tts (Microsoft neural voices, no key required)
- Optional: CUDA GPU + ComfyUI for the generated-figure backend

## Repository contents

Source, exercise metadata and storyboards are committed. `build/`, `out/` and
`tools/ComfyUI/` are ignored: the generated video is a release artefact, not
source, and the model checkout is too large for git.
