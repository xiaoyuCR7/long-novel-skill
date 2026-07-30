#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_fingerprint.py — 文风指纹提取与对比工具（纯标准库，无第三方依赖）。

文风指纹 = 一本书/对标书的量化腔调基线，用于防长篇连载文风漂移、对标书腔调迁移、
跨项目风格复用。详见 references/craft/style-fingerprint.md。

六维文风量化：
  1. 平均句长（按句号/问号/感叹号切分后的平均字数）
  2. 对话占比（「」或 "" 内的文字占总字数比例）
  3. 段落中位长度（段落非空白字符数的中位数）
  4. 标点节奏（？/！/…… 在句末标点中的占比）
  5. 高频词 Top20（去除停用词后的实词，简单分词用正则按 2-4 字滑窗）
  6. 句式偏好（长短句交替比 = 短句数 / 长句数；短句<10字，长句>20字）

子命令：
  extract   从一个或多个文本文件提取文风指纹，输出 Markdown 文风锚文件。
  compare   对比当前章节与文风锚的六维指标，输出偏离维度。

用法：
  python scripts/style_fingerprint.py extract "正文/第001章.md" "正文/第002章.md" \
      --output "设定/文风锚.md"
  python scripts/style_fingerprint.py extract f1.md --tolerance "3,5,10,2,0.2"
  python scripts/style_fingerprint.py compare "正文/第037章.md" "设定/文风锚.md"

容差格式（--tolerance，逗号分隔，顺序固定）：
  句长, 对话占比(%), 段落长度, 标点节奏(%), 句式偏好
默认：3, 5, 10, 2, 0.2

退出码：0 = 成功/容差内；1 = 有偏离；2 = 参数/文件错误。

本模块同时作为共享库被 check_text.py / deconstruct.py 导入，公开函数：
  compute_six_dimensions(text)  -> dict
  format_anchor_md(metrics, tolerance, title, sources) -> str
  parse_anchor_md(path) -> (metrics, tolerance)
  compare_metrics(current, anchor, tolerance) -> list[str]
  count_chars(text) -> (non_ws, cjk)
"""

import argparse
import os
import re
import statistics
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# 基础正则
# ---------------------------------------------------------------------------
CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
CJK_RUN_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")
DIALOGUE_RE = re.compile(r"「[^」]*」|“[^”]*”")
# 句末标点（含中文省略号单字符 …）
END_MARK_RE = re.compile(r"[。！？!?…]")

# ---------------------------------------------------------------------------
# 停用词表（约 100 个常见中文虚词 / 高频功能词）
# ---------------------------------------------------------------------------
STOPWORDS = set("""
的 了 是 在 有 和 就 不 都 一 上 也 很 到 说 要 去 你 会 着 看 好 他 她 它
此 其 该 某 每 各 凡 全 总 共 又 再 只 便 而 以 及 与 或 乃 则 即 便 之 乎
者 矣 焉 哉 没 非 无 未 勿 莫 别 休 更 最 挺 极 得 想 能 可 呢 吧 啊 呀 哇
嘛 哟 嗯 哦 几 多 少
自己 我们 你们 他们 她们 它们 这个 那个 这些 那些 这里 那里 这样 那样
这么 那么 什么 怎么 为何 哪里 哪个 因为 所以 但是 可是 虽然 如果 还是
已经 正在 于是 然后 接着 由于 并且 或者 以及 不过 另外 而且 不仅 甚至
尤其 非常 特别 可以 应该 需要 可能 或许 也许 大概 一定 必定 当然 显然
果然 忽然 突然 立刻 马上 立即 随后 最终 终于 终究 既然 尽管 即使 哪怕
就是 便是 没有
""".split())

# 单字停用词（用于 n-gram 过滤：含任一单字停用词的 gram 视为非纯实词，剔除）
FUNCTION_CHARS = {w for w in STOPWORDS if len(w) == 1}


def count_chars(text):
    """返回 (非空白字符数, 汉字数)。"""
    non_ws = len(re.sub(r"\s", "", text))
    cjk = len(CJK_RE.findall(text))
    return non_ws, cjk


# ---------------------------------------------------------------------------
# 六维指标计算
# ---------------------------------------------------------------------------
def _avg_sent_len(text, non_ws):
    sents = [s for s in SENT_SPLIT_RE.split(text) if s.strip()]
    if not sents:
        return 0.0
    return non_ws / len(sents)


def _dialogue_ratio(text, non_ws):
    if non_ws == 0:
        return 0.0
    quotes = DIALOGUE_RE.findall(text)
    dialogue = sum(len(re.sub(r"\s", "", q)) for q in quotes)
    return dialogue / non_ws * 100.0


def _median_para_len(text):
    paras = [len(re.sub(r"\s", "", p)) for p in text.splitlines() if p.strip()]
    if not paras:
        return 0.0
    return float(statistics.median(paras))


def _punct_rhythm(text):
    """？/！/…… 各占句末标点总数的百分比。"""
    marks = END_MARK_RE.findall(text)
    total = len(marks)
    if total == 0:
        return {"q": 0.0, "e": 0.0, "ellipsis": 0.0}
    q = text.count("？") + text.count("?")
    e = text.count("！") + text.count("!")
    ell = text.count("…")
    return {
        "q": q / total * 100.0,
        "e": e / total * 100.0,
        "ellipsis": ell / total * 100.0,
    }


def _top_words(text, n=20):
    """2-4 字滑窗分词，剔除含单字停用词的 gram，统计高频实词 Top N。"""
    counter = Counter()
    for run in CJK_RUN_RE.findall(text):
        for size in (2, 3, 4):
            if len(run) < size:
                continue
            for i in range(len(run) - size + 1):
                gram = run[i:i + size]
                if gram in STOPWORDS:
                    continue
                # 含任一单字停用词（的/了/是/…）视为非纯实词，剔除
                if any(c in FUNCTION_CHARS for c in gram):
                    continue
                counter[gram] += 1
    return counter.most_common(n)


def _sentence_pattern(text):
    """长短句交替比 = 短句数 / 长句数（短句<10字，长句>20字，按非空白字符计）。"""
    sents = [s for s in SENT_SPLIT_RE.split(text) if s.strip()]
    short = 0
    long_ = 0
    for s in sents:
        length = len(re.sub(r"\s", "", s))
        if length < 10:
            short += 1
        elif length > 20:
            long_ += 1
    ratio = short / long_ if long_ else float(short)
    return {"alternation_ratio": ratio, "short_count": short, "long_count": long_}


def compute_six_dimensions(text):
    """计算六维文风指标，返回字典。"""
    non_ws, _ = count_chars(text)
    return {
        "avg_sent_len": _avg_sent_len(text, non_ws),
        "dialogue_ratio": _dialogue_ratio(text, non_ws),
        "median_para_len": _median_para_len(text),
        "punct_rhythm": _punct_rhythm(text),
        "top_words": _top_words(text, 20),
        "sentence_pattern": _sentence_pattern(text),
        "non_ws": non_ws,
    }


# ---------------------------------------------------------------------------
# 容差
# ---------------------------------------------------------------------------
DEFAULT_TOLERANCE = {"sent": 3.0, "dial": 5.0, "para": 10.0, "punct": 2.0, "pat": 0.2}


def parse_tolerance(spec):
    """解析容差字符串 '3,5,10,2,0.2' -> dict。字段缺失用默认值补齐。"""
    tol = dict(DEFAULT_TOLERANCE)
    if not spec:
        return tol
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    keys = ["sent", "dial", "para", "punct", "pat"]
    for i, p in enumerate(parts):
        if i >= len(keys):
            break
        try:
            tol[keys[i]] = float(p)
        except ValueError:
            raise ValueError(f"容差第 {i + 1} 项 '{p}' 不是数字")
    return tol


# ---------------------------------------------------------------------------
# 文风锚 Markdown 生成与解析
# ---------------------------------------------------------------------------
def format_anchor_md(metrics, tolerance, title="文风锚", sources=None):
    """把六维指标格式化为 Markdown 文风锚文本。"""
    pr = metrics["punct_rhythm"]
    sp = metrics["sentence_pattern"]
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("> 由 style_fingerprint.py extract 自动生成。用于防长篇连载文风漂移，"
                 "每 5-10 章校准一次。")
    lines.append("")
    lines.append("## 量化基线")
    lines.append(f"- 平均句长：{metrics['avg_sent_len']:.1f} 字（容差 ±{tolerance['sent']:g}）")
    lines.append(f"- 对话占比：{metrics['dialogue_ratio']:.1f}%（容差 ±{tolerance['dial']:g}%）")
    lines.append(f"- 段落中位长度：{metrics['median_para_len']:.0f} 字（容差 ±{tolerance['para']:g}）")
    lines.append(f"- 标点节奏：？{pr['q']:.1f}% / ！{pr['e']:.1f}% / ……{pr['ellipsis']:.1f}%"
                 f"（容差 ±{tolerance['punct']:g}%）")
    lines.append(f"- 句式偏好：长短句交替比 {sp['alternation_ratio']:.2f}"
                 f"（短句 {sp['short_count']} / 长句 {sp['long_count']}，容差 ±{tolerance['pat']:g}）")
    lines.append("")
    lines.append("## 高频词 Top20")
    if metrics["top_words"]:
        for i, (w, c) in enumerate(metrics["top_words"], 1):
            lines.append(f"{i}. {w} ({c})")
    else:
        lines.append("（无）")
    lines.append("")
    if sources:
        lines.append("## 样本来源")
        for s in sources:
            lines.append(f"- {s}")
        lines.append("")
    lines.append("## 腔调关键词")
    lines.append("- （作者手填 3 个定义本书腔调的词）")
    lines.append("")
    lines.append("## 样板段落")
    lines.append("- （从样本里贴 3-5 段最能代表本书腔调的原文）")
    lines.append("")
    lines.append("## 高频词白名单")
    lines.append("- （本书合理的高频词，不作为 AI 套话处理）")
    lines.append("")
    return "\n".join(lines)


_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _parse_first_num(s):
    m = _NUM_RE.search(s)
    return float(m.group(1)) if m else None


def parse_anchor_md(path):
    """解析文风锚 Markdown，返回 (metrics_dict, tolerance_dict)。

    metrics_dict 含 avg_sent_len / dialogue_ratio / median_para_len /
    punct_rhythm / sentence_pattern（top_words 留空）。
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    metrics = {
        "avg_sent_len": 0.0,
        "dialogue_ratio": 0.0,
        "median_para_len": 0.0,
        "punct_rhythm": {"q": 0.0, "e": 0.0, "ellipsis": 0.0},
        "sentence_pattern": {"alternation_ratio": 0.0, "short_count": 0, "long_count": 0},
        "top_words": [],
    }
    tol = dict(DEFAULT_TOLERANCE)

    # 容差：从基线行内 “容差 ±X” 提取
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- 平均句长"):
            metrics["avg_sent_len"] = _parse_first_num(s) or 0.0
            tol["sent"] = _tol_from_line(s, tol["sent"])
        elif s.startswith("- 对话占比"):
            metrics["dialogue_ratio"] = _parse_first_num(s) or 0.0
            tol["dial"] = _tol_from_line(s, tol["dial"])
        elif s.startswith("- 段落中位长度"):
            metrics["median_para_len"] = _parse_first_num(s) or 0.0
            tol["para"] = _tol_from_line(s, tol["para"])
        elif s.startswith("- 标点节奏"):
            nums = _NUM_RE.findall(s)
            # 顺序：？ / ！ / …… / 容差
            qs = [float(x) for x in nums]
            if len(qs) >= 1:
                metrics["punct_rhythm"]["q"] = qs[0]
            if len(qs) >= 2:
                metrics["punct_rhythm"]["e"] = qs[1]
            if len(qs) >= 3:
                metrics["punct_rhythm"]["ellipsis"] = qs[2]
            if len(qs) >= 4:
                tol["punct"] = qs[3]
        elif s.startswith("- 句式偏好"):
            nums = _NUM_RE.findall(s)
            qs = [float(x) for x in nums]
            if qs:
                metrics["sentence_pattern"]["alternation_ratio"] = qs[0]
            if len(qs) >= 4:
                tol["pat"] = qs[-1]
    return metrics, tol


def _tol_from_line(line, default):
    m = re.search(r"容差\s*±\s*(-?\d+(?:\.\d+)?)", line)
    return float(m.group(1)) if m else default


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------
def compare_metrics(current, anchor, tolerance):
    """对比当前与锚的六维指标，返回偏离描述列表。"""
    devs = []

    d_sent = abs(current["avg_sent_len"] - anchor["avg_sent_len"])
    if d_sent > tolerance["sent"]:
        devs.append(f"节奏漂移：句长 {anchor['avg_sent_len']:.1f} → {current['avg_sent_len']:.1f} 字"
                    f"（容差 ±{tolerance['sent']:g}）")

    d_dial = current["dialogue_ratio"] - anchor["dialogue_ratio"]
    if abs(d_dial) > tolerance["dial"]:
        direction = "对话过多" if d_dial > 0 else "对话过少"
        devs.append(f"{direction}：对话占比 {anchor['dialogue_ratio']:.1f}% → "
                    f"{current['dialogue_ratio']:.1f}%（容差 ±{tolerance['dial']:g}%）")

    d_para = abs(current["median_para_len"] - anchor["median_para_len"])
    if d_para > tolerance["para"]:
        devs.append(f"段落习惯变了：段落中位长度 {anchor['median_para_len']:.0f} → "
                    f"{current['median_para_len']:.0f} 字（容差 ±{tolerance['para']:g}）")

    for key, label in (("q", "？"), ("e", "！"), ("ellipsis", "……")):
        cv = current["punct_rhythm"][key]
        av = anchor["punct_rhythm"][key]
        if abs(cv - av) > tolerance["punct"]:
            devs.append(f"情绪强度变了：标点 {label} {av:.1f}% → {cv:.1f}%"
                        f"（容差 ±{tolerance['punct']:g}%）")

    d_pat = abs(current["sentence_pattern"]["alternation_ratio"]
                - anchor["sentence_pattern"]["alternation_ratio"])
    if d_pat > tolerance["pat"]:
        devs.append(f"句式偏好变了：长短句交替比 "
                    f"{anchor['sentence_pattern']['alternation_ratio']:.2f} → "
                    f"{current['sentence_pattern']['alternation_ratio']:.2f}"
                    f"（容差 ±{tolerance['pat']:g}）")

    return devs


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------
def cmd_extract(args):
    texts = []
    sources = []
    total_chars = 0
    for path in args.files:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                t = f.read()
        except OSError as e:
            print(f"错误：无法读取文件 {path}: {e}", file=sys.stderr)
            return 2
        texts.append(t)
        non_ws, _ = count_chars(t)
        total_chars += non_ws
        sources.append(f"{os.path.basename(path)}（{non_ws} 字）")

    if not texts:
        print("错误：至少需要一个输入文件", file=sys.stderr)
        return 2

    try:
        tolerance = parse_tolerance(args.tolerance)
    except ValueError as e:
        print(f"错误：--tolerance 解析失败：{e}", file=sys.stderr)
        return 2

    combined = "\n\n".join(texts)
    metrics = compute_six_dimensions(combined)
    md = format_anchor_md(metrics, tolerance, title=args.title or "文风锚", sources=sources)

    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已生成文风锚：{args.output}（样本 {len(texts)} 个文件 / 共 {total_chars} 字）")
    else:
        sys.stdout.write(md)
    return 0


def cmd_compare(args):
    try:
        with open(args.current, "r", encoding="utf-8-sig") as f:
            cur_text = f.read()
    except OSError as e:
        print(f"错误：无法读取当前文件 {args.current}: {e}", file=sys.stderr)
        return 2
    try:
        anchor_metrics, tolerance = parse_anchor_md(args.anchor)
    except OSError as e:
        print(f"错误：无法读取文风锚 {args.anchor}: {e}", file=sys.stderr)
        return 2

    if args.tolerance:
        try:
            tolerance = parse_tolerance(args.tolerance)
        except ValueError as e:
            print(f"错误：--tolerance 解析失败：{e}", file=sys.stderr)
            return 2

    cur = compute_six_dimensions(cur_text)
    pr = cur["punct_rhythm"]
    sp = cur["sentence_pattern"]
    print(f"文风对比：{os.path.basename(args.current)} vs {os.path.basename(args.anchor)}")
    print()
    print("当前指标：")
    print(f"- 平均句长：{cur['avg_sent_len']:.1f} 字")
    print(f"- 对话占比：{cur['dialogue_ratio']:.1f}%")
    print(f"- 段落中位长度：{cur['median_para_len']:.0f} 字")
    print(f"- 标点节奏：？{pr['q']:.1f}% / ！{pr['e']:.1f}% / ……{pr['ellipsis']:.1f}%")
    print(f"- 句式偏好：长短句交替比 {sp['alternation_ratio']:.2f}"
          f"（短 {sp['short_count']} / 长 {sp['long_count']}）")
    print()

    devs = compare_metrics(cur, anchor_metrics, tolerance)
    if devs:
        print(f"偏离维度（{len(devs)} 处）：")
        for d in devs:
            print(f"  [偏离] {d}")
        print()
        print(f"结果：有 {len(devs)} 处偏离，需回头校准本章腔调或更新文风锚")
        return 1
    print("结果：六维全部在容差内")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="文风指纹提取与对比：六维量化腔调基线，防长篇文风漂移。")
    sub = ap.add_subparsers(dest="command", required=True)

    p_ex = sub.add_parser("extract", help="从文本提取文风指纹，生成文风锚 Markdown")
    p_ex.add_argument("files", nargs="+", help="样章文本文件（可多个，合并统计）")
    p_ex.add_argument("--output", "-o", default=None, help="输出文风锚文件路径；不指定则打印到 stdout")
    p_ex.add_argument("--title", default=None, help="文风锚标题（默认“文风锚”）")
    p_ex.add_argument("--tolerance", default=None,
                      help="容差，逗号分隔：句长,对话占比,段落,标点节奏,句式偏好（默认 3,5,10,2,0.2）")
    p_ex.set_defaults(func=cmd_extract)

    p_cmp = sub.add_parser("compare", help="对比当前章节与文风锚的六维指标")
    p_cmp.add_argument("current", help="当前章节文本文件")
    p_cmp.add_argument("anchor", help="文风锚 Markdown 文件")
    p_cmp.add_argument("--tolerance", default=None,
                       help="覆盖文风锚中的容差（格式同 extract）")
    p_cmp.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
