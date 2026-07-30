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


if __name__ == "__main__":
    unittest.main(verbosity=2)
