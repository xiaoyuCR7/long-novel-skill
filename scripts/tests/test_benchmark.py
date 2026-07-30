#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_benchmark.py — 测试 benchmark.py 质量基线评测。

运行方式：
    python scripts/tests/test_benchmark.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from benchmark import (
    evaluate_chapter,
    evaluate_book,
    save_baseline,
    load_baseline,
    compare_baseline,
    trend_analysis,
    _find_chapter_files,
    _cjk_chars,
    baseline_path,
)


class TestCJKChars(unittest.TestCase):
    """CJK 字符统计。"""

    def test_pure_chinese(self):
        self.assertEqual(_cjk_chars("你好世界"), 4)

    def test_mixed(self):
        self.assertEqual(_cjk_chars("Hello 世界 123"), 2)

    def test_empty(self):
        self.assertEqual(_cjk_chars(""), 0)


class TestFindChapterFiles(unittest.TestCase):
    """章节文件查找。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_and_sort(self):
        """按章号排序。"""
        (self.root / "正文" / "第003章.md").write_text("c")
        (self.root / "正文" / "第001章.md").write_text("a")
        chapters = _find_chapter_files(self.root)
        nums = [c[0] for c in chapters]
        self.assertEqual(nums, [1, 3])

    def test_no_manuscript_dir(self):
        """无正文目录返回空。"""
        empty_root = Path(self.tmp.name) / "empty"
        chapters = _find_chapter_files(empty_root)
        self.assertEqual(chapters, [])


class TestEvaluateChapter(unittest.TestCase):
    """单章评测。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chapter = Path(self.tmp.name) / "第001章.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_evaluate_normal_chapter(self):
        """正常章节返回完整评分。"""
        text = (
            "他推开门，看见阳光洒进房间。\n\n"
            "「今天天气真好。」他说。\n\n"
            "他走到窗前，深吸一口气。"
        )
        self.chapter.write_text(text, encoding="utf-8")
        score = evaluate_chapter(self.chapter)
        self.assertNotIn("error", score)
        self.assertIn("ai_score", score)
        self.assertIn("avg_sent_len", score)
        self.assertIn("dialogue_ratio", score)
        self.assertIn("rhythm_balance", score)
        self.assertIn("gate_pass_rate", score)
        # 范围检查
        self.assertGreaterEqual(score["ai_score"], 0.0)
        self.assertLessEqual(score["ai_score"], 100.0)
        self.assertGreaterEqual(score["gate_pass_rate"], 0.0)
        self.assertLessEqual(score["gate_pass_rate"], 1.0)

    def test_evaluate_empty_file(self):
        """空文件返回错误。"""
        self.chapter.write_text("", encoding="utf-8")
        score = evaluate_chapter(self.chapter)
        self.assertIn("error", score)

    def test_dialogue_ratio_calculation(self):
        """对话占比正确计算。"""
        text = "「这句话是对话。」他说。" * 10 + "叙述内容。" * 5
        self.chapter.write_text(text, encoding="utf-8")
        score = evaluate_chapter(self.chapter)
        self.assertGreater(score["dialogue_ratio"], 0)


class TestEvaluateBook(unittest.TestCase):
    """全书评测。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_chapters_error(self):
        """无正文时返回错误。"""
        result = evaluate_book(self.root)
        self.assertIn("error", result)

    def test_evaluate_multiple_chapters(self):
        """多章评测返回汇总。"""
        for i in range(1, 4):
            (self.root / "正文" / f"第{i:03d}章.md").write_text(
                f"第{i}章内容。他走了出去。" * 50,
                encoding="utf-8"
            )
        result = evaluate_book(self.root)
        self.assertNotIn("error", result)
        self.assertEqual(result["total_chapters"], 3)
        self.assertIn("summary", result)
        # 检查汇总统计存在
        self.assertIn("avg_ai_score", result["summary"])


class TestBaselineManagement(unittest.TestCase):
    """基线管理。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)
        (self.root / "追踪").mkdir(parents=True)
        for i in range(1, 4):
            (self.root / "正文" / f"第{i:03d}章.md").write_text(
                "内容。他走了出去。" * 100,
                encoding="utf-8"
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_baseline_creates_file(self):
        """保存基线应创建文件。"""
        result = save_baseline(self.root)
        self.assertNotIn("error", result)
        self.assertTrue(baseline_path(self.root).exists())

    def test_load_existing_baseline(self):
        """加载已存基线应成功。"""
        save_baseline(self.root)
        baseline = load_baseline(self.root)
        self.assertIsNotNone(baseline)
        self.assertIn("version", baseline)

    def test_load_missing_baseline(self):
        """无基线时返回 None。"""
        baseline = load_baseline(self.root)
        self.assertIsNone(baseline)

    def test_compare_baseline_detects_changes(self):
        """对比应检测到变化。"""
        save_baseline(self.root)
        # 修改内容
        (self.root / "正文" / "第001章.md").write_text(
            "仿佛他似乎不禁笑了。" * 50,
            encoding="utf-8"
        )
        result = compare_baseline(self.root)
        self.assertNotIn("error", result)
        self.assertIn("comparison", result)


class TestTrendAnalysis(unittest.TestCase):
    """趋势分析。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)
        for i in range(1, 6):
            (self.root / "正文" / f"第{i:03d}章.md").write_text(
                f"第{i}章内容。他走了出去。" * 100,
                encoding="utf-8"
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_trend_with_enough_chapters(self):
        """足够章节时返回趋势。"""
        result = trend_analysis(self.root, last_n=3)
        self.assertNotIn("error", result)
        self.assertIn("trend", result)

    def test_trend_not_enough_chapters(self):
        """章节不足时返回错误。"""
        result = trend_analysis(self.root, last_n=10)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
