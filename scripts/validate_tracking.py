#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_tracking.py — 追踪文件格式校验器（纯标准库，无第三方依赖）。

模型写歪格式的代价是下游脚本（check_text/rhythm_guard/resume）静默漏检。
本工具把五个追踪文件的约定格式变成可校验的 schema，写歪了能立刻发现：

  追踪/伏笔台账.md  四节齐备（🔴🟡🟢✅）、表格列数正确、ID 形如 F1-03、
                    埋设章节为数字、🟡 表「预期回收」可解析（数字或含「卷」）
  追踪/节奏配额.md  三节齐备（A/B/C 配额 / 事件冷却 / 档位）、章节为数字、
                    配额字母 ∈ {A,B,C}、事件类型 ∈ 已知六类、档位 ∈ {快,慢,中}
  追踪/章节摘要.md  有「近 10 章详记」节；每个 ### 第N章 条目含七个必填字段
  追踪/角色状态.md  每个 ## 角色 节含四个必填字段
  追踪/时间线.md    表格行列数 ≥4、首列含章号

用法：
  python3 scripts/validate_tracking.py "{书名目录}"
  python3 scripts/validate_tracking.py . --file "追踪/伏笔台账.md"

退出码：0 = 全部合格（或文件不存在）；1 = 有格式问题；2 = 参数错误。
"""

import argparse
import os
import re
import sys

EVENT_TYPES = {"conflict_thrill", "bond_deepening", "faction_building",
               "world_painting", "tension_escalation", "revelation"}
GEARS = {"快", "慢", "中"}
LEDGER_ID_RE = re.compile(r"^F\d+-\d+$")

# 伏笔台账四节：节标题关键词 → 期望列数
LEDGER_SECTIONS = [
    ("🔴", "超期", 6),
    ("🟡", "活跃", 6),
    ("🟢", "长线", 5),
    ("✅", "已回收", 6),
]

SUMMARY_REQUIRED_FIELDS = ["发生了什么", "状态变化", "伏笔进出", "新登场",
                           "关键实体", "承上", "启下"]
CHARACTER_REQUIRED_FIELDS = ["当前身份", "当前能力", "关键关系", "状态变更记录"]


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _table_rows(lines, start_idx):
    """从 start_idx 起收集连续表格行。"""
    rows = []
    for i in range(start_idx, len(lines)):
        if lines[i].strip().startswith("|"):
            rows.append((i + 1, lines[i]))
        elif rows:
            break
    return rows


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_sep_row(cells):
    return cells and set(cells[0]) <= set("-: ")


def validate_ledger(path):
    issues = []
    text = _read(path)
    lines = text.splitlines()

    found = {}
    section = None
    for i, line in enumerate(lines):
        h = re.match(r"^#{1,4}\s*(.+)", line)
        if h:
            t = h.group(1)
            section = None
            for icon, name, cols in LEDGER_SECTIONS:
                if icon in t or name in t:
                    section = (icon, name, cols)
                    found[name] = True
                    break
            continue
        if section and line.strip().startswith("|"):
            cells = _cells(line)
            if not cells or cells[0] in ("ID", "") or _is_sep_row(cells):
                continue
            icon, name, cols = section
            if len(cells) != cols:
                issues.append(f"第{i + 1}行 [{name}] 列数 {len(cells)} ≠ 模板 {cols}：{line.strip()[:40]}")
                continue
            fid = cells[0]
            if not LEDGER_ID_RE.match(fid):
                issues.append(f"第{i + 1}行 [{name}] ID「{fid}」不合规（应为 F{{卷}}-{{序号}}，如 F1-03）")
            if name in ("超期", "活跃", "长线", "已回收") and cells[2] and not re.search(r"\d+", cells[2]):
                issues.append(f"第{i + 1}行 [{name}] 埋设章节「{cells[2]}」无数字")
            if name == "活跃":
                expect = cells[3]
                if expect and not re.search(r"\d+", expect) and "卷" not in expect:
                    issues.append(f"第{i + 1}行 [活跃] 预期回收「{expect}」无法解析（应为章号或含「卷」）")

    for _, name, _ in LEDGER_SECTIONS:
        if name not in found:
            issues.append(f"缺少必备分节：{name}（伏笔台账必须四节齐备）")
    return issues


def validate_quota(path):
    issues = []
    text = _read(path)
    lines = text.splitlines()

    required = {"quota": False, "events": False, "gears": False}
    section = None
    for i, line in enumerate(lines):
        h = re.match(r"^#{1,6}\s*(.+)", line)
        if h:
            t = h.group(1)
            if ("A/B/C" in t or "ABC" in t) and "配额" in t:
                section = "quota"
                required["quota"] = True
            elif "事件" in t and "冷却" in t:
                section = "events"
                required["events"] = True
            elif "档位" in t:
                section = "gears"
                required["gears"] = True
            else:
                section = None
            continue
        if not section or not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if not cells or _is_sep_row(cells) or cells[0] in ("章节", "章"):
            continue
        if not re.search(r"\d+", cells[0]):
            issues.append(f"第{i + 1}行 [{section}] 章节列「{cells[0]}」无数字")
            continue
        if section == "quota":
            letters = set(re.findall(r"[ABC]", cells[1] if len(cells) > 1 else ""))
            if not letters:
                issues.append(f"第{i + 1}行 [配额] 配额列「{cells[1] if len(cells) > 1 else ''}」无 A/B/C")
        elif section == "events":
            ev = cells[1] if len(cells) > 1 else ""
            if ev and ev not in EVENT_TYPES:
                issues.append(f"第{i + 1}行 [事件] 事件类型「{ev}」不在已知六类：{sorted(EVENT_TYPES)}")
        elif section == "gears":
            g = (cells[1] if len(cells) > 1 else "").replace("档", "").strip()
            if g and g not in GEARS:
                issues.append(f"第{i + 1}行 [档位] 档位「{cells[1]}」应为 快/慢/中")

    names = {"quota": "A/B/C 配额记录", "events": "事件冷却记录", "gears": "档位记录"}
    for key, ok in required.items():
        if not ok:
            issues.append(f"缺少必备分节：{names[key]}")
    return issues


def validate_summary(path):
    issues = []
    text = _read(path)
    if "近 10 章详记" not in text and "近10章详记" not in text:
        issues.append("缺少必备分节：近 10 章详记")
    # 逐条 ### 第N章 检查七个必填字段
    entries = list(re.finditer(r"^###\s*第\s*(\d+)\s*章.*$", text, re.M))
    for idx, m in enumerate(entries):
        start = m.end()
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        body = text[start:end]
        for field in SUMMARY_REQUIRED_FIELDS:
            if field not in body:
                issues.append(f"第{m.group(1)}章摘要条目缺字段：{field}")
    return issues


def validate_character_state(path):
    issues = []
    text = _read(path)
    entries = list(re.finditer(r"^##\s*(.+?)\s*$", text, re.M))
    for idx, m in enumerate(entries):
        name = m.group(1)
        if "{" in name:  # 模板占位行
            continue
        start = m.end()
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        body = text[start:end]
        for field in CHARACTER_REQUIRED_FIELDS:
            if field not in body:
                issues.append(f"角色「{name}」缺字段：{field}")
    return issues


def validate_timeline(path):
    issues = []
    lines = _read(path).splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if not cells or _is_sep_row(cells) or "章节" in cells[0]:
            continue
        if len(cells) < 4:
            issues.append(f"第{i + 1}行 列数 {len(cells)} < 4（章节/故事内时间/事件/时间标记）")
        elif not re.search(r"\d+", cells[0]):
            issues.append(f"第{i + 1}行 首列「{cells[0]}」无章号")
    return issues


VALIDATORS = {
    "伏笔台账.md": validate_ledger,
    "节奏配额.md": validate_quota,
    "章节摘要.md": validate_summary,
    "角色状态.md": validate_character_state,
    "时间线.md": validate_timeline,
}


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="追踪文件格式校验器")
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--file", default=None,
                    help="只校验单个文件（如 追踪/伏笔台账.md）")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    targets = []
    if args.file:
        base = os.path.basename(args.file)
        if base not in VALIDATORS:
            print(f"错误：{base} 不在可校验的追踪文件清单：{sorted(VALIDATORS)}", file=sys.stderr)
            return 2
        targets.append((base, os.path.join(book_root, args.file)))
    else:
        for base in VALIDATORS:
            targets.append((base, os.path.join(book_root, "追踪", base)))

    total_issues = 0
    for base, path in targets:
        if not os.path.isfile(path):
            print(f"· {base}：不存在（跳过）")
            continue
        issues = VALIDATORS[base](path)
        if issues:
            total_issues += len(issues)
            print(f"⛔ {base}：{len(issues)} 个格式问题")
            for msg in issues:
                print(f"    {msg}")
        else:
            print(f"✓ {base}：格式合格")

    print()
    if total_issues:
        print(f"结果：{total_issues} 个格式问题（写歪的格式会让下游脚本静默漏检，先修再写）")
        return 1
    print("结果：全部合格")
    return 0


if __name__ == "__main__":
    sys.exit(main())
