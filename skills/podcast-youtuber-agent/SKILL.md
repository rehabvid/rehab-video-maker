---
name: podcast-youtuber-agent
description: Turn current popular Business and Technology podcasts into independent 10–15 minute YouTube commentary videos with a personal cloned voice, b-roll slides (no avatar), measured captions, and an optional autonomous YouTube upload. The creator comments on the podcast and never impersonates its host, interviewer or guest. Each run fetches fresh trending sources and filters a cross-run used-episode ledger so an episode is never repeated; short sources are combined around one thesis. Covers voice-sample preparation, a local Chatterbox voice-cloning workflow on Apple Silicon, slide-list drafting/validation, the 1080p renderer, and YouTube OAuth 2.0 best practices.
---

# Podcast YouTuber Agent (legacy all-in-one)

> **Skill split.** For new productions use
> [`../podcast-content-agent/SKILL.md`](../podcast-content-agent/SKILL.md) for
> selection and the slide-by-slide transcript, then
> [`../tech-commentary-slideshow/SKILL.md`](../tech-commentary-slideshow/SKILL.md)
> for the preferred technical slideshow. This skill remains the reference
> all-in-one implementation and the shared home of the content, TTS, assembly
> and upload scripts.

Turn one or more current popular podcast episodes into a **10–15 minute,
b-roll-only YouTube commentary video** narrated in your own cloned voice. There is no talking
avatar in this skill. The visual track is a paced sequence of title, chart,
quote, image and video slides with burned-in captions.

## Editorial role and point of view

The creator is an **independent commentator reviewing the podcast**, not the
podcast's host, interviewer or guest. The original host/interviewer and
guest/interviewee are **subjects of the video**, not the creator's roles. Never
write or perform as if the creator was part of the original recording.

- Refer to the original host and guest in the third person, by name or as
  “the host” and “the guest.” Keep first person for the creator's analysis and
  opinions.
- Do not use host or participant language such as “my guest,” “joining me,”
  “I sat down with,” “I interviewed,” “welcome back to the show,” or “thank you
  for joining me.”
- Attribute the source conversation explicitly: “As [guest] tells [host]…,”
  “The episode argues…,” or “In the interview….” Do not write as if the creator
  asked the question or supplied the answer.
- Open with a clear independent-commentary frame, not an imitation of the
  podcast's own intro. Do not imply that the original show or its guests
  endorse the commentary.
- Titles and descriptions must read as commentary, analysis or critique, never
  as an episode of the original podcast. Never use “Interview with…” unless the
  creator actually conducted that interview.

## Language policy

- **Default published narration is Mandarin (`zh-Hans`).** The English deck is
  the working source for visuals, timing and translation; it is not published
  by default.
- Do **not** upload a separate English narration unless the user explicitly
  asks for English. English audiences should use YouTube's auto-dub on the
  Mandarin primary audio. Keep a Chinese caption track and an English
  translated caption track so both audiences can read along.
- For an explicit English request, run `autopilot.py --language en` (or
  `--english`). For a deliberate two-video release, use
  `--language both` / `--bilingual`.
- The upload remains private by default. Mandarin is the primary ledger entry
  unless English was explicitly requested.

The skill still owns the editorial loop: fetch candidates, score them, research
the guest, and write a continuous spoken script. This document adds the
production layer:

- a measured-timing personal-voice narration pipeline;
- a b-roll slide list and 1080p renderer;
- a YouTube uploader with OAuth 2.0, resumable upload and a synthetic-media
  disclosure.

## Target output

- One 1920×1080 MP4, 30 fps (or 25), H.264 + AAC 48 kHz stereo.
- **Default 10–15 minutes** (target 12–15), roughly **one quarter of the
  source audio** (25%, with a 10-minute floor and a 15-minute cap).
- **35–60 slides.** Qwen3-TTS Base 0.6B measured about **145–155 wpm** on
  slide-by-slide narration. Plan with **150 wpm**: a 10–15 minute commentary
  needs about **1,500–2,250 words**. Use `slides.py --wpm 150` and the measured
  `timing.json` runtime for the final check. A 100-word calibration sample is
  the best way to refine the budget for a new reference voice.
- A source episode shorter than ~40 minutes is combined with 1–2 other current
  popular episodes that share a thesis, until the source pool is ~40–60
  minutes. Do not pad a single short episode into 10 minutes.
- Every run uses a fresh, unused episode. `state/used-episodes.json` is the
  cross-run ledger; never reuse a source id that is already in it.
- A personal voice cloned from **your own** 45–90 second reference recording.
- Burned captions plus a sidecar SRT.
- A `review.md` release sheet that blocks on duration/format problems.
- A YouTube upload receipt (video id, URL, privacy, disclosure state).

## Non-goals

- No avatar, no face, no lip-sync render in this skill. Use
  [`../podcast-avatar-commentary/SKILL.md`](../podcast-avatar-commentary/SKILL.md)
  if you want a talking presenter.
- Do not clone a voice without consent. Use only your own voice, or a voice
  with a signed release kept outside the repository.
- Do not present invented quotes, numbers or episode claims. Trace every claim
  to the transcript, the episode page or a cited public source.
- Do not re-upload a podcast episode or a long excerpt. Commentary is the
  point; clips are short, credited and transformative.
- Do not publish cloned-voice audio without disclosure. Tell the audience, and
  set YouTube's synthetic-media flag.

---

## Repository layout

```text
skills/podcast-youtuber-agent/
  SKILL.md
  config/
    sample-passage.txt       # read this when recording the voice reference
    voice-test.slides.json   # 3-slide smoke test for the voice pipeline
    voice.example.json       # voice-profile shape (real profiles are gitignored)
    youtube.example.json     # upload metadata shape
    pronunciation.zh.json    # TTS-only finance/tech polyphone lexicon
    trending-sources.json    # curated YouTube channels for full episodes
    priority-people.json     # founders/investors/traders/hosts used in ranking
  scripts/
    fetch_popular.py         # PodcastTranscript.ai fetch + used-source ledger
    trending.py              # merge, rank and check transcripts across sources
    people.py                # cited Wikipedia briefs for host/guest
    slides.py                # draft / validate / plan a b-roll slide list
    voice_sample.py          # analyse, trim and register a reference WAV
    chatterbox_worker.py     # batch Chatterbox worker (voice venv)
    narrate.py               # voice synthesis, timing, master.wav, captions
    pronunciation.py         # TTS-only heteronym overrides for finance/tech
    thumbnail.py             # 1280x720 title-card thumbnail from the slide list
    translate.py             # EN -> zh-Hans deck + YouTube metadata via OpenCode
    bilingual.py             # shared visuals + Mandarin primary + optional English upload
    build.py                 # validate -> narrate -> assemble -> optional upload
    youtube_upload.py        # OAuth 2.0 + resumable upload, captions, localizations
    autopilot.py             # queue: select -> editor -> Qwen3 video -> private upload
voices/<name>/               # private: reference.wav, voice.json
state/used-episodes.json     # cross-run ledger: source ids already used
build/<slug>/                # private build artefacts
out/<slug>/final.mp4         # deliverable
```

`voices/`, `build/`, `out/`, OAuth client secrets and tokens are gitignored.
The voice profile is personal data; back it up securely and do not commit it.
`state/used-episodes.json` is intentionally tracked: it prevents the channel
from repeating a source episode on a later run. Do not delete it.

The renderer and card/caption code are shared with
`podcast-avatar-commentary/scripts/assemble.py` and `lib.py`. That is deliberate:
one measured-timeline implementation, one caption renderer.

---

## Dependencies

### Base pipeline

```bash
uv sync
uv sync --extra trending --extra youtube   # research + upload extras
```

FFmpeg/ffprobe with libx264 and AAC are required. On macOS:

```bash
brew install ffmpeg-full
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
```

### Personal voice environment

Chatterbox is MIT-licensed, zero-shot, 0.5B, and runs on Apple Silicon MPS.
Keep it in a **separate** Python 3.11 environment; its PyTorch/torchaudio stack
is large and does not belong in the project venv.

```bash
uv venv --python 3.11 .venv-voice
uv pip install --python .venv-voice/bin/python --upgrade pip
uv pip install --python .venv-voice/bin/python chatterbox-tts 'setuptools<81'
uv pip install --python .venv-voice/bin/python mlx-audio

.venv-voice/bin/python \
  skills/podcast-youtuber-agent/scripts/chatterbox_worker.py --check
.venv-voice/bin/python \
  skills/podcast-youtuber-agent/scripts/qwen3_worker.py --check
```

Qwen3-TTS Base 0.6B is the default now. It uses MLX and the
`mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16` model. The first run downloads the
model; later loads are a few seconds. Chatterbox remains the fallback/alternate.
Qwen3 voice cloning needs the **exact transcript** of the reference recording;
the default is `config/sample-passage.txt`, which is what the sample passage is
for. Pass `--ref-text-file` if your reference uses different text.

`setuptools<81` keeps `pkg_resources`, which `resemble-perth` (Chatterbox's
watermarker) still imports. Without it, the model loads but fails at
`PerthImplicitWatermarker` with `'NoneType' object is not callable`.

The first real synthesis downloads the model weights. If the install fails on
macOS, try installing `s3tokenizer` and the ONNX runtime last, as suggested by
the upstream Chatterbox issues. See
[`https://github.com/resemble-ai/chatterbox`](https://github.com/resemble-ai/chatterbox).

**Licence note.** Chatterbox is MIT. F5-TTS and XTTS-v2 pretrained weights have
non-commercial terms; do not use them for a monetised channel without checking
the current licence. OpenVoice is MIT but its tone-colour clone is a different
quality trade-off. The pipeline now defaults to Qwen3-TTS Base 0.6B on MLX for
near-realtime generation; Chatterbox remains an alternate if its voice matches
better.

If the voice environment is somewhere else, pass
`--voice-python /path/to/python` or set `VOICE_PYTHON`.

`trending` adds `youtube-transcript-api` and the Google client used to read the
curated YouTube channels. If you only use PodcastTranscript.ai, the core
pipeline still works without it.

### Faster personal-voice inference

Chatterbox has an opt-in no-CFG `inference_turbo` path:

```bash
uv run python skills/podcast-youtuber-agent/scripts/narrate.py \
  --slides build/ep01/slides.json --out build/ep01 \
  --voice-profile voices/me --engine chatterbox --turbo
```

In a three-slide test, turbo was about **2× faster** than the standard
CFG path (57 s vs 115 s including model load). It is not the default because
dropping classifier-free guidance can change voice character. Render a short
sample and listen before using it for a full episode. `--no-cpu-fallback`
makes an MPS error fail fast instead of silently dropping to CPU.

For near-real-time production, PyTorch MPS Chatterbox is still the bottleneck.
A quantized MLX/CoreML Chatterbox runtime is the promising next step; benchmark
voice similarity and stability before switching. Do not run FFmpeg/Chromium
assembly concurrently with Chatterbox: CPU contention caused a 15-minute
single-clip stall in testing.

### Draft fallback

`--engine edge` uses `edge-tts` and needs no voice environment. It is for
timing tests and rough cuts only; it does not clone your voice.

---

## Phase 1 — prepare your voice sample

This is the part that determines whether the channel sounds like you. Record
once, carefully, and reuse the same reference for every episode.

### 1.1 What to record

- **Length:** 45–90 seconds of clean speech. 60 seconds is a good target.
  The parser accepts 10 seconds minimum, but short references are less stable.
- **Content:** read [`config/sample-passage.txt`](config/sample-passage.txt).
  It includes statements, questions, numbers, names and varied punctuation.
- **Tone:** the calm, curious tone you want in the videos. Do not perform a
  radio voice, whisper, or rush. The clone copies your prosody, not just your
  timbre.
- **Consistency:** one speaker, one microphone, one room, no music, no TV, no
  notifications, no fan. Put the phone in airplane mode.
- **Mic placement:** 15–20 cm from the mouth, slightly off-axis, with a pop
  filter if you have one. A blanket or a small closet is better than a bare
  room with reverb.
- **Levels:** peaks around −12 to −6 dBFS. Leave headroom; never clip. Do not
  add noise reduction, compression, EQ or reverb before cloning. The script
  trims silence and converts the format, nothing else.
- **Takes:** record three. Pick the one with the least room noise and the most
  natural delivery. A slightly imperfect but honest take clones better than a
  heavily processed one.

### 1.2 Record on macOS

QuickTime Player is enough:

1. **File → New Audio Recording**.
2. Choose the microphone, set the input volume so loud passages stay below 0 dB.
3. Record 60–90 seconds while reading the passage.
4. **File → Export → Audio Only** and save as `voices/me/raw.wav` (or `.m4a`;
   the script converts it).

Or use FFmpeg. List input devices first:

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

The microphone is usually an audio device index such as `:1`. Record:

```bash
mkdir -p voices/me
ffmpeg -f avfoundation -i ":1" -t 90 -ar 48000 -ac 1 \
  voices/me/raw.wav
```

Grant Terminal microphone access in **System Settings → Privacy & Security →
Microphone** if macOS prompts or records silence.

### 1.3 Analyse and register the reference

```bash
uv run python skills/podcast-youtuber-agent/scripts/voice_sample.py \
  analyze voices/me/raw.wav

uv run python skills/podcast-youtuber-agent/scripts/voice_sample.py \
  prepare voices/me/raw.wav \
  --out voices/me \
  --name me \
  --consent self \
  --engine chatterbox \
  --exaggeration 0.5 \
  --cfg-weight 0.5
```

`analyze` reports duration, sample rate, peak/RMS, noise floor, SNR, silence
ratio and clipping. `prepare` trims leading/trailing silence, applies a static
gain to a −3 dBFS peak, converts to 48 kHz mono 24-bit PCM, and writes
`voices/me/voice.json` with the consent record and reference hash.

Target results:

- duration 45–90 s;
- peak around −6 dBFS, no clipped samples;
- noise floor below −50 dBFS;
- SNR above 20–25 dB;
- no long internal pauses (the trimmer only removes the edges).

The profile is required by `narrate.py`; it refuses to proceed without
`consent: "self"` or `"authorized"`.

### 1.4 Test the clone before a full episode

Make a small slide list first:

```bash
uv run python skills/podcast-youtuber-agent/scripts/narrate.py \
  --slides skills/podcast-youtuber-agent/config/voice-test.slides.json \
  --out build/voice-test \
  --voice-profile voices/me \
  --engine qwen3 \
  --ref-text-file skills/podcast-youtuber-agent/config/sample-passage.txt
```

The test deck is short on purpose. Do not render a 15-minute script until the
60-second reference sounds right.

Listen for:

- recognisable timbre and cadence;
- no metallic warble or dropped syllables;
- names and numbers pronounced correctly;
- consistent tone across sentences.

If it sounds unstable, re-record a cleaner reference first. Then try a lower
`--exaggeration` (0.35–0.5), keep `--cfg-weight` around 0.5, and keep the seed
fixed. Do not “fix” a bad reference with heavy processing.

### 1.5 Consent and privacy

`voice.json` records consent. For your own voice use `--consent self`. For
anyone else, use `--consent authorized` and keep the signed release outside
the repo. Never clone a podcast host, guest, public figure or colleague.

---

## Phase 2 — choose the episode and write the script

### 2.1 Fetch and rank fresh candidates

The default source set is **PodcastTranscript.ai plus a curated set of YouTube
channels that publish full interviews**. The YouTube list lives in
[`config/trending-sources.json`](config/trending-sources.json); it covers AI,
startup, technology and markets shows such as Lex Fridman, All-In, a16z, No
Priors, 20VC, Acquired, BG2, Latent Space, Bloomberg, CNBC, The Compound and
Yahoo Finance. Add or remove channels there rather than hard-coding them.

```bash
mkdir -p build/ep01/candidates
uv run python skills/podcast-youtuber-agent/scripts/trending.py list \
  --limit 20 \
  --transcript-check-limit 10 \
  --out build/ep01/candidates/ranked.json
```

`trending.py` merges both sources, drops source ids and near-duplicate titles
from `state/used-episodes.json`, and ranks candidates by:

- **popularity** — YouTube views, normalised across the candidate set, or
  PodcastTranscript list position;
- **recency** — newer episodes receive a higher score;
- **topic fit** — AI, machine learning, semiconductors, startups, founders,
  venture, stocks, markets, earnings, IPOs and trading;
- **people** — priority founders, investors, traders and interviewers from
  [`config/priority-people.json`](config/priority-people.json);
- **authority** — tier-1 specialist channels rank above general news channels;
- **transcript availability** — a verified YouTube transcript gets a bonus.

The score is a shortlisting aid, not an editorial verdict. Read the top 20,
check the guest and the episode page, and pick the strongest story for a
general AI/technology/markets audience. Do not let a high view count override a
thin or repetitive interview.

Useful flags:

- `--skip-youtube` — PodcastTranscript.ai only; useful before OAuth is set up.
- `--skip-podcasttranscript` — curated YouTube channels only.
- `--no-transcript-check` — faster shortlist; transcript status is unknown.
- `--require-transcripts` — strict mode; drops anything not verified.
- `--include-used` — debugging only. Never publish an episode that is already
  in the ledger.

If YouTube auth is missing, the script still returns PodcastTranscript
candidates. If `youtube-transcript-api` is IP-blocked, the candidate is marked
`transcript: false` rather than discarded; verify the transcript another way
(show notes, another provider, or the official episode page) before writing.

### 2.2 Score, select and research the people

**Length policy.** The default commentary is **10–15 minutes and roughly one
quarter (25%) of the source audio**:

- **40–60 minute source:** use one episode; aim for a 10–15 minute commentary.
- **Under ~40 minutes:** a 25% cut would be under 10 minutes, so combine 2–3 of
  the current popular episodes around one shared thesis. The result should
  feel like one argument, not a clip show. Record every source id in the ledger.
- **Over ~60 minutes:** cap the commentary at 15 minutes even though 25% would
  be longer; pick the strongest through-line and cut the rest.

**Never repeat a source.** `trending.py` filters source ids and similar titles
against `state/used-episodes.json` by default. If no unused candidate clears
the editorial bar, stop and report that; do not recycle an old episode just to
publish.

Get the transcript and write the chosen source ids down:

```bash
# PodcastTranscript.ai
uv run python skills/podcast-youtuber-agent/scripts/fetch_popular.py \
  get <id> > build/ep01/source.json

# YouTube
uv run python skills/podcast-youtuber-agent/scripts/trending.py transcript \
  --source youtube --id <video-id> --out build/ep01/source-youtube.json
```

Research the original interviewer and interviewee from public sources, not
just the episode. They are the people being discussed, not the creator's
roles; keep both in the third person. `people.py` gives cited Wikipedia
starting points:

```bash
uv run python skills/podcast-youtuber-agent/scripts/people.py \
  --name "Host Name" --name "Guest Name" \
  --out build/ep01/people.json
```

Verify current role, company, fund or publication, and one reason each person
matters now. If Wikipedia is missing or stale, use the person's company page,
show bio, or a reputable interview. Record the source URL next to every fact.
Do not infer a title from the episode description alone.

Write a **15–25 second setup at the very beginning**: name the original
interviewer and interviewee, their current roles, and one credibility fact or
stake for each. State plainly that this is independent commentary on their
conversation, then move into the hook. Do not use a host-style welcome or imply
that you were part of the episode. Keep the setup factual and short; the
commentary, not the biography, is the reason the video exists.

### 2.3 Write the spoken script


Aim for **1,500–2,250 words at 150 wpm**. One continuous script, no headings,
no bullets, no “first / second / third.” Write for the ear. If the source pool
is only ~40 minutes, stay near the 10–12 minute end; if it is 55–60 minutes,
stay near 14–15 minutes. Qwen3-TTS follows the reference pace: measure a sample,
then use `words / (measured wpm) * 60` as the script budget. A 100-word test
sample is a quick way to calibrate. Record the measured runtime from
`timing.json` and adjust the script, not the estimate. Do not pad to hit a word
count.

Flow:

1. A 15–25 second setup: identify the original interviewer and interviewee,
   their current roles and one credibility fact each, sourced from web research,
   and frame the video as independent commentary. This is not a host intro.
2. A quiet, specific hook: a surprising number, contradiction or personal
   stake. No “hey guys,” no “in today's video.”
3. Three or four core ideas, each followed by the creator's research-backed
   insight, historical parallel, risk or practical implication.
4. A genuine question that survives after the video stops.
5. A low-key close: comments, what they are testing, what to watch next.

The script is the narration. The slide list is the visual layer; do not put
headings or stage directions into the script. The creator is the commentator,
never the podcast host or guest.

---

## Phase 3 — turn the script into b-roll slides

### 3.1 Draft the slide list

```bash
uv run python skills/podcast-youtuber-agent/scripts/slides.py draft \
  --script build/ep01/script.txt \
  --out build/ep01/slides.json \
  --visuals assets/ep01 \
  --title "The AI Story Nobody Is Pricing" \
  --voice-profile voices/me \
  --engine chatterbox \
  --fps 30
```

`--visuals` is optional. If you provide a directory of 16:9 images/videos, the
draft assigns them to the middle slides as `broll`. If you do not, it creates
generated `chart` cards, plus a `title` and an `end` card. That still satisfies
the b-roll-slides format: the visual track is slides, not an avatar.

Recommended visuals:

1. podcast cover and episode page;
2. guest headshot and role;
3. one chart or number that carries the argument;
4. one quote card with attribution and a source link;
5. one short screen recording of the product, paper or demo;
6. one framework/list card for your own insight;
7. an end card with a specific question.

Use 1920×1080 or larger, 16:9. The renderer crops to fill 16:9, so keep faces
and text away from the edges. For short video b-roll, the renderer loops it to
the narration length; keep it silent and short.

### 3.2 Edit the draft

The draft is intentionally mechanical. Replace the heuristic headings and
bullets with the real argument. For example:

```json
{
  "id": "07",
  "kind": "quote",
  "narration": "Here is the line that stuck with me.",
  "quote": "Language is ultimately like a lossy abstraction of the real world.",
  "attribution": "Moritz Baier-Lentz, General Intuition",
  "source": "https://open.spotify.com/episode/...",
  "visual": "assets/ep01/podcast-cover.jpg",
  "transition": "cut"
}
```

Rules:

- `kind` is `broll`, `quote`, `chart`, `title` or `end`. **`avatar` is rejected.**
- `narration` is the exact spoken text, max 340 characters. Split longer beats.
- `broll` needs a `visual` path that exists.
- `quote` needs `quote`, `attribution` and an `http(s)` `source`.
- `chart` needs a `heading` and 1–3 bullets.
- `title` needs `on_screen` (or the top-level title).
- `end` needs a `heading` or `question`; use `next_text` for the CTA.
- Keep the first slide a title and the last an end card.
- 35–60 slides is a good target for 10–15 minutes.

### 3.3 Validate and plan

```bash
uv run python skills/podcast-youtuber-agent/scripts/slides.py \
  validate build/ep01/slides.json --root .

uv run python skills/podcast-youtuber-agent/scripts/slides.py \
  plan build/ep01/slides.json --out build/ep01/plan.md --wpm 150
```

Validation warns when the estimated runtime is outside 10–15 minutes, when
there are no b-roll visuals, or when the slide mix is monotonous. The default
estimate assumes 150 wpm; pass `--wpm` with your measured voice pace (Qwen3 is around 145–155, Chatterbox can be 190–210) when checking the final deck. It errors on
missing visuals, missing quote sources, invalid kinds, duplicate ids and
narration over 340 characters. Fix errors before rendering. The 10–15 minute
window is the default release target, not a suggestion; add or remove source
material rather than filling with recap.

Read `plan.md`. It lists the estimated runtime, slide kinds and upload command.

---

## Phase 4 — synthesise the narration and timeline

```bash
uv run python skills/podcast-youtuber-agent/scripts/narrate.py \
  --slides build/ep01/slides.json \
  --out build/ep01 \
  --voice-profile voices/me \
  --engine qwen3 \
  --ref-text-file skills/podcast-youtuber-agent/config/sample-passage.txt \
  --exaggeration 0.5 \
  --cfg-weight 0.5 \
  --seed 43
```

Outputs:

```text
build/ep01/audio/shot-XX.wav       one clip per slide
build/ep01/audio/narration.json    cache manifest with fingerprints
build/ep01/timing.json             measured duration and exact timeline
build/ep01/master.wav              48 kHz stereo, peak-normalised
build/ep01/captions.srt / .ass
build/ep01/cues.txt
```

Rules:

- Timing is measured with ffprobe, never estimated.
- Lead is 0.6 s on the first slide, 0.25 s thereafter; tail is 0.35 s.
- The timeline is quantised to the video frame grid.
- The cache is keyed by text + engine + voice-profile hash + settings. Editing
  a slide re-synthesises only that slide; `--force` redoes all.
- `--engine edge` is the fallback. It produces a consistent neutral voice but
  not your clone.

For a 12–15 minute video, Chatterbox synthesis is the long pole. Run it once
with the final script; use a 3-slide test before committing to a full episode.

---

## Phase 5 — build the video

The one-command path:

```bash
uv run python skills/podcast-youtuber-agent/scripts/build.py \
  --slides build/ep01/slides.json \
  --out out/ep01/final.mp4 \
  --voice-profile voices/me \
  --engine qwen3 \
  --ref-text-file skills/podcast-youtuber-agent/config/sample-passage.txt
```

`build.py` runs:

1. `slides.py validate`
2. `narrate.py`
3. the shared `assemble.py`
4. if `--upload` is set, `thumbnail.py` (unless `--thumbnail` supplies an
   existing image or `--no-thumbnail` is used), then `youtube_upload.py`

`build.py` forces `--privacy private` unless you pass `unlisted` or `public`
explicitly; a metadata file cannot accidentally publish the video. Direct use
of `youtube_upload.py` still respects a `privacyStatus` in the metadata, so
keep that file private until review.

Optional music bed:

```bash
uv run python skills/podcast-youtuber-agent/scripts/build.py \
  --slides build/ep01/slides.json \
  --out out/ep01/final.mp4 \
  --voice-profile voices/me \
  --music assets/music/bed.mp3 \
  --music-volume 0.05
```

The assembler:

- renders title, chart, quote and end cards at 2560×1440;
- scales/loops b-roll images and videos to each measured shot;
- burns caption overlays and writes a sidecar SRT;
- concatenates segments, attaches `master.wav`, applies
  `loudnorm=I=-14:TP=-1.5:LRA=11`;
- writes `build/ep01/review.md`;
- blocks the build if a segment/final duration is off, if there is a black gap
  over 0.6 s, if the export is not 1080p H.264/AAC, or if an avatar shot slips
  into a b-roll deck.

Render a 1280×720 thumbnail from the title slide's title, subtitle and the
first available still:

```bash
uv run python skills/podcast-youtuber-agent/scripts/thumbnail.py \
  --slides build/ep01/slides.json \
  --out out/ep01/thumbnail.png \
  --root .
```

The thumbnail is a designed title card, not a frame grab. Override
`--title`, `--subtitle`, `--kicker` or `--background` when the cover image is
too busy.

Check the review before uploading:

```bash
sed -n '1,120p' build/ep01/review.md
```

The desired status is `ready for upload`.

### QA checklist

- First 20 seconds contain a specific hook.
- Every factual claim traces to the transcript or a cited source.
- Quotes are exact, attributed and linked.
- Your own insight appears at least twice.
- The ending asks a real question.
- Captions are readable and inside the safe area.
- No line exceeds two lines of 42 characters.
- Names and companies are spelled correctly.
- Audio is intelligible at 1× and 1.5×; no clipping.
- Video is 1920×1080, 30 fps (or 25), H.264 + AAC 48 kHz stereo.
- The deck is actually b-roll/slides; no accidental avatar or black frame.
- AI voice disclosure is in the description and on YouTube's synthetic-media
  flag. The end card can also say “AI voice narration.”

---

## Phase 6 — YouTube upload

### 6.1 One-time Google Cloud setup

1. Create or select a project in the
   [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **YouTube Data API v3**.
3. Configure the **OAuth consent screen**:
   - User type: External.
   - While testing, add your Google account as a test user.
   - Add the scope
     `https://www.googleapis.com/auth/youtube.force-ssl` (video, thumbnail,
     captions). If you only upload the video, the narrower
     `https://www.googleapis.com/auth/youtube.upload` is enough.
4. Create credentials → **OAuth client ID** → application type **Desktop app**.
5. Download the JSON and store it **outside the repo**:

```bash
mkdir -p ~/.config/podcast-youtuber-agent
mv ~/Downloads/client_secret_*.json \
  ~/.config/podcast-youtuber-agent/client_secret.json
chmod 700 ~/.config/podcast-youtuber-agent
chmod 600 ~/.config/podcast-youtuber-agent/client_secret.json
```

Never commit `client_secret.json` or a token. The token file contains a
refresh token and is written with mode 0600. The config directory is personal
data; back it up securely.

### 6.2 Authorize once

```bash
uv sync --extra youtube

uv run python skills/podcast-youtuber-agent/scripts/youtube_upload.py \
  --auth
```

The desktop-app flow uses PKCE, opens the system browser, requests offline
access, and saves a refresh token. It prints the authorized channel. Check it
later with:

```bash
uv run python skills/podcast-youtuber-agent/scripts/youtube_upload.py \
  --check-auth
```

The default scope is `youtube.force-ssl` because the uploader also sets the
thumbnail and captions. Use `--minimal-scope` only for a video-only upload
without extras.

### 6.3 Metadata

Copy the example and edit it:

```bash
cp skills/podcast-youtuber-agent/config/youtube.example.json \
  build/ep01/youtube.json
```

Include:

- a 2–3 sentence summary;
- the original episode title, guest and link;
- a line saying this is independent commentary, not an episode of the original
  podcast;
- sources;
- chapters;
- the AI-voice disclosure;
- sponsor/affiliate disclosures;
- “not financial advice” when relevant.

Frame the title as analysis, commentary or critique. Do not title it as an
interview or as an episode of the source show.

Description example:

```text
Disclosure: This video uses an AI-generated voice clone of the creator. The
script, research and opinions are the creator's own. This is independent
commentary on the original podcast, not an episode of that show; the creator
was not a participant in the interview. The original podcast is credited and
linked above; excerpts are used for commentary and criticism. This is opinion,
not financial advice.
```

The uploader sets `status.containsSyntheticMedia=true` by default. That is the
API equivalent of YouTube's altered/synthetic content disclosure. Keep the
description disclosure too; it is clearer for viewers and survives API changes.
`--no-synthetic-media` exists only for content that genuinely has no synthetic
media; do not use it to hide a cloned voice.

### 6.4 Upload

Start private:

```bash
uv run python skills/podcast-youtuber-agent/scripts/youtube_upload.py \
  --video out/ep01/final.mp4 \
  --metadata build/ep01/youtube.json \
  --thumbnail out/ep01/thumbnail.png \
  --captions build/ep01/captions.srt \
  --privacy private
```

Or run the whole production and upload in one command:

```bash
uv run python skills/podcast-youtuber-agent/scripts/build.py \
  --slides build/ep01/slides.json \
  --out out/ep01/final.mp4 \
  --voice-profile voices/me \
  --engine chatterbox \
  --upload \
  --metadata build/ep01/youtube.json \
  --thumbnail out/ep01/thumbnail.png \
  --privacy private
```

Dry-run metadata without uploading:

```bash
uv run python skills/podcast-youtuber-agent/scripts/youtube_upload.py \
  --video out/ep01/final.mp4 \
  --metadata build/ep01/youtube.json \
  --dry-run
```

Upload extras:

- `--thumbnail path` — JPEG/PNG, 1280×720 or larger. `thumbnail.py` renders a
  title-card version from the slide list.
- `--captions build/ep01/captions.srt` — uploaded as an English caption track
  (`--captions` may be repeated; use `--caption-track zh-Hans=path|中文` for
  explicit language/name pairs).
- `--playlist PLAYLIST_ID` — adds the video to a playlist.
- `--publish-at 2026-11-01T18:00:00Z` — schedules publication. This forces
  `privacyStatus=private` and lets YouTube publish automatically at that time.
- `--privacy unlisted|public` — only after you have reviewed the cut.

The uploader is resumable, retries 429/5xx with bounded exponential backoff,
and writes `youtube-upload.json` next to the video. If the thumbnail, captions
or playlist step fails after the video uploads, the receipt records the warning
instead of discarding the successful upload.

### 6.4a Mandarin pronunciation for finance and technology

Mandarin has many heteronyms, and a TTS model can choose the wrong reading even
when the sentence is otherwise natural. Common investment/tech examples:

| Term | Correct | Common wrong reading | TTS-only override |
| --- | --- | --- | --- |
| 重定价 | chóng dìngjià | zhòng dìngjià | 崇定价 |
| 行业 | hángyè | xíngyè | 航业 |
| 利差 | lìchā | lìchà | 利叉 |
| 杠杆率 | gànggǎnlǜ | gānggǎnlǜ | 杠敢绿 |
| 调用 | diàoyòng | tiáoyòng | 掉用 |
| 看空 | kànkōng | kànkòng | 看跌 |

`narrate.py` applies `config/pronunciation.zh.json` to the **TTS text only**.
Captions, headings, metadata and the English translation keep the original
wording. The build writes `build/ep01/zh/pronunciation.json` so every applied
override is auditable.

Inspect a script before rendering:

```bash
uv run python skills/podcast-youtuber-agent/scripts/pronunciation.py \
  --slides build/ep01/slides.zh.json

uv run python skills/podcast-youtuber-agent/scripts/pronunciation.py \
  --text "央行行长说，重定价和重启不是一回事。"
```

Add a lexicon entry as `[original, spoken, pinyin, note]`. Use a same-sounding
character where possible; use a short paraphrase when a homophone would be
ambiguous. For a one-off name or phrase, put `tts_text` on that slide instead of
changing the shared lexicon:

```json
{
  "id": "07",
  "narration": "重定价是这期节目的核心。",
  "tts_text": "崇定价是这期节目的核心。"
}
```

Use `--no-pronunciation` only for a controlled test. Do not use it for a
published finance/tech video.

### 6.4b Mandarin primary, optional English

The default release is Mandarin with an English translated caption track. The
English master is a local visual/timing reference and is **not uploaded**.
Translate the deck and metadata first, then build and upload the Mandarin
version:

```bash
uv run python skills/podcast-youtuber-agent/scripts/translate.py \
  --slides build/ep01/slides.json \
  --youtube build/ep01/youtube.json \
  --out-dir build/ep01

uv run python skills/podcast-youtuber-agent/scripts/bilingual.py build \
  --slides build/ep01/slides.json \
  --slides-zh build/ep01/slides.zh.json \
  --metadata build/ep01/youtube.json \
  --metadata-zh build/ep01/youtube.zh.json \
  --work build/ep01 \
  --out-dir out/ep01-mandarin \
  --upload
```

`translate.py` uses the same OpenCode model as the editorial writer. It
translates only human-visible fields, preserves shot ids and the whole
`visual`/chart payload, sets `language: "zh-Hans"`, and writes
`slides.zh.json` plus `youtube.zh.json`.

`bilingual.py` reuses the English visual track, synthesises Mandarin with the
same Qwen3 cloned voice, and produces:

```text
out/ep01-bilingual/final.en.mp4
out/ep01-bilingual/final.zh.mp4
out/ep01-bilingual/thumbnail.en.png
out/ep01-bilingual/thumbnail.zh.png
out/ep01-bilingual/bilingual.json
build/ep01/zh/captions.srt                     # Mandarin, Mandarin timings
build/ep01/zh/captions-for-english.srt         # Mandarin, English timings
build/ep01/zh/captions-en-for-zh.srt           # English, Mandarin timings
build/ep01/zh/dub/dub.zh.m4a                   # exact English video length
```

`--upload` defaults to `--upload-languages zh`: the Mandarin master is uploaded
privately, and the English master stays local for reuse. The Mandarin upload
gets Mandarin and English caption tracks plus an `en` localized
title/description. Use `--upload-languages en` only when the user explicitly
asked for English narration, and `--upload-languages both` only for a
deliberate two-video release.

The Mandarin master normally keeps burned-in captions off with
`--no-burn-captions`; the SRT tracks are still uploaded, so viewers select
captions in YouTube instead of seeing duplicate text in every frame.
`--reuse-zh-narration` reuses `work-zh/timing.json` and `master.wav`, which is
useful when only visuals changed. Chapter timestamps are retimed from the
English shot clock to the Mandarin shot clock before upload, so late chapters
stay inside the shorter Chinese video.

`youtube_upload.py` appends a metadata `chapters` list to the description when
the description does not already contain timestamp lines. This makes YouTube
recognise the chapters without a separate Studio step.
`--localizations` on `youtube_upload.py` accepts a JSON map:

```json
{"zh-Hans": {"title": "中文标题", "description": "中文描述"}}
```

**YouTube limitation:** the public Data API can upload videos, captions and
localized metadata, but it has no endpoint for a second audio track. The
default Mandarin upload is the primary audio; enable the channel's auto-dub
setting so YouTube can generate English and other language tracks from it. If
you need an in-player selector immediately, use the generated `dub/dub.zh.m4a`
in **YouTube Studio → Languages → Add language → Dub**. The file is already
time-fitted to `final.en.mp4`. Publishing both complete videos is only for an
explicit two-language request.

`autopilot.py` defaults to Mandarin: it translates the deck, builds the
Mandarin master and uploads only that video. Use `--language en` only when the
user explicitly asks for English narration; use `--language both` (or the
legacy `--bilingual`) to publish both. Mandarin captions use CJK-aware line
wrapping and the system CJK font (STHeiti / Songti on macOS, Noto Sans CJK on
Linux). Do not upload a burned-in Mandarin video that uses an Arial-only font
path.

### 6.5 Quota and platform limits

- `videos.insert` costs about **1,600 quota units**; the default daily quota is
  **10,000 units**, so roughly six uploads per day before other calls.
- API projects that have not completed verification may be restricted to
  private uploads; check the current YouTube API policy in your project.
- Custom thumbnails, scheduling and captions can require channel/account
  eligibility. The script reports those failures as warnings.
- Revoke access with:

```bash
uv run python skills/podcast-youtuber-agent/scripts/youtube_upload.py \
  --revoke
```

### 6.6 Auth troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `access_denied` | account not added as a test user, or consent cancelled | add the account in the OAuth consent screen; retry `--auth` |
| `invalid_grant` | refresh token expired or revoked | delete the token file and run `--auth` again |
| `redirect_uri_mismatch` | OAuth client is not a Desktop app | create a Desktop-app client |
| `403 quotaExceeded` | daily quota exhausted | wait for reset; request more quota if this is recurring |
| uploads always private | unverified API project | complete verification or use the project within policy |
| thumbnail/captions fail | channel eligibility or missing scope | verify the channel; use the default `youtube.force-ssl` scope |
| `youtube.upload` scope only | minimal scope cannot read the channel or set extras | drop `--minimal-scope` |

---

## Fully unattended queue

`autopilot.py` is the unattended coordinator. It picks the highest-ranked fresh
AI/tech/market episode with a transcript, invokes an OpenCode editorial writer
to create `script.txt`, `people.json`, `slides.json` and `youtube.json`, then
builds with Qwen3 and uploads privately.

```bash
nohup caffeinate -dimsu .venv/bin/python \
  skills/podcast-youtuber-agent/scripts/autopilot.py --episodes 1 \
  >> build/autopilot/autopilot.log 2>&1 &
```

For the curated investment/macro feeds, select the RSS source explicitly:

```bash
nohup caffeinate -dimsu .venv/bin/python \
  skills/podcast-youtuber-agent/scripts/autopilot.py \
  --episodes 1 --source investment \
  >> build/autopilot/investment-run.log 2>&1 &
```

It downloads the episode audio and runs local MLX Whisper ASR before writing,
so the first run also downloads the ASR model. Use `--asr-model` to choose a
smaller/faster model.

By default, the queue translates the finished deck, renders Mandarin narration,
and uploads only the private Mandarin video. The English master remains local
as the shared visual/timing reference. The ledger points at the Mandarin
upload. When the channel's YouTube auto-dub setting is on, YouTube can add
English and other language tracks from the Mandarin primary audio.

Use `--language en` only when the user explicitly asks for an English
narration. Use `--language both` / `--bilingual` to publish English and
Mandarin videos; then `--primary-language` chooses the ledger entry. The
translated deck is always validated, and the pronunciation lexicon is applied
before narration.

Stop after the current episode with `touch build/autopilot/STOP`. Uploads are
private by default. Review each private video before publishing. The queue
requires the Qwen3 voice environment, the OpenCode CLI, and enough YouTube
quota; it stops rather than reusing a source if no fresh transcript-backed
candidate clears the filter.

## Autonomous workflow

The agent can run the whole loop non-interactively after the editorial work:

```bash
# 1. Editorial: fetch current business/technology lists with --exclude-used,
#    score fresh candidates, write build/ep01/script.txt, and keep the source
#    ids (combine 2–3 only when a single source would be under 10 minutes).
# 2. Draft the visual layer.
uv run python skills/podcast-youtuber-agent/scripts/slides.py draft \
  --script build/ep01/script.txt --out build/ep01/slides.json \
  --visuals assets/ep01 --title "The AI Story Nobody Is Pricing" \
  --voice-profile voices/me --engine qwen3

# 3. The agent edits slides.json and youtube.json.
# 4. Render a thumbnail, then validate, render and upload private (or schedule).
uv run python skills/podcast-youtuber-agent/scripts/thumbnail.py \
  --slides build/ep01/slides.json --out out/ep01/thumbnail.png --root .
uv run python skills/podcast-youtuber-agent/scripts/build.py \
  --slides build/ep01/slides.json --out out/ep01/final.mp4 \
  --voice-profile voices/me --engine qwen3 \
  --upload --metadata build/ep01/youtube.json \
  --thumbnail out/ep01/thumbnail.png --privacy private
```

After the upload succeeds, record every source id in the ledger:

```bash
uv run python skills/podcast-youtuber-agent/scripts/fetch_popular.py mark \
  --id <source-id> \
  --title "Episode title" \
  --video-id <youtube-video-id> \
  --url https://youtu.be/<youtube-video-id> \
  --note "10–15 minute commentary"
```

If the video combined episodes, repeat `--id` for each source. Do this before
the next run; otherwise the same episode can be selected again.

Use `--publish-at` for scheduled public release, or keep the upload private and
publish deliberately after review. Autonomy is not a reason to skip the
editorial fact-check or the final watch-through.

---

## Slide-list schema

```json
{
  "slug": "ep01-ai-capex",
  "title": "The AI Capex Story Nobody Is Pricing",
  "voice": "me",
  "voice_profile": "voices/me",
  "engine": "chatterbox",
  "fps": 30,
  "format": "broll-slides",
  "shots": [
    {
      "id": "01",
      "kind": "title",
      "narration": "The number everyone quoted this week was not the one that mattered.",
      "on_screen": "The number everyone missed",
      "subtitle": "Independent commentary on the podcast",
      "kicker": "PODCAST COMMENTARY",
      "transition": "cut"
    },
    {
      "id": "02",
      "kind": "broll",
      "narration": "Here is what the headline skipped.",
      "visual": "assets/ep01/episode-page.png",
      "on_screen": "What the headline skipped",
      "transition": "cut"
    },
    {
      "id": "03",
      "kind": "quote",
      "narration": "This is the line that stayed with me.",
      "quote": "Language is ultimately like a lossy abstraction of the real world.",
      "attribution": "Guest Name, Episode Title",
      "source": "https://example.com/episode",
      "visual": "assets/ep01/podcast-cover.jpg",
      "transition": "cut"
    },
    {
      "id": "04",
      "kind": "chart",
      "narration": "Look at where the constraint actually moved.",
      "heading": "The bottleneck moved",
      "bullets": [
        "Demand is still accelerating.",
        "The constraint is now physical, not financial.",
        "The market is pricing the old constraint."
      ],
      "transition": "cut"
    },
    {
      "id": "05",
      "kind": "end",
      "narration": "So here is the question I keep coming back to.",
      "heading": "What would change your mind?",
      "question": "If the bottleneck is physical, what does a rational capex cycle look like from here?",
      "next_text": "AI voice narration. Tell me in the comments.",
      "transition": "cut"
    }
  ]
}
```

Field notes:

- `kind`: `broll` | `quote` | `chart` | `title` | `end`.
- `narration`: exact spoken text, max 340 characters.
- `visual`: required for `broll`; optional background for card kinds.
- `on_screen`: short lower-third or card headline.
- `quote` / `attribution` / `source`: required for quote cards.
- `heading` / `bullets`: required for chart cards (1–3 bullets).
- `next_text`: end-card CTA/disclosure line.
- `fps`: 24, 25 or 30; keep the whole project consistent.
- `format`: `broll-slides`; the assembler uses this to skip avatar checks.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `voice reference not found` | profile not prepared | run `voice_sample.py prepare` |
| `must record consent` | `voice.json` missing consent | re-run `prepare --consent self` |
| Chatterbox import fails | voice venv / Python version | use `.venv-voice` with Python 3.11 and `chatterbox-tts` |
| `PerthImplicitWatermarker` is `None` / `'NoneType' object is not callable` | setuptools too new; `pkg_resources` missing | `uv pip install --python .venv-voice/bin/python 'setuptools<81'` |
| MPS out of memory | model + browser + other apps | close memory-heavy apps; use `--device cpu` for a test |
| voice sounds metallic | poor reference or too much exaggeration | re-record; try `--exaggeration 0.35`; keep the same seed |
| pronunciation is wrong | TTS limitation | spell the name phonetically in that slide, or re-record that line and cache it |
| narration is too fast/slow | Chatterbox pace is reference-driven | use the pace you want in the reference; edge-tts has `--rate` |
| slide validation fails on visual | path relative to repo root | run from the repo root or pass `--root` |
| no b-roll visuals | draft had no `--visuals` | add images/video and re-draft, or use generated cards |
| runtime is short | one source is under ~40 minutes, or script under 1,600 words | combine another current unused episode around one thesis, or add substance; never pad; check the ledger |
| caption overlaps a card | card text near the bottom safe area | keep card text above the lower third; shorten lines |
| YouTube auth loops | wrong OAuth client type or test user | Desktop app client; add account as test user |
| upload always private | unverified API project | complete verification or accept private review |
| thumbnail 403 | channel not eligible | verify the channel; leave the warning |
| token leaked | file copied into git/shell history | revoke with `--revoke`, delete the token, re-auth |

---

## Ethics and legal

- **Consent.** Clone only your own voice, or a voice with a signed release.
- **Disclosure.** Say the narration is AI-generated; set
  `containsSyntheticMedia`; keep the description disclosure.
- **No impersonation.** Do not make a cloned voice say things the real person
  did not say or imply endorsement.
- **Copyright.** Podcast audio/video are third-party works. Use short,
  credited, transformative excerpts. Link the episode. Do not re-upload it.
- **Quotes.** Exact words, attribution, timestamp, link. If unverifiable,
  paraphrase and say so.
- **Privacy.** Voice references, tokens and build artefacts are personal data.
  Keep them out of git and back them up securely.
- **Advice.** Business/tech commentary is opinion. Add “not financial advice”
  when discussing markets or trades.
- **Sponsorship.** Disclose paid placements and affiliate links.

---

## Related skills

- [`../podcast-avatar-commentary/SKILL.md`](../podcast-avatar-commentary/SKILL.md)
  — talking-presenter pipeline, EchoMimic on Apple Silicon, hybrid avatar +
  b-roll. Use that when you want a face; use this skill for a b-roll-only deck.
- [`../rehab-narrated-slideshow/SKILL.md`](../rehab-narrated-slideshow/SKILL.md)
  — the repository's first narrated-slideshow pipeline and clinical review
  conventions.
