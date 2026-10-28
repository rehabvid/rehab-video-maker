---
name: podcast-marketing-agent
description: Audit a YouTube commentary channel and run a free, policy-safe growth sprint: channel/video audit, packaging fixes, vertical Shorts production and upload, playlist/trailer cleanup, cross-platform copy packs for Reddit/X/LinkedIn/WeChat, outreach drafts, and a 30-day measurement plan. Use when a channel has uploads but few views or subscribers, or when asked about free digital marketing, Shorts, SEO, repurposing, or promotion.
---

# Podcast Marketing Agent

Turn a library of finished commentary videos into a measurement-driven
distribution system. This skill is for **free, policy-safe marketing**. It does
not buy engagement, create fake accounts, mass-DM, auto-comment, or post
unsolicited links.

## What is actually plausible

| Channel | Autonomous? | Best use |
| --- | --- | --- |
| YouTube metadata, playlists, Shorts upload | Yes, with the existing OAuth token | Main discovery loop |
| Shorts/vertical clips | Yes, local render + upload | Fastest cold-start reach |
| Reddit | **No safe auto-post**; draft only | Native posts by the owner, following each subreddit's self-promotion rules |
| X / LinkedIn | Draft; post only with user-provided API credentials or manually | Clip/thread distribution |
| WeChat mini program | **Not recommended** as a growth channel | Build only if there is a real product need |
| WeChat Channels / 公众号 | Manual | Existing Chinese network; not cold-start |
| TikTok / Instagram Reels | Manual or approved API | Reuse the same vertical clips |
| Newsletter/Substack | Draft; publish manually | Own the audience instead of renting reach |
| Podcast/newsletter outreach | Draft only | Guest/source amplification |

No ethical free channel guarantees YouTube monetisation. The threshold is
**1,000 subscribers + 4,000 valid public watch hours in 12 months**, or
**1,000 subscribers + 10 million valid public Shorts views in 90 days**.

## First diagnosis

Run the channel audit:

```bash
.venv/bin/python skills/podcast-marketing-agent/scripts/audit_channel.py \
  --out build/marketing/channel-audit.json
```

The audit reports public/private counts, views, subscribers, upload cadence,
top videos and CJK-vs-Latin title performance. If titles are Chinese-only while
the source podcasts and search intent are English, packaging is usually the
first bottleneck.

Diagnose in this order:

1. **Distribution** – Are videos public and actually being promoted somewhere?
2. **Packaging** – Does the thumbnail/title promise a specific payoff for a
   specific viewer? Test English/bilingual titles for English-language sources.
3. **Retention** – Does the first 15 seconds deliver the promised payoff?
4. **Volume** – Stop uploading faster than the channel can promote and learn.
5. **Niche** – Ten topics in three days gives the algorithm no audience signal.
   Pick one wedge for 30 days (e.g. AI capex/power or macro).
6. **Conversion** – Pinned comment, end screen, playlist, channel trailer.

## 30-day growth sprint

- **Days 1–3: packaging.** Pick the 5 strongest videos. Write one English and
  one bilingual title for each. Create 3 thumbnail concepts. Update titles,
  descriptions, chapters, tags and playlists. Create or refresh the series
  playlist and channel trailer.
- **Days 4–30: Shorts.** Cut 3–5 vertical clips from each strong long video.
  Post 1–2 Shorts/day rather than more long videos. Every Short needs a hook in
  the first 1.5 seconds, burned captions, one idea, and a clear reason to watch
  the full video.
- **Long-form cadence.** 2–3 long videos/week maximum while the channel is
  under 1,000 subscribers. Leave time to promote and iterate.
- **Manual distribution.** Post native value in 3–5 relevant communities per
  week. Do not drop a bare link. Disclose that it is your commentary and answer
  comments.
- **Outreach.** Send 10 source shows/guests a specific clip and a one-paragraph
  note. Do not mass-mail.
- **Measure weekly.** Impressions CTR, average view duration, subscribers per
  1,000 views, and Shorts-to-long conversion. Kill formats below target.

## Shorts workflow

Create a **native vertical** clip with chart/visual, transcript captions and a
background, rather than cropping the 16:9 video:

```bash
.venv/bin/python skills/podcast-marketing-agent/scripts/make_promo_short.py \
  --video out/autopilot/<slug>/final.zh.mp4 \
  --background out/autopilot/<slug>/cover.zh.plate.png \
  --visual build/autopilot/<slug>/zh/visuals/shot-05.mp4 \
  --srt build/autopilot/<slug>/zh/captions.srt \
  --start 0.5 --duration 30 \
  --hook "真正的问题不是模型，而是许可" \
  --cta "完整拆解在频道里" \
  --out build/marketing/shorts/<slug>-01.mp4
```

`make_promo_short.py` builds a native 1080x1920 canvas: a blurred/toned cover
background, an optional chart/DAG visual from `visuals/shot-*.mp4`, transcript
captions from the source SRT, hook, CTA and the creator's original commentary
audio. It does **not** simply crop a slide. If no suitable chart exists, omit
`--visual`; the transcript and background still carry the vertical.

Use the older `make_short.py` only as a fast fallback when no chart/transcript
asset is available. Review every clip before upload; automated selection still
needs editorial judgement. Upload privately first, verify audio/captions and
thumbnail, then publish with `#Shorts` in the title or description.

```bash
.venv/bin/python skills/podcast-youtuber-agent/scripts/youtube_upload.py \
  --video build/marketing/shorts/<clip>.mp4 \
  --metadata build/marketing/shorts/<clip>.json \
  --privacy public \
  --caption-track en=build/marketing/shorts/<clip>.srt'|English' \
  --receipt build/marketing/shorts/<clip>-upload.json
```

WeChat Channels (视频号) has no public personal-account upload API. Produce a
9:16 MP4 and a Chinese title/description/cover pack, then upload manually or
through an enterprise integration the account owner controls. Do not request or
store WeChat passwords or QR sessions.

Do not repost source-podcast audio as the main Shorts content. The clip must be
the creator's commentary, with a distinct argument and a payoff.

## Packaging rules

- A title should state a **specific tension or consequence**, not the source
  episode name.
- For English-language AI/finance sources, test **English or bilingual
  packaging** even when the narration is Mandarin. The audio can stay Mandarin;
  English captions and auto-dub serve the global audience.
- Thumbnails: one focal subject, maximum 4 words, high contrast at phone size.
  No source logos or host faces.
- Description: first two lines contain the promise and source attribution;
  then chapters, disclosure, and sources.
- End screen: one next video + one playlist. Pinned comment: one question, not
  a link dump.
- Every video should sit in one primary series playlist and one secondary
  playlist at most.

## Cross-platform packs

Generate copy rather than posting blindly:

```bash
.venv/bin/python skills/podcast-marketing-agent/scripts/promo_pack.py \
  --title "..." --url "https://youtu.be/..." \
  --summary "..." --language zh-Hans \
  --out build/marketing/promo/<slug>.md
```

Platform rules of thumb:

- **Reddit:** post only where self-promotion is allowed; write a native summary
  and put the link in the body or a comment. Automating this is a ban risk.
- **X:** one concrete claim plus a 30–60s clip; thread the evidence. Use the
  source attribution. Tag guests only when genuinely relevant.
- **LinkedIn:** post the clip natively with a 150–250 word argument; link in the
  comments.
- **Hacker News:** only for a technical/engineering angle; no marketing voice.
- **WeChat:** publish an article/video to an existing audience; a mini program
  does not solve discovery.
- **TikTok/Reels:** label synthetic narration; do not upload watermarked or
  third-party clips.

## Policy guardrails

- No fake accounts, engagement pods, bought views, comment spam, mass DMs or
  unsolicited link drops.
- No copyrighted podcast audio as the primary Short; use short attributed
  quotes only where fair use is defensible.
- AI narration must be disclosed; the commentary must add original analysis.
- Keep uploads private until packaging, captions and thumbnail are verified.
- Do not promise monetisation. Report leading indicators weekly.

## Scripts

- `scripts/audit_channel.py` – Data API audit; no Analytics scope required.
- `scripts/make_short.py` – deterministic 9:16 clip renderer with hook/CTA.
- `scripts/promo_pack.py` – platform-specific copy pack; does not post.

Analytics (impressions, CTR, watch time) needs a token with
`https://www.googleapis.com/auth/yt-analytics.readonly`; the existing upload
token usually lacks it. Re-authorise before making claims about CTR or retention.
