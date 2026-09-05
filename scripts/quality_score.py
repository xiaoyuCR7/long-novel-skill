#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_score.py — 章节文本统计观察 v1.0（纯标准库，无第三方依赖）。

从多个维度统计章节正文，输出兼容旧版的启发式加权分和维度雷达。
结果可落盘到 追踪/质量评分/quality_ch{N}.json，供 trend 汇总统计趋势。
本脚本不执行独立机器门禁或语义审稿，两者均明确记录为 not_run。
total_score、grade、passed 仅解释统计规则，不能代表文学质量或审稿结论。

七维评分体系（每维 0-100，加权求总分）：
  1. 用词句式统计 (权重 20%) — 本地词表和句式匹配，不调用 check_text.py
  2. 节奏统计     (权重 15%) — 长度/转换词/配额表近似，不调用 rhythm_guard.py
  3. 文风指标偏离 (权重 15%) — 本地指标与可选文风锚的近似比较
  4. 情绪词与动作词统计 (权重 15%) — 词表、标点命中，不判断情感效果
  5. 结构标记统计 (权重 15%) — 四段位置的关键词匹配，不判断因果或闭合
  6. 对话统计     (权重 10%) — 对话占比/标签密度/词表命中
  7. 阅读形式统计 (权重 10%) — 段落长度/句长分布/过渡词密度

统计分段（保留旧等级字母，不作为文学等级）：
  85-100 A；70-84 B；55-69 C；40-54 D；0-39 F。

子命令：
  score    评分单章，输出 JSON 报告 + 可选 Markdown 摘要
  trend    汇总多章评分趋势（折线图文本 + 均值/方差）

用法：
  python3 scripts/quality_score.py score "正文/第037章.md" --chapter 37
  python3 scripts/quality_score.py score "正文/第037章.md" --chapter 37 --book-dir "."
  python3 scripts/quality_score.py trend --book-dir "." --from 30 --to 40

score 退出码：0 = 达到统计阈值 55；1 = 低于统计阈值；2 = 参数/文件错误。
trend 退出码：0 = 成功读取统计报告；2 = 参数/文件错误。均不表示审稿通过。
为保持现有退出码兼容，--threshold 仍为保留参数，不改变固定阈值 55。
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.0.0"

# =========================================================
# 常量
# =========================================================

DIMENSIONS = [
    {"key": "ai_control", "name": "用词句式统计", "weight": 20},
    {"key": "rhythm", "name": "节奏统计", "weight": 15},
    {"key": "style_consistency", "name": "文风指标偏离", "weight": 15},
    {"key": "emotional_impact", "name": "情绪词与动作词统计", "weight": 15},
    {"key": "structure", "name": "结构标记统计", "weight": 15},
    {"key": "dialogue", "name": "对话统计", "weight": 10},
    {"key": "readability", "name": "阅读形式统计", "weight": 10},
]

GRADE_THRESHOLDS = [
    (85, "A", "统计高分段"),
    (70, "B", "统计中高分段"),
    (55, "C", "统计中分段"),
    (40, "D", "统计低分段"),
    (0, "F", "统计极低分段"),
]

DEFAULT_THRESHOLD = 55
SCORE_DIR = "追踪/质量评分"
SCORE_SCOPE = "heuristic_observation"
SCORE_LIMITATIONS = (
    "本报告仅含启发式文本统计；分数、等级和规则提示不代表文学质量，"
    "不构成机器门禁或语义审稿结论。问题字段 issues 仅供定位复核，不能直接作为改稿依据。"
)
EMOTION_LIMITATIONS = (
    "情绪词、动作词和标点命中不等于情绪效果，也不能判断人物选择与因果。"
    "须结合题材和场景意图复核；安静、日常或含蓄场景的低词频不能据此要求改写，"
    "增加词频也不能证明文学质量提高。"
)


# =========================================================
# 工具函数
# =========================================================

def read_text(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def count_chars(text: str) -> Tuple[int, int]:
    non_ws = len(re.sub(r"\s+", "", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    return non_ws, cjk


def split_paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return lines
    return paras


def split_sentences(text: str) -> List[str]:
    sentences = re.split(r"[。！？!?…\n]+", text)
    return [s.strip() for s in sentences if s.strip()]


def extract_dialogue(text: str) -> str:
    """提取对话内容（引号内）。"""
    quotes = re.findall(r'[""「」『』]([^""「」『』]+)[""「」『』]', text)
    return "\n".join(quotes)


def clamp_score(score: float) -> float:
    return max(0.0, min(100.0, score))


def get_grade(total: float) -> Tuple[str, str]:
    for threshold, grade, label in GRADE_THRESHOLDS:
        if total >= threshold:
            return grade, label
    return "F", "统计极低分段"


def observation_boundary() -> Dict[str, Any]:
    """本工具没有执行其他审核；旧报告缺少状态时也不能从分数推断。"""
    return {
        "score_scope": SCORE_SCOPE,
        "limitations": SCORE_LIMITATIONS,
        "semantic_review": {
            "status": "not_run", "judgment": None,
            "reason": "本工具未执行语义复核；需结合原文证据、人物选择、因果和场景功能另行审阅。",
        },
        "machine_gates": {
            "status": "not_run", "checks": [],
            "reason": "本工具未执行独立机器门禁；局部词表和统计阈值不等同于门禁校验。",
        },
    }


def statistical_issue(issue: str) -> str:
    """旧 JSON 的情绪提示仅转为统计说明，不修改源文件。"""
    return (issue.replace("情感冲击力", "情绪词与动作词统计")
            .replace("情绪密度过低", "情绪词命中密度处于统计低值，需结合场景意图复核")
            .replace("动作描写过少", "动作词表命中处于统计低值，不代表缺少有效动作描写"))


# =========================================================
# 维度1：AI腔控制评分（复用 check_text.py 逻辑）
# =========================================================

# 禁用词清单（子集，与 anti-ai-style.md 同步）
AI_HIGH_FREQ_WORDS = [
    "不禁", "缓缓", "微微", "嘴角勾起", "眼中闪过", "深吸一口气",
    "不由得", "仿佛", "宛如", "犹如", "心头一震", "瞳孔一缩",
    "嘴角上扬", "目光深邃", "若有若无", "不动声色", "意味深长",
    "心旷神怡", "如释重负", "心如止水", "心如刀割",
]

# 毒句式正则（子集）
AI_TOXIC_PATTERNS = [
    (r"不是.{1,15}[，,].{0,5}而是", "反序对比"),
    (r"没有.{1,10}[，,].{0,5}没有.{1,10}[，,].{0,5}没有", "三重否定排比"),
    (r"之所以.{1,20}是因为", "解释腔"),
    (r"她?不知道的是", "上帝视角剧透"),
    (r"这意味着", "总结升华"),
    (r"命运的齿轮", "套话升华"),
    (r"才刚刚开始", "预告式收尾"),
    (r"心中.{0,3}暗想", "心理告知"),
    (r"他?她?感到", "情绪告知"),
    (r"仿佛.{1,20}般", "比喻套路"),
]

# 工程词
ENGINEERING_WORDS = [
    "伏笔", "钩子", "章纲", "大纲", "细纲", "情节点", "本章目标",
    "读者", "作者", "视角", "POV", "人设", "设定集",
]


def score_ai_control(text: str) -> Dict[str, Any]:
    """维度1：AI腔控制评分。"""
    non_ws, cjk = count_chars(text)
    if cjk == 0:
        return {"score": 0, "details": {"error": "无汉字"}, "issues": ["无汉字内容"]}

    # 叙述/对话分离
    dialogue = extract_dialogue(text)
    narration = text
    for q in re.findall(r'[""「」『』][^""「」『』]+[""「」『』]', text):
        narration = narration.replace(q, "")

    # 1. 禁用词密度
    ai_word_hits = []
    for word in AI_HIGH_FREQ_WORDS:
        count = narration.count(word)
        if count > 0:
            ai_word_hits.append({"word": word, "count": count})
    total_ai_words = sum(h["count"] for h in ai_word_hits)
    ai_word_density = total_ai_words / (cjk / 1000) if cjk > 0 else 0

    # 2. 毒句式
    toxic_hits = []
    for pattern, name in AI_TOXIC_PATTERNS:
        matches = re.findall(pattern, narration)
        if matches:
            toxic_hits.append({"pattern": name, "count": len(matches)})
    total_toxic = sum(h["count"] for h in toxic_hits)

    # 3. 工程词泄漏
    eng_hits = []
    for word in ENGINEERING_WORDS:
        count = text.count(word)
        if count > 0:
            eng_hits.append({"word": word, "count": count})
    total_eng = sum(h["count"] for h in eng_hits)

    # 4. 排比检测（连续3+相似结构）
    para_list = split_paragraphs(narration)
    parallelism_count = 0
    for para in para_list:
        sentences = split_sentences(para)
        if len(sentences) >= 3:
            for i in range(len(sentences) - 2):
                s1, s2, s3 = sentences[i], sentences[i + 1], sentences[i + 2]
                if len(s1) > 5 and len(s2) > 5 and len(s3) > 5:
                    if abs(len(s1) - len(s2)) <= 3 and abs(len(s2) - len(s3)) <= 3:
                        parallelism_count += 1

    # 5. 心理告知密度
    psych_markers = ["他想", "她想", "他觉得", "她觉得", "他感到", "她感到",
                     "心中暗想", "内心深处", "他意识到", "她意识到"]
    psych_count = sum(narration.count(m) for m in psych_markers)
    psych_density = psych_count / (cjk / 1000) if cjk > 0 else 0

    # 6. 对话标签密度
    tag_words = ["说道", "问道", "答道", "喊道", "笑道", "怒道", "冷道",
                 "低声道", "大声道", "轻声道"]
    tag_count = sum(text.count(t) for t in tag_words)
    dialogue_sentences = len(re.findall(r'[""「」『』][^""「」『』]+[""「」『』]', text))
    tag_density = tag_count / dialogue_sentences if dialogue_sentences > 0 else 0

    # 7. 结尾升华检测
    last_para = para_list[-1] if para_list else ""
    summary_markers = ["这一", "注定", "从此", "就这样", "一切", "终于明白",
                       "真正重要的是", "这意味着"]
    has_summary_ending = any(m in last_para for m in summary_markers)

    # 评分计算（扣分制，从100开始）
    score = 100.0
    issues = []

    # 禁用词：每千字1个扣3分
    ded = ai_word_density * 3
    score -= ded
    if ai_word_density > 3:
        issues.append(f"禁用词密度过高: {ai_word_density:.1f}/千字")

    # 毒句式：每个扣5分
    score -= total_toxic * 5
    if total_toxic > 0:
        issues.append(f"毒句式命中 {total_toxic} 处")

    # 工程词：每个扣8分
    score -= total_eng * 8
    if total_eng > 0:
        issues.append(f"工程词泄漏 {total_eng} 处")

    # 排比：每组扣4分
    score -= parallelism_count * 4
    if parallelism_count > 2:
        issues.append(f"连续排比 {parallelism_count} 组")

    # 心理告知：每千字1个扣2分
    score -= psych_density * 2

    # 对话标签过密：>0.8扣分
    if tag_density > 0.8:
        score -= (tag_density - 0.8) * 30
        issues.append(f"对话标签过密: {tag_density:.2f}")

    # 结尾升华
    if has_summary_ending:
        score -= 10
        issues.append("结尾升华/总结")

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "ai_word_density": round(ai_word_density, 2),
            "ai_word_hits": ai_word_hits[:5],
            "toxic_hits": toxic_hits,
            "engineering_leaks": eng_hits,
            "parallelism_count": parallelism_count,
            "psych_density": round(psych_density, 2),
            "tag_density": round(tag_density, 2),
            "summary_ending": has_summary_ending,
        },
        "issues": issues,
    }


# =========================================================
# 维度2：节奏控制评分
# =========================================================

def score_rhythm(text: str, book_dir: Optional[Path] = None,
                 chapter: Optional[int] = None) -> Dict[str, Any]:
    """维度2：节奏控制评分。"""
    non_ws, cjk = count_chars(text)
    paras = split_paragraphs(text)
    sentences = split_sentences(text)

    if not sentences:
        return {"score": 0, "details": {"error": "无有效句子"}, "issues": ["无有效句子"]}

    # 1. 段落长度分布
    para_lengths = [count_chars(p)[0] for p in paras]
    avg_para = sum(para_lengths) / len(para_lengths) if para_lengths else 0

    # 段落长度方差（检测是否过于均匀）
    if len(para_lengths) > 1:
        variance = sum((l - avg_para) ** 2 for l in para_lengths) / len(para_lengths)
        std_dev = variance ** 0.5
    else:
        std_dev = 0

    # 2. 句长分布
    sent_lengths = [count_chars(s)[0] for s in sentences]
    avg_sent = sum(sent_lengths) / len(sent_lengths) if sent_lengths else 0

    # 长短句交替
    short_sents = sum(1 for l in sent_lengths if 0 < l < 10)
    long_sents = sum(1 for l in sent_lengths if l > 20)
    alternation_ratio = short_sents / long_sents if long_sents > 0 else short_sents

    # 3. 对话/叙述比
    dialogue = extract_dialogue(text)
    dialogue_chars = count_chars(dialogue)[0]
    dialogue_ratio = dialogue_chars / non_ws if non_ws > 0 else 0

    # 4. 场景转换密度
    transition_markers = ["随后", "接着", "与此同时", "不久", "紧接着",
                          "这时", "就在", "正当", "忽然", "突然", "这时"]
    transition_count = sum(text.count(t) for t in transition_markers)
    transition_density = transition_count / (cjk / 1000) if cjk > 0 else 0

    # 5. 检查节奏配额文件（如果有）
    quota_penalty = 0
    quota_issues = []
    if book_dir and chapter:
        quota_file = book_dir / "追踪" / "节奏配额.md"
        if quota_file.exists():
            quota_text = read_text(quota_file)
            if quota_text:
                # 简单检查：本章是否有配额声明
                ch_pattern = rf"\|\s*{chapter}\s*\|"
                if re.search(ch_pattern, quota_text):
                    # 检查是否有连续快档
                    recent_chs = []
                    for m in re.finditer(r"\|\s*(\d+)\s*\|\s*(快|慢|中)", quota_text):
                        ch_num = int(m.group(1))
                        gear = m.group(2)
                        if ch_num <= chapter and ch_num >= chapter - 3:
                            recent_chs.append((ch_num, gear))
                    recent_chs.sort()
                    if len(recent_chs) >= 2:
                        fast_count = sum(1 for _, g in recent_chs if g == "快")
                        if fast_count >= 2 and recent_chs[-1][1] == "快":
                            quota_penalty = 15
                            quota_issues.append("连续快档")

    # 评分
    score = 100.0
    issues = []

    # 段落过于均匀（std_dev 太小）
    if 0 < avg_para < 500 and std_dev < avg_para * 0.3:
        score -= 10
        issues.append("段落长度过于均匀")

    # 句长过于均匀
    if sent_lengths and len(sent_lengths) > 5:
        sent_std = (sum((l - avg_sent) ** 2 for l in sent_lengths) / len(sent_lengths)) ** 0.5
        if sent_std < avg_sent * 0.3:
            score -= 8
            issues.append("句长过于均匀")

    # 长短句交替不足
    if alternation_ratio < 0.3 and long_sents > 5:
        score -= 10
        issues.append("长短句交替不足")

    # 对话占比异常
    if dialogue_ratio < 0.1 and cjk > 1000:
        score -= 8
        issues.append("对话占比过低")
    elif dialogue_ratio > 0.7:
        score -= 5
        issues.append("对话占比过高")

    # 场景转换过密或过疏
    if transition_density > 5:
        score -= 5
        issues.append("场景转换过密")
    elif transition_density < 0.5 and cjk > 2000:
        score -= 5
        issues.append("场景转换过疏")

    # 配额违规
    score -= quota_penalty
    issues.extend(quota_issues)

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "avg_para_length": round(avg_para, 1),
            "para_std_dev": round(std_dev, 1),
            "avg_sent_length": round(avg_sent, 1),
            "alternation_ratio": round(alternation_ratio, 2),
            "dialogue_ratio": round(dialogue_ratio, 2),
            "transition_density": round(transition_density, 2),
            "quota_penalty": quota_penalty,
        },
        "issues": issues,
    }


# =========================================================
# 维度3：文风一致性评分
# =========================================================

def score_style_consistency(text: str, book_dir: Optional[Path] = None) -> Dict[str, Any]:
    """维度3：文风一致性评分。"""
    non_ws, cjk = count_chars(text)
    sentences = split_sentences(text)
    paras = split_paragraphs(text)

    if not sentences or cjk == 0:
        return {"score": 0, "details": {"error": "文本不足"}, "issues": ["文本不足"]}

    # 计算当前章节的六维文风指标
    avg_sent = sum(count_chars(s)[0] for s in sentences) / len(sentences)

    dialogue = extract_dialogue(text)
    dialogue_chars = count_chars(dialogue)[0]
    dialogue_ratio = dialogue_chars / non_ws if non_ws > 0 else 0

    para_lengths = [count_chars(p)[0] for p in paras]
    para_lengths_sorted = sorted(para_lengths)
    median_para = para_lengths_sorted[len(para_lengths_sorted) // 2] if para_lengths_sorted else 0

    # 标点节奏
    punct_end = len(re.findall(r"[。！？!?]", text))
    punct_special = len(re.findall(r"[？…]", text))
    punct_rhythm = punct_special / punct_end if punct_end > 0 else 0

    # 句式偏好
    short_sents = sum(1 for l in [count_chars(s)[0] for s in sentences] if 0 < l < 10)
    long_sents = sum(1 for l in [count_chars(s)[0] for s in sentences] if l > 20)
    style_pref = short_sents / long_sents if long_sents > 0 else float(short_sents)

    current_metrics = {
        "avg_sent": avg_sent,
        "dialogue_ratio": dialogue_ratio * 100,
        "median_para": median_para,
        "punct_rhythm": punct_rhythm * 100,
        "style_pref": style_pref,
    }

    # 尝试加载文风锚
    anchor_metrics = None
    deviations = []
    if book_dir:
        anchor_file = book_dir / "设定" / "文风锚.md"
        if not anchor_file.exists():
            anchor_file = book_dir / "设定" / "文风指纹.md"
        if anchor_file.exists():
            anchor_text = read_text(anchor_file)
            if anchor_text:
                anchor_metrics = parse_style_anchor(anchor_text)

    if anchor_metrics:
        tolerances = [3, 5, 10, 2, 0.2]
        keys = ["avg_sent", "dialogue_ratio", "median_para", "punct_rhythm", "style_pref"]
        for i, key in enumerate(keys):
            tol = tolerances[i]
            cur = current_metrics.get(key, 0)
            anc = anchor_metrics.get(key, cur)
            diff = abs(cur - anc)
            if diff > tol:
                deviations.append({
                    "dimension": key,
                    "current": round(cur, 2),
                    "anchor": round(anc, 2),
                    "diff": round(diff, 2),
                    "tolerance": tol,
                })

    # 评分
    score = 100.0
    issues = []

    if deviations:
        # 每个偏离维度扣10分
        score -= len(deviations) * 10
        for d in deviations:
            issues.append(f"文风偏离: {d['dimension']} 偏差 {d['diff']}")

    if not anchor_metrics:
        # 没有文风锚，给中性分（不奖不罚）
        score = 75.0
        issues.append("未找到文风锚文件，按中性分评估")

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "current_metrics": {k: round(v, 2) for k, v in current_metrics.items()},
            "anchor_found": anchor_metrics is not None,
            "deviations": deviations,
        },
        "issues": issues,
    }


def parse_style_anchor(text: str) -> Optional[Dict[str, float]]:
    """从文风锚 Markdown 解析六维指标。"""
    metrics = {}
    patterns = {
        "avg_sent": r"平均句长[：:]\s*([\d.]+)",
        "dialogue_ratio": r"对话占比[：:]\s*([\d.]+)",
        "median_para": r"段落中位长度[：:]\s*([\d.]+)",
        "punct_rhythm": r"标点节奏[：:]\s*([\d.]+)",
        "style_pref": r"句式偏好[：:]\s*([\d.]+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except ValueError:
                pass
    return metrics if metrics else None


# =========================================================
# 维度4：情绪词与动作词统计
# =========================================================

def score_emotional_impact(text: str) -> Dict[str, Any]:
    """维度4：情绪词与动作词统计；保留旧数值，不判断情感效果。"""
    non_ws, cjk = count_chars(text)
    paras = split_paragraphs(text)

    if cjk < 100:
        return {"score": 0, "details": {"error": "文本过短"}, "issues": ["文本过短"],
                "score_scope": SCORE_SCOPE, "limitations": EMOTION_LIMITATIONS}

    # 1. 情绪词密度
    positive_words = ["兴奋", "激动", "开心", "喜悦", "振奋", "骄傲", "满足",
                      "温暖", "感动", "幸福", "畅快", "爽", "得意", "欣慰"]
    negative_words = ["愤怒", "悲伤", "恐惧", "绝望", "痛苦", "焦虑", "不安",
                      "紧张", "心痛", "心碎", "悲哀", "恐惧", "惆怅", "孤独"]
    intense_words = ["崩溃", "爆发", "怒吼", "咆哮", "撕心", "震怒", "狂喜",
                     "疯狂", "癫狂", "绝望"]

    pos_count = sum(text.count(w) for w in positive_words)
    neg_count = sum(text.count(w) for w in negative_words)
    intense_count = sum(text.count(w) for w in intense_words)
    total_emotion = pos_count + neg_count + intense_count
    emotion_density = total_emotion / (cjk / 1000) if cjk > 0 else 0

    # 2. 情绪转折检测
    emotion_transitions = 0
    for i in range(len(paras) - 1):
        para1 = paras[i]
        para2 = paras[i + 1]
        para1_pos = sum(para1.count(w) for w in positive_words)
        para1_neg = sum(para1.count(w) for w in negative_words)
        para2_pos = sum(para2.count(w) for w in positive_words)
        para2_neg = sum(para2.count(w) for w in negative_words)
        if (para1_neg > para1_pos and para2_pos > para2_neg) or \
           (para1_pos > para1_neg and para2_neg > para2_pos):
            emotion_transitions += 1

    # 3. 动作冲突密度
    action_verbs = ["冲", "打", "踢", "挥", "斩", "刺", "劈", "挡", "抓",
                    "推", "拉", "撞", "摔", "跃", "扑"]
    action_count = sum(text.count(v) for v in action_verbs)
    action_density = action_count / (cjk / 1000) if cjk > 0 else 0

    # 4. 感叹号密度
    excl_count = text.count("！") + text.count("!")
    excl_density = excl_count / (cjk / 1000) if cjk > 0 else 0

    # 5. 身体反应描写（替代情绪词）
    body_words = ["手抖", "颤抖", "心跳", "呼吸", "瞳孔", "拳头", "咬牙",
                  "攥紧", "掌心", "额头", "脊背", "喉结"]
    body_count = sum(text.count(w) for w in body_words)

    # 评分
    score = 60.0  # 基础分
    issues = []

    # 情绪密度
    if emotion_density > 3:
        score += 15
    elif emotion_density > 1.5:
        score += 10
    elif emotion_density > 0.5:
        score += 5
    else:
        score -= 10
        issues.append(f"情绪词命中密度: {emotion_density:.2f}/千字（统计低值，需结合场景意图复核）")

    # 情绪转折
    if emotion_transitions >= 2:
        score += 10
    elif emotion_transitions >= 1:
        score += 5
    else:
        score -= 5

    # 动作冲突
    if action_density > 5:
        score += 10
    elif action_density > 2:
        score += 5
    elif action_density < 0.5:
        score -= 5
        issues.append(f"动作词表命中密度: {action_density:.2f}/千字（统计低值，不代表缺少有效动作描写）")

    # 感叹号（适度加分，过多扣分）
    if 1 <= excl_density <= 3:
        score += 5
    elif excl_density > 5:
        score -= 5
        issues.append(f"感叹号密度: {excl_density:.2f}/千字（统计高值，需结合场景意图复核）")

    # 身体词表命中（仅保留旧计分规则，不判断展示效果）
    if body_count >= 3:
        score += 8
    elif body_count >= 1:
        score += 4

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "emotion_density": round(emotion_density, 2),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "intense_count": intense_count,
            "emotion_transitions": emotion_transitions,
            "action_density": round(action_density, 2),
            "excl_density": round(excl_density, 2),
            "body_reaction_count": body_count,
        },
        "score_scope": SCORE_SCOPE,
        "limitations": EMOTION_LIMITATIONS,
        "issues": issues,
    }


# =========================================================
# 维度5：结构完整性评分
# =========================================================

def score_structure(text: str) -> Dict[str, Any]:
    """维度5：结构完整性评分（承接→发展→结算→钩子四段式）。"""
    non_ws, cjk = count_chars(text)
    paras = split_paragraphs(text)

    if len(paras) < 4:
        return {"score": 50, "details": {"para_count": len(paras)}, "issues": ["段落过少，无法判定结构"]}

    # 将段落分为四段
    total_paras = len(paras)
    q1 = total_paras // 4
    q2 = total_paras // 2
    q3 = total_paras * 3 // 4

    sections = {
        "承接": paras[:q1] if q1 > 0 else paras[:1],
        "发展": paras[q1:q2] if q2 > q1 else paras[1:2],
        "结算": paras[q2:q3] if q3 > q2 else paras[2:3],
        "钩子": paras[q3:] if q3 < total_paras else paras[-1:],
    }

    # 1. 承接段：是否回顾上章/建立场景
    opening_text = "\n".join(sections["承接"])
    has_context = bool(re.search(r"[上昨前回]|此时|此刻|这边|那边", opening_text))
    has_scene = bool(re.search(r"天色|环境|四周|空气|光线|声音|远处|近处", opening_text))

    # 2. 发展段：是否有冲突/推进
    develop_text = "\n".join(sections["发展"])
    has_conflict = bool(re.search(r"但|然而|却|不料|突然|危机|危险|敌人|对手", develop_text))
    has_progress = bool(re.search(r"于是|因此|所以|决定|选择|开始|终于", develop_text))

    # 3. 结算段：是否有结果/收益
    settle_text = "\n".join(sections["结算"])
    has_result = bool(re.search(r"成功|失败|获得|失去|赢了|输了|结果|最终|终于", settle_text))

    # 4. 钩子段：是否有悬念/预告
    hook_text = "\n".join(sections["钩子"])
    has_suspense = bool(re.search(r"[?？]|不知道|究竟|到底|何时|如何|谁|什么", hook_text))
    has_cliffhanger = bool(re.search(r"突然|忽然|就在这时|却见|不料|此时", hook_text))
    has预告 = bool(re.search(r"明天|接下来|以后|未来|即将|将会|下一步", hook_text))

    # 评分
    score = 100.0
    issues = []

    if not has_context and not has_scene:
        score -= 10
        issues.append("承接段缺少上章回顾或场景建立")
    if not has_conflict and not has_progress:
        score -= 15
        issues.append("发展段缺少冲突或推进")
    if not has_result:
        score -= 15
        issues.append("结算段缺少明确结果")
    if not has_suspense and not has_cliffhanger and not has预告:
        score -= 20
        issues.append("钩子段缺少悬念/断章")

    # 段落比例检查
    section_lengths = {k: sum(count_chars(p)[0] for p in v) for k, v in sections.items()}
    total_len = sum(section_lengths.values())
    if total_len > 0:
        ratios = {k: v / total_len for k, v in section_lengths.items()}
        # 承接过长
        if ratios.get("承接", 0) > 0.35:
            score -= 8
            issues.append("承接段占比过高")
        # 钩子过短
        if ratios.get("钩子", 0) < 0.05:
            score -= 8
            issues.append("钩子段占比过低")
        # 发展段应是最长
        if ratios.get("发展", 0) < ratios.get("承接", 0):
            score -= 5
            issues.append("发展段短于承接段")

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "section_lengths": {k: v for k, v in section_lengths.items()},
            "has_context": has_context,
            "has_scene": has_scene,
            "has_conflict": has_conflict,
            "has_progress": has_progress,
            "has_result": has_result,
            "has_suspense": has_suspense,
            "has_cliffhanger": has_cliffhanger,
        },
        "issues": issues,
    }


# =========================================================
# 维度6：对话质量评分
# =========================================================

def score_dialogue(text: str) -> Dict[str, Any]:
    """维度6：对话质量评分。"""
    non_ws, cjk = count_chars(text)

    # 提取对话
    dialogue_matches = re.findall(r'([""「」『』])([^""「」『』]+)\1', text)
    if not dialogue_matches:
        return {"score": 70, "details": {"dialogue_count": 0}, "issues": ["无对话"]}

    dialogues = [m[1] for m in dialogue_matches]
    dialogue_text = "\n".join(dialogues)
    dialogue_chars = count_chars(dialogue_text)[0]
    dialogue_ratio = dialogue_chars / non_ws if non_ws > 0 else 0

    # 1. 对话标签密度
    tag_words = ["说道", "问道", "答道", "喊道", "笑道", "怒道", "冷道",
                 "低声道", "大声道", "轻声道", "道"]
    tag_count = sum(text.count(t) for t in tag_words)
    tag_density = tag_count / len(dialogues) if dialogues else 0

    # 2. 无标签对话占比（好现象）
    no_tag_count = 0
    for d in dialogues:
        # 检查对话前后是否有标签
        idx = text.find(d)
        if idx >= 0:
            context = text[max(0, idx - 5):idx + len(d) + 10]
            if not any(t in context for t in tag_words):
                no_tag_count += 1
    no_tag_ratio = no_tag_count / len(dialogues) if dialogues else 0

    # 3. 对话长度分布
    dial_lengths = [count_chars(d)[0] for d in dialogues]
    avg_dial = sum(dial_lengths) / len(dial_lengths) if dial_lengths else 0

    # 4. 口语化指标
    colloquial_words = ["嗯", "啊", "哦", "呃", "嘿", "哈", "嘛", "吧", "呢",
                        "呀", "喂", "嗨", "唉", "切", "滚", "靠"]
    colloquial_count = sum(dialogue_text.count(w) for w in colloquial_words)
    colloquial_density = colloquial_count / len(dialogues) if dialogues else 0

    # 5. 冲突对话检测
    conflict_words = ["你", "凭什么", "为什么", "不行", "不可能", "不要", "不能",
                      "必须", "一定", "绝不", "休想"]
    conflict_count = sum(dialogue_text.count(w) for w in conflict_words)
    has_conflict = conflict_count > len(dialogues) * 0.3

    # 6. 对话多样性（不同长度）
    if len(dial_lengths) > 1:
        dial_std = (sum((l - avg_dial) ** 2 for l in dial_lengths) / len(dial_lengths)) ** 0.5
        dial_diversity = dial_std / avg_dial if avg_dial > 0 else 0
    else:
        dial_diversity = 0

    # 评分
    score = 100.0
    issues = []

    # 对话占比
    if dialogue_ratio < 0.1:
        score -= 15
        issues.append("对话占比过低")
    elif dialogue_ratio > 0.6:
        score -= 5

    # 标签密度
    if tag_density > 0.7:
        score -= 15
        issues.append(f"对话标签过密: {tag_density:.2f}")
    elif tag_density > 0.5:
        score -= 8

    # 无标签占比（好现象）
    if no_tag_ratio > 0.5:
        score += 5
    elif no_tag_ratio < 0.2:
        score -= 5
        issues.append("几乎每句对话都有标签")

    # 口语化
    if colloquial_density > 0.5:
        score += 5
    elif colloquial_density < 0.1:
        score -= 8
        issues.append("对话缺乏口语化")

    # 冲突
    if has_conflict:
        score += 5
    else:
        score -= 3

    # 多样性
    if dial_diversity < 0.3 and len(dialogues) > 3:
        score -= 8
        issues.append("对话长度过于均匀")

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "dialogue_count": len(dialogues),
            "dialogue_ratio": round(dialogue_ratio, 2),
            "tag_density": round(tag_density, 2),
            "no_tag_ratio": round(no_tag_ratio, 2),
            "avg_dialogue_length": round(avg_dial, 1),
            "colloquial_density": round(colloquial_density, 2),
            "has_conflict": has_conflict,
            "diversity": round(dial_diversity, 2),
        },
        "issues": issues,
    }


# =========================================================
# 维度7：可读性评分
# =========================================================

def score_readability(text: str) -> Dict[str, Any]:
    """维度7：可读性评分。"""
    non_ws, cjk = count_chars(text)
    paras = split_paragraphs(text)
    sentences = split_sentences(text)

    if not sentences or cjk == 0:
        return {"score": 0, "details": {"error": "文本不足"}, "issues": ["文本不足"]}

    # 1. 平均段落长度
    para_lengths = [count_chars(p)[0] for p in paras]
    avg_para = sum(para_lengths) / len(para_lengths) if para_lengths else 0

    # 2. 长段落占比
    long_paras = sum(1 for l in para_lengths if l > 200)
    long_para_ratio = long_paras / len(paras) if paras else 0

    # 3. 句长分布
    sent_lengths = [count_chars(s)[0] for s in sentences]
    avg_sent = sum(sent_lengths) / len(sent_lengths) if sent_lengths else 0
    long_sents = sum(1 for l in sent_lengths if l > 40)
    long_sent_ratio = long_sents / len(sent_lengths) if sent_lengths else 0

    # 4. 过渡词密度
    transition_words = ["但是", "然而", "不过", "因此", "所以", "于是", "接着",
                        "随后", "然后", "这时", "此刻", "与此同时", "不久"]
    transition_count = sum(text.count(w) for w in transition_words)
    transition_density = transition_count / (cjk / 1000) if cjk > 0 else 0

    # 5. 信息密度（实词占比的近似）
    function_words = ["的", "了", "是", "在", "有", "和", "就", "不", "都",
                      "一", "上", "也", "很", "到", "说", "要", "去", "会",
                      "着", "看", "想", "这", "那", "他", "她"]
    func_count = sum(text.count(w) for w in function_words)
    func_ratio = func_count / (cjk / 10) if cjk > 0 else 0

    # 6. 空行/换行节奏
    line_count = len([l for l in text.split("\n") if l.strip()])
    short_line_ratio = sum(1 for l in text.split("\n") if l.strip() and count_chars(l)[0] < 30) / line_count if line_count else 0

    # 评分
    score = 100.0
    issues = []

    # 段落长度
    if avg_para > 150:
        score -= 10
        issues.append(f"平均段落过长: {avg_para:.0f}字")
    elif avg_para < 20:
        score -= 5

    # 长段落占比
    if long_para_ratio > 0.3:
        score -= 10
        issues.append("长段落过多")

    # 句长
    if avg_sent > 25:
        score -= 8
        issues.append(f"平均句长偏长: {avg_sent:.1f}字")
    elif avg_sent < 8:
        score -= 5

    # 长句占比
    if long_sent_ratio > 0.2:
        score -= 8

    # 过渡词
    if transition_density < 1 and cjk > 1000:
        score -= 5
        issues.append("过渡词过少")
    elif transition_density > 5:
        score -= 5

    # 虚词占比（过高=信息密度低）
    if func_ratio > 5:
        score -= 8
        issues.append("虚词占比过高，信息密度低")

    # 短行比（手机端阅读友好）
    if short_line_ratio > 0.5:
        score += 5
    elif short_line_ratio < 0.2 and cjk > 1000:
        score -= 5
        issues.append("短行占比低，手机端阅读不友好")

    score = clamp_score(score)

    return {
        "score": round(score, 1),
        "details": {
            "avg_para_length": round(avg_para, 1),
            "long_para_ratio": round(long_para_ratio, 2),
            "avg_sent_length": round(avg_sent, 1),
            "long_sent_ratio": round(long_sent_ratio, 2),
            "transition_density": round(transition_density, 2),
            "func_ratio": round(func_ratio, 2),
            "short_line_ratio": round(short_line_ratio, 2),
        },
        "issues": issues,
    }


# =========================================================
# 综合评分
# =========================================================

def score_chapter(
    text: str,
    chapter: int,
    book_dir: Optional[Path] = None,
    file_path: Optional[str] = None,
) -> Dict[str, Any]:
    """汇总七维启发式观察；不执行独立机器门禁或语义审稿。"""

    dimensions_results = {
        "ai_control": score_ai_control(text),
        "rhythm": score_rhythm(text, book_dir, chapter),
        "style_consistency": score_style_consistency(text, book_dir),
        "emotional_impact": score_emotional_impact(text),
        "structure": score_structure(text),
        "dialogue": score_dialogue(text),
        "readability": score_readability(text),
    }
    for dim_result in dimensions_results.values():
        dim_result["score_scope"] = SCORE_SCOPE

    # 加权总分
    total = 0.0
    for dim in DIMENSIONS:
        key = dim["key"]
        weight = dim["weight"]
        score = dimensions_results[key]["score"]
        total += score * weight / 100

    total = round(total, 1)
    grade, grade_label = get_grade(total)

    # 汇总所有问题
    all_issues = []
    for dim in DIMENSIONS:
        key = dim["key"]
        for issue in dimensions_results[key].get("issues", []):
            all_issues.append(f"[{dim['name']}] {issue}")

    # 维度雷达数据
    radar = []
    for dim in DIMENSIONS:
        key = dim["key"]
        radar.append({
            "dimension": dim["name"],
            "key": key,
            "score": dimensions_results[key]["score"],
            "weight": dim["weight"],
        })

    non_ws, cjk = count_chars(text)

    result = {
        "schema_version": "1.0.0",
        "version": VERSION,
        "chapter": chapter,
        "file": file_path or "",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_score": total,
        "grade": grade,
        "grade_label": grade_label,
        "char_count": {"total": non_ws, "chinese": cjk},
        "dimensions": {k: v for k, v in dimensions_results.items()},
        "radar": radar,
        "issues": all_issues,
        "issue_count": len(all_issues),
        "passed": total >= DEFAULT_THRESHOLD,
        "passed_scope": "heuristic_threshold_only",
        "heuristic_threshold": {"value": DEFAULT_THRESHOLD, "met": total >= DEFAULT_THRESHOLD},
        **observation_boundary(),
    }

    return result


def format_markdown_report(result: Dict[str, Any]) -> str:
    """展示统计观察；旧 grade_label/passed 不作为文学结论。"""
    dim_names = {dim["key"]: dim["name"] for dim in DIMENSIONS}
    grade, grade_label = get_grade(result["total_score"])
    threshold_met = result["total_score"] >= DEFAULT_THRESHOLD
    lines = []
    lines.append(f"# 第{result['chapter']}章 质量评分报告（启发式统计观察）")
    lines.append("")
    lines.append(SCORE_LIMITATIONS)
    lines.append(EMOTION_LIMITATIONS)
    lines.append("")
    lines.append(f"**统计总分**: {result['total_score']} / 100  "
                 f"**统计分段**: {grade} ({grade_label})  "
                 f"**统计阈值**: {'达到' if threshold_met else '低于'} {DEFAULT_THRESHOLD}")
    lines.append("**语义复核**: 未运行（not_run）；无文学判断结果。")
    lines.append("**机器门禁**: 未运行（not_run）；本工具没有执行独立门禁。")
    lines.append("兼容字段 passed 与 score 退出码 0/1 仅表示达到/低于统计阈值。")
    lines.append(f"**字数**: {result['char_count']['total']} 字 "
                 f"(汉字 {result['char_count']['chinese']})")
    lines.append(f"**时间**: {result['timestamp']}")
    lines.append("")

    # 维度评分表
    lines.append("## 维度评分")
    lines.append("")
    lines.append("| 统计维度 | 权重 | 得分 | 规则提示（待结合原文复核） |")
    lines.append("|------|------|------|----------|")
    for item in result["radar"]:
        dim_key = item["key"]
        dim_result = result["dimensions"][dim_key]
        issues = [statistical_issue(issue) for issue in dim_result.get("issues", [])]
        issue_summary = "; ".join(issues[:2]) if issues else "—"
        if len(issues) > 2:
            issue_summary += f" 等{len(issues)}项"
        name = dim_names.get(dim_key, item['dimension'])
        lines.append(f"| {name} | {item['weight']}% | "
                     f"{item['score']} | {issue_summary} |")
    lines.append("")

    # 雷达图（文本）
    lines.append("## 维度雷达图")
    lines.append("")
    lines.append("```")
    for item in result["radar"]:
        bar_len = int(item["score"] / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        name = dim_names.get(item["key"], item["dimension"])
        lines.append(f"{name:<8} {bar} {item['score']}")
    lines.append("```")
    lines.append("")

    # 问题清单
    if result["issues"]:
        lines.append("## 统计规则提示（兼容字段 issues）")
        lines.append("")
        for i, issue in enumerate(result["issues"], 1):
            lines.append(f"{i}. {statistical_issue(issue)}")
        lines.append("")

    # 详细数据
    lines.append("## 详细数据")
    lines.append("")
    for item in result["radar"]:
        dim_key = item["key"]
        dim_result = result["dimensions"][dim_key]
        name = dim_names.get(dim_key, item["dimension"])
        lines.append(f"### {name} ({item['score']}分)")
        lines.append("")
        details = dim_result.get("details", {})
        for k, v in details.items():
            if isinstance(v, list):
                if v:
                    lines.append(f"- **{k}**: {len(v)} 项")
                continue
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    return "\n".join(lines)


# =========================================================
# 趋势分析
# =========================================================

def analyze_trend(book_dir: Path, from_ch: int, to_ch: int) -> Dict[str, Any]:
    """汇总多章统计趋势；旧报告缺少审核状态时不从高分推断通过。"""
    score_dir = book_dir / SCORE_DIR
    if not score_dir.exists():
        return {"ok": False, "error": f"评分目录不存在: {score_dir}"}

    chapters = []
    for ch in range(from_ch, to_ch + 1):
        score_file = score_dir / f"quality_ch{ch}.json"
        if score_file.exists():
            data = load_json(score_file)
            if data:
                chapters.append({
                    "chapter": ch,
                    "total": data.get("total_score", 0),
                    "grade": data.get("grade", "?"),
                    "dimensions": {k: v.get("score", 0) for k, v in data.get("dimensions", {}).items()},
                    "issue_count": data.get("issue_count", 0),
                    "heuristic_threshold": {"value": DEFAULT_THRESHOLD,
                                            "met": data.get("total_score", 0) >= DEFAULT_THRESHOLD},
                    **observation_boundary(),
                })

    if not chapters:
        return {"ok": False, "error": f"未找到 {from_ch}-{to_ch} 章的评分文件"}

    # 统计
    totals = [c["total"] for c in chapters]
    avg_total = sum(totals) / len(totals)
    min_total = min(totals)
    max_total = max(totals)

    if len(totals) > 1:
        variance = sum((t - avg_total) ** 2 for t in totals) / len(totals)
        std_dev = variance ** 0.5
    else:
        std_dev = 0

    # 各维度趋势
    dim_keys = [d["key"] for d in DIMENSIONS]
    dim_trends = {}
    for key in dim_keys:
        values = [c["dimensions"].get(key, 0) for c in chapters]
        dim_trends[key] = {
            "avg": round(sum(values) / len(values), 1) if values else 0,
            "min": min(values) if values else 0,
            "max": max(values) if values else 0,
        }

    # 趋势方向
    if len(totals) >= 3:
        first_half = sum(totals[:len(totals) // 2]) / (len(totals) // 2)
        second_half = sum(totals[len(totals) // 2:]) / (len(totals) - len(totals) // 2)
        if second_half - first_half > 3:
            trend = "上升"
        elif first_half - second_half > 3:
            trend = "下降"
        else:
            trend = "稳定"
    else:
        trend = "数据不足"

    return {
        "ok": True,
        "from_chapter": from_ch,
        "to_chapter": to_ch,
        "chapter_count": len(chapters),
        "avg_score": round(avg_total, 1),
        "min_score": min_total,
        "max_score": max_total,
        "std_dev": round(std_dev, 1),
        "trend": trend,
        "dim_trends": dim_trends,
        "chapters": chapters,
        **observation_boundary(),
    }


def format_trend_markdown(trend: Dict[str, Any]) -> str:
    """格式化趋势报告为 Markdown。"""
    if not trend.get("ok"):
        return f"趋势分析失败: {trend.get('error', '未知错误')}"

    lines = []
    lines.append(f"# 质量趋势报告（启发式统计观察） ({trend['from_chapter']}-{trend['to_chapter']}章)")
    lines.append("")
    lines.append(SCORE_LIMITATIONS)
    lines.append(EMOTION_LIMITATIONS)
    lines.append("**语义复核**: 未运行（not_run）；统计分数变化不代表文学质量变化。")
    lines.append("**机器门禁**: 未运行（not_run）；历史报告中的高分或 passed 不作为门禁证据。")
    lines.append("")
    lines.append(f"**章节数**: {trend['chapter_count']}  "
                 f"**均分**: {trend['avg_score']}  "
                 f"**最低**: {trend['min_score']}  "
                 f"**最高**: {trend['max_score']}  "
                 f"**标准差**: {trend['std_dev']}  "
                 f"**趋势**: {trend['trend']}")
    lines.append("")

    # 趋势图
    lines.append("## 统计总分趋势（字母仅表示统计分段）")
    lines.append("```")
    for c in trend["chapters"]:
        bar_len = int(c["total"] / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"第{c['chapter']:>3}章 {bar} {c['total']} ({c['grade']})")
    lines.append("```")
    lines.append("")

    # 维度趋势
    lines.append("## 维度趋势")
    lines.append("")
    lines.append("| 维度 | 均分 | 最低 | 最高 |")
    lines.append("|------|------|------|------|")
    dim_names = {d["key"]: d["name"] for d in DIMENSIONS}
    for key, vals in trend["dim_trends"].items():
        name = dim_names.get(key, key)
        lines.append(f"| {name} | {vals['avg']} | {vals['min']} | {vals['max']} |")
    lines.append("")

    return "\n".join(lines)


def load_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# =========================================================
# CLI
# =========================================================

def cmd_score(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    text = read_text(file_path)
    if text is None:
        print(json.dumps({"error": f"无法读取文件: {file_path}"}, ensure_ascii=False), file=sys.stderr)
        return 2

    book_dir = Path(args.book_dir) if args.book_dir else None

    result = score_chapter(text, args.chapter, book_dir, str(file_path))

    # 落盘
    if book_dir:
        score_dir = book_dir / SCORE_DIR
        score_dir.mkdir(parents=True, exist_ok=True)
        score_file = score_dir / f"quality_ch{args.chapter}.json"
        with open(score_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    if args.markdown:
        print(format_markdown_report(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["passed"] else 1


def cmd_trend(args: argparse.Namespace) -> int:
    book_dir = Path(args.book_dir)
    if not book_dir.exists():
        print(json.dumps({"error": f"目录不存在: {book_dir}"}, ensure_ascii=False), file=sys.stderr)
        return 2

    trend = analyze_trend(book_dir, args.from_ch, args.to_ch)

    if args.markdown:
        print(format_trend_markdown(trend))
    else:
        print(json.dumps(trend, ensure_ascii=False, indent=2))

    return 0 if trend.get("ok") else 2


def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(
        description="章节启发式统计观察 v1.0；不执行独立机器门禁或语义审稿。",
        epilog="score: 0=达到统计阈值55，1=低于统计阈值，2=参数/文件错误；"
               "trend: 0=读取成功，2=参数/文件错误。退出码均不代表文学验收。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # score
    score_parser = subparsers.add_parser("score", help="统计单章（不执行语义审稿）")
    score_parser.add_argument("file", help="章节文件路径")
    score_parser.add_argument("--chapter", type=int, required=True, help="章节号")
    score_parser.add_argument("--book-dir", help="书籍工程目录（用于加载文风锚/配额等）")
    score_parser.add_argument("--markdown", action="store_true", help="输出 Markdown 格式")
    score_parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                              help=f"兼容保留参数，不改变现有固定统计阈值 {DEFAULT_THRESHOLD}")

    # trend
    trend_parser = subparsers.add_parser("trend", help="多章启发式统计趋势（不推断文学质量）")
    trend_parser.add_argument("--book-dir", required=True, help="书籍工程目录")
    trend_parser.add_argument("--from", dest="from_ch", type=int, required=True, help="起始章号")
    trend_parser.add_argument("--to", dest="to_ch", type=int, required=True, help="结束章号")
    trend_parser.add_argument("--markdown", action="store_true", help="输出 Markdown 格式")

    args = parser.parse_args()

    if args.command == "score":
        sys.exit(cmd_score(args))
    elif args.command == "trend":
        sys.exit(cmd_trend(args))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
