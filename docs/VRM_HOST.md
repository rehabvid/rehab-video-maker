# VRM talking host — setup and pipeline

The repo supports two host engines:

| Engine | Source | Look | Lip sync |
|---|---|---|---|
| `vrm` (default) | `assets/avatar/me.vrm` (fallback: `host.vrm`, then `sample.vrm`) | rigged 3D avatar | `aa/ih/ou/ee/oh` blendshapes from syllable visemes + natural blink |
| `svg` | `lee.svg` | flat 2D portrait | syllable visemes (`aa/ih/ou/ee/oh`) |

Both are composited **bottom-right**, above the footer. Landscape uses **1/3 of
the video height**; portrait uses **1/3 of the video width**. The engine is
anchored (no vertical bob) and keeps clear of captions.

## What was added

- `three` and `@pixiv/three-vrm` in `modules/linkZagShow`.
- `tools/vrm/avatar.html` — three.js scene, VRM loader, camera/pose setup.
- `tools/vrm/render_vrm.mjs` — headless Playwright renderer → alpha PNG frames → MOV.
- `tools/gen/apply_avatar.py --engine vrm` — renders the host and overlays it.
- `assets/avatar/me.vrm` — the owner’s current presenter and the default model.
- `assets/avatar/sample.vrm` — the older VRoid model kept as a fallback.

## 1. Get a VRM model

Use **VRoid Studio** (free) to build the host, then export **VRM 1.0**:

- cartoon / clean / professional
- oversized eyes, black rectangular glasses, swept-back hair
- light button shirt
- neutral expression, arms at rest

Save as:

```
assets/avatar/me.vrm
```

VRM 0.x also loads via three-vrm, but 1.0 is preferred.

## 2. Enable the VRM engine

VRM is the **default**. `apply_avatar.py` prefers `assets/avatar/me.vrm`; if it
is absent it uses `host.vrm`, then `sample.vrm`. To pin a model explicitly:

```bash
VRM_MODEL=assets/avatar/me.vrm \
  .venv/bin/python skills/tech-commentary-slideshow/scripts/build.py ...
```

The SVG fallback is opt-in:

```bash
AVATAR_ENGINE=svg AVATAR_SVG=/Users/zhaoli/Downloads/lee.svg \
  .venv/bin/python skills/tech-commentary-slideshow/scripts/build.py ...
```

Or export for the whole shell:

```bash
export AVATAR_ENGINE=vrm
export VRM_MODEL=assets/avatar/me.vrm
```

The build hooks in `build.py` and `bilingual.py` pick it up automatically.

## 3. How the render works

1. `apply_avatar.py` probes the video and sets the square avatar edge to
   `height / 3` for landscape, or `width / 3` for portrait. It stays above the
   footer/captions.
2. It builds a syllable viseme track from `slides.json` + `timing.json`
   (`tools/gen/visemes.py`, pypinyin) and passes it to the renderer.
3. `render_vrm.mjs` starts a local HTTP server (ES modules cannot load over `file://`).
4. Playwright opens `avatar.html`, loads the VRM with `VRMLoaderPlugin`.
5. Per frame at `--fps`:
   - the current syllable sets `aa/ih/ou/ee/oh`, eased over ~55 ms,
   - `blink` closes naturally: 3–5s apart, ~0.18s half-cosine closure,
     12% double blinks,
   - the host stays anchored; head yaw is a small optional sway,
   - screenshot with transparent background.
6. Frames → PNG-in-MOV (alpha) → ffmpeg `overlay` bottom-right.
## 4. Tuning

All in `tools/vrm/avatar.html`:

- **Facing**: VRM 1.0 faces **+Z** and needs no rotation. VRM 0.x is flipped
  with `VRMUtils.rotateVRM0(vrm)`. Do **not** hard-code `-Math.PI / 2`; it
  renders VRM 1.0 models in profile.
- **Arms**: `leftUpperArm.rotation.z = -1.15`, `rightUpperArm.rotation.z = 1.15`.
- **Framing**: camera `z = modelHeight * 0.62`, look at the head.
- **Expressions**: add `ih/ou/ee/oh` or `happy` via `expressionManager.setValue`.
- **Visemes**: `render_vrm.mjs --visemes track.json` accepts a per-frame list
  (`aa/ih/ou/ee/oh`, `null` for silence). `apply_avatar.py` builds it from
  pinyin; for phoneme-accurate timing, swap in Rhubarb or WhisperX alignment.

## 5. Verify

```bash
node tools/vrm/render_vrm.mjs \
  --vrm assets/avatar/me.vrm \
  --audio build/<episode>/master.wav \
  --out /tmp/host.mov --height 360 --fps 15
```

Then apply:

```bash
.venv/bin/python tools/gen/apply_avatar.py \
  --video out/<episode>/final.en.mp4 \
  --audio build/<episode>/master.wav \
  --engine vrm --vrm assets/avatar/me.vrm
```

## 6. Known limits

- `assets/avatar/me.vrm` is the owner’s current VRoid model (16 MB);
  `sample.vrm` is the older fallback. Both have `aa/ih/ou/ee/oh/blink`
  blendshapes and no jaw bone.
- Lip sync is syllable-level (pinyin final), not phoneme-accurate.
- 8 fps keeps long renders cheap; 12–15 fps is smoother (the 20s sample uses 15).
- Model licensing is the owner’s responsibility.
