#!/usr/bin/env python3
"""Measure how spoken / mainland a Mandarin commentary deck reads.

The writer prompt is the main tool; this module is the smoke alarm.  It looks
for the specific habits that make Chinese commentary sound translated or
written-to-be-read:

* 形合 overuse: chains of 因为/所以/但是/并且/同时,
* long attributive ``的`` chains and sentences that cannot be said in one breath,
* noun-heavy calques such as 进行/实现/对于/通过/被认为,
* Taiwan word forms (影片/晶片/资料中心/透过 ...),
* single-character shorthand inside quotes (值得“查”),
* no sentence-final particles at all, or too many,
* no four-character beats / idioms.

Run directly on a deck for a report::

    python mandarin_style.py slides.zh.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

CJK = re.compile(r"[\u3400-\u9fff]")
SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")

# Word forms that mark Taiwan / HK copy in mainland finance videos.
TAIWAN_FORMS = {
    "影片": "视频",
    "晶片": "芯片",
    "资料中心": "数据中心",
    "透过": "通过",
    "网路": "网络",
    "软体": "软件",
    "硬体": "硬件",
    "行销": "营销",
    "萤幕": "屏幕",
    "资讯": "信息",
    "数位": "数字",
    "计画": "计划",
}

# Written / translationese scaffolding.  Warnings, not bans: one or two can be
# natural, but a cluster is the tell.
FORMAL_PHRASES = [
    "进行", "使得", "对于", "关于", "通过", "由于", "随着",
    "与此同时", "综上所述", "在很大程度上", "值得一提的是",
    "值得注意的是", "被认为", "具有重要", "起到了", "从某种意义上",
    "在……方面", "在…方面",
]

# English-shaped patterns that survive translation.
CALQUES = [
    (r"对于[^。，]{1,12}来说", "对……来说"),
    (r"在[^。，]{1,12}的背景下", "在……的背景下"),
    (r"起到[了]?[^。，]{0,8}作用", "起了……作用"),
    (r"被认为是[^。，]{0,12}的", "大家觉得/算是"),
    (r"被[^。，]{1,8}所", "被……"),
]

# English “partner covering infrastructure” compresses into Chinese
# “合伙人，看基础设施”.  “看项目/看公司” is normal VC shorthand, but a bare
# “看 + 大领域” leaves the verb without a real object.  Require 赛道/领域/方向,
# or use 负责/关注/投.
COVERAGE_CALQUES = [
    (
        r"(?<![看])"
        r"(?:(?:合伙人|董事|总经理|负责人|投资人|分析师|主持人)[，,]\s*)?"
        r"看(?:基础设施|人工智能|AI|半导体|芯片|云计算|软件|硬件|消费|金融|医疗|科技|宏观)"
        r"(?=[，。；、]|$)",
        "看+大领域（补赛道/领域/方向或改负责）",
    ),
]

# A compact idiom / four-character beat list.  Not exhaustive: it is a floor,
# not a vocabulary test.  Four-character phrases that are not idioms still help
# rhythm, so the prompt asks for both.
IDIOMS = {
    "刻舟求剑", "饮鸩止渴", "寅吃卯粮", "拆东补西", "竭泽而渔", "杀鸡取卵",
    "本末倒置", "舍本逐末", "缘木求鱼", "南辕北辙", "掩耳盗铃", "自欺欺人",
    "骑虎难下", "进退两难", "左右为难", "捉襟见肘", "入不敷出", "量入为出",
    "未雨绸缪", "亡羊补牢", "锦上添花", "雪中送炭", "火上浇油", "釜底抽薪",
    "扬汤止沸", "抱薪救火", "水涨船高", "水落石出", "一叶知秋", "见微知著",
    "按图索骥", "削足适履", "邯郸学步", "东施效颦", "买椟还珠", "画饼充饥",
    "望梅止渴", "空中楼阁", "海市蜃楼", "镜花水月", "昙花一现", "过眼云烟",
    "大势所趋", "势不可挡", "循序渐进", "拔苗助长", "欲速不达", "厚积薄发",
    "开源节流", "精打细算", "居高不下", "每况愈下", "雪上加霜", "转危为安",
    "化险为夷", "绝处逢生", "柳暗花明", "水到渠成", "顺水推舟", "因势利导",
    "一厢情愿", "自说自话", "自圆其说", "前后矛盾", "漏洞百出", "破绽百出",
    "真金白银", "纸上谈兵", "坐而论道", "雷声大雨点小", "换汤不换药",
    "新瓶旧酒", "旧瓶新酒", "羊毛出在羊身上", "天下没有免费午餐",
}

SPEECH_MARKERS = [
    "其实", "你看", "说白了", "问题是", "关键是", "结果呢", "这事儿",
    "换句话说", "我跟你讲", "什么意思", "你想想", "先说", "再说",
    "更直白一点", "反过来", "到头来", "说到底", "说穿了",
]

PARTICLES = "啊呢吧嘛呗哦呀哈"
CONNECTORS = ["因为", "所以", "但是", "然而", "因此", "并且", "而且", "同时", "于是", "不过"]

LONG_SENTENCE = 30
VERY_LONG_SENTENCE = 38


def _char_len(text: str) -> int:
    return len(CJK.findall(text))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if _char_len(s) >= 2]


def deck_text(deck: dict) -> str:
    return "\n".join(str(s.get("narration") or "") for s in deck.get("shots") or [])


def analyze_text(text: str, *, min_chars: int = 600) -> dict:
    chars = _char_len(text)
    sentences = _sentences(text)
    lengths = [_char_len(s) for s in sentences]
    long_sents = [s for s in sentences if _char_len(s) > LONG_SENTENCE]
    very_long = [s for s in sentences if _char_len(s) > VERY_LONG_SENTENCE]
    long_ratio = len(long_sents) / len(sentences) if sentences else 0.0

    particles = re.findall(f"[{PARTICLES}]", text)
    particle_per_1k = len(particles) / chars * 1000 if chars else 0.0
    connectors = [c for c in CONNECTORS if c in text]
    connector_hits = sum(text.count(c) for c in connectors)
    de_count = text.count("的")
    de_ratio = de_count / chars if chars else 0.0

    taiwan_hits = {w: text.count(w) for w in TAIWAN_FORMS if text.count(w)}
    formal_hits = {w: text.count(w) for w in FORMAL_PHRASES if text.count(w)}
    calque_hits: dict[str, int] = {}
    calque_examples: list[str] = []
    for pattern, label in CALQUES:
        found = re.findall(pattern, text)
        if found:
            calque_hits[label] = calque_hits.get(label, 0) + len(found)
            calque_examples.extend(found[:2])

    coverage_hits: dict[str, int] = {}
    coverage_examples: list[str] = []
    for pattern, label in COVERAGE_CALQUES:
        found = re.findall(pattern, text)
        if found:
            coverage_hits[label] = coverage_hits.get(label, 0) + len(found)
            coverage_examples.extend(found[:2])

    quotes = re.findall(r"[“\"']([\u3400-\u9fff])[”\"']", text)
    idiom_hits = {w: text.count(w) for w in IDIOMS if text.count(w)}
    markers = {w: text.count(w) for w in SPEECH_MARKERS if text.count(w)}
    questions = text.count("？") + text.count("?")

    issues: list[dict] = []
    hard: list[str] = []

    def issue(level: str, code: str, message: str, examples: list[str] | None = None) -> None:
        issues.append({"level": level, "code": code, "message": message,
                       "examples": examples or []})

    if taiwan_hits:
        hard.append("taiwan-forms")
        issue("hard", "taiwan-forms",
              "台湾/港台词形：" + "、".join(f"{k}→{TAIWAN_FORMS[k]}" for k in taiwan_hits),
              [s for s in sentences if any(w in s for w in taiwan_hits)][:2])
    if quotes:
        hard.append("single-char-quotes")
        issue("hard", "single-char-quotes",
              "引号里只有单字：" + "、".join(sorted(set(quotes))),
              [s for s in sentences if re.search(r"[“\"'][\u3400-\u9fff][”\"']", s)][:2])
    if coverage_hits:
        hard.append("coverage-calque")
        issue("hard", "coverage-calque",
              "英文 covers/focuses on 被压成“看+大领域”："
              + "、".join(coverage_hits),
              coverage_examples[:2])
    if very_long:
        hard.append("very-long-sentences")
        issue("hard", "very-long-sentences",
              f"{len(very_long)} 句超过 {VERY_LONG_SENTENCE} 字，一口气说不完",
              sorted(very_long, key=_char_len, reverse=True)[:3])
    elif long_ratio > 0.25:
        hard.append("long-sentence-ratio")
        issue("hard", "long-sentence-ratio",
              f"{long_ratio:.0%} 的句子超过 {LONG_SENTENCE} 字（目标 <15%）",
              sorted(long_sents, key=_char_len, reverse=True)[:3])

    serious_formal: dict[str, int] = {}
    if chars >= min_chars:
        if idiom_hits and sum(idiom_hits.values()) > 8:
            issue("warn", "too-many-idioms",
                  f"成语 {sum(idiom_hits.values())} 次，偏多；3–6 次即可", [])
        elif len(idiom_hits) < 2:
            issue("warn", "few-idioms",
                  "成语/四字格少于 2 个，缺少落点节奏", [])
        if particle_per_1k > 9:
            issue("warn", "too-many-particles",
                  f"语气词 {len(particles)} 个（{particle_per_1k:.1f}/千字），偏多；3–6 个全片即可", [])
        elif particle_per_1k < 0.8:
            issue("warn", "no-particles",
                  "几乎没有语气词（啊/呢/吧/嘛），口播会显得像念稿", [])
        if questions < 2:
            issue("warn", "no-questions",
                  "没有设问/自答，缺少口语的推进感", [])
        if de_ratio > 0.055:
            issue("warn", "de-heavy",
                  f"“的”占比 {de_ratio:.1%}，长定语偏多（目标 <5%）", [])
        if connector_hits > max(4, chars / 220):
            issue("warn", "connector-heavy",
                  f"连接词 {connector_hits} 次，句子关系太靠虚词，试着用语序和停顿",
                  [s for s in sentences if sum(s.count(c) for c in connectors) >= 2][:2])
        serious_formal = {k: v for k, v in formal_hits.items() if v >= 2}
        if sum(serious_formal.values()) >= 4:
            issue("warn", "formal-calques",
                  "书面/翻译腔词：" + "、".join(f"{k}×{v}" for k, v in serious_formal.items()),
                  [s for s in sentences if any(k in s for k in serious_formal)][:2])
        if calque_hits:
            issue("warn", "calque-shapes",
                  "英式句形：" + "、".join(calque_hits),
                  calque_examples[:2])
        if (len(markers) < 2 and chars >= 1200) and particle_per_1k < 4:
            issue("warn", "few-speech-markers",
                  "口头路标太少；适当用“说白了/问题是/换句话说”把话接住", [])

    mean_len = statistics.mean(lengths) if lengths else 0.0
    if mean_len > 23 and chars >= min_chars:
        issue("warn", "long-average",
              f"平均句长 {mean_len:.1f} 字（目标 14–20）", [])

    score = 100
    score -= 8 * len(taiwan_hits)
    score -= 5 * len(set(quotes))
    score -= 12 if very_long else (8 if long_ratio > 0.25 else 0)
    score -= 3 * max(0, sum(serious_formal.values()) - 3)
    score -= 5 if calque_hits else 0
    score -= 8 if coverage_hits else 0
    score -= 5 if de_ratio > 0.055 else 0
    score -= 5 if particle_per_1k > 9 else 0
    score -= 5 if (chars >= min_chars and particle_per_1k < 0.8) else 0
    score -= 4 if (chars >= min_chars and len(idiom_hits) < 2) else 0
    score -= 4 if (chars >= min_chars and questions < 2) else 0
    score = max(0, min(100, score))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C"

    return {
        "chars": chars,
        "sentences": len(sentences),
        "mean_sentence": round(mean_len, 1),
        "median_sentence": statistics.median(lengths) if lengths else 0,
        "p90_sentence": sorted(lengths)[int(len(lengths) * 0.9)] if lengths else 0,
        "max_sentence": max(lengths) if lengths else 0,
        "long_ratio": round(long_ratio, 3),
        "de_ratio": round(de_ratio, 4),
        "particles": len(particles),
        "particle_per_1k": round(particle_per_1k, 2),
        "questions": questions,
        "connectors": connector_hits,
        "idioms": idiom_hits,
        "idiom_count": sum(idiom_hits.values()),
        "markers": markers,
        "taiwan_hits": taiwan_hits,
        "formal_hits": formal_hits,
        "calque_hits": calque_hits,
        "coverage_hits": coverage_hits,
        "single_char_quotes": sorted(set(quotes)),
        "score": score,
        "grade": grade,
        "hard": sorted(set(hard)),
        "issues": issues,
    }


def analyze(deck: dict, **kwargs) -> dict:
    return analyze_text(deck_text(deck), **kwargs)


def feedback(report: dict, limit: int = 6) -> str:
    """A short correction brief for the writer's next attempt."""
    lines: list[str] = []
    for item in report.get("issues") or []:
        if len(lines) >= limit:
            break
        if item["level"] not in {"hard", "warn"}:
            continue
        line = f"- {item['message']}"
        examples = [e.strip() for e in item.get("examples") or [] if e.strip()]
        if examples:
            line += "；例：" + " / ".join(examples[:2])
        lines.append(line)
    if not lines:
        return ""
    return ("上一稿没有通过口语检查。请保留事实、数字和结构，只改 narration 的写法，"
            "把下面的问题逐条改掉：\n" + "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck", help="slides.zh.json")
    parser.add_argument("--json", action="store_true", help="print the full report")
    parser.add_argument("--min-chars", type=int, default=600)
    args = parser.parse_args(argv)

    deck = json.loads(Path(args.deck).read_text())
    report = analyze(deck, min_chars=args.min_chars)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"grade {report['grade']} ({report['score']}/100)  "
          f"{report['chars']} 字 / {report['sentences']} 句")
    print(f"句长 mean {report['mean_sentence']} median {report['median_sentence']} "
          f"p90 {report['p90_sentence']} max {report['max_sentence']} "
          f"长句 {report['long_ratio']:.0%}")
    print(f"“的” {report['de_ratio']:.1%}  语气词 {report['particles']} "
          f"设问 {report['questions']}  成语 {report['idiom_count']} "
          f"连接词 {report['connectors']}")
    for item in report["issues"]:
        print(f"[{item['level']}] {item['message']}")
        for ex in item["examples"][:2]:
            print(f"    {ex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
