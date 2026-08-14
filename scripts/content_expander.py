#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""content_expander.py — 智能内容扩充引擎 v2.0（纯标准库，无第三方依赖）。

当章节字数不足时，不是简单追加指令，而是根据上下文智能识别可扩充维度，
输出结构化的扩充建议。v2.0 在 v1.0 五种策略基础上新增三种，并引入优先级
分析引擎、策略冲突检测、智能融合推荐和具体化建议生成。

八种扩充策略：
  1. 场景扩充（scene_expansion）：环境/感官/空间细节不足时触发
  2. 对话丰富（dialogue_enrichment）：对话占比偏低或对话过于简短时触发
  3. 心理深度（psychological_depth）：关键情绪节点缺乏内心活动时触发
  4. 动作细节（action_detail）：打斗/冲突场景动作描写不足时触发
  5. 过渡润滑（transition_smoothing）：场景切换突兀时触发
  6. 世界观植入（worldbuilding）：设定信息可自然融入的位置
  7. 伏笔埋设（foreshadowing）：适合植入微型伏笔的节点
  8. 感官通感（synesthesia）：多感官交叉描写增强沉浸感

v2.0 新增能力：
  - 章节类型自动推断（战斗/情感/过渡/悬疑/世界观）
  - 优先级分析引擎（根据章节类型+字数缺口计算权重）
  - 策略冲突检测与智能融合（1主+2辅组合推荐）
  - 具体化扩充建议（位置+方向+示例）
  - 扩充方案完整生成（主策略+辅助策略+具体建议+预估增字）

输出：
  - 结构化 JSON 报告（可被其他脚本消费）
  - 人类可读的扩充建议（Markdown 格式）

用法：
  python3 scripts/content_expander.py analyze chapter.md --target 3000
  python3 scripts/content_expander.py suggest chapter.md --strategy scene_expansion
  python3 scripts/content_expander.py priority chapter.md --target 3000
  python3 scripts/content_expander.py expand chapter.md --target 3000
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =========================================================
# 常量
# =========================================================

VERSION = "2.0.0"

# 对话引号模式
QUOTE_PATTERN = r'[「"「][^」"」]*[」"」]'

# 场景/环境关键词
SCENE_KEYWORDS = [
    "天空", "阳光", "月光", "风", "雨", "雪", "雾", "云",
    "街道", "房间", "大厅", "走廊", "庭院", "城门", "山林",
    "气味", "声音", "温度", "光线", "影子",
]

# 动作/冲突关键词
ACTION_KEYWORDS = [
    "拳", "剑", "刀", "掌", "踢", "挡", "闪", "冲", "劈",
    "挡住", "闪避", "攻击", "防御", "反击", "爆发",
]

# 心理/情绪关键词
PSYCH_KEYWORDS = [
    "想", "觉得", "认为", "怀疑", "犹豫", "纠结",
    "心中", "内心", "脑海", "念头", "思绪",
]

# 过渡标记
TRANSITION_MARKERS = ["忽然", "突然", "此时", "此刻", "与此同时", "另一边", "转瞬间"]

# 世界观/设定关键词
WORLDBUILDING_KEYWORDS = [
    "宗门", "家族", "帝国", "王朝", "势力", "门派", "修炼", "境界",
    "功法", "武技", "法术", "灵气", "灵力", "真元", "真气",
    "大陆", "地域", "山脉", "河流", "城池", "秘境", "遗迹",
    "百年", "千年", "上古", "远古", "传说", "神话",
    "规则", "法则", "禁制", "阵法", "契约", "血脉",
]

# 伏笔/悬念关键词
FORESHADOWING_KEYWORDS = [
    "似乎", "仿佛", "隐约", "好像", "隐隐", "莫名",
    "不对劲", "不寻常", "奇怪", "异常", "蹊跷",
    "秘密", "隐藏", "暗中", "背后", "真相",
    "总有一天", "将来", "日后", "以后", "届时",
]

# 感官关键词（按感官分类）
SENSE_KEYWORDS = {
    "visual": ["看", "望", "凝视", "注视", "目光", "视线", "颜色", "光", "影", "亮", "暗"],
    "auditory": ["听", "声音", "声响", "轰鸣", "低语", "尖叫", "沉默", "寂静", "回响"],
    "olfactory": ["气味", "香味", "臭味", "芬芳", "刺鼻", "清香", "腥臭", "气息"],
    "gustatory": ["味道", "苦涩", "甘甜", "辛辣", "酸味", "咸味", "口感"],
    "tactile": ["触摸", "触感", "冰冷", "滚烫", "柔软", "坚硬", "粗糙", "光滑", "疼痛", "发麻"],
}

# 段落最小长度（低于此值可能需要扩充）
MIN_PARAGRAPH_LENGTH = 30

# 对话占比下限（低于此值建议扩充对话）
MIN_DIALOGUE_RATIO = 0.20

# 对话占比上限
MAX_DIALOGUE_RATIO = 0.55

# 章节类型定义
CHAPTER_TYPES = [
    "battle",      # 战斗型
    "emotional",   # 情感型
    "transition",  # 过渡型
    "suspense",    # 悬疑型
    "worldbuilding",  # 世界观型
]

# 策略代码与中文名映射
STRATEGY_NAMES = {
    "scene_expansion": "场景扩充",
    "dialogue_enrichment": "对话丰富",
    "psychological_depth": "心理深度",
    "action_detail": "动作细节",
    "transition_smoothing": "过渡润滑",
    "worldbuilding": "世界观植入",
    "foreshadowing": "伏笔埋设",
    "synesthesia": "感官通感",
}

# 策略冲突矩阵：冲突的策略对不能同时为主策略
STRATEGY_CONFLICTS = {
    "action_detail": {"transition_smoothing", "dialogue_enrichment"},
    "transition_smoothing": {"action_detail", "psychological_depth"},
    "dialogue_enrichment": {"action_detail", "synesthesia"},
    "psychological_depth": {"transition_smoothing", "worldbuilding"},
    "worldbuilding": {"psychological_depth", "action_detail"},
    "foreshadowing": set(),  # 伏笔可与任何策略搭配（作为辅助）
    "scene_expansion": set(),  # 场景百搭
    "synesthesia": {"dialogue_enrichment"},  # 通感和纯对话丰富有重叠
}

# 策略基础优先级（不同章节类型下的基础权重）
BASE_PRIORITY_BY_TYPE = {
    "battle": {
        "action_detail": 5, "scene_expansion": 3, "synesthesia": 3,
        "psychological_depth": 2, "foreshadowing": 1, "dialogue_enrichment": 1,
        "worldbuilding": 1, "transition_smoothing": 1,
    },
    "emotional": {
        "psychological_depth": 5, "dialogue_enrichment": 4, "synesthesia": 3,
        "scene_expansion": 2, "foreshadowing": 2, "action_detail": 1,
        "worldbuilding": 1, "transition_smoothing": 1,
    },
    "transition": {
        "transition_smoothing": 5, "worldbuilding": 3, "scene_expansion": 3,
        "foreshadowing": 3, "dialogue_enrichment": 2, "psychological_depth": 2,
        "synesthesia": 1, "action_detail": 1,
    },
    "suspense": {
        "foreshadowing": 5, "psychological_depth": 4, "scene_expansion": 3,
        "synesthesia": 3, "dialogue_enrichment": 2, "worldbuilding": 2,
        "action_detail": 1, "transition_smoothing": 2,
    },
    "worldbuilding": {
        "worldbuilding": 5, "scene_expansion": 4, "foreshadowing": 3,
        "dialogue_enrichment": 2, "transition_smoothing": 2, "synesthesia": 2,
        "psychological_depth": 1, "action_detail": 1,
    },
}

# 每种策略的预估增字效率（单位字/建议条数）
EXPANSION_EFFICIENCY = {
    "scene_expansion": 150,
    "dialogue_enrichment": 200,
    "psychological_depth": 120,
    "action_detail": 180,
    "transition_smoothing": 80,
    "worldbuilding": 150,
    "foreshadowing": 60,
    "synesthesia": 100,
}


# =========================================================
# 工具函数
# =========================================================

def load_text(file_path: str) -> str:
    """加载文本文件"""
    p = Path(file_path)
    if not p.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def split_paragraphs(text: str) -> List[str]:
    """分割段落"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return paragraphs


def count_chars(text: str) -> int:
    """统计非空白字符数"""
    return len(re.sub(r"\s", "", text))


def count_chinese_chars(text: str) -> int:
    """统计汉字数"""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def extract_dialogues(text: str) -> List[str]:
    """提取对话"""
    return re.findall(r'[「"「][^」"」]+[」"」]', text)


def calculate_dialogue_ratio(text: str) -> float:
    """计算对话占比"""
    total = count_chars(text)
    if total == 0:
        return 0.0
    dialogues = extract_dialogues(text)
    dialogue_chars = sum(count_chars(d) for d in dialogues)
    return dialogue_chars / total


def keyword_density(text: str, keywords: List[str]) -> float:
    """计算关键词密度（关键词出现次数 / 总字符数）"""
    total = count_chars(text)
    if total == 0:
        return 0.0
    count = sum(text.count(kw) for kw in keywords)
    return count / total


# =========================================================
# 八种策略的分析函数
# =========================================================

def analyze_scene_depth(paragraphs: List[str]) -> Dict[str, Any]:
    """分析场景描写深度（策略1：场景扩充）"""
    scene_count = 0
    scene_paragraphs = []
    for i, p in enumerate(paragraphs):
        if any(kw in p for kw in SCENE_KEYWORDS):
            scene_count += 1
            scene_paragraphs.append(i)

    total_paras = len(paragraphs)
    ratio = scene_count / total_paras if total_paras > 0 else 0

    return {
        "scene_paragraph_count": scene_count,
        "total_paragraphs": total_paras,
        "scene_ratio": round(ratio, 3),
        "scene_paragraph_indices": scene_paragraphs,
        "needs_expansion": ratio < 0.15,
        "expansion_potential": "high" if ratio < 0.10 else "medium" if ratio < 0.15 else "low",
    }


def analyze_dialogue_quality(text: str, paragraphs: List[str]) -> Dict[str, Any]:
    """分析对话质量（策略2：对话丰富）"""
    dialogues = extract_dialogues(text)
    dialogue_ratio = calculate_dialogue_ratio(text)

    # 统计对话长度分布
    dialogue_lengths = [count_chars(d) for d in dialogues]
    short_dialogues = sum(1 for l in dialogue_lengths if l < 10)
    medium_dialogues = sum(1 for l in dialogue_lengths if 10 <= l <= 30)
    long_dialogues = sum(1 for l in dialogue_lengths if l > 30)

    # 检查对话是否有动作垫底
    action_cues = ["手", "眼", "身", "头", "脚步", "转", "抬", "放"]
    dialogues_with_action = 0
    for i, p in enumerate(paragraphs):
        if re.search(QUOTE_PATTERN, p):
            prev_has_action = i > 0 and any(kw in paragraphs[i-1] for kw in action_cues)
            curr_has_action = any(kw in p for kw in action_cues)
            if prev_has_action or curr_has_action:
                dialogues_with_action += 1

    return {
        "dialogue_count": len(dialogues),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "short_dialogues": short_dialogues,
        "medium_dialogues": medium_dialogues,
        "long_dialogues": long_dialogues,
        "dialogues_with_action": dialogues_with_action,
        "needs_enrichment": dialogue_ratio < MIN_DIALOGUE_RATIO,
        "expansion_potential": "high" if dialogue_ratio < 0.15 else "medium" if dialogue_ratio < MIN_DIALOGUE_RATIO else "low",
    }


def analyze_psychological_depth(paragraphs: List[str]) -> Dict[str, Any]:
    """分析心理描写深度（策略3：心理深度）"""
    psych_count = 0
    psych_paragraphs = []
    for i, p in enumerate(paragraphs):
        if any(kw in p for kw in PSYCH_KEYWORDS):
            psych_count += 1
            psych_paragraphs.append(i)

    total = len(paragraphs)
    ratio = psych_count / total if total > 0 else 0

    # 检查是否有"直接告知"情绪词（应该用动作替代）
    emotion_direct = 0
    emotion_words = ["紧张", "害怕", "愤怒", "悲伤", "高兴", "兴奋", "失望", "绝望"]
    body_cues = ["手", "眼", "脸", "身体", "声音", "呼吸", "脚步"]
    direct_emotion_positions = []
    for i, p in enumerate(paragraphs):
        for ew in emotion_words:
            if ew in p and not any(kw in p for kw in body_cues):
                emotion_direct += 1
                direct_emotion_positions.append(i)
                break

    return {
        "psych_paragraph_count": psych_count,
        "total_paragraphs": total,
        "psych_ratio": round(ratio, 3),
        "psych_paragraph_indices": psych_paragraphs,
        "direct_emotion_count": emotion_direct,
        "direct_emotion_positions": direct_emotion_positions,
        "needs_deepening": ratio < 0.10 or emotion_direct > 3,
        "expansion_potential": "high" if ratio < 0.05 else "medium" if ratio < 0.10 else "low",
    }


def analyze_action_detail(paragraphs: List[str]) -> Dict[str, Any]:
    """分析动作描写细节（策略4：动作细节）"""
    action_paragraphs = []
    for i, p in enumerate(paragraphs):
        action_count = sum(1 for kw in ACTION_KEYWORDS if kw in p)
        if action_count >= 2:
            action_paragraphs.append(i)

    # 检查动作段是否过短
    short_action_paras = 0
    for i in action_paragraphs:
        if count_chars(paragraphs[i]) < 50:
            short_action_paras += 1

    return {
        "action_paragraph_count": len(action_paragraphs),
        "action_paragraph_indices": action_paragraphs,
        "short_action_paragraphs": short_action_paras,
        "needs_detailing": short_action_paras > 0,
        "expansion_potential": "high" if short_action_paras > 2 else "medium" if short_action_paras > 0 else "low",
    }


def analyze_transitions(paragraphs: List[str]) -> Dict[str, Any]:
    """分析场景过渡（策略5：过渡润滑）"""
    abrupt_transitions = []
    for i in range(1, len(paragraphs)):
        prev = paragraphs[i-1]
        curr = paragraphs[i]
        # 检查是否有过渡标记且前段过短（突兀切换的信号）
        has_transition = any(m in curr[:20] for m in TRANSITION_MARKERS)
        if has_transition and count_chars(prev) < 50:
            abrupt_transitions.append(i)

    return {
        "total_transitions": len(paragraphs) - 1,
        "abrupt_transition_count": len(abrupt_transitions),
        "abrupt_positions": abrupt_transitions,
        "needs_smoothing": len(abrupt_transitions) > 0,
        "expansion_potential": "high" if len(abrupt_transitions) > 2 else "medium" if len(abrupt_transitions) > 0 else "low",
    }


def analyze_worldbuilding(paragraphs: List[str]) -> Dict[str, Any]:
    """分析世界观植入潜力（策略6：世界观植入）

    检测文本中已有设定词密度，以及适合植入设定的空白位置。
    """
    wb_paragraphs = []
    total_mentions = 0
    for i, p in enumerate(paragraphs):
        mentions = sum(p.count(kw) for kw in WORLDBUILDING_KEYWORDS)
        total_mentions += mentions
        if mentions >= 1:
            wb_paragraphs.append(i)

    total = len(paragraphs)
    ratio = len(wb_paragraphs) / total if total > 0 else 0

    # 寻找适合植入设定的"空白"段落：叙事段但缺乏设定信息
    # （不在对话密集段，不在纯动作段，有角色活动但缺少背景）
    implantable_paragraphs = []
    for i, p in enumerate(paragraphs):
        has_dialogue = bool(re.search(QUOTE_PATTERN, p))
        action_count = sum(p.count(kw) for kw in ACTION_KEYWORDS)
        wb_count = sum(p.count(kw) for kw in WORLDBUILDING_KEYWORDS)
        if (not has_dialogue and action_count < 2 and wb_count == 0
                and count_chars(p) >= 30 and i not in wb_paragraphs):
            implantable_paragraphs.append(i)

    return {
        "worldbuilding_paragraph_count": len(wb_paragraphs),
        "worldbuilding_mentions": total_mentions,
        "total_paragraphs": total,
        "worldbuilding_ratio": round(ratio, 3),
        "worldbuilding_paragraph_indices": wb_paragraphs,
        "implantable_paragraph_indices": implantable_paragraphs,
        "implantable_count": len(implantable_paragraphs),
        "needs_embedding": ratio < 0.08 and len(implantable_paragraphs) >= 2,
        "expansion_potential": (
            "high" if len(implantable_paragraphs) >= 4
            else "medium" if len(implantable_paragraphs) >= 2
            else "low"
        ),
    }


def analyze_foreshadowing(paragraphs: List[str]) -> Dict[str, Any]:
    """分析伏笔埋设潜力（策略7：伏笔埋设）

    检测现有伏笔密度，并识别适合埋设新伏笔的关键节点。
    """
    fs_paragraphs = []
    total_mentions = 0
    for i, p in enumerate(paragraphs):
        mentions = sum(p.count(kw) for kw in FORESHADOWING_KEYWORDS)
        total_mentions += mentions
        if mentions >= 1:
            fs_paragraphs.append(i)

    total = len(paragraphs)
    ratio = len(fs_paragraphs) / total if total > 0 else 0

    # 适合埋设伏笔的位置：
    # 1. 章节开头（引入悬念）
    # 2. 场景切换处（新环境的异常感）
    # 3. 章节结尾（留钩子）
    foreshadowing_slots = []
    if total >= 1:
        # 开头第一段
        foreshadowing_slots.append({"position": "opening", "paragraph_index": 0})
    if total >= 3:
        # 中间过渡段附近
        mid = total // 2
        foreshadowing_slots.append({"position": "middle", "paragraph_index": mid})
    if total >= 2:
        # 结尾段
        foreshadowing_slots.append({"position": "ending", "paragraph_index": total - 1})

    return {
        "foreshadowing_paragraph_count": len(fs_paragraphs),
        "foreshadowing_mentions": total_mentions,
        "total_paragraphs": total,
        "foreshadowing_ratio": round(ratio, 3),
        "foreshadowing_paragraph_indices": fs_paragraphs,
        "foreshadowing_slots": foreshadowing_slots,
        "slot_count": len(foreshadowing_slots),
        "needs_foreshadowing": ratio < 0.05,
        "expansion_potential": (
            "high" if ratio < 0.03
            else "medium" if ratio < 0.05
            else "low"
        ),
    }


def analyze_synesthesia(paragraphs: List[str]) -> Dict[str, Any]:
    """分析感官通感潜力（策略8：感官通感）

    检测各感官描写的分布均衡度，找出缺失的感官维度。
    """
    sense_counts = {}
    sense_paragraphs = {}
    for sense, keywords in SENSE_KEYWORDS.items():
        sense_counts[sense] = 0
        sense_paragraphs[sense] = []
        for i, p in enumerate(paragraphs):
            if any(kw in p for kw in keywords):
                sense_counts[sense] += 1
                sense_paragraphs[sense].append(i)

    total = len(paragraphs)

    # 计算感官丰富度（使用的感官种类数）
    active_senses = [s for s, c in sense_counts.items() if c > 0]
    sense_diversity = len(active_senses)

    # 找出薄弱感官（占比最低的2种）
    sense_ratios = {s: (c / total if total > 0 else 0) for s, c in sense_counts.items()}
    sorted_senses = sorted(sense_ratios.items(), key=lambda x: x[1])
    weak_senses = [s for s, r in sorted_senses[:2] if r < 0.05]

    # 通感潜力：是否存在只有单一感官的段落可扩充
    single_sense_paragraphs = []
    for i, p in enumerate(paragraphs):
        active_in_para = sum(1 for s, kws in SENSE_KEYWORDS.items() if any(kw in p for kw in kws))
        if active_in_para == 1 and count_chars(p) >= 40:
            single_sense_paragraphs.append(i)

    return {
        "sense_counts": sense_counts,
        "sense_paragraph_indices": sense_paragraphs,
        "sense_diversity": sense_diversity,
        "active_senses": active_senses,
        "weak_senses": weak_senses,
        "single_sense_paragraphs": single_sense_paragraphs,
        "total_paragraphs": total,
        "needs_enrichment": sense_diversity < 3 or len(weak_senses) >= 2,
        "expansion_potential": (
            "high" if sense_diversity <= 2
            else "medium" if sense_diversity == 3 or len(weak_senses) >= 2
            else "low"
        ),
    }


# =========================================================
# 章节类型自动推断
# =========================================================

def infer_chapter_type(text: str, paragraphs: List[str]) -> Tuple[str, Dict[str, float]]:
    """根据关键词密度自动推断章节类型。

    返回 (类型代码, 各类型置信度字典)
    """
    scores = {}

    # 战斗型：动作词密度高
    action_density = keyword_density(text, ACTION_KEYWORDS)
    scores["battle"] = action_density * 100  # 放大到可读范围

    # 情感型：心理词+对话占比
    psych_density = keyword_density(text, PSYCH_KEYWORDS)
    dialogue_ratio = calculate_dialogue_ratio(text)
    scores["emotional"] = (psych_density * 80 + dialogue_ratio * 0.5)

    # 过渡型：过渡标记多，动作少
    transition_density = keyword_density(text, TRANSITION_MARKERS)
    scores["transition"] = transition_density * 150 + (1.0 / (action_density * 100 + 1)) * 0.1

    # 悬疑型：伏笔词密度高
    foreshadow_density = keyword_density(text, FORESHADOWING_KEYWORDS)
    scores["suspense"] = foreshadow_density * 120

    # 世界观型：设定词密度高
    wb_density = keyword_density(text, WORLDBUILDING_KEYWORDS)
    scores["worldbuilding"] = wb_density * 80

    # 归一化处理，找出最高分
    max_score = max(scores.values()) if scores else 0
    if max_score < 0.001:
        # 所有分数极低，默认为过渡型
        return "transition", scores

    # 找出最高分类型
    best_type = max(scores, key=scores.get)
    return best_type, scores


# =========================================================
# 优先级分析引擎
# =========================================================

def calculate_priorities(
    text: str,
    paragraphs: List[str],
    target_chars: int,
    chapter_type: Optional[str] = None,
) -> List[Tuple[str, float, str]]:
    """计算各扩充策略的优先级权重。

    输入：章节文本、段落列表、目标字数、章节类型（可选，自动推断）
    输出：策略优先级列表 [(strategy_code, weight, reason), ...]，按权重降序排列
    """
    total_chars = count_chars(text)
    gap = max(0, target_chars - total_chars)

    # 自动推断章节类型（如果未提供）
    if chapter_type is None:
        chapter_type, _ = infer_chapter_type(text, paragraphs)

    # 获取八种策略的分析结果
    scene_a = analyze_scene_depth(paragraphs)
    dialogue_a = analyze_dialogue_quality(text, paragraphs)
    psych_a = analyze_psychological_depth(paragraphs)
    action_a = analyze_action_detail(paragraphs)
    transition_a = analyze_transitions(paragraphs)
    worldbuilding_a = analyze_worldbuilding(paragraphs)
    foreshadowing_a = analyze_foreshadowing(paragraphs)
    synesthesia_a = analyze_synesthesia(paragraphs)

    analyses = {
        "scene_expansion": scene_a,
        "dialogue_enrichment": dialogue_a,
        "psychological_depth": psych_a,
        "action_detail": action_a,
        "transition_smoothing": transition_a,
        "worldbuilding": worldbuilding_a,
        "foreshadowing": foreshadowing_a,
        "synesthesia": synesthesia_a,
    }

    # 获取该章节类型下的基础优先级
    base_priorities = BASE_PRIORITY_BY_TYPE.get(chapter_type, {})

    # 计算综合权重
    potential_multiplier = {"high": 3.0, "medium": 2.0, "low": 1.0}
    results = []

    for strategy_code in STRATEGY_NAMES:
        analysis = analyses[strategy_code]
        potential = analysis.get("expansion_potential", "low")
        base = base_priorities.get(strategy_code, 1)
        mult = potential_multiplier.get(potential, 1.0)

        # 字数缺口越大，高潜力策略的权重越高
        gap_factor = 1.0
        if gap > 500:
            gap_factor = 1.0 + (gap / 2000)  # 缺口越大，放大系数越高

        weight = round(base * mult * gap_factor, 2)

        # 生成理由
        reasons = []
        reasons.append(f"章节类型[{chapter_type}]基础权重{base}")
        reasons.append(f"扩充潜力[{potential}]")
        if gap > 0:
            reasons.append(f"字数缺口{gap}字")

        reason_str = "；".join(reasons)
        results.append((strategy_code, weight, reason_str))

    # 按权重降序排列
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# =========================================================
# 策略冲突检测与智能融合
# =========================================================

def check_conflict(strategy_a: str, strategy_b: str) -> bool:
    """检测两个策略是否存在冲突（不能同时为主策略）。"""
    conflicts_a = STRATEGY_CONFLICTS.get(strategy_a, set())
    conflicts_b = STRATEGY_CONFLICTS.get(strategy_b, set())
    return strategy_b in conflicts_a or strategy_a in conflicts_b


def recommend_strategy_combo(
    priorities: List[Tuple[str, float, str]],
) -> Dict[str, Any]:
    """推荐主策略 + 辅助策略组合（1主+2辅）。

    算法：
    1. 优先级最高的为候选主策略
    2. 从剩余策略中选出与主策略不冲突、且权重最高的2个作为辅助
    3. 返回组合及预估增字量
    """
    if not priorities:
        return {
            "primary": None,
            "secondary": [],
            "estimated_expansion": 0,
            "combo_score": 0,
        }

    # 主策略：优先级最高
    primary_code, primary_weight, primary_reason = priorities[0]

    # 辅助策略：从剩余中选与主策略不冲突的前2个
    secondary = []
    for code, weight, reason in priorities[1:]:
        if len(secondary) >= 2:
            break
        if not check_conflict(primary_code, code):
            # 检查辅助策略之间是否冲突
            conflict_with_existing = any(check_conflict(code, s[0]) for s in secondary)
            if not conflict_with_existing:
                secondary.append((code, weight, reason))

    # 如果辅助策略不足2个，放宽条件（允许辅助间轻度冲突）
    if len(secondary) < 2:
        for code, weight, reason in priorities[1:]:
            if len(secondary) >= 2:
                break
            if code == primary_code:
                continue
            if any(s[0] == code for s in secondary):
                continue
            if not check_conflict(primary_code, code):
                secondary.append((code, weight, reason))

    # 如果还不够，再放宽（即使与主策略有冲突，也可以作为辅助）
    if len(secondary) < 2:
        for code, weight, reason in priorities[1:]:
            if len(secondary) >= 2:
                break
            if code == primary_code:
                continue
            if any(s[0] == code for s in secondary):
                continue
            secondary.append((code, weight, reason))

    # 估算组合增字量
    est_primary = EXPANSION_EFFICIENCY.get(primary_code, 100) * 4  # 主策略约4条建议
    est_secondary = sum(EXPANSION_EFFICIENCY.get(s[0], 100) * 2 for s in secondary)  # 各2条
    estimated_expansion = est_primary + est_secondary

    # 组合评分（主策略权重 + 辅助权重的一半）
    combo_score = round(primary_weight + sum(s[1] * 0.5 for s in secondary), 2)

    return {
        "primary": {
            "code": primary_code,
            "name": STRATEGY_NAMES.get(primary_code, primary_code),
            "weight": primary_weight,
            "reason": primary_reason,
        },
        "secondary": [
            {
                "code": code,
                "name": STRATEGY_NAMES.get(code, code),
                "weight": weight,
                "reason": reason,
            }
            for code, weight, reason in secondary
        ],
        "estimated_expansion_chars": estimated_expansion,
        "combo_score": combo_score,
    }


# =========================================================
# 具体化扩充建议生成
# =========================================================

def generate_concrete_suggestions(
    strategy_code: str,
    paragraphs: List[str],
    text: str,
    num_suggestions: int = 4,
) -> List[Dict[str, Any]]:
    """为指定策略生成具体可执行的写作建议。

    每条建议包含：位置（开头/中间/结尾/特定段落）、扩写方向、示例。
    """
    suggestions = []

    if strategy_code == "scene_expansion":
        analysis = analyze_scene_depth(paragraphs)
        # 找缺少场景描写的段落位置
        sparse_positions = []
        for i, p in enumerate(paragraphs):
            if i not in analysis["scene_paragraph_indices"] and count_chars(p) >= 30:
                sparse_positions.append(i)
                if len(sparse_positions) >= num_suggestions:
                    break

        templates = [
            ("角色初到新地点时，用2-3句环境描写建立空间感",
             "用视线引导法：从远到近或从上到下，依次交代空间边界、关键物件、氛围色调"),
            ("情绪转折前，用环境细节做情绪铺垫",
             "将角色内心状态投射到环境上：压抑时天色阴沉，释然时微风拂面"),
            ("战斗/冲突场景补充空间感",
             "交代地形特征、障碍物分布、双方距离，让动作有空间参照"),
            ("角色独处时用环境反衬心境",
             "空房间的回声、钟表滴答、窗外雨声，用环境声放大孤独或紧张感"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            pos_idx = sparse_positions[idx] if idx < len(sparse_positions) else min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "dialogue_enrichment":
        analysis = analyze_dialogue_quality(text, paragraphs)
        # 找对话段和叙事段的位置
        dialogue_paras = [i for i, p in enumerate(paragraphs) if re.search(QUOTE_PATTERN, p)]
        narrative_paras = [i for i, p in enumerate(paragraphs)
                          if not re.search(QUOTE_PATTERN, p) and count_chars(p) >= 40]

        templates = [
            ("把信息密集的叙述改为对话交付",
             "让角色在互动中自然带出设定/背景，而非作者旁白式说明"),
            ("给短句对话加微动作垫底",
             "在台词前后插入手部动作、眼神变化、身体微移，展示人物态度"),
            ("在角色互动中补充日常型对话",
             "增加1-2轮寒暄/调侃/斗嘴，展示人物关系和性格反差"),
            ("加入潜台词：话里有话",
             "让角色说的话和真实意图有偏差，用语气/停顿/动作暗示真实想法"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            if idx < len(dialogue_paras):
                pos_idx = dialogue_paras[idx]
            elif narrative_paras:
                pos_idx = narrative_paras[idx % len(narrative_paras)]
            else:
                pos_idx = min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "psychological_depth":
        analysis = analyze_psychological_depth(paragraphs)
        # 优先在直接情绪词的位置建议
        target_positions = list(analysis.get("direct_emotion_positions", []))
        if len(target_positions) < num_suggestions:
            # 补充关键段落
            for i in range(len(paragraphs)):
                if i not in target_positions and count_chars(paragraphs[i]) >= 30:
                    target_positions.append(i)
                    if len(target_positions) >= num_suggestions:
                        break

        templates = [
            ("用身体细节替代直接情绪词",
             "把「他很紧张」改为「他的手指碰到门把手又缩回来，碰了三次才握住」"),
            ("关键决策前补内心权衡过程",
             "不是总结性的「他决定去」，而是选择与放弃的挣扎、利弊的瞬间掂量"),
            ("情绪转折点的内心独白碎片",
             "用碎片化的思绪、闪回的画面、未说出口的话，展示情绪的烈度"),
            ("角色对自身情绪的觉察与反思",
             "让角色意识到自己的反常，追问「我为什么会这样」，增加人物深度"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            pos_idx = target_positions[idx] if idx < len(target_positions) else min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "action_detail":
        analysis = analyze_action_detail(paragraphs)
        target_positions = list(analysis.get("action_paragraph_indices", []))
        if not target_positions:
            target_positions = [i for i in range(min(num_suggestions, len(paragraphs)))]

        templates = [
            ("拆解关键动作的全过程",
             "不是「他出拳打飞了对方」，是「拳头擦着风声过去，对方格挡的手臂弯了一个不该弯的角度」"),
            ("补充动作的身体后果",
             "打完后的手麻、肩酸、喘息、踉跄，让动作有代价感"),
            ("利用环境道具增强动作画面感",
             "武器划破空气的啸声、脚步踩碎瓦片的脆响、墙体被撞击后的裂痕"),
            ("动作间的节奏变化",
             "快-慢-快的节奏交替：暴风骤雨的连击后，一个定格的慢动作特写"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            pos_idx = target_positions[idx % len(target_positions)] if target_positions else min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "transition_smoothing":
        analysis = analyze_transitions(paragraphs)
        target_positions = list(analysis.get("abrupt_positions", []))
        # 如果没有突兀过渡，也建议在场景切换处优化
        if len(target_positions) < num_suggestions:
            for i in range(1, len(paragraphs)):
                if i not in target_positions:
                    target_positions.append(i)
                    if len(target_positions) >= num_suggestions:
                        break

        templates = [
            ("用角色的位移过渡场景",
             "不要「忽然到了XX」，而是「穿过三道门，转过回廊尽头，才看到那扇紧闭的铁门」"),
            ("用时间流逝的感知过渡",
             "通过光影变化、身体疲劳、事件进度来暗示时间推移，而非「三天后」"),
            ("用感官切换过渡视角",
             "上一段在看，下一段从听开始：「脚步声从走廊尽头传来时，他正盯着墙上的画」"),
            ("用角色思绪串联场景",
             "让角色在上一个场景的思考延续到下一个场景，用内心线索串联空间切换"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            pos_idx = target_positions[idx] if idx < len(target_positions) else min(idx+1, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "worldbuilding":
        analysis = analyze_worldbuilding(paragraphs)
        target_positions = list(analysis.get("implantable_paragraph_indices", []))
        if len(target_positions) < num_suggestions:
            for i in range(len(paragraphs)):
                if i not in target_positions:
                    target_positions.append(i)
                    if len(target_positions) >= num_suggestions:
                        break

        templates = [
            ("通过角色视角自然带出势力格局",
             "让角色在行走/观察中注意到某势力的标记、服饰、建筑风格，顺带交代势力关系"),
            ("用道具/建筑展示世界规则",
             "角色触碰某件物品时，自然解释其运行原理、等级体系、稀有程度"),
            ("通过传闻/闲话植入历史背景",
             "让路人对话或告示牌信息带出历史事件、上古传说、地域渊源"),
            ("在行动中展示修炼/能力体系",
             "角色使用能力时，交代境界划分、功法层级、资源消耗等设定细节"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            pos_idx = target_positions[idx] if idx < len(target_positions) else min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "foreshadowing":
        analysis = analyze_foreshadowing(paragraphs)
        slots = analysis.get("foreshadowing_slots", [])

        templates = [
            ("章节开头：植入环境异常感",
             "用一个不合常理的细节开场：「今天的雾气特别浓，连三步外的灯笼都看不清」"),
            ("中间过渡：角色的莫名不安",
             "在情节推进中插入一瞬的违和感：「他忽然觉得有人在看自己，回头却什么都没有」"),
            ("章节结尾：留下悬念钩子",
             "结尾处揭示一个反常信息：「他没注意到，墙角那盆枯萎的花，花瓣上凝着一滴血」"),
            ("人物对话中藏暗线",
             "让某个角色说一句当时看似无关紧要、事后回想另有深意的话"),
        ]
        for idx in range(min(num_suggestions, len(templates))):
            if idx < len(slots):
                pos_idx = slots[idx]["paragraph_index"]
            else:
                pos_idx = min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    elif strategy_code == "synesthesia":
        analysis = analyze_synesthesia(paragraphs)
        weak_senses = analysis.get("weak_senses", [])
        single_sense_paras = analysis.get("single_sense_paragraphs", [])

        sense_names = {
            "visual": "视觉", "auditory": "听觉", "olfactory": "嗅觉",
            "gustatory": "味觉", "tactile": "触觉",
        }

        templates = [
            ("为薄弱感官补充描写",
             f"当前{'、'.join(sense_names.get(s, s) for s in weak_senses) if weak_senses else '部分感官'}描写不足，可在关键场景补充"),
            ("单感官段落扩充为多感官",
             "只有视觉的场景加入声音和气味：「画面之外，还能闻到焦糊味，听见噼啪的燃烧声」"),
            ("用通感修辞强化情绪",
             "跨感官比喻：「她的声音冷得像冰」「那颜色尖厉得刺耳」，用感官错位增强冲击力"),
            ("情绪高潮处的感官轰炸",
             "在关键情节节点同时调动多感官：视觉冲击+听觉轰鸣+触觉震颤，形成沉浸式体验"),
        ]
        target_positions = single_sense_paras[:num_suggestions] if single_sense_paras else list(range(min(num_suggestions, len(paragraphs))))
        for idx in range(min(num_suggestions, len(templates))):
            pos_idx = target_positions[idx] if idx < len(target_positions) else min(idx, len(paragraphs)-1)
            location = _describe_location(pos_idx, len(paragraphs))
            direction, example = templates[idx]
            suggestions.append({
                "strategy": strategy_code,
                "location": location,
                "paragraph_index": pos_idx,
                "direction": direction,
                "example": example,
            })

    return suggestions


def _describe_location(paragraph_index: int, total_paragraphs: int) -> str:
    """描述段落在章节中的位置。"""
    if total_paragraphs <= 0:
        return "未知位置"
    ratio = paragraph_index / total_paragraphs
    if ratio < 0.15:
        return "开头"
    elif ratio < 0.35:
        return "前中段"
    elif ratio < 0.65:
        return "中间"
    elif ratio < 0.85:
        return "后中段"
    else:
        return "结尾"


# =========================================================
# 完整分析（v1.0 兼容 + v2.0 增强）
# =========================================================

def analyze_text(text: str, target_chars: int = 3000, chapter_type: Optional[str] = None) -> Dict[str, Any]:
    """全面分析文本，输出扩充建议（v2.0 增强版）。"""
    paragraphs = split_paragraphs(text)
    total_chars = count_chars(text)
    chinese_chars = count_chinese_chars(text)
    gap = max(0, target_chars - total_chars)

    # 八种策略分析
    scene_analysis = analyze_scene_depth(paragraphs)
    dialogue_analysis = analyze_dialogue_quality(text, paragraphs)
    psych_analysis = analyze_psychological_depth(paragraphs)
    action_analysis = analyze_action_detail(paragraphs)
    transition_analysis = analyze_transitions(paragraphs)
    worldbuilding_analysis = analyze_worldbuilding(paragraphs)
    foreshadowing_analysis = analyze_foreshadowing(paragraphs)
    synesthesia_analysis = analyze_synesthesia(paragraphs)

    # 章节类型推断
    inferred_type, type_scores = infer_chapter_type(text, paragraphs)
    final_type = chapter_type if chapter_type else inferred_type

    # 优先级计算
    priorities = calculate_priorities(text, paragraphs, target_chars, final_type)

    # 策略组合推荐
    combo = recommend_strategy_combo(priorities)

    # 主策略具体建议
    primary_suggestions = []
    if combo["primary"]:
        primary_suggestions = generate_concrete_suggestions(
            combo["primary"]["code"], paragraphs, text, num_suggestions=4
        )

    # 辅助策略具体建议
    secondary_suggestions = []
    for sec in combo["secondary"]:
        sec_sugs = generate_concrete_suggestions(sec["code"], paragraphs, text, num_suggestions=2)
        secondary_suggestions.extend(sec_sugs)

    # 估算增字（基于建议条数 * 效率）
    total_estimate = 0
    for s in primary_suggestions + secondary_suggestions:
        total_estimate += EXPANSION_EFFICIENCY.get(s["strategy"], 100)

    return {
        "version": VERSION,
        "file": "",
        "total_chars": total_chars,
        "chinese_chars": chinese_chars,
        "target_chars": target_chars,
        "char_gap": gap,
        "paragraph_count": len(paragraphs),
        "needs_expansion": gap > 100,
        "chapter_type": final_type,
        "chapter_type_inferred": inferred_type,
        "chapter_type_scores": type_scores,
        "priorities": [
            {"code": code, "name": STRATEGY_NAMES.get(code, code), "weight": weight, "reason": reason}
            for code, weight, reason in priorities
        ],
        "strategy_combo": combo,
        "primary_suggestions": primary_suggestions,
        "secondary_suggestions": secondary_suggestions,
        "estimated_expansion_total": total_estimate,
        "details": {
            "scene": scene_analysis,
            "dialogue": dialogue_analysis,
            "psychological": psych_analysis,
            "action": action_analysis,
            "transition": transition_analysis,
            "worldbuilding": worldbuilding_analysis,
            "foreshadowing": foreshadowing_analysis,
            "synesthesia": synesthesia_analysis,
        },
    }


# =========================================================
# 人类可读报告生成
# =========================================================

def generate_suggestions(analysis: Dict[str, Any]) -> str:
    """生成人类可读的扩充建议报告（v2.0 增强版）。"""
    lines = []
    lines.append("# 内容扩充建议报告")
    lines.append(f"\n生成引擎：content_expander.py v{VERSION}")
    lines.append(f"\n## 基本信息")
    lines.append(f"- 当前字数：{analysis['total_chars']}（汉字 {analysis['chinese_chars']}）")
    lines.append(f"- 目标字数：{analysis['target_chars']}")
    lines.append(f"- 字数缺口：{analysis['char_gap']}")
    lines.append(f"- 段落数：{analysis['paragraph_count']}")
    lines.append(f"- 章节类型：{analysis['chapter_type']}（自动推断：{analysis['chapter_type_inferred']}）")

    if not analysis["needs_expansion"]:
        lines.append("\n✅ 字数达标，无需扩充。")
        return "\n".join(lines)

    # 优先级排序
    lines.append(f"\n## 扩充策略优先级排序（8种）")
    for i, s in enumerate(analysis["priorities"], 1):
        lines.append(f"{i}. **{s['name']}** ({s['code']}) — 权重: {s['weight']} | 理由: {s['reason']}")

    # 推荐组合
    combo = analysis["strategy_combo"]
    lines.append(f"\n## 推荐策略组合（1主+2辅）")
    if combo["primary"]:
        p = combo["primary"]
        lines.append(f"- **主策略**：{p['name']}（权重 {p['weight']}）— {p['reason']}")
    for j, s in enumerate(combo["secondary"], 1):
        lines.append(f"- **辅助策略{j}**：{s['name']}（权重 {s['weight']}）— {s['reason']}")
    lines.append(f"- **预估增字量**：约 {combo['estimated_expansion_chars']} 字")
    lines.append(f"- **组合评分**：{combo['combo_score']}")

    # 具体建议 - 主策略
    lines.append(f"\n## 主策略具体建议（{combo['primary']['name'] if combo['primary'] else '无'}）")
    for i, sug in enumerate(analysis["primary_suggestions"], 1):
        lines.append(f"\n### 建议 {i}：{sug['direction']}")
        lines.append(f"- **位置**：第 {sug['paragraph_index']+1} 段（{sug['location']}）")
        lines.append(f"- **扩写方向**：{sug['example']}")

    # 具体建议 - 辅助策略
    if analysis["secondary_suggestions"]:
        lines.append(f"\n## 辅助策略具体建议")
        current_strategy = None
        idx_count = 0
        for sug in analysis["secondary_suggestions"]:
            sname = STRATEGY_NAMES.get(sug["strategy"], sug["strategy"])
            if sname != current_strategy:
                current_strategy = sname
                idx_count = 0
                lines.append(f"\n### 【{sname}】")
            idx_count += 1
            lines.append(f"\n**建议 {idx_count}**：{sug['direction']}")
            lines.append(f"- 位置：第 {sug['paragraph_index']+1} 段（{sug['location']}）")
            lines.append(f"- 扩写方向：{sug['example']}")

    # 各维度详细分析
    lines.append("\n## 各维度详细分析")
    details = analysis["details"]

    # 1. 场景
    scene = details["scene"]
    lines.append(f"\n### 1. 场景扩充 (scene_expansion)")
    lines.append(f"- 含场景描写的段落：{scene['scene_paragraph_count']}/{scene['total_paragraphs']} ({scene['scene_ratio']:.1%})")
    lines.append(f"- 扩充潜力：{scene['expansion_potential']}")
    if scene["needs_expansion"]:
        lines.append("- ⚠️ 场景描写不足")

    # 2. 对话
    dialogue = details["dialogue"]
    lines.append(f"\n### 2. 对话丰富 (dialogue_enrichment)")
    lines.append(f"- 对话占比：{dialogue['dialogue_ratio']:.1%}")
    lines.append(f"- 对话数量：{dialogue['dialogue_count']}（短{dialogue['short_dialogues']}/中{dialogue['medium_dialogues']}/长{dialogue['long_dialogues']}）")
    lines.append(f"- 带动作垫底的对话：{dialogue['dialogues_with_action']}")
    lines.append(f"- 扩充潜力：{dialogue['expansion_potential']}")
    if dialogue["needs_enrichment"]:
        lines.append("- ⚠️ 对话占比偏低")

    # 3. 心理
    psych = details["psychological"]
    lines.append(f"\n### 3. 心理深度 (psychological_depth)")
    lines.append(f"- 含心理描写的段落：{psych['psych_paragraph_count']}/{psych['total_paragraphs']} ({psych['psych_ratio']:.1%})")
    lines.append(f"- 直接告知情绪词：{psych['direct_emotion_count']} 处")
    lines.append(f"- 扩充潜力：{psych['expansion_potential']}")
    if psych["needs_deepening"]:
        lines.append("- ⚠️ 心理描写不足或过度直白")

    # 4. 动作
    action = details["action"]
    lines.append(f"\n### 4. 动作细节 (action_detail)")
    lines.append(f"- 动作密集段：{action['action_paragraph_count']}")
    lines.append(f"- 过短动作段：{action['short_action_paragraphs']}")
    lines.append(f"- 扩充潜力：{action['expansion_potential']}")
    if action["needs_detailing"]:
        lines.append("- ⚠️ 动作描写过短")

    # 5. 过渡
    transition = details["transition"]
    lines.append(f"\n### 5. 过渡润滑 (transition_smoothing)")
    lines.append(f"- 突兀过渡：{transition['abrupt_transition_count']} 处")
    lines.append(f"- 扩充潜力：{transition['expansion_potential']}")
    if transition["needs_smoothing"]:
        lines.append(f"- ⚠️ 过渡突兀位置：{transition['abrupt_positions']}")

    # 6. 世界观
    wb = details["worldbuilding"]
    lines.append(f"\n### 6. 世界观植入 (worldbuilding)")
    lines.append(f"- 含设定信息的段落：{wb['worldbuilding_paragraph_count']}/{wb['total_paragraphs']} ({wb['worldbuilding_ratio']:.1%})")
    lines.append(f"- 设定关键词提及：{wb['worldbuilding_mentions']} 次")
    lines.append(f"- 可植入段落：{wb['implantable_count']} 处")
    lines.append(f"- 扩充潜力：{wb['expansion_potential']}")
    if wb["needs_embedding"]:
        lines.append("- ⚠️ 世界观信息偏少，有植入空间")

    # 7. 伏笔
    fs = details["foreshadowing"]
    lines.append(f"\n### 7. 伏笔埋设 (foreshadowing)")
    lines.append(f"- 含伏笔/悬念词的段落：{fs['foreshadowing_paragraph_count']}/{fs['total_paragraphs']} ({fs['foreshadowing_ratio']:.1%})")
    lines.append(f"- 伏笔词提及：{fs['foreshadowing_mentions']} 次")
    lines.append(f"- 可埋设位置：{fs['slot_count']} 处")
    lines.append(f"- 扩充潜力：{fs['expansion_potential']}")
    if fs["needs_foreshadowing"]:
        lines.append("- ⚠️ 伏笔密度偏低")

    # 8. 感官通感
    syn = details["synesthesia"]
    lines.append(f"\n### 8. 感官通感 (synesthesia)")
    sense_names = {"visual": "视觉", "auditory": "听觉", "olfactory": "嗅觉", "gustatory": "味觉", "tactile": "触觉"}
    lines.append(f"- 感官丰富度：{syn['sense_diversity']}/5 种")
    lines.append(f"- 活跃感官：{'、'.join(sense_names.get(s, s) for s in syn['active_senses'])}")
    lines.append(f"- 薄弱感官：{'、'.join(sense_names.get(s, s) for s in syn['weak_senses']) if syn['weak_senses'] else '无'}")
    lines.append(f"- 单感官段落：{len(syn['single_sense_paragraphs'])} 处")
    lines.append(f"- 扩充潜力：{syn['expansion_potential']}")
    if syn["needs_enrichment"]:
        lines.append("- ⚠️ 感官描写不够丰富")

    lines.append("\n## 扩充纪律")
    lines.append("- 扩充不是注水：每句新增内容必须服务于情绪/人设/剧情/信息四职之一")
    lines.append("- 扩充有上限：单章扩充不超过原字数的30%，超过应考虑拆章")
    lines.append("- 扩充后必须重跑 check_text.py 确认无新增AI腔")
    lines.append("- 扩充后必须重跑 rhythm_guard.py 确认节奏配额无越界")

    return "\n".join(lines)


def generate_expansion_plan(analysis: Dict[str, Any]) -> str:
    """生成完整扩充方案（精简版，聚焦行动项）。"""
    lines = []
    lines.append("# 完整扩充方案")
    lines.append(f"\n引擎版本：v{VERSION}")
    lines.append(f"\n## 概览")
    lines.append(f"- 当前字数：{analysis['total_chars']} / 目标：{analysis['target_chars']}")
    lines.append(f"- 字数缺口：{analysis['char_gap']} 字")
    lines.append(f"- 章节类型：{analysis['chapter_type']}")
    lines.append(f"- 预估可扩充：约 {analysis['estimated_expansion_total']} 字")

    combo = analysis["strategy_combo"]
    lines.append(f"\n## 策略组合")
    if combo["primary"]:
        lines.append(f"- 主策略：**{combo['primary']['name']}**（{combo['primary']['code']}）")
    for j, s in enumerate(combo["secondary"], 1):
        lines.append(f"- 辅助{j}：{s['name']}（{s['code']}）")

    lines.append(f"\n## 行动清单")

    all_suggestions = analysis["primary_suggestions"] + analysis["secondary_suggestions"]
    for i, sug in enumerate(all_suggestions, 1):
        sname = STRATEGY_NAMES.get(sug["strategy"], sug["strategy"])
        lines.append(f"\n### [{i}] {sname} — {sug['direction']}")
        lines.append(f"- 位置：第 {sug['paragraph_index']+1} 段（{sug['location']}）")
        lines.append(f"- 操作：{sug['example']}")
        lines.append(f"- 预估增字：约 {EXPANSION_EFFICIENCY.get(sug['strategy'], 100)} 字")

    lines.append(f"\n## 注意事项")
    lines.append("- 优先执行主策略建议，再酌情执行辅助策略")
    lines.append("- 扩充过程中注意节奏平衡，不要让某一维度过度膨胀")
    lines.append("- 扩充后请重新运行 analyze 验证效果")

    return "\n".join(lines)


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
        description="智能内容扩充引擎 v2.0 — 分析章节并给出结构化扩充建议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # analyze 命令
    p_analyze = sub.add_parser("analyze", help="全面分析文本并输出扩充建议")
    p_analyze.add_argument("file", help="章节文件路径")
    p_analyze.add_argument("--target", type=int, default=3000, help="目标字数（默认 3000）")
    p_analyze.add_argument("--type", choices=CHAPTER_TYPES, help="章节类型（默认自动推断）")
    p_analyze.add_argument("--json", action="store_true", help="输出 JSON 格式")
    p_analyze.add_argument("--output", help="输出文件路径（默认 stdout）")

    # suggest 命令
    p_suggest = sub.add_parser("suggest", help="针对特定策略生成详细建议")
    p_suggest.add_argument("file", help="章节文件路径")
    p_suggest.add_argument("--strategy", choices=list(STRATEGY_NAMES.keys()),
                          required=True, help="扩充策略")
    p_suggest.add_argument("--target", type=int, default=3000, help="目标字数")
    p_suggest.add_argument("--num", type=int, default=4, help="建议条数（默认 4）")

    # priority 命令
    p_priority = sub.add_parser("priority", help="输出策略优先级分析")
    p_priority.add_argument("file", help="章节文件路径")
    p_priority.add_argument("--target", type=int, default=3000, help="目标字数")
    p_priority.add_argument("--type", choices=CHAPTER_TYPES, help="章节类型（默认自动推断）")
    p_priority.add_argument("--json", action="store_true", help="输出 JSON 格式")

    # expand 命令
    p_expand = sub.add_parser("expand", help="生成完整扩充方案")
    p_expand.add_argument("file", help="章节文件路径")
    p_expand.add_argument("--target", type=int, default=3000, help="目标字数")
    p_expand.add_argument("--type", choices=CHAPTER_TYPES, help="章节类型（默认自动推断）")
    p_expand.add_argument("--json", action="store_true", help="输出 JSON 格式")
    p_expand.add_argument("--output", help="输出文件路径（默认 stdout）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "analyze":
        text = load_text(args.file)
        analysis = analyze_text(text, args.target, getattr(args, "type", None))
        analysis["file"] = args.file

        if args.json:
            output = json.dumps(analysis, ensure_ascii=False, indent=2)
        else:
            output = generate_suggestions(analysis)

        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"报告已写入 {args.output}")
        else:
            print(output)

    elif args.command == "suggest":
        text = load_text(args.file)
        paragraphs = split_paragraphs(text)
        suggestions = generate_concrete_suggestions(args.strategy, paragraphs, text, args.num)
        print(json.dumps(suggestions, ensure_ascii=False, indent=2))

    elif args.command == "priority":
        text = load_text(args.file)
        paragraphs = split_paragraphs(text)
        chapter_type = getattr(args, "type", None)
        priorities = calculate_priorities(text, paragraphs, args.target, chapter_type)
        inferred_type, type_scores = infer_chapter_type(text, paragraphs)

        if args.json:
            result = {
                "chapter_type": chapter_type or inferred_type,
                "inferred_type": inferred_type,
                "type_scores": type_scores,
                "priorities": [
                    {"code": code, "name": STRATEGY_NAMES.get(code, code),
                     "weight": weight, "reason": reason}
                    for code, weight, reason in priorities
                ],
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"章节类型：{chapter_type or inferred_type}（推断：{inferred_type}）")
            print(f"类型置信度：{ {k: round(v, 4) for k, v in type_scores.items()} }")
            print()
            print("策略优先级排序：")
            for i, (code, weight, reason) in enumerate(priorities, 1):
                name = STRATEGY_NAMES.get(code, code)
                print(f"  {i}. {name} ({code}) — 权重: {weight}")
                print(f"     理由: {reason}")

    elif args.command == "expand":
        text = load_text(args.file)
        analysis = analyze_text(text, args.target, getattr(args, "type", None))
        analysis["file"] = args.file

        if args.json:
            output = json.dumps(analysis, ensure_ascii=False, indent=2)
        else:
            output = generate_expansion_plan(analysis)

        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"方案已写入 {args.output}")
        else:
            print(output)


if __name__ == "__main__":
    main()
