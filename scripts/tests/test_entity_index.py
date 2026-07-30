#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_entity_index.py — 测试 entity_index.py 实体索引核心功能。

运行方式：
    python scripts/tests/test_entity_index.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import entity_index
from entity_index import (
    parse_entities,
    build_index,
    load_index,
    semantic_search,
    is_light_scene,
    BM25Index,
    _tokenize_chinese,
)


def _make_summary_text():
    """构造一份章节摘要测试文本。"""
    return """# 章节摘要

### 第1章 开端

- 关键实体：林雷、盘龙戒指、沃尔夫商店
- 摘要：林雷初到沃尔夫商店选购盘龙戒指。

### 第2章 试炼

- 关键实体：林雷、魔法试炼、火系魔法
- 摘要：林雷参加魔法试炼，展现火系魔法天赋。

### 第3章 秘密

- 关键实体：盘龙戒指、上古龙族、秘密
- 摘要：盘龙戒指中隐藏着上古龙族的秘密。
"""


def _make_book_root(tmpdir):
    """在 tmpdir 下创建一个模拟书籍工程，返回其路径。"""
    book = Path(tmpdir)
    track = book / "追踪"
    track.mkdir(parents=True, exist_ok=True)
    (book / "正文").mkdir(parents=True, exist_ok=True)
    # 写入章节摘要
    (track / "章节摘要.md").write_text(_make_summary_text(), encoding="utf-8")
    # 写入正文
    (book / "正文" / "第1章_开端.md").write_text(
        "林雷走进沃尔夫商店，看到了一枚盘龙戒指。\n", encoding="utf-8")
    (book / "正文" / "第2章_试炼.md").write_text(
        "林雷参加魔法试炼，施展了火系魔法。\n", encoding="utf-8")
    (book / "正文" / "第3章_秘密.md").write_text(
        "盘龙戒指里封印着上古龙族的秘密。\n", encoding="utf-8")
    return str(book)


class TestParseEntities(unittest.TestCase):
    """parse_entities 实体字段切分。"""

    def test_comma_separated(self):
        ents = parse_entities("林雷, 盘龙戒指, 沃尔夫商店")
        self.assertIn("林雷", ents)
        self.assertIn("盘龙戒指", ents)
        self.assertIn("沃尔夫商店", ents)

    def test_chinese_separators(self):
        """顿号/斜杠/分号分隔。"""
        ents = parse_entities("林雷、盘龙戒指/沃尔夫商店；魔法试炼")
        self.assertEqual(len(ents), 4)

    def test_strip_parenthetical_notes(self):
        """括号注释被去除。"""
        ents = parse_entities("林雷（主角）、盘龙戒指")
        self.assertIn("林雷", ents)
        # 「（主角）」被去除
        self.assertNotIn("（主角）", ents)

    def test_skip_overlong(self):
        """超长实体（>20字）被跳过。"""
        long_name = "超" * 25
        ents = parse_entities(f"林雷、{long_name}")
        self.assertIn("林雷", ents)
        self.assertNotIn(long_name, ents)


class TestBuildIndex(unittest.TestCase):
    """build_index 索引构建。"""

    def test_build_index_creates_file(self):
        """build_index 生成 entity_index.json 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            index, out_path, n_entries = build_index(book)
            self.assertTrue(os.path.isfile(out_path))
            self.assertEqual(os.path.basename(out_path), "entity_index.json")
            self.assertEqual(n_entries, 3)

    def test_build_index_content(self):
        """索引内容包含正确实体与章节映射。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            index, _, _ = build_index(book)
            # 林雷出现在第1、2章
            self.assertIn("林雷", index)
            self.assertEqual(sorted(index["林雷"]), [1, 2])
            # 盘龙戒指出现在第1、3章
            self.assertIn("盘龙戒指", index)
            self.assertEqual(sorted(index["盘龙戒指"]), [1, 3])
            # 魔法试炼只在第2章
            self.assertEqual(index["魔法试炼"], [2])

    def test_build_index_idempotent(self):
        """重复构建索引结果一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            index1, _, _ = build_index(book)
            index2, _, _ = build_index(book)
            self.assertEqual(index1, index2)

    def test_load_index_after_build(self):
        """构建后 load_index 能读回。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            build_index(book)
            loaded, path = load_index(book)
            self.assertIsNotNone(loaded)
            self.assertIn("林雷", loaded)

    def test_load_index_missing_returns_none(self):
        """索引不存在时 load_index 返回 (None, path)。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            # 不调用 build_index
            loaded, path = load_index(book)
            self.assertIsNone(loaded)


class TestSemanticSearch(unittest.TestCase):
    """BM25 语义检索。"""

    def test_semantic_search_returns_results(self):
        """semantic_search 返回相关章节列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            build_index(book)  # 先建索引
            results = semantic_search(book, ["林雷 魔法试炼"], top_k=3)
            self.assertIsInstance(results, list)
            self.assertGreater(len(results), 0)
            # 结果结构：(章号, 得分, 预览, 匹配关键词, 元数据)
            first = results[0]
            self.assertEqual(len(first), 5)
            # 第2章（含魔法试炼）应排在前列
            chapters = [r[0] for r in results]
            self.assertIn(2, chapters)

    def test_semantic_search_no_match_returns_empty(self):
        """无匹配查询返回空列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            build_index(book)
            # 用一个完全无关的查询
            results = semantic_search(book, ["zzznonexistent"], top_k=3)
            self.assertEqual(results, [])

    def test_semantic_search_light_scene(self):
        """轻场景查询走实体索引分支。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book_root(tmp)
            build_index(book)
            # 「赶路」是轻场景关键词
            results = semantic_search(book, ["赶路"], top_k=3, light=True)
            self.assertIsInstance(results, list)

    def test_is_light_scene(self):
        """轻场景关键词判定。"""
        self.assertTrue(is_light_scene(["赶路", "过场"]))
        self.assertTrue(is_light_scene(["出发"]))
        self.assertFalse(is_light_scene(["战斗", "秘密"]))


class TestBM25Index(unittest.TestCase):
    """BM25 索引单元测试。"""

    def test_bm25_build_and_score(self):
        """BM25 索引能构建并打分。"""
        docs = [
            (1, "林雷走进沃尔夫商店看到盘龙戒指"),
            (2, "林雷参加魔法试炼施展火系魔法"),
            (3, "盘龙戒指封印上古龙族的秘密"),
        ]
        bm25 = BM25Index(docs)
        # 查询「林雷」
        query_tokens = _tokenize_chinese("林雷")
        results = bm25.search(query_tokens, top_k=3)
        # 林雷出现在第1、2章
        hit_chapters = {r[0] for r in results}
        self.assertTrue({1, 2}.issubset(hit_chapters))

    def test_bm25_empty_query_returns_empty(self):
        """空查询返回空列表。"""
        docs = [(1, "测试文本")]
        bm25 = BM25Index(docs)
        self.assertEqual(bm25.search([], top_k=3), [])

    def test_bm25_idf_positive(self):
        """IDF 值为正（log 内项 > 1）。"""
        docs = [
            (1, "林雷战斗"),
            (2, "林雷休息"),
            (3, "盘龙戒指秘密"),
        ]
        bm25 = BM25Index(docs)
        # 「林雷」出现在 2/3 文档，IDF 应为正
        self.assertGreater(bm25.idf("林雷"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
