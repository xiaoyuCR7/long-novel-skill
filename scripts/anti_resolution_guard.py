#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anti_resolution_guard.py — 反速决守卫 v1.0（纯标准库，无第三方依赖）。

检测 AI 写作中的"快速解决"倾向，强制留钩子，防止剧情透支。
规则依据 references/craft/reverse-brake.md 反向刹车理论。

核心功能：
  1. 速决模式检测（6 种）：冲突速决 / 秘密速揭 / 悬念速解 /
     危机速过 / 关系速定 / 成长速升
  2. 冷却期机制：从章节摘要 + 伏笔台账检测冷却期违规
  3. 钩子充足度检查：每章至少 1 个未解钩子，强度分级
  4. 问题增量检查：结尾未解问题数 >= 开头（终局卷除外

CLI 子命令：
  check     — 检查单章速决问题
  cooling   — 检查冷却期违规
  hooks     — 检查钩子充足度
  report    — 全书速决趋势报告

数据结构 ResolutionIssue：
  {
    "type": "conflict|secret|suspense|crisis|relationship|growth",
    "severity": "blocking|warn",
    "location": "开头/中间/结尾",
    "description": "...",
    "suggestion": "..."
  }

退出码：0 = 通过；1 = 有 blocking 问题；2 = 参数/文件错误。
"""

import argparse
import json
import os
import re
import sys


# =========================================================
# 常量与正则
# =========================================================

# 引号识别（对话域 vs 叙述域）——与 check_text.py 保持一致
QUOTE_RE = re.compile(r'"[^"\n]*"|「[^」\n]*」')

# 章节号提取
CHAPTER_NUM_RE = re.compile(r"第\s*(\d+)\s*章")

# ---- 6 种速决模式的触发关键词与模式
#
# 设计思路：每种速决模式用"问题标记"和"解决标记"两类关键词，
# 在短距离（默认 500 字 / 3 段）内同时出现则判定为速决。

# 1. 冲突速决：冲突建立 → 立即解决
CONFLICT_SETUP_MARKERS = [
    "挑衅", "羞辱", "刁难", "找茬", "威胁", "逼问", "质问",
    "冷笑", "狞笑", "不屑", "鄙夷", "嘲讽", "讥讽", "嘲弄",
    "挡住去路", "拦住", "堵截", "围攻", "围堵",
    "勃然大怒", "脸色一沉", "面色一冷",
    "怒视", "瞪着", "怒喝", "厉喝", "怒斥",
    "你算什么东西", "也配",
    "今天就让你知道", "给你点颜色", "让你尝尝",
]

CONFLICT_RESOLVE_MARKERS = [
    "瞬间", "顷刻", "刹那", "弹指", "一招", "一拳", "一脚",
    "秒杀", "碾压", "击溃", "打飞", "倒地", "狼狈不堪",
    "面如死灰", "脸色煞白", "瑟瑟发抖", "跪地求饶", "磕头认错",
    "彻底服了", "心服口服", "再也不敢", "灰溜溜", "落荒而逃",
    "轻轻松松", "不费吹灰之力", "易如反掌",
]

# 2. 秘密速揭：秘密埋下 → 立即揭露
SECRET_SETUP_MARKERS = [
    "秘密", "隐秘", "隐藏", "隐瞒", "不为人知",
    "无人知晓", "没人知道", "谁也不知道",
    "神秘", "谜团", "不解", "疑惑", "纳闷",
    "到底是什么", "究竟是", "身份成谜", "来历不明",
    "暗道", "心想", "暗自",
    "他不知道的是", "她不知道的是",
]

SECRET_REVEAL_MARKERS = [
    "原来", "竟然是", "正是", "其实", "果然", "果不其然",
    "真相大白", "水落石出", "揭开", "揭晓", "暴露",
    "终于明白", "恍然大悟", "豁然开朗",
    "身份揭晓", "谜底揭晓",
]

# 3. 悬念速解：悬念抛出 → 立即解答
SUSPENSE_SETUP_MARKERS = [
    "难道", "莫非", "会不会是", "究竟", "究竟是谁", "到底是谁",
    "怎么回事", "发生了什么", "为什么", "为何",
    "悬念", "谜团", "疑团", "不解之谜",
    "令人费解", "匪夷所思", "难以置信",
    "这", "这究竟", "这怎么", "这到底",
    "等待他的", "等待着他的",
]

SUSPENSE_RESOLVE_MARKERS = [
    "答案是", "原因是", "因为", "由于", "原来是",
    "事实证明", "真相是", "答案揭晓",
    "他终于知道", "她终于知道",
    "一切都清楚了", "一切都明白了",
]

# 4. 危机速过：危机出现 → 轻松化解
CRISIS_SETUP_MARKERS = [
    "危险", "危机", "凶险", "千钧一发", "危急",
    "命悬一线", "生死关头", "岌岌可危", "危在旦夕",
    "大祸临头", "死到临头", "大难临头",
    "致命", "必死无疑", "死定了", "完蛋了",
    "绝境", "死局", "无解之局",
    "恐怖", "可怕", "骇然", "惊出一身冷汗",
]

CRISIS_RESOLVE_MARKERS = [
    "化险为夷", "有惊无险", "虚惊一场",
    "轻而易举", "轻轻松松", "不费吹灰之力",
    "不过如此", "原来只是", "不过是",
    "安然无恙", "毫发无损", "平安无事",
    "松了口气", "虚惊",
]

# 5. 关系速定：关系建立 → 立即到最终状态
RELATIONSHIP_SETUP_MARKERS = [
    "初次见面", "第一次见面", "刚认识",
    "初识", "邂逅", "偶遇",
    "陌生人", "素未谋面", "素不相识",
    "刚出场", "新登场", "新来的",
]

RELATIONSHIP_RESOLVE_MARKERS = [
    "一见钟情", "一见如故", "相见恨晚",
    "当场结拜", "结为兄弟", "拜为兄弟",
    "当场告白", "表白成功", "在一起了",
    "死心塌地", "忠心耿耿", "誓死追随",
    "当场臣服", "甘拜下风", "心服口服",
    "成为挚友", "成为知己",
]

# 6. 成长速升：境界/实力提升太快，缺乏过程
GROWTH_TRIGGER_MARKERS = [
    "突破", "进阶", "晋升", "晋级", "提升", "暴涨",
    "飙升", "突飞猛进", "一日千里",
    "连升", "连破", "连跳",
    "从.*重", "从.*境", "达到.*境", "踏入.*境",
    "淬体", "炼气", "筑基", "金丹", "元婴",
    "武神", "武尊", "武帝",
]

# 速决判定窗口（字數阈值
QUICK_RESOLUTION_WINDOW = 500  # 字符
QUICK_RESOLUTION_PARA_WINDOW = 3  # 段落数

# 钩子检测 —— 章末窗口大小（字符）
HOOK_WINDOW_CHARS = 500

# 强钩子关键词
STRONG_HOOK_PATTERNS = [
    (re.compile(r"没想到.*(?:才刚刚开始|正要开始|即将开始)"), "强钩子·预告式"),
    (re.compile(r"即将.*拉开.*序幕"), "强钩子·序幕拉开"),
    (re.compile(r"更.*的.*还在后面"), "强钩子·更大在后"),
    (re.compile(r"这仅仅是.*开始"), "强钩子·只是开始"),
    (re.compile(r"真正的.*才.*开始"), "强钩子·真正开始"),
    (re.compile(r"等待着.*更大的"), "强钩子·更大等待"),
    (re.compile(r"一场.*风暴.*来袭"), "强钩子·风暴来袭"),
    (re.compile(r"暴风雨.*来临"), "强钩子·暴风雨来临"),
    (re.compile(r"谁也没有想到"), "强钩子·谁也没想到"),
    (re.compile(r"他不知道的是|她不知道的是"), "强钩子·上帝视角预告"),
    (re.compile(r"更可怕的是"), "强钩子·更可怕"),
    (re.compile(r"然而.*他.*还不知道"), "强钩子·还不知道"),
]

# 中钩子关键词
MEDIUM_HOOK_PATTERNS = [
    (re.compile(r"难道"), "中钩子·反问"),
    (re.compile(r"究竟|到底"), "中钩子·到底"),
    (re.compile(r"怎么回事|发生了什么"), "中钩子·疑问"),
    (re.compile(r"悬念|谜团|不解"), "中钩子·谜团"),
    (re.compile(r"下一秒|下一刻|就在这时"), "中钩子·时间切换"),
    (re.compile(r"突然|忽然|骤然"), "中钩子·突发"),
    (re.compile(r"他心中一动|她心中一动"), "中钩子·心念动"),
]

# 弱钩子关键词
WEAK_HOOK_PATTERNS = [
    (re.compile(r"会怎样|会如何|会怎么样"), "弱钩子·会怎样"),
    (re.compile(r"拭目以待"), "弱钩子·拭目以待"),
    (re.compile(r"未来|以后的日子"), "弱钩子·未来"),
    (re.compile(r"接下来|下一步"), "弱钩子·接下来"),
]

# 问题增量检测关键词
# 问题/悬念建立标记
QUESTION_SETUP_MARKERS = [
    "为什么", "怎么", "究竟", "到底", "难道", "莫非",
    "秘密", "谜团", "不解", "疑惑", "纳闷", "奇怪",
    "悬念", "疑团", "未知", "神秘",
    "是什么", "是谁", "在哪里", "从哪来",
]

# 问题/悬念解决标记
QUESTION_RESOLVE_MARKERS = [
    "原来", "竟然是", "正是", "果然", "因为", "由于",
    "终于明白", "恍然大悟", "知道了", "清楚了", "明白了",
    "真相", "答案", "揭晓", "揭开",
    "一切都清楚了", "水落石出",
]

# 伏笔台账解析相关
FORESHADOW_STATUS_UNRESOLVED = ("未回收", "进行中")
FORESHADOW_RESOLVED = "已回收"

# 微型伏笔阈值（星数 <= 2 星视为微型）
MINI_FORESHADOW_MAX_STARS = 2


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


def strip_dialogue(text):
    """移除文本中的对话内容（引号内），返回叙述域文本。"""
    return QUOTE_RE.sub("", text)


def extract_chapter_number(path_or_text):
    """从文件名或文本中提取章号，找不到返回 None。"""
    # 先尝试当作文件路径处理
    if (isinstance(path_or_text, str)
            and len(path_or_text) < 500
            and "\n" not in path_or_text
            and os.path.exists(path_or_text)):
        base = os.path.basename(path_or_text)
        m = CHAPTER_NUM_RE.search(base)
        if m:
            return int(m.group(1))
    # 尝试从文本首行提取
    if isinstance(path_or_text, str):
        m = CHAPTER_NUM_RE.search(path_or_text[:200])
        if m:
            return int(m.group(1))
    return None


def count_chars_nonws(text):
    """统计非空白字符数。"""
    return sum(1 for c in text if not c.isspace())


def get_location(index, total_len):
    """根据字符位置判断在全文中的位置（开头/中间/结尾）。"""
    if total_len <= 0:
        return "中间"
    ratio = index / total_len
    if ratio < 0.25:
        return "开头"
    elif ratio < 0.75:
        return "中间"
    else:
        return "结尾"


def split_paragraphs(text):
    """按空行分段，返回非空段落列表。"""
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


# =========================================================
# 速决模式检测核心
# =========================================================

def _find_marker_positions(text, markers):
    """在文本中查找标记词的首次出现位置，返回 [(位置, 标记词)]。"""
    positions = []
    for marker in markers:
        if not marker:
            continue
        idx = 0
        while True:
            pos = text.find(marker, idx)
            if pos == -1:
                break
            positions.append((pos, marker))
            idx = pos + 1
    positions.sort(key=lambda x: x[0])
    return positions


def _detect_quick_resolution(text, setup_markers, resolve_markers,
                            window_chars=QUICK_RESOLUTION_WINDOW):
    """检测速决模式：在 window_chars 字符内同时出现 setup 和 resolve 标记。

    返回 [(setup_pos, setup_marker, resolve_pos, resolve_marker)]
    """
    narration = strip_dialogue(text)
    setup_positions = _find_marker_positions(narration, setup_markers)
    resolve_positions = _find_marker_positions(narration, resolve_markers)

    if not setup_positions or not resolve_positions:
        return []

    results = []
    # 对每个 setup 标记，检查其后 window 内是否有 resolve 标记
    for setup_pos, setup_marker in setup_positions:
        for resolve_pos, resolve_marker in resolve_positions:
            if resolve_pos <= setup_pos:
                continue
            if resolve_pos - setup_pos <= window_chars:
                results.append((setup_pos, setup_marker, resolve_pos, resolve_marker))
                break  # 每个 setup 只记第一个快速解决
    return results


def detect_conflict_resolution(text):
    """检测冲突速决：冲突刚出现就被解决。

    返回 ResolutionIssue 列表。
    """
    issues = []
    results = _detect_quick_resolution(text, CONFLICT_SETUP_MARKERS, CONFLICT_RESOLVE_MARKERS)
    total_len = len(text)
    for setup_pos, setup_marker, resolve_pos, resolve_marker in results:
        location = get_location(setup_pos, total_len)
        # 上下文预览
        start = max(0, setup_pos - 20)
        end = min(len(text), resolve_pos + len(resolve_marker) + 20)
        context = text[start:end].replace("\n", " ")
        if len(context) > 80:
            context = context[:77] + "..."
        issues.append({
            "type": "conflict",
            "severity": "blocking",
            "location": location,
            "description": f"冲突标记「{setup_marker}」后约{resolve_pos - setup_pos}字内即被解决（{resolve_marker}）",
            "suggestion": "增加冲突升级过程：拉长对峙/铺垫至少 2-3 段，让对手多撑几章再打脸",
            "context": context,
            "setup_pos": setup_pos,
            "resolve_pos": resolve_pos,
        })
    return issues


def detect_secret_reveal(text):
    """检测秘密速揭：秘密刚埋下就被揭露。"""
    issues = []
    results = _detect_quick_resolution(text, SECRET_SETUP_MARKERS, SECRET_REVEAL_MARKERS)
    total_len = len(text)
    for setup_pos, setup_marker, resolve_pos, resolve_marker in results:
        location = get_location(setup_pos, total_len)
        start = max(0, setup_pos - 20)
        end = min(len(text), resolve_pos + len(resolve_marker) + 20)
        context = text[start:end].replace("\n", " ")
        if len(context) > 80:
            context = context[:77] + "..."
        issues.append({
            "type": "secret",
            "severity": "blocking",
            "location": location,
            "description": (f"秘密标记「{setup_marker}」后约{resolve_pos - setup_pos}字内即被揭露（{resolve_marker}）"),
            "suggestion": "延长秘密保质期：至少 3 章后再揭露，中间加暗示不加答案",
            "context": context,
            "setup_pos": setup_pos,
            "resolve_pos": resolve_pos,
        })
    return issues


def detect_suspense_resolve(text):
    """检测悬念速解：悬念刚抛出就给出答案。"""
    issues = []
    results = _detect_quick_resolution(text, SUSPENSE_SETUP_MARKERS, SUSPENSE_RESOLVE_MARKERS)
    total_len = len(text)
    for setup_pos, setup_marker, resolve_pos, resolve_marker in results:
        location = get_location(setup_pos, total_len)
        start = max(0, setup_pos - 20)
        end = min(len(text), resolve_pos + len(resolve_marker) + 20)
        context = text[start:end].replace("\n", " ")
        if len(context) > 80:
            context = context[:77] + "..."
        issues.append({
            "type": "suspense",
            "severity": "warn",
            "location": location,
            "description": (f"悬念标记「{setup_marker}」后约{resolve_pos - setup_pos}字内即被解答（{resolve_marker}）"),
            "suggestion": "保留悬念到下章：把答案挪到章末或延后揭示",
            "context": context,
            "setup_pos": setup_pos,
            "resolve_pos": resolve_pos,
        })
    return issues


def detect_crisis_passed(text):
    """检测危机速过：危机刚出现就轻松化解。"""
    issues = []
    results = _detect_quick_resolution(text, CRISIS_SETUP_MARKERS, CRISIS_RESOLVE_MARKERS)
    total_len = len(text)
    for setup_pos, setup_marker, resolve_pos, resolve_marker in results:
        location = get_location(setup_pos, total_len)
        start = max(0, setup_pos - 20)
        end = min(len(text), resolve_pos + len(resolve_marker) + 20)
        context = text[start:end].replace("\n", " ")
        if len(context) > 80:
            context = context[:77] + "..."
        issues.append({
            "type": "crisis",
            "severity": "blocking",
            "location": location,
            "description": (f"危机标记「{setup_marker}」后约{resolve_pos - setup_pos}字内即被化解（{resolve_marker}）"),
            "suggestion": "加重危机代价：不能虚惊一场/有惊无险要付出血肉代价",
            "context": context,
            "setup_pos": setup_pos,
            "resolve_pos": resolve_pos,
        })
    return issues


def detect_relationship_settled(text):
    """检测关系速定：人物关系刚建立就到最终状态。"""
    issues = []
    results = _detect_quick_resolution(text, RELATIONSHIP_SETUP_MARKERS, RELATIONSHIP_RESOLVE_MARKERS)
    total_len = len(text)
    for setup_pos, setup_marker, resolve_pos, resolve_marker in results:
        location = get_location(setup_pos, total_len)
        start = max(0, setup_pos - 20)
        end = min(len(text), resolve_pos + len(resolve_marker) + 20)
        context = text[start:end].replace("\n", " ")
        if len(context) > 80:
            context = context[:77] + "..."
        issues.append({
            "type": "relationship",
            "severity": "warn",
            "location": location,
            "description": (f"关系建立标记「{setup_marker}」后约{resolve_pos - setup_pos}字内即定终局（{resolve_marker}）"),
            "suggestion": "关系分阶段发展：初识→试探→信任→深交，至少跨 3 章",
            "context": context,
            "setup_pos": setup_pos,
            "resolve_pos": resolve_pos,
        })
    return issues


def detect_growth_spike(text):
    """检测成长速升：境界/实力提升太快，缺乏过程。

    判定逻辑：同章内出现多个成长关键词且前后缺少过程描写（修炼/战斗/感悟）。
    简化为关键词密度检测。
    """
    issues = []
    narration = strip_dialogue(text)

    # 统计成长触发词
    growth_hits = []
    for marker in GROWTH_TRIGGER_MARKERS:
        idx = 0
        while True:
            pos = narration.find(marker, idx)
            if pos == -1:
                break
            growth_hits.append((pos, marker))
            idx = pos + 1

    if len(growth_hits) >= 3:
        # 检查是否有过程描写（修炼、感悟、战斗等过程词
        process_markers = [
            "修炼", "打坐", "运功", "运转", "调息",
            "感悟", "领悟", "体会", "琢磨",
            "战斗", "激战", "交手", "对战",
            "日夜", "数月", "数日", "许久",
        ]
        process_count = sum(narration.count(m) for m in process_markers)
        if process_count < 2:
            total_len = len(text)
            first_pos = growth_hits[0][0]
            location = get_location(first_pos, total_len)
            issues.append({
                "type": "growth",
                "severity": "warn",
                "location": location,
                "description": (f"本章出现 {len(growth_hits)} 处成长/突破，但过程描写仅 {process_count} 处，提升太快"),
                "suggestion": "增加修炼/战斗/感悟过程：突破前铺垫，让成长有代价有过程",
                "context": f"成长标记：{'、'.join(h[1] for h in growth_hits[:5])}",
                "setup_pos": first_pos,
                "resolve_pos": growth_hits[-1][0],
            })
    return issues


def detect_all_resolutions(text):
    """运行全部 6 种速决模式检测。

    返回 ResolutionIssue 列表。
    """
    issues = []
    issues.extend(detect_conflict_resolution(text))
    issues.extend(detect_secret_reveal(text))
    issues.extend(detect_suspense_resolve(text))
    issues.extend(detect_crisis_passed(text))
    issues.extend(detect_relationship_settled(text))
    issues.extend(detect_growth_spike(text))
    return issues


# =========================================================
# 钩子充足度检查
# =========================================================

def get_end_window(text, chars=HOOK_WINDOW_CHARS):
    """获取章末窗口文本。"""
    if len(text) <= chars:
        return text
    return text[-chars:]


def detect_hooks(text):
    """检测章末钩子，返回 (hooks列表，每个 hook 含 strength、pattern、desc。

    返回 {"strong": [...], "medium": [...], "weak": [...]}
    """
    tail = get_end_window(text)
    narration = strip_dialogue(tail)

    hooks = {"strong": [], "medium": [], "weak": []}

    for pat, desc in STRONG_HOOK_PATTERNS:
        for m in pat.finditer(narration):
            hooks["strong"].append({
                "strength": "强",
                "pattern": desc,
                "match": m.group(0),
                "position": len(text) - len(tail) + m.start(),
            })

    for pat, desc in MEDIUM_HOOK_PATTERNS:
        for m in pat.finditer(narration):
            hooks["medium"].append({
                "strength": "中",
                "pattern": desc,
                "match": m.group(0),
                "position": len(text) - len(tail) + m.start(),
            })

    for pat, desc in WEAK_HOOK_PATTERNS:
        for m in pat.finditer(narration):
            hooks["weak"].append({
                "strength": "弱",
                "pattern": desc,
                "match": m.group(0),
                "position": len(text) - len(tail) + m.start(),
            })

    return hooks


def hook_strength_level(hooks):
    """判断钩子强度等级：强/中/弱/无。"""
    if hooks["strong"]:
        return "强"
    elif hooks["medium"]:
        return "中"
    elif hooks["weak"]:
        return "弱"
    else:
        return "无"


def check_hook_sufficiency(text, min_strong_chain=2):
    """检查钩子充足度。

    返回 (has_hook, strength, issues)：
      has_hook: bool — 是否有至少 1 个钩子
      strength: str — 最强钩子等级
      issues: list — 问题列表
    """
    hooks = detect_hooks(text)
    strength = hook_strength_level(hooks)
    has_hook = strength != "无"
    issues = []

    if not has_hook:
        issues.append({
            "type": "hook_missing",
            "severity": "blocking",
            "location": "结尾",
            "description": "章末 500 字内未检测到任何钩子/悬念/疑问",
            "suggestion": "在章末加一个悬念：反问句、新人物出场、突发变故、预告下章事件",
        })

    return has_hook, strength, issues, hooks


# =========================================================
# 问题增量检查
# =========================================================

def count_questions(text_part):
    """统计文本片段中的未解问题数量（基于关键词的近似估算）。

    返回问题标记数减去解决标记数。
    """
    narration = strip_dialogue(text_part)
    setup_count = sum(narration.count(m) for m in QUESTION_SETUP_MARKERS)
    resolve_count = sum(narration.count(m) for m in QUESTION_RESOLVE_MARKERS)
    # 粗略估算：问题数 = 建立数 - 解决数（下限为 0）
    return max(0, setup_count - resolve_count), setup_count, resolve_count


def check_question_delta(text, is_final_volume=False):
    """检查问题增量：结尾未解问题数应 >= 开头。

    返回 (delta, start_count, end_count, issues)
    """
    issues = []
    total_len = len(text)

    # 取开头 20% 和结尾 20% 作为对比窗口
    window_size = max(int(total_len * 0.2), 200)
    start_part = text[:window_size]
    end_part = text[-window_size:]

    start_q, start_setup, start_resolve = count_questions(start_part)
    end_q, end_setup, end_resolve = count_questions(end_part)
    delta = end_q - start_q

    if not is_final_volume and delta < 0 and end_q < start_q:
        issues.append({
            "type": "question_decrease",
            "severity": "warn",
            "location": "全篇",
            "description": (f"章末未解问题数（{end_q}）少于章初（{start_q}），问题净减少 {abs(delta)}"),
            "suggestion": "每解决 1 个问题，新增 1.5 个问题：解决旧矛盾的同时暴露新隐患",
        })

    return delta, start_q, end_q, issues


# =========================================================
# 冷却期机制
# =========================================================

def parse_foreshadow_ledger(text):
    """解析伏笔台账 Markdown 表格，返回伏笔列表。

    每个伏笔：{id, content, plant_chapter, status, resolve_chapter, importance}
    """
    foreshadows = []
    lines = text.splitlines()
    in_table = False
    header_skipped = False

    for line in lines:
        stripped = line.strip()
        # 识别表格行
        if stripped.startswith("|") and "编号" in stripped:
            in_table = True
            header_skipped = False
            continue
        if in_table and re.match(r"^\|[\s:—-]+\|", stripped):
            # 分隔行（|---| 或 |:---:| 等）
            header_skipped = True
            continue
        if in_table and header_skipped and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 5:
                fid = cells[0]
                content = cells[1] if len(cells) > 1 else ""
                plant_str = cells[2] if len(cells) > 2 else ""
                status = cells[3] if len(cells) > 3 else ""
                resolve_str = cells[4] if len(cells) > 4 else ""
                importance = cells[5] if len(cells) > 5 else ""

                # 提取埋设章节号
                plant_ch = 0
                m = re.search(r"(\d+)", plant_str)
                if m:
                    plant_ch = int(m.group(1))

                # 提取回收章节号
                resolve_ch = 0
                m = re.search(r"(\d+)", resolve_str)
                if m:
                    resolve_ch = int(m.group(1))

                # 计算重要程度星数
                stars = importance.count("★")

                foreshadows.append({
                    "id": fid,
                    "content": content,
                    "plant_chapter": plant_ch,
                    "status": status,
                    "resolve_chapter": resolve_ch,
                    "importance": importance,
                    "stars": stars,
                })
        elif in_table and not stripped.startswith("|") and stripped:
            # 遇到非表格行的标题或正文，退出表格解析
            if stripped.startswith("#") or stripped.startswith("---"):
                in_table = False

    return foreshadows


def check_foreshadow_cooldown(foreshadows, current_chapter, min_chapters=3):
    """检查伏笔冷却期：埋设后 3 章内就回收 → 违规（微型伏笔除外）。

    返回违规伏笔列表。
    """
    violations = []
    for f in foreshadows:
        if f["resolve_chapter"] == 0 or f["plant_chapter"] == 0:
            continue
        if "已回收" not in f["status"]:
            continue
        gap = f["resolve_chapter"] - f["plant_chapter"]
        # 微型伏笔（<=2星）豁免
        if f["stars"] <= MINI_FORESHADOW_MAX_STARS:
            continue
        if gap < min_chapters:
            violations.append({
                "id": f["id"],
                "content": f["content"],
                "plant_chapter": f["plant_chapter"],
                "resolve_chapter": f["resolve_chapter"],
                "gap": gap,
                "stars": f["stars"],
                "severity": "blocking" if gap <= 1 else "warn",
                "description": (f"伏笔 {f['id']} 埋设后仅 {gap} 章即回收（第{f['plant_chapter']}章→第{f['resolve_chapter']}章）"),
                "suggestion": f"重要伏笔至少 {min_chapters} 章后再回收，中间加推进/暗示层",
            })
    return violations


def parse_chapter_summaries(text):
    """解析章节摘要，返回章节列表。

    每个章节：{chapter, title, core_events, foreshadowing, hooks}
    """
    chapters = []
    current = None
    section = None

    for line in text.splitlines():
        # 章节标题
        m = re.match(r"^##\s*第\s*(\d+)\s*章[：:]\s*(.+)", line)
        if m:
            if current:
                chapters.append(current)
            current = {
                "chapter": int(m.group(1)),
                "title": m.group(2).strip(),
                "core_events": "",
                "foreshadowing": "",
                "hooks": "",
                "conflict_types": set(),
            }
            section = None
            continue

        if current is None:
            continue

        # 小节标题
        if line.startswith("### "):
            title = line[4:].strip()
            if "核心事件" in title:
                section = "core_events"
            elif "伏笔" in title:
                section = "foreshadowing"
            elif "爽点" in title or "钩子" in title:
                section = "hooks"
            else:
                section = None
            continue

        # 内容行
        if section and line.strip() and not line.startswith("#"):
            current[section] += line.strip() + "\n"

    if current:
        chapters.append(current)

    # 从核心事件中提取冲突类型关键词
    conflict_keywords = {
        "打脸": "face-slap",
        "战斗": "battle",
        "比试": "competition",
        "对峙": "confrontation",
        "羞辱": "humiliation",
        "阴谋": "conspiracy",
        "陷害": "frame-up",
        "复仇": "revenge",
        "揭秘": "revelation",
        "突破": "breakthrough",
    }
    for ch in chapters:
        for kw, ctype in conflict_keywords.items():
            if kw in ch["core_events"]:
                ch["conflict_types"].add(ctype)

    return chapters


def check_conflict_cooldown(chapters, current_chapter):
    """检查冲突类型冷却：同类冲突连续出现。

    返回违规列表。
    """
    violations = []
    if len(chapters) < 2:
        return violations

    # 找到当前章节
    current = None
    prev = None
    for ch in chapters:
        if ch["chapter"] == current_chapter:
            current = ch
        elif ch["chapter"] < current_chapter:
            prev = ch

    if not current or not prev:
        return violations

    # 检查上一章和本章是否有相同冲突类型
    common = current["conflict_types"] & prev["conflict_types"]
    if common:
        for ctype in common:
            violations.append({
                "type": "conflict_cooldown",
                "severity": "warn",
                "location": "全篇",
                "description": (f"冲突类型「{ctype}」在上一章（第{prev['chapter']}章）刚出现，本章（第{current['chapter']}章）又出现同类冲突"),
                "suggestion": "插入不同类型的事件调剂：羁绊深化/风土人情/势力经营等",
                "conflict_type": ctype,
                "prev_chapter": prev["chapter"],
                "current_chapter": current["chapter"],
            })

    return violations


def check_new_character_reveal(text):
    """检查新角色登场后立即揭示全部背景。

    返回问题列表。
    """
    issues = []
    narration = strip_dialogue(text)

    # 新角色登场标记
    new_char_markers = [
        "新登场", "第一次见到", "第一次出现", "陌生的",
        "从未见过", "不认识的",
    ]
    # 背景揭示标记
    reveal_markers = [
        "原来是", "身份是", "名叫", "名字叫",
        "背景是", "出身于", "来自",
        "他的身世", "她的身世",
    ]

    results = _detect_quick_resolution(text, new_char_markers, reveal_markers, window_chars=300)
    total_len = len(text)
    for setup_pos, setup_marker, resolve_pos, resolve_marker in results:
        location = get_location(setup_pos, total_len)
        issues.append({
            "type": "character_reveal",
            "severity": "warn",
            "location": location,
            "description": (f"新角色「{setup_marker}」后约{resolve_pos - setup_pos}字内即揭示背景（{resolve_marker}）"),
            "suggestion": "新角色背景分层次揭露：先露一面→给线索→慢慢拼出全貌",
        })
    return issues


# =========================================================
# 综合检查
# =========================================================

def run_chapter_check(text, check_hooks=True, check_delta=True, is_final_volume=False):
    """对单章文本运行全部速决检查。

    返回 {
      "resolution_issues": [...],
      "hook_issues": [...],
      "delta_issues": [...],
      "hook_strength": "强/中/弱/无",
      "question_delta": int,
      "start_questions": int,
      "end_questions": int,
      "total_blocking": int,
      "total_warn": int,
      "passed": bool,
    }
    """
    resolution_issues = detect_all_resolutions(text)

    hook_issues = []
    hook_strength = "无"
    hooks = {"strong": [], "medium": [], "weak": []}
    if check_hooks:
        has_hook, hook_strength, hook_issues, hooks = check_hook_sufficiency(text)

    delta_issues = []
    delta = 0
    start_q = 0
    end_q = 0
    if check_delta:
        delta, start_q, end_q, delta_issues = check_question_delta(text, is_final_volume)

    all_issues = resolution_issues + hook_issues + delta_issues
    blocking_count = sum(1 for i in all_issues if i.get("severity") == "blocking")
    warn_count = sum(1 for i in all_issues if i.get("severity") == "warn")

    return {
        "resolution_issues": resolution_issues,
        "hook_issues": hook_issues,
        "delta_issues": delta_issues,
        "hooks": hooks,
        "hook_strength": hook_strength,
        "question_delta": delta,
        "start_questions": start_q,
        "end_questions": end_q,
        "total_blocking": blocking_count,
        "total_warn": warn_count,
        "passed": blocking_count == 0,
    }


# =========================================================
# 输出格式化
# =========================================================

TYPE_LABELS = {
    "conflict": "冲突速决",
    "secret": "秘密速揭",
    "suspense": "悬念速解",
    "crisis": "危机速过",
    "relationship": "关系速定",
    "growth": "成长速升",
    "hook_missing": "钩子缺失",
    "question_decrease": "问题净减",
    "conflict_cooldown": "冲突冷却违规",
    "foreshadow_cooldown": "伏笔冷却违规",
    "character_reveal": "角色背景速揭",
}


def print_check_report(result, chapter_num=None, show_fix_hints=False):
    """打印速决检查报告。"""
    sep = "=" * 16
    title = "反速决守卫检测报告"
    if chapter_num:
        title += f"（第{chapter_num}章）"
    print(f"\n{sep} {title} {sep}")

    # 速决模式
    print("\n【速决模式检测】")
    res_issues = result["resolution_issues"]
    if res_issues:
        print(f"  命中 {len(res_issues)} 处：")
        for issue in res_issues:
            tlabel = TYPE_LABELS.get(issue["type"], issue["type"])
            sev = issue["severity"]
            loc = issue["location"]
            print(f"    [{sev}] {tlabel}（{loc}）：{issue['description']}")
            if "context" in issue:
                print(f"      上下文：{issue['context']}")
            if show_fix_hints:
                print(f"      → 建议：{issue['suggestion']}")
    else:
        print("  命中 0 处")

    # 钩子
    print("\n【钩子充足度】")
    print(f"  最强钩子等级：{result['hook_strength']}")
    hooks = result.get("hooks", {})
    all_hooks = hooks.get("strong", []) + hooks.get("medium", []) + hooks.get("weak", [])
    if all_hooks:
        print(f"  检测到钩子 {len(all_hooks)} 个：")
        for h in all_hooks[:5]:
            print(f"    [{h['strength']}] {h['pattern']}：{h['match']}")
    if result["hook_issues"]:
        for issue in result["hook_issues"]:
            print(f"  [{issue['severity']}] {issue['description']}")
            if show_fix_hints:
                print(f"    → 建议：{issue['suggestion']}")

    # 问题增量
    print("\n【问题增量检查】")
    print(f"  章初问题估算：{result['start_questions']}")
    print(f"  章末问题估算：{result['end_questions']}")
    delta = result["question_delta"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    print(f"  问题增量：{delta_str}")
    if result["delta_issues"]:
        for issue in result["delta_issues"]:
            print(f"  [{issue['severity']}] {issue['description']}")
            if show_fix_hints:
                print(f"    → 建议：{issue['suggestion']}")

    # 总结
    print(f"\n{sep} 检测总结 {sep}")
    print(f"  blocking：{result['total_blocking']} 处 / warn：{result['total_warn']} 处")
    status = "PASS" if result["passed"] else "FAIL"
    print(f"  结论：{status}")
    if not result["passed"]:
        print("  （blocking > 0 判定为 FAIL）")


def print_cooling_report(foreshadow_violations, conflict_violations, char_violations):
    """打印冷却期检查报告。"""
    sep = "=" * 16
    print(f"\n{sep} 冷却期违规检查 {sep}")

    print("\n【伏笔冷却违规】")
    if foreshadow_violations:
        print(f"  违规 {len(foreshadow_violations)} 项：")
        for v in foreshadow_violations:
            print(f"    [{v['severity']}] {v['description']}")
            print(f"      → 建议：{v['suggestion']}")
    else:
        print("  未检测到违规")

    print("\n【冲突类型冷却违规】")
    if conflict_violations:
        print(f"  违规 {len(conflict_violations)} 项：")
        for v in conflict_violations:
            print(f"    [{v['severity']}] {v['description']}")
            print(f"      → 建议：{v['suggestion']}")
    else:
        print("  未检测到违规")

    print("\n【新角色背景速揭】")
    if char_violations:
        print(f"  违规 {len(char_violations)} 项：")
        for v in char_violations:
            print(f"    [{v['severity']}] {v['description']}（{v['location']}）")
            print(f"      → 建议：{v['suggestion']}")
    else:
        print("  未检测到违规")

    total_blocking = (
        sum(1 for v in foreshadow_violations if v["severity"] == "blocking")
        + sum(1 for v in conflict_violations if v["severity"] == "blocking")
        + sum(1 for v in char_violations if v["severity"] == "blocking")
    )
    print(f"\n{sep} 冷却期检查总结 {sep}")
    print(f"  blocking：{total_blocking} 处")
    print(f"  结论：{'PASS' if total_blocking == 0 else 'FAIL'}")


# =========================================================
# 全书报告
# =========================================================

def scan_book_directory(book_dir):
    """扫描书籍目录，收集章节文件列表。"""
    text_dir = os.path.join(book_dir, "正文")
    if not os.path.isdir(text_dir):
        return []

    chapters = []
    for fname in sorted(os.listdir(text_dir)):
        if fname.endswith(".md") or fname.endswith(".txt"):
            m = CHAPTER_NUM_RE.search(fname)
            if m:
                chap_num = int(m.group(1))
                fpath = os.path.join(text_dir, fname)
                chapters.append((chap_num, fpath))
    chapters.sort(key=lambda x: x[0])
    return chapters


def generate_book_report(book_dir):
    """生成全书速决趋势报告。

    返回报告字典。
    """
    chapters = scan_book_directory(book_dir)
    if not chapters:
        return {"error": "未找到章节文件", "chapters": []}

    results = []
    type_counts = {}
    strength_history = []
    no_strong_hook_streak = 0
    max_no_strong_streak = 0

    for chap_num, fpath in chapters:
        text = _read_file(fpath)
        if not text:
            continue
        result = run_chapter_check(text)
        result["chapter"] = chap_num
        result["file"] = fpath
        results.append(result)

        # 统计各类型
        for issue in result["resolution_issues"]:
            t = issue["type"]
            type_counts[t] = type_counts.get(t, 0) + 1

        # 钩子强度历史
        strength_history.append((chap_num, result["hook_strength"]))

        # 连续无强钩子
        if result["hook_strength"] != "强":
            no_strong_hook_streak += 1
            if no_strong_hook_streak > max_no_strong_streak:
                max_no_strong_streak = no_strong_hook_streak
        else:
            no_strong_hook_streak = 0

    total_blocking = sum(r["total_blocking"] for r in results)
    total_warn = sum(r["total_warn"] for r in results)

    return {
        "total_chapters": len(results),
        "total_blocking": total_blocking,
        "total_warn": total_warn,
        "type_counts": type_counts,
        "strength_history": strength_history,
        "max_no_strong_hook_streak": max_no_strong_streak,
        "chapters": results,
        "passed": total_blocking == 0,
    }


def print_book_report(report):
    """打印全书报告。"""
    sep = "=" * 16
    print(f"\n{sep} 全书速决趋势报告 {sep}")

    if "error" in report:
        print(f"  错误：{report['error']}")
        return

    print(f"\n  总章节数：{report['total_chapters']}")
    print(f"  总 blocking：{report['total_blocking']} 处")
    print(f"  总 warn：{report['total_warn']} 处")

    print("\n【速决类型分布】")
    if report["type_counts"]:
        for t, cnt in sorted(report["type_counts"].items(), key=lambda x: -x[1]):
            label = TYPE_LABELS.get(t, t)
            print(f"  {label}：{cnt} 处")
    else:
        print("  无速决问题")

    print("\n【钩子强度走势】")
    for chap, strength in report["strength_history"]:
        bar = "█" if strength == "强" else ("▓" if strength == "中" else ("░" if strength == "弱" else " "))
        print(f"  第{chap:3d}章 {bar} {strength}")

    print(f"\n  最长连续无强钩子：{report['max_no_strong_hook_streak']} 章")
    if report["max_no_strong_hook_streak"] >= 2:
        print("  [WARN] 连续 2 章以上无强钩子 → 节奏疲软")

    print(f"\n{sep} 全书总结 {sep}")
    print(f"  结论：{'PASS' if report['passed'] else 'FAIL'}")


# =========================================================
# CLI
# =========================================================

def main():
    _ensure_utf8()

    parser = argparse.ArgumentParser(
        description="反速决守卫 v1.0：检测 AI 写作中的快速解决倾向，强制留钩子"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # check 子命令
    p_check = subparsers.add_parser("check", help="检查单章速决问题")
    p_check.add_argument("chapter_file", help="章节文件路径")
    p_check.add_argument("--json", action="store_true", help="输出 JSON 格式结果")
    p_check.add_argument("--fix-hints", action="store_true", help="输出修复建议")
    p_check.add_argument("--no-hooks", action="store_true", help="跳过钩子检查")
    p_check.add_argument("--no-delta", action="store_true", help="跳过问题增量检查")
    p_check.add_argument("--final-volume", action="store_true", help="终局卷（豁免问题增量递减）")

    # cooling 子命令
    p_cool = subparsers.add_parser("cooling", help="检查冷却期违规")
    p_cool.add_argument("book_dir", help="书籍目录路径")
    p_cool.add_argument("--chapter", type=int, default=0, help="当前章号（默认从最新章节推断）")
    p_cool.add_argument("--json", action="store_true", help="输出 JSON 格式结果")
    p_cool.add_argument("--fix-hints", action="store_true", help="输出修复建议")

    # hooks 子命令
    p_hooks = subparsers.add_parser("hooks", help="检查钩子充足度")
    p_hooks.add_argument("chapter_file", help="章节文件路径")
    p_hooks.add_argument("--json", action="store_true", help="输出 JSON 格式结果")

    # report 子命令
    p_report = subparsers.add_parser("report", help="全书速决趋势报告")
    p_report.add_argument("book_dir", help="书籍目录路径")
    p_report.add_argument("--json", action="store_true", help="输出 JSON 格式结果")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 2

    # ---- check ----
    if args.command == "check":
        text = _read_file(args.chapter_file)
        if not text:
            print(f"错误：无法读取章节文件 {args.chapter_file}", file=sys.stderr)
            return 2

        chap_num = extract_chapter_number(args.chapter_file)
        result = run_chapter_check(
            text,
            check_hooks=not args.no_hooks,
            check_delta=not args.no_delta,
            is_final_volume=args.final_volume,
        )

        if args.json:
            # 清理不可序列化字段
            clean = dict(result)
            print(json.dumps(clean, ensure_ascii=False, indent=2))
        else:
            print_check_report(result, chap_num, show_fix_hints=args.fix_hints)

        return 0 if result["passed"] else 1

    # ---- cooling ----
    elif args.command == "cooling":
        book_dir = args.book_dir
        if not os.path.isdir(book_dir):
            print(f"错误：书籍目录不存在 {book_dir}", file=sys.stderr)
            return 2

        # 读取伏笔台账
        ledger_path = os.path.join(book_dir, "追踪", "伏笔台账.md")
        foreshadow_violations = []
        if os.path.isfile(ledger_path):
            ledger_text = _read_file(ledger_path)
            foreshadows = parse_foreshadow_ledger(ledger_text)
            foreshadow_violations = check_foreshadow_cooldown(
                foreshadows, args.chapter or 999
            )
        else:
            print("提示：未找到伏笔台账（追踪/伏笔台账.md），跳过伏笔冷却检查", file=sys.stderr)

        # 读取章节摘要
        summary_path = os.path.join(book_dir, "追踪", "章节摘要.md")
        conflict_violations = []
        current_chap = args.chapter
        if os.path.isfile(summary_path):
            summary_text = _read_file(summary_path)
            chapters = parse_chapter_summaries(summary_text)
            if not current_chap and chapters:
                current_chap = max(ch["chapter"] for ch in chapters)
            if current_chap:
                conflict_violations = check_conflict_cooldown(chapters, current_chap)
        else:
            print("提示：未找到章节摘要（追踪/章节摘要.md），跳过冲突冷却检查", file=sys.stderr)

        # 新角色背景速揭（从最新章节文件检测）
        char_violations = []
        chap_files = scan_book_directory(book_dir)
        if chap_files and current_chap:
            for cn, cp in chap_files:
                if cn == current_chap:
                    text = _read_file(cp)
                    char_violations = check_new_character_reveal(text)
                    break

        if args.json:
            output = {
                "foreshadow_violations": foreshadow_violations,
                "conflict_violations": conflict_violations,
                "character_violations": char_violations,
                "total_blocking": (
                    sum(1 for v in foreshadow_violations if v["severity"] == "blocking")
                    + sum(1 for v in conflict_violations if v["severity"] == "blocking")
                    + sum(1 for v in char_violations if v["severity"] == "blocking")
                ),
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print_cooling_report(foreshadow_violations, conflict_violations, char_violations)

        total_blocking = (
            sum(1 for v in foreshadow_violations if v["severity"] == "blocking")
            + sum(1 for v in conflict_violations if v["severity"] == "blocking")
            + sum(1 for v in char_violations if v["severity"] == "blocking")
        )
        return 0 if total_blocking == 0 else 1

    # ---- hooks ----
    elif args.command == "hooks":
        text = _read_file(args.chapter_file)
        if not text:
            print(f"错误：无法读取章节文件 {args.chapter_file}", file=sys.stderr)
            return 2

        hooks = detect_hooks(text)
        strength = hook_strength_level(hooks)
        has_hook, _, hook_issues, _ = check_hook_sufficiency(text)

        if args.json:
            output = {
                "has_hook": has_hook,
                "strength": strength,
                "hooks": hooks,
                "issues": hook_issues,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            sep = "=" * 16
            print(f"\n{sep} 钩子充足度检查 {sep}")
            print(f"\n  最强钩子等级：{strength}")
            all_hooks = hooks["strong"] + hooks["medium"] + hooks["weak"]
            print(f"  钩子总数：{len(all_hooks)}")
            if all_hooks:
                print("\n  检测到的钩子：")
                for h in all_hooks:
                    print(f"    [{h['strength']}] {h['pattern']}：{h['match']}")
            if hook_issues:
                print("\n  问题：")
                for issue in hook_issues:
                    print(f"    [{issue['severity']}] {issue['description']}")
            print(f"\n  结论：{'PASS' if has_hook else 'FAIL'}")

        return 0 if has_hook else 1

    # ---- report ----
    elif args.command == "report":
        book_dir = args.book_dir
        if not os.path.isdir(book_dir):
            print(f"错误：书籍目录不存在 {book_dir}", file=sys.stderr)
            return 2

        report = generate_book_report(book_dir)

        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            print_book_report(report)

        return 0 if report.get("passed", False) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
