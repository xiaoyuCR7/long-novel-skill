#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deconstruct.py — 拆文辅助工具（纯标准库，无第三方依赖）。

拆解对标书，产出量化素材：结构、节奏、文风指纹。用于学习对标书的节奏感与句式结构，
写作时按需召回。详见 references/workflow 与 references/craft/style-fingerprint.md。

子命令：
  stats       统计对标书量化数据：总字数 / 平均章长 / 对话占比 / 平均句长 / 段落中位长度 / 章长分布
  structure   逐章提取结构：首句 / 末句(钩子候选) / 对话段数 / 最长段落 / 章尾钩子类型
  rhythm      分析节奏：由平均句长+对话占比推断快/中/慢档位 + 爽点位置推测
  fingerprint 提取文风指纹（六维，与 style_fingerprint.py extract 一致）

用法：
  python scripts/deconstruct.py stats "对标/书A/原文/第1章.md" "对标/书A/原文/第2章.md"
  python scripts/deconstruct.py structure ch1.md ch2.md --output "对标/书A/结构分析.md"
  python scripts/deconstruct.py rhythm ch1.md ch2.md --output "对标/书A/节奏分析.md"
  python scripts/deconstruct.py fingerprint ch1.md ch2.md --output "对标/书A/文风指纹.md"

退出码：0 = 成功；1 = 有命中/违规（本工具一般不产生）；2 = 参数/文件错误。
"""

import argparse
import os
import re
import statistics
import sys

# 复用同目录 style_fingerprint.py 的六维文风逻辑
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    import style_fingerprint as sf
    _HAS_SF = True
except Exception:
    sf = None
    _HAS_SF = False

CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")
DIALOGUE_RE = re.compile(r"「[^」]*」|“[^”]*”")
CHAPTER_RE = re.compile(r"第\s*(\d+)\s*章")

# 章尾钩子新人物登场启发式
NEW_CHAR_RE = re.compile(r"(一个|一名|一位|只见|走出|出现|来了|降临|走进|身旁|身后|门口|阴影)")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def read_text(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def non_ws_len(s):
    return len(re.sub(r"\s", "", s))


def chapter_key_label(path):
    """返回 (排序键, 显示标签)。优先用文件名里的章号。"""
    base = os.path.basename(path)
    m = CHAPTER_RE.search(base)
    if m:
        return int(m.group(1)), f"第{int(m.group(1))}章"
    return 10 ** 9, os.path.splitext(base)[0]


def first_sentence(text):
    for s in SENT_SPLIT_RE.split(text):
        s = s.strip()
        if s:
            return s
    return ""


def last_sentence(text):
    sents = [s.strip() for s in SENT_SPLIT_RE.split(text) if s.strip()]
    return sents[-1] if sents else ""


def get_last_paragraph(text):
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if paras:
        return paras[-1].strip()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


def count_dialogue_paragraphs(text):
    cnt = 0
    for p in re.split(r"\n\s*\n", text):
        if p.strip() and DIALOGUE_RE.search(p):
            cnt += 1
    if cnt == 0:
        # 无空行分段时按行计
        for ln in text.splitlines():
            if ln.strip() and DIALOGUE_RE.search(ln):
                cnt += 1
    return cnt


def longest_paragraph(text):
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return 0
        paras = lines
    return max(non_ws_len(p) for p in paras)


def detect_hook_types(last_para):
    """章尾钩子类型（启发式）：选择悬置 / 新危机 / 新人物 / 未识别。"""
    types = []
    if "？" in last_para or "?" in last_para:
        types.append("选择悬置")
    if "！" in last_para or "!" in last_para:
        types.append("新危机")
    if NEW_CHAR_RE.search(last_para):
        types.append("新人物")
    return types if types else ["未识别"]


def infer_gear(avg_sent, dialogue_ratio):
    """由平均句长+对话占比推断档位：句长短+对话多=快；句长长+对话少=慢。"""
    if avg_sent < 15 and dialogue_ratio > 40:
        return "快"
    if avg_sent > 22 and dialogue_ratio < 25:
        return "慢"
    return "中"


def climax_position(text):
    """爽点位置推测：把全文按字符位置分 10 段，统计 ！/？ 密度最高的一段。"""
    marks = []
    total = len(text)
    if total == 0:
        return "无数据"
    for m in re.finditer(r"[！！？\?!]", text):
        marks.append(m.start() / total)
    if not marks:
        return "无明显标点高潮"
    bins = [0] * 10
    for pos in marks:
        idx = min(int(pos * 10), 9)
        bins[idx] += 1
    peak = max(range(10), key=lambda i: bins[i])
    lo = peak * 10
    hi = (peak + 1) * 10
    return f"约 {lo}%-{hi}% 处"


def chapter_metrics(text):
    """单章指标：字数 / 对话占比 / 平均句长 / 段落中位长度 / 句数 / 段数。"""
    non_ws, _ = sf.count_chars(text) if _HAS_SF else (non_ws_len(text), 0)
    sents = [s for s in SENT_SPLIT_RE.split(text) if s.strip()]
    avg_sent = non_ws / len(sents) if sents else 0.0
    quotes = DIALOGUE_RE.findall(text)
    dialogue = sum(non_ws_len(q) for q in quotes)
    dial_ratio = dialogue / non_ws * 100 if non_ws else 0.0
    paras = [non_ws_len(p) for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [non_ws_len(ln) for ln in text.splitlines() if ln.strip()]
    median_para = statistics.median(paras) if paras else 0
    return {
        "chars": non_ws,
        "avg_sent": avg_sent,
        "dial_ratio": dial_ratio,
        "median_para": float(median_para),
        "n_sents": len(sents),
        "n_paras": len(paras),
    }


def _truncate(s, n=30):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# 子命令：stats
# ---------------------------------------------------------------------------
def cmd_stats(args):
    rows = []
    for path in sorted(args.files, key=lambda p: chapter_key_label(p)[0]):
        try:
            text = read_text(path)
        except OSError as e:
            print(f"错误：无法读取 {path}: {e}", file=sys.stderr)
            return 2
        _, label = chapter_key_label(path)
        m = chapter_metrics(text)
        rows.append((label, m))

    if not rows:
        print("错误：无输入文件", file=sys.stderr)
        return 2

    total = sum(m["chars"] for _, m in rows)
    avg = total / len(rows)
    lens = [m["chars"] for _, m in rows]
    shortest = min(lens)
    longest = max(lens)
    median_len = statistics.median(lens)
    avg_dial = statistics.mean(m["dial_ratio"] for _, m in rows)
    avg_sent = statistics.mean(m["avg_sent"] for _, m in rows)
    avg_median_para = statistics.mean(m["median_para"] for _, m in rows)

    lines = []
    lines.append("# 对标书量化统计")
    lines.append("")
    lines.append("## 总览")
    lines.append(f"- 章节数：{len(rows)}")
    lines.append(f"- 总字数：{total}（非空白字符）")
    lines.append(f"- 平均章长：{avg:.0f} 字")
    lines.append(f"- 章长分布：最短 {shortest} / 最长 {longest} / 中位 {median_len:.0f}")
    lines.append(f"- 平均对话占比：{avg_dial:.1f}%")
    lines.append(f"- 平均句长（全书均值）：{avg_sent:.1f} 字")
    lines.append(f"- 段落中位长度（全书均值）：{avg_median_para:.0f} 字")
    lines.append("")
    lines.append("## 逐章")
    lines.append("| 章节 | 字数 | 对话占比 | 平均句长 | 段落中位长度 |")
    lines.append("|---|---|---|---|---|")
    for label, m in rows:
        lines.append(f"| {label} | {m['chars']} | {m['dial_ratio']:.0f}% | "
                     f"{m['avg_sent']:.1f} | {m['median_para']:.0f} |")
    lines.append("")
    out = "\n".join(lines)
    _emit(out, args.output, "量化统计")
    return 0


# ---------------------------------------------------------------------------
# 子命令：structure
# ---------------------------------------------------------------------------
def cmd_structure(args):
    rows = []
    for path in sorted(args.files, key=lambda p: chapter_key_label(p)[0]):
        try:
            text = read_text(path)
        except OSError as e:
            print(f"错误：无法读取 {path}: {e}", file=sys.stderr)
            return 2
        _, label = chapter_key_label(path)
        first = first_sentence(text)
        last = last_sentence(text)
        last_para = get_last_paragraph(text)
        hook_types = detect_hook_types(last_para)
        rows.append({
            "label": label,
            "first": _truncate(first, 36),
            "last": _truncate(last, 36),
            "dial_paras": count_dialogue_paragraphs(text),
            "longest": longest_paragraph(text),
            "hooks": "、".join(hook_types),
        })

    lines = []
    lines.append("# 对标书结构分析")
    lines.append("")
    lines.append("## 逐章结构")
    lines.append("| 章节 | 首句 | 末句(钩子候选) | 对话段数 | 最长段落 | 钩子类型 |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['label']} | {r['first']} | {r['last']} | "
                     f"{r['dial_paras']} | {r['longest']}字 | {r['hooks']} |")
    lines.append("")
    lines.append("## 钩子类型说明")
    lines.append("- 选择悬置：末段含问号，角色面临抉择")
    lines.append("- 新危机：末段含感叹号，麻烦出现或升级")
    lines.append("- 新人物：末段含登场词（一个/一名/只见/走出…），关键人物登场")
    lines.append("- 未识别：启发式未命中，需人工判断")
    lines.append("")
    out = "\n".join(lines)
    _emit(out, args.output, "结构分析")
    return 0


# ---------------------------------------------------------------------------
# 子命令：rhythm
# ---------------------------------------------------------------------------
def cmd_rhythm(args):
    rows = []
    for path in sorted(args.files, key=lambda p: chapter_key_label(p)[0]):
        try:
            text = read_text(path)
        except OSError as e:
            print(f"错误：无法读取 {path}: {e}", file=sys.stderr)
            return 2
        _, label = chapter_key_label(path)
        m = chapter_metrics(text)
        gear = infer_gear(m["avg_sent"], m["dial_ratio"])
        climax = climax_position(text)
        rows.append({
            "label": label,
            "avg_sent": m["avg_sent"],
            "dial": m["dial_ratio"],
            "gear": gear,
            "climax": climax,
        })

    dist = {"快": 0, "中": 0, "慢": 0}
    for r in rows:
        dist[r["gear"]] += 1
    n = len(rows)

    lines = []
    lines.append("# 对标书节奏分析")
    lines.append("")
    lines.append("## 档位分布")
    lines.append(f"- 快档：{dist['快']} 章（{dist['快'] / n * 100:.0f}%）")
    lines.append(f"- 中档：{dist['中']} 章（{dist['中'] / n * 100:.0f}%）")
    lines.append(f"- 慢档：{dist['慢']} 章（{dist['慢'] / n * 100:.0f}%）")
    lines.append("")
    lines.append("> 推断口径：句长<15字且对话>40% = 快档；句长>22字且对话<25% = 慢档；其余为中档。"
                 "阈值可按题材微调。")
    lines.append("")
    lines.append("## 逐章档位")
    lines.append("| 章节 | 平均句长 | 对话占比 | 推断档位 | 爽点位置(！/？密度峰值) |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['label']} | {r['avg_sent']:.1f} | {r['dial']:.0f}% | "
                     f"{r['gear']} | {r['climax']} |")
    lines.append("")
    out = "\n".join(lines)
    _emit(out, args.output, "节奏分析")
    return 0


# ---------------------------------------------------------------------------
# 子命令：fingerprint
# ---------------------------------------------------------------------------
def cmd_fingerprint(args):
    if not _HAS_SF:
        print("错误：缺少 style_fingerprint 模块，无法提取文风指纹", file=sys.stderr)
        return 2
    texts = []
    sources = []
    total = 0
    for path in sorted(args.files, key=lambda p: chapter_key_label(p)[0]):
        try:
            t = read_text(path)
        except OSError as e:
            print(f"错误：无法读取 {path}: {e}", file=sys.stderr)
            return 2
        texts.append(t)
        non_ws, _ = sf.count_chars(t)
        total += non_ws
        sources.append(f"{os.path.basename(path)}（{non_ws} 字）")

    try:
        tolerance = sf.parse_tolerance(args.tolerance)
    except ValueError as e:
        print(f"错误：--tolerance 解析失败：{e}", file=sys.stderr)
        return 2

    combined = "\n\n".join(texts)
    metrics = sf.compute_six_dimensions(combined)
    title = args.title or "对标书文风指纹"
    md = sf.format_anchor_md(metrics, tolerance, title=title, sources=sources)
    _emit(md, args.output, "文风指纹", is_md=True)
    return 0


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------
def _emit(content, output, kind, is_md=False):
    if output:
        out_dir = os.path.dirname(os.path.abspath(output))
        os.makedirs(out_dir, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"已生成{kind}：{output}")
    else:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="拆文辅助工具：stats / structure / rhythm / fingerprint")
    sub = ap.add_subparsers(dest="command", required=True)

    def add_files(p, with_output=True):
        p.add_argument("files", nargs="+", help="对标书章节文件（可多个）")
        if with_output:
            p.add_argument("--output", "-o", default=None, help="输出 Markdown 文件；不指定则打印到 stdout")

    p_stats = sub.add_parser("stats", help="统计对标书量化数据")
    add_files(p_stats)
    p_stats.set_defaults(func=cmd_stats)

    p_st = sub.add_parser("structure", help="逐章结构分析")
    add_files(p_st)
    p_st.set_defaults(func=cmd_structure)

    p_rh = sub.add_parser("rhythm", help="节奏档位分析")
    add_files(p_rh)
    p_rh.set_defaults(func=cmd_rhythm)

    p_fp = sub.add_parser("fingerprint", help="提取文风指纹（六维）")
    add_files(p_fp)
    p_fp.add_argument("--title", default=None, help="文风指纹标题（默认“对标书文风指纹”）")
    p_fp.add_argument("--tolerance", default=None,
                      help="容差，逗号分隔：句长,对话占比,段落,标点节奏,句式偏好（默认 3,5,10,2,0.2）")
    p_fp.set_defaults(func=cmd_fingerprint)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
