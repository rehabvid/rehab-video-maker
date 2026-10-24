# ComfyUI workflows for a reusable podcast avatar

This folder is the practical companion to `../SKILL.md`. It covers the two
workflows you build once and reuse every episode:

1. **Character sheet** — turn 6–10 photos into a consistent, licensable
   "presenter" image set (SDXL + IPAdapter, or Flux + PuLID/InstantID).
2. **Talking A-roll** — animate the canonical portrait from a narration clip
   with **EchoMimicV3-Flash** (1.3B, 8 steps), which is the best fit for a
   MacBook M2 with 32 GB unified memory.

It also documents the optional **InfiniteTalk hero-shot** workflow and the
**LivePortrait idle-loop** workflow.

> **The important decision:** on an M2/32 GB, do not try to render 15 minutes of
> 14B InfiniteTalk, and do not plan a 3–5 minute EchoMimic A-roll either.
> Render **30–60 seconds** of 1.3B EchoMimic A-roll in 1-second units and cover
> the rest with b-roll, quote cards, charts and screen recordings. That is a
> 3.5–7 hour overnight job; a 3–5 minute A-roll belongs on a rented GPU.

---

## 0. Install ComfyUI on Apple Silicon

The setup below was tested on an M2/32 GB with macOS and Python 3.12. It
installs ComfyUI under the repository's gitignored `tools/ComfyUI/` directory
so the avatar models never enter the project's own `.venv` or git history.

Tested commits: ComfyUI `d07dff4`, `ComfyUI_EchoMimic` `3a36b00`,
`ComfyUI-VideoHelperSuite` `4d907be`, `ComfyUI_IPAdapter_plus` `a0f451a`.

### 0.1 ComfyUI and PyTorch MPS

```bash
git clone --depth 1 https://github.com/comfyanonymous/ComfyUI tools/ComfyUI
uv venv --python 3.12 tools/ComfyUI/.venv
uv pip install --python tools/ComfyUI/.venv/bin/python \
  torch torchvision torchaudio
uv pip install --python tools/ComfyUI/.venv/bin/python \
  -r tools/ComfyUI/requirements.txt
```

Verify that MPS is available:

```bash
tools/ComfyUI/.venv/bin/python -c \
  "import torch; print(torch.__version__, torch.backends.mps.is_available())"
```

### 0.2 Custom nodes

```bash
mkdir -p tools/ComfyUI/custom_nodes

git clone --depth 1 https://github.com/smthemex/ComfyUI_EchoMimic \
  tools/ComfyUI/custom_nodes/ComfyUI_EchoMimic

git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite \
  tools/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite

git clone --depth 1 https://github.com/cubiq/ComfyUI_IPAdapter_plus \
  tools/ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus
```

Install the Node requirements. `ComfyUI_IPAdapter_plus` has no
`requirements.txt`; it uses ComfyUI core.

```bash
uv pip install --python tools/ComfyUI/.venv/bin/python \
  -r tools/ComfyUI/custom_nodes/ComfyUI_EchoMimic/requirements.txt
uv pip install --python tools/ComfyUI/.venv/bin/python \
  -r tools/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt
```

### 0.3 Fix the EchoMimic node on macOS

The upstream node needs eight fixes as of the tested commit. Apply these once
after cloning.

**1. Pin a mediapipe version that still has `solutions`.** `mediapipe 1.x`
removed it, and the node imports `from mediapipe import solutions`:

```bash
uv pip install --python tools/ComfyUI/.venv/bin/python "mediapipe==0.10.21"
```

**2. Install the modules the requirements file omits:** `librosa` and
`pyloudnorm`.

```bash
uv pip install --python tools/ComfyUI/.venv/bin/python librosa pyloudnorm
```

**3. Restore the missing `src/dist` folder.** The upstream `.gitignore` has a
bare `dist/` entry, so the folder was never committed and the node fails with
`No module named '...echomimic_v3.src.dist'`. Copy it from the EchoMimicV3
repository:

```bash
TMP=$(mktemp -d)
git clone --depth 1 https://github.com/antgroup/echomimic_v3 "$TMP"
cp -R "$TMP/src/dist" \
  tools/ComfyUI/custom_nodes/ComfyUI_EchoMimic/echomimic_v3/src/dist
rm -rf "$TMP"
```

Then make the unused `decord` import optional in
`custom_nodes/ComfyUI_EchoMimic/echomimic_v3/infer_flash_pro.py`:

```python
try:
    import decord  # not used by the Flash path; no macOS arm64 wheel
except ImportError:
    decord = None
```

The Flash path does not use `decord`; the upstream V2 preprocessing does. Do
not spend time building `decord` from source for this workflow.

**4. Replace `torchaudio.save` with `soundfile`.** With torchaudio 2.11, `save`
requires TorchCodec and fails with `ModuleNotFoundError: No module named
'torchcodec'` when `Echo_Predata` writes the temporary narration file.
`soundfile` is already installed with `librosa`. At the top of
`custom_nodes/ComfyUI_EchoMimic/EchoMimic_node.py`, add:

```python
import soundfile as sf
```

Then replace the `io_base.BytesIO()` / `torchaudio.save(...)` block with:

```python
waveform = audio["waveform"].squeeze(0).detach().cpu().float().numpy()
if waveform.ndim == 2 and waveform.shape[0] <= 8:
    waveform = waveform.T
sf.write(audio_file, waveform, int(audio["sample_rate"]), format="FLAC")
```

The file is still named `*_temp.wav`, but the FLAC header is what
`librosa.load` and MoviePy read. This is safer than installing TorchCodec on
Apple Silicon.

**5. Capture Wav2Vec2 hidden states on transformers 5.x.** `Echo_Predata` calls
`audio_encoder(..., output_hidden_states=True)`, but transformers 5 removed that
flag from `Wav2Vec2Encoder.forward`; `embeddings.hidden_states` is `None` and the
node fails with `'NoneType' object is not subscriptable`. In
`custom_nodes/ComfyUI_EchoMimic/echomimic_v3/src/wav2vec2.py`, add this helper
after `linear_interpolation`:

```python
def _capture_encoder_hidden_states(encoder, hidden_states, **kwargs):
    captured = [hidden_states]
    hooks = []
    if kwargs.get("output_hidden_states"):
        def _hook(module, inputs, output):
            captured.append(output[0] if isinstance(output, tuple) else output)

        for layer in encoder.layers:
            hooks.append(layer.register_forward_hook(_hook))
    try:
        outputs = encoder(hidden_states, **kwargs)
    finally:
        for hook in hooks:
            hook.remove()
    return outputs, tuple(captured)
```

Then, in both `forward` and `encode`, replace the `self.encoder(...)` call with:

```python
        encoder_outputs, captured_hidden_states = _capture_encoder_hidden_states(
            self.encoder,
            hidden_states,
            attention_mask=attention_mask,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )
```

and set `hidden_states=captured_hidden_states if output_hidden_states else None`
in the returned `BaseModelOutput`. The tuple starts with the projected input, so
EchoMimic's `hidden_states[1:]` still returns one state per encoder layer. If
you prefer not to patch, pin `transformers==4.x` in the ComfyUI venv instead.

**6. Cast the RoPE and timestep tables to float32.** `rope_params` and
`sinusoidal_embedding_1d` build float64/complex128 tensors, which MPS rejects
with `TypeError: Cannot convert a MPS Tensor to float64 dtype`. In
`custom_nodes/ComfyUI_EchoMimic/echomimic_v3/src/wan_transformer3d_audio_2512.py`
change:

```python
position = position.type(torch.float64)          # -> torch.float32
torch.arange(0, dim, 2).to(torch.float64)        # -> torch.float32  (3 places)
```

Apply the same change to `wan_transformer3d_audio.py` if you plan to use the
non-Flash V3 mode. The RoPE tables then become complex64, which MPS supports.
This changes only the precision of the precomputed tables, not the model
weights.

**7. Match the transformer dtype on MPS.** The pipeline relies on
`torch.cuda.amp.autocast` to cast latents to `weight_dtype`, but that context is
a no-op on MPS. With bf16 weights and float32 latents, MPS aborts with
`failed assertion Destination NDArray and Accumulator NDArray cannot have
different datatype in MPSNDArrayMatrixMultiplication`.

In `echomimic_v3/src/pipeline_wan_fun_inpaint_audio_2512.py`, cast the model
input after scheduler scaling:

```python
latent_model_input = self.scheduler.scale_model_input(latent_model_input, t)
latent_model_input = latent_model_input.to(device, weight_dtype)
...
timestep = t.expand(latent_model_input.shape[0]).to(device, weight_dtype)
```

In `echomimic_v3/src/wan_transformer3d_audio_2512.py`, cast the sinusoidal
timestep embedding before the first linear layer:

```python
e = self.time_embedding(
    sinusoidal_embedding_1d(self.freq_dim, t).to(dtype))
```

If you prefer not to patch the pipeline, load the transformer and VAE in
float32 (`weight_dtype_str="float32"`), but that roughly doubles model memory.

**8. Use the node's `width`/`height` for the Flash path.** The upstream node
hardcodes `(768,768)` as the `sample_size` argument to
`Flash_Echo_v3_predata`, so the `width`/`height` widgets only change metadata.
A 16:9 reference image still renders at 1024×576 (the same area as 768×768).
In `custom_nodes/ComfyUI_EchoMimic/EchoMimic_node.py`, change:

```python
face_img, (768, 768), audio_file, ...
```

to:

```python
face_img, (width, height), audio_file, ...
```

With `"width": 768, "height": 432` in the API workflow, a 16:9 image now renders
at 768×432 — about 44% fewer pixels, a lower memory peak, and a much lower
chance of hitting the macOS GPU watchdog (`Impacting Interactivity`).

### 0.4 Start ComfyUI

```bash
cd tools/ComfyUI
PYTORCH_ENABLE_MPS_FALLBACK=1 \
PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0 \
.venv/bin/python main.py \
  --use-pytorch-cross-attention --preview-method none --port 8188
```

The startup log should list `Echo_LoadModel`, `Echo_Predata` and
`Echo_Sampler`. If it says `IMPORT FAILED`, fix that import before downloading
models.

`PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` lets PyTorch use more unified memory, but
it can also make macOS swap. Watch Activity Monitor and keep 6–8 GB free for the
OS and your browser.

If a model is stored in **fp8**, MPS can fail with
`MPSNDArrayMatrixMultiplication: unsupported input/output datatypes`. The
EchoMimic Flash checkpoints are bf16, but the text encoder is the fp8
`umt5_xxl_fp8_e4m3fn_scaled` file. ComfyUI converts scaled fp8 checkpoints to
mixed operations on load; if your build still fails, either download the 11.4 GB
`umt5_xxl_fp16.safetensors`, or set `CLIPLoader.device` to `cpu` in the API
workflow. CPU text encoding is slower, but the avatar sampler still runs on MPS.
Do not mix fp8 text encoders into an MPS graph if you see that error.

---

## 1. Character sheet (one-time, reusable)

### 1.1 Photo checklist

Use 6–10 photos of the **same person**, with:

- front view, 3/4 left, 3/4 right (the three most important)
- neutral expression, eyes open, no sunglasses, no hat
- even lighting, no strong colour cast
- plain or simple background
- at least 1024 px on the short side
- one person per photo

Avoid: group photos, heavy beauty filters, extreme angles, closed eyes, hands
covering the face.

### 1.2 The workflow

Start from the default SDXL text-to-image graph and add IPAdapter:

```text
CheckpointLoaderSimple (SDXL base)
        │
LoadImage front ─┐
LoadImage left  ─┼─ ImageBatch ── IPAdapterUnifiedLoader ── IPAdapterAdvanced
LoadImage right ─┘                                              │
                                                               ▼
CLIPTextEncode positive ─────────────────────────────────► KSampler
CLIPTextEncode negative ─────────────────────────────────►   │
EmptyLatentImage 1344x768 ───────────────────────────────►   │
                                                             ▼
                                                       VAEDecode
                                                             │
                                                       SaveImage
```

Settings that work well on a 32 GB Mac:

| Node | Setting |
| --- | --- |
| Checkpoint | SDXL base 1.0 (or a photoreal SDXL fine-tune) |
| `ImageBatch` | the three reference photos, in a consistent order |
| `IPAdapterUnifiedLoader` | `PLUS (high strength)` |
| `IPAdapterAdvanced` | weight `0.75`, start `0.0`, end `1.0`, combine `concat` |
| `EmptyLatentImage` | `1344 x 768` (16:9) |
| `KSampler` | steps 30, cfg 7.0, `dpmpp_2m`, `karras`, denoise 1.0 |
| Seed | fixed; write it into `character.json` |
| Batch | 4 images per run, 2–3 runs |

If you have `ComfyUI-Impact-Pack`, add a `FaceDetailer` pass at 0.35 denoise.
It improves eyes and hands, but adds 30–60 seconds per image on an M2.

Keep the canonical `front` image **16:9**. The EchoMimic Flash path preserves
the reference aspect ratio and caps the pixel area at `width × height`; a square
portrait renders at 576×576, while a 16:9 portrait renders at 768×432. Crop the
chosen render to 16:9 before Phase 2 so the avatar matches the timeline.

### 1.3 Prompts

**Positive base**

```text
A 35-year-old person with short dark hair, wearing a charcoal knit sweater,
sitting at a wooden desk in a warm home studio, medium shot, hands resting on
the desk, looking at the camera, soft window light from the left, shallow depth
of field, 35mm lens, natural skin texture, photorealistic, 16:9
```

**Negative base**

```text
cartoon, illustration, 3d render, plastic skin, extra fingers, deformed hands,
distorted face, text, watermark, logo, busy background, harsh flash,
oversaturated, low resolution
```

Generate a small **character sheet** of poses, not one image:

- `front` — neutral, hands on desk
- `three-quarter` — turned 15–20°, still looking at camera
- `listening` — leaning back slightly, relaxed mouth
- `making-a-point` — one hand raised, palm open
- `thinking` — hand near chin
- `smiling` — warm, closed-mouth smile

Pick the best **front** and **three-quarter** images. Those two are enough for
most episodes; the other poses are useful as cutaways or reaction shots.

### 1.4 Freeze the character

Write a `characters/<name>/character.json`:

```json
{
  "name": "me",
  "consent": "self",
  "created": "2026-10-23",
  "checkpoint": "sd_xl_base_1.0.safetensors",
  "ipadapter": "ip-adapter-plus_sdxl_vit-h.safetensors",
  "seed": 123456,
  "prompt": "A 35-year-old person ...",
  "negative_prompt": "cartoon, illustration ...",
  "canonical": {
    "front": "canonical/front.png",
    "three_quarter": "canonical/three-quarter.png"
  },
  "voice": "voice.json"
}
```

Then never regenerate the face for a normal episode. If you change hair,
wardrobe, weight or studio, create `characters/me-v2/` and keep `v1` for old
videos. Mixing versions inside one video is the fastest way to look like a
different person between cuts.

### 1.5 Character pack layout

```text
characters/me/
  character.json
  photos/                 # private; never commit
  canonical/
    front.png
    three-quarter.png
    idle.mp4              # optional LivePortrait loop
  prompts/
    character.md
    scene.md
    negative.md
  workflow.json           # API export of the character-sheet graph
  voice.json
```

Back this folder up outside git. The photos and canonical renders are personal
data; treat them like you would a passport photo.

---

## 2. Talking A-roll with EchoMimicV3-Flash

### 2.1 Why this model

EchoMimicV3 is a 1.3B audio-driven human animation model. It generates a
half-body talking person from one image + audio + a scene prompt, with lip
movement, facial expression and hand/body gestures. The Flash variant is
8-step and was designed for 12 GB VRAM at 768×768, so a 32 GB M2 can run it in
bf16 if you keep the resolution and chunk length modest.

It is not as realistic as InfiniteTalk or LongCat-Video-Avatar, but it is the
only open model in this class that is realistically renderable on your laptop
for minutes of footage rather than seconds.

### 2.2 Models (V3-Flash-Pro)

Use the included script; it is idempotent and resumes partial downloads:

```bash
skills/podcast-avatar-commentary/workflows/download_models.sh tools/ComfyUI
```

It downloads and places roughly 16 GB:

| Source file | Destination |
| --- | --- |
| `Wan2.1-Fun-V1.1-1.3B-InP/diffusion_pytorch_model.safetensors` | `models/echo_mimic/transformer/` |
| `Wan2.1-Fun-V1.1-1.3B-InP/config.json` | `models/echo_mimic/transformer/` |
| `EchoMimicV3/echomimicv3-flash-pro/*` | `models/echo_mimic/echomimicv3-flash-pro/` |
| `chinese-wav2vec2-base/*` | `models/echo_mimic/chinese-wav2vec2-base/` |
| `Wan2.1_VAE.pth` | `models/vae/` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders/` |
| `clip_vision_h.safetensors` | `models/clip_vision/` |

The script also creates `clip_vision_h_wan.safetensors` and
`models/clip/umt5_...` symlinks so the upstream example names still resolve.

The Flash path does **not** need `wav2vec2-base-960h`, `retinaface.h5`, the
non-Flash EchoMimic transformer, or the LightX2V LoRA. Those are for V1/V2 or
the slower V3 graph.

Manual equivalent, if you prefer explicit commands:

```bash
HF=tools/ComfyUI/.venv/bin/hf
C=tools/ComfyUI

$HF download alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP \
  diffusion_pytorch_model.safetensors config.json Wan2.1_VAE.pth \
  --local-dir "$C/.hf-downloads/wan"
mv "$C/.hf-downloads/wan/diffusion_pytorch_model.safetensors" \
  "$C/models/echo_mimic/transformer/"
mv "$C/.hf-downloads/wan/config.json" \
  "$C/models/echo_mimic/transformer/"
mv "$C/.hf-downloads/wan/Wan2.1_VAE.pth" "$C/models/vae/"

$HF download BadToBest/EchoMimicV3 \
  echomimicv3-flash-pro/config.json \
  echomimicv3-flash-pro/diffusion_pytorch_model.safetensors \
  --local-dir "$C/models/echo_mimic"

$HF download TencentGameMate/chinese-wav2vec2-base \
  config.json preprocessor_config.json pytorch_model.bin \
  chinese-wav2vec2-base-fairseq-ckpt.pt \
  --local-dir "$C/models/echo_mimic/chinese-wav2vec2-base"

$HF download Comfy-Org/Wan-2.1 \
  split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
  split_files/clip_vision/clip_vision_h.safetensors \
  --local-dir "$C/.hf-downloads/comfy-org"
mv "$C/.hf-downloads/comfy-org/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
  "$C/models/text_encoders/"
mv "$C/.hf-downloads/comfy-org/split_files/clip_vision/clip_vision_h.safetensors" \
  "$C/models/clip_vision/"
```

Then create the two symlinks:

```bash
ln -sfn clip_vision_h.safetensors \
  "$C/models/clip_vision/clip_vision_h_wan.safetensors"
ln -sfn ../text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
  "$C/models/clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
```

### 2.3 The workflow

The tested API graph is
[`echomimic_v3_flash.api.json`](echomimic_v3_flash.api.json). A draft variant
with `cfg=1.0` is in
[`echomimic_v3_flash_cfg1.api.json`](echomimic_v3_flash_cfg1.api.json); it is
about twice as fast but has weaker mouth motion.

```text
LoadImage ────────────────┐
LoadAudio ────────────────┤
CLIPLoader (umt5, wan) ───┼─ Echo_Predata ── Echo_Sampler ── VHS_VideoCombine
CLIPVisionLoader ─────────┤        ▲                ▲
Echo_LoadModel ───────────┘        │                │
                                   └── model/info ──┘
```

The current `ComfyUI_EchoMimic` node exposes three separate nodes, not one:

| Node | Returns | Role |
| --- | --- | --- |
| `Echo_LoadModel` | `model`, `info` | loads the Wan 1.3B transformer, EchoMimic FlashPro checkpoint, VAE and audio pipeline |
| `Echo_Predata` | `emb` | resizes the portrait, encodes the audio and prompt, builds the latent/mask |
| `Echo_Sampler` | `image`, `frame_rate` | runs the 8-step sampler and returns frames |
| `VHS_VideoCombine` | MP4 | muxes the frames + source audio and writes H.264 |

The API workflow ships with these placeholders: `{{IMAGE}}`, `{{AUDIO}}`,
`{{PROMPT}}`, `{{NEGATIVE_PROMPT}}`, `{{SEED}}`, `{{LENGTH}}`, `{{PREFIX}}`.
`comfy_client.py` fills them. `{{FPS}}` is not needed: the sampler's
`frame_rate` output is wired directly into `VHS_VideoCombine`, and the graph is
fixed at 25 fps.

The avatar clip contains the narration audio for convenience. `assemble.py`
strips it with `-an` and uses `master.wav`, so the final mix is not doubled.

### 2.4 Settings for a 32 GB M2

| Setting | Start here | Why |
| --- | --- | --- |
| Resolution | `768 x 432` | 16:9, 720p-class avatar; the assembler upscales to 1080p |
| Steps | `8` | Flash-Pro is distilled for 8 steps |
| `cfg` | `3.5` | 3–6 is the recommended range; `1.0` is a faster draft option |
| `sample_rate` | `16000` | Wav2Vec2 input rate |
| `context_frames` | `12` | Sampler UI value; the Flash path uses the whole shot |
| `context_overlap` | `3` | Same |
| `lowvram` | `true` | Harmless for Flash; keeps the VAE/transformer path conservative |
| `block_offload` | `false` | Keeps the pipeline on MPS. `true` moves it to CPU and is only a memory escape hatch |
| `use_mmgp` | `None` | The mmgp profiles are CUDA-oriented |
| `teacache_offload` | `false` | Flash is already 8 steps; offload adds overhead |
| `length` | `{{LENGTH}}` | `comfy_client.py` computes frames from the narration duration |
| `partial_video_length` | `65` | Unused by the Flash path; leave the UI default |
| `fps` | `25` | EchoMimic's native rate; set `"fps": 25` in `shots.json` |
| Seed | one per character, reuse | Identity stability across shots |

`cfg=1.0` is a measured **draft** option. It disables the audio-guidance branch
and halves the sampler work: 19.4 s/step, 2:36 of sampling, about 4 min wall for
a 1 s 768×432 shot on the same M2 Pro. The frame is clean, but the mouth motion
is visibly weaker than the `cfg=3.5` output. Use
`echomimic_v3_flash_cfg1.api.json` for drafts and the default workflow for the
final render.

The graph's `facemask_ratio` and `facecrop_ratio` are UI values; the Flash path
uses `nomarl_upscale` on the whole portrait. Give it a clean medium shot with
the face centred and the hands visible but at rest.

If the render is killed or macOS swaps, change `block_offload` to `true` for one
test, or lower the resolution to `640 x 360`. Do not enable `use_mmgp` on MPS.

The Flash path caps the **area** at `width × height` and preserves the reference
image's aspect ratio. A 1024×576 portrait with `768 × 432` in the workflow
renders at 768×432; a square portrait renders at 576×576. Crop the canonical
portrait to 16:9 before rendering so the avatar matches the 16:9 timeline.

Measured on an Apple M2 Pro / 32 GB with this workflow: **38.4 s per step** for
a 1.0 s (25-frame) 768×432 shot, 5:06 of sampling and 6:52 wall including model
load and text/audio preprocessing. A 2.0 s (49-frame) shot took **24:28 of
sampling and about 31 min queue-to-file**; the last three steps degraded to
173 / 231 / 255 s as memory pressure built. Use 1-second shots for production,
close Chrome and other memory-heavy apps, and keep the avatar share of a
15-minute episode to 30–60 s.

### 2.5 Prompt for a casual podcast shot

**Positive**

```text
A person sitting at a wooden desk in a warm home studio, speaking casually to
the camera, natural hand gestures, medium shot, hands visible, soft window light
from the left, shallow depth of field, photorealistic, calm and thoughtful
```

**Negative**

```text
bad hands, extra fingers, fused fingers, distorted face, warped background,
text, watermark, cartoon, 3d render, fast jerky motion, exaggerated gestures,
duplicate person
```

Keep the prompt almost identical across episodes. Change only what you want to
change (wardrobe, background, time of day). The prompt is part of the character,
not a per-video creative writing exercise.

### 2.6 Chunking and stitching

- Generate **one shot per narration beat**, 20–40 seconds.
- Do not ask the model for a 15-minute video in one queue item. Long renders
  drift, and one bad hand means re-rendering the whole thing.
- Use the same canonical image, prompt and seed family for every shot.
- Hard-cut on sentence boundaries in the edit. A 6–8 frame crossfade is fine
  for an idle loop, but it hides lip-sync and looks soft.
- If a shot fails, re-render only that shot. The `comfy_client.py` cache keeps
  the good ones.

### 2.7 API workflow and `comfy_client.py`

The repository ships the API graph at
`skills/podcast-avatar-commentary/workflows/echomimic_v3_flash.api.json`. You
do not need to export it by hand. Point `--workflow` at that file, or copy it
into `characters/me/echomimic.api.json` if you want to customise the prompt,
resolution or sampler settings.

Before the first real render, resolve the placeholders:

```bash
uv run python skills/podcast-avatar-commentary/scripts/comfy_client.py \
  --workflow skills/podcast-avatar-commentary/workflows/echomimic_v3_flash.api.json \
  --timing build/ep01/timing.json \
  --out build/ep01/avatar \
  --root . \
  --dry-run
```

Then run the same command without `--dry-run`. The client uploads the portrait
and narration clip, queues one job per avatar shot, polls ComfyUI, downloads the
MP4, and writes a fingerprint so unchanged shots are skipped. Add `--same-seed`
to reuse one seed across all shots; an explicit `seed` in a shot is always
honoured as written.

If you edit the graph in the ComfyUI UI, use **Workflow → Export (API)** and
re-apply the placeholders:

| Node input | Replace with |
| --- | --- |
| `LoadImage.image` | `"{{IMAGE}}"` |
| `LoadAudio.audio` | `"{{AUDIO}}"` |
| positive prompt text | `"{{PROMPT}}"` |
| negative prompt text | `"{{NEGATIVE_PROMPT}}"` |
| `Echo_Sampler.seed` | `"{{SEED}}"` |
| `Echo_Predata.length` | `"{{LENGTH}}"` |
| `VHS_VideoCombine.filename_prefix` | `"avatar/{{PREFIX}}"` |

Keep the `Echo_LoadModel` widget order exactly as the node exposes it:
`vae, lora, denoising, infer_mode, lowvram, teacache_offload, block_offload,
use_mmgp, version`. The example workflow shipped with the node is stale and has
strings in the boolean slots; do not use it unchanged.

---

## 3. Optional: InfiniteTalk hero shot

Use this when you want a 20–40 second intro that looks noticeably better than
the rest of the video, and you are willing to wait or rent a GPU.

The official ComfyUI template is **Wan2.1 InfiniteTalk** (search the template
library or download `video_wan2_1_infinitetalk.json`). It uses native nodes:
`WanInfiniteTalkToVideo`, `ModelPatchLoader`, `Load Diffusion Model`,
`Load Audio`, `Load Image`, `WanVideo VAE Loader`.

Models:

```text
ComfyUI/models/
  diffusion_models/
    Wan2_1-I2V-14B-480p_fp8_e4m3fn_scaled_KJ.safetensors
  text_encoders/
    umt5_xxl_fp8_e4m3fn_scaled.safetensors
  model_patches/
    wan2.1_infiniteTalk_single_fp16.safetensors
  audio_encoders/
    wav2vec2-chinese-base_fp16.safetensors
  vae/
    Wan2_1_VAE_bf16.safetensors
  loras/
    lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors
```

Settings for a hero shot: 480p, 4–8 steps with the LightX2V LoRA,
`motion_frame_count=9`, `audio_scale=1.0`, 81 frames per chunk, then extend.
Use the same `{{IMAGE}}` / `{{AUDIO}}` / `{{PROMPT}}` placeholders and the same
`comfy_client.py`.

**Mac reality check:** on an M2/32 GB, expect roughly 10 minutes for a 5-second
480p clip with the 14B model, and more with extensions. A 30-second hero shot is
therefore an hour-scale job; a 15-minute one is not a laptop job. Render hero
shots on Comfy Cloud, RunPod, or a rented 4090/5090, then bring the MP4 back into
the same `build/ep01/avatar/` folder.

---

## 4. Optional: LivePortrait idle loop

LivePortrait is fast and has official Apple Silicon support, but it is **not
audio-driven**. It animates a source portrait from a driving video. That makes it
a great way to produce a reusable 10–20 second "listening / breathing / small
head movement" loop, and a poor way to lip-sync a 15-minute script by itself.

Use `ComfyUI-LivePortraitKJ` or `ComfyUI-AdvancedLivePortrait`, load the example
workflow, and use:

- source: `characters/me/canonical/front.png`
- driving: a 10–20 second clip of yourself (or a licensed performance) with a
  neutral expression, blinks, and small head movements
- output: `characters/me/canonical/idle.mp4`

In the edit, use the idle loop for reaction shots and transitions. For the
talking A-roll, keep EchoMimic. If you want to lip-sync an existing performance,
MuseTalk or LatentSync can do it, but both are CUDA-oriented and are not the
recommended path on this laptop.

---

## 5. Benchmark before you commit

Do this once, before you write a 15-minute script.

1. Pick a 10-second narration clip.
2. Render a **1-second** clip at your target resolution and step count. It is
   the stable production unit on this machine.
3. Time it from queue to downloaded MP4.
4. Multiply:

```text
1 minute of avatar  = 60  × the 1-second time
15 minutes          = 900 × the 1-second time
```

Examples:

| 1 s render | 1 min avatar | 15 min avatar | Decision |
| --- | --- | --- | --- |
| 1 min | 1 h | 15 h | comfortable overnight |
| 3 min | 3 h | 45 h | weekend or cloud |
| 5 min | 5 h | 75 h | cap avatar at 30–60 s |
| 7 min (measured) | 7 h | 105 h | measured 768×432, 8 steps, M2 Pro |

Measured on the test machine: 1 s = 6:52 wall, 2 s = about 31 min wall (later
steps slowed under memory pressure). Use 1-second shots.

The hybrid edit is the real optimisation: **30–60 seconds of avatar plus
14–14.5 minutes of b-roll** is a better video and about 3.5–7 hours of local
render. A 3–5 minute avatar share is a cloud/rented-GPU job.

---

## 6. Troubleshooting on macOS

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `MPSNDArrayMatrixMultiplication: unsupported input/output datatypes` | fp8 weights on MPS | use bf16/fp16, or the Apple Silicon fp8→bf16 patch set |
| ComfyUI killed / swap storm | unified memory exhausted | lower resolution to 640×360, set `block_offload=true` for one test, close apps, keep 6–8 GB free |
| `Placeholder {{...}} was not found` | API workflow has a key the client did not fill | add it to the shot or edit the workflow |
| EchoMimic node missing | custom node failed to import | check the ComfyUI console at startup; install its requirements |
| `module 'mediapipe' has no attribute 'solutions'` | mediapipe 1.x removed the legacy API | pin `mediapipe==0.10.21` |
| `No module named 'librosa'` | not in the node requirements | `uv pip install librosa` |
| `No module named 'torchcodec'` | torchaudio 2.11 `save` path | use the `soundfile` patch in section 0.3 |
| `'NoneType' object is not subscriptable` in `get_audio_embed` | transformers 5 removed Wav2Vec2 hidden states | use the hook patch in section 0.3, or pin transformers 4.x |
| `Cannot convert a MPS Tensor to float64 dtype` | RoPE/timestep tables built as float64 | cast them to float32; see section 0.3 item 6 |
| `MPSNDArrayMatrixMultiplication ... different datatype` / `Abort trap: 6` | CUDA autocast is a no-op on MPS; bf16 weights with float32 latents | cast latents/timestep to `weight_dtype`; see section 0.3 item 7 |
| `Impacting Interactivity` / step time over ~1 min | GPU command buffer hit the macOS watchdog; Flash path ignored `width`/`height` | apply the `(width, height)` patch in section 0.3 item 8; render 768×432 or lower |
| `No module named 'pyloudnorm'` | not in the node requirements | `uv pip install pyloudnorm` |
| `No module named '...echomimic_v3.src.dist'` | upstream `.gitignore` excluded `dist/` | copy `src/dist` from `antgroup/echomimic_v3` (section 0.3) |
| `No module named 'decord'` | no macOS arm64 wheel; unused by Flash | use the guarded import in section 0.3 |
| `Echo_LoadModel` cannot find `Wan2.1_VAE.pth` | model not in `models/vae` | run `download_models.sh` |
| `CLIPLoader` list is empty | text encoder not downloaded | check `models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| `CLIPVisionLoader` cannot find `clip_vision_h_wan.safetensors` | expected upstream name | `download_models.sh` creates the symlink |
| Output has no audio | expected if you use a video-only combine | the avatar renderer is silent; narration is muxed in `assemble.py` |
| Face changes between shots | different reference, prompt or seed | reuse the character pack; keep prompt/seed fixed |
| Hands morph | model limitation | medium shot, hands at rest, negative prompt, or crop hands |
| Background warps | busy background / long render | use a plain studio background; render per shot |
| Lip sync drifts | one long render | generate per shot and cut on sentence boundaries |
| Output is 25 fps, timeline is 30 fps | EchoMimic native rate | set `"fps": 25` in `shots.json` and keep the whole pipeline at 25 |
| Captions missing | font not found by Pillow | install Arial/DejaVu; check `find_font` and `render_caption_overlay` in `lib.py` |
| `ffmpeg failed` during concat | mixed timebases | the assembler falls back to re-encoding; check the first error |

---

## 7. What to keep out of git

`characters/*/photos/`, `canonical/`, `renders/`, `audio/`, `voice/` and the
voice-reference audio files are private and already excluded by the repository
`.gitignore`. `character.json` and the API workflow exports are small
configuration files and are safe to track, but they may contain absolute paths;
review them before committing. Back up the character pack separately; it is the
one asset you cannot regenerate exactly.
