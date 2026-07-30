#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_anti_resolution.py — 测试 anti_resolution_guard.py 反速决守卫核心功能。

运行方式：
    python scripts/tests/test_anti_resolution.py
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import anti_resolution_guard as arg
from anti_resolution_guard import (
    # 核心检测函数
    detect_conflict_resolution,
    detect_secret_reveal,
    detect_suspense_resolve,
    detect_crisis_passed,
    detect_relationship_settled,
    detect_growth_spike,
    detect_all_resolutions,
    # 钩子检测
    detect_hooks,
    hook_strength_level,
    check_hook_sufficiency,
    # 问题增量
    check_question_delta,
    count_questions,
    # 冷却期
    parse_foreshadow_ledger,
    check_foreshadow_cooldown,
    parse_chapter_summaries,
    check_conflict_cooldown,
    check_new_character_reveal,
    # 综合
    run_chapter_check,
    # 工具
    strip_dialogue,
    get_location,
    extract_chapter_number,
    split_paragraphs,
    _find_marker_positions,
    _detect_quick_resolution,
    # 常量
    QUICK_RESOLUTION_WINDOW,
    HOOK_WINDOW_CHARS,
    MINI_FORESHADOW_MAX_STARS,
)


# ============================================================
# 测试用文本构造辅助
# ============================================================

def _make_conflict_quick_text():
    """构造一个冲突速决的测试文本（冲突出现后立即解决）。"""
    return (
        "赵天霸一脸狞笑，拦住了林辰的去路，不屑地说："
        "\"就你这废柴，也配走这条路？\""
        "林辰眼神一冷，还没等对方反应过来，一拳就将赵天霸打飞出去，"
        "后者重重摔在地上，狼狈不堪，再也不敢嚣张。"
    )


def _make_conflict_slow_text():
    """构造一个冲突不速决的测试文本（冲突后有足够铺垫）。"""
    return (
        "赵天霸一脸狞笑，拦住了林辰的去路，不屑地说："
        "\"就你这废柴，也配走这条路？\""
        "周围的同学纷纷围了过来，窃窃私语，都想看林辰的笑话。"
        "林辰站在原地，眼神平静，似乎在思考什么。"
        "时间一分一秒过去，赵天霸有些不耐烦了，再次开口挑衅。"
        "林辰缓缓抬起头，目光如刀，直视着对方。"
        "他心中已有定计，但此刻并不打算暴露全部实力。"
    )


def _make_secret_quick_text():
    """构造一个秘密速揭的测试文本。"""
    return (
        "少女留下一枚玉佩后匆匆离去，她的身份成谜，没人知道她来自何方。"
        "原来她是上古世家的嫡女，因为家族变故才流落至此。"
    )


def _make_suspense_quick_text():
    """构造一个悬念速解的测试文本。"""
    return (
        "林辰心中纳闷，这声音到底是谁发出的？为什么如此熟悉？"
        "原来是王胖子在背后拍了他一下，搞了半天是这家伙。"
    )


def _make_crisis_quick_text():
    """构造一个危机速过的测试文本。"""
    return (
        "前方突然出现一头妖兽，千钧一发，命悬一线！"
        "林辰一掌拍出，妖兽应声倒地，不过如此，有惊无险。"
    )


def _make_relationship_quick_text():
    """构造一个关系速定的测试文本。"""
    return (
        "这是王胖子第一次见到林辰，两人素未谋面，互不相识。"
        "王胖子当场就死心塌地要认林辰当大哥，誓死追随。"
    )


def _make_growth_spike_text():
    """构造一个成长速升的测试文本。"""
    return (
        "林辰盘膝而坐，运转纯阳功。"
        "他的境界从淬体三重突破到淬体五重，又飙升至淬体七重，"
        "连升三级，实力暴涨，直接踏入了炼气境。"
    )


def _make_hook_strong_text():
    """构造一个有强钩子结尾的文本。"""
    body = "林辰缓缓睁开眼，感受着体内澎湃的力量。" * 20
    ending = "\n然而他还不知道，一场更大的风暴正在悄然逼近，这才刚刚开始。"
    return body + ending


def _make_hook_none_text():
    """构造一个无钩子结尾的文本。"""
    body = "林辰缓缓睁开眼，感受着体内澎湃的力量。" * 20
    ending = "\n他满意地点点头，今天的修炼就到这里了。"
    return body + ending


# ============================================================
# 1. 6 种速决模式检测测试
# ============================================================

class TestConflictResolution(unittest.TestCase):
    """冲突速决检测。"""

    def test_quick_conflict_detected(self):
        """冲突速决应被检测到。"""
        text = _make_conflict_quick_text()
        issues = detect_conflict_resolution(text)
        self.assertTrue(len(issues) > 0, "应检测到冲突速决")
        self.assertEqual(issues[0]["type"], "conflict")
        self.assertEqual(issues[0]["severity"], "blocking")

    def test_slow_conflict_not_detected(self):
        """非速决冲突不应被检测到。"""
        text = _make_conflict_slow_text()
        issues = detect_conflict_resolution(text)
        # 冲突有但没有快速解决，所以不触发
        self.assertEqual(len(issues), 0)

    def test_clean_text_no_conflict(self):
        """干净文本无冲突速决。"""
        text = "今天天气真好，他走出门去散步，阳光洒在身上暖洋洋的。"
        issues = detect_conflict_resolution(text)
        self.assertEqual(issues, [])


class TestSecretReveal(unittest.TestCase):
    """秘密速揭检测。"""

    def test_quick_secret_detected(self):
        """秘密速揭应被检测到。"""
        text = _make_secret_quick_text()
        issues = detect_secret_reveal(text)
        self.assertTrue(len(issues) > 0, "应检测到秘密速揭")
        self.assertEqual(issues[0]["type"], "secret")
        self.assertEqual(issues[0]["severity"], "blocking")

    def test_secret_without_reveal_not_detected(self):
        """只有秘密没有揭露不触发。"""
        text = "少女的身份成谜，没人知道她来自何方。她只是默默地看着远方。"
        issues = detect_secret_reveal(text)
        self.assertEqual(len(issues), 0)


class TestSuspenseResolve(unittest.TestCase):
    """悬念速解检测。"""

    def test_quick_suspense_detected(self):
        """悬念速解应被检测到。"""
        text = _make_suspense_quick_text()
        issues = detect_suspense_resolve(text)
        self.assertTrue(len(issues) > 0, "应检测到悬念速解")
        self.assertEqual(issues[0]["type"], "suspense")
        self.assertEqual(issues[0]["severity"], "warn")

    def test_suspense_without_answer(self):
        """只有悬念没有答案不触发。"""
        text = "这到底是谁发出的声音？林辰百思不得其解，心中充满了疑惑。"
        issues = detect_suspense_resolve(text)
        self.assertEqual(len(issues), 0)


class TestCrisisPassed(unittest.TestCase):
    """危机速过检测。"""

    def test_quick_crisis_detected(self):
        """危机速过应被检测到。"""
        text = _make_crisis_quick_text()
        issues = detect_crisis_passed(text)
        self.assertTrue(len(issues) > 0, "应检测到危机速过")
        self.assertEqual(issues[0]["type"], "crisis")
        self.assertEqual(issues[0]["severity"], "blocking")

    def test_crisis_without_easy_resolve(self):
        """危机但没有轻松化解不触发。"""
        text = "前方千钧一发，命悬一线！林辰咬牙坚持，浑身浴血，艰难地支撑着。"
        issues = detect_crisis_passed(text)
        self.assertEqual(len(issues), 0)


class TestRelationshipSettled(unittest.TestCase):
    """关系速定检测。"""

    def test_quick_relationship_detected(self):
        """关系速定应被检测到。"""
        text = _make_relationship_quick_text()
        issues = detect_relationship_settled(text)
        self.assertTrue(len(issues) > 0, "应检测到关系速定")
        self.assertEqual(issues[0]["type"], "relationship")
        self.assertEqual(issues[0]["severity"], "warn")

    def test_relationship_slow_build(self):
        """关系慢慢建立不触发。"""
        text = "两人初次见面，互相寒暄了几句，都对对方留下了初步印象。"
        issues = detect_relationship_settled(text)
        self.assertEqual(len(issues), 0)


class TestGrowthSpike(unittest.TestCase):
    """成长速升检测。"""

    def test_growth_spike_detected(self):
        """成长速升应被检测到。"""
        text = _make_growth_spike_text()
        issues = detect_growth_spike(text)
        self.assertTrue(len(issues) > 0, "应检测到成长速升")
        self.assertEqual(issues[0]["type"], "growth")
        self.assertEqual(issues[0]["severity"], "warn")

    def test_growth_with_process(self):
        """有过程描写的成长不触发。"""
        text = (
            "林辰日夜修炼，打坐调息，感悟功法真谛。"
            "经过数月的苦修，他终于突破瓶颈，实力有所提升。"
            "这场战斗让他对战技的领悟更加深刻。"
        )
        issues = detect_growth_spike(text)
        self.assertEqual(len(issues), 0)

    def test_single_growth_not_spike(self):
        """单次成长不构成速升。"""
        text = "林辰运转功法，突破到了淬体四重。"
        issues = detect_growth_spike(text)
        self.assertEqual(len(issues), 0)


class TestAllResolutions(unittest.TestCase):
    """综合速决检测。"""

    def test_detect_all_returns_list(self):
        """detect_all_resolutions 返回列表。"""
        text = _make_conflict_quick_text()
        issues = detect_all_resolutions(text)
        self.assertIsInstance(issues, list)

    def test_multiple_types_detected(self):
        """多种速决模式可同时检测到。"""
        text = _make_conflict_quick_text() + _make_secret_quick_text()
        issues = detect_all_resolutions(text)
        types = {i["type"] for i in issues}
        self.assertIn("conflict", types)
        self.assertIn("secret", types)


# ============================================================
# 2. 冷却期计算测试
# ============================================================

class TestForeshadowCooldown(unittest.TestCase):
    """伏笔冷却期检测。"""

    def _make_ledger_text(self, foreshadows=None):
        """构造伏笔台账文本。"""
        foreshadows = foreshadows or []
        lines = [
            "# 伏笔台账",
            "",
            "| 编号 | 伏笔内容 | 埋设章节 | 状态 | 回收章节 | 重要程度 |",
            "|:----:|---------|:-------:|:----:|:-------:|:-------:|",
        ]
        for f in foreshadows:
            lines.append(
                f"| {f['id']} | {f['content']} | 第{f['plant']}章 | "
                f"{f['status']} | {f['resolve']} | {f['stars']} |"
            )
        return "\n".join(lines) + "\n"

    def test_parse_ledger(self):
        """解析伏笔台账。"""
        text = self._make_ledger_text([
            {"id": "F001", "content": "测试伏笔", "plant": 1,
             "status": "🟢已回收", "resolve": "第5章", "stars": "★★★☆☆"},
        ])
        foreshadows = parse_foreshadow_ledger(text)
        self.assertEqual(len(foreshadows), 1)
        self.assertEqual(foreshadows[0]["id"], "F001")
        self.assertEqual(foreshadows[0]["plant_chapter"], 1)
        self.assertEqual(foreshadows[0]["resolve_chapter"], 5)
        self.assertEqual(foreshadows[0]["stars"], 3)

    def test_quick_resolve_violation(self):
        """重要伏笔 3 章内回收应违规。"""
        text = self._make_ledger_text([
            {"id": "F001", "content": "重要伏笔", "plant": 1,
             "status": "🟢已回收", "resolve": "第2章", "stars": "★★★★★"},
        ])
        foreshadows = parse_foreshadow_ledger(text)
        violations = check_foreshadow_cooldown(foreshadows, current_chapter=10)
        self.assertTrue(len(violations) > 0)
        self.assertEqual(violations[0]["gap"], 1)
        self.assertEqual(violations[0]["severity"], "blocking")

    def test_mini_foreshadow_exempt(self):
        """微型伏笔（2星及以下）豁免冷却期。"""
        text = self._make_ledger_text([
            {"id": "F002", "content": "微型伏笔", "plant": 1,
             "status": "🟢已回收", "resolve": "第2章", "stars": "★★☆☆☆"},
        ])
        foreshadows = parse_foreshadow_ledger(text)
        violations = check_foreshadow_cooldown(foreshadows, current_chapter=10)
        self.assertEqual(len(violations), 0)

    def test_unresolved_not_violation(self):
        """未回收的伏笔不触发违规。"""
        text = self._make_ledger_text([
            {"id": "F003", "content": "未回收伏笔", "plant": 1,
             "status": "🔴未回收", "resolve": "—", "stars": "★★★★★"},
        ])
        foreshadows = parse_foreshadow_ledger(text)
        violations = check_foreshadow_cooldown(foreshadows, current_chapter=10)
        self.assertEqual(len(violations), 0)

    def test_slow_resolve_ok(self):
        """伏笔在 3 章后回收正常。"""
        text = self._make_ledger_text([
            {"id": "F004", "content": "正常伏笔", "plant": 1,
             "status": "🟢已回收", "resolve": "第5章", "stars": "★★★★★"},
        ])
        foreshadows = parse_foreshadow_ledger(text)
        violations = check_foreshadow_cooldown(foreshadows, current_chapter=10)
        self.assertEqual(len(violations), 0)


class TestConflictCooldown(unittest.TestCase):
    """冲突类型冷却检测。"""

    def _make_summary_text(self, chapters_data):
        """构造章节摘要文本。"""
        lines = ["# 章节摘要", ""]
        for ch in chapters_data:
            lines.append(f"## 第{ch['num']}章：{ch['title']}")
            lines.append("")
            lines.append("### 核心事件")
            lines.append(ch.get("events", ""))
            lines.append("")
            lines.append("### 伏笔推进")
            lines.append(ch.get("foreshadow", "无"))
            lines.append("")
        return "\n".join(lines)

    def test_parse_chapter_summaries(self):
        """解析章节摘要。"""
        text = self._make_summary_text([
            {"num": 1, "title": "测试章", "events": "主角打脸反派，一场激烈的战斗"},
        ])
        chapters = parse_chapter_summaries(text)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["chapter"], 1)
        self.assertEqual(chapters[0]["title"], "测试章")

    def test_consecutive_same_conflict(self):
        """连续两章同类冲突应告警。"""
        text = self._make_summary_text([
            {"num": 1, "title": "第一章", "events": "主角与反派战斗，打脸羞辱"},
            {"num": 2, "title": "第二章", "events": "又一场比试战斗，再次打脸"},
        ])
        chapters = parse_chapter_summaries(text)
        violations = check_conflict_cooldown(chapters, current_chapter=2)
        self.assertTrue(len(violations) > 0)
        self.assertIn("conflict_cooldown", [v["type"] for v in violations])

    def test_different_conflict_ok(self):
        """不同类型冲突不触发。"""
        text = self._make_summary_text([
            {"num": 1, "title": "第一章", "events": "主角战斗"},
            {"num": 2, "title": "第二章", "events": "主角揭秘真相"},
        ])
        chapters = parse_chapter_summaries(text)
        violations = check_conflict_cooldown(chapters, current_chapter=2)
        self.assertEqual(len(violations), 0)

    def test_single_chapter_no_violation(self):
        """单章不触发冷却检测。"""
        text = self._make_summary_text([
            {"num": 1, "title": "第一章", "events": "主角战斗打脸"},
        ])
        chapters = parse_chapter_summaries(text)
        violations = check_conflict_cooldown(chapters, current_chapter=1)
        self.assertEqual(len(violations), 0)


class TestNewCharacterReveal(unittest.TestCase):
    """新角色背景速揭检测。"""

    def test_quick_reveal_detected(self):
        """新角色登场后立即揭示背景应被检测。"""
        text = (
            "一个陌生的男子走了进来，众人从未见过此人。"
            "他名叫李云，出身于上古世家，背景显赫。"
        )
        issues = check_new_character_reveal(text)
        self.assertTrue(len(issues) > 0)
        self.assertEqual(issues[0]["type"], "character_reveal")

    def test_slow_reveal_ok(self):
        """新角色登场但不立即揭示背景正常。"""
        text = (
            "一个陌生的男子走了进来，众人从未见过此人。"
            "他只是静静地站在角落，观察着周围的一切。"
            "没有人知道他的来历。"
        )
        issues = check_new_character_reveal(text)
        self.assertEqual(len(issues), 0)


# ============================================================
# 3. 钩子检测测试
# ============================================================

class TestHookDetection(unittest.TestCase):
    """钩子检测。"""

    def test_strong_hook_detected(self):
        """强钩子应被检测到。"""
        text = _make_hook_strong_text()
        hooks = detect_hooks(text)
        self.assertTrue(len(hooks["strong"]) > 0, "应检测到强钩子")

    def test_medium_hook_detected(self):
        """中钩子应被检测到。"""
        text = ("他走在路上。" * 30 + "\n难道这就是传说中的宝物？")
        hooks = detect_hooks(text)
        self.assertTrue(len(hooks["medium"]) > 0, "应检测到中钩子")

    def test_weak_hook_detected(self):
        """弱钩子应被检测到。"""
        text = ("他走在路上。" * 30 + "\n接下来会发生什么，拭目以待。")
        hooks = detect_hooks(text)
        self.assertTrue(len(hooks["weak"]) > 0, "应检测到弱钩子")

    def test_no_hook(self):
        """无钩子文本应检测不到。"""
        text = _make_hook_none_text()
        hooks = detect_hooks(text)
        total = len(hooks["strong"]) + len(hooks["medium"]) + len(hooks["weak"])
        self.assertEqual(total, 0)

    def test_hook_strength_level_strong(self):
        """hook_strength_level 返回强。"""
        hooks = {"strong": [{"strength": "强"}], "medium": [], "weak": []}
        self.assertEqual(hook_strength_level(hooks), "强")

    def test_hook_strength_level_none(self):
        """hook_strength_level 返回无。"""
        hooks = {"strong": [], "medium": [], "weak": []}
        self.assertEqual(hook_strength_level(hooks), "无")

    def test_hook_sufficiency_pass(self):
        """有钩子的章节通过检查。"""
        text = _make_hook_strong_text()
        has_hook, strength, issues, _ = check_hook_sufficiency(text)
        self.assertTrue(has_hook)
        self.assertEqual(len(issues), 0)

    def test_hook_sufficiency_fail(self):
        """无钩子的章节不通过。"""
        text = _make_hook_none_text()
        has_hook, strength, issues, _ = check_hook_sufficiency(text)
        self.assertFalse(has_hook)
        self.assertTrue(len(issues) > 0)
        self.assertEqual(issues[0]["severity"], "blocking")

    def test_hook_only_in_end_window(self):
        """开头的钩子不算（只检查章末窗口）。"""
        # 构造足够长的文本，确保开头钩子不在 500 字章末窗口内
        hook_at_start = "然而他还不知道，一场风暴正在逼近。"
        long_body = "他走在路上，看着周围的风景。" * 100  # 约 1600 字
        text = hook_at_start + long_body
        hooks = detect_hooks(text)
        # 钩子在开头（距离结尾 > 500 字），不应被检测到
        total = len(hooks["strong"]) + len(hooks["medium"]) + len(hooks["weak"])
        self.assertEqual(total, 0)


# ============================================================
# 4. 问题增量检查测试
# ============================================================

class TestQuestionDelta(unittest.TestCase):
    """问题增量检查。"""

    def test_count_questions_basic(self):
        """count_questions 基础计数。"""
        text = "这是什么？为什么会这样？难道是他做的？"
        q, setup, resolve = count_questions(text)
        self.assertGreater(setup, 0)
        self.assertGreaterEqual(q, 0)

    def test_delta_positive(self):
        """结尾问题多于开头 -> 正增量。"""
        start_text = "平静的一天，他走出门去。"
        end_text = "这到底是为什么？谜团越来越深，秘密还在继续。"
        text = start_text + "中间内容。" * 50 + end_text
        delta, start_q, end_q, issues = check_question_delta(text)
        self.assertGreater(delta, 0)
        self.assertEqual(len(issues), 0)

    def test_delta_negative_warns(self):
        """结尾问题少于开头 -> 告警。"""
        start_text = "这是什么？为什么？难道有秘密？谜团不解。"
        end_text = "原来如此，一切都清楚了，答案已经揭晓。"
        text = start_text + "中间内容。" * 50 + end_text
        delta, start_q, end_q, issues = check_question_delta(text)
        self.assertLess(delta, 0)
        self.assertTrue(len(issues) > 0)
        self.assertEqual(issues[0]["type"], "question_decrease")

    def test_final_volume_exempt(self):
        """终局卷豁免问题递减。"""
        start_text = "这是什么？为什么？难道有秘密？谜团不解。"
        end_text = "原来如此，一切都清楚了，答案已经揭晓。"
        text = start_text + "中间内容。" * 50 + end_text
        delta, start_q, end_q, issues = check_question_delta(text, is_final_volume=True)
        self.assertEqual(len(issues), 0)


# ============================================================
# 5. 工具函数测试
# ============================================================

class TestUtilityFunctions(unittest.TestCase):
    """工具函数测试。"""

    def test_strip_dialogue(self):
        """移除对话内容。"""
        text = '他说：「你好，世界。」然后走了出去。'
        narration = strip_dialogue(text)
        self.assertNotIn("你好", narration)
        self.assertIn("然后走了出去", narration)

    def test_strip_dialogue_english_quotes(self):
        """移除英文引号对话。"""
        text = '他说："你好。"然后离开。'
        narration = strip_dialogue(text)
        self.assertNotIn("你好", narration)

    def test_get_location_beginning(self):
        """位置在开头。"""
        loc = get_location(50, 1000)
        self.assertEqual(loc, "开头")

    def test_get_location_middle(self):
        """位置在中间。"""
        loc = get_location(500, 1000)
        self.assertEqual(loc, "中间")

    def test_get_location_end(self):
        """位置在结尾。"""
        loc = get_location(900, 1000)
        self.assertEqual(loc, "结尾")

    def test_extract_chapter_from_text(self):
        """从文本提取章号。"""
        text = "第001章 测试章节\n内容..."
        num = extract_chapter_number(text)
        self.assertEqual(num, 1)

    def test_extract_chapter_invalid(self):
        """无效文本返回 None。"""
        num = extract_chapter_number("没有章号的文本")
        self.assertIsNone(num)

    def test_split_paragraphs(self):
        """分段。"""
        text = "第一段\n\n第二段\n\n第三段"
        paras = split_paragraphs(text)
        self.assertEqual(len(paras), 3)

    def test_find_marker_positions(self):
        """查找标记位置。"""
        text = "他冷笑一声，然后不屑地走开。"
        positions = _find_marker_positions(text, ["冷笑", "不屑"])
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0][1], "冷笑")
        self.assertEqual(positions[1][1], "不屑")

    def test_detect_quick_resolution_finds_pair(self):
        """_detect_quick_resolution 找到快速解决对。"""
        text = "冲突发生，立即被解决了。"
        results = _detect_quick_resolution(
            text, ["冲突"], ["解决"], window_chars=50
        )
        self.assertTrue(len(results) > 0)

    def test_detect_quick_resolution_far_apart(self):
        """距离远不触发。"""
        text = "冲突" + "。" * 1000 + "解决"
        results = _detect_quick_resolution(
            text, ["冲突"], ["解决"], window_chars=500
        )
        self.assertEqual(len(results), 0)


# ============================================================
# 6. 综合检查测试
# ============================================================

class TestRunChapterCheck(unittest.TestCase):
    """run_chapter_check 综合检查。"""

    def test_clean_text_passes(self):
        """干净文本通过检查。"""
        text = (
            "清晨，林辰走出家门，阳光洒在身上。"
            "他来到学校，开始了一天的学习生活。"
            "然而他还不知道，一场更大的风暴正在悄然逼近。"
        )
        result = run_chapter_check(text)
        self.assertIn("passed", result)
        self.assertIn("resolution_issues", result)
        self.assertIn("hook_strength", result)
        self.assertIn("question_delta", result)

    def test_bad_text_fails(self):
        """有问题的文本不通过。"""
        text = _make_conflict_quick_text() + _make_hook_none_text()
        result = run_chapter_check(text)
        self.assertFalse(result["passed"])
        self.assertGreater(result["total_blocking"], 0)

    def test_skip_hook_check(self):
        """可以跳过钩子检查。"""
        text = _make_hook_none_text()
        result = run_chapter_check(text, check_hooks=False)
        self.assertEqual(len(result["hook_issues"]), 0)

    def test_skip_delta_check(self):
        """可以跳过问题增量检查。"""
        text = _make_hook_strong_text()
        result = run_chapter_check(text, check_delta=False)
        self.assertEqual(len(result["delta_issues"]), 0)


# ============================================================
# 7. CLI 子命令测试
# ============================================================

class TestCLICheck(unittest.TestCase):
    """CLI check 子命令。"""

    def setUp(self):
        """创建临时章节文件。"""
        self.tmpdir = tempfile.mkdtemp()
        self.chapter_file = os.path.join(self.tmpdir, "第001章_测试.md")
        with open(self.chapter_file, "w", encoding="utf-8") as f:
            f.write(_make_hook_strong_text())

    def tearDown(self):
        """清理临时文件。"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_check_command_runs(self):
        """check 子命令可运行。"""
        sys.argv = ["anti_resolution_guard.py", "check", self.chapter_file]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        self.assertIn("反速决守卫检测报告", output)
        self.assertIn("速决模式检测", output)
        self.assertIn("钩子充足度", output)

    def test_check_command_json_output(self):
        """check 子命令 --json 输出。"""
        sys.argv = ["anti_resolution_guard.py", "check", self.chapter_file, "--json"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        data = json.loads(output)
        self.assertIn("passed", data)
        self.assertIn("resolution_issues", data)
        self.assertIn("hook_strength", data)

    def test_check_command_fix_hints(self):
        """check 子命令 --fix-hints 输出建议。"""
        sys.argv = ["anti_resolution_guard.py", "check", self.chapter_file, "--fix-hints"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        # 没有问题时也应该正常输出
        self.assertIn("检测总结", output)


class TestCLIHooks(unittest.TestCase):
    """CLI hooks 子命令。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.chapter_file = os.path.join(self.tmpdir, "第001章_测试.md")
        with open(self.chapter_file, "w", encoding="utf-8") as f:
            f.write(_make_hook_strong_text())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_hooks_command_runs(self):
        """hooks 子命令可运行。"""
        sys.argv = ["anti_resolution_guard.py", "hooks", self.chapter_file]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        self.assertIn("钩子充足度检查", output)

    def test_hooks_command_json(self):
        """hooks 子命令 --json。"""
        sys.argv = ["anti_resolution_guard.py", "hooks", self.chapter_file, "--json"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        data = json.loads(output)
        self.assertIn("has_hook", data)
        self.assertIn("strength", data)
        self.assertIn("hooks", data)


class TestCLICooling(unittest.TestCase):
    """CLI cooling 子命令。"""

    def setUp(self):
        """创建模拟书籍目录。"""
        self.tmpdir = tempfile.mkdtemp()
        # 创建正文目录
        text_dir = os.path.join(self.tmpdir, "正文")
        os.makedirs(text_dir, exist_ok=True)
        with open(os.path.join(text_dir, "第001章_测试.md"), "w", encoding="utf-8") as f:
            f.write(_make_hook_strong_text())
        # 创建追踪目录
        track_dir = os.path.join(self.tmpdir, "追踪")
        os.makedirs(track_dir, exist_ok=True)
        # 伏笔台账
        with open(os.path.join(track_dir, "伏笔台账.md"), "w", encoding="utf-8") as f:
            f.write("# 伏笔台账\n\n")
            f.write("| 编号 | 伏笔内容 | 埋设章节 | 状态 | 回收章节 | 重要程度 |\n")
            f.write("|:----:|---------|:-------:|:----:|:-------:|:-------:|\n")
            f.write("| F001 | 测试伏笔 | 第1章 | 🟢已回收 | 第2章 | ★★★★★ |\n")
        # 章节摘要
        with open(os.path.join(track_dir, "章节摘要.md"), "w", encoding="utf-8") as f:
            f.write("# 章节摘要\n\n")
            f.write("## 第1章：测试\n\n### 核心事件\n主角战斗打脸\n\n")
            f.write("## 第2章：测试2\n\n### 核心事件\n又一场战斗比试\n\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cooling_command_runs(self):
        """cooling 子命令可运行。"""
        sys.argv = ["anti_resolution_guard.py", "cooling", self.tmpdir, "--chapter", "2"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        self.assertIn("冷却期违规检查", output)

    def test_cooling_command_json(self):
        """cooling 子命令 --json。"""
        sys.argv = ["anti_resolution_guard.py", "cooling", self.tmpdir, "--chapter", "2", "--json"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        data = json.loads(output)
        self.assertIn("foreshadow_violations", data)
        self.assertIn("conflict_violations", data)
        self.assertIn("character_violations", data)


class TestCLIReport(unittest.TestCase):
    """CLI report 子命令。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        text_dir = os.path.join(self.tmpdir, "正文")
        os.makedirs(text_dir, exist_ok=True)
        with open(os.path.join(text_dir, "第001章_测试.md"), "w", encoding="utf-8") as f:
            f.write(_make_hook_strong_text())
        with open(os.path.join(text_dir, "第002章_测试2.md"), "w", encoding="utf-8") as f:
            f.write(_make_hook_strong_text())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_report_command_runs(self):
        """report 子命令可运行。"""
        sys.argv = ["anti_resolution_guard.py", "report", self.tmpdir]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        self.assertIn("全书速决趋势报告", output)
        self.assertIn("速决类型分布", output)

    def test_report_command_json(self):
        """report 子命令 --json。"""
        sys.argv = ["anti_resolution_guard.py", "report", self.tmpdir, "--json"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        output = f.getvalue()
        data = json.loads(output)
        self.assertIn("total_chapters", data)
        self.assertIn("type_counts", data)
        self.assertIn("strength_history", data)


class TestCLINoCommand(unittest.TestCase):
    """CLI 无子命令时显示帮助。"""

    def test_no_command_shows_help(self):
        """无子命令显示帮助并返回 2。"""
        sys.argv = ["anti_resolution_guard.py"]
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                from anti_resolution_guard import main
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
        self.assertEqual(exit_code, 2)


# ============================================================
# main
# ============================================================

if __name__ == "__main__":
    unittest.main()
