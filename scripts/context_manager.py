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
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

from common import SUMMARY_FIELD_NAMES, extract_summary_fields

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
DEFAULT_MAX_CHARS = DEFAULT_MAX_CONTEXT_CHARS

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

# 内置动态阶段配置（与 config.py CONTEXT_STAGES 保持一致；v7.0 补全组件）
_FALLBACK_CONTEXT_STAGES = {
    "opening": {
        "range": (0.0, 0.05),
        "ratios": {
            "chapter_brief": 0.18,
            "character_cards": 0.25,
            "recent_summaries": 0.10,
            "foreshadowing": 0.08,
            "rhythm_quota": 0.08,
            "outline_anchor": 0.05,
            "entity_context": 0.03,
            "character_state": 0.10,
            "world_setting": 0.08,
            "style_anchor": 0.05,
        },
    },
    "development": {
        "range": (0.05, 0.30),
        "ratios": {
            "chapter_brief": 0.12,
            "character_cards": 0.16,
            "recent_summaries": 0.20,
            "foreshadowing": 0.13,
            "rhythm_quota": 0.10,
            "outline_anchor": 0.06,
            "entity_context": 0.05,
            "character_state": 0.08,
            "world_setting": 0.05,
            "style_anchor": 0.05,
        },
    },
    "deepwater": {
        "range": (0.30, 0.75),
        "ratios": {
            "chapter_brief": 0.10,
            "character_cards": 0.12,
            "recent_summaries": 0.25,
            "foreshadowing": 0.18,
            "rhythm_quota": 0.08,
            "outline_anchor": 0.06,
            "entity_context": 0.06,
            "character_state": 0.07,
            "world_setting": 0.05,
            "style_anchor": 0.03,
        },
    },
    "finale": {
        "range": (0.75, 1.0),
        "ratios": {
            "chapter_brief": 0.08,
            "character_cards": 0.08,
            "recent_summaries": 0.16,
            "foreshadowing": 0.30,
            "rhythm_quota": 0.08,
            "outline_anchor": 0.06,
            "entity_context": 0.04,
            "character_state": 0.06,
            "world_setting": 0.04,
            "style_anchor": 0.03,
            "milestone": 0.07,       # 里程碑（终局储备）
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

# 压缩阈值（超过此字数的摘要需压缩）
COMPRESS_THRESHOLD = 500

# =========================================================
# 动态阶段判定（v1.1 新增）
# =========================================================

def _estimate_total_chapters(book_dir: Path, reader=None) -> Optional[int]:
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
        content = (reader or read_file_safe)(master_outline)
        # 查找"全书X章"、"共X章"、"总计X章"等表述
        total_match = re.search(r"(?:全书|共|总计|计划).*?(\d+)\s*章", content)
        if total_match:
            try:
                return int(total_match.group(1))
            except ValueError:
                pass

        # 常见总纲直接写“第1-50章”或“第951—1000章”，不一定带卷标题。
        ranges = re.findall(r"第\s*(\d+)\s*[-—~～至到]\s*(\d+)\s*章", content)
        if ranges:
            return max(max(int(start), int(end)) for start, end in ranges)

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


def determine_stage(book_dir: Path, target_chapter: int, reader=None) -> str:
    """根据目标章节与全书进度判定当前阶段。

    Args:
        book_dir: 书籍工程目录。
        target_chapter: 目标章节号。

    Returns:
        阶段名：opening / development / deepwater / finale。
        无法推算总章数时默认返回 "development"。
    """
    total = _estimate_total_chapters(book_dir, reader=reader)
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

def extract_milestone_content(book_dir: Path, reader=None) -> str:
    """从总纲中提取与终局相关的段落。

    搜索包含「终局」「结局」「最终」「大结局」关键词的段落。

    Returns:
        匹配的段落文本，无匹配时返回空字符串。
    """
    master_outline = book_dir / "大纲" / "总纲.md"
    if not master_outline.exists():
        return ""

    content = (reader or read_file_safe)(master_outline)
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


def _safe_source_path(book_dir: Path, relative: str) -> Path:
    """Accept portable relative file paths only; never follow link components."""
    if (not isinstance(relative, str) or not relative or PureWindowsPath(relative).drive
            or relative.startswith("/") or any(c in relative for c in '\\:<>"|?*')
            or any(ord(c) < 32 for c in relative)):
        raise ValueError("unsafe_source_path")
    parts = relative.split("/")
    if any(p in {"", ".", ".."} or p.rstrip(" .") != p
           or re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", p, re.I)
           for p in parts):
        raise ValueError("unsafe_source_path")
    root = Path(book_dir).absolute()
    target = root.joinpath(*parts)
    # Check ancestors in order before examining children (including book-root
    # links and Windows junctions). Missing components are handled by the reader.
    for current in [*reversed(target.parents), target]:
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("linked_source_path")
        if current != target and not stat.S_ISDIR(info.st_mode):
            raise ValueError("non_directory_source_parent")
    return target


class _ContextReader:
    """One selection's byte snapshot; parsing and fingerprints share each read."""
    def __init__(self, book_dir: Path):
        self.root = Path(book_dir).absolute()
        self.texts = {}
        self.sources = {}
        self.omitted = {}

    def __call__(self, path: Path) -> str:
        relative = path.absolute().relative_to(self.root).as_posix()
        if relative in self.texts:
            return self.texts[relative]
        try:
            safe = _safe_source_path(self.root, relative)
            data = safe.read_bytes()
            content = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, ValueError) as exc:
            self.omitted[relative] = {"path": relative, "reason":
                "missing" if isinstance(exc, FileNotFoundError) else "unreadable_or_unsafe"}
            self.texts[relative] = ""
            return ""
        self.texts[relative] = content
        self.sources[relative] = {"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                                  "bytes": len(data), "required": False}
        return content

    def optional(self, path: Path, budget: int) -> bool:
        relative = path.absolute().relative_to(self.root).as_posix()
        if budget <= 0:
            self.omitted[relative] = {"path": relative, "reason": "budget"}
            return False
        return bool(self(path).strip())


def _package_sha256(packet: Dict[str, Any]) -> str:
    """Accidental-change detection, not a signature or a semantic truth check."""
    payload = {key: value for key, value in packet.items() if key != "package_sha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def verify_context(book_dir: Path, packet: Any) -> Dict[str, Any]:
    """Verify read sources plus explicit legacy missing-card assumptions."""
    result = {"ready": False, "status": "malformed", "changed": [], "missing": [], "errors": []}
    if not isinstance(packet, dict):
        result["errors"].append("invalid_context_packet")
        return result
    if "source_manifest" not in packet or "package_sha256" not in packet:
        result.update(status="unverified", errors=["context_provenance_missing"])
        return result
    manifest = packet["source_manifest"]
    digest = packet["package_sha256"]
    if (not isinstance(manifest, list) or not manifest
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or type(packet.get("ready")) is not bool or not isinstance(packet.get("components"), dict)
            or not isinstance(packet.get("errors", []), list)
            or any(not isinstance(e, str) for e in packet.get("errors", []))):
        result["errors"].append("invalid_context_provenance")
        return result
    sources, seen = [], set()
    # Validate the entire manifest before reading even its first source.
    for source in manifest:
        if (not isinstance(source, dict) or not isinstance(source.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
                or type(source.get("bytes")) is not int or source["bytes"] < 0
                or type(source.get("required")) is not bool):
            result["errors"].append("invalid_source_manifest")
            return result
        try:
            path = _safe_source_path(book_dir, source.get("path"))
        except (OSError, ValueError) as exc:
            result["errors"].append("invalid_source_path: " + str(exc))
            return result
        key = str(path).casefold()
        if key in seen:
            result["errors"].append("duplicate_source_path")
            return result
        seen.add(key)
        sources.append((source, path))
    card_component = packet["components"].get("character_cards", {})
    if not isinstance(card_component, dict) or not isinstance(card_component.get("state_only", []), list):
        result["errors"].append("invalid_state_only_manifest")
        return result
    absent_cards = []
    for entry in card_component.get("state_only", []):
        if (not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
                or not entry["name"] or any(c in entry["name"] for c in "/\\")
                or entry.get("source") != "追踪/角色状态.md"):
            result["errors"].append("invalid_state_only_manifest")
            return result
        relative = entry.get("missing_card")
        if relative != "设定/角色/" + entry["name"] + ".md":
            result["errors"].append("invalid_state_only_manifest")
            return result
        try:
            path = _safe_source_path(book_dir, relative)
        except (OSError, ValueError) as exc:
            result["errors"].append("invalid_source_path: " + str(exc))
            return result
        key = str(path).casefold()
        if key in seen or not any(s["path"] == entry["source"] and s["required"] for s, _ in sources):
            result["errors"].append("invalid_state_only_manifest")
            return result
        seen.add(key)
        absent_cards.append(relative)
    try:
        actual_digest = _package_sha256(packet)
    except (TypeError, ValueError, OverflowError, RecursionError):
        result["errors"].append("invalid_context_packet")
        return result
    if actual_digest != digest:
        result.update(status="stale", errors=["package_digest_mismatch"])
        return result
    unreadable = False
    for relative in absent_cards:
        try:
            _safe_source_path(book_dir, relative).lstat()
        except FileNotFoundError:
            continue
        except ValueError:
            result["errors"].append("invalid_source_path: " + relative)
            return result
        except OSError:
            unreadable = True
            result["errors"].append("source_unreadable: " + relative)
            continue
        result["changed"].append(relative)
    for source, path in sources:
        try:
            # Recheck links immediately before opening, in case paths changed
            # during manifest validation. This is not an atomic filesystem lock.
            data = _safe_source_path(book_dir, source["path"]).read_bytes()
        except FileNotFoundError:
            result["missing"].append(source["path"])
            continue
        except ValueError:
            result["errors"].append("invalid_source_path: " + source["path"])
            return result
        except OSError:
            unreadable = True
            result["errors"].append("source_unreadable: " + source["path"])
            continue
        if len(data) != source["bytes"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
            result["changed"].append(source["path"])
    result["status"] = ("stale" if result["changed"] or result["missing"] else
                        "unverified" if unreadable else "fresh")
    result["errors"].extend(packet.get("errors", []))
    if not packet["ready"] and not packet.get("errors"):
        result["errors"].append("context_not_ready")
    result["ready"] = result["status"] == "fresh" and packet["ready"] and not result["errors"]
    return result


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
                ending = suffix[:remaining]
                result.append(line[:remaining - count_chars(ending)] + ending)
            break
        result.append(line)
        current += line_chars
    return "\n".join(result)


# =========================================================
# 章节摘要解析
# =========================================================

def parse_chapter_summaries(book_dir: Path, reader=None) -> List[Dict[str, Any]]:
    """解析章节摘要文件"""
    summary_file = book_dir / "追踪" / "章节摘要.md"
    if not summary_file.exists():
        return []

    content = (reader or read_file_safe)(summary_file)
    chapters = []
    current_chapter = None

    for line in content.split("\n"):
        # 匹配章节标题
        match = re.match(r"#{2,6}\s*第(\d+)章", line)
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
    """把多章详记压成仍可被机器解析的结构化卷级记忆。"""
    target = [ch for ch in chapters if from_ch <= ch["chapter"] <= to_ch]
    target.sort(key=lambda x: x["chapter"])

    if not target:
        return f"第{from_ch}-{to_ch}章无摘要数据。"

    aliases = {
        "发生了什么": ("发生了什么", "章节摘要", "一句话", "概要"),
        "状态变化": ("状态变化", "人物变化"),
        "伏笔进出": ("伏笔进出", "伏笔变化"),
        "关键实体": ("关键实体",),
        "时间约束": ("时间约束", "时间锚点"),
    }

    def values(raw, names):
        labels = "|".join(re.escape(name) for name in names)
        matches = re.findall(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:" + labels
            + r")(?:\*\*)?\s*[：:]\s*(.+?)\s*$", raw, re.MULTILINE)
        return [value.strip() for value in matches if value.strip()]

    collected = {field: [] for field in aliases}
    for ch in target:
        raw = ch.get("raw", "")
        chapter_events = []
        for field, names in aliases.items():
            field_values = values(raw, names)
            for value in field_values:
                collected[field].append(f"第{ch['chapter']}章 {value}")
            if field == "发生了什么":
                chapter_events.extend(field_values)
        if not chapter_events:
            body = "\n".join(raw.splitlines()[1:]).strip()
            if body:
                collected["发生了什么"].append(
                    f"第{ch['chapter']}章 {truncate_text(body, 160)}")

    lines = [f"## 第{from_ch}-{to_ch}章 回顾压缩"]
    lines.append(f"- 来源章节：{from_ch}-{to_ch}")
    for field in ("发生了什么", "状态变化", "伏笔进出", "关键实体", "时间约束"):
        value = "；".join(dict.fromkeys(collected[field])) or "N/A"
        lines.append(f"- {field}：{value}")
    return "\n".join(lines)


# =========================================================
# 上下文选取
# =========================================================

def _has_state_value(text: str) -> bool:
    """Reject empty field labels, comments and explicit unfilled placeholders."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    placeholders = {"", "未知", "待填", "待补", "未填写", "暂无", "todo", "tbd", "n/a", "值"}
    for line in text.splitlines():
        if re.match(r"^\s*#{1,6}[ \t]+", line):
            continue
        if line.strip().startswith("|"):
            cells = line.strip().strip("|").split("|")
            if any(_has_state_value(cell) for cell in cells[1:]):
                return True
            continue
        value = re.split(r"[:：]", line, maxsplit=1)[-1].strip(" \t\r\n-*`_|。")
        if value.lower() not in placeholders:
            return True
    return False


def _has_character_state(text: str, name: str) -> bool:
    """Require an identity-bearing section/row, not a relationship mention."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    state_fields = {"当前状态", "当前身份", "当前能力", "关键关系", "状态变更记录", "关键认识与依据",
                    "位置", "伤势", "持有物", "目标", "行动", "能力", "关系", "知识边界", "身份", "物品", "限制"}
    def is_state_field(title):
        title = title.strip(" *`\r")
        # Recognizable property headings, including ordinary compound labels;
        # unknown person headings must not lend their facts to the parent.
        return title in state_fields or bool(re.fullmatch(
            r"(?:当前|最新|身体|生理|心理|本章|长期|短期|近期)?(?:状态|状况|情况|目标)", title))
    headings = list(re.finditer(r"^(#{1,6})[ \t]+([^\n]+)$", text, re.MULTILINE))
    for index, heading in enumerate(headings):
        if heading.group(2).strip(" *`\r") != name:
            continue
        end = next((other.start() for other in headings[index + 1:]
                    if len(other.group(1)) <= len(heading.group(1))
                    or not is_state_field(other.group(2))), len(text))
        if _has_state_value(text[heading.end():end]):
            return True
    for line in text.splitlines():
        cells = [cell.strip(" *`") for cell in line.strip().strip("|").split("|")]
        if len(cells) > 1 and cells[0] == name and any(_has_state_value(cell) for cell in cells[1:]):
            return True
        if (re.match(r"^\s*(?:[-*]\s+)?(?:\*\*)?" + re.escape(name)
                     + r"(?:\*\*)?\s*[:：]\s*\S", line) and _has_state_value(line)):
            return True
    return False


_CARD_FIELDS = re.compile(
    r"基本信息|身份|职业|姓名|年龄|性格|稳定事实|不变量|动机|目标|底线|恐惧|软肋|"
    r"知识|知情|声线|口癖|口头禅|语气|能力|关系|禁忌|原则|价值观")


def _select_character_card(content: str) -> Dict[str, Any]:
    """Keep semantic constraints whole; omit only explicitly optional safe blocks.

    Unknown sections are not assumed irrelevant. A table/field inside an optional
    section can still carry a constraint, so keep the entire section in that case.
    """
    lines = content.splitlines(keepends=True)
    headings = []
    semantic_lines = []
    for index, line in enumerate(lines):
        heading = re.match(r"^(#{1,6})[ \t]+(.+?)\s*$", line)
        if heading:
            headings.append((index, len(heading.group(1)), heading.group(2)))
            if _CARD_FIELDS.search(heading.group(2)):
                semantic_lines.append(index)
        elif line.lstrip().startswith("|"):
            if _CARD_FIELDS.search(line):
                semantic_lines.append(index)
        else:
            field = re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?([^:：\n]+?)(?:\*\*)?[:：]", line)
            if field and _CARD_FIELDS.search(field.group(1)):
                semantic_lines.append(index)
    keep = [True] * len(lines)
    omitted = []
    if semantic_lines:
        for position, (start, level, title) in enumerate(headings):
            if not keep[start] or not re.search(r"(?:可省略|可选|无关).*(?:履历|背景|参考)", title):
                continue
            end = next((i for i, other_level, _ in headings[position + 1:] if other_level <= level), len(lines))
            section = "".join(lines[start:end])
            if (any(start <= i < end for i in semantic_lines)
                    or re.search(r"绝不|不能|不得|必须|禁止|尚不知|只在", section)):
                continue
            keep[start:end] = [False] * (end - start)
            omitted.append({"heading": title, "start_line": start + 1, "end_line": end,
                            "reason": "explicit_optional_section"})
    spans, start = [], None
    for index, retained in enumerate(keep + [False]):
        if retained and start is None:
            start = index
        elif not retained and start is not None:
            spans.append({"start_line": start + 1, "end_line": index})
            start = None
    return {"content": "".join(line for line, retained in zip(lines, keep) if retained),
            "source_spans": spans, "omitted_sections": omitted,
            "selection": "semantic_sections" if semantic_lines else "full_unknown_format"}


def _summary_is_reliable(raw: str) -> bool:
    """Fail closed for an emitted seven-field summary whose fields are blank."""
    body = "\n".join((raw or "").splitlines()[1:]).strip()
    if not body:
        return False
    labels = "|".join(re.escape(name) for name in SUMMARY_FIELD_NAMES)
    if not re.search(r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:" + labels
                     + r")(?:\*\*)?\s*[：:]", body, re.MULTILINE):
        return True  # Legacy prose remains a supported, explicit fallback.
    fields = extract_summary_fields(body)["summary_fields"]
    return all(str(fields.get(name, "")).strip() for name in SUMMARY_FIELD_NAMES)


def _required_context(book_dir: Path, chapter: int, reader=None):
    """Never compress away facts required to write safely. Ambiguity is reported."""
    components, missing = {}, []
    read = reader or read_file_safe

    def add(name, path, content=None):
        text = read(path) if content is None else content
        if not text.strip():
            missing.append(path.relative_to(book_dir).as_posix())
            return
        components[name] = {"source": path.relative_to(book_dir).as_posix(),
                            "content": text, "chars": count_chars(text), "required": True}

    outline = book_dir / "大纲" / f"章纲_第{chapter:03d}章.md"
    if not outline.exists():
        outline = book_dir / "大纲" / f"章纲_第{chapter}章.md"
    add("chapter_brief", outline)
    mentioned = extract_mentioned_characters(
        components.get("chapter_brief", {}).get("content", ""), book_dir)
    state_path = book_dir / "追踪/角色状态.md"
    state = read(state_path)
    missing.extend("追踪/角色状态.md#" + name for name in mentioned
                   if not _has_character_state(state, name))
    # Only omit confidently identified inactive-person sections. Shared sections,
    # tables and unknown headings may contain required facts, so preserve them.
    known_names = {path.stem for path in (book_dir / "设定/角色").glob("*.md")}
    sections = re.split(r"(?=^#{1,2}[ \t]+)", state, flags=re.MULTILINE)
    if mentioned:
        kept = []
        for section in sections:
            heading = re.match(r"^##[ \t]+([^\n]+)", section)
            identity = heading.group(1).strip(" *`\r") if heading else None
            if identity not in known_names or identity in mentioned:
                kept.append(section)
        state = "".join(kept)
    add("character_state", state_path, state)
    foreshadow_path = book_dir / "追踪/伏笔台账.md"
    timeline_path = book_dir / "追踪/时间线.md"
    for kind, path in (("foreshadowing", foreshadow_path), ("timeline", timeline_path)):
        raw = read(path)
        selection = _tracking_selection(raw, kind)
        add(kind, path, selection.pop("content") if raw.strip() else "")
        if kind in components:
            components[kind]["selection"] = selection
    if chapter > 1:
        previous = [s for s in parse_chapter_summaries(book_dir, reader=reader) if s["chapter"] == chapter - 1]
        if len(previous) == 1 and _summary_is_reliable(previous[0]["raw"]):
            add("previous_chapter", book_dir / "追踪/章节摘要.md", previous[0]["raw"])
        else:
            candidates = [p for p in (book_dir / "正文").glob("*.md")
                          if re.match(r"第0*{}章(?:[_\s.]|$)".format(chapter - 1), p.name)]
            if len(candidates) == 1:
                add("previous_chapter", candidates[0])
            else:
                missing.append("上一章正文或可靠摘要: 第{}章".format(chapter - 1))
    cards, state_only = [], []
    for name in mentioned:
        relative = "设定/角色/" + name + ".md"
        if any(c in name for c in "/\\"):
            missing.append(relative)
            continue
        try:
            card_path = _safe_source_path(book_dir, relative)
        except (OSError, ValueError):
            missing.append(relative)
            continue
        content = read(card_path)
        if not content.strip():
            # Only a proven missing file qualifies. Existing empty, unsafe or
            # unreadable cards must not silently lose their hard constraints.
            if (isinstance(read, _ContextReader)
                    and read.omitted.get(relative, {}).get("reason") == "missing"
                    and _has_character_state(state, name)):
                state_only.append({"name": name, "missing_card": relative,
                                   "source": "追踪/角色状态.md"})
            else:
                missing.append(relative)
            continue
        card = _select_character_card(content)
        card.update(name=name, source=relative, chars=count_chars(card["content"]), required=True)
        cards.append(card)
    components["character_cards"] = {"count": len(cards), "chars": sum(card["chars"] for card in cards),
                                     "characters": cards, "state_only": state_only, "required": True}
    return components, missing


def _transaction_blocked_context(book_dir, target_chapter, max_chars, stage, recovery):
    blocked = {
        "version": VERSION, "book_dir": str(book_dir), "target_chapter": target_chapter,
        "max_chars": max_chars, "stage": stage or "unknown",
        "budget_ratios_used": get_dynamic_budget_ratios(stage) if stage else dict(BUDGET_RATIOS),
        "components": {}, "ready": False, "missing_required": [], "required_chars": 0,
        "errors": ["transaction_incomplete"], "recovery_command": recovery,
        "total_chars": 0, "budget_used": 0, "brief_chars": 0,
        "source_manifest": [], "omitted_sources": [],
    }
    blocked["package_sha256"] = _package_sha256(blocked)
    blocked["brief_chars"] = count_chars(_render_brief_context(blocked))
    blocked["package_sha256"] = _package_sha256(blocked)
    return blocked


def select_context(book_dir: Path, target_chapter: int, max_chars: int = DEFAULT_MAX_CHARS,
                   stage: Optional[str] = None) -> Dict[str, Any]:
    """Read one coherent canonical snapshot under the shared transaction lock."""
    if target_chapter < 1 or max_chars < 1:
        raise ValueError("chapter and max_chars must be positive")
    book_dir = Path(book_dir).absolute()
    from chapter_transaction import TransactionError, recovery_command
    from common import canonical_read_lock
    try:
        with canonical_read_lock(book_dir):
            return _select_context_unlocked(book_dir, target_chapter, max_chars, stage)
    except (TransactionError, OSError):
        return _transaction_blocked_context(
            book_dir, target_chapter, max_chars, stage, recovery_command(book_dir))


def _select_context_unlocked(book_dir: Path, target_chapter: int, max_chars: int,
                             stage: Optional[str]) -> Dict[str, Any]:
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

    reader = _ContextReader(book_dir)
    required, missing = _required_context(book_dir, target_chapter, reader=reader)
    required_chars = sum(c["chars"] for c in required.values())
    # v1.1: 自动判定阶段
    if stage is None:
        stage = determine_stage(book_dir, target_chapter, reader=reader)

    # v1.1: 按阶段获取动态预算比例
    budget_ratios_used = get_dynamic_budget_ratios(stage)

    context = {
        "version": VERSION,
        "book_dir": str(book_dir),
        "target_chapter": target_chapter,
        "max_chars": max_chars,
        "stage": stage,                        # v1.1 新增
        "budget_ratios_used": budget_ratios_used,  # v1.1 新增
        "components": dict(required),
        "ready": not missing and required_chars <= max_chars,
        "missing_required": missing,
        "required_chars": required_chars,
        "errors": (["required_context_missing"] if missing else []) + (
            ["required_context_over_budget"] if required_chars > max_chars else []),
        "total_chars": 0,
        "budget_used": 0,
    }

    remaining = max(0, max_chars - required_chars) if context["ready"] else 0
    optional_ratios = {k: v for k, v in budget_ratios_used.items() if k not in required}
    ratio_sum = sum(optional_ratios.values()) or 1
    budget = {k: int(remaining * v / ratio_sum) for k, v in optional_ratios.items()}

    # 3. 近章摘要
    summary_file = book_dir / "追踪/章节摘要.md"
    all_summaries = (parse_chapter_summaries(book_dir, reader=reader)
                     if reader.optional(summary_file, budget.get("recent_summaries", 0)) else [])
    recent = get_recent_summaries(all_summaries, target_chapter, DEFAULT_RECENT_CHAPTERS)

    recent_budget = budget.get("recent_summaries", 0)
    recent_chars = 0
    recent_content = []
    included_chapters = []
    for ch in recent:
        separator_chars = 3 if recent_content else 0
        available = recent_budget - recent_chars - separator_chars
        if available <= 0:
            break
        selected = truncate_text(ch["raw"], available)
        if not selected.strip():
            break
        recent_content.append(selected)
        included_chapters.append(ch["chapter"])
        recent_chars += separator_chars + count_chars(selected)
        if selected != ch["raw"]:
            break

    recent_text = "\n---\n".join(recent_content)

    context["components"]["recent_summaries"] = {
        "count": len(included_chapters),
        "chars": count_chars(recent_text),
        "chapters": included_chapters,
        "content": recent_text,
    }

    # 5. 节奏配额
    rhythm_file = book_dir / "追踪" / "节奏配额.md"
    if reader.optional(rhythm_file, budget.get("rhythm_quota", 0)):
        rhythm_content = reader(rhythm_file)
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
    if reader.optional(anchor_file, budget.get("outline_anchor", 0)):
        try:
            anchor_data = json.loads(reader(anchor_file))
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
    if reader.optional(style_file, budget.get("style_anchor", 0)):
        style_content = reader(style_file)
        style_content = truncate_text(style_content, budget["style_anchor"])
        context["components"]["style_anchor"] = {
            "source": "文风锚.md",
            "chars": count_chars(style_content),
            "content": style_content,
        }

    # 8. 实体上下文（BM25检索结果，如果有）
    entity_index_file = book_dir / "追踪" / "entity_index.json"
    if reader.optional(entity_index_file, budget.get("entity_context", 0)):
        try:
            entity_data = json.loads(reader(entity_index_file))
            # 以待写章章纲中的实体为查询，召回其历史出现章；待写章本身尚未入索引。
            chapter_brief = context["components"].get("chapter_brief", {}).get("content", "")
            index_entries = entity_data.get("entities", entity_data) if isinstance(entity_data, dict) else {}
            relevant = {}
            for entity, chapters in index_entries.items():
                if not isinstance(entity, str) or entity not in chapter_brief or not isinstance(chapters, list):
                    continue
                historical = [ch for ch in chapters if isinstance(ch, int) and ch < target_chapter]
                if historical:
                    relevant[entity] = historical[-5:]
            entity_text = json.dumps(relevant, ensure_ascii=False, indent=2)
            entity_text = truncate_text(entity_text, budget["entity_context"])
            context["components"]["entity_context"] = {
                "source": "entity_index.json",
                "chars": count_chars(entity_text),
                "content": entity_text,
            }
        except (json.JSONDecodeError, TypeError):
            pass

    # 8.6 世界观关键设定（v7.0 新增）
    world_file = book_dir / "设定" / "世界观.md"
    if reader.optional(world_file, budget.get("world_setting", 0)):
        world_content = reader(world_file)
        world_content = truncate_text(world_content, budget["world_setting"])
        context["components"]["world_setting"] = {
            "source": "世界观.md",
            "chars": count_chars(world_content),
            "content": world_content,
        }

    # 9. 里程碑（v1.1 新增：finale 阶段加载终局储备）
    if stage == "finale" and "milestone" in budget:
        milestone_budget = budget["milestone"]
        milestone_text = (extract_milestone_content(book_dir, reader=reader)
                          if reader.optional(book_dir / "大纲/总纲.md", milestone_budget) else "")
        if milestone_text:
            milestone_text = truncate_text(milestone_text, milestone_budget)
            context["components"]["milestone"] = {
                "source": "总纲.md（终局储备）",
                "chars": count_chars(milestone_text),
                "content": milestone_text,
            }

    # Brief 是实际注入写作模型的载荷。若固定标签使其超限，先缩减可选组件；
    # required 内容保持逐字不变，仍超限则明确阻断。
    brief = _render_brief_context(context)
    overflow = count_chars(brief) - max_chars
    if overflow > 0 and context["ready"]:
        for name in reversed(list(context["components"])):
            component = context["components"][name]
            if component.get("required") or name == "character_cards":
                continue
            content = component.get("content", "")
            if not content:
                continue
            keep = max(0, count_chars(content) - overflow)
            component["content"] = truncate_text(content, keep, suffix="")
            component["chars"] = count_chars(component["content"])
            brief = _render_brief_context(context)
            overflow = count_chars(brief) - max_chars
            if overflow <= 0:
                break
    brief = _render_brief_context(context)
    context["brief_chars"] = count_chars(brief)
    if context["ready"] and context["brief_chars"] > max_chars:
        context["ready"] = False
        if "required_context_over_budget" not in context["errors"]:
            context["errors"].append("required_context_over_budget")

    # 计算组件内容字数（保留既有 total_chars 语义）。
    total = sum(comp.get("chars", 0) for comp in context["components"].values())
    context["total_chars"] = total
    context["budget_used"] = round(total / max_chars * 100, 1) if max_chars > 0 else 0

    for component in required.values():
        paths = [component["source"]] if "source" in component else [
            card["source"] for card in component.get("characters", [])]
        for path in paths:
            if path in reader.sources:
                reader.sources[path]["required"] = True
    context["source_manifest"] = list(reader.sources.values())
    context["omitted_sources"] = list(reader.omitted.values())
    context["selection_receipt"] = {
        "required_chars": required_chars, "budget_chars": max_chars,
        "brief_chars": context["brief_chars"], "semantic_review": "not_run",
        "tracking": {kind: required[kind]["selection"] for kind in
                     ("foreshadowing", "timeline") if kind in required},
    }
    context["package_sha256"] = _package_sha256(context)

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

    # Explicit cast may contain new characters without cards. Never hide them
    # merely because one already registered character was found in the outline.
    cast_level = None
    for line in chapter_content.splitlines():
        heading = re.match(r"^(#{1,6})[ \t]+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            if cast_level is not None and level <= cast_level:
                cast_level = None
            if heading.group(2).strip(" *`\r") in {"出场人物", "出场角色"}:
                cast_level = level
            continue
        labels = "出场人物|出场角色|人物|角色|出场"
        if cast_level is not None:
            labels += "|主要|次要"  # The shipped outline-chapter.md format.
        match = re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:" + labels + r")"
                         r"(?:\*\*)?\s*[：:]\s*(.+)$", line)
        if match:
            names = re.split(r"[，,、;；]", match.group(1))
            names = [name.strip(" \t\r\n*`。.!！?？") for name in names]
            no_cast = {"无", "无人", "无出场人物", "不新增出场人物", "不新增人物",
                       "无新增人物", "无新增出场人物", "无其他人物", "无其他出场人物"}
            mentioned.extend(name for name in names if name and name not in no_cast)

    return list(dict.fromkeys(mentioned))


def _tracking_selection(content: str, kind: str) -> Dict[str, Any]:
    """Only omit explicitly archived sections; retain unknown siblings verbatim.

    Headings define lifecycle, never chapter numbers alone. A nested heading
    inherits its parent's classification unless it explicitly states otherwise.
    This is a layout diagnosis, not a claim that an archived fact is false.
    """
    lines = content.splitlines(keepends=True)
    active = (("🔴", "🟡", "🟢", "超期", "活跃", "长线", "未结", "未回收", "待回收")
              if kind == "foreshadowing" else ("当前", "锚点", "承诺", "约束", "待办", "未完成", "分支"))
    # Exact lifecycle labels, not lexical matches such as "历史真相" / "未归档".
    archive_labels = (("已回收", "归档", "已归档", "历史归档") if kind == "foreshadowing"
                      else ("历史记录", "历史归档", "归档", "已归档", "已完成", "已结束"))
    starts = [(i, re.match(r"^(#{1,6})[ \t]+(.+)", line)) for i, line in enumerate(lines)]
    starts = [(i, match) for i, match in starts if match]
    if not starts or starts[0][0] != 0:
        starts.insert(0, (0, None))
    sections, stack, recognized = [], [], False
    selected = []
    for pos, (start, match) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        level, title = (len(match.group(1)), match.group(2).strip()) if match else (0, "")
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_kind = stack[-1][1] if stack else "unknown"
        pending = bool(re.search(r"(?:未|待|尚未|尚待|不应|不要).{0,4}(?:归档|回收|完成|结束)|(?:归档|回收)前", title))
        clean_title = re.sub(r"^[✅\s]+", "", title).strip()
        explicit_archive = any(re.fullmatch(re.escape(label) + r"(?:\s*[（(][^）)]*[）)])?", clean_title)
                               for label in archive_labels)
        if pending or any(word in title for word in active):
            state, recognized = "active", True
        elif explicit_archive or title.strip() == "✅":
            state, recognized = "archived", True
        else:
            state = parent_kind
        stack.append((level, state))
        chunk = "".join(lines[start:end])
        structural = bool(match and not "".join(lines[start + 1:end]).strip())
        keep = state != "archived"
        reason = "explicit_archive" if not keep else (
            "active_constraint" if state == "active" else "heading" if structural else "unknown_preserved")
        sections.append({"heading": title, "start_line": start + 1, "end_line": end,
                         "selected": keep, "reason": reason, "chars": count_chars(chunk)})
        if keep:
            selected.append(chunk)
    chosen = "".join(selected).strip() if recognized else content
    if kind == "foreshadowing" and recognized and not any(
            line.strip() and not line.lstrip().startswith("#") for line in chosen.splitlines()):
        chosen = "# 活跃伏笔\n（无未结伏笔）"
    return {"content": chosen, "mode": "lifecycle_sections" if recognized else "legacy_preserved",
            "source_chars": count_chars(content), "selected_chars": count_chars(chosen),
            "omitted_chars": sum(s["chars"] for s in sections if not s["selected"]),
            "sections": sections,
            "next_action": "context_manager.py inspect-state：生成工程外整理候选，未知条目须人工核对",
            "manual_review_required": not recognized or any(s["reason"] == "unknown_preserved" for s in sections)}


def extract_active_foreshadows(foreshadow_content: str, target_chapter: int) -> str:
    """Lifecycle selection; unknown constraints are kept regardless of age."""
    return _tracking_selection(foreshadow_content, "foreshadowing")["content"]


def extract_relevant_timeline(timeline_content: str, target_chapter: int) -> str:
    """Preserve unknown state; an old chapter number is not proof of expiry."""
    return _tracking_selection(timeline_content, "timeline")["content"]


def inspect_tracking_state(book_dir: Path, chapter: int) -> Dict[str, Any]:
    """Read-only proposal with original content; no automatic semantic migration."""
    from common import canonical_read_lock
    if chapter < 1:
        raise ValueError("chapter must be positive")
    reader = _ContextReader(Path(book_dir))
    proposal = {"schema_version": 1, "chapter": chapter, "applied": False,
                "manual_review_required": True, "sources": {}}
    with canonical_read_lock(book_dir):
        for kind, relative in (("timeline", "追踪/时间线.md"), ("foreshadowing", "追踪/伏笔台账.md")):
            content = reader(Path(book_dir) / relative)
            if not content.strip():
                raise ValueError("required_context_missing: " + relative)
            selection = _tracking_selection(content, kind)
            selection.pop("content")
            proposal["sources"][kind] = dict(selection, original_content=content,
                                              source=reader.sources[relative])
    return proposal


def _render_brief_context(context: Dict[str, Any]) -> str:
    """Render the actual compact prompt payload; provenance stays in JSON/report."""
    lines = []
    if not context.get("ready", True):
        lines.append("BLOCKED: " + ", ".join(context.get("errors", [])))
    lines.append(f"# 第{context['target_chapter']}章写作上下文")
    for name, component in context.get("components", {}).items():
        lines.append(f"\n[{name}]")
        if name == "character_cards":
            for legacy in component.get("state_only", []):
                lines.append(f"{legacy['name']} 无独立人物卡；仅使用 {legacy['source']}，未载明事实保持未知。")
            for card in component.get("characters", []):
                lines.append(f"{card['name']}：")
                for omitted in card.get("omitted_sections", []):
                    lines.append(f"省略可选段：{omitted['heading']}")
                lines.append(card.get("content", ""))
        else:
            content = component.get("content", "")
            if content:
                lines.append(content)
    return "\n".join(lines)


# =========================================================
# 上下文报告生成
# =========================================================

def generate_context_report(context: Dict[str, Any]) -> str:
    """生成人类可读的上下文报告"""
    lines = []
    lines.append("# 写作上下文包")
    if not context.get("ready", True):
        lines.append("BLOCKED: " + ", ".join(context.get("errors", [])))
        lines.extend("- 缺少：" + path for path in context.get("missing_required", []))
        lines.append("先补齐必需信息，或提高预算/由作者确认无损摘录；不得直接写章。")
    lines.append(f"\n生成引擎：context_manager.py v{VERSION}")
    lines.append(f"目标章节：第{context['target_chapter']}章")
    # v1.1: 显示当前阶段
    stage = context.get("stage", "")
    if stage:
        stage_label = STAGE_LABELS.get(stage, stage)
        lines.append(f"当前阶段：{stage_label} ({stage})")
    lines.append(f"预算上限：{context['max_chars']} 字符")
    lines.append(f"实际使用：{context['total_chars']} 字符 ({context['budget_used']}%)")
    for kind, selection in context.get("selection_receipt", {}).get("tracking", {}).items():
        lines.append("- {} 选取：{}，保留 {} 字符，省略明确归档 {} 字符。".format(
            kind, selection["mode"], selection["selected_chars"], selection["omitted_chars"]))
        if selection.get("manual_review_required"):
            lines.append("  存在旧格式或未知分区，未按章龄删除；" + selection["next_action"])
    if "source_manifest" in context:
        lines.append("来源核验范围：清单中的实际读取文件及 state-only 缺卡前提；复用前运行 verify。哈希不证明语义正确。")
        lines.append("上下文包 SHA-256：" + context.get("package_sha256", ""))
        for source in context["source_manifest"]:
            lines.append(f"- 来源指纹：{source['path']} ({source['bytes']} bytes, SHA-256 {source['sha256']})")
        for source in context.get("omitted_sources", []):
            lines.append(f"- 可选源未纳入或读取失败：{source['path']} ({source['reason']})")

    # v1.1: 使用实际使用的预算比例
    used_ratios = context.get("budget_ratios_used", BUDGET_RATIOS)
    lines.append(f"\n## 组件清单")
    for name, comp in context["components"].items():
        chars = comp.get("chars", 0)
        budget_pct = used_ratios.get(name, 0) * 100
        allocation = "必需，完整保留" if comp.get("required") else f"可选参考权重 {budget_pct:.0f}%"
        lines.append(f"- **{name}**：{chars} 字 ({allocation}) — 来源: {comp.get('source', 'N/A')}")

    lines.append(f"\n## 上下文内容")
    for name, comp in context["components"].items():
        lines.append(f"\n### [{name}]")
        content = comp.get("content", "")
        if name == "character_cards":
            for legacy in comp.get("state_only", []):
                lines.append(f"旧工程兼容：{legacy['name']} 无独立人物卡（{legacy['missing_card']}）；"
                             f"仅使用已读取的 {legacy['source']}，未载明事实保持未知。"
                             "新增人物卡后必须重新选取上下文。")
            for char in comp.get("characters", []):
                lines.append(f"\n**{char['name']}**:")
                if "source" in char:
                    positions = ", ".join(f"{span['start_line']}-{span['end_line']}"
                                          for span in char.get("source_spans", []))
                    lines.append(f"来源：{char['source']}，行 {positions}；选取：{char.get('selection', '')}")
                    for omitted in char.get("omitted_sections", []):
                        lines.append(f"省略可选段：{omitted['heading']}（行 {omitted['start_line']}-{omitted['end_line']}）")
                lines.append(char["content"])
        else:
            lines.append(content)

    return "\n".join(lines)


def generate_brief_context(context: Dict[str, Any]) -> str:
    """生成精简版上下文（本节速记格式）"""
    return _render_brief_context(context)


# =========================================================
# CLI
# =========================================================

def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
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

    p_verify = sub.add_parser("verify", help="只读核验已有 JSON 上下文包及其来源")
    p_verify.add_argument("book_dir", help="书籍工程目录（不采用包内目录）")
    p_verify.add_argument("--context", required=True, help="待核验的 JSON 上下文包")

    p_inspect = sub.add_parser("inspect-state", help="只读检查追踪布局，生成工程外整理候选")
    p_inspect.add_argument("book_dir")
    p_inspect.add_argument("--chapter", type=int, required=True)
    p_inspect.add_argument("--output", help="工程外新建 JSON 文件；省略则只输出 JSON")

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
        if not context["ready"]:
            sys.exit(1)

    elif args.command == "inspect-state":
        try:
            book_dir = Path(args.book_dir).absolute()
            result = inspect_tracking_state(book_dir, args.chapter)
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                target = Path(args.output).resolve()
                try:
                    target.relative_to(book_dir.resolve())
                except ValueError:
                    pass
                else:
                    raise ValueError("output_must_be_outside_book")
                with target.open("x", encoding="utf-8") as handle:
                    handle.write(output)
            print(output)
        except (OSError, ValueError, RuntimeError) as exc:
            print(json.dumps({"error": str(exc), "applied": False}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

    elif args.command == "verify":
        try:
            packet = json.loads(Path(args.context).read_text(encoding="utf-8-sig"))
            result = verify_context(Path(args.book_dir), packet)
        except (OSError, ValueError, RecursionError):
            result = {"ready": False, "status": "malformed", "changed": [], "missing": [],
                      "errors": ["context_package_unreadable_or_invalid_json"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["ready"] else 1)

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
