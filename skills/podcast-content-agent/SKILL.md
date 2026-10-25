---
name: podcast-content-agent
description: Select a fresh trending podcast episode, research the interviewer and guest, and produce a slide-by-slide commentary transcript with sources. Content-only: no voice cloning, video rendering or upload. The output is consumed by tech-commentary-slideshow or an optional AI-video skill.
---

# Podcast Content Agent

This skill owns **truth, selection and wording**. It does not render video.

Input: a fresh Business/Technology podcast episode.
Output: a `slides.json` deck with one narration beat per slide, plus source and
people research. The preferred consumer is
[`../tech-commentary-slideshow/SKILL.md`](../tech-commentary-slideshow/SKILL.md).

## Why the split

| Layer | Skill | Responsibility |
| --- | --- | --- |
| Content | this skill | trending selection, transcript, people, claims, slide-by-slide narration |
| Technical visuals | `tech-commentary-slideshow` | charts, diagrams, SVG, DAG/PetriNet, MP4 |
| Optional AI video | `podcast-avatar-commentary` | talking presenter; heavy, use sparingly |

The content scripts are self-contained in `scripts/`. The legacy end-to-end
skill keeps a copy for its old pipeline; change the content skill first.

## Length policy

- Default video: **10–15 minutes**.
- Source ratio: roughly **one quarter (25%)** of the source audio, with a
  10-minute floor and 15-minute cap.
- A 40–60 minute episode usually yields one commentary.
- If the episode is under ~40 minutes, combine 2–3 current popular episodes
  around one thesis. Do not pad.
- If the episode is over ~60 minutes, keep the strongest through-line and stop
  at 15 minutes.
- `slides.json` should contain **35–60 beats**. Qwen3-TTS Base 0.6B reads at
  roughly **160 wpm**; a 10–15 minute commentary needs about **1,600–2,400
  words**. Use `slides.py --wpm 160`, then verify with measured timing.

## Freshness and no repeats

Every run must fetch current lists and filter `state/used-episodes.json`.
Never reuse a source episode, even if it is still trending.

```bash
mkdir -p build/ep01/candidates
uv run python skills/podcast-content-agent/scripts/trending.py list \
  --limit 20 --transcript-check-limit 10 \
  --out build/ep01/candidates/ranked.json
```

The ranker merges PodcastTranscript.ai with curated AI/startup/technology/markets
YouTube channels, checks transcripts, and scores popularity, recency, topic fit,
priority people and channel authority. Use `--skip-youtube` if OAuth is not
configured.

After publishing, record every source id:

```bash
uv run python skills/podcast-content-agent/scripts/fetch_popular.py mark \
  --id <source-id> --title "Episode title" \
  --video-id <youtube-video-id> --url https://youtu.be/<youtube-video-id>
```

Repeat `--id` for a combined episode.

## Research the people

At the beginning of the eventual video, name the interviewer and interviewee
and give one credibility fact for each.

```bash
uv run python skills/podcast-content-agent/scripts/people.py \
  --name "Host Name" --name "Guest Name" \
  --out build/ep01/people.json
```

Wikipedia is a starting point. Verify current role, company/fund/publication and
the reason they matter now with a company page, show bio or reputable
interview. Record source URLs next to the facts.

## Fetch the transcript

```bash
# PodcastTranscript.ai
uv run python skills/podcast-content-agent/scripts/fetch_popular.py \
  get <id> > build/ep01/source.json

# YouTube
uv run python skills/podcast-content-agent/scripts/trending.py transcript \
  --source youtube --id <video-id> --out build/ep01/source-youtube.json
```

Read enough of the transcript to verify the guest's role, 2–3 key claims and
one or two short quotable lines with timestamps. Do not rely only on the
provider summary.

## Write the slide-by-slide transcript

Create `build/ep01/script.txt` as continuous spoken prose. Then split it into
beats:

```bash
uv run python skills/podcast-content-agent/scripts/slides.py draft \
  --script build/ep01/script.txt \
  --out build/ep01/slides.json \
  --title "Episode title" \
  --voice-profile voices/me \
  --engine qwen3 \
  --fps 30 --wpm 160
```

Then edit the deck by hand. Each `narration` is what the narrator says; each
slide should be one idea.

For a technical visual, add an explicit hint and real data:

```json
{
  "id": "07",
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
```

The visual-layer skill also accepts `dag`, `petrinet`, `diagram` and `svg`
hints. If there is no defensible data, omit the hint; the planner will use a
text card instead.

Validate and plan:

```bash
uv run python skills/podcast-content-agent/scripts/slides.py \
  validate build/ep01/slides.json --root . --wpm 160

uv run python skills/podcast-content-agent/scripts/slides.py \
  plan build/ep01/slides.json --out build/ep01/plan.md --wpm 160
```

## Script shape

1. 15–25 second who-is-who intro: interviewer, interviewee, current roles and
   one credibility fact each.
2. A specific hook: number, contradiction or stake.
3. Three or four core ideas, each followed by your own analysis, risk or
   practical implication.
4. A real question that survives the video.
5. A low-key close.

No headings, no bullet reading, no “hey guys,” no invented quotes or numbers.
The slide deck is the visual layer; do not put stage directions in the
narration.

## Handoff

Deliver:

- `build/ep01/slides.json` — one narration beat per slide;
- `build/ep01/source.json` — transcript and episode metadata;
- `build/ep01/people.json` — cited host/guest briefs;
- `build/ep01/plan.md` — estimated runtime and slide list.

Then run:

```bash
uv run python skills/tech-commentary-slideshow/scripts/build.py \
  --slides build/ep01/slides.json \
  --out out/ep01/final.mp4 \
  --voice-profile voices/me
```

For a talking avatar instead, use `podcast-avatar-commentary`; for a
b-roll-only legacy render, use `podcast-youtuber-agent`.
