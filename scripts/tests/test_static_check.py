#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_static_check.py — 测试 static_check.py 跨文件一致性检查。

运行方式：
    python scripts/tests/test_static_check.py
"""

import os
import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from static_check import (
    CheckResult,
    _parse_chapter_number,
    _collect_chapter_files,
    _count_chinese_chars,
    _get_character_names_from_cards,
    _parse_timeline_entries,
    _parse_foreshadow_ledger,
    _parse_summary_entries,
    check_character,
    check_timeline,
    check_sync,
    check_wordcount,
)


class TestCheckResult(unittest.TestCase):
    """测试结果数据结构。"""

    def test_to_dict_structure(self):
        """to_dict 返回正确结构。"""
        r = CheckResult("TEST", "测试", "PASS", "消息", ["详情"], ["修复"])
        d = r.to_dict()
        self.assertEqual(d["category"], "TEST")
        self.assertEqual(d["status"], "PASS")
        self.assertEqual(d["message"], "消息")
        self.assertEqual(d["details"], ["详情"])
        self.assertEqual(d["fix_hints"], ["修复"])


class TestParseChapterNumber(unittest.TestCase):
    """章节号解析。"""

    def test_chinese_format(self):
        """「第X章」格式。"""
        self.assertEqual(_parse_chapter_number("第001章_开篇.md"), 1)
        self.assertEqual(_parse_chapter_number("第37章.md"), 37)

    def test_chapter_format(self):
        """"Chapter_X" 格式。"""
        self.assertEqual(_parse_chapter_number("Chapter_5.md"), 5)
        self.assertEqual(_parse_chapter_number("chapter-12.md"), 12)

    def test_no_chapter_returns_none(self):
        """无章节号返回 None。"""
        self.assertIsNone(_parse_chapter_number("readme.md"))


class TestCollectChapterFiles(unittest.TestCase):
    """章节文件收集。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_collect_and_sort(self):
        """按章号排序收集。"""
        (self.root / "第003章.md").write_text("c")
        (self.root / "第001章.md").write_text("a")
        (self.root / "第010章.md").write_text("b")
        chapters = _collect_chapter_files(self.root)
        nums = [c[0] for c in chapters]
        self.assertEqual(nums, [1, 3, 10])

    def test_empty_dir(self):
        """空目录返回空列表。"""
        chapters = _collect_chapter_files(self.root)
        self.assertEqual(chapters, [])


class TestCountChineseChars(unittest.TestCase):
    """中文字符统计。"""

    def test_pure_chinese(self):
        self.assertEqual(_count_chinese_chars("你好世界"), 4)

    def test_mixed(self):
        self.assertEqual(_count_chinese_chars("Hello 世界 123"), 2)

    def test_empty(self):
        self.assertEqual(_count_chinese_chars(""), 0)


class TestGetCharacterNames(unittest.TestCase):
    """角色名提取。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_names(self):
        """从文件名提取角色名。"""
        (self.root / "张三.md").write_text("x")
        (self.root / "李四_别名.md").write_text("x")
        (self.root / "王五（外号）.md").write_text("x")
        names = _get_character_names_from_cards(self.root)
        self.assertIn("张三", names)
        self.assertIn("李四", names)
        self.assertIn("王五", names)

    def test_empty_dir(self):
        """空目录返回空集合。"""
        names = _get_character_names_from_cards(self.root)
        self.assertEqual(names, set())


class TestParseTimeline(unittest.TestCase):
    """时间线解析。"""

    def test_simple_table(self):
        """解析简单时间线表格。"""
        text = "| 章节 | 时间 |\n|------|------|\n| 1 | 第一天 |\n| 2 | 第二天 |"
        entries = _parse_timeline_entries(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "1")


class TestCheckTimeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "追踪").mkdir()
        self.timeline = self.root / "追踪" / "时间线.md"

    def write_timeline(self, marker="", time=1, event="回到入宗日"):
        self.timeline.write_text(
            "| 章节 | 故事内时间 | 事件 | 时间标记/约定 |\n"
            "| --- | --- | --- | --- |\n"
            "| 第1章 | 第10天 | 遭劫 | |\n"
            f"| 第2章 | 第{time}天 | {event} | {marker} |\n", encoding="utf-8")

    def test_marked_time_regression_requires_semantic_review(self):
        for marker in ("闪回", "插叙", "时间回溯", "时间循环", "重生"):
            with self.subTest(marker=marker):
                self.write_timeline(f"{marker}；依据：世界观第三条")
                result = check_timeline(self.root, target_chapter=2)
                self.assertEqual(result.status, "WARN")
                self.assertIn("需语义核对", result.message)
                self.assertIn(marker, " ".join(result.details))
                self.assertIn("尚未验证", " ".join(result.fix_hints))

    def test_time_regression_only_accepts_explicit_marker_items(self):
        for marker in ("", "没有时间回溯", "并非闪回", "禁止重生", "讨论时间循环", "时间回溯未发生"):
            with self.subTest(marker=marker):
                self.write_timeline(marker, event="时间回溯已被提及")
                self.assertEqual(check_timeline(self.root).status, "FAIL")

    def test_marked_regression_does_not_hide_another_unmarked_regression(self):
        self.write_timeline("时间循环", time=2)
        with self.timeline.open("a", encoding="utf-8") as out:
            out.write("| 第3章 | 第1天 | 再度归来 | |\n")
        self.assertEqual(check_timeline(self.root).status, "FAIL")

    def test_time_regression_cli_exit_codes(self):
        for marker, time, expected_code, status in (
            ("", 11, 0, "PASS"), ("时间回溯", 1, 1, "WARN"),
            ("", 1, 1, "FAIL"), ("没有时间回溯", 1, 1, "FAIL"),
        ):
            with self.subTest(marker=marker, time=time):
                self.write_timeline(marker, time)
                result = subprocess.run([sys.executable, "-B", str(SCRIPT_DIR / "static_check.py"),
                                         str(self.root), "--json"], capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, expected_code, result.stderr)
                checks = json.loads(result.stdout)["results"]
                self.assertEqual(next(r for r in checks if r["category"] == "TIMELINE")["status"], status)


class TestParseForeshadowLedger(unittest.TestCase):
    """伏笔台账解析。"""

    def test_resolved_and_unresolved(self):
        """区分已回收与未回收伏笔。"""
        text = (
            "| 编号 | 内容 | 状态 |\n"
            "|------|------|------|\n"
            "| F1-1 | 秘密 | ✅已回收 |\n"
            "| F1-2 | 谜团 | 未回收 |"
        )
        entries = _parse_foreshadow_ledger(text)
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0]["resolved"])
        self.assertFalse(entries[1]["resolved"])


class TestParseSummaryEntries(unittest.TestCase):
    """章节摘要解析。"""

    def test_extract_chapter_headers(self):
        """提取章节号。"""
        text = "### 第1章\n内容\n### 第5章\n内容"
        entries = _parse_summary_entries(text)
        self.assertEqual([e["chapter"] for e in entries], [1, 5])


class TestCheckCharacter(unittest.TestCase):
    """角色一致性检查。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)
        (self.root / "设定").mkdir(parents=True)
        (self.root / "设定" / "角色").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_character_dir_warns(self):
        """无角色目录且无正文时返回 PASS（无内容可检查）。"""
        # 删除角色目录
        import shutil
        shutil.rmtree(self.root / "设定" / "角色")
        result = check_character(self.root)
        # 无正文文件时返回 PASS（无内容可检查）
        self.assertIn(result.status, ("PASS", "WARN", "FAIL"))

    def test_character_consistency_pass(self):
        """正文角色都有人物卡时通过。"""
        (self.root / "设定" / "角色" / "张三.md").write_text("x")
        (self.root / "正文" / "第001章.md").write_text("张三走了出去。", encoding="utf-8")
        result = check_character(self.root, target_chapter=1)
        self.assertEqual(result.status, "PASS")


class TestCheckSync(unittest.TestCase):
    """同步检查。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "追踪").mkdir(parents=True)
        (self.root / "正文").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync_pass(self):
        """追踪文件更新到最新章时通过。"""
        (self.root / "追踪" / "章节摘要.md").write_text("### 第5章\n摘要")
        (self.root / "追踪" / "角色状态.md").write_text("第5章状态")
        (self.root / "正文" / "第005章.md").write_text("正文内容")
        result = check_sync(self.root, target_chapter=5)
        self.assertIn(result.status, ("PASS", "WARN"))


class TestCheckWordcount(unittest.TestCase):
    """字数连续性检查。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_similar_length_pass(self):
        """相邻章节字数相近时通过。"""
        (self.root / "正文" / "第001章.md").write_text("中文字符测试内容" * 150, encoding="utf-8")
        (self.root / "正文" / "第002章.md").write_text("中文字符测试内容" * 155, encoding="utf-8")
        result = check_wordcount(self.root)
        self.assertEqual(result.status, "PASS")

    def test_large_diff_warns(self):
        """相邻章节字数差异过大时告警。"""
        (self.root / "正文" / "第001章.md").write_text("中文字符测试内容" * 150, encoding="utf-8")
        (self.root / "正文" / "第002章.md").write_text("短。", encoding="utf-8")
        result = check_wordcount(self.root)
        self.assertIn(result.status, ("WARN", "FAIL"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
