#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_common.py — 测试 common.py 共享模块的核心函数。

运行方式：
    python scripts/tests/test_common.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# 把 scripts 目录加入 sys.path，便于 import common
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    read_text,
    write_text,
    count_chinese_chars,
    split_paragraphs,
    parse_chapter_number,
    truncate_text,
    find_book_dir,
    count_chars,
    normalize_whitespace,
)


class TestReadText(unittest.TestCase):
    """测试 read_text / write_text 文件读写。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "f.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_text_normal(self):
        """正常读取 UTF-8 文本。"""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("你好，世界。")
        self.assertEqual(read_text(self.path), "你好，世界。")

    def test_read_text_with_bom(self):
        """读取带 BOM 的 UTF-8 文件（默认 utf-8-sig）。"""
        with open(self.path, "w", encoding="utf-8-sig") as f:
            f.write("带 BOM 的文本")
        self.assertEqual(read_text(self.path), "带 BOM 的文本")

    def test_read_text_missing_returns_none(self):
        """文件不存在返回 None。"""
        self.assertIsNone(read_text(os.path.join(self.tmp.name, "不存在.txt")))

    def test_write_text_creates_parents(self):
        """write_text 自动创建父目录。"""
        nested = os.path.join(self.tmp.name, "a", "b", "c.txt")
        self.assertTrue(write_text(nested, "内容"))
        self.assertEqual(read_text(nested), "内容")

    def test_write_text_returns_bool(self):
        """write_text 成功返回 True。"""
        self.assertTrue(write_text(self.path, "新内容"))
        self.assertEqual(read_text(self.path), "新内容")


class TestCountChineseChars(unittest.TestCase):
    """测试 count_chinese_chars 中文字符统计。"""

    def test_pure_chinese(self):
        self.assertEqual(count_chinese_chars("你好世界"), 4)

    def test_mixed_text(self):
        self.assertEqual(count_chinese_chars("Hello 世界! 123"), 2)

    def test_no_chinese(self):
        self.assertEqual(count_chinese_chars("Hello World 123"), 0)

    def test_empty_string(self):
        self.assertEqual(count_chinese_chars(""), 0)

    def test_with_punctuation(self):
        # 中文标点不在 \u4e00-\u9fff 范围
        self.assertEqual(count_chinese_chars("你好，世界！"), 4)


class TestSplitParagraphs(unittest.TestCase):
    """测试 split_paragraphs 段落分割。"""

    def test_single_paragraph(self):
        self.assertEqual(split_paragraphs("只有一段文字"), ["只有一段文字"])

    def test_multiple_paragraphs(self):
        text = "第一段。\n\n第二段。\n\n第三段。"
        self.assertEqual(split_paragraphs(text),
                         ["第一段。", "第二段。", "第三段。"])

    def test_strip_whitespace(self):
        text = "  第一段  \n\n  第二段  "
        self.assertEqual(split_paragraphs(text), ["第一段", "第二段"])

    def test_skip_empty(self):
        text = "第一段\n\n\n\n第二段"
        self.assertEqual(split_paragraphs(text), ["第一段", "第二段"])

    def test_empty_text(self):
        self.assertEqual(split_paragraphs(""), [])

    def test_only_whitespace(self):
        self.assertEqual(split_paragraphs("   \n\n  \n  "), [])


class TestParseChapterNumber(unittest.TestCase):
    """测试 parse_chapter_number 章节号解析（多种格式）。"""

    def test_format_chinese_zero_padded(self):
        self.assertEqual(parse_chapter_number("第037章_xxx.md"), 37)

    def test_format_chinese_with_space(self):
        self.assertEqual(parse_chapter_number("第37章 xxx.md"), 37)

    def test_format_chinese_only(self):
        self.assertEqual(parse_chapter_number("第37章.md"), 37)

    def test_format_chapter_underscore(self):
        self.assertEqual(parse_chapter_number("chapter_37.md"), 37)

    def test_format_chapter_no_sep(self):
        self.assertEqual(parse_chapter_number("chapter37.md"), 37)

    def test_format_ch_prefix(self):
        self.assertEqual(parse_chapter_number("ch37.md"), 37)

    def test_format_outline_prefix(self):
        self.assertEqual(parse_chapter_number("章纲_第037章.md"), 37)

    def test_no_chapter_number(self):
        self.assertIsNone(parse_chapter_number("readme.md"))

    def test_large_number(self):
        self.assertEqual(parse_chapter_number("第1234章_尾声.md"), 1234)


class TestTruncateText(unittest.TestCase):
    """测试 truncate_text 文本截断。"""

    def test_short_text_unchanged(self):
        text = "短文本"
        self.assertEqual(truncate_text(text, 100), text)

    def test_truncate_at_paragraph_boundary(self):
        """超出字数时在段落边界截断。"""
        p1 = "甲" * 50
        p2 = "乙" * 50
        p3 = "丙" * 50
        text = f"{p1}\n\n{p2}\n\n{p3}"
        # 总 150 字，截到 80
        result = truncate_text(text, 80)
        # 应至少包含第一段
        self.assertIn(p1, result)
        # 不应包含第三段
        self.assertNotIn(p3, result)

    def test_truncate_returns_string(self):
        text = "段落一。\n\n段落二。"
        result = truncate_text(text, 5)
        self.assertIsInstance(result, str)

    def test_truncate_exact_fit(self):
        text = "正好"
        self.assertEqual(truncate_text(text, count_chars(text)), text)


class TestFindBookDir(unittest.TestCase):
    """测试 find_book_dir 书籍工程定位。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_book(self, name):
        """在临时目录下创建一个模拟书籍工程。"""
        book = Path(self.tmp.name) / name
        (book / "追踪").mkdir(parents=True)
        (book / "大纲").mkdir(parents=True)
        (book / "正文").mkdir(parents=True)
        return book

    def test_self_is_book_dir(self):
        """路径本身是书籍工程目录。"""
        book = self._make_book("我的书")
        self.assertEqual(find_book_dir(book), book)

    def test_child_is_book_dir(self):
        """在父目录下查找子目录中的书籍工程。"""
        book = self._make_book("我的书")
        parent = Path(self.tmp.name)
        self.assertEqual(find_book_dir(parent), book)

    def test_no_book_dir(self):
        """没有书籍工程时返回 None。"""
        empty = Path(self.tmp.name) / "空目录"
        empty.mkdir()
        self.assertIsNone(find_book_dir(empty))

    def test_nonexistent_path(self):
        """路径不存在返回 None。"""
        self.assertIsNone(find_book_dir(Path(self.tmp.name) / "不存在"))


class TestNormalizeWhitespace(unittest.TestCase):
    """测试 normalize_whitespace 规范化空白。"""

    def test_collapse_multiple_blank_lines(self):
        text = "段一\n\n\n\n段二"
        self.assertEqual(normalize_whitespace(text), "段一\n\n段二")

    def test_strip_line_ends(self):
        text = "  行一  \n  行二  "
        self.assertEqual(normalize_whitespace(text), "行一\n行二")

    def test_strip_outer(self):
        self.assertEqual(normalize_whitespace("\n\n内容\n\n"), "内容")


if __name__ == "__main__":
    unittest.main(verbosity=2)
