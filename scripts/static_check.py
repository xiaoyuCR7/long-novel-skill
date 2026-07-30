#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""static_check.py — 跨文件一致性静态守卫（纯标准库，无第三方依赖）。

在写完一章后运行，检查正文与设定/追踪文件之间的跨文件一致性。
是 check_text.py（单章内部检查）的补充，专门检查「这一章和别的文件对不对得上」。

检查项目（每项返回 PASS/WARN/FAIL）：
  1. CHARACTER — 角色名一致性：正文出现的人名是否有对应人物卡
  2. TIMELINE — 时间线一致性：章节间时间推进是否倒退
  3. FORESHADOW — 伏笔状态一致性：正文中回收的伏笔是否在台账标记
  4. SYNC — 章节摘要同步：追踪文件是否更新到最新章节
  5. WORDCOUNT — 字数连续性：相邻章节字数差异是否过大

用法：
  python scripts/static_check.py "{书名目录}"                    # 全量检查
  python scripts/static_check.py "{书名目录}" --chapter 37       # 只检查第37章
  python scripts/static_check.py "{书名目录}" --json               # JSON输出
  python scripts/static_check.py "{书名目录}" --fix                # 输出修复建议

退出码：0 = 全部 PASS；1 = 有 WARN 或 FAIL；2 = 参数错误。
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

# 从 config.py 导入，失败则使用默认值
try:
    from config import (
        STATIC_CHECK_STRICT_CHARACTER,
        STATIC_CHECK_TIMELINE,
        STATIC_CHECK_FORESHADOW,
        TRACKING_FILES,
        SETTING_FILES,
        BOOK_DIRS,
    )
except ImportError:
    STATIC_CHECK_STRICT_CHARACTER = False
    STATIC_CHECK_TIMELINE = True
    STATIC_CHECK_FORESHADOW = True
    TRACKING_FILES = {
        "foreshadow": "伏笔台账.md",
        "character_state": "角色状态.md",
        "chapter_summary": "章节摘要.md",
        "timeline": "时间线.md",
        "rhythm_quota": "节奏配额.md",
    }
    SETTING_FILES = {
        "characters_dir": "角色",
    }
    BOOK_DIRS = {
        "setting": "设定",
        "manuscript": "正文",
        "tracking": "追踪",
    }

# 伏笔回收关键词（正文出现则认为回收了某条伏笔）
FORESHADOW_REVEAL_KEYWORDS = [
    "真相大白", "揭晓", "原来", "解开", "终于明白",
    "恍然大悟", "谜底", "水落石出", "真相", "秘密揭开",
]

# 字数差异告警阈值（百分比）
WORDCOUNT_DIFF_THRESHOLD = 2.0  # 200%

# 追踪文件检查项
SYNC_CHECK_FILES = [
    ("chapter_summary", "章节摘要.md"),
    ("character_state", "角色状态.md"),
    ("rhythm_quota", "节奏配额.md"),
]


# ---------------------------------------------------------------------------
# 结果数据结构
# ---------------------------------------------------------------------------

class CheckResult:
    """单条检查结果。"""

    def __init__(self, category: str, name: str, status: str,
                 message: str = "", details: list = None, fix_hints: list = None):
        self.category = category
        self.name = name
        self.status = status  # PASS / WARN / FAIL
        self.message = message
        self.details = details or []
        self.fix_hints = fix_hints or []

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "fix_hints": self.fix_hints,
        }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _read(path) -> str:
    """安全读取文本文件，失败返回空字符串。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
        return ""


def _parse_chapter_number(filename: str):
    """从文件名解析章节号，返回 int 或 None。"""
    m = re.search(r"第(\d+)章", filename)
    if m:
        return int(m.group(1))
    m = re.search(r"[Cc]hapter[_\-]?(\d+)", filename)
    if m:
        return int(m.group(1))
    return None


def _collect_chapter_files(manuscript_dir: Path):
    """收集正文目录下所有章节文件，返回 [(章节号, Path), ...] 按章节号排序。"""
    if not manuscript_dir.exists():
        return []
    chapters = []
    for f in manuscript_dir.iterdir():
        if not f.is_file():
            continue
        num = _parse_chapter_number(f.name)
        if num is not None:
            chapters.append((num, f))
    chapters.sort(key=lambda x: x[0])
    return chapters


def _count_chinese_chars(text: str) -> int:
    """统计中文字符数。"""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _get_character_names_from_cards(characters_dir: Path) -> set:
    """从 设定/角色/ 目录下所有 .md 文件名提取已注册角色名集合。

    支持：张三.md、张三_别名.md、张三（外号）.md 等格式，
    取括号前的核心名称。
    """
    names = set()
    if not characters_dir.exists():
        return names
    for f in characters_dir.iterdir():
        if not f.is_file() or not f.name.endswith(".md"):
            continue
        # 去掉扩展名
        base = f.name[:-3]
        # 取括号前的部分（如 "张三_别名" 或 "张三（外号）"）
        core = re.split(r"[_\-（\(]", base)[0]
        if core:
            names.add(core.strip())
    return names


def _parse_timeline_entries(timeline_text: str) -> list:
    """解析时间线表格，返回 [(章节号_str, 时间描述, ...), ...]。

    期望格式为 Markdown 表格，每行以 | 开头。
    """
    entries = []
    header_seen = False
    for line in timeline_text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header_seen = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # 跳过分隔行
        if cells and set(cells[0]) <= set("-: "):
            header_seen = True
            continue
        if not header_seen:
            continue  # 跳过表头
        if cells and re.search(r"\d+", cells[0]):
            entries.append(cells)
    return entries


def _parse_foreshadow_ledger(ledger_text: str) -> list:
    """解析伏笔台账，返回 [{"id": ..., "columns": [...], "resolved": bool}, ...]。"""
    entries = []
    header_seen = False
    for line in ledger_text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header_seen = False
            continue
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            header_seen = True
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not header_seen:
            continue
        if cells and re.match(r"^F\d+-\d+$", cells[0]):
            resolved = "✅" in stripped or "已回收" in stripped or "已揭晓" in stripped
            entries.append({
                "id": cells[0],
                "columns": cells[1:] if len(cells) > 1 else [],
                "resolved": resolved,
            })
    return entries


def _parse_summary_entries(summary_text: str) -> list:
    """解析章节摘要，返回 [{"chapter": int, ...}, ...]。"""
    entries = []
    for m in re.finditer(r"^###\s*第(\d+)章", summary_text, re.M):
        entries.append({"chapter": int(m.group(1))})
    return entries


def _parse_character_state(character_state_text: str) -> list:
    """解析角色状态，返回其中出现的章节号列表。"""
    chapter_nums = []
    # 从状态变更记录中提取章号引用
    for m in re.finditer(r"第(\d+)章", character_state_text):
        chapter_nums.append(int(m.group(1)))
    return chapter_nums


def _parse_rhythm_quota(rhythm_text: str) -> list:
    """解析节奏配额，返回其中出现的章节号列表。"""
    chapter_nums = []
    for line in rhythm_text.split("\n"):
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and re.search(r"\d+", cells[0]):
                m = re.search(r"(\d+)", cells[0])
                if m:
                    chapter_nums.append(int(m.group(1)))
    return chapter_nums


# ---------------------------------------------------------------------------
# 检查 1：角色名一致性 (CHARACTER)
# ---------------------------------------------------------------------------

def check_character(book_dir: Path, target_chapter: int = None) -> CheckResult:
    """检查正文出现的角色名是否在 设定/角色/ 有对应人物卡。"""
    characters_dir = book_dir / BOOK_DIRS.get("setting", "设定") / SETTING_FILES.get("characters_dir", "角色")
    manuscript_dir = book_dir / BOOK_DIRS.get("manuscript", "正文")

    registered = _get_character_names_from_cards(characters_dir)
    chapters = _collect_chapter_files(manuscript_dir)

    # 筛选目标章节
    if target_chapter is not None:
        chapters = [(num, path) for num, path in chapters if num == target_chapter]

    if not chapters:
        return CheckResult("CHARACTER", "角色名一致性", "PASS",
                           "无正文章节可供检查")

    unregistered_set = set()
    # 扫描正文中出现的人名模式：已注册的 + 未知的中文名（2-4字连续中文且被引号或描述词包围）
    # 方法：列出所有已注册名在正文中的出现，并寻找未注册但频繁出现的2-4字中文词
    for num, path in chapters:
        text = _read(path)
        if not text:
            continue
        # 提取正文中的中文词（2-4字），排除单字、排除常见虚词，
        # 看是否有未在 registered 中的词高频出现
        chinese_words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
        word_freq = Counter(chinese_words)

        # 过滤掉常见虚词/非人名词
        non_person_words = {
            "这个", "那个", "什么", "怎么", "为什么", "可以", "没有", "不是",
            "已经", "一个", "自己", "他们", "她们", "我们", "你们", "这里",
            "那里", "知道", "看到", "觉得", "开始", "起来", "下来", "出来",
            "不过", "虽然", "但是", "因为", "所以", "如果", "这样", "那样",
            "只是", "而且", "或者", "这些", "那些", "之后", "之前", "于是",
            "然后", "终于", "突然", "之间", "同时", "然而", "此刻", "这时",
            "一直", "似乎", "可能", "应该", "不过", "仍然", "倒也", "反而",
            "竟然", "果然", "忽然", "尽管", "否则", "而且", "只是", "其实",
            "当下", "如此", "怎样", "何等", "这般", "十分", "非常", "实在",
            "有些", "是否", "能否", "只见", "只见得", "此时", "当时", "只听",
        }
        # 出现 >= 3 次的词可能是人名
        candidates = {w: c for w, c in word_freq.items()
                      if c >= 3 and w not in non_person_words and w not in registered}
        if candidates:
            unregistered_set.update(candidates.keys())

    if not unregistered_set:
        return CheckResult("CHARACTER", "角色名一致性", "PASS",
                           "所有正文角色名均有对应人物卡")

    # 排除一些常见非人名的2-4字词
    # 进一步过滤：这些候选词中有些可能是地名/物品名等，只做提示
    status = "FAIL" if STATIC_CHECK_STRICT_CHARACTER else "WARN"
    unreg_list = sorted(unregistered_set)
    fix_hints = [
        f"在 设定/角色/ 目录下为以下疑似角色名创建人物卡：{', '.join(unreg_list[:10])}",
    ]
    if STATIC_CHECK_STRICT_CHARACTER:
        fix_hints.append("当前为严格模式（STATIC_CHECK_STRICT_CHARACTER=True），"
                         "可在 config.py 中设为 False 以降级为 WARN")
    return CheckResult(
        "CHARACTER", "角色名一致性", status,
        f"发现 {len(unreg_list)} 个疑似未注册角色名：{', '.join(unreg_list[:10])}",
        details=unreg_list,
        fix_hints=fix_hints,
    )


# ---------------------------------------------------------------------------
# 检查 2：时间线一致性 (TIMELINE)
# ---------------------------------------------------------------------------

def check_timeline(book_dir: Path, target_chapter: int = None) -> CheckResult:
    """检查章节间时间推进是否倒退。"""
    if not STATIC_CHECK_TIMELINE:
        return CheckResult("TIMELINE", "时间线一致性", "PASS",
                           "时间线检查已禁用（STATIC_CHECK_TIMELINE=False）")

    timeline_file = book_dir / BOOK_DIRS.get("tracking", "追踪") / TRACKING_FILES.get("timeline", "时间线.md")
    timeline_text = _read(timeline_file)

    if not timeline_text:
        return CheckResult("TIMELINE", "时间线一致性", "PASS",
                           "时间线文件不存在或为空（跳过）")

    entries = _parse_timeline_entries(timeline_text)
    if len(entries) < 2:
        return CheckResult("TIMELINE", "时间线一致性", "PASS",
                           "时间线条目不足2条，无法比较")

    # 如果指定了章节，只检查该章节与前一章
    if target_chapter is not None:
        relevant = []
        for e in entries:
            m = re.search(r"(\d+)", e[0])
            if m:
                ch_num = int(m.group(1))
                if ch_num == target_chapter or ch_num == target_chapter - 1:
                    relevant.append((ch_num, e))
        relevant.sort(key=lambda x: x[0])
        if len(relevant) < 2:
            return CheckResult("TIMELINE", "时间线一致性", "PASS",
                               f"时间线中未找到第{target_chapter}章及其前一章")
        entries_to_check = [r[1] for r in relevant]
    else:
        entries_to_check = entries

    # 尝试从时间列提取相对排序信息
    # 时间线表格通常列：章节 | 故事内时间 | 事件 | ...
    # 我们检查相邻条目的"故事内时间"是否有明显倒退
    time_descs = []  # 收集每条的时间描述

    for e in entries_to_check:
        # 时间描述通常在第2列（索引1）
        time_desc = e[1] if len(e) > 1 else ""
        time_descs.append((e[0], time_desc))

    # 解析时间描述中的数字线索（如"第三天""一月""第X年"等）
    def _extract_time_order(desc: str) -> int:
        """从时间描述提取相对顺序数字，失败返回 -1。"""
        if not desc:
            return -1
        # "第X天/年/月/周"
        m = re.search(r"第(\d+)[天年月周]", desc)
        if m:
            return int(m.group(1))
        # "X月X日"
        m = re.search(r"(\d+)月", desc)
        if m:
            month = int(m.group(1))
            m2 = re.search(r"(\d+)日", desc)
            day = int(m2.group(1)) if m2 else 1
            return month * 100 + day
        # "X年"
        m = re.search(r"(\d+)年", desc)
        if m:
            return int(m.group(1)) * 10000
        return -1

    # 检查相邻条目时间是否倒退
    regressions = []
    for i in range(1, len(time_descs)):
        ch_from, desc_from = time_descs[i - 1]
        ch_to, desc_to = time_descs[i]
        order_from = _extract_time_order(desc_from)
        order_to = _extract_time_order(desc_to)

        if order_from != -1 and order_to != -1 and order_to < order_from:
            regressions.append({
                "chapter_from": ch_from,
                "chapter_to": ch_to,
                "time_from": desc_from,
                "time_to": desc_to,
            })

    if regressions:
        details = [f"第{r['chapter_from']}章({r['time_from']}) → "
                   f"第{r['chapter_to']}章({r['time_to']})" for r in regressions]
        fix_hints = [
            "检查时间线表格中标记的时间是否正确，确认是否存在闪回/插叙",
            "如确为闪回情节，在时间线中注明「闪回」以避免误报",
        ]
        return CheckResult(
            "TIMELINE", "时间线一致性", "FAIL",
            f"发现 {len(regressions)} 处时间倒退",
            details=details,
            fix_hints=fix_hints,
        )

    return CheckResult("TIMELINE", "时间线一致性", "PASS",
                       "时间线推进正常，无倒退")


# ---------------------------------------------------------------------------
# 检查 3：伏笔状态一致性 (FORESHADOW)
# ---------------------------------------------------------------------------

def check_foreshadow(book_dir: Path, target_chapter: int = None) -> CheckResult:
    """检查正文中回收的伏笔是否在台账标记为已回收。"""
    if not STATIC_CHECK_FORESHADOW:
        return CheckResult("FORESHADOW", "伏笔状态一致性", "PASS",
                           "伏笔检查已禁用（STATIC_CHECK_FORESHADOW=False）")

    ledger_file = book_dir / BOOK_DIRS.get("tracking", "追踪") / TRACKING_FILES.get("foreshadow", "伏笔台账.md")
    manuscript_dir = book_dir / BOOK_DIRS.get("manuscript", "正文")

    ledger_text = _read(ledger_file)
    if not ledger_text:
        return CheckResult("FORESHADOW", "伏笔状态一致性", "PASS",
                           "伏笔台账不存在或为空（跳过）")

    ledger_entries = _parse_foreshadow_ledger(ledger_text)
    chapters = _collect_chapter_files(manuscript_dir)

    if target_chapter is not None:
        chapters = [(num, path) for num, path in chapters if num == target_chapter]

    if not chapters:
        return CheckResult("FORESHADOW", "伏笔状态一致性", "PASS",
                           "无正文章节可供检查")

    # 找出台账中未标记为已回收的活跃伏笔
    unresolved = [e for e in ledger_entries if not e["resolved"]]
    if not unresolved:
        return CheckResult("FORESHADOW", "伏笔状态一致性", "PASS",
                           "无活跃伏笔（均已回收或台账为空）")

    # 扫描最新章节正文，检查是否包含伏笔回收关键词
    # 重点关注最新章节
    checked_chapters = chapters[-3:]  # 检查最近3章
    revealed_in_text = []
    for num, path in checked_chapters:
        text = _read(path)
        if not text:
            continue
        for kw in FORESHADOW_REVEAL_KEYWORDS:
            if kw in text:
                # 进一步检查：回收关键词附近是否提及某条伏笔
                for entry in unresolved:
                    eid = entry["id"]
                    desc = " ".join(entry["columns"])
                    # 如果伏笔ID或描述关键词出现在同一章节
                    if eid in text or (desc and any(w in text for w in re.findall(r"[\u4e00-\u9fff]{2,6}", desc)[:5])):
                        revealed_in_text.append({
                            "chapter": num,
                            "foreshadow_id": eid,
                            "keyword": kw,
                        })

    if not revealed_in_text:
        return CheckResult("FORESHADOW", "伏笔状态一致性", "PASS",
                           "正文中未发现伏笔回收迹象")

    # 去重
    seen = set()
    unique_reveals = []
    for r in revealed_in_text:
        key = (r["chapter"], r["foreshadow_id"])
        if key not in seen:
            seen.add(key)
            unique_reveals.append(r)

    details = [f"第{r['chapter']}章发现回收关键词「{r['keyword']}」，"
               f"疑似涉及伏笔 {r['foreshadow_id']}（台账未标记已回收）"
               for r in unique_reveals]
    fix_hints = [
        "在伏笔台账中将对应伏笔移入 ✅ 已回收 分节",
        "或确认该关键词与伏笔无关后忽略此告警",
    ]
    return CheckResult(
        "FORESHADOW", "伏笔状态一致性", "WARN",
        f"发现 {len(unique_reveals)} 处疑似伏笔回收但台账未标记",
        details=details,
        fix_hints=fix_hints,
    )


# ---------------------------------------------------------------------------
# 检查 4：章节摘要同步 (SYNC)
# ---------------------------------------------------------------------------

def check_sync(book_dir: Path, target_chapter: int = None) -> CheckResult:
    """检查追踪文件是否更新到最新章节。"""
    manuscript_dir = book_dir / BOOK_DIRS.get("manuscript", "正文")
    chapters = _collect_chapter_files(manuscript_dir)
    if not chapters:
        return CheckResult("SYNC", "章节摘要同步", "PASS",
                           "无正文章节可供检查")

    latest_chapter = chapters[-1][0]
    if target_chapter is not None:
        latest_chapter = target_chapter

    tracking_dir = book_dir / BOOK_DIRS.get("tracking", "追踪")
    missing = []

    for key, filename in SYNC_CHECK_FILES:
        filepath = tracking_dir / filename
        text = _read(filepath)
        if not text:
            missing.append(f"{filename}（文件不存在或为空）")
            continue

        # 检查是否包含最新章节号
        if key == "chapter_summary":
            # 章节摘要：应有 ### 第N章 标题
            if not re.search(rf"###\s*第\s*{latest_chapter}\s*章", text):
                missing.append(f"{filename}（缺少第{latest_chapter}章摘要）")
        elif key == "character_state":
            # 角色状态：检查状态变更记录中是否提及最新章节
            chapter_nums = _parse_character_state(text)
            if latest_chapter not in chapter_nums:
                # 也检查第二新章节（可能刚写完还没更新角色状态）
                second_latest = chapters[-2][0] if len(chapters) >= 2 else 0
                if latest_chapter > second_latest:
                    missing.append(f"{filename}（未更新到第{latest_chapter}章）")
        elif key == "rhythm_quota":
            # 节奏配额：检查是否记录了最新章节
            chapter_nums = _parse_rhythm_quota(text)
            if latest_chapter not in chapter_nums:
                missing.append(f"{filename}（缺少第{latest_chapter}章配额记录）")

    if not missing:
        return CheckResult("SYNC", "章节摘要同步", "PASS",
                           f"追踪文件均已同步至第{latest_chapter}章")

    fix_hints = []
    for m in missing:
        fname = m.split("（")[0]
        fix_hints.append(f"更新 {fname}，补充第{latest_chapter}章的相关记录")

    return CheckResult(
        "SYNC", "章节摘要同步", "WARN",
        f"{len(missing)} 项追踪文件未同步至第{latest_chapter}章",
        details=missing,
        fix_hints=fix_hints,
    )


# ---------------------------------------------------------------------------
# 检查 5：字数连续性 (WORDCOUNT)
# ---------------------------------------------------------------------------

def check_wordcount(book_dir: Path, target_chapter: int = None) -> CheckResult:
    """检查最近5章正文字数，相邻章节差异过大时告警。"""
    manuscript_dir = book_dir / BOOK_DIRS.get("manuscript", "正文")
    chapters = _collect_chapter_files(manuscript_dir)

    if target_chapter is not None:
        chapters = [(num, path) for num, path in chapters if num == target_chapter]
        # 单章检查无相邻对比意义
        if len(chapters) <= 1:
            return CheckResult("WORDCOUNT", "字数连续性", "PASS",
                               "单章模式下无法进行相邻字数对比")
    else:
        # 取最近5章
        chapters = chapters[-5:]

    if len(chapters) < 2:
        return CheckResult("WORDCOUNT", "字数连续性", "PASS",
                           "章节数不足2章，无法进行相邻字数对比")

    wordcounts = []
    for num, path in chapters:
        text = _read(path)
        wc = _count_chinese_chars(text)
        wordcounts.append((num, wc))

    # 检查相邻章节字数差异
    warnings = []
    for i in range(1, len(wordcounts)):
        prev_num, prev_wc = wordcounts[i - 1]
        curr_num, curr_wc = wordcounts[i]
        if prev_wc == 0:
            continue
        ratio = curr_wc / prev_wc
        if ratio > WORDCOUNT_DIFF_THRESHOLD or ratio < (1.0 / WORDCOUNT_DIFF_THRESHOLD):
            diff_pct = abs(curr_wc - prev_wc) / prev_wc * 100
            warnings.append(
                f"第{prev_num}章({prev_wc}字) → 第{curr_num}章({curr_wc}字)，"
                f"差异 {diff_pct:.0f}%"
            )

    if not warnings:
        wc_str = " → ".join(f"第{n}({c}字)" for n, c in wordcounts)
        return CheckResult("WORDCOUNT", "字数连续性", "PASS",
                           f"相邻章节字数差异正常：{wc_str}")

    fix_hints = [
        "检查字数异常章节是否有内容遗漏或注水",
        "如为特殊设计（如过渡章极短），可在章纲中注明意图",
    ]
    return CheckResult(
        "WORDCOUNT", "字数连续性", "WARN",
        f"发现 {len(warnings)} 处相邻章节字数差异超过{int(WORDCOUNT_DIFF_THRESHOLD * 100)}%",
        details=warnings,
        fix_hints=fix_hints,
    )


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def _colorize(text: str, status: str) -> str:
    """根据状态返回带颜色的文本。"""
    if not sys.stdout.isatty():
        return text
    colors = {
        "PASS": "\033[92m",   # 绿
        "WARN": "\033[93m",   # 黄
        "FAIL": "\033[91m",   # 红
        "reset": "\033[0m",
    }
    code = colors.get(status, "")
    reset = colors.get("reset", "")
    return f"{code}{text}{reset}"


def format_human(results: list, show_fix: bool = False) -> str:
    """格式化为人类可读的报告。"""
    lines = []
    lines.append("=" * 60)
    lines.append("跨文件一致性静态检查报告".center(52))
    lines.append("=" * 60)

    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    total = len(results)

    for r in results:
        tag = _colorize(f"[{r.status}]", r.status)
        lines.append(f"\n  {tag} {r.category} — {r.name}")
        lines.append(f"        {r.message}")
        if r.details:
            for d in r.details:
                lines.append(f"          · {d}")
        if show_fix and r.fix_hints:
            lines.append("        修复建议：")
            for hint in r.fix_hints:
                lines.append(f"          → {hint}")

    lines.append("")
    lines.append("-" * 60)
    summary = f"总计：{total} 项  PASS: {pass_count}  WARN: {warn_count}  FAIL: {fail_count}"
    lines.append(summary)
    lines.append("-" * 60)

    return "\n".join(lines)


def format_json(results: list) -> str:
    """格式化为 JSON。"""
    data = {
        "results": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r.status == "PASS"),
            "warn": sum(1 for r in results if r.status == "WARN"),
            "fail": sum(1 for r in results if r.status == "FAIL"),
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_checks(book_dir: Path, target_chapter: int = None) -> list:
    """运行所有检查，返回 CheckResult 列表。"""
    results = []
    results.append(check_character(book_dir, target_chapter))
    results.append(check_timeline(book_dir, target_chapter))
    results.append(check_foreshadow(book_dir, target_chapter))
    results.append(check_sync(book_dir, target_chapter))
    results.append(check_wordcount(book_dir, target_chapter))
    return results


def main():
    # Windows 终端编码兼容
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="跨文件一致性静态守卫 — 检查正文与设定/追踪文件的一致性"
    )
    ap.add_argument("book_root", help="书籍工程目录路径")
    ap.add_argument("--chapter", type=int, default=None,
                    help="只检查指定章节号（如 37）")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="以 JSON 格式输出结果")
    ap.add_argument("--fix", action="store_true",
                    help="输出修复建议（不自动修复）")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    book_dir = Path(book_root)

    # 验证是否为书籍工程目录
    has_tracking = (book_dir / BOOK_DIRS.get("tracking", "追踪")).exists()
    has_manuscript = (book_dir / BOOK_DIRS.get("manuscript", "正文")).exists()
    if not has_tracking and not has_manuscript:
        print(f"错误：{book_root} 不是有效的书籍工程目录"
              f"（缺少「{BOOK_DIRS.get('tracking', '追踪')}」或「{BOOK_DIRS.get('manuscript', '正文')}」目录）",
              file=sys.stderr)
        return 2

    results = run_checks(book_dir, args.chapter)

    if args.as_json:
        print(format_json(results))
    else:
        print(format_human(results, show_fix=args.fix))

    # 退出码：0=全PASS，1=有WARN/FAIL
    has_issues = any(r.status in ("WARN", "FAIL") for r in results)
    return 1 if has_issues else 0


if __name__ == "__main__":
    sys.exit(main())
