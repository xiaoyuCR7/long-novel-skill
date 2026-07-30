#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adaptive_engine.py — 自适应写作引擎（独家创新功能，MVP）。

核心思想：根据作者实时状态 + 作品数据，动态调整写作辅助策略。
解决"千人一面"的固定提示词问题，让写作辅助真正"懂你"。

三个维度的自适应：
  1. 写作速度自适应：速度下降时降低单章目标，速度上升时提高目标
  2. 质量趋势自适应：AI味连续上升时加强去AI味提示
  3. 节奏模式自适应：连续冲突场景后自动推荐缓冲场景

用法：
  python scripts/adaptive_engine.py analyze "书名目录"
  python scripts/adaptive_engine.py suggest "书名目录" --next-chapter 38
  python scripts/adaptive_engine.py report "书名目录" --output "追踪/自适应报告.md"

  （也通过 novel-cli 调用）
  python novel-cli.py adaptive analyze "书名目录"
  python novel-cli.py adaptive suggest "书名目录"
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 让脚本能导入同目录的模块
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import common

# =============================================================================
# 常量
# =============================================================================

# 分析时考虑的最近章节数
DEFAULT_RECENT_CHAPTERS = 10
# 速度趋势判定阈值（百分比变化）
SPEED_RISING_THRESHOLD = 0.15   # 速度上升超过15%
SPEED_FALLING_THRESHOLD = -0.15  # 速度下降超过15%
# 质量趋势判定阈值（AI味分数变化）
QUALITY_DEGRADING_THRESHOLD = 5  # 连续上升5分以上
# 字数目标调整
DEFAULT_TARGET_CHARS = 4000
REDUCED_TARGET_CHARS = 3000
INCREASED_TARGET_CHARS = 5000
# 节奏连续判定
MAX_CONSECUTIVE_INTENSE = 3  # 连续3章高强度后建议缓冲


# =============================================================================
# 数据收集
# =============================================================================

def _collect_chapter_data(book_dir: Path, recent_n: int = DEFAULT_RECENT_CHAPTERS) -> List[Dict[str, Any]]:
    """收集最近N章的所有数据（字数/门禁/AI味分）。"""
    chapters = []
    prose_dir = book_dir / "正文"
    gate_dir = book_dir / "追踪" / "门禁"

    if not prose_dir.exists():
        return chapters

    for f in sorted(prose_dir.glob("*.md")):
        ch_no = common.parse_chapter_number(f.name)
        if ch_no is None:
            continue
        text = common.read_text(f) or ""
        chars = common.count_chars(text)

        # 门禁结果
        gate_passed = None
        ai_score = None
        gate_path = gate_dir / f"gate_ch{ch_no}.json" if gate_dir.exists() else None
        if gate_path and gate_path.exists():
            data = common.read_json(gate_path) or {}
            gate_passed = data.get("passed")
            ai_score = data.get("ai_score")

        # 场景类型（从标题/文件首行推断）
        scene_type = _detect_scene_type(f, text)

        chapters.append({
            "chapter": ch_no,
            "title": f.stem,
            "chars": chars,
            "gate_passed": gate_passed,
            "ai_score": ai_score,
            "scene_type": scene_type,
        })

    return chapters[-recent_n:] if len(chapters) > recent_n else chapters


def _detect_scene_type(file_path: Path, text: str) -> str:
    """从标题和内容推断场景类型。

    返回：intense（冲突/战斗/高潮） / light（日常/过渡/缓冲） / normal（普通）
    """
    title = file_path.stem
    first_100_chars = text[:200] if len(text) > 200 else text

    intense_keywords = [
        "战", "斗", "决", "杀", "死", "灭", "爆", "怒", "惊", "危",
        "险", "逼", "压", "冲", "撞", "撕", "裂", "崩", "溃", "败",
        "挑战", "决斗", "对决", "战斗", "激战", "血战", "死战",
        "危机", "险境", "绝境", "生死", "爆发", "冲突",
    ]
    light_keywords = [
        "日常", "休息", "赶路", "过场", "过渡", "转场", "路途", "行路",
        "出发", "启程", "到达", "抵达", "离开", "告别", "夜宿",
        "闲聊", "聊天", "交谈", "吃饭", "喝酒", "品茶",
    ]

    intense_score = sum(1 for kw in intense_keywords if kw in title or kw in first_100_chars)
    light_score = sum(1 for kw in light_keywords if kw in title or kw in first_100_chars)

    if intense_score > light_score and intense_score >= 2:
        return "intense"
    elif light_score > intense_score and light_score >= 2:
        return "light"
    return "normal"


# =============================================================================
# 状态分析
# =============================================================================

def analyze_speed_trend(chapters: List[Dict[str, Any]]) -> str:
    """分析写作速度趋势。

    比较前半段和后半段的平均每章字数。
    返回：rising / stable / falling
    """
    if len(chapters) < 4:
        return "stable"

    mid = len(chapters) // 2
    first_half = chapters[:mid]
    second_half = chapters[mid:]

    avg_first = sum(c["chars"] for c in first_half) / len(first_half)
    avg_second = sum(c["chars"] for c in second_half) / len(second_half)

    if avg_first == 0:
        return "stable"

    change = (avg_second - avg_first) / avg_first
    if change >= SPEED_RISING_THRESHOLD:
        return "rising"
    elif change <= SPEED_FALLING_THRESHOLD:
        return "falling"
    return "stable"


def analyze_quality_trend(chapters: List[Dict[str, Any]]) -> str:
    """分析质量趋势（AI味分数变化）。

    返回：improving / stable / degrading
    """
    scores = [c["ai_score"] for c in chapters if c["ai_score"] is not None]
    if len(scores) < 3:
        return "stable"

    # 最近3章的平均分 vs 更早的平均分
    recent = scores[-3:]
    earlier = scores[:-3] if len(scores) > 3 else scores[:1]

    avg_recent = sum(recent) / len(recent)
    avg_earlier = sum(earlier) / max(len(earlier), 1)

    diff = avg_recent - avg_earlier
    if diff >= QUALITY_DEGRADING_THRESHOLD:
        return "degrading"
    elif diff <= -QUALITY_DEGRADING_THRESHOLD:
        return "improving"
    return "stable"


def analyze_rhythm_pattern(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析节奏模式。

    返回：{pattern: str, counts: dict, consecutive_intense: int}
    """
    counts = {"intense": 0, "light": 0, "normal": 0}
    for c in chapters:
        counts[c["scene_type"]] = counts.get(c["scene_type"], 0) + 1

    # 统计连续高强度章节数
    consecutive = 0
    max_consecutive = 0
    for c in reversed(chapters):
        if c["scene_type"] == "intense":
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            break

    return {
        "counts": counts,
        "consecutive_intense": consecutive,
        "max_consecutive_intense": max_consecutive,
    }


def analyze_author_state(book_dir: Path, recent_n: int = DEFAULT_RECENT_CHAPTERS) -> Dict[str, Any]:
    """综合分析作者状态。

    返回包含所有维度的分析结果字典。
    """
    chapters = _collect_chapter_data(book_dir, recent_n)
    if not chapters:
        return {
            "state": "insufficient_data",
            "confidence": 0.0,
            "chapters_analyzed": 0,
            "message": "章节数据不足，无法进行自适应分析",
        }

    speed = analyze_speed_trend(chapters)
    quality = analyze_quality_trend(chapters)
    rhythm = analyze_rhythm_pattern(chapters)

    # 总体状态
    flags = []
    if speed == "falling":
        flags.append("速度下降")
    if quality == "degrading":
        flags.append("质量下降")
    if rhythm["consecutive_intense"] >= MAX_CONSECUTIVE_INTENSE:
        flags.append("连续高强度")

    state = "good" if not flags else ("warning" if len(flags) == 1 else "alert")

    return {
        "state": state,
        "confidence": min(len(chapters) / recent_n, 1.0),
        "chapters_analyzed": len(chapters),
        "latest_chapter": chapters[-1]["chapter"] if chapters else 0,
        "speed_trend": speed,
        "quality_trend": quality,
        "rhythm": rhythm,
        "flags": flags,
        "chapters": chapters,
    }


# =============================================================================
# 策略推荐
# =============================================================================

def suggest_strategies(book_dir: Path, next_chapter: Optional[int] = None) -> List[Dict[str, Any]]:
    """根据当前状态推荐下一章的写作策略。

    返回策略列表，每项包含 type/action/reason/priority。
    """
    state = analyze_author_state(book_dir)
    strategies = []

    if state["state"] == "insufficient_data":
        return [{
            "type": "info",
            "action": "collect_data",
            "reason": "章节数据不足，建议先写3-5章后再进行自适应分析",
            "priority": "low",
        }]

    # 策略1：速度下降 → 降低单章字数目标
    if state["speed_trend"] == "falling" and state["confidence"] > 0.5:
        strategies.append({
            "type": "target_adjustment",
            "action": "reduce_target_chars",
            "from": DEFAULT_TARGET_CHARS,
            "to": REDUCED_TARGET_CHARS,
            "reason": "写作速度连续下降，建议降低单章目标避免焦虑和质量滑坡",
            "priority": "high",
        })

    # 策略2：速度上升 → 可提高目标
    if state["speed_trend"] == "rising" and state["confidence"] > 0.5:
        strategies.append({
            "type": "target_adjustment",
            "action": "increase_target_chars",
            "from": DEFAULT_TARGET_CHARS,
            "to": INCREASED_TARGET_CHARS,
            "reason": "写作状态良好，速度持续上升，可适当提高目标",
            "priority": "medium",
        })

    # 策略3：AI味上升 → 加强去AI味
    if state["quality_trend"] == "degrading" and state["confidence"] > 0.5:
        strategies.append({
            "type": "quality_enhancement",
            "action": "enable_heavy_deslop",
            "reason": "AI味连续3章上升，启动强去AI味模式，增加禁用词检查强度",
            "priority": "high",
            "steps": [
                "将7 Gate的禁用词模式从标准模式切换到严格模式",
                "增加毒句式检测阈值（检测更多变体）",
                "写作前先看3段对标书原文找感觉",
            ],
        })

    # 策略4：连续冲突 → 推荐缓冲场景
    rhythm = state.get("rhythm", {})
    if rhythm.get("consecutive_intense", 0) >= MAX_CONSECUTIVE_INTENSE:
        strategies.append({
            "type": "rhythm_balance",
            "action": "suggest_light_scene",
            "reason": f'连续{rhythm["consecutive_intense"]}章高强度场景，读者情绪需要缓冲',
            "priority": "high",
            "suggestions": [
                "日常/闲聊场景：展示角色间的关系和性格",
                "赶路/转场：自然过渡到下一个地点",
                "休息/恢复：战斗后的喘息和反思",
                "铺垫/伏笔：为下一个高潮悄悄埋线索",
            ],
        })

    # 策略5：质量好 → 保持并尝试创新
    if state["quality_trend"] == "improving" and state["confidence"] > 0.5:
        strategies.append({
            "type": "encouragement",
            "action": "maintain_and_experiment",
            "reason": "质量持续提升，保持当前节奏的同时可以尝试一些新写法",
            "priority": "low",
        })

    # 如果没什么特别的，给通用建议
    if not strategies:
        strategies.append({
            "type": "info",
            "action": "maintain_current",
            "reason": "状态稳定，继续保持当前节奏即可",
            "priority": "low",
        })

    # 按优先级排序
    priority_order = {"high": 0, "medium": 1, "low": 2}
    strategies.sort(key=lambda s: priority_order.get(s["priority"], 2))

    return strategies


# =============================================================================
# 报告生成
# =============================================================================

def generate_report(book_dir: Path, output_path: Optional[Path] = None) -> str:
    """生成自适应分析报告（Markdown格式）。

    返回报告文本，同时可选写入文件。
    """
    state = analyze_author_state(book_dir)
    strategies = suggest_strategies(book_dir)

    state_emoji = {"good": "🟢", "warning": "🟡", "alert": "🔴", "insufficient_data": "⚪"}
    speed_emoji = {"rising": "📈", "stable": "➡️", "falling": "📉"}
    quality_emoji = {"improving": "✅", "stable": "➡️", "degrading": "⚠️"}

    lines = [
        f"# 🎯 自适应写作分析报告",
        f"",
        f"**书籍**：{book_dir.name}",
        f"**生成时间**：{common.timestamp()}",
        f"**分析章节**：最近{state['chapters_analyzed']}章",
        f"**置信度**：{state['confidence']*100:.0f}%",
        f"",
        f"## 📊 总体状态",
        f"",
        f"- **状态**：{state_emoji.get(state['state'], '❓')} {state['state'].upper()}",
        f"- **写作速度趋势**：{speed_emoji.get(state['speed_trend'], '❓')} {state['speed_trend']}",
        f"- **质量趋势（AI味）**：{quality_emoji.get(state['quality_trend'], '❓')} {state['quality_trend']}",
        f"- **节奏分布**：",
        f"  - 高强度（冲突/战斗）：{state.get('rhythm', {}).get('counts', {}).get('intense', 0)}章",
        f"  - 缓冲（日常/过渡）：{state.get('rhythm', {}).get('counts', {}).get('light', 0)}章",
        f"  - 普通：{state.get('rhythm', {}).get('counts', {}).get('normal', 0)}章",
        f"  - 连续高强度：{state.get('rhythm', {}).get('consecutive_intense', 0)}章",
        f"",
        f"## 🎯 策略建议",
        f"",
    ]

    for i, s in enumerate(strategies, 1):
        priority_tag = {"high": "🔴高", "medium": "🟡中", "low": "🟢低"}.get(s["priority"], s["priority"])
        lines.append(f"### {i}. [{priority_tag}] {s.get('action', s['type'])}")
        lines.append(f"")
        lines.append(f"**原因**：{s['reason']}")
        lines.append(f"")
        if "from" in s and "to" in s:
            lines.append(f"- 从 **{s['from']}字** 调整为 **{s['to']}字**")
            lines.append(f"")
        if "steps" in s:
            lines.append(f"**执行步骤**：")
            for step in s["steps"]:
                lines.append(f"- {step}")
            lines.append(f"")
        if "suggestions" in s:
            lines.append(f"**可选方向**：")
            for sug in s["suggestions"]:
                lines.append(f"- {sug}")
            lines.append(f"")

    lines.extend([
        f"## 💡 通用建议",
        f"",
        f"1. **保持节奏**：不管状态如何，稳定的日更习惯比爆发式写作更重要",
        f"2. **及时止损**：如果连续3章状态不佳，考虑休息1天或换个场景写",
        f"3. **对标参考**：状态不好时，读3段对标书原文找感觉比硬写更有效",
        f"4. **相信数据**：本报告基于实际数据分析，直觉可能有偏差但数据不会",
        f"",
        f"---",
        f"*本报告由自适应写作引擎自动生成，仅供参考*",
    ])

    report = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        common.write_text(output_path, report)

    return report


# =============================================================================
# 主入口
# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="自适应写作引擎（根据作者状态动态调整写作策略）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/adaptive_engine.py analyze "我的小说"
  python scripts/adaptive_engine.py suggest "我的小说"
  python scripts/adaptive_engine.py report "我的小说" --output "追踪/自适应报告.md"
""",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # analyze
    p_analyze = sub.add_parser("analyze", help="分析作者状态")
    p_analyze.add_argument("book_dir", help="书籍工程目录")
    p_analyze.add_argument("--recent", type=int, default=DEFAULT_RECENT_CHAPTERS,
                           help=f"分析最近N章（默认{DEFAULT_RECENT_CHAPTERS}）")

    # suggest
    p_suggest = sub.add_parser("suggest", help="给出策略建议")
    p_suggest.add_argument("book_dir", help="书籍工程目录")
    p_suggest.add_argument("--next-chapter", type=int, default=None, help="下一章章节号")

    # report
    p_report = sub.add_parser("report", help="生成Markdown报告")
    p_report.add_argument("book_dir", help="书籍工程目录")
    p_report.add_argument("--output", default=None, help="输出文件路径（默认打印到stdout）")

    args = ap.parse_args()
    book_dir = Path(args.book_dir).resolve()

    if not book_dir.is_dir():
        print(f"错误：目录不存在 {book_dir}", file=sys.stderr)
        return 2

    if args.command == "analyze":
        state = analyze_author_state(book_dir, args.recent)
        common.print_json(state)

    elif args.command == "suggest":
        strategies = suggest_strategies(book_dir, args.next_chapter)
        for i, s in enumerate(strategies, 1):
            print(f"\n{i}. [{s['priority'].upper()}] {s.get('action', s['type'])}")
            print(f"   原因：{s['reason']}")
            if "from" in s:
                print(f"   调整：{s['from']}字 → {s['to']}字")
            if "steps" in s:
                print(f"   步骤：")
                for step in s["steps"]:
                    print(f"    - {step}")
            if "suggestions" in s:
                print(f"   建议：")
                for sug in s["suggestions"]:
                    print(f"    - {sug}")

    elif args.command == "report":
        output = Path(args.output) if args.output else None
        report = generate_report(book_dir, output)
        if output is None:
            print(report)
        else:
            print(f"报告已生成：{output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
