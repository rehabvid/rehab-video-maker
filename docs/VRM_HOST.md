# VRM talking host — setup and pipeline

The repo supports two host engines:

| Engine | Source | Look | Lip sync |
|---|---|---|---|
| `vrm` (default) | `assets/avatar/me.vrm` (fallback: `host.vrm`) | rigged 3D avatar | `aa/ih/ou/ee/oh` blendshapes from syllable visemes + natural blink |
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
- `sample.vrm` / `sample1.vrm` / `sample2.vrm` were older experiments and are not
  committed; `apply_avatar.py` still accepts them via `VRM_MODEL`.

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
is absent it uses `host.vrm`. To pin a model explicitly:

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

- `assets/avatar/me.vrm` is the owner’s current VRoid model (16 MB). It has
  `aa/ih/ou/ee/oh/blink` blendshapes, no jaw bone, and a full 54-bone humanoid
  rig (fingers included).
- Lip sync is syllable-level (pinyin final), not phoneme-accurate.
- 8 fps keeps long renders cheap; 12–15 fps is smoother (the 20s sample uses 15).
- Model licensing is the owner’s responsibility.

## 7. Previewing the pages

`tools/vrm/avatar.html` and `tools/vrm/rehab.html` are three.js **scenes**, not
stand-alone documents. Their imports are ES modules, so opening the file
directly (`file://`) is blocked by the browser's CORS rules and you get a blank
page plus `ERR_FAILED` on `three.module.js`. That is not a bug in the page.

Serve the repository and open the page over HTTP:

```bash
cd /path/to/rehab-video-maker
python3 -m http.server 8765
```

Then:

```
http://localhost:8765/tools/vrm/avatar.html?model=/assets/avatar/me.vrm&size=512
http://localhost:8765/tools/vrm/rehab.html?model=/assets/avatar/me.vrm&w=1280&h=720&k=0.00448&floor=612&wall=596
```

If you do open the file directly, both pages now print this command instead of
showing a blank canvas. The headless renderers (`render_vrm.mjs`,
`render_rehab.mjs`) start their own server and never need this step.

## 8. Full-body rehab patient

`rehab.html` is a second, separate scene: a **full-body** patient in strict
right profile, animated from a pose track, used by the rehab video.

```bash
.venv/bin/rehab-slideshow build --exercise wall-climb --engine vrm
```

How it fits:

1. `rehab_slideshow/cli.py` renders the storyboard frames **without** the
   vector figure (`with_figure=False`); the room, floor and text overlay are
   unchanged.
2. `tools/gen/vrm_pose.py` turns the storyboard poses into wrist targets on the
   wall plane (`build/<id>/pose-track.json`). The track is in absolute seconds,
   so the climb carries across cue cuts.
2. The layout switches to the **stage** composition (`illustrations.STAGE`):
   the patient fills ~72% of the frame height and the copy moves into a side
   panel on the wall, like a training video. The vector engine keeps the
   original wide composition.
3. `tools/vrm/render_rehab.mjs` renders alpha PNGs at 1280x720, 30 fps.
4. `rehab_slideshow/video.py` composites each patient frame onto the 2x master
   below the text overlay, then applies the usual camera move.

Calibration is shared with `rehab_slideshow.illustrations`:

| Constant | Value | Meaning |
|---|---|---|
| `k` | 0.003242 m/px | metres per design pixel (figure ≈ 520 px tall, ~72% of the frame) |
| floor | 618 | floor line in the 1280x720 design space |
| wall | 640 | wall line; the palm meets it and the text panel starts at 700 |
| `zWall` | 0.30 m | wall plane in front of the hips |

The arm is solved with two-bone IK: the storyboard gives a wrist height, and
the elbow angle follows, so the hand stays on the wall at every step instead of
floating. The upper bound (`HIGH_Y = 1.50 m`) sits inside the 0.426 m reach, so
the elbow is never hyperextended to fake contact.

The hand is oriented with a full basis (finger direction + palm normal), not a
single "point the fingers" rotation. That twist is what decides whether you see
the back of the hand or the palm: on the wall the fingers point up and the palm
normal is +Z (flat on the wall); with the arm down the fingers follow the
forearm and the palm normal turns to the thigh. The rest basis is the VRoid
T-pose with palms down.

The Ken Burns pan/zoom is disabled when a patient layer is present: the figure
is already moving, and a camera pan on top would slide it against the fixed text
panel.

Poses come only from the storyboard names (`intro`, `stance`, `hands`, `climb`,
`high`, `hold`, `lower`, `close`); the track times the transitions and adds the
finger-walk steps. It does not invent a movement the clinical script does not
ask for.

### Glasses fit

`me.vrm` parents its glasses to the head bone with an offset that floats the
frame in front of the nose and below the eyes. `tools/vrm/glasses.js` corrects
that at load time, for both `rehab.html` and `avatar.html`:

- the lens plane is placed 4 mm in front of the nose tip (the +Z extent of the
  `Face` mesh),
- the frame's vertical centre sits 5 mm below the `leftEye`/`rightEye` bones,
  so the pupil lands inside the lens instead of under its lower edge,
- the frame is scaled 1.08x about the lens centre: the exported pair is small
  for this head and leaves the eyes uncovered,
- the correction is applied in the head bone's local space, so head turns keep
  the frames on the face.

On `me.vrm` that is about +13 mm up and -31 mm back from the exported offset. A model whose glasses
already fit moves by ~0. Nothing is written to the 16 MB asset.

### Limits

- The VRM is a stylised VRoid figure, not a photoreal patient. It reads as 3D
  cartoon; the vector version remains the default (`--engine vector`).
- One arm is animated (the affected side). The far arm is held at shoulder
  height on the wall.
- The model's own clothes (white shirt, trousers) replace the illustration's
  teal top. Wardrobe is not medically meaningful but it is a visible change.
- Lip sync and facial acting are off; the narration is voice-over, so the
  patient does not talk.

