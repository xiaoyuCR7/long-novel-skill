#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""beat_sheet_generator.py — Beat Sheet（分镜表）生成器 v1.0（纯标准库，无第三方依赖）。

将复杂章节拆解为多个 Beat（节拍），每个 Beat 是一个独立的叙事单元。
配合 beat-pipeline.md 工作流使用，解决 AI 单次生成长章节时容易压缩剧情、
跳过细节的问题。

三个核心子命令：
  generate  — 从章纲生成 Beat Sheet（读取章纲，按场景/情绪转折拆分为 3-7 个 Beat）
  expand    — 为指定 Beat 生成扩写提示（角色/场景/情绪/动作/对话五维度提示）
  validate  — 校验合成稿（检查 Beat 覆盖度、字数分布、情绪曲线连贯性）

Beat Sheet 产出为 JSON 格式，存入 `追踪/beat_sheets/beat_ch{N}.json`。
expand 产出为 Markdown 格式提示，直接输出到终端。
validate 产出为 JSON 格式校验报告，同时更新 Beat Sheet 中的 validation 字段。

用法：
  python scripts/beat_sheet_generator.py generate "{书名目录}" --chapter 37
  python scripts/beat_sheet_generator.py expand "{书名目录}" --chapter 37 --beat 2
  python scripts/beat_sheet_generator.py validate "{书名目录}" --chapter 37 --manuscript "正文/第037章_标题.md"
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =========================================================
# 常量
# =========================================================

VERSION = "1.0.0"

# Beat Sheet 输出目录（相对于书籍工程根目录）
BEAT_SHEET_DIR = "追踪/beat_sheets"

# 情绪关键词映射：章纲中可能出现的情绪标记
EMOTION_KEYWORDS = {
    "紧张": "紧张",
    "焦虑": "焦虑",
    "恐惧": "恐惧",
    "愤怒": "愤怒",
    "悲伤": "悲伤",
    "绝望": "绝望",
    "平静": "平静",
    "安宁": "安宁",
    "温馨": "温馨",
    "喜悦": "喜悦",
    "兴奋": "兴奋",
    "期待": "期待",
    "疑惑": "疑惑",
    "震惊": "震惊",
    "爆发": "爆发",
    "转折": "转折",
    "悬念": "悬念",
    "压抑": "压抑",
    "释放": "释放",
    "感动": "感动",
    "尴尬": "尴尬",
    "嘲讽": "嘲讽",
    "警惕": "警惕",
    "危机": "危机",
    "绝望": "绝望",
    "温暖": "温暖",
    "杀意": "杀意",
    "温情": "温情",
}

# 场景类型关键词
SCENE_TYPE_KEYWORDS = {
    "对话": "对话",
    "交谈": "对话",
    "说话": "对话",
    "争论": "对话",
    "谈判": "对话",
    "质问": "对话",
    "动作": "动作",
    "战斗": "动作",
    "打斗": "动作",
    "逃跑": "动作",
    "追逐": "动作",
    "出手": "动作",
    "出拳": "动作",
    "拔剑": "动作",
    "心理": "心理",
    "内心": "心理",
    "回忆": "心理",
    "思考": "心理",
    "独白": "心理",
    "场景": "场景",
    "环境": "场景",
    "描写": "场景",
    "赶路": "动作",
    "移动": "动作",
}

# 场景转换标记：章纲中出现这些标记意味着应该拆出新 Beat
SCENE_BREAK_MARKERS = [
    r"场景[切换转]",
    r"转场",
    r"时间[：:跳转]",
    r"视角[切换转]",
    r"与此同时",
    r"另一边",
    r"稍后",
    r"次日",
    r"次日清晨",
    r"当天",
    r"傍晚",
    r"深夜",
    r"黎明",
    r"与此同时",
    r"然而",
    r"但是",
    r"突然",
    r"这时",
    r"就在此时",
    r"与此同时",
]

# 节奏档位
PACE_LEVELS = ["慢", "中", "快"]


# =========================================================
# 工具函数
# =========================================================

def find_book_dir(path: str) -> Optional[Path]:
    """查找书籍工程目录，验证存在 大纲 和 追踪 目录。"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return None
    if (p / "追踪").exists() and (p / "大纲").exists():
        return p
    for child in p.iterdir():
        if child.is_dir() and (child / "追踪").exists() and (child / "大纲").exists():
            return child
    return None


def read_text(path: Path) -> Optional[str]:
    """安全读取文本文件。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def load_json(path: Path, default: Any = None) -> Any:
    """安全加载 JSON 文件。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data: Any) -> bool:
    """保存 JSON 文件，自动创建父目录。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def find_outline_file(book_dir: Path, chapter: int) -> Optional[Path]:
    """查找指定章节的章纲文件。

    支持的文件名模式：
      大纲/章纲_第XXX章.md
      大纲/章纲_第XXX章_*.md
    """
    outline_dir = book_dir / "大纲"
    if not outline_dir.exists():
        return None
    # 精确匹配
    for pattern in [
        f"章纲_第{chapter:03d}章.md",
        f"章纲_第{chapter}章.md",
    ]:
        p = outline_dir / pattern
        if p.exists():
            return p
    # 模糊匹配
    for f in outline_dir.glob(f"章纲_第*{chapter}章*.md"):
        match = re.search(rf"第(\d+)章", f.name)
        if match and int(match.group(1)) == chapter:
            return f
    return None


def find_manuscript_file(book_dir: Path, chapter: int) -> Optional[Path]:
    """查找指定章节的正文文件。

    支持的文件名模式：
      正文/第XXX章_*.md
      正文/第XXX章.md
    """
    text_dir = book_dir / "正文"
    if not text_dir.exists():
        return None
    for pattern in [
        f"第{chapter:03d}章_*.md",
        f"第{chapter}章_*.md",
    ]:
        matches = list(text_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def count_chinese_chars(text: str) -> int:
    """统计文本中的中文字符数（不含标点和空白）。"""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def extract_emotion_from_text(text: str) -> List[str]:
    """从文本中提取情绪标记。"""
    found = []
    seen = set()
    for keyword, emotion in EMOTION_KEYWORDS.items():
        if keyword in text and emotion not in seen:
            found.append(emotion)
            seen.add(emotion)
    return found


def extract_scene_type_from_text(text: str) -> str:
    """从文本中判断主要场景类型。"""
    type_counts = {}
    for keyword, scene_type in SCENE_TYPE_KEYWORDS.items():
        count = text.count(keyword)
        if count > 0:
            type_counts[scene_type] = type_counts.get(scene_type, 0) + count
    if not type_counts:
        return "场景"
    return max(type_counts, key=type_counts.get)


def extract_chapter_title(outline_text: str) -> str:
    """从章纲中提取章节标题。

    优先级：
      1. 第一行 `# 第N章 标题` 或 `# 标题`
      2. `- 标题：xxx` 元信息行
      3. `标题：xxx` 行
    """
    # 尝试从第一行 # 标题 提取
    first_line = outline_text.strip().split("\n")[0].strip()
    match = re.match(r"^#\s*第\d+章\s*(.+?)\s*$", first_line)
    if match:
        title = match.group(1).strip()
        if title:
            return title
    match = re.match(r"^#\s*(.+?)\s*$", first_line)
    if match:
        title = match.group(1).strip()
        # 排除 "Beat Sheet" 等无关标题
        if title and "beat sheet" not in title.lower():
            return title
    # 回退：从元信息行提取
    match = re.search(r"^-\s*标题[：:]\s*(.+?)(?:\n|$)", outline_text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    match = re.search(r"标题[：:]\s*(.+?)(?:\n|$)", outline_text)
    if match:
        return match.group(1).strip()
    return ""


def extract_target_chars(outline_text: str) -> int:
    """从章纲中提取目标字数。"""
    # 匹配 "字数预算：2000-3000字" 或 "目标字数：3000字"
    for pattern in [
        r"字数预算[：:]\s*(\d+)\s*[-—~]\s*(\d+)",
        r"目标字数[：:]\s*(\d+)",
        r"全章字数预算[：:]\s*(\d+)\s*[-—~]\s*(\d+)",
        r"(\d+)\s*[-—~]\s*(\d+)\s*字",
    ]:
        match = re.search(pattern, outline_text)
        if match:
            try:
                low = int(match.group(1))
                high = int(match.group(2))
                return (low + high) // 2
            except (IndexError, ValueError):
                try:
                    return int(match.group(1))
                except (IndexError, ValueError):
                    pass
    return 3000  # 默认值


def extract_pace_level(outline_text: str) -> str:
    """从章纲中提取节奏档位。"""
    match = re.search(r"节奏档位[：:]\s*(慢|中|快)", outline_text)
    if match:
        return match.group(1)
    return "中"


def detect_scene_breaks(outline_text: str) -> List[Tuple[int, str, str]]:
    """检测章纲中的场景/时间/视角转换点。

    Returns:
        列表，每项为 (行号, 行内容, 匹配的标记)
    """
    breaks = []
    for i, line in enumerate(outline_text.split("\n")):
        for marker in SCENE_BREAK_MARKERS:
            m = re.search(marker, line)
            if m:
                breaks.append((i, line.strip(), m.group()))
                break
    return breaks


def parse_outline_sections(outline_text: str) -> List[Dict[str, Any]]:
    """解析章纲为结构化的段落/场景列表。

    按以下规则拆分：
      1. 场景转换标记
      2. ## 级标题
      3. - 列表项中的场景描述

    Returns:
        段落列表，每项包含 text, line_start, elements, emotion, scene_type
    """
    sections = []
    lines = outline_text.split("\n")

    # 找到 Beat 清单区域之后的内容（如果有的话）
    in_beat_list = False
    beat_list_end = len(lines)
    for i, line in enumerate(lines):
        if re.match(r"^##\s*Beat\s*清单", line):
            in_beat_list = True
        if in_beat_list and line.startswith("## ") and "Beat 清单" not in line:
            beat_list_end = i
            in_beat_list = False
            break

    # 找节奏预检区域
    in_rhythm = False
    rhythm_start = len(lines)
    for i, line in enumerate(lines):
        if re.match(r"^##\s*节奏预检", line):
            rhythm_start = i
            break

    # 有效内容范围：跳过 Beat 清单和节奏预检
    valid_start = 0
    # 跳过文件头（标题、元信息行）
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("- 章") or stripped.startswith("- 节奏"):
            continue
        valid_start = i
        break

    effective_lines = lines[valid_start:beat_list_end]

    # 按场景转换拆分
    current_section = {"text_lines": [], "line_start": valid_start}
    sections_accum = []

    for i, line in enumerate(effective_lines):
        stripped = line.strip()
        is_break = False

        # 检查是否是场景转换标记
        for marker in SCENE_BREAK_MARKERS:
            if re.search(marker, stripped):
                is_break = True
                break

        # ## 级标题也算新场景
        if re.match(r"^##\s+", stripped) and not re.match(r"^##\s*(Beat 清单|节奏预检)", stripped):
            is_break = True

        if is_break and current_section["text_lines"]:
            # 保存当前段
            text = "\n".join(current_section["text_lines"]).strip()
            if text:
                sections_accum.append({
                    "text": text,
                    "line_start": current_section["line_start"],
                })
            current_section = {"text_lines": [], "line_start": valid_start + i}

        if stripped:  # 跳过空行
            current_section["text_lines"].append(stripped)

    # 保存最后一段
    if current_section["text_lines"]:
        text = "\n".join(current_section["text_lines"]).strip()
        if text:
            sections_accum.append({
                "text": text,
                "line_start": current_section["line_start"],
            })

    # 如果拆分太少，尝试按 - 列表项拆分
    if len(sections_accum) <= 1:
        sections_accum = []
        for i, line in enumerate(effective_lines):
            stripped = line.strip()
            if stripped.startswith("- ") and not stripped.startswith("- 章") and not stripped.startswith("- 节奏"):
                sections_accum.append({
                    "text": stripped[2:].strip(),
                    "line_start": valid_start + i,
                })

    # 为每段提取元信息
    for sec in sections_accum:
        text = sec["text"]
        sec["emotion"] = extract_emotion_from_text(text)
        sec["scene_type"] = extract_scene_type_from_text(text)
        sec["elements"] = extract_key_elements(text)

    return sections_accum


def extract_key_elements(text: str) -> List[str]:
    """从文本中提取关键元素（角色名、地点名等）。

    简单规则：提取加粗文本和中文人名/地名模式。
    """
    elements = []
    seen = set()

    # 提取加粗文本
    bolds = re.findall(r"\*\*([^*]+)\*\*", text)
    for b in bolds:
        b = b.strip()
        if len(b) <= 10 and b not in seen:
            elements.append(b)
            seen.add(b)

    # 提取「」中的内容
    brackets = re.findall(r"「([^」]+)」", text)
    for b in brackets:
        b = b.strip()
        if len(b) <= 10 and b not in seen:
            elements.append(b)
            seen.add(b)

    # 提取"出场人物"后的内容
    match = re.search(r"出场人物[：:]\s*([^\n]+)", text)
    if match:
        for name in re.split(r"[,，、;；]", match.group(1)):
            name = name.strip()
            if name and name not in seen:
                elements.append(name)
                seen.add(name)

    return elements


def allocate_chars_by_complexity(
    total_chars: int,
    sections: List[Dict[str, Any]],
) -> List[int]:
    """按场景复杂度加权分配目标字数。

    复杂度因素：
      - 文本长度（章纲中描述越长，场景越复杂）
      - 情绪种类（情绪变化多 = 更复杂）
      - 关键元素数量
      - 场景类型（对话通常比纯描写需要更多字数展开）
    """
    if not sections:
        return []

    n = len(sections)
    weights = []
    for sec in sections:
        w = 1.0
        # 文本长度权重
        text_len = len(sec.get("text", ""))
        w += text_len / 200.0
        # 情绪复杂度
        w += len(sec.get("emotion", [])) * 0.5
        # 关键元素数量
        w += len(sec.get("elements", [])) * 0.3
        # 场景类型权重
        st = sec.get("scene_type", "")
        if st == "对话":
            w += 0.5
        elif st == "动作":
            w += 0.8
        elif st == "心理":
            w += 0.3
        weights.append(max(w, 0.5))

    total_weight = sum(weights)

    # 限制 Beat 数量：3-7 个
    if n < 3:
        # 如果拆分太少，不强制增加——保持已识别的场景
        pass
    elif n > 7:
        # 合并权重最低的相邻 Beat
        while n > 7:
            min_idx = 0
            min_w = weights[0] + weights[1]
            for i in range(1, n - 1):
                combined = weights[i] + weights[i + 1]
                if combined < min_w:
                    min_w = combined
                    min_idx = i
            # 合并
            weights[min_idx] += weights[min_idx + 1]
            sections[min_idx]["text"] += "\n" + sections[min_idx + 1]["text"]
            sections[min_idx]["emotion"].extend(sections[min_idx + 1].get("emotion", []))
            sections[min_idx]["elements"].extend(sections[min_idx + 1].get("elements", []))
            del weights[min_idx + 1]
            del sections[min_idx + 1]
            n -= 1

    # 分配字数
    allocations = []
    for i, w in enumerate(weights):
        allocated = int(total_chars * w / sum(weights))
        # 确保每个 Beat 至少 200 字
        allocated = max(allocated, 200)
        allocations.append(allocated)

    # 校正总和（四舍五入可能导致偏差）
    diff = total_chars - sum(allocations)
    if diff != 0:
        # 按权重比例分配偏差
        idx = 0
        remaining = abs(diff)
        step = 1 if diff > 0 else -1
        while remaining > 0:
            allocations[idx] += step
            remaining -= 1
            idx = (idx + 1) % len(allocations)

    return allocations


# =========================================================
# generate 命令
# =========================================================

def cmd_generate(book_dir: Path, chapter: int, args) -> Dict[str, Any]:
    """generate 命令 — 从章纲生成 Beat Sheet。

    流程：
      1. 读取章纲文件
      2. 提取章节标题、目标字数、节奏档位
      3. 解析章纲为结构化段落
      4. 按场景/情绪转折拆分为 Beat
      5. 为每个 Beat 分配目标字数
      6. 生成情绪曲线
      7. 输出 Beat Sheet JSON
    """
    result = {
        "chapter": chapter,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Step 1: 查找章纲文件
    outline_path = find_outline_file(book_dir, chapter)
    if not outline_path:
        result["ok"] = False
        result["error"] = f"未找到第{chapter}章章纲文件（期望路径：大纲/章纲_第{chapter:03d}章.md）"
        return result

    outline_text = read_text(outline_path)
    if not outline_text:
        result["ok"] = False
        result["error"] = f"章纲文件为空：{outline_path}"
        return result

    result["outline_file"] = str(outline_path)

    # Step 2: 提取元信息
    title = extract_chapter_title(outline_text)
    if not title:
        # 从文件名提取
        match = re.search(r"第\d+章_(.+?)(?:\.md)?$", outline_path.stem)
        if match:
            title = match.group(1)
        else:
            title = f"第{chapter}章"

    target_chars = extract_target_chars(outline_text)
    pace_level = extract_pace_level(outline_text)

    # Step 3: 解析章纲段落
    sections = parse_outline_sections(outline_text)
    if not sections:
        result["ok"] = False
        result["error"] = "章纲解析失败：未能识别任何场景/情节点"
        return result

    result["raw_sections"] = len(sections)

    # Step 4: 分配字数
    allocations = allocate_chars_by_complexity(target_chars, sections)

    # Step 5: 构建 Beat 列表
    beats = []
    emotion_curve = []
    for i, (sec, alloc) in enumerate(zip(sections, allocations)):
        beat_id = i + 1

        # 确定 Beat 名称
        name = _generate_beat_name(sec, beat_id, len(sections))

        # 情绪：优先从段提取，否则从曲线推断
        if sec.get("emotion"):
            emotion = sec["emotion"][0]
        elif emotion_curve:
            emotion = _infer_next_emotion(emotion_curve[-1], beat_id, len(sections))
        else:
            emotion = "平静"

        emotion_curve.append(emotion)

        # 场景类型
        scene_type = sec.get("scene_type", "场景")

        # 关键元素
        key_elements = list(set(sec.get("elements", [])))[:5]

        # 钩子：从段末提取或生成默认
        hook = _extract_hook(sec, beat_id, len(sections))

        # 章纲引用（取段首行作为引用）
        outline_ref = sec.get("text", "")[:80]

        beat = {
            "id": beat_id,
            "name": name,
            "scene_type": scene_type,
            "emotion": emotion,
            "target_chars": alloc,
            "key_elements": key_elements,
            "hook": hook,
            "outline_ref": outline_ref,
        }
        beats.append(beat)

    # Step 6: 情绪曲线连贯性校验
    emotion_flow = _check_emotion_flow(emotion_curve)

    # Step 7: 构建 Beat Sheet
    beat_sheet = {
        "version": VERSION,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chapter": chapter,
        "title": title,
        "outline_file": str(outline_path.relative_to(book_dir)) if outline_path.is_relative_to(book_dir) else outline_path.name,
        "pace_level": pace_level,
        "total_beats": len(beats),
        "target_chars": target_chars,
        "beats": beats,
        "emotion_curve": emotion_curve,
        "validation": {
            "total_coverage": 1.0,
            "char_distribution": _check_char_distribution(beats, target_chars),
            "emotion_flow": emotion_flow,
        },
    }

    # 保存 Beat Sheet
    output_dir = book_dir / BEAT_SHEET_DIR
    output_path = output_dir / f"beat_ch{chapter:03d}.json"
    saved = save_json(output_path, beat_sheet)

    result["ok"] = saved
    result["beat_sheet"] = beat_sheet
    result["output_file"] = str(output_path)
    result["total_beats"] = len(beats)
    result["target_chars"] = target_chars

    return result


def _generate_beat_name(sec: Dict[str, Any], beat_id: int, total_beats: int) -> str:
    """为 Beat 生成名称。

    清理规则：
      - 去除 markdown 标题前缀（## / ###）
      - 去除"章纲"、"场景切换"、"视角切换"等元信息前缀
      - 去除"大纲/章纲_xxx.md"等路径引用
      - 提取实际场景描述或动作内容
    """
    text = sec.get("text", "")
    elements = sec.get("elements", [])
    emotions = sec.get("emotion", [])
    scene_type = sec.get("scene_type", "")

    # 尝试从段首行提取动作描述
    first_line = text.split("\n")[0] if text else ""

    # 清理前缀：去除 markdown 标题符号、列表符号、元信息前缀
    first_line = re.sub(r"^#{1,6}\s*", "", first_line)  # ## 标题
    first_line = re.sub(r"^[-*]\s*", "", first_line)    # - 列表
    # 去除"场景切换："、"视角切换："等元信息前缀，保留后面的内容
    first_line = re.sub(r"^(场景|视角|时间|地点)[切换转]*[：:]\s*", "", first_line)
    # 去除"章纲："等引用前缀
    first_line = re.sub(r"^章纲[：:]\s*", "", first_line)
    # 去除文件路径
    first_line = re.sub(r"大纲[/\\]章纲[^\s]*\.md\s*", "", first_line)
    # 去除"场景一："、"场景二："等编号
    first_line = re.sub(r"^场景[一二三四五六七八九十\d]+[：:]\s*", "", first_line)
    first_line = first_line.strip()

    # 如果首行太短或为空，尝试第二行
    if len(first_line) < 2:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines[1:3]:
            cleaned = re.sub(r"^[-*#]+\s*", "", line)
            cleaned = re.sub(r"^(场景|视角|时间|地点)[切换转]*[：:]\s*", "", cleaned)
            cleaned = cleaned.strip()
            if len(cleaned) >= 2:
                first_line = cleaned
                break

    # 截断过长的首行（取第一个完整句子或前 20 字）
    if len(first_line) > 20:
        # 尝试在标点处截断
        for sep in ["。", "，", "；", "、", " "]:
            idx = first_line.find(sep)
            if 2 <= idx <= 20:
                first_line = first_line[:idx]
                break
        else:
            first_line = first_line[:20]

    # 根据位置确定前缀
    if beat_id == 1:
        prefix = "开场"
    elif beat_id == total_beats:
        prefix = "结尾"
    else:
        prefix = f"发展{beat_id - 1}"

    # 组合名称
    if first_line and len(first_line) >= 2:
        return f"{prefix}：{first_line}"
    elif elements:
        return f"{prefix}：{elements[0]}"
    elif emotions:
        return f"{prefix}：{emotions[0]}段"
    elif scene_type:
        return f"{prefix}：{scene_type}场景"
    else:
        return f"{prefix}"


def _extract_hook(sec: Dict[str, Any], beat_id: int, total_beats: int) -> str:
    """从段中提取钩子（Beat 末尾留什么）。"""
    text = sec.get("text", "")

    # 尝试匹配"钩子"相关标记
    match = re.search(r"钩子[：:]\s*(.+?)(?:\n|$)", text)
    if match:
        return match.group(1).strip()

    # 从段末提取悬念句
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        last_line = lines[-1]
        # 去掉编号前缀
        last_line = re.sub(r"^[-*]\s*", "", last_line)
        if len(last_line) <= 30 and re.search(r"[？?!！]", last_line):
            return last_line

    # 默认钩子
    if beat_id == total_beats:
        return "章尾钩子，引出下一章悬念"
    elif beat_id == 1:
        return "章首钩子，建立读者兴趣"
    else:
        return ""


def _infer_next_emotion(prev_emotion: str, beat_id: int, total_beats: int) -> str:
    """推断下一个情绪值。"""
    # 简单的渐进模型：情绪随着 Beat 递进
    calm_emotions = {"平静", "安宁", "温馨", "温暖", "温情"}
    rising_emotions = {"紧张", "焦虑", "恐惧", "愤怒", "警惕", "杀意"}
    peak_emotions = {"爆发", "震惊", "绝望"}
    falling_emotions = {"释放", "感动", "悲伤", "悬念", "疑惑"}

    if prev_emotion in calm_emotions:
        if beat_id <= total_beats // 2:
            return "紧张"
        else:
            return "释放"
    elif prev_emotion in rising_emotions:
        if beat_id < total_beats:
            return "爆发"
        else:
            return "悬念"
    elif prev_emotion in peak_emotions:
        return "回落"
    else:
        return "转折"


def _check_emotion_flow(curve: List[str]) -> str:
    """检查情绪曲线的连贯性。"""
    if len(curve) <= 1:
        return "smooth"

    calm = {"平静", "安宁", "温馨", "温暖", "温情"}
    intense = {"爆发", "震惊", "绝望", "愤怒", "恐惧"}
    negative = {"紧张", "焦虑", "悲伤", "压抑", "杀意", "警惕", "杀意"}

    abrupt_count = 0
    for i in range(1, len(curve)):
        prev = curve[i - 1]
        curr = curve[i]
        # 从平静直接跳到爆发 = 突变
        if prev in calm and curr in intense:
            abrupt_count += 1
        # 从爆发直接跳回平静 = 突变
        elif prev in intense and curr in calm:
            abrupt_count += 1

    if abrupt_count == 0:
        return "smooth"
    elif abrupt_count == 1:
        return "acceptable"  # 一个转折可以接受
    else:
        return "abrupt"


def _check_char_distribution(beats: List[Dict], target_chars: int) -> str:
    """检查字数分布是否均衡。"""
    if not beats:
        return "unknown"

    chars = [b["target_chars"] for b in beats]
    avg = sum(chars) / len(chars)
    max_dev = max(abs(c - avg) / avg for c in chars) if avg > 0 else 0

    if max_dev <= 0.2:
        return "balanced"
    elif max_dev <= 0.4:
        return "moderate"
    else:
        return "uneven"


# =========================================================
# expand 命令
# =========================================================

def cmd_expand(book_dir: Path, chapter: int, beat_id: int, args) -> Dict[str, Any]:
    """expand 命令 — 为指定 Beat 生成五维度扩写提示。

    五维度：
      1. 角色维度：出场角色当前状态、动机、关系张力
      2. 场景维度：环境细节、感官描写方向
      3. 情绪维度：本 Beat 情绪目标、与前 Beat 的情绪衔接
      4. 动作维度：关键动作序列、身体细节建议
      5. 对话维度：对话目的、信息差、潜台词方向

    输出 Markdown 格式提示。
    """
    result = {
        "chapter": chapter,
        "beat_id": beat_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 读取 Beat Sheet
    beat_sheet_path = book_dir / BEAT_SHEET_DIR / f"beat_ch{chapter:03d}.json"
    beat_sheet = load_json(beat_sheet_path)
    if not beat_sheet:
        result["ok"] = False
        result["error"] = f"未找到 Beat Sheet：{beat_sheet_path}。请先执行 generate 命令。"
        return result

    beats = beat_sheet.get("beats", [])
    beat = None
    for b in beats:
        if b["id"] == beat_id:
            beat = b
            break

    if not beat:
        result["ok"] = False
        result["error"] = f"Beat Sheet 中不存在 Beat {beat_id}（共 {len(beats)} 个 Beat）"
        return result

    # 读取角色状态（用于角色维度提示）
    char_state_path = book_dir / "追踪" / "角色状态.md"
    char_state = read_text(char_state_path) or ""

    # 读取前一章摘要（用于上下文衔接）
    prev_ch_summary = ""
    prev_summary_path = book_dir / "追踪" / "章节摘要.md"
    if prev_summary_path.exists():
        summary_text = read_text(prev_summary_path) or ""
        # 提取前一章摘要
        blocks = re.split(r"\n### 第(\d+)章", summary_text)
        for i in range(1, len(blocks), 2):
            try:
                ch_num = int(blocks[i])
                if ch_num == chapter - 1:
                    prev_ch_summary = blocks[i + 1] if i + 1 < len(blocks) else ""
                    break
            except ValueError:
                continue

    # 生成五维度提示
    prompt_lines = _generate_expand_prompt(
        beat=beat,
        beat_sheet=beat_sheet,
        char_state=char_state,
        prev_summary=prev_ch_summary,
        chapter=chapter,
    )

    result["ok"] = True
    result["prompt"] = prompt_lines
    return result


def _generate_expand_prompt(
    beat: Dict,
    beat_sheet: Dict,
    char_state: str,
    prev_summary: str,
    chapter: int,
) -> str:
    """生成五维度扩写提示的 Markdown 文本。"""
    lines = []
    beat_id = beat["id"]
    total_beats = beat_sheet["total_beats"]
    title = beat_sheet["title"]

    lines.append(f"# Beat {beat_id} 扩写提示 — 第{chapter}章「{title}」")
    lines.append("")
    lines.append(f"**Beat 名称**：{beat['name']}")
    lines.append(f"**场景类型**：{beat['scene_type']}")
    lines.append(f"**目标情绪**：{beat['emotion']}")
    lines.append(f"**目标字数**：{beat['target_chars']}字")
    lines.append(f"**位置**：第 {beat_id}/{total_beats} 拍")
    lines.append("")

    if beat.get("key_elements"):
        lines.append(f"**关键元素**：{', '.join(beat['key_elements'])}")
        lines.append("")

    if beat.get("outline_ref"):
        lines.append(f"**章纲引用**：{beat['outline_ref']}")
        lines.append("")

    # --- 维度一：角色 ---
    lines.append("---")
    lines.append("")
    lines.append("## 维度一：角色")
    lines.append("")

    elements = beat.get("key_elements", [])
    if elements:
        lines.append(f"**出场角色**：{', '.join(elements)}")
        lines.append("")
        for elem in elements:
            # 尝试从角色状态中查找该角色
            char_info = _lookup_char_state(char_state, elem)
            if char_info:
                lines.append(f"- {elem}：{char_info[:100]}")
            else:
                lines.append(f"- {elem}：需补充当前状态与动机")
            # 关系张力提示
            if len(elements) > 1:
                other_chars = [e for e in elements if e != elem]
                for other in other_chars[:2]:
                    lines.append(f"  - 与 {other} 的关系张力：需明确当前态度（对抗/合作/试探）")
    else:
        lines.append("本章拍未明确标注出场角色，请根据章纲补充。")

    lines.append("")

    # --- 维度二：场景 ---
    lines.append("---")
    lines.append("")
    lines.append("## 维度二：场景")
    lines.append("")

    scene_type = beat.get("scene_type", "场景")
    lines.append(f"**场景类型**：{scene_type}")
    lines.append("")

    if scene_type == "对话":
        lines.append("**场景描写方向**：")
        lines.append("- 对话发生的空间：室内/室外/半封闭")
        lines.append("- 光线与氛围：时间对应的光照条件")
        lines.append("- 声音环境：安静/嘈杂/自然声（风/雨/虫鸣）")
        lines.append("- 角色位置关系：面对面/侧面/背对，距离远近")
    elif scene_type == "动作":
        lines.append("**场景描写方向**：")
        lines.append("- 空间布局：障碍物、通道、高低差")
        lines.append("- 地面材质：影响脚步声和动作质感")
        lines.append("- 环境危险因素：可利用的地形/物品")
        lines.append("- 光影变化：动作过程中的光影变化")
    elif scene_type == "心理":
        lines.append("**场景描写方向**：")
        lines.append("- 内心空间的具象化：记忆画面、意象闪回")
        lines.append("- 外部环境映射内心：天气/光线暗示情绪")
        lines.append("- 身体微反应：呼吸、手指、眼神等生理反应")
    else:
        lines.append("**场景描写方向**：")
        lines.append("- 时空定位：明确的时间、地点、天气")
        lines.append("- 感官层次：视觉 > 听觉 > 触觉 > 嗅觉 > 味觉（至少覆盖前两层）")
        lines.append("- 环境氛围：与目标情绪「{0}」一致的环境细节".format(beat.get("emotion", "")))

    lines.append("")

    # --- 维度三：情绪 ---
    lines.append("---")
    lines.append("")
    lines.append("## 维度三：情绪")
    lines.append("")

    target_emotion = beat.get("emotion", "平静")
    lines.append(f"**本拍目标情绪**：{target_emotion}")
    lines.append("")

    # 情绪衔接
    emotion_curve = beat_sheet.get("emotion_curve", [])
    if beat_id > 1 and len(emotion_curve) >= beat_id:
        prev_emotion = emotion_curve[beat_id - 2]
        lines.append(f"**前一拍情绪**：{prev_emotion}")
        if prev_emotion == target_emotion:
            lines.append(f"- 情绪延续：保持「{prev_emotion}」基调，在细节中递进变化")
        else:
            lines.append(f"- 情绪转换：从「{prev_emotion}」过渡到「{target_emotion}」")
            lines.append(f"- 转换方式：通过 {get_emotion_transition(prev_emotion, target_emotion)} 实现平滑过渡")
    else:
        lines.append("- 章首 Beat：直接建立目标情绪基调")

    if beat_id < total_beats and len(emotion_curve) >= beat_id:
        next_emotion = emotion_curve[beat_id]
        lines.append(f"**下一拍情绪**：{next_emotion}")
        lines.append(f"- 本拍末尾需为「{next_emotion}」做铺垫")

    lines.append("")
    lines.append("**情绪实现手法建议**：")
    for technique in get_emotion_techniques(target_emotion):
        lines.append(f"- {technique}")

    lines.append("")

    # --- 维度四：动作 ---
    lines.append("---")
    lines.append("")
    lines.append("## 维度四：动作")
    lines.append("")

    if scene_type == "动作":
        lines.append("**关键动作序列**：")
        lines.append("- 起手/预备动作（建立张力）")
        lines.append("- 核心动作（高光时刻，需细致描写）")
        lines.append("- 动作结果（对手反应/环境变化）")
        lines.append("- 收招/余势（动作结束后的身体状态）")
        lines.append("")
        lines.append("**身体细节建议**：")
        lines.append("- 呼吸节奏：紧张时短促，发力时屏气")
        lines.append("- 肌肉紧张度：握拳/咬牙/肩膀耸起")
        lines.append("- 视线追踪：盯住目标还是扫视全局")
    elif scene_type == "对话":
        lines.append("**关键动作序列**：")
        lines.append("- 角色在对话中的微动作（打断/转身/走近/退后）")
        lines.append("- 手势与表情配合对话节奏")
        lines.append("- 对话间隙的身体语言（沉默时的动作）")
        lines.append("")
        lines.append("**身体细节建议**：")
        lines.append("- 眼神变化：回避/直视/游移")
        lines.append("- 姿势变化：前倾/后仰/交叉双臂")
        lines.append("- 手部动作：握拳/松开/摆弄物品")
    else:
        lines.append("**关键动作序列**：")
        lines.append("- 角色进入场景的动作（开门/走入/抬头）")
        lines.append("- 核心行为动作（观察/操作/等待）")
        lines.append("- 离开/转换前的收束动作")
        lines.append("")
        lines.append("**身体细节建议**：")
        lines.append("- 姿态与神态：体现角色当前心理状态")
        lines.append("- 步态与节奏：匆忙/从容/犹豫")

    lines.append("")

    # --- 维度五：对话 ---
    lines.append("---")
    lines.append("")
    lines.append("## 维度五：对话")
    lines.append("")

    if scene_type == "对话":
        lines.append("**对话目的**：推进冲突/揭示信息/建立关系/试探底牌")
        lines.append("")
        lines.append("**信息差设计**：")
        lines.append("- 读者知道但角色不知道（悬念/紧张）")
        lines.append("- 角色知道但读者不知道（揭秘/反转）")
        lines.append("- 不同角色掌握不同信息（信息不对称博弈）")
        lines.append("")
        lines.append("**潜台词方向**：")
        lines.append("- 表面意思 vs 真实意图的分层")
        lines.append("- 未说出口的话（用省略号/动作替代）")
        lines.append("- 对话中的权力博弈（谁主导、谁回避）")
    else:
        lines.append("**对话目的**：辅助叙事推进（少量对话点缀）")
        lines.append("")
        lines.append("本拍以非对话场景为主，对话应当：")
        lines.append("- 精简有力，不超过 3 轮交锋")
        lines.append("- 每句对话都承载信息或推动情节")
        lines.append("- 避免无意义的寒暄和废话")

    if beat.get("hook"):
        lines.append("")
        lines.append(f"**本拍钩子**：{beat['hook']}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Beat {beat_id}/{total_beats} | 目标字数：{beat['target_chars']}字*")

    return "\n".join(lines)


def _lookup_char_state(char_state_text: str, char_name: str) -> str:
    """从角色状态文件中查找指定角色的状态描述。"""
    if not char_state_text:
        return ""

    # 按 ## 角色名 分节查找
    sections = re.split(r"\n##\s*", char_state_text)
    for sec in sections:
        lines = sec.strip().split("\n", 1)
        name = lines[0].strip()
        if name == char_name or char_name in name:
            return lines[1].strip()[:200] if len(lines) > 1 else "有记录，详见角色状态文件"

    return ""


def get_emotion_transition(from_emotion: str, to_emotion: str) -> str:
    """获取两个情绪之间的推荐过渡方式。"""
    transitions = {
        ("平静", "紧张"): "外部事件触发（突然声响、意外消息、不安预感）",
        ("紧张", "爆发"): "导火索事件（忍无可忍、真相揭晓、威胁升级）",
        ("爆发", "回落"): "能量耗尽/外部干预（被制止、局面变化、体力不支）",
        ("回落", "悬念"): "新信息出现（意想不到的发现、未解的细节）",
        ("悬念", "紧张"): "悬念开始应验（预感成真、危险逼近）",
        ("悲伤", "愤怒"): "悲痛转化为力量（不甘心、追究责任）",
        ("愤怒", "平静"): "压抑/无奈接受/决意放下",
    }

    key = (from_emotion, to_emotion)
    if key in transitions:
        return transitions[key]

    # 通用过渡
    calm = {"平静", "安宁", "温馨", "温暖", "温情"}
    intense = {"爆发", "震惊", "绝望", "愤怒", "恐惧", "杀意"}
    negative = {"紧张", "焦虑", "悲伤", "压抑", "警惕"}

    if from_emotion in calm and to_emotion in intense:
        return "外部突发事件打破平静（转折/意外）"
    elif from_emotion in intense and to_emotion in calm:
        return "情绪释放后自然回落（呼吸平复、时间流逝）"
    elif from_emotion in negative and to_emotion in calm:
        return "问题暂时解决/转移注意力"
    else:
        return "通过场景切换和角色反应自然过渡"


def get_emotion_techniques(emotion: str) -> List[str]:
    """获取实现指定情绪的写作技巧建议。"""
    techniques_map = {
        "紧张": [
            "短句加速节奏（动词密集、形容词减少）",
            "时间感压缩（'一秒' '瞬间' '来不及'）",
            "感官收窄（聚焦单一感官：耳鸣/心跳/视线模糊）",
            "环境暗示（光线变暗、空间收紧、气温骤降）",
        ],
        "爆发": [
            "动作爆裂化（短促有力的动词，避免修饰）",
            "情绪外化（喊叫、摔打、身体不受控）",
            "时间慢镜头（关键动作逐帧描写）",
            "环境共振（物品震颤、空气凝固、草木倒伏）",
        ],
        "平静": [
            "长句营造舒缓节奏（环境描写+呼吸感）",
            "感官全开（视觉+听觉+触觉的层次描写）",
            "时间感拉长（'很久' '缓慢' '似乎没有尽头'）",
            "对比暗示（表面平静下的暗流）",
        ],
        "悲伤": [
            "身体语言代替直接表达（低头、沉默、手抖）",
            "环境呼应（雨、灰蒙蒙的天、落叶）",
            "时间停滞感（时钟不走、空气凝固）",
            "日常行为的断裂（杯中的茶凉了、筷子停在半空）",
        ],
        "悬念": [
            "信息不完整（只给碎片，让读者拼凑）",
            "延迟满足（关键时刻被打断/视角切换）",
            "暗示与伏笔（看似无关的细节埋线）",
            "结尾留白（最后一句话引发新问题）",
        ],
        "温暖": [
            "触觉细节（温度、柔软、重量）",
            "光影描写（暖色、柔光、逆光轮廓）",
            "微小动作（轻拍、注视、靠近）",
            "日常细节中的情感（一杯热茶、一件外套）",
        ],
        "愤怒": [
            "身体反应先行（瞳孔收缩、太阳穴跳动、牙关紧咬）",
            "声音变化（压低/颤抖/突然拔高）",
            "破坏性动作（握碎杯子、踩裂地板）",
            "语言克制与爆发的对比",
        ],
    }

    return techniques_map.get(emotion, [
        "通过角色内心独白直接传达情绪",
        "用环境描写暗示情绪基调",
        "通过其他角色的反应侧面烘托",
        "在对话和动作中自然流露",
    ])


# =========================================================
# validate 命令
# =========================================================

def cmd_validate(book_dir: Path, chapter: int, args) -> Dict[str, Any]:
    """validate 命令 — 校验合成稿与 Beat Sheet 的一致性。

    检查项：
      1. Beat 覆盖度：每个 Beat 是否在正文中有对应内容
      2. 字数分布：各 Beat 实际字数 vs 目标字数
      3. 情绪曲线连贯性：相邻 Beat 情绪是否合理衔接

    读取合成稿（正文文件）和 Beat Sheet JSON，输出校验报告。
    """
    result = {
        "chapter": chapter,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 读取 Beat Sheet
    beat_sheet_path = book_dir / BEAT_SHEET_DIR / f"beat_ch{chapter:03d}.json"
    beat_sheet = load_json(beat_sheet_path)
    if not beat_sheet:
        result["ok"] = False
        result["error"] = f"未找到 Beat Sheet：{beat_sheet_path}。请先执行 generate 命令。"
        return result

    # 读取合成稿
    manuscript_path = None
    if args.manuscript:
        manuscript_path = Path(args.manuscript)
        if not manuscript_path.is_absolute():
            manuscript_path = book_dir / manuscript_path

    if not manuscript_path or not manuscript_path.exists():
        # 尝试自动查找
        manuscript_path = find_manuscript_file(book_dir, chapter)

    if not manuscript_path:
        result["ok"] = False
        result["error"] = f"未找到第{chapter}章正文文件。请通过 --manuscript 指定路径。"
        return result

    manuscript_text = read_text(manuscript_path)
    if not manuscript_text:
        result["ok"] = False
        result["error"] = f"正文文件为空：{manuscript_path}"
        return result

    result["manuscript_file"] = str(manuscript_path)
    result["manuscript_chars"] = len(manuscript_text)
    result["manuscript_chinese_chars"] = count_chinese_chars(manuscript_text)

    # Step 1: Beat 覆盖度检查
    coverage_report = _check_beat_coverage(beat_sheet, manuscript_text)
    result["coverage"] = coverage_report

    # Step 2: 字数分布检查
    char_report = _check_char_distribution_validation(beat_sheet, manuscript_text)
    result["char_distribution"] = char_report

    # Step 3: 情绪曲线连贯性检查
    emotion_report = _check_emotion_curve_validation(beat_sheet, manuscript_text)
    result["emotion_curve_check"] = emotion_report

    # 汇总
    all_warnings = (
        coverage_report.get("warnings", [])
        + char_report.get("warnings", [])
        + emotion_report.get("warnings", [])
    )
    total_coverage = coverage_report.get("coverage_ratio", 0.0)

    # 更新 Beat Sheet 中的 validation 字段
    beat_sheet["validation"] = {
        "total_coverage": total_coverage,
        "char_distribution": char_report.get("status", "unknown"),
        "emotion_flow": emotion_report.get("status", "unknown"),
        "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "manuscript_file": str(manuscript_path.relative_to(book_dir)) if manuscript_path.is_relative_to(book_dir) else manuscript_path.name,
        "beat_details": char_report.get("beat_details", []),
    }

    # 保存更新后的 Beat Sheet
    save_json(beat_sheet_path, beat_sheet)

    result["ok"] = True
    result["total_coverage"] = total_coverage
    result["warnings"] = all_warnings
    result["warning_count"] = len(all_warnings)
    result["updated_beat_sheet"] = str(beat_sheet_path)

    return result


def _check_beat_coverage(beat_sheet: Dict, manuscript_text: str) -> Dict[str, Any]:
    """检查每个 Beat 是否在正文中有对应内容。"""
    beats = beat_sheet.get("beats", [])
    total = len(beats)
    covered = 0
    warnings = []
    details = []

    for beat in beats:
        beat_id = beat["id"]
        keywords = _extract_match_keywords(beat)

        if not keywords:
            # 无关键词可匹配，标记为未验证
            details.append({
                "beat_id": beat_id,
                "status": "unverifiable",
                "message": "无匹配关键词",
            })
            continue

        matched = 0
        matched_keywords = []
        for kw in keywords:
            if kw in manuscript_text:
                matched += 1
                matched_keywords.append(kw)

        # 至少匹配一个关键词视为覆盖
        if matched > 0:
            covered += 1
            status = "covered"
        else:
            status = "missing"
            warnings.append(
                f"Beat {beat_id}「{beat['name']}」未在正文中找到对应内容 "
                f"（关键词：{', '.join(keywords[:3])}）"
            )

        details.append({
            "beat_id": beat_id,
            "status": status,
            "matched_keywords": matched_keywords,
            "total_keywords": len(keywords),
        })

    coverage_ratio = covered / total if total > 0 else 0.0

    return {
        "covered": covered,
        "total": total,
        "coverage_ratio": round(coverage_ratio, 2),
        "details": details,
        "warnings": warnings,
    }


def _extract_match_keywords(beat: Dict) -> List[str]:
    """从 Beat 信息中提取用于匹配正文的关键词。"""
    keywords = []
    seen = set()

    # 从 key_elements 提取
    for elem in beat.get("key_elements", []):
        if elem not in seen and len(elem) >= 2:
            keywords.append(elem)
            seen.add(elem)

    # 从 name 提取角色名/地名
    name = beat.get("name", "")
    for word in re.findall(r"[：:]([^\s：:]+)", name):
        word = word.strip()
        if word not in seen and len(word) >= 2:
            keywords.append(word)
            seen.add(word)

    # 从 outline_ref 提取
    outline_ref = beat.get("outline_ref", "")
    # 提取引号内的内容
    for quoted in re.findall(r"[「""](.+?)[」""]", outline_ref):
        if quoted not in seen and len(quoted) >= 2:
            keywords.append(quoted)
            seen.add(quoted)

    return keywords


def _check_char_distribution_validation(
    beat_sheet: Dict,
    manuscript_text: str,
) -> Dict[str, Any]:
    """检查各 Beat 实际字数 vs 目标字数。"""
    beats = beat_sheet.get("beats", [])
    warnings = []
    details = []

    total_target = sum(b["target_chars"] for b in beats)
    total_actual = count_chinese_chars(manuscript_text)

    # 按 Beat 顺序将正文分段，通过关键词定位
    beat_segments = _segment_manuscript_by_beats(beats, manuscript_text)

    for beat in beats:
        beat_id = beat["id"]
        target = beat["target_chars"]
        actual = beat_segments.get(beat_id, 0)

        if target > 0:
            deviation = (actual - target) / target
        else:
            deviation = 0.0

        detail = {
            "beat_id": beat_id,
            "name": beat.get("name", ""),
            "target_chars": target,
            "actual_chars": actual,
            "deviation": round(deviation, 2),
        }

        if abs(deviation) > 0.3:
            direction = "超出" if deviation > 0 else "不足"
            warnings.append(
                f"Beat {beat_id}「{beat.get('name', '')}」字数{direction} {abs(deviation)*100:.0f}% "
                f"（目标：{target}，实际：{actual}）"
            )
            detail["status"] = "warning"
        else:
            detail["status"] = "ok"

        details.append(detail)

    overall_deviation = (total_actual - total_target) / total_target if total_target > 0 else 0.0

    if abs(overall_deviation) > 0.2:
        status = "overall_warning"
    elif warnings:
        status = "partial_warning"
    else:
        status = "balanced"

    return {
        "total_target": total_target,
        "total_actual": total_actual,
        "overall_deviation": round(overall_deviation, 2),
        "status": status,
        "beat_details": details,
        "warnings": warnings,
    }


def _segment_manuscript_by_beats(
    beats: List[Dict],
    manuscript_text: str,
) -> Dict[int, int]:
    """将正文按 Beat 关键词分段，统计各段字数。

    使用简单的关键词定位 + 均分策略：
      1. 按 Beat 顺序在正文中查找关键词出现位置
      2. 两个相邻 Beat 关键词之间的文本 = 前一个 Beat 的内容
      3. 最后一个关键词到文末 = 最后一个 Beat 的内容
    """
    if not beats:
        return {}

    lines = manuscript_text.split("\n")
    n_lines = len(lines)

    # 为每个 Beat 找到最早出现的关键词位置（行号）
    beat_positions = {}  # beat_id -> first matching line number
    for beat in beats:
        keywords = _extract_match_keywords(beat)
        earliest_line = n_lines
        for kw in keywords:
            for i, line in enumerate(lines):
                if kw in line and i < earliest_line:
                    earliest_line = i
                    break
            if earliest_line < n_lines:
                break
        if earliest_line < n_lines:
            beat_positions[beat["id"]] = earliest_line

    if len(beat_positions) < 2:
        # 关键词匹配不足，均分
        total_chars = count_chinese_chars(manuscript_text)
        n = len(beats)
        per_beat = total_chars // n
        result = {}
        for i, beat in enumerate(beats):
            result[beat["id"]] = per_beat
        # 余数分配给最后一个
        if n > 0:
            result[beats[-1]["id"]] += total_chars - per_beat * n
        return result

    # 按行号排序
    sorted_positions = sorted(beat_positions.items(), key=lambda x: x[1])

    result = {}
    for idx, (beat_id, start_line) in enumerate(sorted_positions):
        if idx + 1 < len(sorted_positions):
            end_line = sorted_positions[idx + 1][1]
        else:
            end_line = n_lines

        segment = "\n".join(lines[start_line:end_line])
        result[beat_id] = count_chinese_chars(segment)

    # 未匹配到位置的 Beat 按均分估算
    matched_ids = set(result.keys())
    unmatched = [b for b in beats if b["id"] not in matched_ids]
    if unmatched:
        remaining_chars = sum(result.values())
        # 未匹配 Beat 分配 0，靠字数偏差标记
        for b in unmatched:
            result[b["id"]] = 0

    return result


def _check_emotion_curve_validation(
    beat_sheet: Dict,
    manuscript_text: str,
) -> Dict[str, Any]:
    """检查情绪曲线连贯性。"""
    emotion_curve = beat_sheet.get("emotion_curve", [])
    warnings = []

    if len(emotion_curve) <= 1:
        return {
            "status": "smooth",
            "curve": emotion_curve,
            "warnings": [],
        }

    calm = {"平静", "安宁", "温馨", "温暖", "温情"}
    intense = {"爆发", "震惊", "绝望", "愤怒", "恐惧", "杀意"}

    transitions = []
    for i in range(1, len(emotion_curve)):
        prev = emotion_curve[i - 1]
        curr = emotion_curve[i]
        is_abrupt = False

        if prev in calm and curr in intense:
            is_abrupt = True
            warnings.append(
                f"情绪突变：Beat {i} 从「{prev}」跳到「{curr}」，建议添加过渡"
            )
        elif prev in intense and curr in calm:
            is_abrupt = True
            warnings.append(
                f"情绪突变：Beat {i} 从「{prev}」跳到「{curr}」，建议添加缓冲"
            )

        transitions.append({
            "from": prev,
            "to": curr,
            "abrupt": is_abrupt,
        })

    # 检查正文中的情绪标记是否与 Beat Sheet 一致
    text_emotions = extract_emotion_from_text(manuscript_text)
    # 只做信息性报告，不作为校验失败条件
    detected_set = set(text_emotions)
    expected_set = set(emotion_curve)
    missing_in_text = expected_set - detected_set

    if missing_in_text:
        warnings.append(
            f"情绪「{', '.join(missing_in_text)}」在 Beat Sheet 中标注但正文中未明显体现（仅供参考）"
        )

    status = "smooth" if not warnings else ("acceptable" if len(warnings) <= 2 else "abrupt")

    return {
        "status": status,
        "curve": emotion_curve,
        "transitions": transitions,
        "text_detected_emotions": text_emotions,
        "warnings": warnings,
    }


# =========================================================
# CLI
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="Beat Sheet（分镜表）生成器 — 将章节拆解为独立叙事单元",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/beat_sheet_generator.py generate "{书名目录}" --chapter 37
  python scripts/beat_sheet_generator.py expand "{书名目录}" --chapter 37 --beat 2
  python scripts/beat_sheet_generator.py validate "{书名目录}" --chapter 37 --manuscript "正文/第037章_标题.md"
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # generate
    p_gen = sub.add_parser("generate", help="从章纲生成 Beat Sheet")
    p_gen.add_argument("book_dir", help="书籍工程目录")
    p_gen.add_argument("--chapter", type=int, required=True, help="章节号")
    p_gen.add_argument("--json", action="store_true", help="输出 JSON 格式")

    # expand
    p_exp = sub.add_parser("expand", help="为指定 Beat 生成五维度扩写提示")
    p_exp.add_argument("book_dir", help="书籍工程目录")
    p_exp.add_argument("--chapter", type=int, required=True, help="章节号")
    p_exp.add_argument("--beat", type=int, required=True, help="Beat 编号")
    p_exp.add_argument("--output", help="输出文件路径（默认输出到终端）")

    # validate
    p_val = sub.add_parser("validate", help="校验合成稿与 Beat Sheet 的一致性")
    p_val.add_argument("book_dir", help="书籍工程目录")
    p_val.add_argument("--chapter", type=int, required=True, help="章节号")
    p_val.add_argument("--manuscript", help="合成稿文件路径（默认自动查找）")
    p_val.add_argument("--json", action="store_true", help="输出 JSON 格式")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    book_dir = find_book_dir(args.book_dir)
    if not book_dir:
        print("错误：未找到书籍工程目录（需包含 大纲/ 和 追踪/ 子目录）", file=sys.stderr)
        sys.exit(1)

    # ---- generate ----
    if args.command == "generate":
        result = cmd_generate(book_dir, args.chapter, args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not result.get("ok"):
                print(f"错误：{result.get('error', '生成失败')}", file=sys.stderr)
                sys.exit(1)
            bs = result["beat_sheet"]
            print(f"=== Beat Sheet 已生成 — 第{bs['chapter']}章「{bs['title']}」===")
            print(f"节奏档位：{bs.get('pace_level', '?')}")
            print(f"总 Beat 数：{bs['total_beats']}")
            print(f"目标字数：{bs['target_chars']}")
            print(f"情绪曲线：{' → '.join(bs['emotion_curve'])}")
            print(f"字数分布：{bs['validation']['char_distribution']}")
            print(f"情绪连贯：{bs['validation']['emotion_flow']}")
            print()
            for beat in bs["beats"]:
                print(f"  Beat {beat['id']}：{beat['name']}")
                print(f"    类型：{beat['scene_type']} | 情绪：{beat['emotion']} | 字数：{beat['target_chars']}")
                if beat.get("key_elements"):
                    print(f"    元素：{', '.join(beat['key_elements'])}")
                if beat.get("hook"):
                    print(f"    钩子：{beat['hook']}")
            print()
            print(f"输出文件：{result['output_file']}")

    # ---- expand ----
    elif args.command == "expand":
        result = cmd_expand(book_dir, args.chapter, args.beat, args)
        if not result.get("ok"):
            print(f"错误：{result.get('error', '扩写失败')}", file=sys.stderr)
            sys.exit(1)
        prompt = result["prompt"]
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(prompt, encoding="utf-8")
            print(f"扩写提示已写入 {out_path}")
        else:
            print(prompt)

    # ---- validate ----
    elif args.command == "validate":
        result = cmd_validate(book_dir, args.chapter, args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not result.get("ok"):
                print(f"错误：{result.get('error', '校验失败')}", file=sys.stderr)
                sys.exit(1)
            print(f"=== Beat Sheet 校验 — 第{args.chapter}章 ===")
            print(f"正文文件：{result.get('manuscript_file', '?')}")
            print(f"正文字符数：{result.get('manuscript_chars', 0)}（中文 {result.get('manuscript_chinese_chars', 0)}）")
            print()

            # 覆盖度
            cov = result["coverage"]
            print(f"Beat 覆盖度：{cov['covered']}/{cov['total']} ({cov['coverage_ratio']*100:.0f}%)")

            # 字数分布
            char_dist = result["char_distribution"]
            print(f"字数偏差：总目标 {char_dist['total_target']}，总实际 {char_dist['total_actual']}（{char_dist['overall_deviation']*100:+.0f}%）")
            for detail in char_dist.get("beat_details", []):
                status_icon = "OK" if detail["status"] == "ok" else "!!"
                print(f"  [{status_icon}] Beat {detail['beat_id']}：目标 {detail['target_chars']} / 实际 {detail['actual_chars']}（{detail['deviation']*100:+.0f}%）")

            # 情绪曲线
            emotion_check = result["emotion_curve_check"]
            print(f"情绪连贯性：{emotion_check['status']}")
            for idx, trans in enumerate(emotion_check.get("transitions", []), start=1):
                if trans["abrupt"]:
                    print(f"  !! Beat {idx + 1}：{trans['from']} → {trans['to']}（突变）")

            # 警告
            if result["warnings"]:
                print(f"\n警告（{result['warning_count']} 条）：")
                for w in result["warnings"]:
                    print(f"  - {w}")
            else:
                print("\n校验通过，无警告。")

            print(f"\nBeat Sheet 已更新：{result.get('updated_beat_sheet', '')}")


if __name__ == "__main__":
    main()
