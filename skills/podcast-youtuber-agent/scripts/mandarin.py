#!/usr/bin/env python3
"""Write the Mandarin deck natively from the source transcript.

Translation keeps English sentence shapes, which reads as 翻译体.  This agent
instead reads the original podcast transcript, uses the English commentary only
as a structural/argument reference, and writes each Mandarin shot from scratch
in a mainland conversational register.

Outputs ``slides.zh.json`` and ``youtube.zh.json`` next to the English deck,
preserving ids, kinds, visual numbers and URLs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mandarin_style  # noqa: E402

SKIP_TRANSCRIPT_KEYS = {"source", "audio_url", "image", "url", "id"}


def _load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _transcript(path: Path) -> str:
    if path.suffix == ".txt":
        return path.read_text()
    data = _load(path)
    node = data.get("transcription") if isinstance(data.get("transcription"), dict) else data
    for key in ("transcript", "text", "content"):
        value = node.get(key) if isinstance(node, dict) else None
        if value:
            return str(value)
    # a plain transcript.txt
    if path.suffix == ".txt":
        return path.read_text()
    raise ValueError(f"no transcript found in {path}")


def _prompt(slides: Path, youtube: Path, source: Path, out_slides: Path,
            out_youtube: Path, feedback: str = "") -> str:
    correction = f"\n{feedback}\n" if feedback else ""
    return f"""你是一位常驻中国大陆的中文财经/科技评论作者，母语中文，长期给中文观众讲
AI、投资与宏观。现在要为一条中文口播视频写稿。

输入：
- 原始播客转录：{source}
- 英文评论稿（只作为论点、结构、作者观点的参考，不要逐句翻译）：{slides}
- 英文 YouTube 元数据：{youtube}

输出两个 UTF-8 JSON 文件：
1. {out_slides}
2. {out_youtube}

核心要求：**不要翻译英文稿，用中文从头写。** 每一页都先想“一个中文作者会怎么
把这件事讲给朋友听”，再写口播；英文稿只用来确认论点、事实、作者补充和先后顺序。

写作风格（重点，按这个来）：
听众是下班后刷视频的普通人，不是审稿人。你要像坐在他对面，把一件事讲清楚。

1) 句子：一句一个意思
- 平均 14–20 字；超过 30 字必须拆；超过 38 字一律不合格。
- 长定语拆成两句。反例：“一个被市场反复讨论、但始终没有结论的问题”；
  正例：“这个问题，市场讨论了很久，一直没结论。”
- 宁可多一个句号，不要多一个从句；能逗号断开就断开。
- 每段结尾尽量用短句收住（4–10 字），让判断落地：“钱从哪来。”“谁来兜底。”“越拖越贵。”

2) 口语的骨架
- 话题先行：“这事儿，……”“这个判断，……”“钱的问题，……”。
- 设问自答，每 300–500 字一次：“那问题出在哪？出在……”“为什么？因为……”。
- 口头路标全片 4–8 次，不要每段都用：“说白了”“你看”“问题是”“关键是”
  “换句话说”“反过来”“说到底”。
- 语气词全片 3–6 个，放在转折或收尾：“呢/吧/嘛/啊”。不要每句都加。
- 直接称呼“你”，不要“您”；可以用“我们”拉近距离，但不要每句都“我们”。
- 允许一次自我修正：“更准确地说，……”“我换个说法，……”。
- 可用的口语词块（挑 3–5 个，不要全用）：
  开场“先说结论”“这件事，得从……说起”；
  转折“可问题是”“话是这么说，但……”；
  解释“什么意思呢？就是说……”；
  举例“举个最简单的例子”；
  收束“所以说到底”“一句话”。

3) 动词和具体
- 动词优先：进行讨论→聊；做出判断→判断；实现增长→涨；产生影响→影响；起到作用→起作用。
- 抽象名词后面补一个动作或画面：“流动性问题”→“想卖，卖不掉”。
- 数字后面补一句人话：“800 亿美元，相当于……”；不要一句话连堆三个数字。
- 少用“性/化/度”名词化（可行性、优化、强度），改成动词或短句。
- 英文的 covers / focuses on / leads / backs 不要一律压成“看”。按中文动作分开：
  covers infrastructure → 负责基础设施领域 / 主要看基础设施赛道；
  leads the round → 领投；backs founders → 投早期项目。
- 不要把两个名词硬拼成一句。反例：“Casado 在 a16z 做合伙人，看基础设施。”
  正例：“Casado 是 a16z 的合伙人，主要看基础设施赛道的投资。”
  这里的“看”后面要么补“赛道/领域/方向”，要么换成“负责/关注/投”。

4) 不要翻译腔
- 少用或不用：进行、使得、对于、关于、通过、由于、随着、与此同时、综上所述、
  在很大程度上、值得一提的是、值得注意的是、被认为、具有……意义、起到……作用。
- 不要成对使用“因为……所以……”“虽然……但是……”“不仅……而且……”；
  中文靠语序和停顿，不靠连接词。
- 不要照搬英文的“It is … that …”“…, followed by …”“one of the most …”。
- 不要用“首先/其次/最后”当段落骨架；用“先说……再说……”或直接讲。
- 不要用“本文/笔者/我们将会看到/接下来让我们”。
- 不要用“看+大领域”代替完整动宾。反例：“看基础设施”“看AI”“看消费”；
  正例：“负责基础设施领域”“主要看AI赛道”“关注消费行业”。
- 英文的省略句不要照搬。英文可以写 “partner covering infrastructure”，
  中文要补主语和动作：“他是合伙人，负责基础设施领域的投资。”
- 引号里不要放单字（反例：值得“查”），要写完整的词（值得检查）。
- 大陆词形：视频、芯片、数据中心、网络、软件、硬件、营销、屏幕、信息、数字、
  链接、设置、支持、计划、检查；不要用台湾用语（影片、晶片、资料中心、透过、网路）。
- 用完整的双音节词，不要为了“口语”把词砍成单字。反例：做个“检”、看一“数”。

5) 节奏和成语
- 长短句交替：连续两句短句后，可以放一个稍长的解释句，再收回短句。
- 关键判断用四字格/成语收住，全片 3–6 次，放在转折、结论或反问之后。
- 成语要贴切，不要为了用而用；四字短语也算（“钱从哪来”“谁来兜底”“越拖越贵”）。
- 一段里至少有一次四字节奏；但不要连续两句都甩成语。

6) 事实和立场
- 保留英文稿的立场、限定条件、作者自己加的判断和数字；不要新增事实，不要改变观点。
- 每页 narration 的说话时长与英文大致相当（中文约 4.2–4.8 字/秒），不要明显变长。
- 专有名词保留常用英文或通用译名；不要加拼音；除非名字容易被读错，不要加 tts_text。

对照例子（感受一下差别）：
- 书面/翻译腔：“对于当前市场而言，流动性的收紧在很大程度上使得风险资产承压。”
  口播：“钱紧了，风险资产先扛不住。就这么简单。”
- 书面/翻译腔：“该公司进行了为期两年的产能扩张，并在此过程中实现了成本的显著优化。”
  口播：“这家公司花了两年扩产。结果呢？成本没降多少。”
- 书面/翻译腔：“值得注意的是，该现象的背后存在多重结构性因素。”
  口播：“这事儿不简单。背后有好几层原因。”

写完后的口语检查（必须做，不合格会被打回重写）：
- 逐句默读一遍；超过 30 字就拆，超过 38 字必须拆。
- 数一下：设问至少 2 次，口头路标 4–8 次，语气词 3–6 个，成语/四字格 3–6 个。
- 搜一遍黑名单词（进行、对于、通过、与此同时、被认为……），能换就换。
- 搜一遍“，看”“看AI”“看基础设施”“看消费”；每一处补成“看……赛道/领域/方向”，
  或者改成“负责/关注/投”。
- 确认没有“首先/其次/最后”三段式，没有单字引号，没有台湾词形。

结构要求：
- 完整保留 JSON 结构、每个 shot 的 id、kind、fps、engine、voice_profile，以及
  visual 里的数值。把 deck 级 language 设为 "zh-Hans"。
- 每个 shot 重写：narration、heading、bullets（条数不变）、kicker、on_screen、
  subtitle、quote、attribution、question、next_text。
- visual 里的标签要本地化：data.categories、series[].name、unit、source、title、
  subtitle、label、points、SVG/Mermaid 文字。保留 type、chart_type、animated、ID、
  URL、股票代码、公司/产品名和所有数值。
- 普通标签（如 Crude、Refined products）译成中文；公司名、人名可保留原文。
- attribution 是专有名词时可保留原文。

YouTube 元数据：
- 保留完整结构和所有非文本值。
- 用中文原生重写 title、description、每个 chapters[].title、tags；不要翻译英文
  模板，也不要保留英文免责声明套话。
- 保留 URL、时间戳、数字、来源名，以及“AI 生成语音/独立评论/非投资建议”的含义。
- defaultLanguage 和 defaultAudioLanguage 设为 "zh-Hans"；privacyStatus 保持 private；
  containsSyntheticMedia 保持 true。

写完后确认两个文件都能被 JSON 解析。不要运行音频、渲染或上传命令；写完即停。
{correction}"""


def _validate(en: dict, zh: dict) -> str:
    if zh.get("language") != "zh-Hans":
        return "language must be zh-Hans"
    en_shots, zh_shots = en.get("shots") or [], zh.get("shots") or []
    if len(en_shots) != len(zh_shots):
        return f"shot count {len(zh_shots)} != {len(en_shots)}"
    for a, b in zip(en_shots, zh_shots):
        if str(a.get("id")) != str(b.get("id")) or a.get("kind") != b.get("kind"):
            return f"shot {a.get('id')} id/kind changed"
        if "bullets" in a and len(a["bullets"]) != len(b.get("bullets") or []):
            return f"shot {a.get('id')} bullets length changed"
        if not str(b.get("narration") or "").strip():
            return f"shot {a.get('id')} narration empty"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--youtube", required=True)
    parser.add_argument("--source", required=True, help="source.json or transcript.txt")
    parser.add_argument("--out-dir")
    parser.add_argument("--model", default="opencode-go/deepseek-v4.1-flash")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--style-strict", action="store_true",
                        help="also reject a grade-C deck")
    parser.add_argument("--log")
    args = parser.parse_args(argv)

    slides = Path(args.slides).resolve()
    youtube = Path(args.youtube).resolve()
    source = Path(args.source).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else slides.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_slides = out_dir / "slides.zh.json"
    out_youtube = out_dir / "youtube.zh.json"
    style_path = out_dir / "mandarin.style.json"
    log_path = Path(args.log).resolve() if args.log else out_dir / "mandarin.log"

    en_slides = _load(slides)
    _load(youtube)
    if not _transcript(source).strip():
        raise SystemExit("source transcript is empty")

    feedback = ""
    for attempt in range(1, args.attempts + 1):
        prompt = _prompt(slides, youtube, source, out_slides, out_youtube, feedback)
        out_slides.unlink(missing_ok=True)
        out_youtube.unlink(missing_ok=True)
        with log_path.open("a") as handle:
            handle.write(f"\n=== native mandarin attempt {attempt} ===\n")
            handle.flush()
            code = subprocess.run(
                [
                    "opencode", "run", "--auto", "--model", args.model,
                    "--title", f"mandarin-native-{slides.parent.name}-{attempt}",
                    prompt,
                ],
                cwd=out_dir.parents[2] if len(out_dir.parents) > 2 else out_dir,
                stdout=handle, stderr=subprocess.STDOUT,
            ).returncode
        if code or not out_slides.exists() or not out_youtube.exists():
            print(f"native mandarin attempt {attempt} failed; see {log_path}", file=sys.stderr)
            continue
        try:
            zh = _load(out_slides)
            _load(out_youtube)
        except Exception as exc:  # noqa: BLE001
            print(f"invalid JSON: {exc}", file=sys.stderr)
            continue
        problem = _validate(en_slides, zh)
        if problem:
            print(f"validation failed: {problem}", file=sys.stderr)
            feedback = f"上一稿结构不合格：{problem}。请保持原 JSON 结构和 id 不变。"
            continue

        report = mandarin_style.analyze(zh)
        style_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"style: grade {report['grade']} ({report['score']}/100), "
              f"{report['chars']} chars, mean {report['mean_sentence']}, "
              f"hard {len(report['hard'])}, warnings "
              f"{sum(1 for i in report['issues'] if i['level'] == 'warn')}",
              file=sys.stderr)
        blocked = bool(report["hard"]) or (args.style_strict and report["grade"] == "C")
        if blocked and attempt < args.attempts:
            feedback = mandarin_style.feedback(report) or (
                "上一稿口语度不够。请按 14–20 字一句重写 narration，"
                "加入 2 次设问、3–6 个语气词和 3–6 个四字节拍。\n")
            print(f"style gate: retrying with {len(report['hard'])} hard issue(s); "
                  f"report at {style_path}", file=sys.stderr)
            continue
        if blocked:
            print(f"style gate: accepting last attempt with issues; "
                  f"report at {style_path}", file=sys.stderr)

        print(f"wrote {out_slides}")
        print(f"wrote {out_youtube}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
