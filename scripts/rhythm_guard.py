#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rhythm_guard.py — 节奏配额检查工具 v2.0（纯标准库，无第三方依赖）。

解析 `追踪/节奏配额.md`，检查单章是否违反节奏三档制、A/B/C 配额、事件冷却规则。
规则依据 references/craft/reverse-brake.md 与 pacing-and-hooks.md。

v2.0 新增 5 类事件矩阵 + gentle_window + recommend/record 子命令：
  事件类型（原 A/B/C 配额保持向后兼容）：
    conflict      (冲突爽点)   冷却2章，连续上限2   ← 映射 A
    bond          (人物羁绊)   冷却3章               ← 映射 B（部分）
    faction       (势力经营)   冷却4章
    world         (风土人情)   冷却3章
    crisis        (危机升级)   冷却2章
    revelation    (核心秘密)   冷却5章（C类升级）    ← 映射 C（部分）
  gentle_window：每5章至少1次 bond 或 world。
  recommend 子命令：为下一章推荐事件类型分配。
  record 子命令：记录本章使用的事件类型。
  A/B/C 配额双向兼容：conflict=A，bond=B 之一，revelation=C 之一。

配额文件格式（三节，表头行可省略，列序固定）：
  ## A/B/C 配额记录
  | 章节 | 配额 | 触发内容 |
  |---|---|---|
  | 35 | A | 主角加入宗门 |

  ## 事件冷却记录
  | 章节 | 事件类型 | 事件内容 |
  |---|---|---|
  | 35 | conflict_thrill | 打脸长老 |

  ## 档位记录
  | 章节 | 档位 |
  |---|---|
  | 35 | 快 |

检查项：
  1. A/B/C 配额越界：本章声明同时触发 ≥2 项 → FAIL
  2. A/B/C 冷却违规：A 冷却 2 章 / B 冷却 1 章 / C 冷却 3 章
  3. 事件冷却违规：conflict 2 / bond 3 / faction 4 / world 3 / crisis 2 / revelation 5
     （旧名 conflict_thrill/bond_deepening 等经别名归一化后走同一套冷却值）
  4. 连续快档：当前快档且上一章快档 → FAIL
  5. 慢档缺失：近 4 章无慢档 → WARN
  6. bond_deepening 缺失：连续 3 章无 bond_deepening → WARN

两种用法：
  1) 写完章后检查（从章纲/正文批注解析声明）：
     python scripts/rhythm_guard.py --chapter-file "正文/第037章.md" --quota "追踪/节奏配额.md"
  2) 写章前预检声明：
     python scripts/rhythm_guard.py --quota "追踪/节奏配额.md" --declare "A,conflict_thrill,快"
     python scripts/rhythm_guard.py --quota "追踪/节奏配额.md" --declare "A,conflict_thrill,快" --chapter 37

声明解析（--chapter-file 模式从文件内容提取）：
  - 配额：含「配额/触发/声明/quota」的行中提取 A/B/C 字母
  - 事件：含「事件/event」的行中提取已知事件类型
  - 档位：含「档」的行中提取 快/慢/中
  章纲批注推荐写法：`> 节奏声明：配额 A，事件 conflict_thrill，档位 快`
  或 HTML 注释：`<!-- quota:A event:conflict_thrill gear:快 -->`

退出码：0 = 通过；1 = 有违规（FAIL）；2 = 参数/文件错误。

v2.1 新增 --gate-state：把本次节奏检查结果合并写入 追踪/门禁/gate_ch{N}.json
的 rhythm 段（与 check_text.py 的门禁状态共享一份文件），供 resume.py 与
--verify-prev 跨会话查验。
"""

import argparse
import datetime
import json
import os
import re
import sys

# A/B/C 配额冷却（触发后接下来 N 章不得再触发同类；与事件 cooldown 是独立概念，不可混用）
QUOTA_COOLDOWN = {"A": 2, "B": 1, "C": 3}

# v2.0 事件矩阵：5+1 类事件类型与冷却期
# 向后兼容映射：conflict→A，bond→B（部分），revelation→C（部分）
EVENT_TYPES_NEW = ["conflict", "bond", "faction", "world", "crisis", "revelation"]

# 事件冷却/连续上限单一来源：config.EVENT_META（失败回退到内联常量，值保持一致）
try:
    from config import EVENT_META
    EVENT_COOLDOWN_NEW = {k: v["cooldown"] for k, v in EVENT_META.items()}
    EVENT_CONSECUTIVE_LIMIT = {k: v["consecutive_limit"] for k, v in EVENT_META.items()}
except ImportError:
    EVENT_COOLDOWN_NEW = {
        "conflict": 2, "bond": 3, "faction": 4, "world": 3, "crisis": 2, "revelation": 5,
    }
    EVENT_CONSECUTIVE_LIMIT = {
        "conflict": 2, "bond": 3, "faction": 2, "world": 2, "crisis": 2, "revelation": 1,
    }
# A/B/C → 新事件类型映射（双向兼容）
QUOTA_TO_EVENT = {"A": "conflict", "B": "bond", "C": "revelation"}
EVENT_TO_QUOTA = {"conflict": "A", "bond": "B", "revelation": "C"}

# 事件类型别名（兼容旧版 conflict_thrill 等）
EVENT_ALIASES = {
    "conflict_thrill": "conflict",
    "bond_deepening": "bond",
    "faction_building": "faction",
    "world_painting": "world",
    "tension_escalation": "crisis",
    "revelation": "revelation",
}

# gentle_window：每5章至少1次 bond 或 world
GENTLE_WINDOW_SIZE = 5
GENTLE_WINDOW_TYPES = ("bond", "world")

# 旧版事件类型名（仅用于声明解析向后兼容；冷却值统一走 EVENT_COOLDOWN_NEW）
EVENT_TYPES = ["conflict_thrill", "bond_deepening", "faction_building",
               "world_painting", "tension_escalation", "revelation"]

# 向后兼容别名：旧事件名 → 冷却值（归一化后查 EVENT_COOLDOWN_NEW，单源真相）
EVENT_COOLDOWN = {old: EVENT_COOLDOWN_NEW[new] for old, new in EVENT_ALIASES.items()}

# 声明提取用关键词
DECL_KEYWORDS = ("节奏声明", "quota", "配额", "触发", "声明", "档位", "事件",
                 "gear", "event", "档：", "档:")
GEAR_RE = re.compile(r"(快|慢|中)档|档[位]?\s*[:：]?\s*(快|慢|中)")


def parse_quota_file(path):
    """解析节奏配额文件，返回 {'quota':[], 'events':[], 'gears':[]}。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    records = {"quota": [], "events": [], "gears": []}
    section = None
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s*(.+)", line)
        if h:
            t = h.group(1)
            if ("A/B/C" in t or "ABC" in t) and "配额" in t:
                section = "quota"
            elif "事件" in t and "冷却" in t:
                section = "events"
            elif "档位" in t or "档位记录" in t:
                section = "gears"
            else:
                section = None
            continue
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        # 跳过分隔行（---）与表头行
        if set(cells[0]) <= set("-: "):
            continue
        if cells[0] in ("章节", "章", "Chapter", "chapter"):
            continue
        chap_m = re.search(r"\d+", cells[0])
        if not chap_m:
            continue
        chap = int(chap_m.group())
        if section == "quota":
            quota = cells[1] if len(cells) > 1 else ""
            content = cells[2] if len(cells) > 2 else ""
            records["quota"].append((chap, quota, content))
        elif section == "events":
            event = cells[1] if len(cells) > 1 else ""
            content = cells[2] if len(cells) > 2 else ""
            records["events"].append((chap, event, content))
        elif section == "gears":
            gear = cells[1] if len(cells) > 1 else ""
            records["gears"].append((chap, gear))
    return records


def extract_chapter_number(path):
    """从文件名提取章号（第XXX章），找不到返回 None。"""
    base = os.path.basename(path)
    m = re.search(r"第\s*(\d+)\s*章", base)
    return int(m.group(1)) if m else None


def _extract_decl_from_text(text):
    """从章纲/正文批注文本提取声明 (quota_set, event, gear)。"""
    quota_set = set()
    event = None
    gear = None
    for line in text.splitlines():
        if not any(k in line for k in DECL_KEYWORDS):
            continue
        # A/B/C
        for letter in re.findall(r"[ABC]", line):
            quota_set.add(letter)
        # event：先查新版5类，再查旧版别名
        if event is None:
            for ev in EVENT_TYPES_NEW + EVENT_TYPES:
                if ev in line:
                    event = ev
                    break
        # gear：仅在含「档」的行提取，避免「中」误匹配
        if gear is None and "档" in line:
            m = GEAR_RE.search(line)
            if m:
                gear = m.group(1) or m.group(2)
    # 排除「不触发/无」语义（若声明行明确写不触发，清空 quota_set）
    for line in text.splitlines():
        if any(k in line for k in DECL_KEYWORDS):
            if "不触发" in line or re.search(r"配额\s*[:：]\s*(无|不|-)", line):
                quota_set.clear()
                break
    return quota_set, event, gear


def _parse_declare(s):
    """解析 --declare 字符串 'A,conflict,快' -> (quota_set, event, gear)。"""
    quota_set = set()
    event = None
    gear = None
    for part in s.split(","):
        p = part.strip()
        if not p or p in ("无", "不触发", "无触发", "-"):
            continue
        if p in EVENT_TYPES_NEW or p in EVENT_TYPES:
            event = p
        elif p in ("快", "慢", "中"):
            gear = p
        elif p in ("快档", "慢档", "中档"):
            gear = p[0]
        else:
            letters = re.findall(r"[ABC]", p)
            if letters:
                quota_set.update(letters)
            # 也兼容 event 写成中文名（少用）
    return quota_set, event, gear


def _quota_letters(cell):
    """从配额记录单元格提取 A/B/C 字母集合。"""
    return set(re.findall(r"[ABC]", cell))


def _gear_normalize(g):
    if not g:
        return None
    g = g.strip()
    m = GEAR_RE.search(g)
    if m:
        return m.group(1) or m.group(2)
    for x in ("快", "慢", "中"):
        if x in g:
            return x
    return None


def run_checks(records, current, quota_set, event, gear):
    """执行全部检查，返回 (fails:list[str], warns:list[str])。"""
    fails = []
    warns = []

    # 1. A/B/C 越界
    if len(quota_set) >= 2:
        fails.append(f"A/B/C 配额越界：本章同时声明 {'、'.join(sorted(quota_set))}（≥2 项），"
                     f"每章至多触发 1 项，必须改纲重写")

    # 2. A/B/C 冷却违规
    for q in sorted(quota_set):
        prev = max((c for c, qc, _ in records["quota"]
                    if c < current and q in _quota_letters(qc)), default=None)
        if prev is not None:
            gap = current - prev
            cd = QUOTA_COOLDOWN[q]
            if gap <= cd:
                fails.append(f"{q} 冷却违规：第{prev}章触发 {q}，冷却期 {cd} 章，"
                             f"当前第{current}章（间隔 {gap} 章 ≤ {cd}）")

    # 3. 事件冷却违规（统一走 v2.0 新版检查，旧名经别名归一化后同一套冷却值）
    # v2.0 新增：新版事件矩阵冷却检查
    events_new = parse_event_records(records)
    if event:
        ev_norm = normalize_event(event)
        if ev_norm:
            new_fails = check_event_cooldown_new(events_new, current, ev_norm)
            fails.extend(new_fails)

    # v2.0 新增：gentle_window 检查
    gentle_ok, gentle_msg = check_gentle_window(events_new, current)
    if not gentle_ok:
        warns.append(gentle_msg)

    # 4. 连续快档：当前快档且上一章快档 → FAIL；否则近2章记录皆快 → WARN
    prev_gears = sorted([(c, _gear_normalize(g)) for c, g in records["gears"]
                         if c < current], key=lambda x: x[0])
    prev_gear = prev_gears[-1][1] if prev_gears else None
    if gear == "快" and prev_gear == "快":
        fails.append(f"连续快档：第{prev_gears[-1][0]}章为快档，当前第{current}章声明快档；"
                     f"快档后必须有慢/中档缓冲")
    elif gear != "快" and len(prev_gears) >= 2 and prev_gears[-1][1] == "快" \
            and prev_gears[-2][1] == "快":
        warns.append(f"近 2 章已连续快档（第{prev_gears[-2][0]}、{prev_gears[-1][0]}章），"
                     f"建议本章用慢/中档缓冲")

    # 5. 慢档缺失：近 4 章无慢档 → WARN
    gear_seq = sorted([(c, _gear_normalize(g)) for c, g in records["gears"]
                       if c < current], key=lambda x: x[0])
    if gear:
        gear_seq.append((current, gear))
    recent4 = gear_seq[-4:]
    if len(recent4) >= 4 and not any(g == "慢" for _, g in recent4):
        warns.append(f"近 4 章无慢档（第{recent4[0][0]}–{recent4[-1][0]}章），"
                     f"每 3-4 章应至少 1 章慢档铺垫/羁绊/风土")

    # 6. bond 缺失：连续 3 章无 bond（新事件类型） → WARN
    last_bond = max((c for c, e in events_new
                     if c < current and e == "bond"), default=0)
    ev_norm = normalize_event(event) if event else None
    if ev_norm != "bond":
        streak = current - last_bond
        if streak >= 3:
            tail = f"（上次 bond 在第{last_bond}章）" if last_bond else "（全书尚未记录 bond）"
            warns.append(f"连续 {streak} 章无 bond{tail}，建议本章安排人物羁绊深化")

    return fails, warns


def _format_decl(quota_set, event, gear):
    parts = []
    parts.append("配额 " + ("、".join(sorted(quota_set)) if quota_set else "无"))
    parts.append("事件 " + (event or "未声明"))
    parts.append("档位 " + (gear or "未声明"))
    return "，".join(parts)


def normalize_event(event):
    """将事件类型规范化为新版5类（兼容旧版别名）。返回 None 表示无法识别。"""
    if not event:
        return None
    event = event.strip()
    if event in EVENT_TYPES_NEW:
        return event
    if event in EVENT_ALIASES:
        return EVENT_ALIASES[event]
    # 尝试前缀匹配
    for alias, canonical in EVENT_ALIASES.items():
        if alias.startswith(event) or event.startswith(alias.split("_")[0]):
            return canonical
    return None


def event_to_quota(event):
    """事件类型 → A/B/C 配额字母（双向兼容）。"""
    ev = normalize_event(event)
    return EVENT_TO_QUOTA.get(ev)


def quota_to_event(quota_letter):
    """A/B/C 配额字母 → 事件类型。"""
    return QUOTA_TO_EVENT.get(quota_letter)


def parse_event_records(records):
    """从配额文件记录中提取事件历史（规范化为新版5类）。
    返回 [(章节号, 事件类型), ...]。
    """
    events_new = []
    for chap, ev, _ in records["events"]:
        ev_norm = normalize_event(ev)
        if ev_norm:
            events_new.append((chap, ev_norm))
    # 也从 A/B/C 配额记录中推断事件（向后兼容）
    for chap, quota, _ in records["quota"]:
        qletters = _quota_letters(quota)
        for q in qletters:
            ev = quota_to_event(q)
            if ev:
                # 避免重复
                if not any(c == chap and e == ev for c, e in events_new):
                    events_new.append((chap, ev))
    events_new.sort(key=lambda x: x[0])
    return events_new


def check_gentle_window(events_new, current_chapter):
    """检查 gentle_window：每5章至少1次 bond 或 world。
    返回 (是否满足, 消息)。
    """
    window_start = current_chapter - GENTLE_WINDOW_SIZE + 1
    if window_start < 1:
        window_start = 1
    window_events = [(c, e) for c, e in events_new
                     if window_start <= c <= current_chapter
                     and e in GENTLE_WINDOW_TYPES]
    if not window_events:
        # 如果当前窗口还没到5章，放宽要求
        if current_chapter < GENTLE_WINDOW_SIZE:
            return True, f"前 {current_chapter} 章尚在初始窗口（未满 {GENTLE_WINDOW_SIZE} 章）"
        return False, (f"gentle_window 未满足：第{window_start}-{current_chapter}章（{GENTLE_WINDOW_SIZE}章窗口）"
                       f"内无 bond 或 world 事件，建议本章安排人物羁绊或风土人情")
    return True, (f"gentle_window 已满足：第{window_start}-{current_chapter}章窗口内有 "
                  f"{len(window_events)} 次 bond/world 事件")


def check_event_cooldown_new(events_new, current_chapter, event):
    """检查新版事件冷却。返回 [违规消息列表]。"""
    fails = []
    ev = normalize_event(event)
    if not ev:
        return fails
    cd = EVENT_COOLDOWN_NEW[ev]
    # 冷却检查：同类型事件在冷却期内
    prev_same = max((c for c, e in events_new if c < current_chapter and e == ev), default=None)
    if prev_same is not None:
        gap = current_chapter - prev_same
        if gap <= cd:
            fails.append(f"事件冷却违规：{ev} 第{prev_same}章触发，冷却期 {cd} 章，"
                         f"当前第{current_chapter}章（间隔 {gap} 章 ≤ {cd}）")
    # 连续上限检查
    limit = EVENT_CONSECUTIVE_LIMIT[ev]
    consecutive = 0
    prev_chaps = sorted([c for c, e in events_new if e == ev and c < current_chapter], reverse=True)
    check_chap = current_chapter - 1
    for c in prev_chaps:
        if c == check_chap:
            consecutive += 1
            check_chap -= 1
        else:
            break
    # 当前章也算一次
    if consecutive + 1 > limit:
        fails.append(f"事件连续上限违规：{ev} 已连续 {consecutive} 章（含本章 {consecutive+1} 次），"
                     f"超过连续上限 {limit}")
    return fails


def recommend_events(events_new, gear):
    """为下一章推荐事件类型分配。
    gear: 快/中/慢 档位。
    返回 [(事件类型, 推荐理由), ...] 按优先级排序。
    """
    recommendations = []
    # 找出已冷却完毕的事件类型
    available = []
    for ev in EVENT_TYPES_NEW:
        cd = EVENT_COOLDOWN_NEW[ev]
        prev = max((c for c, e in events_new if e == ev), default=0)
        gap = len(events_new) and (max(c for c, _ in events_new) if events_new else 0) - prev + 1
        # 简化：如果从未出现或距上次≥冷却期，则可用
        last_chap = max((c for c, _ in events_new), default=0)
        if prev == 0 or last_chap - prev >= cd:
            available.append((ev, last_chap - prev if prev else 999))
        else:
            recommendations.append((ev, f"冷却中（还需 {cd - (last_chap - prev)} 章）"))

    # gentle_window 检查：优先 bond/world
    last_chap = max((c for c, _ in events_new), default=0)
    window_start = last_chap - GENTLE_WINDOW_SIZE + 1
    if window_start < 1:
        window_start = 1
    window_events = [(c, e) for c, e in events_new
                     if c >= window_start and e in GENTLE_WINDOW_TYPES]
    gentle_needed = not window_events and last_chap >= GENTLE_WINDOW_SIZE - 1

    # 根据档位排序
    gear_priority = {
        "快": ["conflict", "crisis", "revelation", "faction", "bond", "world"],
        "中": ["bond", "faction", "world", "conflict", "crisis", "revelation"],
        "慢": ["world", "bond", "faction", "conflict", "crisis", "revelation"],
    }
    priority = gear_priority.get(gear, gear_priority["中"])

    result = []
    for ev in priority:
        if any(a[0] == ev for a in available):
            reason = f"已冷却完毕"
            if ev in GENTLE_WINDOW_TYPES and gentle_needed:
                reason += "；gentle_window 需求（推荐优先）"
            if ev == "conflict" and gear == "快":
                reason += "；快档首选冲突爽点"
            if ev == "world" and gear == "慢":
                reason += "；慢档首选风土人情"
            if ev == "bond" and gear in ("中", "慢"):
                reason += "；中慢档适合人物羁绊"
            result.append((ev, reason))
    # 冷却中的事件也列出（但不推荐）
    for ev, reason in recommendations:
        if ev not in [r[0] for r in result]:
            result.append((ev, reason))
    return result


def record_event(quota_path, chapter_no, event):
    """记录本章使用的事件类型，追加到配额文件的事件冷却记录表。
    返回写入的行文本。
    """
    ev = normalize_event(event)
    if not ev:
        return None
    line = f"| {chapter_no} | {ev} | （record 子命令记录） |\n"
    # 追加到配额文件（在事件冷却记录表的末尾）
    try:
        with open(quota_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        # 找到事件冷却记录表的位置
        lines = content.splitlines(keepends=True)
        insert_idx = None
        in_events_section = False
        for i, ln in enumerate(lines):
            h = re.match(r"^#{1,6}\s*(.+)", ln)
            if h:
                t = h.group(1)
                if "事件" in t and "冷却" in t:
                    in_events_section = True
                elif in_events_section:
                    # 进入下一节
                    if insert_idx is None:
                        insert_idx = i
                    in_events_section = False
            elif in_events_section and ln.strip().startswith("|"):
                insert_idx = i + 1
        if insert_idx is None:
            # 没找到事件表，追加到文件末尾
            if not content.endswith("\n"):
                content += "\n"
            content += f"\n## 事件冷却记录\n| 章节 | 事件类型 | 事件内容 |\n|---|---|---|\n{line}"
        else:
            lines.insert(insert_idx, line)
            content = "".join(lines)
        with open(quota_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass
    return line


def merge_gate_rhythm(quota_path, chapter_no, passed, fails, warns, decl):
    """把节奏检查结果合并进 追踪/门禁/gate_ch{N}.json 的 rhythm 段。"""
    gdir = os.path.join(os.path.dirname(os.path.abspath(quota_path)), "门禁")
    os.makedirs(gdir, exist_ok=True)
    path = os.path.join(gdir, f"gate_ch{chapter_no}.json")
    state = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
    state.setdefault("chapter", chapter_no)
    state["rhythm"] = {
        "passed": passed,
        "fails": fails,
        "warns": warns,
        "declare": decl,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return path


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="节奏配额检查 v2.0：A/B/C 越界/冷却 + 5类事件矩阵 + gentle_window + 档位纪律")
    ap.add_argument("--quota", required=True, help="节奏配额文件路径（追踪/节奏配额.md）")
    ap.add_argument("--chapter-file", default=None,
                    help="章节文件路径（正文或章纲），从中解析章号与声明")
    ap.add_argument("--declare", default=None,
                    help='预检声明字符串，如 "A,conflict,快" 或 "A,conflict_thrill,快"（写章前检查）')
    ap.add_argument("--chapter", type=int, default=0, help="当前章号（覆盖文件名推断）")
    ap.add_argument("--gate-state", action="store_true",
                    help="把节奏检查结果合并写入 追踪/门禁/gate_ch{N}.json 的 rhythm 段")
    # v2.0 新增子命令
    ap.add_argument("--recommend", default=None,
                    help="为下一章推荐事件类型分配，传入档位（快/中/慢），如 --recommend 快")
    ap.add_argument("--record", default=None,
                    help="记录本章使用的事件类型，如 --record conflict（需配合 --chapter 指定章号）")
    args = ap.parse_args()

    # v2.0 recommend 子命令
    if args.recommend:
        try:
            records = parse_quota_file(args.quota)
        except OSError as e:
            print(f"错误：无法读取配额文件 {args.quota}: {e}", file=sys.stderr)
            return 2
        gear = args.recommend.strip()
        if gear not in ("快", "中", "慢"):
            print(f"错误：--recommend 参数需为 快/中/慢，收到：{gear}", file=sys.stderr)
            return 2
        events_new = parse_event_records(records)
        # 确定下一章章号
        next_chap = args.chapter if args.chapter > 0 else (
            max((c for c, _ in events_new), default=0) + 1
            if events_new else 1
        )
        print(f"事件矩阵推荐：第{next_chap}章（档位：{gear}）")
        print()
        # gentle_window 状态
        gentle_ok, gentle_msg = check_gentle_window(events_new, next_chap)
        print(f"gentle_window：{'满足' if gentle_ok else '未满足'} - {gentle_msg}")
        print()
        # 推荐列表
        recs = recommend_events(events_new, gear)
        print("推荐事件类型（按优先级）：")
        for ev, reason in recs:
            quota = EVENT_TO_QUOTA.get(ev, "-")
            cd = EVENT_COOLDOWN_NEW.get(ev, "?")
            limit = EVENT_CONSECUTIVE_LIMIT.get(ev, "?")
            print(f"  {ev:<12} (配额{quota}, 冷却{cd}章, 连续上限{limit}) - {reason}")
        print()
        if recs:
            best = recs[0][0]
            print(f"建议：本章使用「{best}」事件类型")
        return 0

    # v2.0 record 子命令
    if args.record:
        if args.chapter <= 0:
            print("错误：--record 需配合 --chapter 指定章号", file=sys.stderr)
            return 2
        ev = normalize_event(args.record)
        if not ev:
            print(f"错误：无法识别事件类型「{args.record}」，可用：{', '.join(EVENT_TYPES_NEW + list(EVENT_ALIASES.keys()))}",
                  file=sys.stderr)
            return 2
        line = record_event(args.quota, args.chapter, args.record)
        if line:
            print(f"已记录：第{args.chapter}章 事件类型 {ev}")
            print(f"  写入行：{line.strip()}")
            # 同步映射到 A/B/C 配额
            q = event_to_quota(ev)
            if q:
                print(f"  对应配额：{q}（双向兼容）")
        else:
            print("错误：记录失败", file=sys.stderr)
            return 2
        return 0

    if not args.chapter_file and not args.declare:
        print("错误：至少需要 --chapter-file 或 --declare 之一", file=sys.stderr)
        return 2

    try:
        records = parse_quota_file(args.quota)
    except OSError as e:
        print(f"错误：无法读取配额文件 {args.quota}: {e}", file=sys.stderr)
        return 2

    # 确定当前章号
    current = args.chapter if args.chapter > 0 else None
    if current is None and args.chapter_file:
        current = extract_chapter_number(args.chapter_file)
    if current is None:
        all_chaps = ([c for c, _, _ in records["quota"]]
                     + [c for c, _, _ in records["events"]]
                     + [c for c, _ in records["gears"]])
        if all_chaps and args.declare:
            current = max(all_chaps) + 1
        else:
            print("错误：无法确定当前章号，请用 --chapter 指定，或让 --chapter-file 名含「第XXX章」",
                  file=sys.stderr)
            return 2

    # 确定声明
    if args.declare:
        quota_set, event, gear = _parse_declare(args.declare)
    else:
        try:
            with open(args.chapter_file, "r", encoding="utf-8-sig") as f:
                ch_text = f.read()
        except OSError as e:
            print(f"错误：无法读取章节文件 {args.chapter_file}: {e}", file=sys.stderr)
            return 2
        quota_set, event, gear = _extract_decl_from_text(ch_text)
        if not (quota_set or event or gear):
            print(f"提示：未在 {os.path.basename(args.chapter_file)} 中解析到节奏声明"
                  f"（配额/事件/档位），建议在章纲批注中声明或改用 --declare 预检。")

    print(f"节奏配额检查：第{current}章")
    print(f"声明：{_format_decl(quota_set, event, gear)}")
    print()

    fails, warns = run_checks(records, current, quota_set, event, gear)

    for f in fails:
        print(f"  [FAIL] {f}")
    for w in warns:
        print(f"  [WARN] {w}")

    if not fails and not warns:
        print("  全部检查通过")
    print()
    if args.gate_state:
        path = merge_gate_rhythm(args.quota, current, not fails,
                                 len(fails), len(warns), _format_decl(quota_set, event, gear))
        print(f"节奏门禁状态已合并写入：{path}")
    if fails:
        print(f"结果：{len(fails)} 项违规" + (f"，另 {len(warns)} 项警告" if warns else ""))
        return 1
    if warns:
        print(f"结果：通过（{len(warns)} 项警告，建议关注）")
    else:
        print("结果：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
