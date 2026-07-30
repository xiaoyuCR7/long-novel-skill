#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""entry_mode.py — 章节入口模式与小说家人格推荐器 v1.0（纯标准库，无第三方依赖）。

反模板化核心工具：基于历史记录推荐下一章的入口模式和小说家人格，
避免连续使用同一模式导致 AI 味同质化。

方法论依据：
  - references/craft/chapter-entry-modes.md（8种入口模式）
  - references/craft/novelist-personas.md（3种小说家人格）

8种入口模式：
  scene      场景切入   — 新地图、新环境、时间跨度后重新定位
  dialogue   对话切入   — 冲突升级、信息揭露、节奏加快
  action     动作切入   — 战斗章、追逐戏、紧急情境
  suspense   悬念切入   — 卷首、转折点、伏笔铺设
  flashback  回忆切入   — 角色弧光关键节点、动机揭示
  information 信息切入  — 世界观扩展、势力博弈、时间线推进
  sensory    感官切入   — 受伤后、异环境、情绪转换
  rhythm     节奏切入   — 高潮前蓄力、情绪爆发、风格化段落

3种小说家人格：
  blade      冷峻派 — 短句、动词驱动、留白（战斗/对峙）
  fire       热血派 — 排比、感叹、情绪外放（突破/逆转）
  witness    旁观派 — 疏离、白描、环境交织（过渡/沉淀）

子命令：
  recommend  推荐下一章入口模式（需指定档位）
  persona    推荐下一章小说家人格
  record     记录本章使用的入口模式和人格
  list       列出所有模式/人格及说明
  check      检查近期轮换是否违规

用法：
  python scripts/entry_mode.py recommend "{书名目录}" --gear 快
  python scripts/entry_mode.py persona "{书名目录}" --gear 中
  python scripts/entry_mode.py record "{书名目录}" --chapter 37 --mode action --persona blade
  python scripts/entry_mode.py list
  python scripts/entry_mode.py check "{书名目录}"

退出码：0 = 成功；1 = 有违规/警告；2 = 参数/文件错误。
"""

import argparse
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置导入（带回退）
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    from config import (
        BOOK_DIRS,
        TRACKING_FILES,
    )
except ImportError:
    BOOK_DIRS = {
        "outline": "大纲",
        "setting": "设定",
        "manuscript": "正文",
        "tracking": "追踪",
    }
    TRACKING_FILES = {
        "rhythm_quota": "节奏配额.md",
    }

# ---------------------------------------------------------------------------
# 8种入口模式定义
# ---------------------------------------------------------------------------

ENTRY_MODES = [
    {
        "code": "scene",
        "name": "场景切入",
        "name_en": "Scene",
        "desc": "以具体场景的视觉/听觉描写开篇，不带主观判断",
        "scenarios": "新地图、新环境、时间跨度后重新定位",
        "taboo": "不要写「天空很蓝」「阳光明媚」等空泛描写",
    },
    {
        "code": "dialogue",
        "name": "对话切入",
        "name_en": "Dialogue",
        "desc": "以有张力或信息量的对话直接开篇，不加说话标签",
        "scenarios": "冲突升级、信息揭露、节奏加快",
        "taboo": "对话必须承载信息或情绪，不能是无意义寒暄",
    },
    {
        "code": "action",
        "name": "动作切入",
        "name_en": "Action",
        "desc": "以连续动作序列开篇，动词密集，节奏快",
        "scenarios": "战斗章、追逐戏、紧急情境",
        "taboo": "动作要有因果链，不能是孤立动作堆砌",
    },
    {
        "code": "suspense",
        "name": "悬念切入",
        "name_en": "Suspense",
        "desc": "以反常现象、未解之谜或倒计时开篇，制造「为什么」",
        "scenarios": "卷首、转折点、伏笔铺设",
        "taboo": "悬念必须在5章内回收或推进",
    },
    {
        "code": "flashback",
        "name": "回忆切入",
        "name_en": "Flashback",
        "desc": "以记忆碎片开篇，与当前情节形成对照或补充",
        "scenarios": "角色弧光关键节点、动机揭示、情感高潮",
        "taboo": "回忆不超过200字，必须与当前情节有因果关联",
    },
    {
        "code": "information",
        "name": "信息切入",
        "name_en": "Information",
        "desc": "以消息、通缉令、公告或他人转述开篇",
        "scenarios": "世界观扩展、势力博弈、时间线推进",
        "taboo": "信息必须立即引发角色行动或决策",
    },
    {
        "code": "sensory",
        "name": "感官切入",
        "name_en": "Sensory",
        "desc": "以具体感官体验（味/触/嗅/温度/痛感）开篇，非视觉优先",
        "scenarios": "受伤后、异环境、情绪转换",
        "taboo": "感官描写必须服务于情节",
    },
    {
        "code": "rhythm",
        "name": "节奏切入",
        "name_en": "Rhythm",
        "desc": "以短句群或韵律化文字开篇，用句式本身制造节奏感",
        "scenarios": "高潮前蓄力、情绪爆发、风格化段落",
        "taboo": "整章只能用一次，不能变成风格 gimmick",
    },
]

# 快速查找：code → mode, name → mode
_MODE_BY_CODE = {m["code"]: m for m in ENTRY_MODES}
_MODE_BY_NAME = {m["name"]: m for m in ENTRY_MODES}

# 入口模式别名（支持多种写法）
_MODE_ALIASES = {
    "场景": "scene",
    "对话": "dialogue",
    "动作": "action",
    "悬念": "suspense",
    "回忆": "flashback",
    "信息": "information",
    "感官": "sensory",
    "节奏": "rhythm",
}

# ---------------------------------------------------------------------------
# 3种小说家人格定义
# ---------------------------------------------------------------------------

PERSONAS = [
    {
        "code": "blade",
        "name": "冷峻派",
        "name_en": "The Blade",
        "style": "短句、动词驱动、零形容词堆砌、留白",
        "avg_sent_len": "12-18字",
        "verb_ratio": ">25%",
        "adj_ratio": "<8%",
        "scenarios": "战斗、对峙、追杀、竞技、危机决策",
        "taboo": "不能连续5句以上无对话或无心理；冷峻不等于没有情绪",
    },
    {
        "code": "fire",
        "name": "热血派",
        "name_en": "The Fire",
        "style": "排比、感叹、情绪外放、节奏递进",
        "avg_sent_len": "18-28字",
        "verb_ratio": "中等",
        "adj_ratio": "中等",
        "scenarios": "突破、逆转、热血对决、信念宣告、团队集结",
        "taboo": "排比每章不超过2处；感叹号全章不超过15个",
    },
    {
        "code": "witness",
        "name": "旁观派",
        "name_en": "The Witness",
        "style": "疏离、白描、环境与人物交织、时间感",
        "avg_sent_len": "20-30字",
        "verb_ratio": "较低",
        "adj_ratio": "中等",
        "scenarios": "过渡章、日常、情感沉淀、战后余波、世界观铺展",
        "taboo": "环境描写不超过段落字数30%；不能连续2章使用",
    },
]

_PERSONA_BY_CODE = {p["code"]: p for p in PERSONAS}
_PERSONA_BY_NAME = {p["name"]: p for p in PERSONAS}

_PERSONA_ALIASES = {
    "冷峻": "blade",
    "热血": "fire",
    "旁观": "witness",
}

# ---------------------------------------------------------------------------
# 入口模式 × 人格 搭配矩阵
# ---------------------------------------------------------------------------
# ✓ 推荐  ○ 可用  △ 慎用  ✗ 不推荐

COMPATIBILITY = {
    #              blade    fire     witness
    "scene":       {"blade": "o",  "fire": "d", "witness": "y"},
    "dialogue":    {"blade": "y",  "fire": "y", "witness": "d"},
    "action":      {"blade": "y",  "fire": "y", "witness": "x"},
    "suspense":    {"blade": "y",  "fire": "d", "witness": "y"},
    "flashback":   {"blade": "d",  "fire": "x", "witness": "y"},
    "information": {"blade": "o",  "fire": "d", "witness": "y"},
    "sensory":     {"blade": "y",  "fire": "o", "witness": "y"},
    "rhythm":      {"blade": "y",  "fire": "y", "witness": "x"},
}

_COMPAT_LABEL = {"y": "✓ 推荐", "o": "○ 可用", "d": "△ 慎用", "x": "✗ 不推荐"}
_COMPAT_SCORE = {"y": 3, "o": 2, "d": 1, "x": 0}

# ---------------------------------------------------------------------------
# 档位与入口模式推荐权重
# ---------------------------------------------------------------------------

# 不同档位下入口模式的优先级排序（快档偏动作/对话，慢档偏场景/回忆/信息）
GEAR_MODE_PRIORITY = {
    "快": ["action", "dialogue", "sensory", "rhythm", "suspense", "information", "scene", "flashback"],
    "中": ["dialogue", "suspense", "information", "scene", "action", "sensory", "flashback", "rhythm"],
    "慢": ["scene", "flashback", "information", "sensory", "suspense", "dialogue", "action", "rhythm"],
}

# 不同档位下人格的优先级排序
GEAR_PERSONA_PRIORITY = {
    "快": ["blade", "fire", "witness"],
    "中": ["fire", "blade", "witness"],
    "慢": ["witness", "fire", "blade"],
}

# 轮换规则常量
ENTRY_MODE_RECENT_WINDOW = 3   # 近3章内同一模式最多使用1次
PERSONA_CONSECUTIVE_LIMIT = 3   # 不得连续3章使用同一人格
PERSONA_WITNESS_CONSECUTIVE = 2  # 旁观派不能连续2章使用

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _read_file(path) -> str:
    """安全读取文本文件，失败返回空字符串。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
        return ""


def normalize_mode(mode_str):
    """将入口模式字符串规范化为 code，无法识别返回 None。"""
    if not mode_str:
        return None
    s = mode_str.strip()
    # 直接匹配 code
    if s in _MODE_BY_CODE:
        return s
    # 直接匹配中文名
    if s in _MODE_BY_NAME:
        return _MODE_BY_NAME[s]["code"]
    # 匹配别名
    if s in _MODE_ALIASES:
        return _MODE_ALIASES[s]
    # 尝试包含匹配（如"场景切入" → scene）
    for name, code in _MODE_ALIASES.items():
        if name in s:
            return code
    # 尝试英文
    s_lower = s.lower()
    for m in ENTRY_MODES:
        if m["name_en"].lower() == s_lower:
            return m["code"]
    return None


def normalize_persona(persona_str):
    """将人格字符串规范化为 code，无法识别返回 None。"""
    if not persona_str:
        return None
    s = persona_str.strip()
    # 直接匹配 code
    if s in _PERSONA_BY_CODE:
        return s
    # 直接匹配中文名
    if s in _PERSONA_BY_NAME:
        return _PERSONA_BY_NAME[s]["code"]
    # 匹配别名
    if s in _PERSONA_ALIASES:
        return _PERSONA_ALIASES[s]
    for name, code in _PERSONA_ALIASES.items():
        if name in s:
            return code
    s_lower = s.lower()
    for p in PERSONAS:
        if p["name_en"].lower() == s_lower:
            return p["code"]
    return None


def get_mode_display(code):
    """获取入口模式的显示名。"""
    m = _MODE_BY_CODE.get(code)
    return f"{m['name']}（{m['name_en']}）" if m else code


def get_persona_display(code):
    """获取人格的显示名。"""
    p = _PERSONA_BY_CODE.get(code)
    return f"{p['name']}（{p['name_en']}）" if p else code


# ---------------------------------------------------------------------------
# 解析节奏配额文件
# ---------------------------------------------------------------------------

def parse_rhythm_quota(quota_path):
    """解析节奏配额文件，提取入口模式和人格历史记录。

    返回:
        {
            "entries": [(chapter_num, mode_code, persona_code), ...],
            "gears": [(chapter_num, gear_str), ...],
        }
    """
    text = _read_file(quota_path)
    if not text:
        return {"entries": [], "gears": []}

    entries = []
    gears = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        # 跳过分隔行
        if set(cells[0]) <= set("-: "):
            continue
        # 跳过表头行
        if cells[0] in ("章节", "章", "Chapter", "chapter", "第章"):
            continue
        # 提取章节号
        chap_m = re.search(r"\d+", cells[0])
        if not chap_m:
            continue
        chap = int(chap_m.group())

        # 扫描所有列，寻找入口模式和人格
        mode_code = None
        persona_code = None
        gear = None

        for cell in cells[1:]:
            cell_stripped = cell.strip()
            if not cell_stripped:
                continue
            # 尝试匹配入口模式
            if mode_code is None:
                mode_code = normalize_mode(cell_stripped)
            # 尝试匹配人格
            if persona_code is None:
                persona_code = normalize_persona(cell_stripped)
            # 尝试匹配档位（快/慢/中 或 A/B/C 映射）
            if gear is None:
                for g in ("快", "慢", "中"):
                    if g in cell_stripped:
                        gear = g
                        break
                if gear is None:
                    # A/B/C 配额类型映射到档位
                    # 去除 markdown 加粗标记后匹配
                    clean = re.sub(r"[*_`]+", "", cell_stripped).strip()
                    if clean in ("A", "a"):
                        gear = "快"
                    elif clean in ("B", "b"):
                        gear = "中"
                    elif clean in ("C", "c"):
                        gear = "慢"

        # 只要找到至少一项就记录
        if mode_code or persona_code or gear:
            entries.append((chap, mode_code, persona_code))
            if gear:
                gears.append((chap, gear))

    # 去重：同一章节只保留最后一条记录
    seen = {}
    for chap, mode, persona in entries:
        seen[chap] = (mode, persona)
    entries_sorted = sorted([(chap, m, p) for chap, (m, p) in seen.items()])

    gear_seen = {}
    for chap, g in gears:
        gear_seen[chap] = g
    gears_sorted = sorted([(chap, g) for chap, g in gear_seen.items()])

    return {"entries": entries_sorted, "gears": gears_sorted}


def find_quota_path(book_dir):
    """在书名目录下查找节奏配额文件路径。"""
    tracking = book_dir / BOOK_DIRS.get("tracking", "追踪")
    quota_file = tracking / TRACKING_FILES.get("rhythm_quota", "节奏配额.md")
    return quota_file


# ---------------------------------------------------------------------------
# 推荐算法
# ---------------------------------------------------------------------------

def recommend_entry_mode(history, gear="中", chapter=None):
    """推荐下一章入口模式。

    规则：
      1. 不得与上一章相同
      2. 近3章内同一模式最多使用1次
      3. 根据档位排序优先级
      4. 兼容性评分

    返回: [(mode_code, reason_str, score), ...] 按推荐度排序
    """
    entries = history["entries"]
    gears = history["gears"]

    # 确定下一章号
    if chapter is None:
        all_chaps = [e[0] for e in entries] + [g[0] for g in gears]
        next_chap = max(all_chaps) + 1 if all_chaps else 1
    else:
        next_chap = chapter

    # 近3章使用的模式
    recent_modes = []
    for chap, mode, _ in reversed(entries):
        if mode and next_chap - chap <= ENTRY_MODE_RECENT_WINDOW:
            recent_modes.append((chap, mode))

    # 上一章模式
    last_mode = recent_modes[0][1] if recent_modes else None

    # 各模式在近3章的使用次数
    mode_recent_count = {}
    for _, mode in recent_modes:
        mode_recent_count[mode] = mode_recent_count.get(mode, 0) + 1

    # 档位优先级
    priority = GEAR_MODE_PRIORITY.get(gear, GEAR_MODE_PRIORITY["中"])

    results = []
    for mode in ENTRY_MODES:
        code = mode["code"]
        reasons = []
        score = 0

        # 规则1：不能与上一章相同
        if code == last_mode:
            reasons.append("与上一章相同（禁止）")
            score = -100
        else:
            score += 10

        # 规则2：近3章使用次数
        count = mode_recent_count.get(code, 0)
        if count == 0:
            score += 15
            reasons.append("近3章未使用")
        elif count == 1:
            score += 5
            reasons.append(f"近3章已使用1次")
        else:
            score -= 20
            reasons.append(f"近3章已使用{count}次（超限）")

        # 规则3：档位优先级加分
        priority_idx = priority.index(code) if code in priority else len(priority)
        priority_bonus = max(0, len(priority) - priority_idx) * 2
        score += priority_bonus
        if priority_idx == 0:
            reasons.append(f"{gear}档首选")

        # 规则4：适合场景说明
        reasons.append(f"适用：{mode['scenarios']}")

        results.append((code, "；".join(reasons), score))

    # 按分数降序排列
    results.sort(key=lambda x: x[2], reverse=True)
    return results, next_chap


def recommend_persona(history, gear="中", chapter=None, mode_code=None):
    """推荐下一章小说家人格。

    规则：
      1. 不得连续3章使用同一人格
      2. 旁观派不得连续2章使用
      3. 根据档位排序优先级
      4. 如果指定了入口模式，参考兼容性矩阵

    返回: [(persona_code, reason_str, score), ...] 按推荐度排序
    """
    entries = history["entries"]

    # 确定下一章号
    if chapter is None:
        all_chaps = [e[0] for e in entries]
        next_chap = max(all_chaps) + 1 if all_chaps else 1
    else:
        next_chap = chapter

    # 收集最近的人格序列
    recent_personas = []
    for chap, _, persona in reversed(entries):
        if persona and next_chap - chap <= PERSONA_CONSECUTIVE_LIMIT:
            recent_personas.append((chap, persona))

    # 计算连续使用次数
    consecutive_count = {}
    for i, (_, persona) in enumerate(recent_personas):
        if i == 0:
            consecutive_count[persona] = 1
        elif recent_personas[i - 1][1] == persona:
            consecutive_count[persona] = consecutive_count.get(persona, 1) + 1
        else:
            break

    # 档位优先级
    priority = GEAR_PERSONA_PRIORITY.get(gear, GEAR_PERSONA_PRIORITY["中"])

    results = []
    for persona in PERSONAS:
        code = persona["code"]
        reasons = []
        score = 0

        # 规则1：连续使用限制
        consec = consecutive_count.get(code, 0)
        limit = PERSONA_WITNESS_CONSECUTIVE if code == "witness" else PERSONA_CONSECUTIVE_LIMIT
        if consec >= limit:
            reasons.append(f"已连续{consec}章使用（上限{limit}）")
            score = -100
        elif consec > 0:
            score += 5
            remaining = limit - consec
            reasons.append(f"已连续{consec}章，还可连续{remaining}章")
        else:
            score += 15
            reasons.append("近期未使用")

        # 规则2：档位优先级
        priority_idx = priority.index(code) if code in priority else len(priority)
        priority_bonus = max(0, len(priority) - priority_idx) * 3
        score += priority_bonus
        if priority_idx == 0:
            reasons.append(f"{gear}档首选")

        # 规则3：与入口模式的兼容性
        if mode_code and code not in ("",):
            compat = COMPATIBILITY.get(mode_code, {}).get(code, "o")
            compat_score = _COMPAT_SCORE.get(compat, 1)
            score += compat_score * 5
            reasons.append(f"与{get_mode_display(mode_code)}兼容性：{_COMPAT_LABEL[compat]}")

        # 规则4：适合场景
        reasons.append(f"适用：{persona['scenarios']}")

        results.append((code, "；".join(reasons), score))

    results.sort(key=lambda x: x[2], reverse=True)
    return results, next_chap


# ---------------------------------------------------------------------------
# 检查轮换违规
# ---------------------------------------------------------------------------

def check_rotation(history, chapter=None):
    """检查近期入口模式和人格轮换是否有违规。

    返回: (fails: list[str], warns: list[str])
    """
    fails = []
    warns = []

    entries = history["entries"]

    if not entries:
        return fails, warns

    # 确定检查范围
    if chapter is None:
        chapter = max(e[0] for e in entries)

    # === 入口模式检查 ===
    recent_modes = []
    for chap, mode, _ in entries:
        if mode and chapter - chap <= ENTRY_MODE_RECENT_WINDOW:
            recent_modes.append((chap, mode))

    # 1. 与上一章相同
    prev_entries = sorted([(c, m) for c, m, _ in entries if m and c < chapter],
                          key=lambda x: x[0])
    if prev_entries:
        last_chap, last_mode = prev_entries[-1]
        current_mode = None
        for c, m, p in entries:
            if c == chapter:
                current_mode = m
                break
        if current_mode and current_mode == last_mode:
            fails.append(f"入口模式违规：第{chapter}章与第{last_chap}章使用相同模式"
                         f"「{get_mode_display(current_mode)}」，不得连续两章相同")

    # 2. 近3章同一模式超过1次
    mode_count = {}
    for chap, mode in recent_modes:
        mode_count[mode] = mode_count.get(mode, 0) + 1
    for mode, count in mode_count.items():
        if count > 1:
            chaps = [c for c, m in recent_modes if m == mode]
            warns.append(f"入口模式警告：「{get_mode_display(mode)}」在近3章"
                         f"（第{min(chaps)}-{max(chaps)}章）使用了{count}次，"
                         f"建议更换")

    # === 人格检查 ===
    # 3. 连续3章同一人格
    persona_seq = []
    for c in sorted(set(e[0] for e in entries)):
        for chap, _, persona in entries:
            if chap == c and persona:
                persona_seq.append((c, persona))
                break

    for i in range(len(persona_seq) - 2):
        if (persona_seq[i][1] == persona_seq[i + 1][1]
                and persona_seq[i + 1][1] == persona_seq[i + 2][1]):
            p = persona_seq[i][1]
            chaps = [persona_seq[j][0] for j in range(i, i + 3)]
            fails.append(f"人格轮换违规：第{chaps[0]}-{chaps[2]}章连续3章使用"
                         f"「{get_persona_display(p)}」，超过连续上限")

    # 4. 旁观派连续2章
    for i in range(len(persona_seq) - 1):
        if (persona_seq[i][1] == "witness"
                and persona_seq[i + 1][1] == "witness"):
            warns.append(f"人格轮换警告：第{persona_seq[i][0]}、"
                         f"{persona_seq[i+1][0]}章连续使用「旁观派」，"
                         f"旁观派不宜连续2章，会导致节奏拖沓")

    return fails, warns


# ---------------------------------------------------------------------------
# 记录入口模式和人格
# ---------------------------------------------------------------------------

def record_entry(quota_path, chapter_no, mode_code=None, persona_code=None, gear=None):
    """将本章入口模式和人格记录追加到节奏配额文件。

    在文件末尾创建/更新「入口模式与人格记录」表格。
    返回写入的行文本。
    """
    text = _read_file(quota_path)

    # 构建记录表头和行
    section_header = "## 入口模式与人格记录"
    table_header = "| 章节 | 入口模式 | 人格 | 档位 |"
    table_sep = "|---|---|---|---|"

    mode_display = get_mode_display(mode_code) if mode_code else "—"
    persona_display = get_persona_display(persona_code) if persona_code else "—"
    gear_str = gear or "—"

    new_line = f"| 第{chapter_no}章 | {mode_display} | {persona_display} | {gear_str} |"

    # 检查是否已有记录表
    if section_header in text:
        # 已有表：检查是否已有该章记录
        lines = text.splitlines(keepends=True)
        in_section = False
        insert_idx = None
        replaced = False

        for i, ln in enumerate(lines):
            if ln.strip().startswith(section_header):
                in_section = True
                continue
            if in_section:
                if ln.strip().startswith("## ") or ln.strip().startswith("# "):
                    # 进入下一节
                    if insert_idx is None:
                        insert_idx = i
                    in_section = False
                elif ln.strip().startswith("|"):
                    # 检查是否是该章已有记录
                    if f"第{chapter_no}章" in ln or re.search(rf"\b{chapter_no}\b", ln):
                        # 替换已有记录
                        lines[i] = new_line + "\n"
                        replaced = True
                    insert_idx = i + 1

        if not replaced and insert_idx is not None:
            lines.insert(insert_idx, new_line + "\n")
        elif not replaced and insert_idx is None:
            lines.append(new_line + "\n")

        content = "".join(lines)
    else:
        # 没有记录表：在文件末尾追加
        if not text.endswith("\n"):
            text += "\n"
        content = text + f"\n{section_header}\n\n{table_header}\n{table_sep}\n{new_line}\n"

    try:
        with open(quota_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return None

    return new_line


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_recommend(book_dir, gear, chapter):
    """推荐下一章入口模式。"""
    quota_path = find_quota_path(book_dir)
    if not quota_path.is_file():
        print(f"错误：节奏配额文件不存在：{quota_path}", file=sys.stderr)
        return 2

    history = parse_rhythm_quota(quota_path)
    results, next_chap = recommend_entry_mode(history, gear, chapter)

    print(f"入口模式推荐：第{next_chap}章（档位：{gear}）")
    print()

    # 显示历史
    if history["entries"]:
        print("近期入口模式记录：")
        for chap, mode, persona in history["entries"][-5:]:
            mode_str = get_mode_display(mode) if mode else "—"
            persona_str = get_persona_display(persona) if persona else "—"
            print(f"  第{chap}章：{mode_str} / {persona_str}")
        print()

    print("推荐入口模式（按推荐度排序）：")
    for code, reason, score in results:
        mode = _MODE_BY_CODE[code]
        marker = "★" if score == results[0][2] else " "
        print(f"  {marker} {mode['name']}（{mode['name_en']}）"
              f"  [分数 {score}]")
        print(f"      → {reason}")
        print(f"      → 禁忌：{mode['taboo']}")
        print()

    if results:
        best = results[0]
        mode = _MODE_BY_CODE[best[0]]
        print(f"建议：本章使用「{mode['name']}」入口模式")
    return 0


def cmd_persona(book_dir, gear, chapter, mode_code):
    """推荐下一章小说家人格。"""
    quota_path = find_quota_path(book_dir)
    if not quota_path.is_file():
        print(f"错误：节奏配额文件不存在：{quota_path}", file=sys.stderr)
        return 2

    history = parse_rhythm_quota(quota_path)
    results, next_chap = recommend_persona(history, gear, chapter, mode_code)

    print(f"人格推荐：第{next_chap}章（档位：{gear}）")
    if mode_code:
        print(f"已指定入口模式：{get_mode_display(mode_code)}")
    print()

    # 显示历史
    persona_entries = [(c, m, p) for c, m, p in history["entries"] if p]
    if persona_entries:
        print("近期人格记录：")
        for chap, mode, persona in persona_entries[-5:]:
            mode_str = get_mode_display(mode) if mode else "—"
            persona_str = get_persona_display(persona) if persona else "—"
            print(f"  第{chap}章：{mode_str} / {persona_str}")
        print()

    print("推荐小说家人格（按推荐度排序）：")
    for code, reason, score in results:
        persona = _PERSONA_BY_CODE[code]
        marker = "★" if score == results[0][2] else " "
        print(f"  {marker} {persona['name']}（{persona['name_en']}）"
              f"  [分数 {score}]")
        print(f"      → 风格：{persona['style']}")
        print(f"      → 句长：{persona['avg_sent_len']}，动词占比{persona['verb_ratio']}，"
              f"形容词占比{persona['adj_ratio']}")
        print(f"      → {reason}")
        print()

    if results:
        best = results[0]
        persona = _PERSONA_BY_CODE[best[0]]
        print(f"建议：本章使用「{persona['name']}」人格")
    return 0


def cmd_record(book_dir, chapter_no, mode_code, persona_code, gear):
    """记录本章入口模式和人格。"""
    quota_path = find_quota_path(book_dir)
    if not quota_path.is_file():
        print(f"错误：节奏配额文件不存在：{quota_path}", file=sys.stderr)
        return 2

    if not mode_code and not persona_code:
        print("错误：至少需要指定 --mode 或 --persona 之一", file=sys.stderr)
        return 2

    line = record_entry(quota_path, chapter_no, mode_code, persona_code, gear)
    if line is None:
        print("错误：写入失败", file=sys.stderr)
        return 2

    print(f"已记录：第{chapter_no}章")
    if mode_code:
        print(f"  入口模式：{get_mode_display(mode_code)}")
    if persona_code:
        print(f"  人格：{get_persona_display(persona_code)}")
    if gear:
        print(f"  档位：{gear}")
    print(f"  写入行：{line}")
    return 0


def cmd_list():
    """列出所有入口模式和人格。"""
    print("=" * 70)
    print("8种章节入口模式")
    print("=" * 70)
    for i, mode in enumerate(ENTRY_MODES, 1):
        print(f"\n{i}. {mode['name']}（{mode['name_en']}）")
        print(f"   code: {mode['code']}")
        print(f"   描述：{mode['desc']}")
        print(f"   适用：{mode['scenarios']}")
        print(f"   禁忌：{mode['taboo']}")

    print()
    print("=" * 70)
    print("3种小说家人格")
    print("=" * 70)
    for i, persona in enumerate(PERSONAS, 1):
        print(f"\n{i}. {persona['name']}（{persona['name_en']}）")
        print(f"   code: {persona['code']}")
        print(f"   风格：{persona['style']}")
        print(f"   句长：{persona['avg_sent_len']}，动词占比{persona['verb_ratio']}，"
              f"形容词占比{persona['adj_ratio']}")
        print(f"   适用：{persona['scenarios']}")
        print(f"   禁忌：{persona['taboo']}")

    print()
    print("=" * 70)
    print("入口模式 × 人格 兼容性矩阵")
    print("=" * 70)
    # 表头
    header = f"{'入口模式':<12}"
    for p in PERSONAS:
        header += f" | {p['name']:<8}"
    print(header)
    print("-" * len(header))
    for mode in ENTRY_MODES:
        row = f"{mode['name']:<12}"
        for persona in PERSONAS:
            compat = COMPATIBILITY.get(mode["code"], {}).get(persona["code"], "o")
            row += f" | {_COMPAT_LABEL[compat]:<8}"
        print(row)
    print()
    print("图例：✓ 推荐  ○ 可用  △ 慎用  ✗ 不推荐")
    return 0


def cmd_check(book_dir, chapter):
    """检查近期轮换违规。"""
    quota_path = find_quota_path(book_dir)
    if not quota_path.is_file():
        print(f"错误：节奏配额文件不存在：{quota_path}", file=sys.stderr)
        return 2

    history = parse_rhythm_quota(quota_path)

    target_chap = chapter
    if target_chap is None:
        if history["entries"]:
            target_chap = max(e[0] for e in history["entries"])
        else:
            print("提示：无历史记录可供检查")
            return 0

    print(f"轮换检查：第{target_chap}章及近期记录")
    print()

    if not history["entries"]:
        print("  无入口模式/人格记录")
        return 0

    # 显示近期记录
    print("近期记录：")
    for chap, mode, persona in history["entries"][-8:]:
        mode_str = get_mode_display(mode) if mode else "—"
        persona_str = get_persona_display(persona) if persona else "—"
        print(f"  第{chap}章：{mode_str} / {persona_str}")
    print()

    fails, warns = check_rotation(history, target_chap)

    for f in fails:
        print(f"  [FAIL] {f}")
    for w in warns:
        print(f"  [WARN] {w}")

    if not fails and not warns:
        print("  全部检查通过")
    print()

    if fails:
        print(f"结果：{len(fails)} 项违规" +
              (f"，另 {len(warns)} 项警告" if warns else ""))
        return 1
    if warns:
        print(f"结果：通过（{len(warns)} 项警告，建议关注）")
    else:
        print("结果：通过")
    return 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="章节入口模式与小说家人格推荐器 v1.0：反模板化轮换管理")
    sub = ap.add_subparsers(dest="command", help="子命令")

    # recommend
    p_rec = sub.add_parser("recommend", help="推荐下一章入口模式")
    p_rec.add_argument("book_dir", help="书名目录路径")
    p_rec.add_argument("--gear", default="中", choices=["快", "中", "慢"],
                       help="当前章节档位（默认：中）")
    p_rec.add_argument("--chapter", type=int, default=None,
                       help="指定章号（默认自动推断下一章）")

    # persona
    p_per = sub.add_parser("persona", help="推荐下一章小说家人格")
    p_per.add_argument("book_dir", help="书名目录路径")
    p_per.add_argument("--gear", default="中", choices=["快", "中", "慢"],
                       help="当前章节档位（默认：中）")
    p_per.add_argument("--chapter", type=int, default=None,
                       help="指定章号（默认自动推断下一章）")
    p_per.add_argument("--mode", default=None,
                       help="已选定的入口模式（code或中文名），用于兼容性参考")

    # record
    p_rec2 = sub.add_parser("record", help="记录本章使用的入口模式和人格")
    p_rec2.add_argument("book_dir", help="书名目录路径")
    p_rec2.add_argument("--chapter", type=int, required=True,
                        help="章节号")
    p_rec2.add_argument("--mode", default=None,
                        help="入口模式（code或中文名）")
    p_rec2.add_argument("--persona", default=None,
                        help="人格（code或中文名）")
    p_rec2.add_argument("--gear", default=None, choices=["快", "中", "慢", None],
                        help="档位")

    # list
    sub.add_parser("list", help="列出所有入口模式/人格及兼容性矩阵")

    # check
    p_chk = sub.add_parser("check", help="检查近期轮换是否违规")
    p_chk.add_argument("book_dir", help="书名目录路径")
    p_chk.add_argument("--chapter", type=int, default=None,
                       help="指定检查的章号（默认最新章）")

    args = ap.parse_args()

    if args.command is None:
        ap.print_help()
        return 2

    if args.command == "list":
        return cmd_list()

    # 以下子命令需要 book_dir
    book_dir = Path(args.book_dir)
    if not book_dir.is_dir():
        print(f"错误：书名目录不存在：{book_dir}", file=sys.stderr)
        return 2

    if args.command == "recommend":
        return cmd_recommend(book_dir, args.gear, args.chapter)

    if args.command == "persona":
        mode_code = normalize_mode(args.mode) if args.mode else None
        if args.mode and mode_code is None:
            print(f"警告：无法识别入口模式「{args.mode}」，将忽略兼容性参考",
                  file=sys.stderr)
        return cmd_persona(book_dir, args.gear, args.chapter, mode_code)

    if args.command == "record":
        mode_code = normalize_mode(args.mode) if args.mode else None
        persona_code = normalize_persona(args.persona) if args.persona else None
        if args.mode and mode_code is None:
            print(f"错误：无法识别入口模式「{args.mode}」", file=sys.stderr)
            return 2
        if args.persona and persona_code is None:
            print(f"错误：无法识别人格「{args.persona}」", file=sys.stderr)
            return 2
        return cmd_record(book_dir, args.chapter, mode_code, persona_code, args.gear)

    if args.command == "check":
        return cmd_check(book_dir, args.chapter)

    return 0


if __name__ == "__main__":
    sys.exit(main())
