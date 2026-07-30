#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""context_manager.py — 长篇上下文管理器 v1.1（纯标准库，无第三方依赖）。

解决百万字长篇写作中的"上下文爆炸"问题。不是把所有文件塞进上下文，
而是智能选取"不知道就会写错"的最小信息集。

参考 novel-creator-skill 的 long_term_context_manager.py 设计，
但改为纯标准库实现，且集成本 skill 的四目录文件系统。

核心功能：
  1. compress — 压缩章节摘要（多章合并为回顾段）
  2. select — 为指定章节选取最小必读上下文（v1.1: 支持动态阶段）
  3. budget — 上下文预算管理（字数上限分配）
  4. report — 生成上下文使用报告
  5. stage — 查看当前章节所处阶段与预算策略（v1.1 新增）

v1.1 新增：动态上下文窗口
  - 根据全书进度（开篇/发展/深水/收束）自动切换预算比例
  - 收束阶段自动加载终局储备（里程碑组件）
  - 新增 stage 子命令，查看阶段判定与策略说明

数据来源：书籍工程的 追踪/、设定/、大纲/ 目录。
输出：结构化的上下文包（Markdown 格式，可直接注入写作提示）。

用法：
  python3 scripts/context_manager.py select "{书名目录}" --chapter 37
  python3 scripts/context_manager.py compress "{书名目录}" --from 1 --to 20
  python3 scripts/context_manager.py budget "{书名目录}" --chapter 37 --max-chars 8000
  python3 scripts/context_manager.py stage "{书名目录}" --chapter 37
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =========================================================
# 从 config.py 导入（带 fallback）
# =========================================================
try:
    from config import CONTEXT_STAGES, DEFAULT_MAX_CONTEXT_CHARS, DEFAULT_RECENT_CHAPTERS
except ImportError:
    CONTEXT_STAGES = None  # 使用内置默认
    DEFAULT_MAX_CONTEXT_CHARS = 8000
    DEFAULT_RECENT_CHAPTERS = 10

# =========================================================
# 常量
# =========================================================

VERSION = "1.1.0"

# 上下文预算默认值（字符数）
DEFAULT_MAX_CHARS = 8000

# 各组件预算分配比例（静态默认值，无动态阶段时使用）
BUDGET_RATIOS = {
    "chapter_brief": 0.15,      # 章纲
    "character_cards": 0.20,    # 人物卡
    "recent_summaries": 0.25,   # 近章摘要
    "foreshadowing": 0.15,      # 伏笔台账
    "rhythm_quota": 0.05,       # 节奏配额
    "outline_anchor": 0.10,     # 大纲锚点
    "style_anchor": 0.05,       # 文风锚
    "entity_context": 0.05,     # 实体上下文
}

# 内置动态阶段配置（与 config.py CONTEXT_STAGES 保持一致）
_FALLBACK_CONTEXT_STAGES = {
    "opening": {
        "range": (0.0, 0.05),
        "ratios": {
            "chapter_brief": 0.20,
            "character_cards": 0.30,
            "recent_summaries": 0.15,
            "foreshadowing": 0.10,
            "style_anchor": 0.15,
            "rhythm_quota": 0.10,
        },
    },
    "development": {
        "range": (0.05, 0.30),
        "ratios": {
            "chapter_brief": 0.15,
            "character_cards": 0.20,
            "recent_summaries": 0.25,
            "foreshadowing": 0.15,
            "style_anchor": 0.10,
            "rhythm_quota": 0.15,
        },
    },
    "deepwater": {
        "range": (0.30, 0.75),
        "ratios": {
            "chapter_brief": 0.12,
            "character_cards": 0.15,
            "recent_summaries": 0.35,
            "foreshadowing": 0.20,
            "style_anchor": 0.08,
            "rhythm_quota": 0.10,
        },
    },
    "finale": {
        "range": (0.75, 1.0),
        "ratios": {
            "chapter_brief": 0.10,
            "character_cards": 0.10,
            "recent_summaries": 0.20,
            "foreshadowing": 0.35,
            "style_anchor": 0.05,
            "rhythm_quota": 0.10,
            "milestone": 0.10,       # 里程碑（终局储备）
        },
    },
}

# 阶段中文名与策略说明
STAGE_LABELS = {
    "opening": "开篇",
    "development": "发展",
    "deepwater": "深水",
    "finale": "收束",
}

STAGE_STRATEGIES = {
    "opening": (
        "开篇阶段：重点建立角色形象与世界观基调。"
        "加大人物卡和文风锚比例，近章摘要较少。"
        "确保前几章的一致性，为全书奠定基调。"
    ),
    "development": (
        "发展阶段：进入主线，伏笔开始铺设。"
        "均衡分配各项组件，节奏配额适当提升。"
        "关注角色关系发展与情节推进。"
    ),
    "deepwater": (
        "深水阶段：情节复杂度最高，伏笔大量堆积。"
        "近章摘要权重最大，伏笔追踪比例提高。"
        "需要精确追踪角色状态和伏笔线索。"
    ),
    "finale": (
        "收束阶段：全力回收伏笔，推进结局。"
        "伏笔信息量最大，额外加载终局储备（里程碑组件）。"
        "从总纲中提取终局相关段落辅助收束。"
    ),
}

# 近章摘要默认数量
DEFAULT_RECENT_CHAPTERS = 10

# 压缩阈值（超过此字数的摘要需压缩）
COMPRESS_THRESHOLD = 500

# =========================================================
# 动态阶段判定（v1.1 新增）
# =========================================================

def _estimate_total_chapters(book_dir: Path) -> Optional[int]:
    """估算全书计划章数。

    优先从 大纲/总纲.md 中提取「第X卷」的总章数线索，
    其次统计 大纲/ 目录下章纲文件数量作为估算值。

    Returns:
        估算的总章数，无法推算时返回 None。
    """
    outline_dir = book_dir / "大纲"

    # 方法1：读总纲，查找「第X卷」以及卷内章数信息
    master_outline = outline_dir / "总纲.md"
    if master_outline.exists():
        content = read_file_safe(master_outline)
        # 查找"全书X章"、"共X章"、"总计X章"等表述
        total_match = re.search(r"(?:全书|共|总计|计划).*?(\d+)\s*章", content)
        if total_match:
            try:
                return int(total_match.group(1))
            except ValueError:
                pass

        # 查找「第X卷」中的章节分配信息，如"第X卷：第n-m章"
        volume_chapters = re.findall(r"第[一二三四五六七八九十百\d]+卷.*?第(\d+).*?第(\d+)\s*章", content)
        if volume_chapters:
            max_ch = 0
            for start, end in volume_chapters:
                try:
                    max_ch = max(max_ch, int(start), int(end))
                except ValueError:
                    continue
            if max_ch > 0:
                return max_ch

        # 统计卷数，按每卷平均章数估算
        volumes = re.findall(r"第[一二三四五六七八九十百\d]+卷", content)
        if len(volumes) > 0:
            # 看总纲中是否提到每卷章数
            chapters_per_volume = re.findall(r"(?:每卷|卷均).*?(\d+)\s*章", content)
            if chapters_per_volume:
                try:
                    return len(volumes) * int(chapters_per_volume[0])
                except ValueError:
                    pass
            # 默认每卷20章估算
            return len(volumes) * 20

    # 方法2：统计大纲目录下章纲文件数量
    if outline_dir.exists():
        chapter_files = list(outline_dir.glob("章纲_*.md"))
        if chapter_files:
            return len(chapter_files)

    return None


def determine_stage(book_dir: Path, target_chapter: int) -> str:
    """根据目标章节与全书进度判定当前阶段。

    Args:
        book_dir: 书籍工程目录。
        target_chapter: 目标章节号。

    Returns:
        阶段名：opening / development / deepwater / finale。
        无法推算总章数时默认返回 "development"。
    """
    total = _estimate_total_chapters(book_dir)
    if total is None or total <= 0:
        return "development"

    ratio = target_chapter / total
    stages = CONTEXT_STAGES or _FALLBACK_CONTEXT_STAGES

    for stage_name, stage_config in stages.items():
        low, high = stage_config["range"]
        if low <= ratio < high:
            return stage_name

    # ratio == 1.0 或溢出时归入 finale
    if ratio >= 0.75:
        return "finale"
    return "development"


# =========================================================
# 动态预算比例（v1.1 新增）
# =========================================================

def get_dynamic_budget_ratios(stage: str) -> Dict[str, float]:
    """根据阶段获取动态预算比例。

    Args:
        stage: 阶段名（opening/development/deepwater/finale）。

    Returns:
        组件名到比例的字典。如果阶段无效，返回静态默认值 BUDGET_RATIOS。
    """
    stages = CONTEXT_STAGES or _FALLBACK_CONTEXT_STAGES
    if stage in stages and "ratios" in stages[stage]:
        return dict(stages[stage]["ratios"])
    return dict(BUDGET_RATIOS)


# =========================================================
# 里程碑提取（v1.1 新增：finale 阶段终局储备）
# =========================================================

def extract_milestone_content(book_dir: Path) -> str:
    """从总纲中提取与终局相关的段落。

    搜索包含「终局」「结局」「最终」「大结局」关键词的段落。

    Returns:
        匹配的段落文本，无匹配时返回空字符串。
    """
    master_outline = book_dir / "大纲" / "总纲.md"
    if not master_outline.exists():
        return ""

    content = read_file_safe(master_outline)
    if not content:
        return ""

    milestone_keywords = ["终局", "结局", "最终", "大结局"]
    matched_paragraphs = []

    # 按空行分段
    paragraphs = re.split(r"\n\s*\n", content)
    for para in paragraphs:
        for keyword in milestone_keywords:
            if keyword in para:
                matched_paragraphs.append(para.strip())
                break

    return "\n\n".join(matched_paragraphs)


# =========================================================
# 文件路径工具
# =========================================================

def find_book_dir(path: str) -> Optional[Path]:
    """查找书籍工程目录"""
    p = Path(path)
    if not p.exists():
        print(f"错误：路径不存在 {path}", file=sys.stderr)
        return None
    # 检查是否是书籍工程（含 追踪/ 和 大纲/）
    if (p / "追踪").exists() and (p / "大纲").exists():
        return p
    # 检查子目录
    for child in p.iterdir():
        if child.is_dir() and (child / "追踪").exists():
            return child
    return None


def read_file_safe(path: Path) -> str:
    """安全读取文件"""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def count_chars(text: str) -> int:
    """统计非空白字符数"""
    return len(re.sub(r"\s", "", text))


def truncate_text(text: str, max_chars: int, suffix: str = "...") -> str:
    """截断文本到指定字数"""
    chars = count_chars(text)
    if chars <= max_chars:
        return text
    # 按字符截断（保留完整行）
    lines = text.split("\n")
    result = []
    current = 0
    for line in lines:
        line_chars = count_chars(line)
        if current + line_chars > max_chars:
            remaining = max_chars - current
            if remaining > 20:
                result.append(line[:remaining] + suffix)
            break
        result.append(line)
        current += line_chars
    return "\n".join(result)


# =========================================================
# 章节摘要解析
# =========================================================

def parse_chapter_summaries(book_dir: Path) -> List[Dict[str, Any]]:
    """解析章节摘要文件"""
    summary_file = book_dir / "追踪" / "章节摘要.md"
    if not summary_file.exists():
        return []

    content = read_file_safe(summary_file)
    chapters = []
    current_chapter = None

    for line in content.split("\n"):
        # 匹配章节标题
        match = re.match(r"##\s*第(\d+)章", line)
        if match:
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = {
                "chapter": int(match.group(1)),
                "raw": line + "\n",
                "char_count": 0,
            }
        elif current_chapter:
            current_chapter["raw"] += line + "\n"

    if current_chapter:
        chapters.append(current_chapter)

    # 计算字数
    for ch in chapters:
        ch["char_count"] = count_chars(ch["raw"])

    return chapters


def get_recent_summaries(chapters: List[Dict], target_chapter: int, count: int = 10) -> List[Dict]:
    """获取目标章节前N章的摘要"""
    recent = [ch for ch in chapters if ch["chapter"] < target_chapter]
    recent.sort(key=lambda x: x["chapter"], reverse=True)
    return recent[:count]


def compress_summaries(chapters: List[Dict], from_ch: int, to_ch: int) -> str:
    """压缩多章摘要为回顾段"""
    target = [ch for ch in chapters if from_ch <= ch["chapter"] <= to_ch]
    target.sort(key=lambda x: x["chapter"])

    if not target:
        return f"第{from_ch}-{to_ch}章无摘要数据。"

    lines = [f"## 第{from_ch}-{to_ch}章 回顾压缩"]
    lines.append(f"(原始摘要 {len(target)} 章，共 {sum(c['char_count'] for c in target)} 字 → 压缩为回顾段)\n")

    for ch in target:
        # 提取关键信息（标题行 + 关键实体 + 一句话摘要）
        raw = ch["raw"]
        # 取标题行
        title_line = raw.split("\n")[0] if raw else f"第{ch['chapter']}章"
        # 尝试提取一句话摘要
        one_line = ""
        for line in raw.split("\n"):
            if "一句话" in line or "摘要" in line or "概要" in line:
                one_line = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                break
        if one_line:
            lines.append(f"- {title_line}：{one_line}")
        else:
            # 截取前100字
            compressed = truncate_text(raw, 100)
            lines.append(f"- {title_line}：{compressed}")

    return "\n".join(lines)


# =========================================================
# 上下文选取
# =========================================================

def select_context(book_dir: Path, target_chapter: int, max_chars: int = DEFAULT_MAX_CHARS,
                   stage: Optional[str] = None) -> Dict[str, Any]:
    """为目标章节选取最小必读上下文。

    v1.1 增强：
      - 新增 stage 参数，若为 None 则自动判定当前阶段
      - 根据阶段使用动态预算比例
      - finale 阶段额外加载终局储备（milestone 组件）
      - 返回结果中包含 stage 和 budget_ratios_used 字段

    Args:
        book_dir: 书籍工程目录。
        target_chapter: 目标章节号。
        max_chars: 上下文预算上限（字符数）。
        stage: 阶段名，None 表示自动判定。

    Returns:
        上下文包字典。
    """

    # v1.1: 自动判定阶段
    if stage is None:
        stage = determine_stage(book_dir, target_chapter)

    # v1.1: 按阶段获取动态预算比例
    budget_ratios_used = get_dynamic_budget_ratios(stage)

    context = {
        "version": VERSION,
        "book_dir": str(book_dir),
        "target_chapter": target_chapter,
        "max_chars": max_chars,
        "stage": stage,                        # v1.1 新增
        "budget_ratios_used": budget_ratios_used,  # v1.1 新增
        "components": {},
        "total_chars": 0,
        "budget_used": 0,
    }

    budget = {k: int(max_chars * v) for k, v in budget_ratios_used.items()}

    # 1. 章纲
    chapter_outline = book_dir / "大纲" / f"章纲_第{target_chapter:03d}章.md"
    if not chapter_outline.exists():
        # 尝试不带前导零
        chapter_outline = book_dir / "大纲" / f"章纲_第{target_chapter}章.md"
    if chapter_outline.exists() and "chapter_brief" in budget:
        content = read_file_safe(chapter_outline)
        content = truncate_text(content, budget["chapter_brief"])
        context["components"]["chapter_brief"] = {
            "source": str(chapter_outline.name),
            "chars": count_chars(content),
            "content": content,
        }

    # 2. 人物卡（从章纲中提取出场角色）
    chapter_content = context["components"].get("chapter_brief", {}).get("content", "")
    mentioned_chars = extract_mentioned_characters(chapter_content, book_dir)

    char_cards = []
    char_budget = budget.get("character_cards", 0)
    char_chars = 0
    for char_name in mentioned_chars:
        if char_chars >= char_budget:
            break
        card_path = book_dir / "设定" / "角色" / f"{char_name}.md"
        if card_path.exists():
            card_content = read_file_safe(card_path)
            # 只取人物卡的核心部分（前30行）
            card_content = "\n".join(card_content.split("\n")[:30])
            card_content = truncate_text(card_content, char_budget // max(len(mentioned_chars), 1))
            char_cards.append({"name": char_name, "content": card_content, "chars": count_chars(card_content)})
            char_chars += count_chars(card_content)
    context["components"]["character_cards"] = {
        "count": len(char_cards),
        "chars": char_chars,
        "characters": char_cards,
    }

    # 3. 近章摘要
    all_summaries = parse_chapter_summaries(book_dir)
    recent = get_recent_summaries(all_summaries, target_chapter, DEFAULT_RECENT_CHAPTERS)

    recent_budget = budget.get("recent_summaries", 0)
    recent_chars = 0
    recent_content = []
    for ch in recent:
        if recent_chars + ch["char_count"] > recent_budget:
            # 压缩
            compressed = truncate_text(ch["raw"], recent_budget - recent_chars)
            recent_content.append(compressed)
            recent_chars += count_chars(compressed)
            break
        recent_content.append(ch["raw"])
        recent_chars += ch["char_count"]

    context["components"]["recent_summaries"] = {
        "count": len(recent),
        "chars": recent_chars,
        "chapters": [ch["chapter"] for ch in recent],
        "content": "\n---\n".join(recent_content),
    }

    # 4. 伏笔台账
    foreshadow_file = book_dir / "追踪" / "伏笔台账.md"
    if foreshadow_file.exists() and "foreshadowing" in budget:
        foreshadow_content = read_file_safe(foreshadow_file)
        # 只提取未回收和即将到期的伏笔
        active_foreshadows = extract_active_foreshadows(foreshadow_content, target_chapter)
        active_foreshadows = truncate_text(active_foreshadows, budget["foreshadowing"])
        context["components"]["foreshadowing"] = {
            "source": "伏笔台账.md",
            "chars": count_chars(active_foreshadows),
            "content": active_foreshadows,
        }

    # 5. 节奏配额
    rhythm_file = book_dir / "追踪" / "节奏配额.md"
    if rhythm_file.exists() and "rhythm_quota" in budget:
        rhythm_content = read_file_safe(rhythm_file)
        # 只取最近几章的配额记录
        rhythm_lines = rhythm_content.split("\n")
        recent_rhythm = []
        for line in rhythm_lines:
            if re.search(r"第\d+章", line):
                recent_rhythm.append(line)
        recent_rhythm_text = "\n".join(recent_rhythm[-10:])
        recent_rhythm_text = truncate_text(recent_rhythm_text, budget["rhythm_quota"])
        context["components"]["rhythm_quota"] = {
            "source": "节奏配额.md",
            "chars": count_chars(recent_rhythm_text),
            "content": recent_rhythm_text,
        }

    # 6. 大纲锚点（如果有 outline_anchors.json）
    anchor_file = book_dir / "大纲" / "outline_anchors.json"
    if anchor_file.exists() and "outline_anchor" in budget:
        try:
            anchor_data = json.loads(read_file_safe(anchor_file))
            anchor_text = json.dumps(anchor_data, ensure_ascii=False, indent=2)
            anchor_text = truncate_text(anchor_text, budget["outline_anchor"])
            context["components"]["outline_anchor"] = {
                "source": "outline_anchors.json",
                "chars": count_chars(anchor_text),
                "content": anchor_text,
            }
        except json.JSONDecodeError:
            pass

    # 7. 文风锚
    style_file = book_dir / "设定" / "文风锚.md"
    if style_file.exists() and "style_anchor" in budget:
        style_content = read_file_safe(style_file)
        style_content = truncate_text(style_content, budget["style_anchor"])
        context["components"]["style_anchor"] = {
            "source": "文风锚.md",
            "chars": count_chars(style_content),
            "content": style_content,
        }

    # 8. 实体上下文（BM25检索结果，如果有）
    entity_index_file = book_dir / "追踪" / "entity_index.json"
    if entity_index_file.exists() and "entity_context" in budget:
        try:
            entity_data = json.loads(read_file_safe(entity_index_file))
            # 提取与目标章节相关的实体
            relevant = {}
            for entity, chapters in entity_data.items():
                if isinstance(chapters, list) and target_chapter in chapters:
                    relevant[entity] = chapters[-5:]  # 最近5章
            entity_text = json.dumps(relevant, ensure_ascii=False, indent=2)
            entity_text = truncate_text(entity_text, budget["entity_context"])
            context["components"]["entity_context"] = {
                "source": "entity_index.json",
                "chars": count_chars(entity_text),
                "content": entity_text,
            }
        except (json.JSONDecodeError, TypeError):
            pass

    # 9. 里程碑（v1.1 新增：finale 阶段加载终局储备）
    if stage == "finale" and "milestone" in budget:
        milestone_budget = budget["milestone"]
        milestone_text = extract_milestone_content(book_dir)
        if milestone_text:
            milestone_text = truncate_text(milestone_text, milestone_budget)
            context["components"]["milestone"] = {
                "source": "总纲.md（终局储备）",
                "chars": count_chars(milestone_text),
                "content": milestone_text,
            }

    # 计算总字数
    total = sum(comp.get("chars", 0) for comp in context["components"].values())
    context["total_chars"] = total
    context["budget_used"] = round(total / max_chars * 100, 1) if max_chars > 0 else 0

    return context


def extract_mentioned_characters(chapter_content: str, book_dir: Path) -> List[str]:
    """从章纲内容中提取提及的角色名"""
    # 方法1：从设定/角色/ 目录获取所有角色名
    char_dir = book_dir / "设定" / "角色"
    known_chars = []
    if char_dir.exists():
        for f in char_dir.glob("*.md"):
            known_chars.append(f.stem)

    # 方法2：在章纲中搜索角色名
    mentioned = []
    for name in known_chars:
        if name in chapter_content:
            mentioned.append(name)

    # 方法3：如果没有已知角色，尝试从章纲中提取人名（简单启发式）
    if not mentioned:
        # 查找"角色："或"人物："后面的内容
        for line in chapter_content.split("\n"):
            if "角色" in line or "人物" in line or "出场" in line:
                # 提取冒号后的内容
                parts = line.split("：") if "：" in line else line.split(":")
                if len(parts) > 1:
                    names = [n.strip().strip("，,、 ") for n in parts[1].split("，")]
                    mentioned.extend([n for n in names if n and len(n) <= 5])

    return mentioned[:5]  # 最多5个角色


def extract_active_foreshadows(foreshadow_content: str, target_chapter: int) -> str:
    """提取活跃伏笔（未回收且回收窗口包含目标章节）"""
    lines = foreshadow_content.split("\n")
    active_lines = []
    for line in lines:
        # 检查是否是未回收伏笔行（含 🟡 或 🔴 或 待回收）
        if "🟡" in line or "🔴" in line or "待回收" in line or "未回收" in line:
            active_lines.append(line)
        # 检查回收窗口
        window_match = re.search(r"回收.*?第(\d+).*?第(\d+)章", line)
        if window_match:
            start_ch = int(window_match.group(1))
            end_ch = int(window_match.group(2))
            if start_ch <= target_chapter <= end_ch:
                if line not in active_lines:
                    active_lines.append(line)

    if not active_lines:
        # 如果没找到活跃伏笔，返回前20行
        return "\n".join(lines[:20])
    return "\n".join(active_lines)


# =========================================================
# 上下文报告生成
# =========================================================

def generate_context_report(context: Dict[str, Any]) -> str:
    """生成人类可读的上下文报告"""
    lines = []
    lines.append("# 写作上下文包")
    lines.append(f"\n生成引擎：context_manager.py v{VERSION}")
    lines.append(f"目标章节：第{context['target_chapter']}章")
    # v1.1: 显示当前阶段
    stage = context.get("stage", "")
    if stage:
        stage_label = STAGE_LABELS.get(stage, stage)
        lines.append(f"当前阶段：{stage_label} ({stage})")
    lines.append(f"预算上限：{context['max_chars']} 字符")
    lines.append(f"实际使用：{context['total_chars']} 字符 ({context['budget_used']}%)")

    # v1.1: 使用实际使用的预算比例
    used_ratios = context.get("budget_ratios_used", BUDGET_RATIOS)
    lines.append(f"\n## 组件清单")
    for name, comp in context["components"].items():
        chars = comp.get("chars", 0)
        budget_pct = used_ratios.get(name, 0) * 100
        lines.append(f"- **{name}**：{chars} 字 (预算 {budget_pct:.0f}%) — 来源: {comp.get('source', 'N/A')}")

    lines.append(f"\n## 上下文内容")
    for name, comp in context["components"].items():
        lines.append(f"\n### [{name}]")
        content = comp.get("content", "")
        if name == "character_cards":
            for char in comp.get("characters", []):
                lines.append(f"\n**{char['name']}**:")
                lines.append(char["content"])
        else:
            lines.append(content)

    return "\n".join(lines)


def generate_brief_context(context: Dict[str, Any]) -> str:
    """生成精简版上下文（本节速记格式）"""
    lines = []
    lines.append(f"# 本节速记 — 第{context['target_chapter']}章")
    lines.append(f"(上下文预算 {context['budget_used']}%)")

    # v1.1: 标注当前阶段
    stage = context.get("stage", "")
    if stage:
        stage_label = STAGE_LABELS.get(stage, stage)
        lines[1] = f"(上下文预算 {context['budget_used']}%，阶段：{stage_label})"

    # 章纲要点
    brief = context["components"].get("chapter_brief", {}).get("content", "")
    if brief:
        lines.append("\n## 章纲要点")
        lines.append(truncate_text(brief, 500))

    # 出场角色
    chars = context["components"].get("character_cards", {})
    if chars.get("count", 0) > 0:
        lines.append(f"\n## 出场角色 ({chars['count']}人)")
        for char in chars.get("characters", []):
            lines.append(f"- **{char['name']}**：{truncate_text(char['content'], 200)}")

    # 近章回顾
    recent = context["components"].get("recent_summaries", {})
    if recent.get("count", 0) > 0:
        lines.append(f"\n## 近章回顾 ({recent['count']}章)")
        lines.append(truncate_text(recent.get("content", ""), 800))

    # 活跃伏笔
    foreshadow = context["components"].get("foreshadowing", {}).get("content", "")
    if foreshadow:
        lines.append("\n## 待处理伏笔")
        lines.append(truncate_text(foreshadow, 400))

    # 节奏约束
    rhythm = context["components"].get("rhythm_quota", {}).get("content", "")
    if rhythm:
        lines.append("\n## 节奏约束")
        lines.append(truncate_text(rhythm, 200))

    return "\n".join(lines)


# =========================================================
# CLI
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="长篇上下文管理器 — 智能选取最小必读上下文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # select 命令
    p_select = sub.add_parser("select", help="为目标章节选取上下文")
    p_select.add_argument("book_dir", help="书籍工程目录")
    p_select.add_argument("--chapter", type=int, required=True, help="目标章节号")
    p_select.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="上下文预算上限")
    p_select.add_argument("--brief", action="store_true", help="输出精简版（本节速记格式）")
    p_select.add_argument("--json", action="store_true", help="输出 JSON 格式")
    p_select.add_argument("--output", help="输出文件路径")
    p_select.add_argument("--stage", help="手动指定阶段（opening/development/deepwater/finale），默认自动判定")

    # compress 命令
    p_compress = sub.add_parser("compress", help="压缩多章摘要为回顾段")
    p_compress.add_argument("book_dir", help="书籍工程目录")
    p_compress.add_argument("--from", dest="from_ch", type=int, required=True, help="起始章号")
    p_compress.add_argument("--to", dest="to_ch", type=int, required=True, help="结束章号")
    p_compress.add_argument("--output", help="输出文件路径")

    # budget 命令
    p_budget = sub.add_parser("budget", help="查看上下文预算分配")
    p_budget.add_argument("book_dir", help="书籍工程目录")
    p_budget.add_argument("--chapter", type=int, required=True, help="目标章节号")
    p_budget.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="上下文预算上限")

    # stage 命令（v1.1 新增）
    p_stage = sub.add_parser("stage", help="查看当前章节所处阶段与预算策略")
    p_stage.add_argument("book_dir", help="书籍工程目录")
    p_stage.add_argument("--chapter", type=int, required=True, help="目标章节号")

    args = parser.parse_args()

    if args.command == "select":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程目录 {args.book_dir}", file=sys.stderr)
            sys.exit(1)

        # v1.1: 支持手动指定阶段
        stage = args.stage if args.stage else None
        context = select_context(book_dir, args.chapter, args.max_chars, stage=stage)

        if args.json:
            output = json.dumps(context, ensure_ascii=False, indent=2)
        elif args.brief:
            output = generate_brief_context(context)
        else:
            output = generate_context_report(context)

        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"上下文包已写入 {args.output}")
        else:
            print(output)

    elif args.command == "compress":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程目录", file=sys.stderr)
            sys.exit(1)

        all_summaries = parse_chapter_summaries(book_dir)
        result = compress_summaries(all_summaries, args.from_ch, args.to_ch)

        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"压缩摘要已写入 {args.output}")
        else:
            print(result)

    elif args.command == "budget":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程目录", file=sys.stderr)
            sys.exit(1)

        context = select_context(book_dir, args.chapter, args.max_chars)

        print(f"上下文预算分配（第{args.chapter}章，上限 {args.max_chars} 字符）")
        print(f"{'组件':<25} {'预算':>8} {'实际':>8} {'使用率':>8}")
        print("-" * 55)
        # v1.1: 使用实际使用的预算比例
        used_ratios = context.get("budget_ratios_used", BUDGET_RATIOS)
        for name, comp in context["components"].items():
            budget_pct = used_ratios.get(name, 0) * 100
            actual = comp.get("chars", 0)
            actual_pct = (actual / args.max_chars * 100) if args.max_chars > 0 else 0
            print(f"{name:<25} {budget_pct:>7.0f}% {actual:>8} {actual_pct:>7.1f}%")
        print("-" * 55)
        print(f"{'总计':<25} {'100%':>8} {context['total_chars']:>8} {context['budget_used']:>7.1f}%")

    elif args.command == "stage":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程目录 {args.book_dir}", file=sys.stderr)
            sys.exit(1)

        stage = determine_stage(book_dir, args.chapter)
        stage_label = STAGE_LABELS.get(stage, stage)
        ratios = get_dynamic_budget_ratios(stage)
        total = _estimate_total_chapters(book_dir)

        print(f"阶段判定结果（第{args.chapter}章）")
        print(f"{'=' * 50}")
        print(f"  当前阶段：{stage_label} ({stage})")
        if total:
            progress = args.chapter / total * 100
            print(f"  全书进度：{args.chapter}/{total} 章 ({progress:.1f}%)")
        else:
            print(f"  全书进度：无法推算总章数（使用默认阶段）")
        print(f"{'=' * 50}")

        print(f"\n预算比例分配：")
        for name, ratio in sorted(ratios.items(), key=lambda x: -x[1]):
            print(f"  {name:<25} {ratio:>6.0%}")

        print(f"\n推荐策略：")
        print(f"  {STAGE_STRATEGIES.get(stage, '无策略说明。')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
