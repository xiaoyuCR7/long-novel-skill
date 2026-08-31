#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_context_manager.py — 测试 context_manager.py 动态上下文管理。

运行方式：
    python scripts/tests/test_context_manager.py
"""

import os
import sys
import tempfile
import unittest
import json
import subprocess
import ast
import hashlib
import warnings
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from context_manager import (
    determine_stage,
    get_dynamic_budget_ratios,
    compress_summaries,
    _estimate_total_chapters,
    select_context,
    generate_brief_context,
    truncate_text,
    count_chars,
)


class TestDetermineStage(unittest.TestCase):
    """测试阶段判定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "大纲").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_opening_stage(self):
        """章节 1/100 = 1% → 开篇。"""
        (self.root / "大纲" / "总纲.md").write_text("全书共100章", encoding="utf-8")
        stage = determine_stage(self.root, 1)
        self.assertEqual(stage, "opening")

    def test_development_stage(self):
        """章节 15/100 = 15% → 发展。"""
        (self.root / "大纲" / "总纲.md").write_text("全书共100章", encoding="utf-8")
        stage = determine_stage(self.root, 15)
        self.assertEqual(stage, "development")

    def test_deepwater_stage(self):
        """章节 50/100 = 50% → 深水。"""
        (self.root / "大纲" / "总纲.md").write_text("全书共100章", encoding="utf-8")
        stage = determine_stage(self.root, 50)
        self.assertEqual(stage, "deepwater")

    def test_finale_stage(self):
        """章节 90/100 = 90% → 收束。"""
        (self.root / "大纲" / "总纲.md").write_text("全书共100章", encoding="utf-8")
        stage = determine_stage(self.root, 90)
        self.assertEqual(stage, "finale")

    def test_estimate_from_chapter_files(self):
        """无总纲时从章纲文件数估算。"""
        (self.root / "大纲" / "章纲_第001章.md").write_text("x")
        (self.root / "大纲" / "章纲_第002章.md").write_text("x")
        (self.root / "大纲" / "章纲_第003章.md").write_text("x")
        total = _estimate_total_chapters(self.root)
        self.assertEqual(total, 3)

    def test_estimate_none(self):
        """无任何线索时返回 None。"""
        total = _estimate_total_chapters(self.root)
        self.assertIsNone(total)

    def test_estimate_uses_largest_chapter_range_end(self):
        """常见的“第1-50章”范围应优先于卷数回退估算。"""
        (self.root / "大纲" / "总纲.md").write_text(
            "第1卷：第1-50章\n第8卷：第951-1000章", encoding="utf-8")
        self.assertEqual(_estimate_total_chapters(self.root), 1000)


class TestGetDynamicBudgetRatios(unittest.TestCase):
    """测试预算比例获取。"""

    def test_opening_ratios_sum_to_one(self):
        """开篇阶段比例之和为 1。"""
        ratios = get_dynamic_budget_ratios("opening")
        total = sum(ratios.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_finale_has_milestone(self):
        """收束阶段包含 milestone。"""
        ratios = get_dynamic_budget_ratios("finale")
        self.assertIn("milestone", ratios)

    def test_invalid_stage_fallback(self):
        """无效阶段应返回默认比例。"""
        ratios = get_dynamic_budget_ratios("nonexistent")
        total = sum(ratios.values())
        self.assertAlmostEqual(total, 1.0, places=2)


class TestSelectContext(unittest.TestCase):
    """测试上下文选取。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "大纲").mkdir(parents=True)
        (self.root / "追踪").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_select_returns_structure(self):
        """select_context 返回完整结构。"""
        (self.root / "大纲" / "总纲.md").write_text("全书共100章", encoding="utf-8")
        result = select_context(self.root, 1, max_chars=8000)
        self.assertIn("stage", result)
        self.assertIn("budget_ratios_used", result)
        self.assertIn("components", result)
        self.assertIn("max_chars", result)

    def test_select_uses_specified_stage(self):
        """传入 stage 参数时直接使用。"""
        result = select_context(self.root, 1, max_chars=8000, stage="finale")
        self.assertEqual(result["stage"], "finale")

    def test_select_budget_allocation(self):
        """预算应分配给各组件。"""
        (self.root / "大纲" / "总纲.md").write_text("全书共100章", encoding="utf-8")
        result = select_context(self.root, 10, max_chars=10000)
        # 检查 budget_ratios_used 存在且比例之和合理
        ratios = result["budget_ratios_used"]
        total = sum(ratios.values())
        self.assertAlmostEqual(total, 1.0, places=2)


class TestRequiredContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in ("大纲", "追踪", "正文", "设定/角色"):
            (self.root / folder).mkdir(parents=True)
        self.write("大纲/章纲_第002章.md", "人物：林澈\n取回铜钥匙。")
        self.write("设定/角色/林澈.md", "林澈，修表师。")
        self.write("追踪/角色状态.md", "# 角色状态\n## 林澈\n- 位置：北站\n- 伤势：右手骨折\n- 持有物：铜钥匙")
        self.write("追踪/伏笔台账.md", "# 伏笔\n🟡 钥匙暂不能开门。")
        self.write("追踪/时间线.md", "# 时间线\n第二天上午，距离末班车还有两小时。")
        self.write("追踪/章节摘要.md", "## 近章详记\n### 第1章 北站\n林澈右手受伤，把钥匙藏入衣袋。")

    def write(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")

    def test_preserves_current_state_without_chapter_numbers(self):
        result = select_context(self.root, 2)
        state = result["components"]["character_state"]["content"]
        for fact in ("北站", "右手骨折", "铜钥匙"):
            self.assertIn(fact, state)
        self.assertTrue(result.get("ready"))

    def test_r5_cast_punctuation_and_negative_notes(self):
        from context_manager import extract_mentioned_characters
        outline = "## 出场人物\n- 主要：林澈，唐序。\n- 次要：不新增出场人物。\n人物：无名。"
        self.assertEqual(extract_mentioned_characters(outline, self.root), ["林澈", "唐序", "无名"])

    def test_r5_state_only_legacy_card_is_explicit_and_fresh(self):
        from context_manager import verify_context
        (self.root / "设定/角色/林澈.md").unlink()
        packet = select_context(self.root, 2)
        self.assertTrue(packet["ready"], packet["missing_required"])
        cards = packet["components"]["character_cards"]
        self.assertEqual(cards["characters"], [])
        self.assertEqual(cards["state_only"], [{"name": "林澈", "missing_card": "设定/角色/林澈.md",
                                               "source": "追踪/角色状态.md"}])
        brief = generate_brief_context(packet)
        self.assertIn("未载明事实保持未知", brief)
        self.assertIn("右手骨折", brief)
        self.assertTrue(verify_context(self.root, packet)["ready"])

    def test_r5_new_card_invalidates_state_only_packet(self):
        from context_manager import verify_context
        (self.root / "设定/角色/林澈.md").unlink()
        packet = select_context(self.root, 2)
        self.write("设定/角色/林澈.md", "## 硬约束\n不能用右手。")
        result = verify_context(self.root, packet)
        self.assertEqual(result["status"], "stale")
        self.assertIn("设定/角色/林澈.md", result["changed"])

    def test_r5_empty_or_unreadable_card_never_uses_state_only(self):
        for data in (b"", b"\xff"):
            with self.subTest(data=data):
                (self.root / "设定/角色/林澈.md").write_bytes(data)
                result = select_context(self.root, 2)
                self.assertFalse(result["ready"])
                self.assertIn("设定/角色/林澈.md", result["missing_required"])
                self.assertFalse(result["components"]["character_cards"].get("state_only"))

    def test_r5_state_only_needs_own_state_not_relationship_mention(self):
        (self.root / "设定/角色/林澈.md").unlink()
        self.write("追踪/角色状态.md", "## 周言\n- 关系：认识林澈。")
        result = select_context(self.root, 2)
        self.assertFalse(result["ready"])
        self.assertIn("追踪/角色状态.md#林澈", result["missing_required"])
        self.assertFalse(result["components"]["character_cards"].get("state_only"))

    def test_r5_state_only_path_validation_precedes_reads(self):
        from context_manager import verify_context, _package_sha256
        packet = select_context(self.root, 2)
        packet["components"]["character_cards"]["state_only"] = [
            {"name": "../outside", "missing_card": "../outside.md", "source": "追踪/角色状态.md"}]
        packet["package_sha256"] = _package_sha256(packet)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
            result = verify_context(self.root, packet)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "malformed")

    def test_review_placeholder_state_cannot_replace_missing_card(self):
        (self.root / "设定/角色/林澈.md").unlink()
        for body in ("- 位置：\n- 当前身份：", "<!-- 待填 -->", "## 当前身份\n待填",
                     "- 位置：未知\n- 伤势：待填", "### 周言\n- 位置：北站",
                     "| 字段 | 值 |\n|---|---|\n| 位置 | |"):
            with self.subTest(body=body):
                self.write("追踪/角色状态.md", "# 角色状态\n## 林澈\n" + body)
                result = select_context(self.root, 2)
                self.assertFalse(result["ready"])
                self.assertFalse(result["components"]["character_cards"].get("state_only"))

    def test_review_regular_file_parent_is_not_missing_card(self):
        (self.root / "设定/角色/林澈.md").unlink()
        (self.root / "设定/角色").rmdir()
        self.write("设定/角色", "不是目录")
        result = select_context(self.root, 2)
        self.assertFalse(result["ready"])
        self.assertFalse(result["components"]["character_cards"].get("state_only"))

    def test_review_descriptive_state_subheadings_keep_own_facts(self):
        from context_manager import verify_context
        (self.root / "设定/角色/林澈.md").unlink()
        for heading, fact in (("身体状况", "伤势：右手骨折"), ("当前目标", "目标：取回铜钥匙"),
                              ("短期目标", "目标：赶上末班车")):
            with self.subTest(heading=heading):
                self.write("追踪/角色状态.md", f"## 林澈\n### {heading}\n- {fact}")
                packet = select_context(self.root, 2)
                self.assertTrue(packet["ready"], packet["missing_required"])
                self.assertIn(fact, generate_brief_context(packet))
                self.assertTrue(verify_context(self.root, packet)["ready"])

    def test_review_nested_character_identity_cannot_make_unverifiable_packet(self):
        self.write("大纲/章纲_第002章.md", "人物：nested/新角色\n取回钥匙。")
        self.write("追踪/角色状态.md", "## nested/新角色\n- 位置：北站")
        result = select_context(self.root, 2)
        self.assertFalse(result["ready"])
        self.assertFalse(result["components"]["character_cards"].get("state_only"))

    def test_required_timeline_and_previous_summary_survive_brief_format(self):
        brief = generate_brief_context(select_context(self.root, 2))
        for fact in ("末班车", "藏入衣袋", "右手骨折"):
            self.assertIn(fact, brief)

    def test_required_outline_is_not_truncated_before_character_discovery(self):
        text = "场景说明。" * 260 + "\n人物：林澈\n最后约束：不能开门。"
        self.write("大纲/章纲_第002章.md", text)
        result = select_context(self.root, 2, max_chars=8000)
        self.assertEqual(result["components"]["chapter_brief"]["content"], text)
        self.assertIn("不能开门", generate_brief_context(result))
        self.assertEqual(result["components"]["character_cards"]["count"], 1)

    def test_missing_required_is_blocked_in_json_and_cli(self):
        (self.root / "追踪/时间线.md").unlink()
        result = select_context(self.root, 2)
        self.assertFalse(result.get("ready", True))
        self.assertIn("required_context_missing", json.dumps(result))
        proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "context_manager.py"),
                               "select", str(self.root), "--chapter", "2", "--json"],
                              capture_output=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)["ready"])

    def test_insufficient_budget_blocks_without_truncating_required_state(self):
        result = select_context(self.root, 2, max_chars=20)
        self.assertFalse(result.get("ready", True))
        self.assertIn("required_context_over_budget", json.dumps(result))
        self.assertIn("右手骨折", result["components"]["character_state"]["content"])

    def test_chapter_one_needs_no_previous_chapter(self):
        self.write("大纲/章纲_第001章.md", "人物：林澈\n前往北站。")
        (self.root / "追踪/章节摘要.md").unlink()
        result = select_context(self.root, 1)
        self.assertTrue(result.get("ready"))

    def test_previous_prose_fallback_is_exact_chapter_not_arbitrary_recent(self):
        self.write("追踪/章节摘要.md", "### 第8章 未来\n不应引用。")
        self.write("正文/第001章_北站.md", "林澈右手受伤，把钥匙藏入衣袋。")
        result = select_context(self.root, 2)
        self.assertTrue(result.get("ready"))
        self.assertIn("藏入衣袋", generate_brief_context(result))

    def test_budget_never_drops_required_in_favor_of_optional(self):
        self.write("设定/文风锚.md", "可选样文" * 10000)
        result = select_context(self.root, 2, max_chars=600)
        self.assertTrue(result.get("ready"))
        self.assertLessEqual(result["total_chars"], 600)
        self.assertIn("铜钥匙", generate_brief_context(result))

    def test_optional_truncation_suffix_is_within_its_budget(self):
        for budget in (0, 1, 20, 21, 40):
            with self.subTest(budget=budget):
                self.assertLessEqual(count_chars(truncate_text("可选参考" * 100, budget)), budget)

    def test_full_optional_sources_do_not_overflow_packet_budget(self):
        self.write("设定/角色/林澈.md", "## 身份\n修表师。\n## 可省略履历\n" + "可选人物参考" * 1000)
        for path in ("设定/文风锚.md", "设定/世界观.md"):
            self.write(path, "可选参考" * 1000)
        self.write("大纲/outline_anchors.json", json.dumps({"data": "参考" * 1000}))
        self.write("追踪/章节摘要.md", "### 第1章 北站\n" + "林澈藏入钥匙。" * 30)
        result = select_context(self.root, 2, max_chars=700)
        self.assertTrue(result["ready"])
        self.assertLessEqual(result["total_chars"], 700)

    def test_multi_summary_separators_count_toward_packet_budget(self):
        self.write("大纲/章纲_第012章.md", "人物：林澈\n取回钥匙。")
        self.write("追踪/章节摘要.md", "\n".join(
            "### 第{}章 北站\n林澈等车，钥匙未用。".format(ch) for ch in range(1, 12)))
        self.write("设定/角色/林澈.md", "## 身份\n修表师。\n## 可省略履历\n" + "可选参考" * 1000)
        for path in ("设定/文风锚.md", "设定/世界观.md"):
            self.write(path, "可选参考" * 1000)
        self.write("追踪/节奏配额.md", "第1章" + "参考" * 1000)
        self.write("大纲/outline_anchors.json", json.dumps({"data": "参考" * 1000}, ensure_ascii=False))
        self.write("追踪/entity_index.json", json.dumps({"参考" * 1000: [12]}, ensure_ascii=False))
        result = select_context(self.root, 12, max_chars=500, stage="development")
        self.assertTrue(result["ready"])
        component = result["components"]["recent_summaries"]
        self.assertIn("---", component["content"])
        self.assertEqual(component["chars"], count_chars(component["content"]))
        actual = sum(count_chars(comp.get("content", "")) + sum(
            count_chars(card["content"]) for card in comp.get("characters", []))
            for comp in result["components"].values())
        self.assertEqual(result["total_chars"], actual)
        self.assertLessEqual(actual, 500)

    def test_missing_named_character_state_is_blocked(self):
        self.write("追踪/角色状态.md", "# 角色状态\n## 周言\n- 位置：南门")
        result = select_context(self.root, 2)
        self.assertFalse(result.get("ready", True))
        self.assertIn("林澈", " ".join(result.get("missing_required", [])))

    def test_table_state_and_global_constraints_are_preserved(self):
        self.write("追踪/角色状态.md", "# 角色状态\n全局：停电未恢复。\n"
                   "| 人物 | 位置 | 伤势 |\n| 林澈 | 北站 | 右手骨折 |")
        result = select_context(self.root, 2)
        state = result["components"]["character_state"]["content"]
        self.assertIn("停电未恢复", state)
        self.assertIn("右手骨折", state)

    def test_heading_preamble_is_not_lost_when_selecting_active_characters(self):
        self.write("设定/角色/周言.md", "周言，车站职员。")
        self.write("追踪/角色状态.md", "# 角色状态\n全局：停电未恢复。\n"
                   "## 林澈\n- 位置：北站\n## 周言\n- 位置：南门")
        result = select_context(self.root, 2)
        state = result["components"]["character_state"]["content"]
        self.assertIn("停电未恢复", state)
        self.assertNotIn("南门", state)

    def test_shared_state_sections_survive_character_selection(self):
        self.write("设定/角色/周言.md", "周言，车站职员。")
        self.write("追踪/角色状态.md", "## 林澈\n- 位置：北站\n"
                   "## 当前伤势与物品\n林澈右手骨折；铜钥匙在林澈衣袋。\n"
                   "## 周言\n- 位置：南门")
        result = select_context(self.root, 2)
        self.assertTrue(result["ready"])
        self.assertIn("右手骨折", result["components"]["character_state"]["content"])
        self.assertIn("铜钥匙", generate_brief_context(result))

    def test_relationship_mention_is_not_own_character_state(self):
        self.write("追踪/角色状态.md", "## 周言\n关键关系：林澈的朋友。")
        result = select_context(self.root, 2)
        self.assertFalse(result["ready"])
        self.assertIn("林澈", " ".join(result["missing_required"]))

    def test_higher_heading_ends_inactive_person_section(self):
        self.write("设定/角色/周言.md", "周言，车站职员。")
        self.write("追踪/角色状态.md", "# 角色状态\n## 林澈\n位置：北站\n"
                   "## 周言\n位置：南门\n# 全局状态\n林澈右手骨折；铜钥匙在林澈衣袋。")
        result = select_context(self.root, 2)
        self.assertTrue(result["ready"])
        self.assertIn("右手骨折", result["components"]["character_state"]["content"])
        self.assertIn("铜钥匙", generate_brief_context(result))

    def test_empty_own_heading_cannot_borrow_other_character_state(self):
        self.write("追踪/角色状态.md", "## 林澈\n\n## 周言\n- 位置：南门")
        self.assertFalse(select_context(self.root, 2)["ready"])

    def test_character_identity_must_not_match_name_prefix(self):
        self.write("追踪/角色状态.md", "## 林澈明\n- 位置：南门")
        self.assertFalse(select_context(self.root, 2)["ready"])

    def test_explicit_flat_character_state_is_supported(self):
        self.write("追踪/角色状态.md", "# 角色状态\n林澈：北站，右手骨折，铜钥匙在衣袋。")
        self.assertTrue(select_context(self.root, 2)["ready"])

    def test_summary_with_colon_in_chapter_heading_is_supported(self):
        self.write("追踪/章节摘要.md", "### 第1章：北站\n钥匙藏入衣袋。")
        self.assertTrue(select_context(self.root, 2).get("ready"))

    def test_empty_previous_summary_heading_is_not_reliable_context(self):
        self.write("追踪/章节摘要.md", "### 第1章 北站\n")
        self.assertFalse(select_context(self.root, 2).get("ready", True))

    def test_formal_empty_previous_summary_fields_are_not_reliable_context(self):
        fields = ("发生了什么", "状态变化", "伏笔进出", "新登场", "关键实体", "承上", "启下")
        self.write("追踪/章节摘要.md", "### 第1章 北站\n" + "\n".join(
            f"- {field}：" for field in fields))
        result = select_context(self.root, 2)
        self.assertFalse(result.get("ready", True))
        self.assertIn("上一章正文或可靠摘要", " ".join(result["missing_required"]))

    def test_pending_transaction_blocks_canonical_context_read(self):
        from chapter_transaction import prepare
        self.write("追踪/节奏配额.md", "# 节奏配额\n")
        prepare(self.root, 2)
        result = select_context(self.root, 2)
        self.assertFalse(result["ready"])
        self.assertIn("transaction_incomplete", result["errors"])

    def test_context_holds_transaction_lock_for_entire_canonical_read(self):
        import context_manager
        import chapter_transaction
        original = context_manager._required_context

        def checked_required(*args, **kwargs):
            with self.assertRaises(chapter_transaction.TransactionError):
                with chapter_transaction.transaction_lock(self.root):
                    pass
            return original(*args, **kwargs)

        with patch.object(context_manager, "_required_context", side_effect=checked_required):
            self.assertTrue(select_context(self.root, 2)["ready"])

    def test_entity_context_queries_brief_entities_in_historical_chapters(self):
        self.write("追踪/entity_index.json", json.dumps(
            {"铜钥匙": [1], "无关玉佩": [1], "未来物件": [3]}, ensure_ascii=False))
        result = select_context(self.root, 2, max_chars=12000)
        entity_context = result["components"]["entity_context"]["content"]
        self.assertIn("铜钥匙", entity_context)
        self.assertIn("1", entity_context)
        self.assertNotIn("无关玉佩", entity_context)
        self.assertNotIn("未来物件", entity_context)

    def test_ready_brief_respects_real_serialized_budget(self):
        result = select_context(self.root, 2, max_chars=1000)
        brief_chars = count_chars(generate_brief_context(result))
        if result["ready"]:
            self.assertLessEqual(brief_chars, 1000)
        else:
            self.assertIn("required_context_over_budget", result["errors"])

    def test_resolved_foreshadows_do_not_exhaust_required_budget(self):
        resolved = "\n".join(
            f"| F1-{i:03d} | 已结束旧秘密{i} | 第{i}章 | 第{i + 1}章 | 完成 |" for i in range(1, 180))
        self.write("追踪/伏笔台账.md", "# 伏笔台账\n## ✅ 已回收\n" + resolved
                   + "\n## 🟡 活跃\n| F9-01 | 铜钥匙不能开门 | 第1章 | 第9章 | 待回收 |")
        result = select_context(self.root, 2, max_chars=2000)
        self.assertTrue(result["ready"], result["errors"])
        content = result["components"]["foreshadowing"]["content"]
        self.assertIn("F9-01", content)
        self.assertNotIn("F1-179", content)

    def test_historical_timeline_rows_do_not_exhaust_required_budget(self):
        history = "\n".join(
            f"| 第{i}章 | 第{i}天 | 已结束事件{i} | 完成 |" for i in range(1, 180))
        self.write("追踪/时间线.md", "# 时间线\n## 历史记录\n" + history
                   + "\n## 当前时间锚点\n- 第2章：第二天上午，末班车还有两小时。")
        result = select_context(self.root, 2, max_chars=2000)
        self.assertTrue(result["ready"], result["errors"])
        content = result["components"]["timeline"]["content"]
        self.assertIn("第二天上午", content)
        self.assertNotIn("已结束事件179", content)

    def test_timeline_without_top_level_title_still_drops_history(self):
        self.write("追踪/时间线.md", "## 历史记录\n已结束旧事。\n"
                   "## 当前时间锚点\n第二天上午，末班车还有两小时。")
        content = select_context(self.root, 2)["components"]["timeline"]["content"]
        self.assertIn("第二天上午", content)
        self.assertNotIn("已结束旧事", content)

    def test_mcp_context_argument_adapter_runs_real_cli(self):
        # Compile the pure argument adapter without optional MCP/pydantic imports.
        source = (SCRIPT_DIR.parent / "mcp_server/server.py").read_text(encoding="utf-8")
        nodes = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_context_manager_args"]
        self.assertEqual(len(nodes), 1, "MCP context tool needs a tested CLI adapter")
        namespace = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "server.py", "exec"), namespace)
        for action in ("select", "compact"):
            params = SimpleNamespace(action=action, chapter=2, book_dir=str(self.root))
            args = namespace["_context_manager_args"](params)
            proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "context_manager.py"), *args],
                                  capture_output=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("藏入衣袋", proc.stdout)

    def test_flow_preserves_complete_selected_context(self):
        self.write("大纲/章纲_第002章.md", "场景说明。" * 260 + "\n人物：林澈\n最后约束：不能开门。")
        for mode in ([], ["--json"]):
            proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "novel_flow.py"),
                                   "prepare", str(self.root), "--chapter", "2", *mode],
                                  capture_output=True, encoding="utf-8")
            self.assertIn("不能开门", proc.stdout)
            self.assertIn("右手骨折", proc.stdout)

    def test_flow_missing_context_produces_failing_exit(self):
        (self.root / "追踪/时间线.md").unlink()
        proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "novel_flow.py"),
                               "prepare", str(self.root), "--chapter", "2", "--json"],
                              capture_output=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)["all_ready"])

    def test_explicit_cast_not_hidden_by_one_registered_character(self):
        self.write("大纲/章纲_第002章.md", "出场人物：林澈、周言\n一起取钥匙。")
        result = select_context(self.root, 2)
        self.assertFalse(result.get("ready", True))
        self.assertIn("周言", " ".join(result.get("missing_required", [])))

    def test_standard_outline_template_checks_secondary_cast(self):
        outline = (SCRIPT_DIR.parent / "assets/templates/outline-chapter.md").read_text(encoding="utf-8")
        outline = outline.replace("- 主要：", "- 主要：林澈").replace("- 次要：", "- 次要：周言")
        self.write("大纲/章纲_第002章.md", outline)
        result = select_context(self.root, 2)
        self.assertFalse(result["ready"])
        self.assertIn("周言", " ".join(result["missing_required"]))

    def test_cast_section_stops_at_following_heading(self):
        self.write("大纲/章纲_第002章.md", "## 出场人物\n- 主要：林澈\n- 次要：无\n"
                   "## 核心事件\n- 主要：取钥匙\n- 次要：等车")
        self.assertTrue(select_context(self.root, 2)["ready"])

    def test_all_registered_characters_are_checked_not_only_first_five(self):
        names = ["人物" + str(i) for i in range(7)]
        for name in names:
            self.write("设定/角色/" + name + ".md", name + "，职员。")
        self.write("大纲/章纲_第002章.md", "出场人物：" + "、".join(names))
        self.write("追踪/角色状态.md", "\n".join("## " + name + "\n- 位置：北站" for name in names[:6]))
        self.assertIn(names[6], " ".join(select_context(self.root, 2).get("missing_required", [])))


class TestR4ContextProvenance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r4-context-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        files = {
            "大纲/章纲_第002章.md": "# 第二章\n出场人物：林澄\n目标：取回自己的钥匙，不替别人作承诺。",
            "追踪/角色状态.md": "## 林澄\n当前地点：门外。已知：钥匙在屋内。",
            "追踪/章节摘要.md": "### 第1章\n林澄把钥匙留在屋内。",
            "追踪/伏笔台账.md": "无未结伏笔。",
            "追踪/时间线.md": "第1章：清晨；第2章：同日午后。",
            "设定/角色/林澄.md": "# 林澄\n## 动机与目标\n只负责自己的承诺。",
        }
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def verify(self, packet):
        import context_manager
        self.assertTrue(hasattr(context_manager, "verify_context"), "context verification is not implemented")
        return context_manager.verify_context(self.root, packet)

    def test_late_voice_and_knowledge_are_not_silently_lost(self):
        path = self.root / "设定/角色/林澄.md"
        path.write_text("# 林澄\n## 履历\n" + "无关履历。\n" * 40
                        + "## 口癖与声线\n只在谈价时使用敬语。\n"
                        + "## 知识边界\n尚不知钥匙已被转交。", encoding="utf-8")
        packet = select_context(self.root, 2, max_chars=12000)
        text = generate_brief_context(packet)
        self.assertIn("只在谈价时使用敬语", text)
        self.assertIn("尚不知钥匙已被转交", text)

    def test_unknown_card_format_keeps_tail_constraint(self):
        path = self.root / "设定/角色/林澄.md"
        path.write_text("林澄的档案\n" + "背景。\n" * 40 + "绝不替他人签字。", encoding="utf-8")
        self.assertIn("绝不替他人签字", generate_brief_context(select_context(self.root, 2, max_chars=12000)))

    def test_critical_card_content_counts_toward_required_budget(self):
        (self.root / "设定/角色/林澄.md").write_text("## 底线与恐惧\n" + "不能签字。" * 250, encoding="utf-8")
        packet = select_context(self.root, 2, max_chars=500)
        self.assertFalse(packet["ready"])
        self.assertIn("required_context_over_budget", packet["errors"])
        self.assertIn("不能签字。" * 250, generate_brief_context(packet))

    def test_unchanged_packet_is_fresh(self):
        packet = select_context(self.root, 2, max_chars=12000)
        result = self.verify(packet)
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "fresh")

    def test_changed_source_with_same_mtime_is_stale(self):
        packet = select_context(self.root, 2, max_chars=12000)
        path = self.root / "追踪/角色状态.md"
        stamp = path.stat()
        path.write_text("## 林澄\n当前地点：屋内。", encoding="utf-8")
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        result = self.verify(packet)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "stale")
        self.assertIn("追踪/角色状态.md", result["changed"])

    def test_deleted_source_is_missing(self):
        packet = select_context(self.root, 2, max_chars=12000)
        (self.root / "追踪/时间线.md").unlink()
        result = self.verify(packet)
        self.assertFalse(result["ready"])
        self.assertIn("追踪/时间线.md", result["missing"])

    def test_legacy_packet_has_no_fabricated_freshness(self):
        result = self.verify({"components": {}, "ready": True, "target_chapter": 2})
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unverified")

    def test_packet_content_edit_is_detected(self):
        packet = select_context(self.root, 2, max_chars=12000)
        packet["components"]["character_state"]["content"] = "林澄知道一切。"
        self.assertFalse(self.verify(packet)["ready"])

    def test_unrelated_file_change_does_not_invalidate_packet(self):
        packet = select_context(self.root, 2, max_chars=12000)
        (self.root / "无关笔记.txt").write_text("与本次无关", encoding="utf-8")
        self.assertTrue(self.verify(packet)["ready"])

    def test_verify_cli_reports_json_and_nonzero_for_stale(self):
        packet = select_context(self.root, 2, max_chars=12000)
        output = self.root / "packet.json"
        output.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, "-X", "utf8", str(SCRIPT_DIR / "context_manager.py"),
                   "verify", str(self.root), "--context", str(output)]
        result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ready"])
        (self.root / "追踪/时间线.md").unlink()
        stale = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(stale.returncode, 1)
        self.assertFalse(json.loads(stale.stdout)["ready"])

    def test_unknown_long_card_is_required_and_blocks(self):
        text = "林澄的档案\n" + "背景。\n" * 250 + "绝不替人签字。"
        (self.root / "设定/角色/林澄.md").write_text(text, encoding="utf-8")
        packet = select_context(self.root, 2, max_chars=500)
        self.assertFalse(packet["ready"])
        self.assertIn(text, generate_brief_context(packet))

    def test_semantic_selection_reports_source_lines_and_omissions(self):
        text = ("# 林澄\n## 身份\n修表师。\n## 可省略履历\n" + "闲话。\n" * 400
                + "## 口癖与声线\n只在谈价时使用敬语。\n## 知识边界\n不知道钥匙已转交。")
        (self.root / "设定/角色/林澄.md").write_text(text, encoding="utf-8")
        packet = select_context(self.root, 2, max_chars=500)
        self.assertTrue(packet["ready"])
        card = packet["components"]["character_cards"]["characters"][0]
        self.assertEqual(card["source"], "设定/角色/林澄.md")
        self.assertTrue(card["source_spans"])
        self.assertTrue(card["omitted_sections"])
        self.assertIn("只在谈价时使用敬语。", card["content"])
        self.assertNotIn("闲话。", card["content"])
        self.assertIn("省略", generate_brief_context(packet))

    def test_table_fields_and_nested_heading_are_kept_whole(self):
        text = ("# 林澄\n## 身份\n修表师。\n## 可省略履历\n### 早年\n"
                "| 字段 | 内容 |\n| --- | --- |\n| 底线 | 绝不替他人签字。 |\n"
                "| 知识边界 | 尚不知钥匙已转交。 |\n| 声线 | 不用敬语。 |")
        (self.root / "设定/角色/林澄.md").write_text(text, encoding="utf-8")
        packet = select_context(self.root, 2)
        card = packet["components"]["character_cards"]["characters"][0]
        self.assertIn("| 字段 | 内容 |", card["content"])
        self.assertIn("| --- | --- |", card["content"])
        self.assertIn("### 早年", card["content"])
        self.assertIn("| 声线 | 不用敬语。 |", card["content"])
        self.assertTrue(packet["components"]["character_cards"].get("required"))

    def test_unmentioned_large_card_is_not_read_or_budgeted(self):
        path = self.root / "设定/角色/周言.md"
        path.write_text("未知格式背景" * 5000, encoding="utf-8")
        packet = select_context(self.root, 2, max_chars=500)
        self.assertTrue(packet["ready"])
        self.assertNotIn("设定/角色/周言.md", [s["path"] for s in packet["source_manifest"]])
        path.write_text("完全不同", encoding="utf-8")
        self.assertTrue(self.verify(packet)["ready"])

    def test_selected_optional_source_change_and_deletion_are_stale(self):
        path = self.root / "设定/世界观.md"
        path.write_text("北站一年只有一个夏天。", encoding="utf-8")
        packet = select_context(self.root, 2)
        source = next(s for s in packet["source_manifest"] if s["path"] == "设定/世界观.md")
        self.assertFalse(source["required"])
        path.write_text("北站没有夏天。", encoding="utf-8")
        self.assertIn("设定/世界观.md", self.verify(packet)["changed"])
        path.unlink()
        self.assertIn("设定/世界观.md", self.verify(packet)["missing"])

    def test_missing_optional_sources_are_visible_not_claimed_verified(self):
        packet = select_context(self.root, 2)
        self.assertTrue(packet["ready"])
        self.assertNotIn("设定/世界观.md", [s["path"] for s in packet["source_manifest"]])
        omitted = {s["path"]: s["reason"] for s in packet["omitted_sources"]}
        self.assertEqual(omitted["设定/世界观.md"], "missing")
        self.assertEqual(omitted["设定/文风锚.md"], "missing")

    def test_snapshot_fingerprint_matches_bytes_used_before_source_changes(self):
        path = self.root / "追踪/角色状态.md"
        original_bytes = path.read_bytes()
        original_read = Path.read_bytes
        reads = []

        def change_after_read(candidate):
            data = original_read(candidate)
            if candidate == path:
                reads.append(candidate)
                path.write_text("## 林澄\n当前地点：屋内。", encoding="utf-8")
            return data

        # The boundary mutation simulates a concurrent writer; the content,
        # returned fingerprint and subsequent verify still exercise real files.
        with patch.object(Path, "read_bytes", change_after_read):
            packet = select_context(self.root, 2)
        source = next(s for s in packet["source_manifest"] if s["path"] == "追踪/角色状态.md")
        self.assertEqual(source["sha256"], hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(source["bytes"], len(original_bytes))
        self.assertTrue(source["required"])
        self.assertIn("门外", packet["components"]["character_state"]["content"])
        self.assertEqual(len(reads), 1)
        self.assertEqual(self.verify(packet)["status"], "stale")

    def test_missing_manifest_or_digest_does_not_claim_fresh(self):
        for key in ("source_manifest", "package_sha256"):
            packet = select_context(self.root, 2)
            packet.pop(key, None)
            result = self.verify(packet)
            self.assertFalse(result["ready"])
            self.assertEqual(result["status"], "unverified")

    def test_empty_or_malformed_manifest_is_rejected(self):
        for manifest in ([], {}, [None], [{"path": "追踪/时间线.md"}]):
            packet = select_context(self.root, 2)
            packet["source_manifest"] = manifest
            self.resign(packet)
            result = self.verify(packet)
            self.assertFalse(result["ready"])
            self.assertEqual(result["status"], "malformed")

    @staticmethod
    def resign(packet):
        packet.pop("package_sha256", None)
        packet["package_sha256"] = hashlib.sha256(json.dumps(
            packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest()

    def test_unsafe_manifest_paths_are_rejected_without_reading(self):
        paths = ("../outside.md", "/outside.md", "C:/outside.md", "C:outside.md",
                 "设定/../outside.md", "..\\outside.md", "追踪/时间线.md:stream",
                 "NUL", "追踪/COM1.md", "追踪/alias. ")
        for unsafe in paths:
            with self.subTest(path=unsafe):
                packet = select_context(self.root, 2)
                packet["source_manifest"][0]["path"] = unsafe
                self.resign(packet)
                with patch.object(Path, "read_bytes", side_effect=AssertionError("must reject before reading")):
                    result = self.verify(packet)
                self.assertEqual(result["status"], "malformed")
                self.assertFalse(result["ready"])

    def test_symbolic_source_is_not_followed(self):
        external = self.root.parent / (self.root.name + "-outside.md")
        external.write_text("外部秘密", encoding="utf-8")
        self.addCleanup(external.unlink)
        source = self.root / "追踪/时间线.md"
        packet = select_context(self.root, 2)
        source.unlink()
        try:
            source.symlink_to(external)
        except OSError as exc:
            self.skipTest("symbolic links unavailable: " + str(exc))
        self.addCleanup(source.unlink)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must reject before reading")):
            result = self.verify(packet)
        self.assertEqual(result["status"], "malformed")
        selected = select_context(self.root, 2)
        self.assertFalse(selected["ready"])
        self.assertNotIn("外部秘密", generate_brief_context(selected))

    def test_fresh_sources_cannot_override_original_not_ready(self):
        packet = select_context(self.root, 2, max_chars=20)
        result = self.verify(packet)
        self.assertFalse(result["ready"])
        self.assertIn("required_context_over_budget", result["errors"])

    def test_package_strings_are_data_not_commands(self):
        marker = self.root / "executed.txt"
        packet = select_context(self.root, 2)
        packet["instruction"] = "__import__('pathlib').Path({!r}).write_text('bad')".format(str(marker))
        self.resign(packet)
        self.assertTrue(self.verify(packet)["ready"])
        self.assertFalse(marker.exists())

    def test_verify_cli_malformed_json_and_missing_argument(self):
        output = self.root / "packet.json"
        output.write_text("{broken", encoding="utf-8")
        command = [sys.executable, "-X", "utf8", str(SCRIPT_DIR / "context_manager.py"),
                   "verify", str(self.root)]
        malformed = subprocess.run(command + ["--context", str(output)], capture_output=True,
                                   encoding="utf-8", timeout=30)
        self.assertEqual(malformed.returncode, 1)
        self.assertEqual(json.loads(malformed.stdout)["status"], "malformed")
        missing = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(missing.returncode, 2)

    def test_selection_and_verification_emit_no_runtime_warnings(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            packet = select_context(self.root, 2)
            self.assertTrue(self.verify(packet)["ready"])

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_junction_source_directory_is_rejected_before_reading(self):
        import _winapi
        with tempfile.TemporaryDirectory(prefix="r4-outside-") as external:
            (Path(external) / "秘密.md").write_text("外部秘密", encoding="utf-8")
            link = self.root / "外部链接"
            _winapi.CreateJunction(external, str(link))
            try:
                packet = select_context(self.root, 2)
                packet["source_manifest"][0]["path"] = "外部链接/秘密.md"
                self.resign(packet)
                with patch.object(Path, "read_bytes", side_effect=AssertionError("must reject before reading")):
                    result = self.verify(packet)
                self.assertEqual(result["status"], "malformed")
                self.assertFalse(result["ready"])
            finally:
                link.rmdir()

    def test_shared_summary_source_is_read_once_and_required(self):
        original_read = Path.read_bytes
        summary_path = self.root / "追踪/章节摘要.md"
        reads = []

        def counted_read(path):
            if path == summary_path:
                reads.append(path)
            return original_read(path)

        with patch.object(Path, "read_bytes", counted_read):
            packet = select_context(self.root, 2)
        self.assertEqual(len(reads), 1)
        source = next(s for s in packet["source_manifest"] if s["path"] == "追踪/章节摘要.md")
        self.assertTrue(source["required"])
        self.assertEqual(source["sha256"], hashlib.sha256(summary_path.read_bytes()).hexdigest())

    def test_readers_are_isolated_between_books_and_calls(self):
        with tempfile.TemporaryDirectory(prefix="r4-second-") as temporary:
            other = Path(temporary)
            for path in self.root.rglob("*.md"):
                target = other / path.relative_to(self.root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
            (other / "追踪/角色状态.md").write_text("## 林澄\n当前地点：楼上。", encoding="utf-8")
            roots = [self.root, other] * 4
            with ThreadPoolExecutor(max_workers=4) as executor:
                packets = list(executor.map(lambda root: select_context(root, 2), roots))
            for root, packet in zip(roots, packets):
                expected = "门外" if root == self.root else "楼上"
                self.assertIn(expected, packet["components"]["character_state"]["content"])
            (self.root / "追踪/角色状态.md").write_text("## 林澄\n当前地点：远处。", encoding="utf-8")
            self.assertIn("远处", select_context(self.root, 2)["components"]["character_state"]["content"])

    def test_verifier_uses_caller_root_not_packet_directory(self):
        packet = select_context(self.root, 2)
        packet["book_dir"] = str(self.root.parent / "outside")
        self.resign(packet)
        self.assertTrue(self.verify(packet)["ready"])

    def test_duplicate_manifest_source_is_malformed(self):
        packet = select_context(self.root, 2)
        packet["source_manifest"].append(dict(packet["source_manifest"][0]))
        self.resign(packet)
        self.assertEqual(self.verify(packet)["status"], "malformed")

    def test_verify_cli_legacy_and_original_not_ready_exit_one(self):
        output = self.root / "packet.json"
        command = [sys.executable, "-X", "utf8", str(SCRIPT_DIR / "context_manager.py"),
                   "verify", str(self.root), "--context", str(output)]
        for packet, status in (({"components": {}, "ready": True}, "unverified"),
                               (select_context(self.root, 2, max_chars=20), "fresh")):
            output.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], status)
            self.assertFalse(json.loads(result.stdout)["ready"])


class TestCompressSummaries(unittest.TestCase):
    """测试摘要压缩。"""

    def test_single_chapter_not_compressed(self):
        """单章不压缩，直接拼接。"""
        chapters = [
            {"chapter": 1, "char_count": 10, "raw": "第一章内容。"},
        ]
        result = compress_summaries(chapters, 1, 1)
        self.assertIn("1-1章", result)

    def test_multiple_chapters_compressed(self):
        """多章压缩为回顾段。"""
        chapters = [
            {"chapter": 1, "char_count": 20, "raw": "张三出场，发现秘密。\n一句话摘要:张三发现秘密"},
            {"chapter": 2, "char_count": 20, "raw": "李四加入，冲突升级。\n一句话摘要:李四加入"},
            {"chapter": 3, "char_count": 20, "raw": "真相大白，战斗开始。\n一句话摘要:真相大白"},
        ]
        result = compress_summaries(chapters, 1, 3)
        self.assertIn("1-3章", result)

    def test_empty_chapters(self):
        """空章节列表返回提示。"""
        result = compress_summaries([], 1, 5)
        self.assertIn("无摘要数据", result)

    def test_published_fields_survive_structured_volume_compression(self):
        chapters = [{
            "chapter": 1,
            "char_count": 500,
            "raw": (
                "### 第1章：月门\n"
                "- 发生了什么：林澈穿过废站并发现宗主伪造命令。\n"
                "- 状态变化：林澈右手伤势加重。\n"
                "- 伏笔进出：埋入 F1-99，月纹钥匙只能在子时使用。\n"
                "- 新登场：守门人。\n"
                "- 关键实体：月纹钥匙、废站。\n"
                "- 承上：继续追查假命令。\n"
                "- 启下：子时返回月门。"
            ),
        }]
        result = compress_summaries(chapters, 1, 1)
        for fact in ("宗主伪造命令", "右手伤势加重", "F1-99", "月纹钥匙", "子时"):
            self.assertIn(fact, result)
        self.assertIn("- 来源章节：1-1", result)

    def test_each_legacy_chapter_contributes_a_fallback_event(self):
        chapters = [
            {"chapter": 1, "char_count": 20, "raw": "### 第1章\n林澈把钥匙藏进衣袋。"},
            {"chapter": 2, "char_count": 20, "raw": "### 第2章\n唐序关闭北站闸门。"},
        ]
        result = compress_summaries(chapters, 1, 2)
        self.assertIn("钥匙藏进衣袋", result)
        self.assertIn("关闭北站闸门", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
