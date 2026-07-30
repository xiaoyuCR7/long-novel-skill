#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""event_matrix.py — 事件矩阵调度器 v1.0（纯标准库，无第三方依赖）。

5+1 类事件类型的节奏调度工具，独立于 rhythm_guard.py 运行，但与之双向兼容。

事件类型：
  conflict    (冲突爽点)   冷却2章，连续上限2   ← 映射 A
  bond        (人物羁绊)   冷却3章               ← 映射 B（部分）
  faction     (势力经营)   冷却4章
  world       (风土人情)   冷却3章
  crisis      (危机升级)   冷却2章
  revelation  (核心秘密)   冷却5章（C类升级）    ← 映射 C（部分）

gentle_window：每5章至少1次 bond 或 world，防止连续高强度章节导致读者疲劳。

数据持久化到 追踪/event_matrix.json。

与 rhythm_guard.py 的 A/B/C 配额双向兼容：
  conflict → A，bond → B 之一，revelation → C 之一

子命令：
  recommend  为下一章推荐事件类型分配（输入档位：快/中/慢）
  record     记录本章使用的事件类型，更新冷却状态
  status     显示当前冷却状态和 gentle_window 进度

用法：
  python scripts/event_matrix.py recommend "{书名目录}" --gear 快 --chapter 6
  python scripts/event_matrix.py record "{书名目录}" --event conflict --chapter 5
  python scripts/event_matrix.py status "{书名目录}"

退出码：0 = 成功；1 = 有违规/警告；2 = 参数/文件错误。
"""

import argparse
import datetime
import json
import os
import sys

# Windows 中文控制台兼容
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# 事件类型定义
EVENT_TYPES = ["conflict", "bond", "faction", "world", "crisis", "revelation"]

EVENT_META = {
    "conflict": {
        "name": "冲突爽点", "cooldown": 2, "consecutive_limit": 2,
        "quota": "A", "desc": "打脸/对决/爽点爆发",
    },
    "bond": {
        "name": "人物羁绊", "cooldown": 3, "consecutive_limit": 3,
        "quota": "B", "desc": "师徒/友情/情感深化",
    },
    "faction": {
        "name": "势力经营", "cooldown": 4, "consecutive_limit": 2,
        "quota": None, "desc": "宗门/势力/组织运作",
    },
    "world": {
        "name": "风土人情", "cooldown": 3, "consecutive_limit": 2,
        "quota": None, "desc": "世界观/风物/民俗",
    },
    "crisis": {
        "name": "危机升级", "cooldown": 2, "consecutive_limit": 2,
        "quota": None, "desc": "威胁逼近/压力升级",
    },
    "revelation": {
        "name": "核心秘密", "cooldown": 5, "consecutive_limit": 1,
        "quota": "C", "desc": "身世/真相/核心揭秘（C类升级）",
    },
}

# gentle_window：每5章至少1次 bond 或 world
GENTLE_WINDOW_SIZE = 5
GENTLE_WINDOW_TYPES = ("bond", "world")

# A/B/C → 事件类型映射（双向兼容）
QUOTA_TO_EVENT = {"A": "conflict", "B": "bond", "C": "revelation"}
EVENT_TO_QUOTA = {ev: meta["quota"] for ev, meta in EVENT_META.items() if meta["quota"]}

# 事件类型别名（兼容 rhythm_guard.py 旧版）
EVENT_ALIASES = {
    "conflict_thrill": "conflict",
    "bond_deepening": "bond",
    "faction_building": "faction",
    "world_painting": "world",
    "tension_escalation": "crisis",
    "revelation": "revelation",
}


def normalize_event(event):
    """规范化事件类型，兼容别名。"""
    if not event:
        return None
    event = event.strip()
    if event in EVENT_TYPES:
        return event
    if event in EVENT_ALIASES:
        return EVENT_ALIASES[event]
    # 前缀匹配
    for alias, canonical in EVENT_ALIASES.items():
        if alias.startswith(event) or event.startswith(alias.split("_")[0]):
            return canonical
    return None


def matrix_path(book_root):
    """事件矩阵数据文件路径。"""
    return os.path.join(book_root, "追踪", "event_matrix.json")


def load_matrix(book_root):
    """加载事件矩阵状态。返回状态字典。"""
    path = matrix_path(book_root)
    if not os.path.isfile(path):
        return {
            "records": [],  # [(章号, 事件类型), ...]
            "last_updated": None,
        }
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if "records" not in data:
            data["records"] = []
        return data
    except (OSError, ValueError):
        return {"records": [], "last_updated": None}


def save_matrix(book_root, data):
    """保存事件矩阵状态。"""
    path = matrix_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def get_cooldown_status(data, current_chapter):
    """获取各事件类型的冷却状态。
    返回 {事件类型: {可用, 剩余冷却, 上次出现, 连续次数}。
    """
    records = data.get("records", [])
    status = {}
    for ev in EVENT_TYPES:
        meta = EVENT_META[ev]
        cd = meta["cooldown"]
        limit = meta["consecutive_limit"]
        # 上次出现
        last = max((c for c, e in records if e == ev), default=None)
        # 连续次数（从最近一章往回数）
        consecutive = 0
        sorted_records = sorted([c for c, e in records if e == ev], reverse=True)
        check_chap = (current_chapter - 1) if current_chapter else (
            max((c for c, _ in records), default=0))
        for c in sorted_records:
            if c == check_chap:
                consecutive += 1
                check_chap -= 1
            else:
                break
        # 剩余冷却
        if last is None:
            remaining = 0
            available = True
        else:
            latest_chap = max((c for c, _ in records), default=0)
            gap = latest_chap - last
            remaining = max(0, cd - gap)
            available = remaining == 0
        status[ev] = {
            "name": meta["name"],
            "available": available,
            "remaining_cooldown": remaining,
            "last_chapter": last,
            "consecutive": consecutive,
            "consecutive_limit": limit,
            "quota": meta["quota"],
        }
    return status


def check_gentle_window(data, current_chapter):
    """检查 gentle_window 进度。
    返回 (是否满足, 进度消息, 窗口内事件列表)。
    """
    records = data.get("records", [])
    window_start = current_chapter - GENTLE_WINDOW_SIZE + 1
    if window_start < 1:
        window_start = 1
    window_events = [(c, e) for c, e in records
                     if window_start <= c <= current_chapter
                     and e in GENTLE_WINDOW_TYPES]
    if not window_events:
        if current_chapter < GENTLE_WINDOW_SIZE:
            return True, (f"前 {current_chapter} 章尚在初始窗口"
                          f"（未满 {GENTLE_WINDOW_SIZE} 章）"), []
        return False, (f"gentle_window 未满足：第{window_start}-{current_chapter}章"
                       f"（{GENTLE_WINDOW_SIZE}章窗口）内无 bond 或 world 事件"), []
    return True, (f"gentle_window 已满足：第{window_start}-{current_chapter}章窗口内有 "
                  f"{len(window_events)} 次 bond/world 事件"), window_events


def recommend(data, gear, next_chapter):
    """为下一章推荐事件类型分配。
    gear: 快/中/慢
    返回 [(事件类型, 推荐理由), ...] 按优先级排序。
    """
    status = get_cooldown_status(data, next_chapter)
    # gentle_window 检查
    gentle_ok, gentle_msg, _ = check_gentle_window(data, next_chapter - 1)
    gentle_needed = not gentle_ok

    # 档位优先级
    gear_priority = {
        "快": ["conflict", "crisis", "revelation", "faction", "bond", "world"],
        "中": ["bond", "faction", "world", "conflict", "crisis", "revelation"],
        "慢": ["world", "bond", "faction", "conflict", "crisis", "revelation"],
    }
    priority = gear_priority.get(gear, gear_priority["中"])

    available_list = []
    cooling_list = []
    for ev in priority:
        s = status[ev]
        if s["available"]:
            reason_parts = ["已冷却完毕"]
            if s["last_chapter"]:
                reason_parts.append(f"上次第{s['last_chapter']}章")
            if ev in GENTLE_WINDOW_TYPES and gentle_needed:
                reason_parts.append("gentle_window 需求（推荐优先）")
            if ev == "conflict" and gear == "快":
                reason_parts.append("快档首选冲突爽点")
            if ev == "world" and gear == "慢":
                reason_parts.append("慢档首选风土人情")
            if ev == "bond" and gear in ("中", "慢"):
                reason_parts.append("中慢档适合人物羁绊")
            if ev == "revelation":
                reason_parts.append("核心秘密类需谨慎安排")
            available_list.append((ev, "；".join(reason_parts)))
        else:
            cooling_list.append((ev, f"冷却中（还需 {s['remaining_cooldown']} 章）"))

    return available_list + cooling_list


def record(data, chapter_no, event):
    """记录本章使用的事件类型，更新状态。返回 (是否成功, 消息列表)。"""
    ev = normalize_event(event)
    if not ev:
        return False, [f"无法识别事件类型「{event}」"]

    records = data.get("records", [])
    # 检查是否已记录同一章
    existing = [(c, e) for c, e in records if c == chapter_no]
    if existing:
        # 移除旧记录
        records = [(c, e) for c, e in records if c != chapter_no]

    # 检查冷却和连续上限
    msgs = []
    meta = EVENT_META[ev]
    status = get_cooldown_status(data, chapter_no)
    s = status[ev]
    if not s["available"]:
        msgs.append(f"[WARN] {ev}（{meta['name']}）仍在冷却期（还需 {s['remaining_cooldown']} 章）")
    if s["consecutive"] + 1 > meta["consecutive_limit"]:
        msgs.append(f"[WARN] {ev}（{meta['name']}）将超过连续上限 {meta['consecutive_limit']}")

    records.append((chapter_no, ev))
    records.sort(key=lambda x: x[0])
    data["records"] = records
    return True, msgs


def cmd_recommend(book_root, args):
    """recommend 子命令。"""
    data = load_matrix(book_root)
    gear = args.gear
    if gear not in ("快", "中", "慢"):
        print(f"错误：--gear 需为 快/中/慢，收到：{gear}", file=sys.stderr)
        return 2

    # 确定下一章章号
    records = data.get("records", [])
    next_chap = args.chapter if args.chapter > 0 else (
        max((c for c, _ in records), default=0) + 1 if records else 1
    )

    print(f"事件矩阵推荐：第{next_chap}章（档位：{gear}）")
    print()

    # gentle_window 状态
    gentle_ok, gentle_msg, _ = check_gentle_window(data, next_chap - 1 if next_chap > 1 else 1)
    print(f"gentle_window：{'满足' if gentle_ok else '未满足'} - {gentle_msg}")
    print()

    # 冷却状态概览
    status = get_cooldown_status(data, next_chap)
    print("当前冷却状态：")
    for ev in EVENT_TYPES:
        s = status[ev]
        avail_tag = "可用" if s["available"] else f"冷却中({s['remaining_cooldown']}章)"
        last_tag = f"上次第{s['last_chapter']}章" if s["last_chapter"] else "未出现"
        print(f"  {ev:<12} ({s['name']:<4}) {avail_tag}  {last_tag}  连续{s['consecutive']}/{s['consecutive_limit']}")
    print()

    # 推荐列表
    recs = recommend(data, gear, next_chap)
    print("推荐事件类型（按优先级）：")
    for ev, reason in recs:
        meta = EVENT_META[ev]
        quota_tag = f"配额{meta['quota']}" if meta["quota"] else "无配额"
        print(f"  {ev:<12} ({meta['name']:<4}, {quota_tag}, 冷却{meta['cooldown']}章) - {reason}")
    print()

    if recs:
        best = recs[0][0]
        print(f"建议：本章使用「{best}」（{EVENT_META[best]['name']}）")
        quota = EVENT_META[best]["quota"]
        if quota:
            print(f"  对应 rhythm_guard 配额：{quota}（双向兼容）")
    return 0


def cmd_record(book_root, args):
    """record 子命令。"""
    if args.chapter <= 0:
        print("错误：--record 需配合 --chapter 指定章号", file=sys.stderr)
        return 2
    ev = normalize_event(args.event)
    if not ev:
        print(f"错误：无法识别事件类型「{args.event}」，可用：{', '.join(EVENT_TYPES + list(EVENT_ALIASES.keys()))}",
              file=sys.stderr)
        return 2

    data = load_matrix(book_root)
    ok, msgs = record(data, args.chapter, args.event)
    if not ok:
        print(f"错误：{msgs[0]}", file=sys.stderr)
        return 2

    path = save_matrix(book_root, data)
    print(f"已记录：第{args.chapter}章 事件类型 {ev}（{EVENT_META[ev]['name']}）")
    for m in msgs:
        print(f"  {m}")
    quota = EVENT_META[ev]["quota"]
    if quota:
        print(f"  对应 rhythm_guard 配额：{quota}（双向兼容）")
    print(f"  数据已写入：{path}")
    return 0


def cmd_status(book_root, args):
    """status 子命令。"""
    data = load_matrix(book_root)
    records = data.get("records", [])
    current_chapter = max((c for c, _ in records), default=0)

    print(f"事件矩阵状态（共 {len(records)} 条记录，最新第{current_chapter}章）")
    if data.get("last_updated"):
        print(f"最后更新：{data['last_updated']}")
    print()

    # 冷却状态
    status = get_cooldown_status(data, current_chapter + 1 if current_chapter else 1)
    print("冷却状态（相对下一章）：")
    for ev in EVENT_TYPES:
        s = status[ev]
        avail_tag = "可用" if s["available"] else f"冷却中(还需{s['remaining_cooldown']}章)"
        last_tag = f"上次第{s['last_chapter']}章" if s["last_chapter"] else "未出现"
        quota_tag = f"[配额{s['quota']}]" if s["quota"] else ""
        print(f"  {ev:<12} ({s['name']:<4}) {avail_tag}  {last_tag}  连续{s['consecutive']}/{s['consecutive_limit']}  {quota_tag}")
    print()

    # gentle_window 进度
    if current_chapter > 0:
        gentle_ok, gentle_msg, window_events = check_gentle_window(data, current_chapter)
        print(f"gentle_window：{'满足' if gentle_ok else '未满足'}")
        print(f"  {gentle_msg}")
        if window_events:
            for c, e in window_events:
                print(f"    第{c}章: {e}（{EVENT_META[e]['name']}）")
    print()

    # 最近10条记录
    recent = sorted(records, key=lambda x: x[0])[-10:]
    if recent:
        print("最近记录（最多10条）：")
        for c, e in recent:
            meta = EVENT_META[e]
            quota_tag = f"[配额{meta['quota']}]" if meta["quota"] else ""
            print(f"  第{c}章: {e}（{meta['name']}）{quota_tag}")

    return 0


def main():
    ap = argparse.ArgumentParser(
        description="事件矩阵调度器 v1.0：5+1类事件类型的节奏调度，与 rhythm_guard.py 双向兼容")
    ap.add_argument("command", choices=["recommend", "record", "status"],
                    help="子命令：recommend 推荐事件 / record 记录事件 / status 显示状态")
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--gear", default=None,
                    help="recommend：档位（快/中/慢）")
    ap.add_argument("--event", default=None,
                    help="record：事件类型（conflict/bond/faction/world/crisis/revelation 或旧版别名）")
    ap.add_argument("--chapter", type=int, default=0,
                    help="章号（recommend 指定下一章；record 指定本章）")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)

    if args.command == "recommend":
        if not args.gear:
            print("错误：recommend 需要 --gear 参数（快/中/慢）", file=sys.stderr)
            return 2
        return cmd_recommend(book_root, args)

    if args.command == "record":
        if not args.event:
            print("错误：record 需要 --event 参数", file=sys.stderr)
            return 2
        return cmd_record(book_root, args)

    if args.command == "status":
        return cmd_status(book_root, args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
