#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chapter_synthesizer.py — 章节合成器 v1.0（纯标准库，无第三方依赖）。

将 Beat Sheet 流水线产出的多个 Beat 片段合成为完整章节，并做合成稿质量校验。
对应 beat-pipeline.md 的 Step 4（串联合成），以及合成后质量预检。

三个子命令：
  synthesize — 读取 Beat 片段文件，按顺序拼接并检测衔接，输出合成稿与元数据 JSON
  check      — 对合成稿做字数/覆盖度/衔接/钩子/格式五维校验，输出校验报告 JSON
  polish     — 识别 Beat 边界，生成过渡润色提示（Markdown）

Beat Sheet 数据来源：
  - Beat Sheet JSON：追踪/beat_sheets/beat_ch{N}.json
  - Beat 片段文件：追踪/beat_sheets/beats/ch{N}_beat{M}.md
  - 合成稿输出：正文/第XXX章_{标题}_合成稿.md

Beat Sheet JSON 结构（beat_sheet_generator.py 产出）：
  {
    "chapter": 37,
    "title": "...",
    "word_budget": {"min": 3000, "max": 4000},
    "gear": "中",
    "beats": [
      {
        "id": 1,
        "name": "...",
        "scene": "地点/时间",
        "characters": ["..."],
        "action": "...",
        "emotion": "...",
        "word_budget": 600,
        "hook": "..."
      }
    ]
  }

用法：
  python scripts/chapter_synthesizer.py synthesize "{书名目录}" --chapter 37
  python scripts/chapter_synthesizer.py check "{书名目录}" --chapter 37 --manuscript "正文/第037章_标题.md"
  python scripts/chapter_synthesizer.py polish "{书名目录}" --chapter 37

退出码：0 = 正常；1 = 有 FAIL 项；2 = 参数/文件错误。
"""

import argparse
import datetime
import json
import os
import re
import sys

# =========================================================
# 常量
# =========================================================

VERSION = "1.0.0"

# 路径常量（相对于书籍工程根目录）
BEAT_SHEET_DIR = "追踪/beat_sheets"
BEAT_SHEET_FILE = "beat_ch{N}.json"
BEAT_FRAG_DIR = "追踪/beat_sheets/beats"
BEAT_FRAG_PATTERN = "ch{N}_beat{M}.md"

# 合成稿输出目录
PROSE_DIR = "正文"

# 合成元数据输出目录
META_DIR = "追踪/beat_sheets"

# 字数偏差容忍阈值（百分比）
WORD_COUNT_TOLERANCE = 0.15

# =========================================================
# 工具函数
# =========================================================


def _read(path):
    """读取文件内容，返回字符串。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _read_json(path):
    """读取 JSON 文件，返回 dict。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _write(path, content, encoding="utf-8"):
    """写入字符串到文件。"""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def _write_json(path, data):
    """写入 JSON 到文件。"""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _count_chars(text):
    """统计汉字数（不含空白与标点，纯汉字字符数）。"""
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")

def _count_total_chars(text):
    """统计非空白字符数。"""
    return sum(1 for c in text if not c.isspace())


def _strip_bom(text):
    """去除 BOM 标记。"""
    return text.lstrip("\ufeff")


def _ensure_dir(path):
    """确保目录存在。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# =========================================================
# Beat Sheet 读取
# =========================================================


def load_beat_sheet(book_root, chapter_no):
    """加载 Beat Sheet JSON，返回 dict。找不到返回 None。"""
    path = os.path.join(book_root, BEAT_SHEET_DIR, BEAT_SHEET_FILE.format(N=chapter_no))
    if not os.path.isfile(path):
        return None
    try:
        return _read_json(path)
    except (OSError, ValueError):
        return None


def load_beat_fragment(book_root, chapter_no, beat_no):
    """加载单个 Beat 片段 Markdown，返回字符串。找不到返回 None。"""
    path = os.path.join(book_root, BEAT_FRAG_DIR,
                        BEAT_FRAG_PATTERN.format(N=chapter_no, M=beat_no))
    if not os.path.isfile(path):
        return None
    try:
        return _strip_bom(_read(path))
    except OSError:
        return None


def load_all_fragments(book_root, chapter_no, beat_sheet):
    """按 Beat 顺序加载所有片段，返回 [(beat_id, beat_meta, fragment_text), ...]。
    缺失片段用 None 表示文本。
    """
    results = []
    beats = beat_sheet.get("beats", [])
    for beat in beats:
        bid = beat.get("id", len(results) + 1)
        text = load_beat_fragment(book_root, chapter_no, bid)
        results.append((bid, beat, text))
    return results


# =========================================================
# synthesize — 合成章节
# =========================================================


def _ends_with_dialogue(text):
    """判断文本末尾是否是对话（引号内内容）。"""
    if not text:
        return False
    # 取最后非空行
    lines = [l.rstrip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False
    last = lines[-1]
    # 检查是否以引号结尾
    return bool(re.search(r'[「"").,!?」\"]\s*$', last))


def _starts_with_dialogue(text):
    """判断文本开头是否是对话。"""
    if not text:
        return False
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False
    first = lines[0]
    # 检查是否以引号开头
    return bool(re.match(r'^[「""]', first))


def _extract_scene(text):
    """从 Beat 片段中提取场景关键词（地点/时间）。返回 set。"""
    if not text:
        return set()
    keywords = set()
    # 常见时间词
    time_words = ["夜", "晚", "晨", "早", "昼", "午", "暮", "黄昏", "黎明",
                  "清晨", "夜晚", "白天", "晌午", "傍晚", "深夜", "午后", "拂晓"]
    # 常见地点词（从文本中提取粗略标记）
    location_words = []
    for word in time_words:
        if word in text:
            keywords.add(("time", word))
    return keywords


def _extract_emotion(text):
    """从 Beat 片段中粗略提取情绪关键词。返回 set。"""
    if not text:
        return set()
    emotion_words = ["愤怒", "悲伤", "喜悦", "恐惧", "紧张", "平静", "惊讶",
                     "绝望", "感动", "焦虑", "兴奋", "温馨", "压抑", "震惊"]
    found = set()
    for word in emotion_words:
        if word in text:
            found.add(word)
    return found


def _detect_transition_need(prev_beat_meta, next_beat_meta, prev_text, next_text):
    """检测两个 Beat 之间是否需要过渡句。返回 (need:bool, reason:str)。"""
    reasons = []

    # 1. 对话→对话：可能需要场景说明
    if _ends_with_dialogue(prev_text) and _starts_with_dialogue(next_text):
        reasons.append("前后Beat均为对话结尾/开头，可能需要场景说明过渡")

    # 2. 场景/地点转换：从 Beat 元数据检测
    prev_scene = prev_beat_meta.get("scene", "") if prev_beat_meta else ""
    next_scene = next_beat_meta.get("scene", "") if next_beat_meta else ""
    if prev_scene and next_scene:
        # 提取场景中的地点关键词做粗略比对
        prev_loc = set(prev_scene.split("/")[0].split()) if "/" in prev_scene else set(prev_scene)
        next_loc = set(next_scene.split("/")[0].split()) if "/" in next_scene else set(next_scene)
        # 如果地点部分完全不同
        if prev_loc and next_loc and not (prev_loc & next_loc):
            reasons.append(f"场景转换：{prev_scene} → {next_scene}")

    # 3. 时间转换
    prev_time = ""
    next_time = ""
    if prev_scene and "/" in prev_scene:
        prev_time = prev_scene.split("/")[1].strip() if len(prev_scene.split("/")) > 1 else ""
    if next_scene and "/" in next_scene:
        next_time = next_scene.split("/")[1].strip() if len(next_scene.split("/")) > 1 else ""

    time_shift_markers = [
        ("夜", "晨"), ("夜", "早"), ("夜", "清晨"), ("夜", "黎明"), ("夜", "白天"),
        ("晚", "晨"), ("晚", "早"), ("晚", "清晨"),
        ("白天", "夜"), ("白天", "晚"), ("白天", "夜晚"),
        ("晨", "夜"), ("晨", "晚"), ("晨", "傍晚"),
    ]
    if prev_time and next_time:
        for a, b in time_shift_markers:
            if a in prev_time and b in next_time:
                reasons.append(f"时间转换：{prev_time} → {next_time}")
                break

    # 4. 情绪突变
    prev_emotion = prev_beat_meta.get("emotion", "") if prev_beat_meta else ""
    next_emotion = next_beat_meta.get("emotion", "") if next_beat_meta else ""
    # 简单的情绪突变检测
    emotion_opposites = [
        ("悲伤", "喜悦"), ("悲伤", "兴奋"), ("悲伤", "温馨"),
        ("愤怒", "平静"), ("愤怒", "温馨"), ("愤怒", "喜悦"),
        ("恐惧", "平静"), ("恐惧", "温馨"), ("恐惧", "喜悦"),
        ("紧张", "平静"), ("紧张", "温馨"),
        ("绝望", "喜悦"), ("绝望", "希望"),
        ("平静", "震惊"), ("平静", "愤怒"), ("平静", "恐惧"),
    ]
    if prev_emotion and next_emotion:
        for a, b in emotion_opposites:
            if a in prev_emotion and b in next_emotion:
                reasons.append(f"情绪突变：{prev_emotion} → {next_emotion}")
                break

    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def _clean_fragment(text):
    """清理片段文本：去除首尾空白、多余空行、Beat标记行。"""
    if not text:
        return ""
    lines = text.strip().splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # 跳过 Beat 标记头（## Beat N / <!-- beat:N --> 等）
        if re.match(r"^##\s*Beat\s+\d+", stripped, re.I):
            continue
        if re.match(r"^<!--\s*beat\s*:\s*\d+\s*-->", stripped, re.I):
            continue
        cleaned.append(stripped)
    # 合并连续空行为单个空行
    result = []
    prev_empty = False
    for line in cleaned:
        if not line:
            if not prev_empty:
                result.append("")
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False
    # 去首尾空行
    while result and not result[0]:
        result.pop(0)
    while result and not result[-1]:
        result.pop()
    return "\n".join(result)


def cmd_synthesize(book_root, args):
    """synthesize 子命令：合成章节。"""
    chapter_no = args.chapter

    # 1. 加载 Beat Sheet
    beat_sheet = load_beat_sheet(book_root, chapter_no)
    if not beat_sheet:
        print(f"错误：找不到 Beat Sheet 文件 "
              f"{BEAT_SHEET_DIR}/{BEAT_SHEET_FILE.format(N=chapter_no)}",
              file=sys.stderr)
        return 2

    title = beat_sheet.get("title", "")
    beats = beat_sheet.get("beats", [])
    if not beats:
        print(f"错误：Beat Sheet 中没有 Beat 定义", file=sys.stderr)
        return 2

    print(f"章节合成：第{chapter_no}章「{title}」")
    print(f"  Beat 数量：{len(beats)}")

    # 2. 加载所有片段
    fragments = load_all_fragments(book_root, chapter_no, beat_sheet)
    missing = [bid for bid, _, text in fragments if text is None]
    if missing:
        print(f"错误：以下 Beat 片段文件缺失：{missing}", file=sys.stderr)
        return 2

    # 3. 清理片段
    cleaned = []
    for bid, beat_meta, text in fragments:
        cleaned_text = _clean_fragment(text)
        cleaned.append((bid, beat_meta, cleaned_text, text))

    # 4. 拼接 + 检测过渡
    parts = []
    transition_notes = []
    total_chars = 0

    for i, (bid, beat_meta, clean_text, raw_text) in enumerate(cleaned):
        if i == 0:
            # 第一个 Beat 直接加入
            parts.append(clean_text)
        else:
            prev_bid, prev_meta, _, prev_raw = cleaned[i - 1]
            need, reason = _detect_transition_need(
                prev_meta, beat_meta, prev_raw, raw_text
            )
            if need:
                # 插入过渡占位标记（实际润色由 polish 子命令生成提示）
                transition_line = f"\n<!-- [合成提示] Beat {prev_bid}→{bid} 边界可能需要过渡：{reason} -->\n"
                parts.append(transition_line)
                transition_notes.append({
                    "boundary": f"{prev_bid}->{bid}",
                    "need": True,
                    "reason": reason,
                })
            parts.append(clean_text)

        char_count = _count_chars(clean_text)
        total_chars += char_count

    # 5. 组合正文
    synthesized = "\n\n".join(parts).strip()

    # 6. 输出合成稿
    prose_file = os.path.join(book_root, PROSE_DIR,
                               f"第{chapter_no:03d}章_{title}_合成稿.md")
    _ensure_dir(prose_file)
    _write(prose_file, synthesized + "\n")

    # 7. 构建元数据
    budget = beat_sheet.get("word_budget", {})
    target_min = budget.get("min", 0)
    target_max = budget.get("max", 0)

    beat_stats = []
    for bid, beat_meta, clean_text, _ in cleaned:
        beat_stats.append({
            "beat_id": bid,
            "name": beat_meta.get("name", ""),
            "char_count": _count_chars(clean_text),
            "budget": beat_meta.get("word_budget", 0),
        })

    meta = {
        "version": VERSION,
        "chapter": chapter_no,
        "title": title,
        "synthesized_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "beat_sheet_file": f"{BEAT_SHEET_DIR}/{BEAT_SHEET_FILE.format(N=chapter_no)}",
        "output_file": prose_file,
        "word_count": {
            "total_chars": total_chars,
            "total_nonblank": _count_total_chars(synthesized),
            "target_min": target_min,
            "target_max": target_max,
            "within_budget": (target_min <= total_chars <= target_max) if (target_min and target_max) else True,
        },
        "beats": beat_stats,
        "transitions": transition_notes,
        "fragment_files": [
            f"{BEAT_FRAG_DIR}/{BEAT_FRAG_PATTERN.format(N=chapter_no, M=bid)}"
            for bid, _, _ in fragments
        ],
    }

    # 8. 输出元数据 JSON
    meta_file = os.path.join(book_root, META_DIR, f"synthesis_meta_ch{chapter_no}.json")
    _write_json(meta_file, meta)

    # 9. 打印摘要
    print(f"  合成稿字数（汉字）：{total_chars}")
    if target_min and target_max:
        status = "在预算内" if target_min <= total_chars <= target_max else "超出预算"
        print(f"  字数预算：{target_min}-{target_max}（{status}）")
    print(f"  过渡检测：{len(transition_notes)} 处需要关注")
    for note in transition_notes:
        print(f"    Beat {note['boundary']}：{note['reason']}")
    print()
    print(f"合成稿已输出：{prose_file}")
    print(f"合成元数据已输出：{meta_file}")
    return 0


# =========================================================
# check — 合成稿质量校验
# =========================================================


def _find_manuscript(book_root, chapter_no, manuscript_arg):
    """定位合成稿文件路径。"""
    if manuscript_arg:
        path = manuscript_arg if os.path.isabs(manuscript_arg) else os.path.join(book_root, manuscript_arg)
        if os.path.isfile(path):
            return path
        return None

    # 自动查找：优先 _合成稿.md，其次任意匹配
    prose_dir = os.path.join(book_root, PROSE_DIR)
    if not os.path.isdir(prose_dir):
        return None

    # 优先查找合成稿
    synthesis_pattern = f"第{chapter_no:03d}章_*_合成稿.md"
    for name in os.listdir(prose_dir):
        if name.endswith("_合成稿.md"):
            m = re.search(r"第\s*(\d+)\s*章", name)
            if m and int(m.group(1)) == chapter_no:
                return os.path.join(prose_dir, name)

    # 其次查找任意匹配
    for name in os.listdir(prose_dir):
        m = re.search(r"第\s*(\d+)\s*章", name)
        if m and int(m.group(1)) == chapter_no:
            return os.path.join(prose_dir, name)

    return None


def _check_word_count(text, beat_sheet):
    """字数检查。返回 dict。"""
    total = _count_chars(text)
    budget = beat_sheet.get("word_budget", {})
    target_min = budget.get("min", 0)
    target_max = budget.get("max", 0)
    target = (target_min + target_max) // 2 if (target_min and target_max) else 0

    if target > 0:
        deviation = abs(total - target) / target * 100
        status = "pass"
        if total < target_min:
            status = "fail"
        elif total > target_max:
            status = "fail"
        elif deviation > WORD_COUNT_TOLERANCE * 100:
            status = "warning"
    else:
        deviation = 0
        status = "skip"

    return {
        "total": total,
        "total_nonblank": _count_total_chars(text),
        "target": target,
        "target_min": target_min,
        "target_max": target_max,
        "status": status,
        "deviation": f"{deviation:.1f}%" if target > 0 else "N/A",
    }


def _check_beat_coverage(text, beat_sheet):
    """Beat 覆盖度检查。每个 Beat 的核心动作关键词是否在合成稿中出现。"""
    beats = beat_sheet.get("beats", [])
    covered = 0
    uncovered = []
    beat_details = []

    for beat in beats:
        bid = beat.get("id", 0)
        action = beat.get("action", "")
        name = beat.get("name", "")

        if not action:
            beat_details.append({"beat_id": bid, "name": name, "covered": True, "action": action})
            covered += 1
            continue

        # 从核心动作中提取关键词（去掉停用词）
        stopwords = {"的", "了", "在", "是", "被", "把", "到", "和", "与", "对",
                     "从", "向", "给", "让", "用", "以", "为", "上", "下", "中"}
        keywords = [c for c in action if c not in stopwords and len(c) > 1]

        # 检查关键词是否在合成稿中出现
        found = sum(1 for kw in keywords if kw in text)
        is_covered = found > 0 or len(keywords) == 0

        if is_covered:
            covered += 1
        else:
            uncovered.append(bid)

        beat_details.append({
            "beat_id": bid,
            "name": name,
            "covered": is_covered,
            "action": action,
            "keywords_found": found,
            "keywords_total": len(keywords),
        })

    total = len(beats)
    status = "pass" if covered == total else ("fail" if covered < total - 1 else "warning")

    return {
        "total_beats": total,
        "covered": covered,
        "uncovered": uncovered,
        "status": status,
        "details": beat_details,
    }


def _check_transitions(text, beat_sheet):
    """衔接检查：检测 Beat 边界处是否有突兀切换。"""
    beats = beat_sheet.get("beats", [])
    if len(beats) < 2:
        return {"boundaries": 0, "smooth": 0, "abrupt": 0, "status": "pass",
                "abrupt_positions": [], "details": []}

    # 在合成稿中定位各 Beat 的位置（通过 Beat 名称/关键词）
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    beat_positions = []  # [(start_para_idx, end_para_idx)]

    for beat in beats:
        name = beat.get("name", "")
        action = beat.get("action", "")
        # 提取关键词
        kw = ""
        if name:
            # 取名称中去除数字后的部分
            kw = re.sub(r"\d+", "", name).strip()
        if not kw and action:
            kw = action[:10]

        if not kw:
            continue

        for idx, para in enumerate(paragraphs):
            if kw in para:
                beat_positions.append(idx)
                break

    # 检测边界
    boundaries = len(beats) - 1
    smooth = 0
    abrupt = 0
    abrupt_positions = []
    details = []

    for i in range(boundaries):
        prev_end = beat_positions[i] if i < len(beat_positions) else 0
        next_start = beat_positions[i + 1] if i + 1 < len(beat_positions) else prev_end + 1

        # 检查边界处段落特征
        is_smooth = True
        reasons = []

        if prev_end < len(paragraphs) and next_start < len(paragraphs):
            prev_para = paragraphs[prev_end] if prev_end < len(paragraphs) else ""
            next_para = paragraphs[next_start] if next_start < len(paragraphs) else ""

            # 对话→对话无过渡
            if _ends_with_dialogue(prev_para) and _starts_with_dialogue(next_para):
                # 检查中间是否有过渡段
                gap = next_start - prev_end
                if gap <= 1:
                    is_smooth = False
                    reasons.append("对话连续无场景说明")

            # 同一段落中检测场景切换标记
            if prev_para and next_para:
                # 检查合成提示标记（synthesize 时插入的）
                if "<!-- [合成提示]" in text:
                    # 找到对应的提示
                    hint_re = re.search(
                        rf"\[合成提示\]\s*Beat\s*\d+→{beats[i+1].get('id', i+2)}\s*边界.*?-->", text)
                    if hint_re:
                        is_smooth = False
                        reasons.append("合成时检测到需要过渡但未处理")

        if is_smooth:
            smooth += 1
        else:
            abrupt += 1
            abrupt_positions.append(i + 1)  # Beat 编号（从1开始）

        details.append({
            "boundary": f"{beats[i].get('id', i+1)}->{beats[i+1].get('id', i+2)}",
            "smooth": is_smooth,
            "reasons": reasons,
        })

    status = "pass"
    if abrupt > 0:
        status = "fail" if abrupt > boundaries // 2 else "warning"

    return {
        "boundaries": boundaries,
        "smooth": smooth,
        "abrupt": abrupt,
        "status": status,
        "abrupt_positions": abrupt_positions,
        "details": details,
    }


def _check_hooks(text, beat_sheet):
    """钩子检查：章首钩子和章末钩子是否存在。"""
    beats = beat_sheet.get("beats", [])
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # 章首钩子：检查第一段是否具有吸引力（非纯描写开头）
    opening_hook = False
    if paragraphs:
        first = paragraphs[0]
        # 钩子特征：对话开头、动作开头、悬念句（含问号/感叹号）
        hook_patterns = [
            r'[「""]',           # 对话开头
            r'[!?]',             # 疑问/感叹
            r'^(突然|忽然|就在)',  # 突发动作
            r'^(谁|什么|怎么|为什么)',  # 疑问词开头
        ]
        for pat in hook_patterns:
            if re.search(pat, first):
                opening_hook = True
                break

    # 章末钩子：检查最后一段是否有悬念/钩子
    ending_hook = False
    if paragraphs:
        last = paragraphs[-1]
        hook_patterns_end = [
            r'[?？]$',            # 以问号结尾
            r'[!！]$',            # 以感叹号结尾
            r'然而|可是|但是',     # 转折词
            r'不会想到|不知道|没想到',  # 悬念
            r'就在这时|此时',      # 悬念
            r'至于|然而|不过',     # 未完待续感
        ]
        for pat in hook_patterns_end:
            if re.search(pat, last):
                ending_hook = True
                break

    # 也检查 Beat Sheet 最后一个 Beat 的钩子声明
    last_beat_hook = ""
    if beats:
        last_beat_hook = beats[-1].get("hook", "")

    if last_beat_hook and ending_hook:
        ending_hook = True  # Beat Sheet 声明的钩子在合成稿中存在

    status = "pass" if (opening_hook and ending_hook) else (
        "fail" if not (opening_hook or ending_hook) else "warning"
    )

    return {
        "opening_hook": opening_hook,
        "ending_hook": ending_hook,
        "last_beat_hook": last_beat_hook,
        "status": status,
    }


def _check_format(text):
    """格式检查：元信息是否混入正文、标点是否规范。"""
    issues = []
    punct_issues = 0
    meta_in_text = False

    # 1. 元信息混入正文检测
    meta_patterns = [
        r"Beat\s+\d+",                    # Beat 标记
        r"字数预算[：:]\s*\d+",             # 字数预算
        r"目标情绪[：:]",                   # 情绪标签
        r"核心动作[：:]",                   # 动作标签
        r"出场人物[：:]",                   # 人物标签
        r"末尾钩子[：:]",                   # 钩子标签
        r"本章目标[：:]",                   # 章目标标签
        r"\[合成提示\]",                    # 合成提示残留
        r"<!--.*beat.*-->",                 # HTML注释残留
    ]
    for pat in meta_patterns:
        matches = re.findall(pat, text, re.I)
        if matches:
            meta_in_text = True
            for m in matches[:3]:
                issues.append(f"元信息残留：{m}")

    # 2. 标点规范检查
    punct_rules = [
        # 连续句号
        (r"\.{3,}", "连续英文句号（...）应使用中文省略号（……）"),
        # 英文标点混入
        (r"(?<=[\u4e00-\u9fff]),(?=[\u4e00-\u9fff])", "中文语境使用英文逗号"),
        (r"(?<=[\u4e00-\u9fff])\.(?=[\u4e00-\u9fff])", "中文语境使用英文句号"),
        # 括号不匹配
        (r"[（(][^）)]*$", "左括号无对应右括号（行末）"),
        # 引号不匹配
        (r'[\u300c\u201c"][^\u300d\u201d"]*$', "左引号无对应右引号（行末）"),
    ]
    for pat, desc in punct_rules:
        matches = re.findall(pat, text)
        if matches:
            punct_issues += len(matches)
            if len(matches) <= 3:
                for m in matches:
                    issues.append(f"标点：{desc}（{m.strip()[:20]}）")

    # 去重问题列表
    issues = list(dict.fromkeys(issues))

    status = "pass"
    if meta_in_text:
        status = "fail"
    elif punct_issues > 5:
        status = "fail"
    elif punct_issues > 0:
        status = "warning"

    return {
        "meta_in_text": meta_in_text,
        "punct_issues": punct_issues,
        "issues": issues,
        "status": status,
    }


def cmd_check(book_root, args):
    """check 子命令：合成稿质量校验。"""
    chapter_no = args.chapter

    # 1. 加载 Beat Sheet
    beat_sheet = load_beat_sheet(book_root, chapter_no)
    if not beat_sheet:
        print(f"错误：找不到 Beat Sheet 文件", file=sys.stderr)
        return 2

    # 2. 定位合成稿
    manuscript_path = _find_manuscript(book_root, chapter_no, args.manuscript)
    if not manuscript_path:
        print(f"错误：找不到第{chapter_no}章的合成稿文件", file=sys.stderr)
        return 2

    print(f"合成稿校验：第{chapter_no}章")
    print(f"  合成稿：{manuscript_path}")

    # 3. 读取合成稿
    try:
        text = _strip_bom(_read(manuscript_path))
    except OSError as e:
        print(f"错误：无法读取合成稿 {manuscript_path}: {e}", file=sys.stderr)
        return 2

    # 4. 执行各项检查
    word_count = _check_word_count(text, beat_sheet)
    beat_coverage = _check_beat_coverage(text, beat_sheet)
    transitions = _check_transitions(text, beat_sheet)
    hooks = _check_hooks(text, beat_sheet)
    fmt = _check_format(text)

    # 5. 汇总
    warnings = []
    fails = []

    if word_count["status"] == "fail":
        fails.append(f"字数检查未通过：{word_count['total']}字"
                     f"（目标 {word_count['target_min']}-{word_count['target_max']}，"
                     f"偏差 {word_count['deviation']}）")
    elif word_count["status"] == "warning":
        warnings.append(f"字数偏差较大：{word_count['deviation']}")

    if beat_coverage["status"] == "fail":
        fails.append(f"Beat 覆盖度不足：{beat_coverage['covered']}/{beat_coverage['total_beats']} 个 Beat 被覆盖"
                     f"（缺失 Beat：{beat_coverage['uncovered']}）")
    elif beat_coverage["status"] == "warning":
        warnings.append(f"Beat 覆盖度偏低：{beat_coverage['covered']}/{beat_coverage['total_beats']}")

    if transitions["status"] == "fail":
        fails.append(f"衔接检查未通过：{transitions['abrupt']}/{transitions['boundaries']} 处突兀切换"
                     f"（位置：{transitions['abrupt_positions']}）")
    elif transitions["status"] == "warning":
        warnings.append(f"部分衔接略显突兀（Beat {transitions['abrupt_positions']}）")

    if hooks["status"] == "fail":
        missing = []
        if not hooks["opening_hook"]:
            missing.append("章首")
        if not hooks["ending_hook"]:
            missing.append("章末")
        fails.append(f"钩子缺失：{','.join(missing)}钩子不存在")
    elif hooks["status"] == "warning":
        missing = []
        if not hooks["opening_hook"]:
            missing.append("章首")
        if not hooks["ending_hook"]:
            missing.append("章末")
        warnings.append(f"钩子偏弱：{','.join(missing)}钩子不明显")

    if fmt["status"] == "fail":
        fails.append(f"格式检查未通过：元信息混入正文={fmt['meta_in_text']}，"
                     f"标点问题={fmt['punct_issues']}处")
    elif fmt["status"] == "warning":
        warnings.append(f"格式检查：{fmt['punct_issues']}处标点问题")

    for issue in fmt["issues"]:
        warnings.append(f"  {issue}")

    # 6. 构建报告
    report = {
        "version": VERSION,
        "chapter": chapter_no,
        "manuscript_file": os.path.relpath(manuscript_path, book_root),
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "checks": {
            "word_count": word_count,
            "beat_coverage": {
                "total_beats": beat_coverage["total_beats"],
                "covered": beat_coverage["covered"],
                "status": beat_coverage["status"],
            },
            "transition_quality": {
                "boundaries": transitions["boundaries"],
                "smooth": transitions["smooth"],
                "abrupt": transitions["abrupt"],
                "status": transitions["status"],
                "abrupt_positions": transitions["abrupt_positions"],
            },
            "hooks": {
                "opening_hook": hooks["opening_hook"],
                "ending_hook": hooks["ending_hook"],
                "status": hooks["status"],
            },
            "format": {
                "meta_in_text": fmt["meta_in_text"],
                "punct_issues": fmt["punct_issues"],
                "status": fmt["status"],
            },
        },
        "overall": "pass" if not fails else (
            "fail" if (
                word_count["status"] == "fail" or
                beat_coverage["status"] == "fail" or
                transitions["status"] == "fail" or
                hooks["status"] == "fail" or
                fmt["status"] == "fail"
            ) else "warning"
        ),
        "warnings": warnings,
        "fails": fails,
    }

    # 7. 输出报告
    report_file = os.path.join(book_root, META_DIR,
                               f"check_report_ch{chapter_no}.json")
    _write_json(report_file, report)

    # 8. 打印摘要
    print(f"\n  字数检查：{word_count['total']} 字"
          f"（目标 {word_count['target_min']}-{word_count['target_max']}，"
          f"偏差 {word_count['deviation']}）[{word_count['status']}]")
    print(f"  Beat 覆盖度：{beat_coverage['covered']}/{beat_coverage['total_beats']} [{beat_coverage['status']}]")
    print(f"  衔接检查：{transitions['smooth']}/{transitions['boundaries']} 平滑"
          f"（{transitions['abrupt']} 处突兀）[{transitions['status']}]")
    print(f"  钩子检查：章首={hooks['opening_hook']}，章末={hooks['ending_hook']} [{hooks['status']}]")
    print(f"  格式检查：元信息残留={fmt['meta_in_text']}，标点问题={fmt['punct_issues']} [{fmt['status']}]")

    for f in fails:
        print(f"\n  [FAIL] {f}")
    for w in warnings:
        print(f"  [WARN] {w}")

    if not fails and not warnings:
        print("\n  全部检查通过")

    print(f"\n校验报告已输出：{report_file}")
    return 1 if fails else 0


# =========================================================
# polish — 过渡润色提示
# =========================================================


def cmd_polish(book_root, args):
    """polish 子命令：生成过渡润色提示。"""
    chapter_no = args.chapter

    # 1. 加载 Beat Sheet
    beat_sheet = load_beat_sheet(book_root, chapter_no)
    if not beat_sheet:
        print(f"错误：找不到 Beat Sheet 文件", file=sys.stderr)
        return 2

    beats = beat_sheet.get("beats", [])
    if len(beats) < 2:
        print(f"提示：第{chapter_no}章仅有 {len(beats)} 个 Beat，无需过渡润色")
        return 0

    print(f"过渡润色提示：第{chapter_no}章「{beat_sheet.get('title', '')}」")
    print(f"  Beat 数量：{len(beats)}")

    # 2. 加载片段
    fragments = load_all_fragments(book_root, chapter_no, beat_sheet)
    missing = [bid for bid, _, text in fragments if text is None]
    if missing:
        print(f"警告：以下 Beat 片段缺失，将仅基于元数据生成提示：{missing}")

    # 3. 为每个边界生成润色提示
    lines = []
    lines.append(f"# 第{chapter_no}章 过渡润色提示")
    lines.append(f"> 基于 Beat Sheet 自动生成，供人工润色参考。")
    lines.append(f"> 章节：{beat_sheet.get('title', '')}")
    lines.append(f"> Beat 数量：{len(beats)}")
    lines.append("")

    polish_hints = []

    for i in range(len(beats) - 1):
        prev_beat = beats[i]
        next_beat = beats[i + 1]
        prev_bid = prev_beat.get("id", i + 1)
        next_bid = next_beat.get("id", i + 2)

        prev_text = fragments[i][2] if i < len(fragments) and fragments[i][2] else ""
        next_text = fragments[i + 1][2] if i + 1 < len(fragments) and fragments[i + 1][2] else ""

        hints = []

        # --- 时间跳跃检测 ---
        prev_scene = prev_beat.get("scene", "")
        next_scene = next_beat.get("scene", "")
        prev_time = ""
        next_time = ""
        if prev_scene and "/" in prev_scene:
            parts = prev_scene.split("/")
            prev_time = parts[1].strip() if len(parts) > 1 else ""
        if next_scene and "/" in next_scene:
            parts = next_scene.split("/")
            next_time = parts[1].strip() if len(parts) > 1 else ""

        time_shift = False
        if prev_time and next_time and prev_time != next_time:
            # 更细致的时间变化检测
            time_day = {"晨", "早", "上午", "白天", "中午", "午后", "下午"}
            time_night = {"夜", "晚", "傍晚", "黄昏", "深夜", "凌晨"}
            prev_is_day = bool(time_day & set(prev_time))
            next_is_day = bool(time_day & set(next_time))
            prev_is_night = bool(time_night & set(prev_time))
            next_is_night = bool(time_night & set(next_time))
            if (prev_is_day and next_is_night) or (prev_is_night and next_is_day):
                time_shift = True
            elif prev_time != next_time:
                # 不同时间段（同日/夜）
                time_shift = True

        if time_shift:
            hints.append({
                "type": "时间过渡",
                "detail": f"Beat {prev_bid}「{prev_beat.get('name', '')}」（{prev_time}）"
                          f" → Beat {next_bid}「{next_beat.get('name', '')}」（{next_time}）",
                "suggestion": f"建议添加时间过渡词，如："
                               f"「时光流转，转眼已到了{next_time}」"
                               f"或「{next_time}，{next_scene.split('/')[0] if '/' in next_scene else ''}里...」",
            })

        # --- 空间转换检测 ---
        prev_loc = prev_scene.split("/")[0].strip() if prev_scene and "/" in prev_scene else prev_scene
        next_loc = next_scene.split("/")[0].strip() if next_scene and "/" in next_scene else next_scene
        space_shift = False
        if prev_loc and next_loc:
            prev_words = set(prev_loc)
            next_words = set(next_loc)
            overlap = prev_words & next_words
            if not overlap:
                space_shift = True

        if space_shift:
            hints.append({
                "type": "空间过渡",
                "detail": f"Beat {prev_bid}（{prev_loc}）→ Beat {next_bid}（{next_loc}）",
                "suggestion": f"建议添加场景切换标记，如："
                               f"用动作转场（角色移动到{next_loc}）"
                               f"或用环境描写衔接两个场景",
            })

        # --- 情绪突变检测 ---
        prev_emotion = prev_beat.get("emotion", "")
        next_emotion = next_beat.get("emotion", "")
        emotion_shift = False
        emotion_opposites = [
            ("悲伤", ["喜悦", "兴奋", "温馨", "希望"]),
            ("愤怒", ["平静", "温馨", "喜悦"]),
            ("恐惧", ["平静", "温馨", "喜悦"]),
            ("紧张", ["平静", "温馨"]),
            ("绝望", ["喜悦", "希望", "温暖"]),
            ("平静", ["震惊", "愤怒", "恐惧", "悲伤"]),
            ("喜悦", ["悲伤", "愤怒", "恐惧"]),
        ]
        if prev_emotion and next_emotion:
            for neg, pos_list in emotion_opposites:
                if neg in prev_emotion:
                    for pos in pos_list:
                        if pos in next_emotion:
                            emotion_shift = True
                            break
                if emotion_shift:
                    break

        if emotion_shift:
            hints.append({
                "type": "情绪缓冲",
                "detail": f"Beat {prev_bid}（情绪：{prev_emotion}）→ Beat {next_bid}（情绪：{next_emotion}）",
                "suggestion": f"情绪从「{prev_emotion}」切换到「{next_emotion}」跨度较大，"
                               f"建议添加情绪缓冲句，如：内心独白、环境烘托、"
                               f"或通过其他角色的反应来过渡情绪",
            })

        # --- 视角切换检测 ---
        prev_chars = set(prev_beat.get("characters", []))
        next_chars = set(next_beat.get("characters", []))
        pov_shift = False
        if prev_chars and next_chars:
            # 如果前Beat的视角角色在后Beat中不存在
            shared = prev_chars & next_chars
            only_prev = prev_chars - next_chars
            only_next = next_chars - prev_chars
            if only_prev and only_next and not shared:
                pov_shift = True

        if pov_shift:
            hints.append({
                "type": "视角转换",
                "detail": f"Beat {prev_bid}（{', '.join(prev_chars)}）→ Beat {next_bid}（{', '.join(next_chars)}）",
                "suggestion": f"人物阵营完全切换，建议添加视角转换标识，"
                               f"如：「与此同时」「另一边」或通过第三方叙述连接",
            })

        # --- 对话连续检测 ---
        if prev_text and next_text:
            if _ends_with_dialogue(prev_text) and _starts_with_dialogue(next_text):
                hints.append({
                    "type": "对话衔接",
                    "detail": f"Beat {prev_bid} 结尾是对话，Beat {next_bid} 开头也是对话",
                    "suggestion": f"建议在对话之间插入动作描写或场景说明，"
                                   f"避免读者混淆说话人",
                })

        # 生成该边界的 Markdown 段
        if hints:
            lines.append(f"## Beat {prev_bid} → Beat {next_bid}")
            for h in hints:
                lines.append(f"### {h['type']}")
                lines.append(f"- **变更**：{h['detail']}")
                lines.append(f"- **建议**：{h['suggestion']}")
                lines.append("")
            polish_hints.append({
                "boundary": f"{prev_bid}->{next_bid}",
                "hints": hints,
            })
        else:
            lines.append(f"## Beat {prev_bid} → Beat {next_bid}")
            lines.append("无需润色，衔接自然。")
            lines.append("")

    # 4. 输出提示
    output_text = "\n".join(lines) + "\n"
    output_file = os.path.join(book_root, META_DIR,
                                f"polish_hints_ch{chapter_no}.md")
    _ensure_dir(output_file)
    _write(output_file, output_text)

    # 输出 JSON 格式的结构化提示
    polish_json = {
        "version": VERSION,
        "chapter": chapter_no,
        "title": beat_sheet.get("title", ""),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_boundaries": len(beats) - 1,
        "boundaries_needing_polish": len(polish_hints),
        "hints": polish_hints,
    }
    polish_json_file = os.path.join(book_root, META_DIR,
                                     f"polish_hints_ch{chapter_no}.json")
    _write_json(polish_json_file, polish_json)

    print(f"\n  总边界数：{len(beats) - 1}")
    print(f"  需要润色：{len(polish_hints)} 处")
    print(f"\n润色提示已输出：{output_file}")
    print(f"结构化提示已输出：{polish_json_file}")
    return 0


# =========================================================
# 主入口
# =========================================================


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="章节合成器 v1.0：Beat 片段合成 + 质量校验 + 过渡润色提示"
    )
    ap.add_argument("command", choices=["synthesize", "check", "polish"],
                    help="子命令：synthesize=合成章节, check=质量校验, polish=润色提示")
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--chapter", type=int, required=True,
                    help="章号")
    ap.add_argument("--manuscript", default=None,
                    help="合成稿文件路径（check 子命令用，不指定则自动查找）")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    if args.command == "synthesize":
        return cmd_synthesize(book_root, args)
    elif args.command == "check":
        return cmd_check(book_root, args)
    elif args.command == "polish":
        return cmd_polish(book_root, args)

    print(f"错误：未知子命令 {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
