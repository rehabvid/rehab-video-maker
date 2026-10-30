---
name: podcast-content-agent
description: Select a fresh trending podcast episode, research the interviewer and guest as third-person subjects, and produce an independent slide-by-slide commentary transcript with sources. The creator comments on the podcast and never impersonates its host or guest. Content-only: no voice cloning, video rendering or upload. The output is consumed by tech-commentary-slideshow or an optional AI-video skill.
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

## Editorial role and point of view

The video creator is an **independent commentator reviewing the podcast**. The
original host/interviewer and guest/interviewee are **subjects of the video**,
not the creator's roles. The narration must never imply that the creator hosted
the original show, conducted the interview, was a guest, or was present during
the recording.

- Refer to the original host and guest in the third person, by name or as
  “the host” and “the guest.” Keep first person for the creator's analysis,
  opinions and questions.
- Do not use host or participant language such as “my guest,” “joining me,”
  “I sat down with,” “I interviewed,” “welcome back to the show,” or “thank you
  for joining me.”
- Attribute what happened on the podcast explicitly: “As [guest] tells
  [host]…,” “The episode argues…,” or “In the interview….” Do not write as if
  the creator asked the question or supplied the answer.
- Open with a short independent-commentary frame: identify the original host
  and guest, then make clear that this video is your analysis of their
  conversation. Do not imitate the podcast's own intro or outro.
- Titles and descriptions should read as commentary, analysis or critique, not
  as an episode of the original show. Never use “Interview with…” unless the
  creator actually conducted that interview.

## Editorial standard: argue, don't recap

A star commentator is known for a **point of view**, not for covering an
episode in order. Every video needs:

- a cold open (5–10 seconds) with the thesis, tension or number;
- a compact independent-commentary frame (10–15 seconds) naming the host and
  guests — credentials come after the hook, never before it;
- at least half the beats adding the creator's framework, evidence,
  counterpoint, implication or a falsifiable call;
- one recurring question the video keeps answering;
- a close with what the creator is watching next.

For each section, separate: **what the source says → what I think → why it
matters → what would change my mind.** Do not read the episode back to the
viewer.

## Confidence and evidence

- Attribute source claims explicitly: “Alhajji argues…”, “The episode reports…”.
- Use “I verified” only for claims checked against a primary source or
  reputable web research; record the URL in the metadata.
- Add a claim scorecard or a “verified/unverified” label only when confidence
  is very high and the evidence is cited. Otherwise omit the scorecard and
  keep the claim attributed to the episode.
- Never imply that the creator personally interviewed the guest or independently
  confirmed a claim without evidence.
- Prefer primary data (EIA, IEA, OPEC, Eurostat, central banks, company filings)
  over another commentator's summary. If the data is not available, say so.

## Visual language

Every human-visible word in the video must match the **published video
language**:

- Mandarin video → Chinese chart titles, categories, series names, axes,
  units, causal-chain labels and footer/source lines.
- English video → English labels.
- Proper names, tickers, URLs and the original source cover may stay in their
  original language.

Do not reuse English-rendered charts in the Mandarin master. Translate the
`visual` labels in `slides.zh.json` and render the Mandarin visuals from that
deck. Charts need a real source/date line and real values; if the source gives a
range, show the range rather than an invented midpoint.

## Language policy

- Write the source script and `slides.json` in English: that deck is the
  canonical editorial/timing plan and the translation source. The Mandarin
  master renders its own localized charts/DAGs from the translated deck.
- The **default published narration is Mandarin (`zh-Hans`)**. Translate the
  finished English deck and metadata; do not publish the English narration
  unless the user explicitly asks for it.
- English audiences use YouTube auto-dub from the Mandarin primary audio. Keep
  a translated English caption track and localized metadata so they can read
  along.
- Do not set `--language en` or upload an English master merely because the
  source podcast is English.

## Chinese pronunciation

Finance and technology Mandarin is full of heteronyms. The narrator applies
[`../podcast-youtuber-agent/config/pronunciation.zh.json`](../podcast-youtuber-agent/config/pronunciation.zh.json)
to TTS text only, so captions keep the original wording. It covers terms such
as 重定价 (chóng), 行业/央行/行长 (háng), 利差 (chā), 杠杆率 (gàng), 调用
(diào), 看空 (kōng) and 应用 (yìng).

- When translating, use standard mainland finance/tech terminology.
- Do not add pinyin to `narration`; the lexicon and TTS layer handle it.
- For a proper name or a new term that the lexicon misses, add a `tts_text`
  field to that slide with a same-sounding or unambiguous spoken variant.
- Run `python skills/podcast-youtuber-agent/scripts/pronunciation.py --slides
  build/ep01/slides.zh.json` to audit the override list before rendering.

## Length policy

- Default video: **10–15 minutes**.
- Source ratio: roughly **one quarter (25%)** of the source audio, with a
  10-minute floor and 15-minute cap.
- A 40–60 minute episode usually yields one commentary.
- If the episode is under ~40 minutes, combine 2–3 current popular episodes
  around one thesis. Do not pad.
- If the episode is over ~60 minutes, keep the strongest through-line and stop
  at 15 minutes.
- `slides.json` should contain **30–45 beats**. Qwen3-TTS Base 1.7B reads at
  roughly **150 wpm**; a 10–15 minute commentary needs about **1,500–2,250
  words**. Use `slides.py --wpm 150`, then verify with measured timing. Fewer,
  longer-held slides read better than a card every ten seconds.

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

## Apple Podcasts and investment RSS sources

Apple Podcasts has in-app transcripts, but it does **not** provide a public
transcript API. Apple's iTunes Search API can resolve a show to its RSS feed:

```bash
curl -s 'https://itunes.apple.com/search?term=Top%20Traders%20Unplugged&entity=podcast&limit=2'
```

Use the returned `feedUrl` to fetch full episodes. Because the RSS enclosure is
audio, run local ASR (MLX Whisper) before writing the commentary. The curated
investment feeds live in `config/investment-sources.json`:

- Top Traders Unplugged
- Macro Voices
- Invest Like the Best
- The Compound and Friends
- Odd Lots
- Forward Guidance

List the latest episodes:

```bash
uv run python skills/podcast-content-agent/scripts/investment_sources.py \
  list --per-feed 2 --out build/investment.json
```

Transcribe one episode locally (the first run downloads the ASR model):

```bash
uv run python skills/podcast-content-agent/scripts/investment_sources.py \
  transcript --audio-url "<enclosure url>" --out build/ep01/transcript.txt
```

RSS candidates have no provider ranking. Rank them by feed tier, recency and
title/person relevance, and **always transcribe before writing**. Do not treat
the Apple Podcasts app's transcript as an API.

## Research the people

At the beginning of the eventual video, name the original interviewer and
interviewee and give one credibility fact for each. They are the people being
discussed, not the creator's roles; keep both in the third person.

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
  --fps 30 --wpm 150
```

Then edit the deck by hand. Each `narration` is what the independent
commentator says; each slide should be one idea. The original host and guest
remain third-person subjects and never become the creator's role.

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
  validate build/ep01/slides.json --root . --wpm 150

uv run python skills/podcast-content-agent/scripts/slides.py \
  plan build/ep01/slides.json --out build/ep01/plan.md --wpm 150
```

## Script shape

1. A 5–10 second cold open: the thesis, number, contradiction or stake.
2. A 10–15 second independent-commentary frame: identify the original
   host/interviewer and guest, give their current roles and one credibility fact
   each, and state that this is independent commentary on their conversation.
   Credentials never come before the hook.
3. Three or four core ideas, each followed by the creator's analysis, risk or
   practical implication. At least half the beats must add something beyond
   recap.
4. A real question that survives the video, plus one falsifiable “what I’m
   watching” call when confidence is high.
5. A low-key close.

No headings, no bullet reading, no “hey guys,” no invented quotes or numbers.
The slide deck is the visual layer; do not put stage directions in the
narration. The creator is the commentator, never the podcast host or guest.

## Handoff

Deliver:

- `build/ep01/slides.json` — one narration beat per slide;
- `build/ep01/source.json` — transcript and episode metadata;
- `build/ep01/people.json` — cited host/guest briefs;
- `build/ep01/plan.md` — estimated runtime and slide list.

For the default Mandarin release, translate the deck and metadata, then build
with the bilingual/Mandarin path (English remains a local timing/reference cut
and is not uploaded; the Mandarin video renders its own Chinese visuals):

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
  --work build/ep01 --out-dir out/ep01-mandarin --upload
```

For an explicit English request, build `slides.json` directly with
`tech-commentary-slideshow/scripts/build.py`. For a talking avatar instead, use
`podcast-avatar-commentary`; for a b-roll-only legacy render, use
`podcast-youtuber-agent`.
