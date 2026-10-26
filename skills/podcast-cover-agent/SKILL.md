---
name: podcast-cover-agent
description: Generate content-aware 1280x720 cover images for Link Zag commentary videos. Uses a consistent Singapore Marina Bay skyline backdrop, rotating angles, ink-and-watercolour sketch or cinematic photo render styles, one topic-specific foreground object, and PIL-composited title/stat text. Produces multiple candidates, a contact sheet, and a YouTube-ready thumbnail.
---

# Podcast Cover Agent

This skill owns the **cover image / YouTube thumbnail** for commentary videos.
It is deliberately separate from the video renderer: covers need art direction,
typography and a recognizable brand, not another slide.

The visual identity is:

> **Singapore Marina Bay as the recurring backdrop, seen from a different angle
> each time; one content-specific foreground object; a cream sketch panel or a
> dark cinematic panel; the same amber/teal accents and typography.**

That gives viewers a recognizable channel even when the topics jump from
refining to France to AI agents.

## Why this exists

The default `thumbnail.py` makes a clean title card. It is useful, but it is not
a magazine cover. This skill adds:

- a real photographic or sketch background instead of a blurred podcast cover;
- a topic-specific foreground object so the cover reflects the video;
- a repeatable safe zone and typography system;
- 3 candidates and a contact sheet for a fast visual choice;
- a short generation loop measured in minutes, not a design session.

## Inputs

Preferred: `youtube.zh.json` (or `youtube.json`) with an optional `cover` brief:

```json
{
  "cover": {
    "topic": "energy",
    "subject": "a lone oil tanker and refinery storage tanks in the foreground",
    "stat": "25–35%",
    "render_style": "sketch",
    "angle": "waterfront"
  }
}
```

`topic` is one of `energy`, `europe`, `ai_advances`, `ai_power`, `macro`,
`investor`, `default`. If omitted, the script scores the title, tags,
description and chapter titles against the keyword rules.

`angle` is one of `waterfront`, `helix`, `gardens`, `esplanade`, `aerial`,
`merlion`. If omitted, the angle is chosen deterministically from the title, so
the same story always gets the same angle but different videos rotate.

## Workflow

Generate three sketch candidates:

```bash
.venv/bin/python skills/podcast-cover-agent/scripts/cover.py \
  --metadata build/ep01/youtube.zh.json \
  --out out/ep01/cover.zh.png \
  --candidates 3
```

Outputs:

```text
out/ep01/cover.zh.png          candidate 1 (default choice)
out/ep01/cover.zh-2.png        candidate 2
out/ep01/cover.zh-3.png        candidate 3
out/ep01/cover.zh-contact.png  labelled 3-up contact sheet
out/ep01/cover.zh.json         prompt, topic, angle, seeds, chosen files
```

Open the contact sheet, pick the best composition, and copy or rename it to
`cover.zh.png`.

Text-only preview using an existing image (no ComfyUI):

```bash
.venv/bin/python skills/podcast-cover-agent/scripts/cover.py \
  --metadata build/ep01/youtube.zh.json \
  --background assets/marina-bay.jpg \
  --out out/ep01/cover-preview.png \
  --no-generate
```

Generate a cinematic photo variant instead of the default sketch:

```bash
.venv/bin/python skills/podcast-cover-agent/scripts/cover.py \
  --metadata build/ep01/youtube.zh.json \
  --render-style photo \
  --angle gardens \
  --out out/ep01/cover-photo.zh.png
```

The raw `.plate.png` is the **video story background** (no baked-in text).
The finished `.png` is the YouTube thumbnail. Do not use the finished cover
behind a card: its title and stat would ghost through the translucent panel.
The video pipeline uses the plate automatically when given the finished cover.

Use the cover on the upload:

```bash
.venv/bin/python skills/podcast-youtuber-agent/scripts/bilingual.py build \
  ... \
  --thumbnail-zh out/ep01/cover.zh.png \
  --upload
```

Or set/refresh it on an existing private video with the uploader's thumbnail
path; YouTube's Data API `thumbnails.set` is part of that flow. A successful
set is confirmed by `contentDetails.hasCustomThumbnail: true`.

## Style pack

| Topic | Kicker | Content-specific foreground |
| --- | --- | --- |
| `energy` | 能源与大宗商品 | oil tanker + refinery storage tanks |
| `europe` | 欧洲与财政政策 | euro notes + government bond certificates |
| `ai_advances` | 人工智能前沿 | illuminated AI server rack |
| `ai_power` | AI 资本开支与电力 | transmission lines + data-centre cooling stack |
| `macro` | 宏观与市场 | bond certificates + currency notes |
| `investor` | 投资者对话 | empty boardroom table + studio microphone |
| `default` | 独立评论 | calm waterfront with one small boat |

The foreground object is what makes the cover reflect the video. Do not use a
generic Marina Bay photo with no content cue.

## Render styles

**Sketch (default)** — architectural ink and watercolour, fine linework,
cross-hatching, muted teal and amber washes, cream paper. This is the most
distinctive and the most consistent across topics. Text sits on a cream panel.

**Photo** — cinematic editorial photograph at blue hour, 35mm, shallow depth of
field, muted teal/amber. Better for a premium documentary feel; slightly more
generic and more likely to produce uncanny details.

Both styles use the same:
- Marina Bay backdrop and angle pack;
- left-third text safe zone;
- amber accent bar, teal stat, paper/muted text;
- 1280×720 output and 16:9 crop;
- no text, logos or faces inside the generated plate.

## ComfyUI setup

The engine is `tools/gen/cover.py`; it talks to a local ComfyUI server.

```bash
# Check the server
curl -s http://127.0.0.1:8188/system_stats >/dev/null

# Start it if needed
tools/ComfyUI/.venv/bin/python tools/ComfyUI/main.py --port 8188 &
```

Models (gitignored, about 8 GB):

```text
tools/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors
tools/ComfyUI/models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors
tools/ComfyUI/models/clip_vision/clip_vision_h.safetensors
```

Optional style reference: pass `--reference path/to/brand-cover.jpg` to use
IPAdapter. Use this only with a cover you own or have rights to.

On an M2 Pro 32 GB, SDXL at 1216×704, 28 steps is typically **30–90 seconds per
plate**. Three candidates plus the contact sheet and text composite usually
finishes in **2–5 minutes**. The diffusion model supplies the background only;
text is drawn in PIL, so Chinese/English titles stay sharp.

If ComfyUI is unavailable, use `--background` with a licensed Marina Bay photo
and keep the same layout. The skill degrades to a typography compositor.

## Review checklist

- At 320×180, the title is still legible in 2 seconds.
- One focal point, not a collage; the foreground object matches the argument.
- No fake faces, logos, brand marks, signatures or generated text.
- Marina Bay is recognizable but not the same angle as the last three covers.
- The left panel and title do not cover the focal object.
- The stat is real and comes from the episode or verified data; otherwise omit.
- The cover language matches the video language.
- AI disclosure stays in the description and YouTube's synthetic-media flag;
  the cover itself should not carry a defensive “human-reviewed” claim.
- Source/credit is in the description; the cover uses no unlicensed image.

## Rules and rights

- Do not generate a real person's likeness or imply guest endorsement.
- Do not put a real company logo or a fake “breaking” badge on a cover.
- Do not use a generated cover to misrepresent a quote, number or event.
- Do not commit ComfyUI models, reference photos or generated cover source
  files outside `out/`/`build/`; these are release artefacts.
- If a cover uses a photographer's Marina Bay image, record the licence and
  credit in the description.
