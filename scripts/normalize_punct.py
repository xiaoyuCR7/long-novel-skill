#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize_punct.py — 标点归一化（纯标准库，无第三方依赖）。

清理正文里的非功能性标点，让停顿用动作/短句/换行表达，而不是符号堆砌：
  1. 省略号 ……/…/。。。 → 句号或逗号（盐言「」引号本身不动）
  2. 破折号 ——/— → 逗号或句号（-- 双连字符 → 逗号）
  3. 感叹/疑问堆叠：!!!→！ ???→？ ！!→！ ？？→？
  4. 独立分隔线（——— / *** / --- / === 整行）→ 删除该行
  5. 全角空格 → 半角；行尾空白清除

默认改写模式（就地写回文件，写前自动留 .bak 备份一次）；--check 只报告不修改。
--quote-mode keep（默认）不改动引号字符本身；「」与 "" 都保留原样。

用法：
  python3 scripts/normalize_punct.py "正文/第037章_标题.md"           # 就地归一化
  python3 scripts/normalize_punct.py "正文/第037章_标题.md" --check   # 只报告
  python3 scripts/normalize_punct.py a.md b.md --check

退出码：0 = 无需处理/处理完成；1 = --check 模式有命中；2 = 参数/文件错误。
"""

import argparse
import os
import re
import sys

ELLIPSIS_RE = re.compile(r"…{1,}|\.{3,}|。{2,}")
DASH_RE = re.compile(r"——{0,}|—–|–—")
DOUBLE_HYPHEN_RE = re.compile(r"--")
BANG_RE = re.compile(r"！{2,}|!{2,}|！!|!！")
QUESTION_RE = re.compile(r"？{2,}|\?{2,}|？\?|\?？")
SEPARATOR_LINE_RE = re.compile(r"^\s*(?:——{2,}|—{3,}|\*{3,}|-{3,}|={3,}|_{3,})\s*$")
FULL_SPACE_RE = re.compile(r"　")
TRAIL_WS_RE = re.compile(r"[ \t]+$", re.M)


def normalize_text(text):
    """返回 (新文本, 命中统计 dict)。"""
    stats = {"ellipsis": 0, "dash": 0, "double_hyphen": 0, "bang": 0,
             "question": 0, "separator_line": 0, "full_space": 0}

    lines = text.splitlines(keepends=True)
    kept = []
    for ln in lines:
        if SEPARATOR_LINE_RE.match(ln.rstrip("\r\n")):
            stats["separator_line"] += 1
            continue
        kept.append(ln)
    text = "".join(kept)

    def _ellipsis_sub(m):
        stats["ellipsis"] += 1
        return "。"
    text = ELLIPSIS_RE.sub(_ellipsis_sub, text)

    def _dash_sub(m):
        stats["dash"] += 1
        return "，"
    text = DASH_RE.sub(_dash_sub, text)

    def _dhyph_sub(m):
        stats["double_hyphen"] += 1
        return "，"
    text = DOUBLE_HYPHEN_RE.sub(_dhyph_sub, text)

    def _bang_sub(m):
        stats["bang"] += 1
        return "！"
    text = BANG_RE.sub(_bang_sub, text)

    def _q_sub(m):
        stats["question"] += 1
        return "？"
    text = QUESTION_RE.sub(_q_sub, text)

    def _fs_sub(m):
        stats["full_space"] += 1
        return " "
    text = FULL_SPACE_RE.sub(_fs_sub, text)

    text = TRAIL_WS_RE.sub("", text)

    # 归一化可能产生的连续标点：。。→。 ，。→。 ，，→，
    text = re.sub(r"。{2,}", "。", text)
    text = re.sub(r"，。", "。", text)
    text = re.sub(r"，{2,}", "，", text)
    return text, stats


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="标点归一化：省略号/破折号/感叹堆叠/分隔线清理")
    ap.add_argument("files", nargs="+", help="正文文件路径（UTF-8）")
    ap.add_argument("--check", action="store_true", help="只报告不修改")
    ap.add_argument("--quote-mode", choices=["keep"], default="keep",
                    help="引号处理模式（当前仅 keep：不动引号字符本身）")
    args = ap.parse_args()

    any_hits = False
    for path in args.files:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except OSError as e:
            print(f"错误：无法读取文件 {path}: {e}", file=sys.stderr)
            return 2

        new_text, stats = normalize_text(text)
        total = sum(stats.values())
        name = os.path.basename(path)
        if total == 0:
            print(f"{name}：无需处理")
            continue
        any_hits = True
        detail = "、".join(f"{k}={v}" for k, v in stats.items() if v)
        if args.check:
            print(f"{name}：命中 {total} 处（{detail}）")
        else:
            bak = path + ".bak"
            if not os.path.exists(bak):
                try:
                    with open(bak, "w", encoding="utf-8") as f:
                        f.write(text)
                except OSError as e:
                    print(f"警告：备份失败 {bak}: {e}", file=sys.stderr)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_text)
            except OSError as e:
                print(f"错误：无法写回文件 {path}: {e}", file=sys.stderr)
                return 2
            print(f"{name}：已归一化 {total} 处（{detail}），备份：{os.path.basename(bak)}")

    if args.check and any_hits:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
