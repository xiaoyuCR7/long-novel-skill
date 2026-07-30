#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resume.py — 会话恢复报告（纯标准库，无第三方依赖）。

每次开工先跑它，把「写到哪了 / 欠什么账 / 下一章是什么」一次说清，
替代人工逐个翻追踪文件。这就是 chapter-loop 里「欠账门」的机器查验。

检查项：
  1. 进度：正文/ 最新一章是第几章（按文件名「第N章」排序）
  2. 门禁：最新一章的 追踪/门禁/gate_ch{N}.json 是否存在、是否通过、
     正文过闸后是否被改动（mtime 比对）、节奏段是否通过
  3. 追踪同步：章节摘要.md 是否有第 N 章条目；节奏配额.md 是否有第 N 章记录；
     伏笔台账是否有 🔴 超期项
  4. 下一章：第 N+1 章的章纲是否已建（大纲/章纲_第NNN章.md，兼容不补零写法）

用法：
  python3 scripts/resume.py "{书名目录}"
  python3 scripts/resume.py . --json

退出码：0 = 无欠账，可直接开写；1 = 有欠账（报告里列出补账步骤）；2 = 参数错误。
"""

import argparse
import glob
import json
import os
import re
import sys

CHAPTER_FILE_RE = re.compile(r"第\s*(\d+)\s*章")


def find_last_chapter(book_root):
    """返回 (章号, 文件名) 或 (None, None)。"""
    prose_dir = os.path.join(book_root, "正文")
    chapters = []
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = CHAPTER_FILE_RE.search(os.path.basename(path))
        if m:
            chapters.append((int(m.group(1)), path))
    if not chapters:
        return None, None
    chapters.sort(key=lambda x: x[0])
    return chapters[-1]


def check_gate(book_root, chapter_no, chapter_path):
    """查验最新章门禁，返回 (欠账列表, 备注列表)。"""
    debts, notes = [], []
    gate_path = os.path.join(book_root, "追踪", "门禁", f"gate_ch{chapter_no}.json")
    if not os.path.isfile(gate_path):
        debts.append(f"第{chapter_no}章门禁状态缺失：跑 check_text.py --gate-report --gate-state 补账")
        return debts, notes
    try:
        with open(gate_path, "r", encoding="utf-8-sig") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        debts.append(f"第{chapter_no}章门禁文件损坏：{e}")
        return debts, notes
    if not state.get("passed"):
        debts.append(f"第{chapter_no}章门禁未通过（blocking={state.get('blocking')}）：先修再写")
    recorded = state.get("chapter_mtime")
    if recorded and chapter_path and os.path.isfile(chapter_path):
        if abs(os.stat(chapter_path).st_mtime - float(recorded)) > 1.0:
            debts.append(f"第{chapter_no}章正文在过闸后有改动：重跑门禁")
    rhythm = state.get("rhythm")
    if isinstance(rhythm, dict):
        if rhythm.get("passed") is False:
            debts.append(f"第{chapter_no}章节奏配额检查未通过（fails={rhythm.get('fails')}）")
        else:
            notes.append("节奏配额检查已通过")
    else:
        notes.append("无节奏检查记录（建议跑 rhythm_guard.py --gate-state）")
    return debts, notes


def check_tracking_sync(book_root, chapter_no):
    """检查追踪文件是否已回写最新章，返回 (欠账列表, 备注列表)。"""
    debts, notes = [], []
    tracking = os.path.join(book_root, "追踪")

    summary = os.path.join(tracking, "章节摘要.md")
    if os.path.isfile(summary):
        with open(summary, "r", encoding="utf-8-sig") as f:
            text = f.read()
        if re.search(rf"第\s*0*{chapter_no}\s*章", text):
            notes.append("章节摘要已回写")
        else:
            debts.append(f"章节摘要.md 缺第{chapter_no}章条目：按模板字段补记")
    else:
        notes.append("章节摘要.md 不存在（开书初期可忽略）")

    quota = os.path.join(tracking, "节奏配额.md")
    if os.path.isfile(quota):
        with open(quota, "r", encoding="utf-8-sig") as f:
            text = f.read()
        rows = [ln for ln in text.splitlines()
                if ln.strip().startswith("|") and re.match(rf"^\|\s*0*{chapter_no}\s*\|", ln.strip())]
        if rows:
            notes.append("节奏配额已回写")
        else:
            debts.append(f"节奏配额.md 缺第{chapter_no}章记录：补 A/B/C 触发 + 事件 + 档位")
    else:
        notes.append("节奏配额.md 不存在（开书初期可忽略）")

    ledger = os.path.join(tracking, "伏笔台账.md")
    if os.path.isfile(ledger):
        with open(ledger, "r", encoding="utf-8-sig") as f:
            text = f.read()
        section = None
        overdue = []
        for line in text.splitlines():
            h = re.match(r"^#{1,4}\s*(.+)", line)
            if h:
                t = h.group(1)
                section = "overdue" if ("🔴" in t or "超期" in t) else None
                continue
            if section == "overdue" and line.strip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] and cells[0] != "ID" and not set(cells[0]) <= set("-: "):
                    overdue.append(cells[0])
        if overdue:
            debts.append(f"伏笔台账有 {len(overdue)} 项 🔴 超期（{'、'.join(overdue)}）："
                         f"先给处理方案（回收/延期/弃坑需作者点头）")
        else:
            notes.append("伏笔台账无超期项")
    return debts, notes


def check_next_outline(book_root, next_no):
    """检查下一章章纲是否存在，返回 备注。"""
    outline_dir = os.path.join(book_root, "大纲")
    if not os.path.isdir(outline_dir):
        return "大纲/ 目录不存在"
    for name in os.listdir(outline_dir):
        m = re.match(rf"^章纲_第\s*0*{next_no}\s*章.*\.md$", name)
        if m:
            return f"第{next_no}章章纲已就位（大纲/{name}）"
    return f"第{next_no}章章纲未建：按 outline-system.md 滚动补纲后再写"


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="会话恢复报告：写到哪 / 欠什么账 / 下一章是什么")
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    report = {"book_root": book_root, "last_chapter": None, "next_chapter": None,
              "debts": [], "notes": []}

    last_no, last_path = find_last_chapter(book_root)
    if last_no is None:
        report["notes"].append("正文/ 还没有任何章节：项目处于开书/备纲阶段")
        report["next_chapter"] = 1
        report["notes"].append(check_next_outline(book_root, 1))
    else:
        report["last_chapter"] = last_no
        report["next_chapter"] = last_no + 1
        d1, n1 = check_gate(book_root, last_no, last_path)
        d2, n2 = check_tracking_sync(book_root, last_no)
        report["debts"] = d1 + d2
        report["notes"] = n1 + n2
        report["notes"].append(check_next_outline(book_root, last_no + 1))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 20 + " 会话恢复报告 " + "=" * 20)
        print(f"书籍工程：{book_root}")
        if report["last_chapter"]:
            print(f"进度：已写完第 {report['last_chapter']} 章 → 下一章第 {report['next_chapter']} 章")
        else:
            print("进度：尚无正文（开书/备纲阶段）")
        print()
        if report["debts"]:
            print(f"【欠账 {len(report['debts'])} 项——先补账再开写】")
            for d in report["debts"]:
                print(f"  ⛔ {d}")
            print()
        else:
            print("【无欠账】可开写下一章")
            print()
        if report["notes"]:
            print("【状态备注】")
            for n in report["notes"]:
                print(f"  · {n}")
        print("=" * 54)

    return 1 if report["debts"] else 0


if __name__ == "__main__":
    sys.exit(main())
