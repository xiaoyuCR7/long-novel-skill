#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""event_system.py — 统一事件调度系统 v1.0.0（纯标准库）。

合并 rhythm_guard.py（节奏配额检查）+ event_matrix.py（事件矩阵调度）。
单一定义事件类型/冷却值/gentle_window，消除两处硬编码重复。

子命令：
  check     — 节奏配额检查（A/B/C越界+冷却+档位+gentle_window）
  recommend — 为下一章推荐事件类型分配
  record    — 记录本章事件类型，更新冷却状态
  status    — 显示当前冷却状态和 gentle_window 进度
  quota     — A/B/C 配额视图

用法：
  python scripts/event_system.py check "{书名目录}" --chapter N --declare "A,conflict,快"
  python scripts/event_system.py recommend "{书名目录}" --gear 快 --chapter N
  python scripts/event_system.py record "{书名目录}" --event conflict --chapter N
  python scripts/event_system.py status "{书名目录}"
  python scripts/event_system.py quota "{书名目录}"

退出码：0 = 成功；1 = 有违规/警告；2 = 参数/文件错误。
"""

import argparse
import datetime
import json
import os
import re
import sys

# --- 事件类型定义（单源真相） ---

EVENT_TYPES = ["conflict", "bond", "faction", "world", "crisis", "revelation"]

EVENT_META = {
    "conflict": {"name": "冲突爽点", "cooldown": 2, "consecutive_limit": 2, "quota": "A",
                  "desc": "打脸/对决/爽点爆发"},
    "bond": {"name": "人物羁绊", "cooldown": 3, "consecutive_limit": 3, "quota": "B",
              "desc": "师徒/友情/情感深化"},
    "faction": {"name": "势力经营", "cooldown": 4, "consecutive_limit": 2, "quota": None,
                 "desc": "宗门/势力/组织运作"},
    "world": {"name": "风土人情", "cooldown": 3, "consecutive_limit": 2, "quota": None,
               "desc": "世界观/风物/民俗"},
    "crisis": {"name": "危机升级", "cooldown": 2, "consecutive_limit": 2, "quota": None,
                "desc": "威胁逼近/压力升级"},
    "revelation": {"name": "核心秘密", "cooldown": 5, "consecutive_limit": 1, "quota": "C",
                    "desc": "身世/真相/核心揭秘"},
}

GENTLE_WINDOW_SIZE = 5
GENTLE_WINDOW_TYPES = ("bond", "world")
QUOTA_TO_EVENT = {"A": "conflict", "B": "bond", "C": "revelation"}
EVENT_TO_QUOTA = {ev: meta["quota"] for ev, meta in EVENT_META.items() if meta["quota"]}

EVENT_ALIASES = {
    "conflict_thrill": "conflict", "bond_deepening": "bond",
    "faction_building": "faction", "world_painting": "world",
    "tension_escalation": "crisis", "revelation": "revelation",
}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def normalize_event(event):
    if not event: return None
    event = event.strip()
    if event in EVENT_TYPES: return event
    if event in EVENT_ALIASES: return EVENT_ALIASES[event]
    for alias, canonical in EVENT_ALIASES.items():
        if alias.startswith(event) or event.startswith(alias.split("_")[0]):
            return canonical
    return None


def _matrix_path(book_root):
    return os.path.join(book_root, "追踪", "event_matrix.json")


def load_matrix(book_root):
    path = _matrix_path(book_root)
    if not os.path.isfile(path):
        return {"records": [], "last_updated": None}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if "records" not in data: data["records"] = []
        return data
    except (OSError, ValueError):
        return {"records": [], "last_updated": None}


def save_matrix(book_root, data):
    path = _matrix_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def get_cooldown_status(data, current_chapter):
    records = data.get("records", [])
    status = {}
    for ev in EVENT_TYPES:
        meta = EVENT_META[ev]
        cd = meta["cooldown"]; limit = meta["consecutive_limit"]
        last = max((c for c, e in records if e == ev), default=None)
        consecutive = 0
        sorted_records = sorted([c for c, e in records if e == ev], reverse=True)
        check_chap = (current_chapter - 1) if current_chapter else (max((c for c, _ in records), default=0))
        for c in sorted_records:
            if c == check_chap: consecutive += 1; check_chap -= 1
            else: break
        if last is None:
            remaining = 0; available = True
        else:
            latest_chap = max((c for c, _ in records), default=0)
            gap = latest_chap - last
            remaining = max(0, cd - gap)
            available = remaining == 0
        status[ev] = {"name": meta["name"], "available": available,
                       "remaining_cooldown": remaining, "last_chapter": last,
                       "consecutive": consecutive, "consecutive_limit": limit,
                       "quota": meta["quota"]}
    return status


def check_gentle_window(data, current_chapter):
    records = data.get("records", [])
    window_start = current_chapter - GENTLE_WINDOW_SIZE + 1
    if window_start < 1: window_start = 1
    window_events = [(c, e) for c, e in records
                     if window_start <= c <= current_chapter and e in GENTLE_WINDOW_TYPES]
    if not window_events:
        if current_chapter < GENTLE_WINDOW_SIZE:
            return True, f"前{current_chapter}章尚在初始窗口（未满{GENTLE_WINDOW_SIZE}章）", []
        return False, f"gentle_window 未满足：第{window_start}-{current_chapter}章无 bond 或 world", []
    return True, f"gentle_window 已满足：{len(window_events)}次 bond/world", window_events


def recommend_events(data, gear, next_chapter):
    status = get_cooldown_status(data, next_chapter)
    gentle_ok, _, _ = check_gentle_window(data, next_chapter - 1)
    gentle_needed = not gentle_ok
    gear_priority = {
        "快": ["conflict", "crisis", "revelation", "faction", "bond", "world"],
        "中": ["bond", "faction", "world", "conflict", "crisis", "revelation"],
        "慢": ["world", "bond", "faction", "conflict", "crisis", "revelation"],
    }
    priority = gear_priority.get(gear, gear_priority["中"])
    available_list, cooling_list = [], []
    for ev in priority:
        s = status[ev]
        if s["available"]:
            reasons = ["已冷却完毕"]
            if s["last_chapter"]: reasons.append(f"上次第{s['last_chapter']}章")
            if ev in GENTLE_WINDOW_TYPES and gentle_needed: reasons.append("gentle_window 需求")
            if ev == "conflict" and gear == "快": reasons.append("快档首选")
            if ev == "world" and gear == "慢": reasons.append("慢档首选")
            if ev == "bond" and gear in ("中", "慢"): reasons.append("中慢档适合")
            if ev == "revelation": reasons.append("核心秘密需谨慎")
            available_list.append((ev, "；".join(reasons)))
        else:
            cooling_list.append((ev, f"冷却中（还需{s['remaining_cooldown']}章）"))
    return available_list + cooling_list


def record_event(data, chapter_no, event):
    ev = normalize_event(event)
    if not ev: return False, [f"无法识别事件类型「{event}」"]
    records = [(c, e) for c, e in data.get("records", []) if c != chapter_no]
    msgs = []
    meta = EVENT_META[ev]
    status = get_cooldown_status(data, chapter_no)
    s = status[ev]
    if not s["available"]:
        msgs.append(f"[WARN] {ev}（{meta['name']}）仍在冷却期（还需{s['remaining_cooldown']}章）")
    if s["consecutive"] + 1 > meta["consecutive_limit"]:
        msgs.append(f"[WARN] {ev} 将超过连续上限 {meta['consecutive_limit']}")
    records.append((chapter_no, ev))
    records.sort(key=lambda x: x[0])
    data["records"] = records
    return True, msgs


# ---------------------------------------------------------------------------
# A/B/C 配额检查（来自 rhythm_guard）
# ---------------------------------------------------------------------------

def _parse_quota_md(quota_path):
    """解析 追踪/节奏配额.md 的 A/B/C 配额记录和事件冷却记录。"""
    if not os.path.isfile(quota_path):
        return [], [], []
    with open(quota_path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    # A/B/C 配额记录
    quota_section = re.search(r"##\s*A/B/C\s*配额记录(.*?)(?=##|\Z)", text, re.S)
    quota_records = []
    if quota_section:
        for line in quota_section.group(1).split("\n"):
            m = re.match(r"\|\s*(\d+)\s*\|\s*([ABC])\s*\|(.*?)\|", line)
            if m: quota_records.append((int(m.group(1)), m.group(2), m.group(3).strip()))
    # 事件冷却记录
    event_section = re.search(r"##\s*事件冷却记录(.*?)(?=##|\Z)", text, re.S)
    event_records = []
    if event_section:
        for line in event_section.group(1).split("\n"):
            m = re.match(r"\|\s*(\d+)\s*\|\s*(\S+)\s*\|(.*?)\|", line)
            if m: event_records.append((int(m.group(1)), m.group(2), m.group(3).strip()))
    # 档位记录
    gear_section = re.search(r"##\s*档位记录(.*?)(?=##|\Z)", text, re.S)
    gear_records = []
    if gear_section:
        for line in gear_section.group(1).split("\n"):
            m = re.match(r"\|\s*(\d+)\s*\|\s*(.{1,3})\s*\|", line)
            if m: gear_records.append((int(m.group(1)), m.group(2).strip()))
    return quota_records, event_records, gear_records


def check_quota(book_root, chapter, declare_str, quota_path=None):
    """检查 A/B/C 配额和事件冷却。
    declare_str: "A,conflict,快" 格式
    返回 (pass: bool, violations: list, warnings: list)
    """
    if quota_path is None:
        quota_path = os.path.join(book_root, "追踪", "节奏配额.md")
    quota_records, event_records, gear_records = _parse_quota_md(quota_path)
    matrix_data = load_matrix(book_root)

    # 解析声明
    parts = declare_str.split(",") if declare_str else []
    quota_declared = parts[0] if parts else None
    event_declared = normalize_event(parts[1]) if len(parts) > 1 else None
    gear_declared = parts[2] if len(parts) > 2 else None

    violations = []
    warnings = []

    # 1. A/B/C 越界检查
    if quota_declared and quota_declared in ("A", "B", "C"):
        recent_3 = [r for r in quota_records[-3:] if r[0] != chapter]
        same_quota = [r for r in recent_3 if r[1] == quota_declared]
        if len(same_quota) >= 1 and quota_declared == "A":
            violations.append(f"A 配额冷却中：近3章已有 A 类事件（{same_quota[-1][0]}章）")
        if len(same_quota) >= 1 and quota_declared == "B":
            violations.append(f"B 配额冷却中：近3章已有 B 类事件")
        if len(same_quota) >= 1 and quota_declared == "C":
            violations.append(f"C 配额越界：核心秘密类需隔5章以上")

    # 2. 档位检查
    if gear_declared and gear_records:
        last_gear = gear_records[-1][1] if gear_records else None
        if gear_declared == "快" and last_gear == "快":
            violations.append("连续快档：上一章已是快档，禁止连续快档")

    # 3. 事件冷却检查（优先使用 event_matrix.json）
    if event_declared:
        status = get_cooldown_status(matrix_data, chapter)
        s = status.get(event_declared)
        if s and not s["available"]:
            violations.append(f"{event_declared} 冷却中（还需{s['remaining_cooldown']}章）")
        if s and s["consecutive"] + 1 > s["consecutive_limit"]:
            violations.append(f"{event_declared} 连续上限：{s['consecutive'] + 1} > {s['consecutive_limit']}")

    # 4. gentle_window 检查
    gentle_ok, gentle_msg, _ = check_gentle_window(matrix_data, chapter)
    if not gentle_ok:
        warnings.append(gentle_msg)

    # 5. 慢档缺失检查
    if gear_records and chapter > 4:
        recent_4_gears = [g for _, g in gear_records[-4:]]
        if "慢" not in recent_4_gears:
            warnings.append("近4章无慢档，建议安排风土人情/人物羁绊章节")

    return len(violations) == 0, violations, warnings


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_check(book_root, args):
    quota_path = getattr(args, 'quota_file', None)
    if quota_path is None:
        quota_path = os.path.join(book_root, "追踪", "节奏配额.md")
    passed, violations, warnings = check_quota(
        book_root, args.chapter, args.declare, quota_path)

    print(f"节奏配额检查（第{args.chapter}章）")
    if violations:
        print(f"  [FAIL] {len(violations)} 项违规：")
        for v in violations: print(f"    - {v}")
    if warnings:
        print(f"  [WARN] {len(warnings)} 项警告：")
        for w in warnings: print(f"    - {w}")
    if passed and not warnings:
        print("  [PASS] 全部通过")
    elif passed:
        print("  [PASS] 无违规（有警告）")

    # 同步写入 event_matrix.json（如声明了事件）
    parts = args.declare.split(",") if args.declare else []
    if len(parts) > 1 and normalize_event(parts[1]):
        data = load_matrix(book_root)
        ok, msgs = record_event(data, args.chapter, parts[1])
        if ok:
            save_matrix(book_root, data)
            print(f"  事件已自动同步至 event_matrix.json：{normalize_event(parts[1])}")

    return 0 if passed else 1


def cmd_recommend(book_root, args):
    data = load_matrix(book_root)
    gear = args.gear
    if gear not in ("快", "中", "慢"):
        print(f"错误：--gear 需为 快/中/慢", file=sys.stderr); return 2

    records = data.get("records", [])
    next_chap = args.chapter if args.chapter > 0 else (
        max((c for c, _ in records), default=0) + 1 if records else 1)

    print(f"事件推荐：第{next_chap}章（档位：{gear}）")
    gentle_ok, gentle_msg, _ = check_gentle_window(data, next_chap - 1 if next_chap > 1 else 1)
    print(f"gentle_window：{'满足' if gentle_ok else '未满足'} - {gentle_msg}\n")

    status = get_cooldown_status(data, next_chap)
    print("冷却状态：")
    for ev in EVENT_TYPES:
        s = status[ev]
        avail = "可用" if s["available"] else f"冷却中({s['remaining_cooldown']}章)"
        last = f"上次第{s['last_chapter']}章" if s["last_chapter"] else "未出现"
        print(f"  {ev:<12} {avail}  {last}  连续{s['consecutive']}/{s['consecutive_limit']}")
    print()

    recs = recommend_events(data, gear, next_chap)
    print("推荐（按优先级）：")
    for ev, reason in recs:
        meta = EVENT_META[ev]
        quota_tag = f"配额{meta['quota']}" if meta["quota"] else "无配额"
        print(f"  {ev:<12} ({meta['name']}, {quota_tag}, 冷却{meta['cooldown']}章) - {reason}")
    if recs:
        best = recs[0][0]
        print(f"\n建议：使用「{best}」（{EVENT_META[best]['name']}）")
    return 0


def cmd_record(book_root, args):
    if args.chapter <= 0:
        print("错误：需要 --chapter 指定章号", file=sys.stderr); return 2
    data = load_matrix(book_root)
    ok, msgs = record_event(data, args.chapter, args.event)
    if not ok: print(f"错误：{msgs[0]}", file=sys.stderr); return 2
    path = save_matrix(book_root, data)
    ev = normalize_event(args.event)
    print(f"已记录：第{args.chapter}章 {ev}（{EVENT_META[ev]['name']}）")
    for m in msgs: print(f"  {m}")
    print(f"  数据：{path}")
    return 0


def cmd_status(book_root, args):
    data = load_matrix(book_root)
    records = data.get("records", [])
    current = max((c for c, _ in records), default=0)
    print(f"事件系统状态（{len(records)}条记录，最新第{current}章）")
    if data.get("last_updated"): print(f"最后更新：{data['last_updated']}")
    next_chap = current + 1 if current else 1
    status = get_cooldown_status(data, next_chap)
    print("\n冷却状态：")
    for ev in EVENT_TYPES:
        s = status[ev]
        avail = "可用" if s["available"] else f"冷却中(还需{s['remaining_cooldown']}章)"
        last = f"上次第{s['last_chapter']}章" if s["last_chapter"] else "未出现"
        quota = f"[配额{s['quota']}]" if s["quota"] else ""
        print(f"  {ev:<12} ({s['name']}) {avail}  {last}  连续{s['consecutive']}/{s['consecutive_limit']}  {quota}")
    if current > 0:
        gentle_ok, gentle_msg, _ = check_gentle_window(data, current)
        print(f"\ngentle_window：{'满足' if gentle_ok else '未满足'} - {gentle_msg}")
    recent = sorted(records, key=lambda x: x[0])[-10:]
    if recent:
        print("\n最近记录：")
        for c, e in recent:
            meta = EVENT_META[e]
            quota_tag = f"[配额{meta['quota']}]" if meta.get('quota') else ""
            print(f"  第{c}章: {e}（{meta['name']}）{quota_tag}")
    return 0


def cmd_quota(book_root, args):
    quota_path = os.path.join(book_root, "追踪", "节奏配额.md")
    quota_records, event_records, gear_records = _parse_quota_md(quota_path)
    print("A/B/C 配额记录：")
    if quota_records:
        for chap, q, content in quota_records[-10:]:
            print(f"  第{chap}章: {q} - {content}")
    else:
        print("  （无记录）")
    print(f"\n档位记录（近5章）：")
    if gear_records:
        for chap, gear in gear_records[-5:]:
            print(f"  第{chap}章: {gear}")
    else:
        print("  （无记录）")
    data = load_matrix(book_root)
    records = data.get("records", [])
    if records:
        print(f"\n事件矩阵记录（{len(records)}条）：")
        for c, e in sorted(records, key=lambda x: x[0])[-10:]:
            print(f"  第{c}章: {e}")
    return 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="统一事件调度系统 v1.0.0")
    ap.add_argument("command", choices=["check", "recommend", "record", "status", "quota"])
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--chapter", type=int, default=0, help="章号")
    ap.add_argument("--declare", default="", help="check：声明 'A,conflict,快'")
    ap.add_argument("--gear", default=None, help="recommend：档位（快/中/慢）")
    ap.add_argument("--event", default=None, help="record：事件类型")
    ap.add_argument("--quota-file", default=None, help="check：节奏配额.md 路径（默认自动查找）")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)

    if args.command == "check":
        return cmd_check(book_root, args)
    elif args.command == "recommend":
        if not args.gear:
            print("错误：recommend 需要 --gear", file=sys.stderr); return 2
        return cmd_recommend(book_root, args)
    elif args.command == "record":
        if not args.event:
            print("错误：record 需要 --event", file=sys.stderr); return 2
        return cmd_record(book_root, args)
    elif args.command == "status":
        return cmd_status(book_root, args)
    elif args.command == "quota":
        return cmd_quota(book_root, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
