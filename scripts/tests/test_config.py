#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_config.py — 测试 config.py 环境变量覆盖与动态上下文阶段。

运行方式：
    python scripts/tests/test_config.py
"""

import os
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import config


class TestEnvOverride(unittest.TestCase):
    """环境变量覆盖功能测试。"""

    def test_env_int_reads_valid_value(self):
        """LNS_ 前缀环境变量可覆盖整数值。"""
        old = os.environ.get("LNS_TEST_INT")
        os.environ["LNS_TEST_INT"] = "42"
        try:
            val = config._env_int("TEST_INT", 0)
            self.assertEqual(val, 42)
        finally:
            if old is None:
                os.environ.pop("LNS_TEST_INT", None)
            else:
                os.environ["LNS_TEST_INT"] = old

    def test_env_int_returns_default_when_missing(self):
        """环境变量不存在时返回默认值。"""
        key = "LNS_DEFINITELY_NOT_SET_12345"
        if key in os.environ:
            del os.environ[key]
        val = config._env_int("DEFINITELY_NOT_SET_12345", 99)
        self.assertEqual(val, 99)

    def test_env_int_returns_default_on_invalid(self):
        """环境变量值非整数时返回默认值。"""
        old = os.environ.get("LNS_TEST_BAD")
        os.environ["LNS_TEST_BAD"] = "not_a_number"
        try:
            val = config._env_int("TEST_BAD", 7)
            self.assertEqual(val, 7)
        finally:
            if old is None:
                os.environ.pop("LNS_TEST_BAD", None)
            else:
                os.environ["LNS_TEST_BAD"] = old

    def test_env_float_reads_valid_value(self):
        """LNS_ 前缀环境变量可覆盖浮点值。"""
        old = os.environ.get("LNS_TEST_FLOAT")
        os.environ["LNS_TEST_FLOAT"] = "3.14"
        try:
            val = config._env_float("TEST_FLOAT", 0.0)
            self.assertAlmostEqual(val, 3.14)
        finally:
            if old is None:
                os.environ.pop("LNS_TEST_FLOAT", None)
            else:
                os.environ["LNS_TEST_FLOAT"] = old


class TestContextStages(unittest.TestCase):
    """动态上下文阶段配置测试。"""

    def test_context_stages_has_four_phases(self):
        """CONTEXT_STAGES 包含四个阶段。"""
        expected = {"opening", "development", "deepwater", "finale"}
        self.assertEqual(set(config.CONTEXT_STAGES.keys()), expected)

    def test_each_stage_has_range_and_ratios(self):
        """每个阶段都有 range 和 ratios 键。"""
        for name, stage in config.CONTEXT_STAGES.items():
            self.assertIn("range", stage, f"{name} 缺少 range")
            self.assertIn("ratios", stage, f"{name} 缺少 ratios")
            self.assertIsInstance(stage["range"], tuple)
            self.assertIsInstance(stage["ratios"], dict)

    def test_stage_ranges_are_continuous(self):
        """阶段范围连续不重叠，覆盖 0.0-1.0。"""
        stages = [
            config.CONTEXT_STAGES["opening"]["range"],
            config.CONTEXT_STAGES["development"]["range"],
            config.CONTEXT_STAGES["deepwater"]["range"],
            config.CONTEXT_STAGES["finale"]["range"],
        ]
        # 检查起点
        self.assertEqual(stages[0][0], 0.0)
        # 检查连续
        for i in range(len(stages) - 1):
            self.assertEqual(stages[i][1], stages[i + 1][0])
        # 检查终点
        self.assertEqual(stages[-1][1], 1.0)

    def test_ratios_sum_to_one(self):
        """每个阶段的预算比例之和应约为 1.0。"""
        for name, stage in config.CONTEXT_STAGES.items():
            total = sum(stage["ratios"].values())
            self.assertAlmostEqual(
                total, 1.0, places=2,
                msg=f"{name} 的比例之和为 {total}，不等于 1.0"
            )

    def test_finale_has_milestone(self):
        """收束阶段独有 milestone 组件。"""
        finale_ratios = config.CONTEXT_STAGES["finale"]["ratios"]
        self.assertIn("milestone", finale_ratios)
        self.assertGreater(finale_ratios["milestone"], 0)


class TestConfigConstants(unittest.TestCase):
    """配置常量基本检查。"""

    def test_skill_version_is_string(self):
        """版本号应为字符串。"""
        self.assertIsInstance(config.SKILL_VERSION, str)
        self.assertTrue(config.SKILL_VERSION)

    def test_book_dirs_has_required_keys(self):
        """书籍目录结构包含必要键。"""
        required = {"outline", "setting", "manuscript", "tracking"}
        self.assertTrue(required.issubset(config.BOOK_DIRS.keys()))

    def test_tracking_files_has_required_keys(self):
        """追踪文件配置包含必要键。"""
        required = {"chapter_summary", "character_state", "foreshadow", "entity_index"}
        self.assertTrue(required.issubset(config.TRACKING_FILES.keys()))

    def test_rag_keywords_is_list(self):
        """RAG 轻场景关键词应为列表。"""
        self.assertIsInstance(config.RAG_LIGHT_SCENE_KEYWORDS, list)
        self.assertTrue(len(config.RAG_LIGHT_SCENE_KEYWORDS) > 0)

    def test_graph_node_types_is_list(self):
        """图谱节点类型应为列表。"""
        self.assertIsInstance(config.GRAPH_NODE_TYPES, list)
        self.assertTrue(len(config.GRAPH_NODE_TYPES) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
