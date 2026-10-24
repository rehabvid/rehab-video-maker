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

## Install

The CPU pipeline and the standalone skills share one Python environment.
ComfyUI is optional and lives in a separate environment.

### 1. Install `uv`

macOS with Homebrew:

```bash
brew install uv
```

Or use the standalone installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install the project dependencies

From the repository root:

```bash
uv sync
```

This creates `.venv/` and installs `edge-tts`, `Pillow`, `numpy`, `PyYAML` and
the package itself from `pyproject.toml` / `uv.lock`. The avatar skill uses the
same packages, so it needs no separate Python install.

The podcast-youtuber agent's optional uploader uses Google's client libraries:

```bash
uv sync --extra trending --extra youtube
```

Its personal-voice backend lives in a separate Python 3.11 environment because
Chatterbox pulls in PyTorch and torchaudio:

```bash
uv venv --python 3.11 .venv-voice
uv pip install --python .venv-voice/bin/python --upgrade pip
uv pip install --python .venv-voice/bin/python chatterbox-tts 'setuptools<81'
.venv-voice/bin/python \
  skills/podcast-youtuber-agent/scripts/chatterbox_worker.py --check
```

The first synthesis downloads the model weights. `--engine edge` remains a
no-clone fallback for testing the render pipeline.

Either activate the environment:

```bash
source .venv/bin/activate
```

or prefix commands with `uv run`:

```bash
uv run rehab-slideshow list
uv run python -c "import edge_tts, numpy, PIL, yaml; print('python deps ok')"
```

### 3. Install FFmpeg

macOS:

```bash
brew install ffmpeg

# The rehab slideshow burns ASS captions, so it also needs libass.
# Homebrew's regular ffmpeg 9.x bottle does not include it; ffmpeg-full does.
brew install ffmpeg-full
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
```

Add that `export PATH=...` line to `~/.zshrc` or `~/.bash_profile` so new
shells use the full build. `ffmpeg-full` is keg-only; do not `brew link` it
unless you intend to replace the regular `ffmpeg`.

Debian/Ubuntu:

```bash
sudo apt update
sudo apt install ffmpeg
```

Check the build:

```bash
ffmpeg -version
ffprobe -version
ffmpeg -filters | grep -E " (ass|overlay) "
```

The `ass` filter is what the rehab slideshow uses for burned captions. The
`podcast-avatar-commentary` skill deliberately does **not** require `libass` or
`drawtext`. It burns captions with Pillow-rendered overlays, so it only needs
`libx264`, AAC and the core `overlay` filter. It works with either FFmpeg
build; using `ffmpeg-full` for both is simplest.

### 4. Install a font

macOS already has Arial and Helvetica in `/System/Library/Fonts`. On Linux:

```bash
sudo apt install fonts-dejavu-core
```

The scripts search the common macOS, Liberation and DejaVu paths. The rehab
pipeline requires one of these fonts; the avatar skill falls back to Pillow's
default font if none are found.

### 5. Check network access for narration

`edge-tts` uses Microsoft's neural-voice endpoint and needs no API key, but it
does need outbound network access. If synthesis fails, check the connection and
re-run with `--force`; you can also drop your own MP3s into
`build/<slug>/audio/shot-XX.mp3`.

### 6. Optional: ComfyUI

ComfyUI is only needed for generated illustrations or an AI avatar. It is a
separate environment and model download (roughly 20 GB for the clinical backend,
about 16 GB for the EchoMimic avatar), and `tools/ComfyUI/` is gitignored.

- Clinical GPU backend: see [GPU (optional)](#gpu-optional) below.
- Avatar workflow: see
  `skills/podcast-avatar-commentary/workflows/README.md` for the tested Apple
  Silicon install, the EchoMimic node fixes, MPS flags, the character sheet and
  the API workflow.
- Avatar models: after installing ComfyUI, run
  `skills/podcast-avatar-commentary/workflows/download_models.sh tools/ComfyUI`.

The tested avatar render on an Apple M2 Pro / 32 GB is **768×432, 25 fps,
8 steps**, at about **38 s per sampling step**. A 1-second shot takes roughly
7 minutes wall including model load; a 2-second shot took about 25 minutes of
sampling and 31 minutes wall, with later steps slowing under memory pressure.
Prefer 1-second shots and close Chrome and other memory-heavy apps. Plan on
30–60 seconds of avatar per 15-minute episode and use b-roll, quote cards,
charts and screen recordings for the rest. Rendering 15 minutes of avatar
locally is not practical; use a rented GPU or a cloud avatar service for a
3–5 minute A-roll.

Do not install ComfyUI into the project `.venv`; use its own virtual
environment.

### Verify the setup

```bash
uv run rehab-slideshow list
uv run python -c "import edge_tts, numpy, PIL, yaml; print('python deps ok')"
ffmpeg -version
uv run python skills/podcast-avatar-commentary/scripts/shotlist.py --help
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

## Skills

`skills/` contains repeatable production procedures that use the same patterns
as the pipeline above (measured TTS, burned captions, review sheets):

- `rehab-narrated-slideshow/` — the clinical slideshow procedure implemented in
  this repository.
- `podcast-youtuber-agent/` — research, scoring and scripting for podcast
  commentary episodes, plus a personal-voice, b-roll-only 10–15 minute renderer
  and an OAuth 2.0 YouTube uploader.
- `podcast-avatar-commentary/` — a reusable AI presenter and a ~15-minute
  commentary video, including the MacBook M2 / 32 GB model comparison
  (EchoMimicV3 vs InfiniteTalk vs LivePortrait) and the ComfyUI character
  workflow.

The avatar skill is self-contained under `skills/podcast-avatar-commentary/`
and writes to `build/` and `out/`. Its private character packs live under
`characters/<name>/`; photos, canonical renders and voice references are
gitignored.

The podcast-youtuber agent writes a private voice profile to `voices/<name>/`
and reads OAuth credentials from `~/.config/podcast-youtuber-agent/` by default.
Both are gitignored. Its flow is:

```bash
# 1. Record 45-90s in your own voice, then analyse and register it.
uv run python skills/podcast-youtuber-agent/scripts/voice_sample.py \
  analyze voices/me/raw.wav
uv run python skills/podcast-youtuber-agent/scripts/voice_sample.py \
  prepare voices/me/raw.wav --out voices/me --consent self

# 2. Draft a b-roll slide list from the finished script.
uv run python skills/podcast-youtuber-agent/scripts/slides.py draft \
  --script build/ep01/script.txt --out build/ep01/slides.json \
  --visuals assets/ep01 --voice-profile voices/me

# 3. Validate, render and upload private.
uv run python skills/podcast-youtuber-agent/scripts/build.py \
  --slides build/ep01/slides.json --out out/ep01/final.mp4 \
  --voice-profile voices/me --engine chatterbox \
  --upload --metadata build/ep01/youtube.json --privacy private
```

Every run should start from the current popular lists, not a saved topic. The
ranked list merges PodcastTranscript.ai with curated AI, startup, technology and
markets YouTube channels, filters the used-episode ledger, and checks which
videos have transcripts:

```bash
uv run python skills/podcast-youtuber-agent/scripts/trending.py list \
  --limit 20 --transcript-check-limit 10 \
  --out build/ep01/candidates/ranked.json
```

Use `--skip-youtube` for a PodcastTranscript.ai-only shortlist. The ranking
weights are editable in `config/trending-sources.json` and
`config/priority-people.json`. For the selected episode, collect cited host and
guest briefs before scripting:

```bash
uv run python skills/podcast-youtuber-agent/scripts/people.py \
  --name "Host Name" --name "Guest Name" --out build/ep01/people.json
```

`state/used-episodes.json` is the cross-run ledger. Mark every source after a
successful upload; if a video combines episodes, repeat `--id`:

```bash
uv run python skills/podcast-youtuber-agent/scripts/fetch_popular.py mark \
  --id <source-id> --title "Episode title" \
  --video-id <youtube-video-id> --url https://youtu.be/<youtube-video-id>
```

The default commentary is 10–15 minutes, roughly one quarter of the source
audio. If a popular episode is under ~40 minutes, combine 2–3 current episodes
around one thesis rather than padding a short one.

`build.py` validates the deck, synthesises measured narration, assembles 1080p
H.264/AAC with burned captions, and stops before upload if the review fails.
The uploader defaults to private, sets YouTube's synthetic-media flag, supports
resumable uploads, thumbnails, captions, playlists and `--publish-at` scheduling.
See `skills/podcast-youtuber-agent/SKILL.md` for voice-recording guidance,
Chatterbox setup and the Google Cloud OAuth steps.

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

- Python 3.10+ and [`uv`](https://docs.astral.sh/uv/)
- FFmpeg and ffprobe with libx264 and AAC; `libass` for the rehab slideshow's
  burned ASS captions (macOS: `ffmpeg-full`)
- A TrueType font (Arial/Helvetica on macOS, DejaVu Sans on Linux)
- Network access for edge-tts (Microsoft neural voices, no key required)
- Optional: CUDA GPU + ComfyUI for the generated-figure backend
- Optional: Apple Silicon + ComfyUI for the avatar skill
- Optional: Python 3.11 voice environment + Chatterbox for personal-voice
  narration (Apple Silicon MPS or CPU)
- Optional: a Google Cloud project with YouTube Data API v3 enabled for uploads

See [Install](#install) for the commands and verification steps.

## Repository contents

Source, exercise metadata and storyboards are committed. `build/`, `out/` and
`tools/ComfyUI/` are ignored: the generated video is a release artefact, not
source, and the model checkout is too large for git.
