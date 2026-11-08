# Native, spoken Mandarin commentary

The Chinese commentary is written **from the source transcript**, not translated
from the English deck. Translation is what produces 翻译体: English sentence
shapes, long attributive `的` chains, and noun-heavy calques.

This note records the rules the writer prompt follows and the gate that checks
the result.

## What makes Chinese sound translated

Research on 翻译腔 / 欧化中文 points at four habits:

1. **形合 instead of 意合** — English links clauses with `because / so /
   although / and / while`; Chinese normally lets word order and commas carry
   the relation. Paired connectors (`因为……所以……`, `不仅……而且……`) are the
   clearest tell.
2. **Long attributive phrases** — `一个被市场反复讨论、但始终没有结论的问题`
   is written Chinese. Speech splits it: `这个问题，市场讨论了很久，一直没结论。`
3. **Noun-heavy calques** — `进行讨论`, `做出判断`, `实现增长`, `产生影响`,
   `对于……来说`, `通过……`, `随着……`, `被认为……`.
4. **Written scaffolding** — `首先 / 其次 / 最后`, `综上所述`, `值得一提的是`,
   `值得注意的是`, `本文`, `我们将会看到`.
5. **Compressed English coverage verbs** — `partner covering infrastructure`
   becomes `合伙人，看基础设施`. Chinese needs a real predicate and object:
   `负责基础设施领域的投资`, `主要看基础设施赛道`, or `关注基础设施方向`.
   `看项目 / 看公司` is normal VC shorthand; a bare `看 + 大领域` is not.

Two more from spoken-language research:

- Spoken Chinese is **topic-first** (`这事儿，……`; `钱的问题，……`) and tolerates
  ellipsis, self-repair, and afterthoughts.
- It is **chunked by breath**, not by clause. A sentence that cannot be said in
  one breath is a written sentence.

## Writer rules (enforced in the prompt)

- Mean 14–20 characters per sentence; split anything over 30; hard-fail over 38.
- One idea per sentence. Prefer a full stop over a relative clause.
- End a passage on a short 4–10 character beat: `钱从哪来。` `谁来兜底。`
  `越拖越贵。`
- Ask and answer a question every 300–500 characters.
- 4–8 spoken signposts per video: `说白了`, `你看`, `问题是`, `关键是`,
  `换句话说`, `反过来`, `说到底`.
- 3–6 sentence-final particles per video (`啊/呢/吧/嘛`), not one per sentence.
- 3–6 idioms or four-character beats, placed on turns and conclusions.
- Verbs over nouns: `进行讨论 → 聊`, `做出判断 → 判断`, `实现增长 → 涨`.
- Do not compress `covers / focuses on / leads / backs` into `看 + 大领域`.
  Write `合伙人，负责基础设施领域的投资` or `主要看基础设施赛道`, not
  `合伙人，看基础设施`. `看项目 / 看公司` remains fine.
- Make abstractions physical: `流动性问题 → 想卖，卖不掉`.
- Mainland forms only: 视频、芯片、数据中心、网络、软件、硬件、营销、屏幕、
  信息、数字、链接、设置、支持、计划、检查.
- Never put a single character in quotes (`值得“查”`); write the full word
  (`值得检查`).

## The gate

`mandarin.py` runs `mandarin_style.py` on the generated deck. It writes
`mandarin.style.json` next to the deck and reports a grade.

Hard failures trigger one rewrite with a correction brief:

- Taiwan/HK word forms
- single-character quotes
- English coverage calques such as `合伙人，看基础设施` / `看AI`
- sentences over 38 characters, or more than 25% over 30
- (with `--style-strict`) a grade-C deck

Warnings do not block, but they are recorded:

- no/few sentence-final particles, or too many
- no rhetorical questions
- `的` density over 5.5%
- connector clusters
- formal/calque phrases
- fewer than two idioms

Run it on any existing deck:

```bash
.venv/bin/python skills/podcast-youtuber-agent/scripts/mandarin_style.py \
  build/autopilot/<episode>/slides.zh.json
```

Example output:

```
grade B (79/100)  2823 字 / 173 句
句长 mean 16.3 median 14 p90 28 max 42 长句 6%
“的” 3.2%  语气词 0 设问 1  成语 2 连接词 13
[hard] 3 句超过 38 字，一口气说不完
[warn] 几乎没有语气词（啊/呢/吧/嘛），口播会显得像念稿
```

## References

- 维基百科：翻译腔 / 欧化中文 — 形合与意合、话题优先、英文句形照搬。
- 维基百科：口语 — 口语与书面语的差别、口语化。
- 维基百科：汉语欧化 — 长定语、被动句、连接词滥用。
