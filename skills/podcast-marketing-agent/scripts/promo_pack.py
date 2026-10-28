#!/usr/bin/env python3
"""Create policy-safe cross-platform copy for one commentary video.

This script never posts.  It produces drafts that the owner can edit and publish
from their own accounts, following each platform's self-promotion rules.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--source", default="")
    parser.add_argument("--language", default="zh-Hans")
    parser.add_argument("--communities", default="r/ArtificialIntelligence, r/investing, r/MacroEconomics")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    zh = args.language.lower().startswith(("zh", "cmn", "mandarin"))
    disclosure = (
        "独立评论；我不是原播客的主持人或嘉宾。中文配音，英文可读字幕。"
        if zh else
        "Independent commentary; I was not a participant in the original podcast. AI-assisted narration."
    )
    source_line = f"Source: {args.source}" if args.source else ""
    text = f"""# Promotion pack — {args.title}

> Draft only. Post manually from the owner's accounts. Do not mass-post the same
> link, automate comments, or ignore a community's self-promotion rules.

## Positioning

**Promise:** {args.summary}

**Disclosure:** {disclosure}

**Link:** {args.url}
{source_line}

## Reddit

Suggested communities: {args.communities} (verify each community's current rules).

**Title options**
- The part of this story everyone is measuring wrong
- A framework for the claim behind {args.title}
- What would change my mind about {args.title}

**Body**
{args.summary}

I make independent commentary on podcasts. This video is my analysis, not a
clip dump or an episode of the source show. I am happy to answer questions about
the framework or the counterargument. {disclosure}

[Full commentary]({args.url})

## X / Twitter thread

1. {args.summary}
2. The part I keep coming back to: the headline is not the mechanism. The
   mechanism is the incentive that produced the headline.
3. My counterargument: if the input that matters is permission, trust or
   distribution rather than raw capability, the obvious winner may not be the
   model with the best benchmark.
4. What would change my mind: a measurable shift in the bottleneck. Until then,
   treat the claim as a framework, not a fact.
5. Full breakdown: {args.url}

## LinkedIn

{args.summary}

I reviewed the source conversation as an independent commentator, not as a
participant. The useful question is not "who is right?" but "which constraint
binds first?" That is the test I apply in the video.

{disclosure}

Watch: {args.url}

## WeChat / 公众号 / 视频号

**标题：** {args.title}

{args.summary}

这是独立评论，不是原播客节目。视频为中文配音，提供英文可读字幕；完整分析见视频。{disclosure}

## Hacker News / technical forum

Only post if the video has a genuine engineering or research angle. Lead with
the mechanism, not the video:

> A short analysis of the constraint behind {args.title}: {args.summary}
> Full notes/video: {args.url}

## Source-show / guest outreach

Subject: Independent analysis of your conversation with {args.title}

Hi — I made an independent commentary video on your conversation. I focused on
one mechanism and added a counterargument rather than recapping the episode. If
useful, here is the clip/link: {args.url}

No obligation to share; happy to correct anything I misread.

## Shorts plan

- Cut 3 clips from the strongest 30–60 seconds.
- Hook in the first 1.5 seconds; one idea per clip.
- Add burned captions and a CTA to the full video.
- Post 1–2/day; do not dump all clips at once.
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
