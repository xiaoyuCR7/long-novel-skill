#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_repair.py — 门禁修复计划生成器（纯标准库，无第三方依赖）。

当章节门禁检查失败时，自动分析失败原因并生成最短修复路径。

核心流程：
  1. 读取门禁报告（追踪/门禁/gate_ch{N}.json）
  2. 按严重度分类失败原因（blocking / advisory）
  3. 为每个 blocking 问题生成修复建议
  4. 生成最短修复路径（优先修复高影响问题，合并相关问题）
  5. 输出修复计划 Markdown 文件到 追踪/门禁/repair_plan_ch{N}.md

用法：
  python scripts/gate_repair.py "书名目录" --chapter 37
  python scripts/gate_repair.py "书名目录" --chapter 37 --gate-report "追踪/门禁/gate_ch37.json"
  python scripts/gate_repair.py "书名目录" --chapter 37 --markdown
"""

import argparse
import datetime
import json
import os
import re
import sys

# ---------- 内置修复策略映射表 ----------

# Gate A 禁用词替换建议（词 → [建议替换方案]）
GATE_A_REPLACEMENTS = {
    "仿佛": ["删除", "直接写看到/听到/感受到的", "用具体比喻替代"],
    "似乎": ["删除，直接叙述", "改为「看上去像」"],
    "不禁": ["删除，直接写角色行动"],
    "不由得": ["删除，直接写反应"],
    "一丝": ["删除", "改为具体程度描写，如「些许」「几分」"],
    "眼底闪过": ["改为具体眼神描写", "直接写角色的表情变化"],
    "嘴角勾起": ["「他笑了」或删除", "改为具体表情动作"],
    "嘴角上扬": ["「他笑了」或删除"],
    "意味深长": ["删除，用对话/动作暗示含义"],
    "若有所思": ["删除，改为具体思考内容的动作描写"],
    "不容置疑": ["删除，改为具体语气描写"],
    "空气仿佛凝固": ["删除整句", "用沉默的动作替代"],
    "时间仿佛静止": ["删除整句", "用具体感知替代"],
    "众所周知": ["删除，改为叙述者自然的背景交代"],
    "值得一提": ["删除"],
    "不得不说": ["删除"],
    "映入眼帘": ["直接写看到了什么"],
}

# Gate B 毒句式改写建议（rule_id → 改写方向）
GATE_B_REWRITE = {
    "not-is-comparison": [
        "删除对比，直接写结果",
        "拆为两段独立叙述，去掉「不是A，而是B」结构",
        "用动作/场景展示「而是B」的部分，省略「不是A」",
    ],
    "no-only": [
        "去掉「没有X」，直接写「只有Y」",
        "用场景细节暗示缺失，不直接否定",
    ],
    "this-moment": [
        "删除「这一刻，」起手式，直接写当下发生的事",
        "改为具体时间/环境锚点",
    ],
    "negation-parade": [
        "只保留最后一个否定，改为肯定式叙述",
        "打散到不同段落，每段只留一个否定",
    ],
    "reverse-not-is": [
        "去掉「是A，不是B」结构，只写核心信息",
        "用行动/对话展示判断，避免直接对比句式",
    ],
    "voice-contrast": [
        "去掉前半句声音描写，直接写说了什么/做了什么",
        "改为：先写其他人的反应来侧面展示",
    ],
}

# Gate C 心理告知改写建议（标签 → 改写方向）
GATE_C_REWRITE = {
    "心理告知·直接陈述情绪": [
        "情绪→身体部位映射：紧张→手心出汗/心跳加速/呼吸急促",
        "情绪→身体部位映射：愤怒→拳头攥紧/牙关咬紧/太阳穴跳",
        "情绪→身体部位映射：恐惧→后退一步/瞳孔收缩/喉咙发紧",
        "情绪→身体部位映射：悲伤→眼眶发热/喉咙哽住/肩膀塌下来",
        "改为微动作/生理反应/环境感知展示情绪",
        "用角色具体行为替代情绪标签",
    ],
    "心理告知·心中句式": [
        "把「心中一紧」改为具体生理描写（心脏猛地一缩/胸口发闷）",
        "把「心中暗道」改为直接写角色的内心独白",
        "删除心中句式，用行动表达心理状态",
    ],
    "心理告知·一股X涌上心头": [
        "删除该句，改为具体情绪的身体反应",
        "拆解为感官细节描写",
    ],
}

# Gate D 节奏均匀（密度/结构类问题）改写建议
GATE_D_REWRITE = {
    "long-paragraph": [
        "长段落拆短：在镜头切换/时间跳跃/视角变化处断段",
        "每段控制在 80-150 字，一段一个核心信息",
        "检查是否有多个动作可分到不同段落",
    ],
    "period-stutter": [
        "合并短句：用逗号/分号连接相关短句",
        "穿插长句调节节奏",
        "每 2-3 个短句后接一个长句",
    ],
    "action-list-tic": [
        "监控摄像头式动作清单→选择1-2个关键动作详写",
        "合并琐碎动作，用「随手」「径直」一笔带过",
        "在动作间穿插心理/环境/感官描写",
    ],
    "repeat-sentence": [
        "复读句→只保留一次，其余删除或改写为不同表达",
        "如果是刻意的修辞重复（排比/强调），保留2次即可",
    ],
    "truncation": [
        "补充末行标点",
        "检查是否末句被截断，补全或改写到上一段",
    ],
    # 密度类
    "metaphor-density-tic": [
        "删除多余的比喻，全文只保留2-3个关键比喻",
        "部分比喻改为直白叙述",
    ],
    "reasoning-chain-tic": [
        "解释链打断：删除中间的「因此/所以/这说明」",
        "用行动/结果替代因果解释",
        "只保留最关键的一环因果",
    ],
    "quote-emphasis-tic": [
        "去掉引号强调，直接写叙述",
        "仅保留1-2个关键强调",
    ],
}

# v3.0 段落级 AI 模式检测改写建议
GATE_D_PARA_TICS = {
    "micro-tic-para": [
        "「了下/了一下」高密度→合并琐碎动作或删除",
        "每段最多保留1个「V了下」式描写",
        "改为其他动作补语：用「干脆」「一气呵成」等替代",
    ],
    "abstract-summary-para": [
        "段落内拔高关键词聚集→删除大部分拔高词",
        "只保留1处拔高，其余改为具体叙述",
        "用行动/对话替代「命运/齿轮/注定」等抽象词",
    ],
    "formula-density": [
        "套词密度过高→逐一替换「仿佛/似乎/宛如」等",
        "全文套词控制在千字3个以内",
        "部分套词改为直白叙述",
    ],
    "causal-chain-tic": [
        "解释链打断：在连续因果句间插入行动/场景",
        "删除部分「因为/所以/因此」标记",
    ],
    "action-sent-list": [
        "「主语+动词」句式连排→合并部分动作",
        "变换句式开头：用时间/地点/感受开头替代人名开头",
        "穿插心理/环境描写打断动作流",
    ],
    "quote-emphasis-para": [
        "引号强调滥用→去掉大部分强调引号",
        "仅保留1-2个真正需要强调的词",
        "用加粗/加语气替代（网文场景下直接去掉即可）",
    ],
}

# Gate E 对话腔调（目前 check_text.py 未单独检测，预留给扩展）
GATE_E_REWRITE = {
    "dialogue-tag-repeat": [
        "对话标签多样化：减少「他说/她道」，用动作替代标签",
        "信息碎片化：长对话拆为多轮短对话",
        "去掉多余的对话标签，靠上下文辨识说话人",
    ],
}

# Gate F 结尾升华改写建议
GATE_F_REWRITE = {
    "summary_ending": [
        "删除末段总结性语句（「这次经历」「他知道」「从此」等）",
        "改为动作/场景收尾：角色做了一个具体动作，留给读者想象空间",
        "用悬念结尾：角色面临一个新问题/新选择，戛然而止",
        "用感官细节结尾：一抹光线/一个声音/一个气味，画面感收尾",
    ],
    "sublimation_phrase": [
        "末段含「他终于明白/她终于懂了/这一切都」→ 删除这些短语",
        "改为具体的认知行动：他转头看向某个方向/她沉默了/他关上了门",
    ],
}

# Gate G 解释腔/上帝感改写建议（rule_id → 改写方向）
GATE_G_REWRITE = {
    "explainer-tone": [
        "「他不知道的是」→ 删除，改为只写读者能看到的表面",
        "「之所以…是因为」→ 删除解释，用行动/结果展示因果",
        "「这意味着」→ 删除叙述者定性，留给读者自己判断",
        "「事实证明」→ 删除裁判式叙述",
    ],
    "meta-leak": [
        "工程词「第X章/前文/伏笔/细纲」入正文→ 立即删除",
        "如果是角色在故事内讨论情节的文本，加 <!-- 闸口:跳过 --> 豁免",
    ],
    "refusal-tone": [
        "AI 助手身份残留→ 立即删除整句",
        "拒绝语残留→ 立即删除整句",
    ],
}

# 文末窗口修复建议
TRAILER_REWRITE = {
    "trailer-ending": [
        "预告式收尾→ 改为具体动作/场景，不要预告未来",
        "「没人知道…」→ 删除，用角色当下行动收尾",
        "「才刚刚开始」→ 删除，留一个开放式结尾画面",
    ],
    "trailer-summary": [
        "章尾状态总结→ 删除总结，改为具体画面",
        "「这一夜注定/命运的齿轮/尘埃落定」→ 全部删除",
        "「新的人生/新的篇章」→ 改为具体行动描写",
    ],
}

# 伏笔超期修复建议
FORESHADOW_REWRITE = [
    "在当前章节或下一章安排伏笔回收场景",
    "如果当前剧情不合适，可在对话中侧面提及",
    "长线伏笔可延后但需更新台账预期回收章节",
    "超期伏笔优先级最高，应在最短路径中排在首位",
]

# 字数问题修复建议
WORD_COUNT_REWRITE = {
    "under_min": [
        "调用 content_expander 分析可扩充的段落",
        "增加场景细节描写（五感扩展）",
        "增加角色对话或内心独白",
        "增加环境描写营造氛围",
        "扩写关键动作的细节过程",
    ],
    "over_max": [
        "删除总结性段落和解释性段落",
        "压缩对话中的冗余信息",
        "合并相邻的同质描写",
        "删除重复的动作描写",
        "识别并删除「中间过渡」段落（不推进情节的段落）",
    ],
}

# Gate 分类 → 中文标签映射
GATE_LABELS = {
    "banned_blocking": ("Gate A 禁用词", "blocking"),
    "banned_advisory": ("Gate A 禁用词", "advisory"),
    "toxic_blocking": ("Gate B 毒句式", "blocking"),
    "toxic_advisory": ("Gate B 毒句式", "advisory"),
    "gate_c": ("Gate C 心理告知", "advisory"),
    "gate_g_meta_refusal": ("Gate G 解释腔/工程词/拒绝语", "blocking"),
    "trailer": ("文末窗口", "blocking"),
    "density_advisory": ("密度检测", "advisory"),
    "structure_advisory": ("结构检测", "advisory"),
    "para_tics_advisory": ("段落级AI模式检测", "advisory"),
    "gate_f": ("Gate F 结尾升华", "advisory"),
}

# Gate 分组键：用于合并同一 Gate 的 blocking + advisory 问题
# （注意 gate_c / gate_g_meta_refusal / gate_f 是不同的 Gate，不能合并）
GATE_GROUP_KEY = {
    "banned_blocking": "gate_a",
    "banned_advisory": "gate_a",
    "toxic_blocking": "gate_b",
    "toxic_advisory": "gate_b",
    "gate_c": "gate_c",
    "gate_g_meta_refusal": "gate_g",
    "trailer": "trailer",
    "density_advisory": "gate_d",
    "structure_advisory": "gate_d",
    "para_tics_advisory": "para_tics",
    "gate_f": "gate_f",
}

# blocking 问题对 AI 评分的影响权重
BLOCKING_IMPACT = {
    "banned_blocking": 5,       # 每处约影响5分
    "toxic_blocking": 8,       # 毒句式影响更大
    "gate_g_meta_refusal": 10, # 解释腔/工程词泄漏影响最大
    "trailer": 10,             # 文末窗口问题
}

# 修复优先级：越高越先修
REPAIR_PRIORITY = {
    "gate_g_meta_refusal": 100,  # 工程词泄漏/AI身份残留 → 最先修
    "trailer": 90,               # 文末窗口 → 其次
    "toxic_blocking": 80,       # 毒句式
    "banned_blocking": 70,       # 禁用词
    "gate_c": 50,                # 心理告知
    "gate_f": 40,                # 结尾升华
    "density_advisory": 30,      # 密度
    "structure_advisory": 30,     # 结构
    "para_tics_advisory": 30,    # 段落级
    "banned_advisory": 20,       # 对话内禁用词
    "toxic_advisory": 20,        # 对话内毒句式
}


# ---------- 核心逻辑 ----------

def load_gate_report(path):
    """加载门禁报告 JSON 文件。"""
    if not os.path.isfile(path):
        print(f"错误：门禁报告不存在：{path}", file=sys.stderr)
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"错误：门禁报告格式损坏：{e}", file=sys.stderr)
        return None


def find_gate_report(book_dir, chapter_no):
    """自动查找门禁报告文件路径。"""
    gate_dir = os.path.join(book_dir, "追踪", "门禁")
    return os.path.join(gate_dir, f"gate_ch{chapter_no}.json")


def find_chapter_file(book_dir, chapter_no):
    """在正文目录下查找章节文件。"""
    ch_dir = os.path.join(book_dir, "正文")
    if not os.path.isdir(ch_dir):
        return None
    # 尝试匹配 第037章 或 第37章 格式
    pattern1 = f"第{chapter_no:03d}章"
    pattern2 = f"第{chapter_no}章"
    for fname in os.listdir(ch_dir):
        if pattern1 in fname or pattern2 in fname:
            if fname.endswith(".md") or fname.endswith(".txt"):
                return os.path.join(ch_dir, fname)
    return None


def analyze_failures(report):
    """分析门禁报告中的失败原因，按严重度和影响排序。

    返回 {
        "blocking": [(category, count, label, severity, impact_score)],
        "advisory": [(category, count, label, severity, impact_score)],
        "total_blocking": int,
        "total_advisory": int,
        "ai_score": float,
        "passed": bool,
    }
    """
    passed = report.get("passed", True)
    ai_score = report.get("ai_score", 0.0)
    categories = report.get("categories", {})

    blocking_items = []
    advisory_items = []

    for cat, count in categories.items():
        if count <= 0:
            continue
        if cat in ("blocking", "advisory", "ai_score", "categories", "skipped"):
            continue

        label, severity = GATE_LABELS.get(cat, (cat, "unknown"))
        impact = 0
        if severity == "blocking":
            weight = BLOCKING_IMPACT.get(cat, 5)
            impact = count * weight
            blocking_items.append((cat, count, label, severity, impact))
        else:
            impact = count * 2
            advisory_items.append((cat, count, label, severity, impact))

    # 按 impact 降序排列
    blocking_items.sort(key=lambda x: -x[4])
    advisory_items.sort(key=lambda x: -x[4])

    total_blocking = sum(c for _, c, _, _, _ in blocking_items)
    total_advisory = sum(c for _, c, _, _, _ in advisory_items)

    return {
        "blocking": blocking_items,
        "advisory": advisory_items,
        "total_blocking": total_blocking,
        "total_advisory": total_advisory,
        "ai_score": ai_score,
        "passed": passed,
    }


def get_repair_suggestions(category, count, report):
    """根据问题类别生成修复建议列表。

    返回 [(建议文本, 预计影响描述)]。
    """
    suggestions = []

    if category in ("banned_blocking", "banned_advisory"):
        # Gate A：逐词替换
        # 尝试从报告的 detail 中获取具体命中的词
        # 如果没有详细数据，给通用建议
        detail = report.get("detail", {})
        banned_words = detail.get("banned_words", [])
        if not banned_words:
            # 通用建议
            suggestions.append((
                "逐一替换禁用词，参考下方替换方案",
                f"预计修复 {count} 处，AI评分降低约 {count * 5} 分"
            ))
            for word, alts in sorted(GATE_A_REPLACEMENTS.items()):
                suggestions.append((
                    f"「{word}」→ {alts[0]}（备选：{'；'.join(alts[1:])}）",
                    None
                ))
        else:
            for word_info in banned_words:
                word = word_info if isinstance(word_info, str) else word_info.get("word", "")
                alts = GATE_A_REPLACEMENTS.get(word, ["删除", "改写为具体描写"])
                suggestions.append((
                    f"「{word}」→ {alts[0]}（备选：{'；'.join(alts[1:])}）",
                    None
                ))
            suggestions.append((
                "",
                f"预计修复 {len(banned_words)} 处，AI评分降低约 {len(banned_words) * 5} 分"
            ))

    elif category in ("toxic_blocking", "toxic_advisory"):
        # Gate B：句式改写
        detail = report.get("detail", {})
        toxic_rules = detail.get("toxic_rules", [])
        if not toxic_rules:
            suggestions.append((
                f"改写 {count} 处毒句式，参考下方改写方向",
                f"预计修复 {count} 处，AI评分降低约 {count * 8} 分"
            ))
            for rule_id, rewrites in GATE_B_REWRITE.items():
                suggestions.append((
                    f"  · {rule_id}：{rewrites[0]}",
                    None
                ))
        else:
            seen_rules = set()
            for rule_info in toxic_rules:
                rule_id = rule_info if isinstance(rule_info, str) else rule_info.get("rule_id", "")
                if rule_id in seen_rules:
                    continue
                seen_rules.add(rule_id)
                rewrites = GATE_B_REWRITE.get(rule_id, ["改写为直白叙述"])
                suggestions.append((
                    f"  · {rule_id}：{rewrites[0]}",
                    None
                ))
            suggestions.append((
                "",
                f"预计修复 {count} 处，AI评分降低约 {count * 8} 分"
            ))

    elif category == "gate_c":
        # Gate C：心理告知
        suggestions.append((
            f"改写 {count} 处心理告知句式，改为动作展示",
            f"预计修复 {count} 处，AI评分降低约 {count * 3} 分"
        ))
        for label, rewrites in GATE_C_REWRITE.items():
            suggestions.append((
                f"  · {label}：{rewrites[0]}",
                None
            ))

    elif category == "gate_g_meta_refusal":
        # Gate G：解释腔/工程词/拒绝语
        suggestions.append((
            f"修复 {count} 处解释腔/工程词泄漏/拒绝语",
            f"预计修复 {count} 处，AI评分降低约 {count * 10} 分"
        ))
        for rule_id, rewrites in GATE_G_REWRITE.items():
            suggestions.append((
                f"  · {rule_id}：{rewrites[0]}",
                None
            ))

    elif category == "trailer":
        # 文末窗口
        suggestions.append((
            f"修复 {count} 处文末窗口问题（预告式收尾/章尾状态总结）",
            f"预计修复 {count} 处，AI评分降低约 {count * 10} 分"
        ))
        for key, rewrites in TRAILER_REWRITE.items():
            suggestions.append((
                f"  · {key}：{rewrites[0]}",
                None
            ))

    elif category == "gate_f":
        # Gate F：结尾升华
        suggestions.append((
            "末段含总结性语句，建议改为动作/场景收尾",
            "预计AI评分降低约 3-5 分"
        ))
        for key, rewrites in GATE_F_REWRITE.items():
            for r in rewrites:
                suggestions.append((f"  · {r}", None))

    elif category in ("density_advisory", "structure_advisory"):
        # Gate D：密度/结构
        suggestions.append((
            f"优化 {count} 项密度/结构问题",
            f"预计修复后AI评分降低约 {count * 2} 分"
        ))
        for rule_id, rewrites in GATE_D_REWRITE.items():
            suggestions.append((
                f"  · {rule_id}：{rewrites[0]}",
                None
            ))

    elif category == "para_tics_advisory":
        # 段落级AI模式检测
        suggestions.append((
            f"修复 {count} 项段落级AI模式问题",
            f"预计修复后AI评分降低约 {count * 2} 分"
        ))
        for rule_id, rewrites in GATE_D_PARA_TICS.items():
            suggestions.append((
                f"  · {rule_id}：{rewrites[0]}",
                None
            ))

    elif category == "foreshadow_overdue":
        suggestions.append((
            f"处理 {count} 项超期伏笔",
            "优先级最高，必须在下一章或当前章回收"
        ))
        for r in FORESHADOW_REWRITE:
            suggestions.append((f"  · {r}", None))

    elif category == "word_count_under":
        suggestions.append((
            "字数不足，需要扩充",
            "参考 content_expander 分析可扩充段落"
        ))
        for r in WORD_COUNT_REWRITE["under_min"]:
            suggestions.append((f"  · {r}", None))

    elif category == "word_count_over":
        suggestions.append((
            "字数超限，需要删减",
            "识别可压缩段落"
        ))
        for r in WORD_COUNT_REWRITE["over_max"]:
            suggestions.append((f"  · {r}", None))

    else:
        suggestions.append((
            f"未知类别 {category}，{count} 处命中，需人工判断",
            None
        ))

    return suggestions


def build_repair_path(analysis, report):
    """生成最短修复路径。

    策略：
    1. 按 REPAIR_PRIORITY 排序所有问题
    2. 合并相关问题（同一 Gate 的 blocking + advisory 合并为一个步骤）
    3. 计算预计修复后的 AI 评分

    返回 [(步骤序号, Gate标签, 修复动作, 预计影响)]。
    """
    all_items = []
    for cat, count, label, severity, impact in analysis["blocking"]:
        priority = REPAIR_PRIORITY.get(cat, 50)
        all_items.append((priority, cat, count, label, severity, "blocking", impact))
    for cat, count, label, severity, impact in analysis["advisory"]:
        priority = REPAIR_PRIORITY.get(cat, 20)
        all_items.append((priority, cat, count, label, severity, "advisory", impact))

    # 按优先级降序
    all_items.sort(key=lambda x: (-x[0], x[1]))

    # 合并同一 Gate 的项目（用 GATE_GROUP_KEY 作为分组键）
    gate_groups = {}  # gate_key → (label, total_count, severity_list, total_impact, categories)
    for priority, cat, count, label, severity, sev_type, impact in all_items:
        gate_key = GATE_GROUP_KEY.get(cat, cat)
        if gate_key not in gate_groups:
            gate_groups[gate_key] = {
                "label": label,
                "total_count": 0,
                "severities": set(),
                "total_impact": 0,
                "categories": [],
            }
        g = gate_groups[gate_key]
        g["total_count"] += count
        g["severities"].add(sev_type)
        g["total_impact"] += impact
        g["categories"].append((cat, count))

    # 按优先级生成修复步骤
    steps = []
    step_no = 1
    for priority, cat, count, label, severity, sev_type, impact in all_items:
        gate_key = GATE_GROUP_KEY.get(cat, cat)
        if gate_key in gate_groups:
            g = gate_groups.pop(gate_key)
            # 生成修复动作描述
            action_parts = []
            for c, n in g["categories"]:
                if c in ("banned_blocking", "banned_advisory"):
                    action_parts.append(f"替换{n}处禁用词")
                elif c in ("toxic_blocking", "toxic_advisory"):
                    action_parts.append(f"改写{n}处毒句式")
                elif c == "gate_c":
                    action_parts.append(f"改写{n}处心理告知")
                elif c == "gate_g_meta_refusal":
                    action_parts.append(f"删除{n}处解释腔/工程词")
                elif c == "trailer":
                    action_parts.append(f"改写{n}处文末问题")
                elif c == "gate_f":
                    action_parts.append("改写末段结尾")
                elif c in ("density_advisory", "structure_advisory"):
                    action_parts.append(f"优化{n}项密度/结构")
                elif c == "para_tics_advisory":
                    action_parts.append(f"修复{n}项段落级问题")

            sev_label = "blocking+advisory" if len(g["severities"]) > 1 else sev_type
            action = "、".join(action_parts) if action_parts else f"修复{g['total_count']}处问题"
            steps.append((
                step_no,
                g["label"],
                action,
                g["total_impact"],
                sev_label,
            ))
            step_no += 1

    return steps


def generate_markdown(chapter_no, analysis, report, chapter_file, steps):
    """生成修复计划 Markdown 文本。"""
    ai_score = analysis["ai_score"]
    if ai_score < 20:
        risk = "低风险"
    elif ai_score < 40:
        risk = "中风险"
    elif ai_score < 60:
        risk = "高风险"
    else:
        risk = "极高风险"

    lines = []
    lines.append(f"# 第{chapter_no}章 门禁修复计划")
    lines.append("")

    # 1. 门禁状态
    lines.append("## 门禁状态")
    lines.append(f"- 通过状态：{'通过' if analysis['passed'] else '失败'}")
    lines.append(f"- Blocking问题：{analysis['total_blocking']}")
    lines.append(f"- Advisory问题：{analysis['total_advisory']}")
    lines.append(f"- AI评分：{ai_score}/100（{risk}）")

    if not analysis["passed"] and report.get("checked_at"):
        lines.append(f"- 检查时间：{report['checked_at']}")

    lines.append("")

    # 2. 修复优先级
    lines.append("## 修复优先级")

    # P0: Blocking
    if analysis["blocking"]:
        lines.append("")
        lines.append("### P0：必须修复（blocking）")
        lines.append("")

        item_no = 1
        for cat, count, label, severity, impact in analysis["blocking"]:
            lines.append(f"#### {item_no}. {label}")
            lines.append(f"- **问题**：检测到{count}处问题")
            lines.append(f"- **严重度**：blocking")
            lines.append(f"- **影响评估**：AI评分贡献约{impact}分")

            # 生成修复建议
            suggestions = get_repair_suggestions(cat, count, report)
            repair_lines = []
            impact_lines = []
            for text, impact_text in suggestions:
                if not text:
                    continue
                if impact_text:
                    impact_lines.append(impact_text)
                repair_lines.append(f"  - {text}")

            lines.append("- **修复建议**：")
            if repair_lines:
                lines.extend(repair_lines)
            else:
                lines.append("  - 需人工判断后修改")

            if impact_lines:
                lines.append(f"- **预计影响**：{impact_lines[-1]}")

            lines.append("")
            item_no += 1

    # P1: Advisory
    if analysis["advisory"]:
        lines.append("")
        lines.append("### P1：建议修复（advisory）")
        lines.append("")

        item_no = 1
        for cat, count, label, severity, impact in analysis["advisory"]:
            lines.append(f"#### {item_no}. {label}")
            lines.append(f"- **问题**：检测到{count}处问题")
            lines.append(f"- **严重度**：advisory（需人工判断）")
            lines.append(f"- **影响评估**：AI评分贡献约{impact}分")

            suggestions = get_repair_suggestions(cat, count, report)
            repair_lines = []
            impact_lines = []
            for text, impact_text in suggestions:
                if not text:
                    continue
                if impact_text:
                    impact_lines.append(impact_text)
                repair_lines.append(f"  - {text}")

            lines.append("- **修复建议**：")
            if repair_lines:
                lines.extend(repair_lines)
            else:
                lines.append("  - 需人工判断后修改")

            lines.append("")
            item_no += 1

    # 3. 修复路径
    lines.append("## 修复路径")

    if steps:
        total_reduction = sum(s[3] for s in steps)
        estimated_score = max(0, ai_score - total_reduction)

        for step_no, gate_label, action, impact, sev_label in steps:
            lines.append(f"{step_no}. 先修复{gate_label}（{action}）")

        lines.append("")
        if estimated_score < 20:
            est_risk = "低风险"
        elif estimated_score < 40:
            est_risk = "中风险"
        else:
            est_risk = "高风险"
        lines.append(f"预计修复后AI评分：约{estimated_score}（{est_risk}）")
    else:
        lines.append("无需修复，门禁已通过。")
    lines.append("")

    # 4. 修复后验证
    lines.append("## 修复后验证")
    lines.append("修复完成后重新执行：")
    lines.append("```bash")

    if chapter_file:
        # 提取文件相对路径
        rel_path = os.path.basename(chapter_file)
        lines.append(f'python scripts/check_text.py "{rel_path}" --min-chars 2000 --max-chars 3500 --gate-report --gate-state')
    else:
        lines.append(f'python scripts/check_text.py "正文/第{chapter_no:03d}章_标题.md" --min-chars 2000 --max-chars 3500 --gate-report --gate-state')

    lines.append("```")
    lines.append("")

    # 5. 禁用词速查表（附录）
    lines.append("## 附录：禁用词替换速查表")
    lines.append("")
    lines.append("| 原词 | 建议替换 |")
    lines.append("|------|----------|")
    for word, alts in sorted(GATE_A_REPLACEMENTS.items()):
        lines.append(f"| {word} | {alts[0]} |")
    lines.append("")

    return "\n".join(lines)


def print_summary(analysis):
    """在终端输出简要摘要。"""
    ai_score = analysis["ai_score"]
    if ai_score < 20:
        risk = "低风险"
    elif ai_score < 40:
        risk = "中风险"
    elif ai_score < 60:
        risk = "高风险"
    else:
        risk = "极高风险"

    sep = "=" * 16
    print(f"\n{sep} 门禁修复分析摘要 {sep}")
    print(f"  通过状态：{'通过' if analysis['passed'] else '失败'}")
    print(f"  Blocking问题：{analysis['total_blocking']} 处")
    print(f"  Advisory问题：{analysis['total_advisory']} 处")
    print(f"  AI评分：{ai_score}/100（{risk}）")

    if analysis["blocking"]:
        print(f"\n  Blocking 问题清单（按影响排序）：")
        for cat, count, label, severity, impact in analysis["blocking"]:
            print(f"    [{severity}] {label}：{count}处（影响≈{impact}分）")

    if analysis["advisory"]:
        print(f"\n  Advisory 问题清单：")
        for cat, count, label, severity, impact in analysis["advisory"]:
            print(f"    [{severity}] {label}：{count}处（影响≈{impact}分）")

    print(f"{sep}{sep}{sep}\n")


def main():
    # Windows 中文控制台 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="门禁修复计划生成器：分析门禁报告，生成最短修复路径")
    ap.add_argument("book_dir", help="书名目录（书籍工程根目录）")
    ap.add_argument("--chapter", type=int, required=True,
                    help="章节号（如 37）")
    ap.add_argument("--gate-report", default=None,
                    help="门禁报告路径（默认自动查找 追踪/门禁/gate_ch{N}.json）")
    ap.add_argument("--markdown", action="store_true",
                    help="输出完整 Markdown 格式修复计划（默认只输出摘要）")
    ap.add_argument("--output", default=None,
                    help="指定输出文件路径（默认写入 追踪/门禁/repair_plan_ch{N}.md）")
    args = ap.parse_args()

    book_dir = os.path.abspath(args.book_dir)
    chapter_no = args.chapter

    # 查找门禁报告
    report_path = args.gate_report or find_gate_report(book_dir, chapter_no)
    report = load_gate_report(report_path)
    if report is None:
        return 2

    # 查找章节文件
    chapter_file = find_chapter_file(book_dir, chapter_no)

    # 如果门禁已通过，提示并退出
    if report.get("passed", True):
        print(f"第{chapter_no}章门禁已通过（AI评分：{report.get('ai_score', 0)}），无需修复。")
        if args.markdown:
            analysis = analyze_failures(report)
            steps = build_repair_path(analysis, report)
            md = generate_markdown(chapter_no, analysis, report, chapter_file, steps)
            out_dir = os.path.join(book_dir, "追踪", "门禁")
            os.makedirs(out_dir, exist_ok=True)
            out_path = args.output or os.path.join(out_dir, f"repair_plan_ch{chapter_no}.md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"修复计划已写入：{out_path}")
        return 0

    # 分析失败原因
    analysis = analyze_failures(report)

    # 输出摘要
    print_summary(analysis)

    # 生成修复路径
    steps = build_repair_path(analysis, report)

    # 输出修复路径摘要
    if steps:
        print("最短修复路径：")
        for step_no, gate_label, action, impact, sev_label in steps:
            print(f"  {step_no}. {gate_label}（{action}）")
        print()

    # 输出 Markdown 修复计划
    if args.markdown:
        md = generate_markdown(chapter_no, analysis, report, chapter_file, steps)

        if args.output:
            out_path = args.output
        else:
            out_dir = os.path.join(book_dir, "追踪", "门禁")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"repair_plan_ch{chapter_no}.md")

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"修复计划已写入：{out_path}")
    else:
        print("提示：添加 --markdown 参数可输出完整修复计划 Markdown 文件。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
