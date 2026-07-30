#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks.py — 自动化 Hook 机制（纯标准库，无第三方依赖）。

参考 oh-story-claudecode 的自动化 hook 设计，但改为纯 Python 标准库实现，
适配本 skill 的四目录文件结构（正文/、大纲/、追踪/、设定/）。

五个子命令：
  1. session-start    会话开始时显示进度快照
  2. guard-outline    写正文前检查大纲是否存在
  3. check-prose      正文写入后轻量扫描
  4. detect-gaps      检测设定缺口
  5. pre-compact      上下文压缩前保存进度快照

用法：
  python scripts/hooks.py session-start "{书名目录}"
  python scripts/hooks.py guard-outline "{书名目录}" --chapter 37
  python scripts/hooks.py check-prose "正文/第037章_标题.md" --book-dir "{书名目录}"
  python scripts/hooks.py detect-gaps "{书名目录}"
  python scripts/hooks.py pre-compact "{书名目录}"

退出码：0 = 正常/通过；1 = 有 blocking 问题；2 = 参数错误。
"""

import argparse
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

# =========================================================
# 常量与正则
# =========================================================

CHAPTER_FILE_RE = re.compile(r"第\s*(\d+)\s*章")

# 结尾终止标点
ENDING_PUNCT = set("。！？!?\"」』…—~")

# ---- check-prose 用到的毒句式（取最常见的 5 种，与 check_text.py 一致） ----
QUICK_TOXIC_PATTERNS = [
    (re.compile(r"不是[^。！？\n]{1,30}[，,][^。！？\n]{0,12}而是"),
     "not-is-comparison", "「不是A，而是B」句式"),
    (re.compile(r"没有[^。！？\n]{1,20}[，,]\s*只有"),
     "no-only", "「没有X，只有Y」句式"),
    (re.compile(r"(?:没有|无)[^。！？\n]{1,14}[，,](?:也)?(?:没有|无)[^。！？\n]{1,14}"),
     "negation-parade", "否定排比（没有X，没有Y连排）"),
    (re.compile(r"是[^。！？\n]{1,20}[，,]\s*(?:而)?不是[^。！？\n]{1,20}"),
     "reverse-not-is", "反序对比（是A，不是B）"),
    (re.compile(r"声音(?:不大|不高|很轻|轻柔|平静|平淡|低)[^。！？\n]{0,20}却"),
     "voice-contrast", "音量反差腔（声音不大…却…）"),
]

# 工程词/元信息泄漏模式
META_LEAK_PATTERNS = [
    re.compile(r"\[说明[：:]"),
    re.compile(r"\[TODO"),
    re.compile(r"本章目标"),
    re.compile(r"情节点"),
    re.compile(r"伏笔"),
    re.compile(r"细纲"),
    re.compile(r"章纲"),
    re.compile(r"大纲"),
    re.compile(r"钩子"),
    re.compile(r"铺垫[：:]"),
    re.compile(r"\[备注[：:]"),
    re.compile(r"<!--\s*"),
]

# 英文标点混入模式
ENG_PUNCT_RE = re.compile(r"(?<=[一-鿿㐀-䶿豈-﫿]),|,(?=[一-鿿㐀-䶿豈-﫿])")   # 中文旁边英文逗号
ENG_PERIOD_RE = re.compile(r"(?<=[一-鿿㐀-䶿豈-﫿])\.(?=[一-鿿㐀-䶿豈-﫿])")  # 中文之间英文句号
ENG_SEMICOLON_RE = re.compile(r";(?=[一-鿿㐀-䶿豈-﫿])")                    # 英文分号

# 省略号堆叠
ELLIPSIS_STACK_RE = re.compile(r"\.{4,}|…{2,}|…\.{2,}|\.{2,}…")


# =========================================================
# 通用工具函数
# =========================================================

def _ensure_utf8():
    """确保 stdout/stderr 使用 UTF-8 编码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _read_file(path):
    """安全读取文件，失败返回空字符串。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


def _load_json(path):
    """安全读取 JSON 文件，失败返回 None。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    """安全写入 JSON 文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_last_chapter(book_root):
    """返回 (章号, 文件路径) 或 (None, None)。"""
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


def _find_chapter_files(book_root, chapter_no):
    """查找指定章节号的正文文件列表。"""
    prose_dir = os.path.join(book_root, "正文")
    results = []
    if not os.path.isdir(prose_dir):
        return results
    for name in os.listdir(prose_dir):
        m = re.match(rf"^第\s*0*{chapter_no}\s*章.*\.md$", name)
        if m:
            results.append(os.path.join(prose_dir, name))
    return results


def _find_outline_files(book_root, chapter_no):
    """查找指定章节的章纲文件列表。"""
    outline_dir = os.path.join(book_root, "大纲")
    results = []
    if not os.path.isdir(outline_dir):
        return results
    for name in os.listdir(outline_dir):
        m = re.match(rf"^章纲_第\s*0*{chapter_no}\s*章.*\.md$", name)
        if m:
            results.append(os.path.join(outline_dir, name))
    return results


def _extract_chapter_no_from_filename(filepath):
    """从文件名中提取章节号。"""
    basename = os.path.basename(filepath)
    m = CHAPTER_FILE_RE.search(basename)
    return int(m.group(1)) if m else None


def _count_chars(text):
    """统计非空白字符数。"""
    return len(re.sub(r"\s", "", text))


# =========================================================
# session-start：会话开始时显示进度快照
# =========================================================

def cmd_session_start(book_root):
    """读取书籍工程状态，输出进度快照。"""
    book_root = os.path.abspath(book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    # 取书名
    book_name = os.path.basename(book_root)

    # 查找最新章节
    last_no, last_path = find_last_chapter(book_root)
    next_no = (last_no + 1) if last_no is not None else 1

    # 门禁状态
    gate_status = "N/A"
    gate_debts = []
    if last_no is not None:
        gate_path = os.path.join(book_root, "追踪", "门禁", f"gate_ch{last_no}.json")
        gate_data = _load_json(gate_path)
        if gate_data is None:
            gate_status = "缺失"
            gate_debts.append(f"第{last_no}章门禁缺失")
        elif gate_data.get("passed"):
            gate_status = "通过"
        else:
            gate_status = "未通过"
            gate_debts.append(f"第{last_no}章门禁未通过")

    # 追踪文件同步状态
    tracking_dir = os.path.join(book_root, "追踪")
    sync_items = []  # (文件名, 是否同步)
    if last_no is not None:
        # 章节摘要
        summary = os.path.join(tracking_dir, "章节摘要.md")
        if os.path.isfile(summary):
            text = _read_file(summary)
            synced = bool(re.search(rf"第\s*0*{last_no}\s*章", text))
            sync_items.append(("章节摘要.md", synced))
        else:
            sync_items.append(("章节摘要.md", None))  # 不存在

        # 节奏配额
        quota = os.path.join(tracking_dir, "节奏配额.md")
        if os.path.isfile(quota):
            text = _read_file(quota)
            rows = [ln for ln in text.splitlines()
                    if ln.strip().startswith("|")
                    and re.match(rf"^\|\s*0*{last_no}\s*\|", ln.strip())]
            sync_items.append(("节奏配额.md", bool(rows)))
        else:
            sync_items.append(("节奏配额.md", None))

        # 伏笔台账
        ledger = os.path.join(tracking_dir, "伏笔台账.md")
        if os.path.isfile(ledger):
            sync_items.append(("伏笔台账.md", True))
        else:
            sync_items.append(("伏笔台账.md", None))

        # 大纲锚点
        anchor = os.path.join(book_root, "大纲", "outline_anchors.json")
        sync_items.append(("outline_anchors.json", os.path.isfile(anchor)))

    total = len(sync_items)
    synced_count = sum(1 for _, s in sync_items if s is True)
    if total > 0 and synced_count == total:
        sync_str = f"{total}/{total} 同步"
    else:
        parts = []
        for name, s in sync_items:
            if s is True:
                parts.append(name)
            elif s is False:
                parts.append(f"{name}(未同步)")
            else:
                parts.append(f"{name}(不存在)")
        sync_str = f"{synced_count}/{total} — {', '.join(parts)}"

    # 伏笔台账统计
    foreshadow_active = 0
    foreshadow_overdue = 0
    ledger = os.path.join(tracking_dir, "伏笔台账.md")
    if os.path.isfile(ledger):
        text = _read_file(ledger)
        section = None
        for line in text.splitlines():
            h = re.match(r"^#{1,4}\s*(.+)", line)
            if h:
                t = h.group(1)
                if "活跃" in t or "进行中" in t or "跟踪" in t:
                    section = "active"
                elif "🔴" in t or "超期" in t:
                    section = "overdue"
                elif "已完成" in t or "已回收" in t:
                    section = "done"
                else:
                    section = None
                continue
            if section == "active" and line.strip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] and cells[0] != "ID" and not set(cells[0]) <= set("-: "):
                    foreshadow_active += 1
            elif section == "overdue" and line.strip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] and cells[0] != "ID" and not set(cells[0]) <= set("-: "):
                    foreshadow_overdue += 1

    # 近3章节奏配额
    rhythm_str = "N/A"
    quota_file = os.path.join(tracking_dir, "节奏配额.md")
    if os.path.isfile(quota_file):
        text = _read_file(quota_file)
        recent = []
        for line in text.splitlines():
            m = re.match(r"^\|\s*(\d+)\s*\|\s*(\w*)\s*\|", line.strip())
            if m:
                recent.append((int(m.group(1)), m.group(2).strip() or "none"))
        recent.sort(key=lambda x: x[0])
        if recent:
            # 取最近3章
            last_three = recent[-3:]
            last_three_nums = [x[0] for x in last_three]
            # 找到章节号最大的3个
            all_nums = sorted(set(x[0] for x in recent))
            top3_nums = all_nums[-3:] if len(all_nums) >= 3 else all_nums
            rhythm_parts = []
            for num in top3_nums:
                entry = [x[1] for x in recent if x[0] == num]
                rhythm_parts.append(entry[0] if entry else "none")
            rhythm_str = f"近3章 {rhythm_parts}"

    # 下一章建议
    next_hint = []
    outlines = _find_outline_files(book_root, next_no)
    if outlines:
        next_hint.append(f"可开写第{next_no}章，章纲已就位")
    else:
        next_hint.append(f"第{next_no}章章纲未建，需先补纲")

    # 输出快照
    print("=" * 30 + " 书籍工程状态 " + "=" * 30)
    print(f"书名：{book_name}")
    if last_no is not None:
        print(f"最新章节：第{last_no}章")
    else:
        print("最新章节：无（开书/备纲阶段）")
    print(f"门禁状态：{gate_status}")
    print(f"追踪文件：{sync_str}")
    print(f"伏笔台账：{foreshadow_active}活跃 / {foreshadow_overdue}超期")
    print(f"节奏配额：{rhythm_str}")
    print(f"下一步：{', '.join(next_hint)}")

    if gate_debts:
        print()
        for d in gate_debts:
            print(f"  [!] {d}")

    print("=" * 68)

    return 1 if gate_debts else 0


# =========================================================
# guard-outline：写正文前检查大纲是否存在
# =========================================================

def cmd_guard_outline(book_root, chapter_no):
    """检查指定章节的章纲是否存在。"""
    book_root = os.path.abspath(book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    outlines = _find_outline_files(book_root, chapter_no)

    if not outlines:
        # 也检查短篇的小节大纲（节纲_第NNN章_第N节.md）
        outline_dir = os.path.join(book_root, "大纲")
        section_outlines = []
        if os.path.isdir(outline_dir):
            for name in os.listdir(outline_dir):
                m = re.match(rf"^节纲_第\s*0*{chapter_no}\s*章.*\.md$", name)
                if m:
                    section_outlines.append(os.path.join(outline_dir, name))

        if not section_outlines:
            print(f"[GUARD-OUTLINE] 阻止：第{chapter_no}章章纲不存在", file=sys.stderr)
            print(f"  请先创建章纲：大纲/章纲_第{chapter_no:03d}章*.md", file=sys.stderr)
            return 1
        else:
            print(f"[GUARD-OUTLINE] 确认：第{chapter_no}章有小节大纲（{len(section_outlines)} 个节纲）")
            return 0
    else:
        names = [os.path.basename(p) for p in outlines]
        print(f"[GUARD-OUTLINE] 确认：第{chapter_no}章章纲已存在")
        for n in names:
            print(f"  大纲/{n}")
        return 0


# =========================================================
# check-prose：正文写入后轻量扫描
# =========================================================

def _check_truncation(text):
    """截断检测：正文是否突然中断。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"status": "pass", "detail": "空文件"}

    # 检查最后几行是否有不完整的句子
    tail_lines = lines[-3:] if len(lines) >= 3 else lines
    issues = []
    for line in tail_lines:
        stripped = line.strip()
        if stripped and stripped[-1] not in ENDING_PUNCT:
            # 排除正常段落中间的行
            if len(stripped) < 15:
                issues.append(f"末尾不完整：{stripped[:40]}")

    # 最终判断：末行
    last = lines[-1].strip()
    if last and last[-1] not in ENDING_PUNCT:
        issues.append(f"末行无终止标点：{last[:50]}")
        return {"status": "fail", "detail": "; ".join(issues)}

    return {"status": "pass", "detail": "末尾标点正常"}


def _check_meta_leak(text):
    """工程词/元信息检测：正文中是否混入元信息。"""
    items = []
    for pat in META_LEAK_PATTERNS:
        for m in pat.finditer(text):
            # 获取匹配行
            start = m.start()
            line_start = text.rfind("\n", 0, start) + 1
            line_end = text.find("\n", start)
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end].strip()
            items.append(line if len(line) <= 60 else line[:57] + "...")
            break  # 每种模式只报一处

    if items:
        return {"status": "fail", "items": items}
    return {"status": "pass", "items": []}


def _check_toxic_patterns(text):
    """毒句式快速扫描：检查最常见的5种毒句式。"""
    hits = []
    for pat, rule_id, label in QUICK_TOXIC_PATTERNS:
        matches = list(pat.finditer(text))
        if matches:
            for m in matches[:3]:  # 每种最多报3处
                start = m.start()
                line_start = text.rfind("\n", 0, start) + 1
                line_end = text.find("\n", start)
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end].strip()
                preview = line if len(line) <= 50 else line[:47] + "..."
                hits.append({"rule": rule_id, "label": label, "preview": preview})

    count = len(hits)
    if count > 0:
        return {"status": "fail", "count": count, "items": hits}
    return {"status": "pass", "count": 0, "items": []}


def _check_word_count(text, min_chars=2000):
    """字数检查：是否达到最低字数。"""
    chars = _count_chars(text)
    if chars >= min_chars:
        return {"status": "pass", "chars": chars, "min": min_chars}
    return {"status": "warning", "chars": chars, "min": min_chars}


def _check_punctuation(text):
    """标点快速检查：英文标点混入、省略号堆叠。"""
    issues = []

    # 英文逗号
    eng_commas = ENG_PUNCT_RE.findall(text)
    if eng_commas:
        issues.append(f"英文逗号混入（{len(eng_commas)} 处）")

    # 英文句号
    eng_periods = ENG_PERIOD_RE.findall(text)
    if eng_periods:
        issues.append(f"英文句号混入（{len(eng_periods)} 处）")

    # 英文分号
    eng_semicolons = ENG_SEMICOLON_RE.findall(text)
    if eng_semicolons:
        issues.append(f"英文分号混入（{len(eng_semicolons)} 处）")

    # 省略号堆叠
    ellipsis_matches = ELLIPSIS_STACK_RE.findall(text)
    if ellipsis_matches:
        issues.append(f"省略号异常（{len(ellipsis_matches)} 处）")

    if issues:
        return {"status": "warning", "issues": len(issues), "details": issues}
    return {"status": "pass", "issues": 0, "details": []}


def cmd_check_prose(file_path, book_dir):
    """正文写入后轻量扫描。"""
    file_path = os.path.abspath(file_path)

    if not os.path.isfile(file_path):
        result = {
            "file": file_path,
            "error": f"文件不存在: {file_path}",
            "overall": "error",
            "blocking": [],
            "warnings": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    text = _read_file(file_path)
    if not text.strip():
        result = {
            "file": file_path,
            "checks": {
                "truncation": {"status": "pass", "detail": "空文件"},
                "meta_leak": {"status": "pass", "items": []},
                "toxic_patterns": {"status": "pass", "count": 0, "items": []},
                "word_count": {"status": "fail", "chars": 0, "min": 2000},
                "punctuation": {"status": "pass", "issues": 0, "details": []},
            },
            "overall": "fail",
            "blocking": ["word_count"],
            "warnings": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    checks = {}
    blocking = []
    warnings = []

    # 截断检测
    checks["truncation"] = _check_truncation(text)
    if checks["truncation"]["status"] == "fail":
        blocking.append("truncation")

    # 工程词检测
    checks["meta_leak"] = _check_meta_leak(text)
    if checks["meta_leak"]["status"] == "fail":
        blocking.append("meta_leak")

    # 毒句式扫描
    checks["toxic_patterns"] = _check_toxic_patterns(text)
    if checks["toxic_patterns"]["status"] == "fail":
        blocking.append("toxic_patterns")

    # 字数检查
    min_chars = 2000
    # 尝试从书籍工程读取最低字数设置
    if book_dir:
        settings_dir = os.path.join(os.path.abspath(book_dir), "设定")
        config_file = os.path.join(settings_dir, "写作配置.json")
        if os.path.isfile(config_file):
            config = _load_json(config_file)
            if config and isinstance(config.get("min_chapter_chars"), (int, float)):
                min_chars = int(config["min_chapter_chars"])
    checks["word_count"] = _check_word_count(text, min_chars)
    if checks["word_count"]["status"] == "fail":
        blocking.append("word_count")
    elif checks["word_count"]["status"] == "warning":
        warnings.append("word_count")

    # 标点检查
    checks["punctuation"] = _check_punctuation(text)
    if checks["punctuation"]["status"] == "warning":
        warnings.append("punctuation")

    overall = "fail" if blocking else ("warning" if warnings else "pass")

    result = {
        "file": file_path,
        "checks": checks,
        "overall": overall,
        "blocking": blocking,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    return 1 if blocking else 0


# =========================================================
# detect-gaps：检测设定缺口
# =========================================================

def _extract_character_names_from_prose(book_root):
    """从正文文件中提取出现的角色名（简单匹配：连续2-4个汉字且频繁出现）。"""
    prose_dir = os.path.join(book_root, "正文")
    if not os.path.isdir(prose_dir):
        return set()

    from collections import Counter
    name_counter = Counter()
    # 匹配连续2-4个汉字作为候选名字
    name_re = re.compile(r"[\u4e00-\u9fff]{2,4}")

    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        text = _read_file(path)
        for m in name_re.findall(text):
            name_counter[m] += 1

    # 过滤高频但明显不是名字的词
    common_words = {
        "这个", "那个", "什么", "怎么", "为什么", "可以", "已经", "因为", "所以",
        "如果", "虽然", "但是", "不过", "而且", "或者", "不是", "没有", "他们",
        "自己", "这么", "那样", "这样", "那样", "一个", "两个", "三个",
    }
    # 取出现 >=5 次的候选
    candidates = {name for name, cnt in name_counter.items()
                  if cnt >= 5 and name not in common_words}

    return candidates


def _list_character_cards(book_root):
    """列出设定/角色/ 目录下的角色卡文件。"""
    char_dir = os.path.join(book_root, "设定", "角色")
    if not os.path.isdir(char_dir):
        return []
    return [os.path.join(char_dir, f) for f in os.listdir(char_dir)
            if f.endswith(".md")]


def _character_name_from_card(card_path):
    """从角色卡文件名或首行提取角色名。"""
    basename = os.path.basename(card_path)
    # 尝试从文件名提取
    name = os.path.splitext(basename)[0]
    # 尝试从文件首行提取
    text = _read_file(card_path)
    first_lines = [ln for ln in text.splitlines() if ln.strip()][:3]
    for line in first_lines:
        m = re.match(r"^#\s*(.+)", line)
        if m:
            name = m.group(1).strip()
            break
    return name


def _check_world_settings(book_root):
    """检查世界观关键设定是否缺失。"""
    setting_dir = os.path.join(book_root, "设定")
    missing = []
    expected = [
        ("世界观.md", "世界观设定"),
        ("力量体系.md", "力量体系"),
        ("地理设定.md", "地理设定"),
    ]
    for filename, label in expected:
        if not os.path.isfile(os.path.join(setting_dir, filename)):
            missing.append(label)

    # 检查设定目录是否存在关键文件
    if os.path.isdir(setting_dir):
        files = os.listdir(setting_dir)
        if not files:
            missing.append("设定/ 目录为空")
    else:
        missing.append("设定/ 目录不存在")

    return missing


def _check_foreshadow_continuity(book_root, last_chapter_no):
    """检查伏笔是否有断线（已埋设但长时间未提及）。"""
    ledger = os.path.join(book_root, "追踪", "伏笔台账.md")
    if not os.path.isfile(ledger):
        return []

    text = _read_file(ledger)
    stale = []  # (ID, 埋设章节, 建议回收章节)
    section = None

    for line in text.splitlines():
        h = re.match(r"^#{1,4}\s*(.+)", line)
        if h:
            t = h.group(1)
            if "活跃" in t or "进行中" in t or "跟踪" in t:
                section = "active"
            else:
                section = None
            continue

        if section == "active" and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not cells or cells[0] in ("ID", "") or set(cells[0]) <= set("-: "):
                continue

            foreshadow_id = cells[0]
            # 尝试从列中提取埋设章节号
            planted_ch = None
            plan_ch = None
            for cell in cells:
                m = re.search(r"第\s*(\d+)\s*章", cell)
                if m:
                    num = int(m.group(1))
                    if planted_ch is None:
                        planted_ch = num
                    elif plan_ch is None:
                        plan_ch = num

            if planted_ch and last_chapter_no:
                gap = last_chapter_no - planted_ch
                if gap > 15:  # 超过15章未提及
                    stale.append({
                        "id": foreshadow_id,
                        "planted_chapter": planted_ch,
                        "gap": gap,
                        "suggestion": f"已{gap}章未提及，建议在第{last_chapter_no + 1}章回收或延续"
                    })

    return stale


def _check_outline_coverage(book_root, last_chapter_no):
    """检查大纲是否覆盖到当前章节。"""
    if last_chapter_no is None:
        return []

    missing = []
    for ch in range(1, last_chapter_no + 1):
        outlines = _find_outline_files(book_root, ch)
        if not outlines:
            # 也检查是否存在对应正文（只有已写但无纲才报缺失）
            prose_files = _find_chapter_files(book_root, ch)
            if prose_files:
                missing.append(ch)

    return missing


def _check_style_anchor(book_root):
    """检查文风锚是否存在。"""
    candidates = [
        os.path.join(book_root, "设定", "文风锚.md"),
        os.path.join(book_root, "设定", "文风锚点.md"),
        os.path.join(book_root, "设定", "文风样本.md"),
        os.path.join(book_root, "设定", "style_anchor.md"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return {"exists": True, "path": os.path.relpath(path, book_root)}

    return {"exists": False, "path": None}


def cmd_detect_gaps(book_root):
    """检测设定缺口。"""
    book_root = os.path.abspath(book_root)
    if not os.path.isdir(book_root):
        print(json.dumps({"error": f"目录不存在: {book_root}"}, ensure_ascii=False, indent=2))
        return 1

    gaps = {}
    last_no, _ = find_last_chapter(book_root)

    # 1. 角色卡检查
    prose_names = _extract_character_names_from_prose(book_root)
    cards = _list_character_cards(book_root)
    card_names = set()
    for card in cards:
        card_names.add(_character_name_from_card(card))

    # 过滤出可能的角色（卡片名中包含候选名的部分匹配）
    missing_chars = []
    for name in prose_names:
        found = False
        for card_name in card_names:
            if name in card_name or card_name in name:
                found = True
                break
        if not found:
            missing_chars.append(name)

    gaps["character_cards"] = {
        "prose_characters_found": len(prose_names),
        "cards_count": len(cards),
        "characters_without_cards": sorted(missing_chars),
        "status": "warning" if missing_chars else "pass",
    }

    # 2. 世界观设定检查
    missing_world = _check_world_settings(book_root)
    gaps["world_settings"] = {
        "missing": missing_world,
        "status": "warning" if missing_world else "pass",
    }

    # 3. 伏笔断线检查
    stale = _check_foreshadow_continuity(book_root, last_no)
    gaps["foreshadow_stale"] = {
        "stale_count": len(stale),
        "items": stale,
        "status": "warning" if stale else "pass",
    }

    # 4. 大纲覆盖检查
    missing_outlines = _check_outline_coverage(book_root, last_no)
    gaps["outline_coverage"] = {
        "missing_chapters": missing_outlines,
        "status": "warning" if missing_outlines else "pass",
    }

    # 5. 文风锚检查
    style_anchor = _check_style_anchor(book_root)
    gaps["style_anchor"] = {
        **style_anchor,
        "status": "warning" if not style_anchor["exists"] else "pass",
    }

    # 汇总
    all_warnings = [k for k, v in gaps.items() if v.get("status") == "warning"]
    result = {
        "book": os.path.basename(book_root),
        "last_chapter": last_no,
        "gaps": gaps,
        "summary": {
            "total_categories": 5,
            "warnings": len(all_warnings),
            "warning_categories": all_warnings,
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if all_warnings else 0


# =========================================================
# pre-compact：上下文压缩前保存进度快照
# =========================================================

def cmd_pre_compact(book_root):
    """在上下文压缩前保存进度快照。"""
    book_root = os.path.abspath(book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "unix_ts": time.time(),
        "book_root": book_root,
    }

    # 当前章节号
    last_no, last_path = find_last_chapter(book_root)
    snapshot["last_chapter"] = last_no
    snapshot["last_chapter_file"] = os.path.relpath(last_path, book_root) if last_path else None

    # 正在写的章节（如有未完成标记的章节）
    writing_chapter = None
    if last_no is not None:
        # 检查最后一章是否可能有未完成标记
        if last_path:
            text = _read_file(last_path)
            # 简单启发：如果最后200字有"未完"或截断特征
            tail = text[-200:] if len(text) > 200 else text
            tail_lines = [ln for ln in tail.splitlines() if ln.strip()]
            if tail_lines:
                last_line = tail_lines[-1].strip()
                if last_line and last_line[-1] not in ENDING_PUNCT and len(tail) < 500:
                    writing_chapter = last_no
    snapshot["writing_chapter"] = writing_chapter

    # 已加载的上下文文件列表（列举关键追踪文件的存在和大小）
    context_files = []
    tracking_dir = os.path.join(book_root, "追踪")

    # 追踪文件
    for fname in ("章节摘要.md", "节奏配额.md", "伏笔台账.md"):
        fpath = os.path.join(tracking_dir, fname)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            context_files.append({
                "path": f"追踪/{fname}",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })

    # 最新门禁
    if last_no is not None:
        gate_path = os.path.join(tracking_dir, "门禁", f"gate_ch{last_no}.json")
        if os.path.isfile(gate_path):
            stat = os.stat(gate_path)
            context_files.append({
                "path": f"追踪/门禁/gate_ch{last_no}.json",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })

    # 大纲锚点
    anchor_path = os.path.join(book_root, "大纲", "outline_anchors.json")
    if os.path.isfile(anchor_path):
        stat = os.stat(anchor_path)
        context_files.append({
            "path": "大纲/outline_anchors.json",
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        })

    # 文风锚
    for fname in ("文风锚.md", "文风锚点.md", "文风样本.md"):
        style_path = os.path.join(book_root, "设定", fname)
        if os.path.isfile(style_path):
            stat = os.stat(style_path)
            context_files.append({
                "path": f"设定/{fname}",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
            break

    # 最新章节章纲
    next_no = (last_no + 1) if last_no is not None else 1
    outlines = _find_outline_files(book_root, next_no)
    for ol in outlines:
        stat = os.stat(ol)
        context_files.append({
            "path": f"大纲/{os.path.basename(ol)}",
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        })

    # 最近3章正文（轻量记录）
    if last_no is not None:
        prose_dir = os.path.join(book_root, "正文")
        recent_prose = []
        for path in glob.glob(os.path.join(prose_dir, "*.md")):
            m = CHAPTER_FILE_RE.search(os.path.basename(path))
            if m:
                recent_prose.append((int(m.group(1)), path))
        recent_prose.sort(key=lambda x: x[0])
        for ch_no, ch_path in recent_prose[-3:]:
            stat = os.stat(ch_path)
            context_files.append({
                "path": f"正文/{os.path.basename(ch_path)}",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })

    snapshot["context_files"] = context_files
    snapshot["context_file_count"] = len(context_files)

    # 写入文件
    output_path = os.path.join(tracking_dir, "compact_snapshot.json")
    _write_json(output_path, snapshot)

    print(f"[PRE-COMPACT] 进度快照已保存：{output_path}")
    print(f"  时间：{snapshot['timestamp']}")
    print(f"  最新章节：第{last_no}章" if last_no else "  最新章节：无")
    if writing_chapter is not None:
        print(f"  正在写：第{writing_chapter}章（疑似未完成）")
    print(f"  已记录上下文文件：{len(context_files)} 个")

    return 0


# =========================================================
# 命令行入口
# =========================================================

def main():
    _ensure_utf8()

    ap = argparse.ArgumentParser(
        description="自动化 Hook 机制：session-start / guard-outline / check-prose / detect-gaps / pre-compact"
    )
    sub = ap.add_subparsers(dest="command", help="子命令")

    # session-start
    p_start = sub.add_parser("session-start", help="会话开始时显示进度快照")
    p_start.add_argument("book_dir", help="书籍工程目录")

    # guard-outline
    p_guard = sub.add_parser("guard-outline", help="写正文前检查大纲是否存在")
    p_guard.add_argument("book_dir", help="书籍工程目录")
    p_guard.add_argument("--chapter", type=int, required=True, help="章节号")

    # check-prose
    p_check = sub.add_parser("check-prose", help="正文写入后轻量扫描")
    p_check.add_argument("file", help="正文文件路径")
    p_check.add_argument("--book-dir", default=None, help="书籍工程目录（可选，用于读取配置）")

    # detect-gaps
    p_gaps = sub.add_parser("detect-gaps", help="检测设定缺口")
    p_gaps.add_argument("book_dir", help="书籍工程目录")

    # pre-compact
    p_compact = sub.add_parser("pre-compact", help="上下文压缩前保存进度快照")
    p_compact.add_argument("book_dir", help="书籍工程目录")

    args = ap.parse_args()

    if not args.command:
        ap.print_help()
        return 2

    if args.command == "session-start":
        return cmd_session_start(args.book_dir)

    elif args.command == "guard-outline":
        return cmd_guard_outline(args.book_dir, args.chapter)

    elif args.command == "check-prose":
        return cmd_check_prose(args.file, args.book_dir)

    elif args.command == "detect-gaps":
        return cmd_detect_gaps(args.book_dir)

    elif args.command == "pre-compact":
        return cmd_pre_compact(args.book_dir)

    return 2


if __name__ == "__main__":
    sys.exit(main())
