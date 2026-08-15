#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plot_suggest.py — 基于记忆的情节建议引擎（纯标准库，模板合成，无 LLM）。

输入：未回收伏笔（伏笔台账.md）+ 大纲锚点进度（outline_anchors.json）+ 节奏配额 + 角色状态。
输出：下一章 3 个情节方向，每个方向标注「回收哪条伏笔 / 触发哪个锚点 / 推进哪条角色线 /
对应节奏档位」。纯结构化聚合，不做 LLM 情节生成（避免幻觉），给作者/Agent 做方向参考。

用法：
  python scripts/plot_suggest.py "{书名目录}" --chapter 6
  python scripts/plot_suggest.py "{书名目录}" --chapter 6 --json
"""

import argparse
import json
import os
import re
import sys


def _ensure_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _read(path):
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


def _extract_unresolved_foreshadows(text):
    """提取未回收/进行中的伏笔 [(id, 内容行), ...]。兼容新旧台账格式。"""
    result = []
    for line in text.splitlines():
        if not any(k in line for k in ("🔴", "🟡", "未回收", "进行中", "待回收")):
            continue
        m = re.search(r"(F\d+(?:-\d+)?)", line)
        if m:
            content = re.sub(r"^\s*[|#\-]+\s*", "", line).strip()
            content = re.sub(r"\s*[|]\s*$", "", content)
            result.append((m.group(1), content[:80]))
    return result


def _extract_forecast(text):
    """提取回收计划 {伏笔id: 预计回收章号}（只匹配「预计第N章」的回收计划行）。"""
    result = {}
    for line in text.splitlines():
        m = re.search(r"(F\d+(?:-\d+)?).*?预计第\s*(\d+)\s*章", line)
        if m:
            result[m.group(1)] = int(m.group(2))
    return result


def _read_anchors(book_root):
    p = os.path.join(book_root, "大纲", "outline_anchors.json")
    txt = _read(p)
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except (ValueError, TypeError):
        return {}


def _anchor_constraints(anchors, target_chapter):
    """从锚点 JSON 提取当前章可用的约束。"""
    out = {}
    vol = {}
    for v in anchors.get("volumes", []) or []:
        s, e = v.get("chapter_start"), v.get("chapter_end")
        if s is not None and e is not None and s <= target_chapter <= e:
            vol = v
            break
    out["progress_pct"] = anchors.get("progress_pct", vol.get("progress_pct"))
    out["must_achieve"] = vol.get("must_achieve", []) or anchors.get("must_achieve", [])
    out["must_not_reveal"] = vol.get("must_not_reveal", []) or anchors.get("must_not_reveal", [])
    out["foreshadows_to_plant"] = vol.get("foreshadows_to_plant", []) or anchors.get("foreshadows_to_plant", [])
    return out


def _recent_pacing(book_root):
    lines = _read(os.path.join(book_root, "追踪", "节奏配额.md")).splitlines()
    out = []
    for line in lines:
        if re.search(r"第\s*\d+\s*章", line) and re.search(r"[ABC]档|快|慢|中", line):
            out.append(re.sub(r"\s+", " ", line).strip())
    return out[-5:]


def _recent_char_changes(book_root):
    lines = _read(os.path.join(book_root, "追踪", "角色状态.md")).splitlines()
    out = []
    for line in lines:
        if re.search(r"第\s*\d+\s*章", line) and "|" not in line:
            out.append(re.sub(r"^\s*[-*]\s*", "", line).strip())
    return out[-10:]


def _synthesize(foreshadows, forecast, anchors, pacing, char_changes, target_chapter):
    suggestions = []
    must_achieve = anchors.get("must_achieve") or []
    must_not = anchors.get("must_not_reveal") or []

    # 方向 1：主线推进（大纲锚点）
    d1 = {"direction": "主线推进", "pacing": "快/A",
          "anchor": must_achieve[0] if must_achieve else "推进当前卷核心目标",
          "avoid": must_not[0] if must_not else None,
          "foreshadow": None, "character": None}
    suggestions.append(d1)

    # 方向 2：伏笔回收（选回收计划最近的未回收伏笔）
    d2 = {"direction": "伏笔回收", "pacing": "中/B",
          "anchor": None, "avoid": None, "foreshadow": None, "character": None}
    candidates = []
    for fid, content in foreshadows:
        target = forecast.get(fid)
        if target:
            candidates.append((abs(target - target_chapter), fid, content, target))
    candidates.sort(key=lambda x: x[0])
    if candidates:
        _, fid, content, target = candidates[0]
        d2["foreshadow"] = fid
        d2["reason"] = f"伏笔 {fid} 预计第{target}章回收，当前第{target_chapter}章临近"
    elif foreshadows:
        fid, content = foreshadows[0]
        d2["foreshadow"] = fid
        d2["reason"] = f"伏笔 {fid} 长期未回收，可安排推进"
    suggestions.append(d2)

    # 方向 3：角色线/节奏调剂
    d3 = {"direction": "人物线推进", "pacing": "慢/缓冲",
          "anchor": None, "avoid": None, "foreshadow": None, "character": None}
    if char_changes:
        d3["character"] = char_changes[-1]
    if pacing:
        # 最近连续高强度 → 建议缓冲
        recent = "".join(pacing[-2:])
        if recent.count("快") >= 2 or recent.count("A") >= 2:
            d3["direction"] = "节奏缓冲"
            d3["pacing"] = "慢/世界/日常"
    suggestions.append(d3)

    return suggestions


def cmd_suggest(book_root, target_chapter):
    ledger_text = _read(os.path.join(book_root, "追踪", "伏笔台账.md"))
    foreshadows = _extract_unresolved_foreshadows(ledger_text)
    forecast = _extract_forecast(ledger_text)
    anchors = _anchor_constraints(_read_anchors(book_root), target_chapter)
    pacing = _recent_pacing(book_root)
    char_changes = _recent_char_changes(book_root)
    suggestions = _synthesize(foreshadows, forecast, anchors, pacing, char_changes, target_chapter)
    return {
        "target_chapter": target_chapter,
        "unresolved_foreshadows": [fid for fid, _ in foreshadows],
        "progress_pct": anchors.get("progress_pct"),
        "suggestions": suggestions,
    }


def _write_md(book_root, result):
    lines = ["# 下一章情节建议", "",
             f"> 目标章节：第{result['target_chapter']}章",
             f"> 未回收伏笔：{len(result['unresolved_foreshadows'])} 条（{'、'.join(result['unresolved_foreshadows'][:8]) or '无'}）",
             f"> 全书进度：{result.get('progress_pct') or '未知'}", ""]
    for i, s in enumerate(result["suggestions"], 1):
        lines.append(f"## 方向 {i}：{s['direction']}")
        lines.append(f"- 节奏档位：{s['pacing']}")
        if s.get("anchor"):
            lines.append(f"- 大纲锚点（必须达成）：{s['anchor']}")
        if s.get("avoid"):
            lines.append(f"- 禁止揭露：{s['avoid']}")
        if s.get("foreshadow"):
            lines.append(f"- 伏笔回收：{s['foreshadow']}")
        if s.get("reason"):
            lines.append(f"- 依据：{s['reason']}")
        if s.get("character"):
            lines.append(f"- 角色线参考：{s['character']}")
        lines.append("")
    out = os.path.join(book_root, "追踪", "next_plot_suggestion.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out


def main():
    _ensure_utf8()
    ap = argparse.ArgumentParser(description="基于记忆的情节建议引擎（模板合成，无 LLM）")
    ap.add_argument("book_dir", help="书籍工程目录")
    ap.add_argument("--chapter", type=int, required=True, help="目标章节号")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    book_root = os.path.abspath(args.book_dir)
    result = cmd_suggest(book_root, args.chapter)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    out = _write_md(book_root, result)
    print(f"=== 下一章情节建议 — 第{args.chapter}章 ===")
    print(f"未回收伏笔：{len(result['unresolved_foreshadows'])} 条")
    if result.get("progress_pct") is not None:
        print(f"全书进度：{result['progress_pct']}")
    print()
    for i, s in enumerate(result["suggestions"], 1):
        print(f"方向 {i}：{s['direction']}（节奏：{s['pacing']}）")
        if s.get("anchor"): print(f"  锚点：{s['anchor']}")
        if s.get("avoid"): print(f"  禁揭：{s['avoid']}")
        if s.get("foreshadow"): print(f"  伏笔：{s['foreshadow']}")
        if s.get("reason"): print(f"  依据：{s['reason']}")
        if s.get("character"): print(f"  角色线：{s['character']}")
        print()
    print(f"已写入：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
