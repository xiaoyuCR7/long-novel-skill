#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_rag_retriever.py — 测试 rag_retriever.py RAG 检索器核心功能。

覆盖范围：
  - _tokenize_chinese：中文分词（去停用字单字 + 滑窗双字词）
  - _parse_entities：实体字段切分（括号注释去除、多分隔符、长度过滤）
  - _extract_emotion_tags：情绪标签提取
  - _extract_summary_text：章节摘要文本提取（含回退逻辑）
  - BM25Index：BM25 索引构建、IDF、打分、检索排序
  - cmd_build：RAG 索引构建（含增量更新、元数据提取）
  - rag_query：相关章节检索（全量 BM25+TF-IDF 精排 / 轻场景快速匹配）
  - is_light_scene：轻场景关键词判定
  - CLI 子进程测试：build / query / status

运行方式：
    python scripts/tests/test_rag_retriever.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rag_retriever
from rag_retriever import (
    _tokenize_chinese,
    _parse_entities,
    _extract_emotion_tags,
    _extract_summary_text,
    BM25Index,
    cmd_build,
    rag_query,
    is_light_scene,
    load_rag_index,
    save_rag_index,
)

SCRIPT_PATH = str(SCRIPT_DIR / "rag_retriever.py")


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------

def _make_summary_text():
    """构造一份包含关键实体、章节摘要、情绪基调的章节摘要测试文本。"""
    return """# 章节摘要

### 第1章 初入沃尔夫

- 关键实体：林雷、盘龙戒指、沃尔夫商店、德林柯沃特
- 章节摘要：林雷初到沃尔夫商店选购盘龙戒指，偶遇神秘老者德林柯沃特。
- 情绪基调：期待、好奇

### 第2章 魔法试炼

- 关键实体：林雷、魔法试炼、火系魔法、风系魔法
- 章节摘要：林雷参加魔法学院试炼，展现火系魔法与风系魔法双重天赋。
- 情绪基调：紧张、兴奋

### 第3章 龙族秘密

- 关键实体：盘龙戒指、上古龙族、德林柯沃特、灵魂印记
- 章节摘要：盘龙戒指中封印着上古龙族的秘密，德林柯沃特以灵魂印记指引林雷。
- 情绪基调：神秘、震撼

### 第4章 宿敌初现

- 关键实体：林雷、布莱特、决斗、光明教廷
- 章节摘要：林雷与布莱特发生冲突，约定三日后决斗，光明教廷暗中观察。
- 情绪基调：愤怒、决意
"""


def _make_book_root(tmpdir):
    """在 tmpdir 下创建模拟书籍工程目录（正文/ + 追踪/章节摘要.md），返回路径。"""
    book = Path(tmpdir)
    track = book / "追踪"
    track.mkdir(parents=True, exist_ok=True)
    (book / "正文").mkdir(parents=True, exist_ok=True)
    # 写入章节摘要
    (track / "章节摘要.md").write_text(_make_summary_text(), encoding="utf-8")
    # 写入正文文件
    chapters = {
        "第1章_初入沃尔夫.md": (
            "林雷走进沃尔夫商店，目光被柜台上一枚古朴的盘龙戒指吸引。\n"
            "旁边一位白发老者德林柯沃特微微一笑，似乎早已预料到这一切。\n"
        ),
        "第2章_魔法试炼.md": (
            "魔法学院的试炼场上，林雷深吸一口气，双手同时凝聚出火系魔法与风系魔法。\n"
            "考官们纷纷起身，这般双系天赋百年罕见。\n"
        ),
        "第3章_龙族秘密.md": (
            "夜深人静，盘龙戒指微微发光，德林柯沃特的灵魂印记浮现。\n"
            "他缓缓道出上古龙族被封印的秘密，林雷听得心潮澎湃。\n"
        ),
        "第4章_宿敌初现.md": (
            "走廊尽头，布莱特拦住林雷的去路，言语挑衅。\n"
            "林雷毫不退让，两人约定三日后公开决斗，光明教廷的探子暗暗记下这一切。\n"
        ),
    }
    for name, content in chapters.items():
        (book / "正文" / name).write_text(content, encoding="utf-8")
    return str(book)


class _BookFixture(unittest.TestCase):
    """需要完整书籍工程夹具的测试基类。

    使用 tempfile.mkdtemp 创建临时目录，通过 addCleanup 注册清理。
    """

    def setUp(self):
        """创建临时书籍工程目录。"""
        self.tmpdir = tempfile.mkdtemp(prefix="rag_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.book_root = _make_book_root(self.tmpdir)


# ---------------------------------------------------------------------------
# _tokenize_chinese
# ---------------------------------------------------------------------------

class TestTokenizeChinese(unittest.TestCase):
    """_tokenize_chinese 中文分词测试。"""

    def test_basic_unigrams_and_bigrams(self):
        """基础分词：返回单字 + 相邻双字词。"""
        tokens = _tokenize_chinese("林雷战斗")
        # 单字
        self.assertIn("林", tokens)
        self.assertIn("雷", tokens)
        self.assertIn("战", tokens)
        self.assertIn("斗", tokens)
        # 双字
        self.assertIn("林雷", tokens)
        self.assertIn("雷战", tokens)
        self.assertIn("战斗", tokens)

    def test_stop_chars_removed_from_unigrams(self):
        """停用字从单字结果中移除。"""
        tokens = _tokenize_chinese("林的雷")
        # 「的」是停用字
        self.assertNotIn("的", tokens)
        self.assertIn("林", tokens)
        self.assertIn("雷", tokens)

    def test_stop_chars_removed_from_bigrams(self):
        """停用字不参与双字词构建。"""
        tokens = _tokenize_chinese("林的雷")
        # 「林 的」和「的 雷」均含停用字，不应出现
        self.assertNotIn("林的", tokens)
        self.assertNotIn("的雷", tokens)

    def test_empty_text(self):
        """空文本返回空列表。"""
        self.assertEqual(_tokenize_chinese(""), [])

    def test_whitespace_filtered_from_unigrams(self):
        """空白字符从单字结果中过滤（双字词可能含空白）。"""
        tokens = _tokenize_chinese("   ")
        unigrams = [t for t in tokens if len(t) == 1]
        self.assertEqual(unigrams, [])

    def test_returns_list_type(self):
        """返回值类型为列表。"""
        self.assertIsInstance(_tokenize_chinese("测试"), list)

    def test_single_char(self):
        """单字文本只返回一个单字，无双字词。"""
        tokens = _tokenize_chinese("龙")
        self.assertEqual(tokens, ["龙"])


# ---------------------------------------------------------------------------
# _parse_entities
# ---------------------------------------------------------------------------

class TestParseEntities(unittest.TestCase):
    """_parse_entities 实体字段切分测试。"""

    def test_comma_separated(self):
        """英文逗号分隔。"""
        ents = _parse_entities("林雷, 盘龙戒指, 沃尔夫商店")
        self.assertIn("林雷", ents)
        self.assertIn("盘龙戒指", ents)
        self.assertIn("沃尔夫商店", ents)

    def test_chinese_separators(self):
        """顿号/斜杠/分号分隔。"""
        ents = _parse_entities("林雷、盘龙戒指/沃尔夫商店；魔法试炼")
        self.assertEqual(len(ents), 4)
        self.assertIn("魔法试炼", ents)

    def test_strip_fullwidth_parenthetical(self):
        """全角括号注释被去除。"""
        ents = _parse_entities("林雷（主角）、盘龙戒指")
        self.assertIn("林雷", ents)
        self.assertNotIn("（主角）", ents)

    def test_strip_halfwidth_parenthetical(self):
        """半角括号注释被去除。"""
        ents = _parse_entities("林雷(主角)、盘龙戒指")
        self.assertIn("林雷", ents)

    def test_skip_overlong(self):
        """超长实体（>20字）被跳过。"""
        long_name = "超" * 25
        ents = _parse_entities(f"林雷、{long_name}")
        self.assertIn("林雷", ents)
        self.assertNotIn(long_name, ents)

    def test_newline_separated(self):
        """换行符分隔。"""
        ents = _parse_entities("林雷\n盘龙戒指\n沃尔夫商店")
        self.assertEqual(len(ents), 3)

    def test_empty_string(self):
        """空字符串返回空列表。"""
        self.assertEqual(_parse_entities(""), [])

    def test_strip_trailing_period(self):
        """去除尾部句号。"""
        ents = _parse_entities("林雷。")
        self.assertEqual(ents, ["林雷"])

    def test_boundary_length_20(self):
        """恰好 20 字的实体保留。"""
        name = "超" * 20
        ents = _parse_entities(name)
        self.assertIn(name, ents)


# ---------------------------------------------------------------------------
# _extract_emotion_tags
# ---------------------------------------------------------------------------

class TestExtractEmotionTags(unittest.TestCase):
    """_extract_emotion_tags 情绪标签提取测试。"""

    def test_normal_extraction(self):
        """正常提取顿号分隔的情绪标签。"""
        text = "- 情绪基调：期待、好奇\n"
        tags = _extract_emotion_tags(text)
        self.assertIn("期待", tags)
        self.assertIn("好奇", tags)

    def test_comma_separated(self):
        """英文逗号分隔的情绪标签。"""
        text = "情绪基调：紧张, 兴奋"
        tags = _extract_emotion_tags(text)
        self.assertEqual(tags, ["紧张", "兴奋"])

    def test_no_emotion_field(self):
        """无情绪基调字段返回空列表。"""
        text = "- 关键实体：林雷、盘龙戒指\n- 章节摘要：林雷的故事。\n"
        tags = _extract_emotion_tags(text)
        self.assertEqual(tags, [])

    def test_multiple_tags(self):
        """多个情绪标签全部提取。"""
        text = "情绪基调：愤怒、悲伤、决意、震撼"
        tags = _extract_emotion_tags(text)
        self.assertEqual(len(tags), 4)

    def test_skip_overlong_tag(self):
        """超长标签（>10字）被跳过。"""
        long_tag = "超" * 15
        text = f"情绪基调：期待、{long_tag}"
        tags = _extract_emotion_tags(text)
        self.assertIn("期待", tags)
        self.assertNotIn(long_tag, tags)


# ---------------------------------------------------------------------------
# _extract_summary_text
# ---------------------------------------------------------------------------

class TestExtractSummaryText(unittest.TestCase):
    """_extract_summary_text 章节摘要文本提取测试。"""

    def test_normal_extraction(self):
        """正常提取章节摘要文本。"""
        text = (
            "### 第1章 初入沃尔夫\n"
            "- 关键实体：林雷\n"
            "- 章节摘要：林雷初到沃尔夫商店选购盘龙戒指。\n"
            "- 情绪基调：期待\n"
        )
        summary = _extract_summary_text(text)
        self.assertIn("林雷", summary)
        self.assertIn("沃尔夫商店", summary)
        self.assertIn("盘龙戒指", summary)

    def test_strips_trailing_period(self):
        """主路径去除尾部句号和空白。"""
        text = "章节摘要：林雷的故事。"
        summary = _extract_summary_text(text)
        self.assertFalse(summary.endswith("。"))
        self.assertEqual(summary, "林雷的故事")

    def test_fallback_no_summary_field(self):
        """无章节摘要字段时回退取第一段非标题行。"""
        text = "### 第1章 测试\n这是回退文本内容。\n"
        summary = _extract_summary_text(text)
        self.assertEqual(summary, "这是回退文本内容。")

    def test_fallback_skips_header_lines(self):
        """回退时跳过 # 标题行。"""
        text = "### 第1章 测试\n### 子标题\n回退行。\n"
        summary = _extract_summary_text(text)
        self.assertEqual(summary, "回退行。")

    def test_fallback_skips_key_prefixed(self):
        """回退时跳过「关键」「情绪」开头的行。"""
        text = "### 第1章 测试\n关键实体说明\n情绪描述\n回退行。\n"
        summary = _extract_summary_text(text)
        self.assertEqual(summary, "回退行。")

    def test_empty_text(self):
        """空文本返回空字符串。"""
        self.assertEqual(_extract_summary_text(""), "")

    def test_truncation_in_fallback(self):
        """回退文本超过 200 字时截断为 200 字。"""
        long_line = "字" * 250
        text = f"### 第1章 测试\n{long_line}\n"
        summary = _extract_summary_text(text)
        self.assertEqual(len(summary), 200)


# ---------------------------------------------------------------------------
# BM25Index
# ---------------------------------------------------------------------------

class TestBM25Index(unittest.TestCase):
    """BM25Index 索引构建、打分与检索测试。"""

    def test_build_and_search(self):
        """构建索引并检索返回相关文档。"""
        docs = [
            (1, "林雷走进沃尔夫商店看到盘龙戒指"),
            (2, "林雷参加魔法试炼施展火系魔法"),
            (3, "盘龙戒指封印上古龙族的秘密"),
        ]
        bm25 = BM25Index(docs)
        query_tokens = _tokenize_chinese("林雷魔法试炼")
        results = bm25.search(query_tokens, top_k=3)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        # 林雷出现在第1、2章，魔法试炼在第2章
        hit_chapters = {r[0] for r in results}
        self.assertIn(2, hit_chapters)

    def test_search_sorted_by_score(self):
        """检索结果按得分降序排列。"""
        docs = [
            (1, "林雷林雷林雷"),
            (2, "林雷"),
            (3, "盘龙戒指"),
        ]
        bm25 = BM25Index(docs)
        results = bm25.search(_tokenize_chinese("林雷"), top_k=3)
        scores = [r[1] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_query_returns_empty(self):
        """空查询返回空列表。"""
        bm25 = BM25Index([(1, "测试文本")])
        self.assertEqual(bm25.search([], top_k=3), [])

    def test_no_match_returns_empty(self):
        """无匹配查询返回空列表。"""
        bm25 = BM25Index([(1, "林雷战斗")])
        results = bm25.search(_tokenize_chinese("zzz"), top_k=3)
        self.assertEqual(results, [])

    def test_idf_positive(self):
        """常见词 IDF 值为正。"""
        docs = [
            (1, "林雷战斗"),
            (2, "林雷休息"),
            (3, "盘龙戒指秘密"),
        ]
        bm25 = BM25Index(docs)
        self.assertGreater(bm25.idf("林雷"), 0)

    def test_idf_rarer_term_higher(self):
        """罕见词 IDF 高于常见词。"""
        docs = [
            (1, "林雷战斗秘密"),
            (2, "林雷休息秘密"),
            (3, "林雷盘龙戒指"),
        ]
        bm25 = BM25Index(docs)
        # 「林雷」出现在 3/3 文档，「盘龙」出现在 1/3 文档
        self.assertGreater(bm25.idf("盘龙"), bm25.idf("林雷"))

    def test_score_zero_for_unknown_doc(self):
        """未知文档 ID 得分为 0。"""
        bm25 = BM25Index([(1, "测试")])
        self.assertEqual(bm25.score(_tokenize_chinese("测试"), 999), 0.0)

    def test_score_zero_for_no_token_match(self):
        """文档不含查询词时得分为 0。"""
        bm25 = BM25Index([(1, "林雷"), (2, "盘龙")])
        self.assertEqual(bm25.score(_tokenize_chinese("魔法"), 1), 0.0)

    def test_avgdl_positive(self):
        """平均文档长度为正。"""
        docs = [
            (1, "林雷战斗"),
            (2, "盘龙戒指"),
        ]
        bm25 = BM25Index(docs)
        self.assertGreater(bm25.avgdl, 0)

    def test_search_returns_matched_terms(self):
        """检索结果包含匹配词项列表。"""
        docs = [(1, "林雷战斗"), (2, "盘龙戒指")]
        bm25 = BM25Index(docs)
        results = bm25.search(_tokenize_chinese("林雷"), top_k=1)
        self.assertEqual(len(results), 1)
        doc_id, score, matched = results[0]
        self.assertEqual(doc_id, 1)
        self.assertIsInstance(matched, list)
        # 匹配词项格式为 (term, tf)
        if matched:
            self.assertEqual(len(matched[0]), 2)

    def test_search_top_k_limit(self):
        """top_k 限制返回数量。"""
        docs = [(i, "林雷") for i in range(10)]
        bm25 = BM25Index(docs)
        results = bm25.search(_tokenize_chinese("林雷"), top_k=3)
        self.assertLessEqual(len(results), 3)

    def test_custom_k1_b(self):
        """自定义 k1 / b 参数生效。"""
        docs = [(1, "林雷战斗"), (2, "盘龙戒指")]
        bm25 = BM25Index(docs, k1=2.0, b=0.5)
        self.assertEqual(bm25.k1, 2.0)
        self.assertEqual(bm25.b, 0.5)


# ---------------------------------------------------------------------------
# cmd_build（build_index）
# ---------------------------------------------------------------------------

class TestCmdBuild(_BookFixture):
    """cmd_build RAG 索引构建测试。"""

    def test_build_returns_zero(self):
        """构建成功返回退出码 0。"""
        ret = cmd_build(self.book_root)
        self.assertEqual(ret, 0)

    def test_build_creates_index_file(self):
        """构建生成 rag_index.json 文件。"""
        cmd_build(self.book_root)
        idx_path = os.path.join(self.book_root, "追踪", "rag_index.json")
        self.assertTrue(os.path.isfile(idx_path))

    def test_build_index_structure(self):
        """索引顶层结构包含 version / chapters 等字段。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        self.assertIsNotNone(index_data)
        self.assertIn("version", index_data)
        self.assertIn("last_updated", index_data)
        self.assertIn("total_chapters", index_data)
        self.assertIn("indexed_chapters", index_data)
        self.assertIn("chapters", index_data)

    def test_build_index_chapter_count(self):
        """索引章节数与正文文件数一致。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        self.assertEqual(index_data["total_chapters"], 4)
        self.assertEqual(index_data["indexed_chapters"], 4)
        self.assertEqual(len(index_data["chapters"]), 4)

    def test_build_entities_extracted(self):
        """索引条目包含从摘要提取的实体列表。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        ch1 = next(c for c in index_data["chapters"] if c["chapter"] == 1)
        self.assertIn("林雷", ch1["entities"])
        self.assertIn("盘龙戒指", ch1["entities"])
        self.assertIn("沃尔夫商店", ch1["entities"])

    def test_build_emotion_tags_extracted(self):
        """索引条目包含从摘要提取的情绪标签。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        ch2 = next(c for c in index_data["chapters"] if c["chapter"] == 2)
        self.assertIn("紧张", ch2["emotion_tags"])
        self.assertIn("兴奋", ch2["emotion_tags"])

    def test_build_summary_extracted(self):
        """索引条目包含从摘要提取的摘要文本。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        ch2 = next(c for c in index_data["chapters"] if c["chapter"] == 2)
        self.assertIn("魔法学院", ch2["summary"])
        self.assertIn("火系魔法", ch2["summary"])

    def test_build_char_count(self):
        """索引条目包含正文字数统计（>0）。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        for ch in index_data["chapters"]:
            self.assertGreater(ch["char_count"], 0)

    def test_build_content_hash_present(self):
        """索引条目包含 content_hash 字段。"""
        cmd_build(self.book_root)
        index_data, _ = load_rag_index(self.book_root)
        for ch in index_data["chapters"]:
            self.assertIn("content_hash", ch)
            self.assertTrue(ch["content_hash"])

    def test_build_idempotent(self):
        """重复构建索引章节数一致。"""
        cmd_build(self.book_root)
        idx1, _ = load_rag_index(self.book_root)
        cmd_build(self.book_root)
        idx2, _ = load_rag_index(self.book_root)
        self.assertEqual(idx1["total_chapters"], idx2["total_chapters"])
        self.assertEqual(idx1["indexed_chapters"], idx2["indexed_chapters"])

    def test_build_incremental_skip(self):
        """增量构建时未变章节被跳过（返回 0 且章节数不变）。"""
        cmd_build(self.book_root)
        ret = cmd_build(self.book_root)
        self.assertEqual(ret, 0)
        index_data, _ = load_rag_index(self.book_root)
        self.assertEqual(len(index_data["chapters"]), 4)

    def test_build_no_chapters_returns_error(self):
        """正文目录无 .md 文件时返回错误码 2。"""
        empty_book = Path(self.tmpdir) / "empty_book"
        (empty_book / "正文").mkdir(parents=True)
        (empty_book / "追踪").mkdir(parents=True)
        ret = cmd_build(str(empty_book))
        self.assertEqual(ret, 2)

    def test_load_rag_index_missing_returns_none(self):
        """索引不存在时 load_rag_index 返回 (None, path)。"""
        loaded, path = load_rag_index(self.book_root)
        self.assertIsNone(loaded)

    def test_save_and_load_rag_index(self):
        """save_rag_index 写入后 load_rag_index 能读回。"""
        data = {"version": "1.0.0", "chapters": [], "total_chapters": 0}
        save_rag_index(self.book_root, data)
        loaded, _ = load_rag_index(self.book_root)
        self.assertEqual(loaded["version"], "1.0.0")


# ---------------------------------------------------------------------------
# rag_query（query）
# ---------------------------------------------------------------------------

class TestRagQuery(_BookFixture):
    """rag_query 相关章节检索测试。"""

    def setUp(self):
        """创建夹具并预先构建索引。"""
        super().setUp()
        cmd_build(self.book_root)

    def test_normal_query_returns_results(self):
        """全量检索返回相关章节列表。"""
        result = rag_query(self.book_root, "林雷魔法试炼", top_k=3)
        self.assertTrue(result["triggered"])
        self.assertIsInstance(result["results"], list)
        self.assertGreater(len(result["results"]), 0)
        # 第2章（含魔法试炼）应在结果中
        chapters = [r["chapter"] for r in result["results"]]
        self.assertIn(2, chapters)

    def test_query_result_structure(self):
        """检索结果条目包含完整字段。"""
        result = rag_query(self.book_root, "盘龙戒指", top_k=3)
        self.assertIn("query", result)
        self.assertIn("triggered", result)
        self.assertIn("cache_hit", result)
        self.assertIn("results", result)
        if result["results"]:
            r = result["results"][0]
            self.assertIn("chapter", r)
            self.assertIn("title", r)
            self.assertIn("score", r)
            self.assertIn("relevance", r)
            self.assertIn("snippet", r)

    def test_query_relevance_labels(self):
        """检索结果相关度标签合法（high/medium/low）。"""
        result = rag_query(self.book_root, "林雷", top_k=4)
        valid_labels = {"high", "medium", "low"}
        for r in result["results"]:
            self.assertIn(r["relevance"], valid_labels)

    def test_query_score_normalized(self):
        """检索得分归一化到 [0, 1] 区间。"""
        result = rag_query(self.book_root, "林雷", top_k=4)
        for r in result["results"]:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)

    def test_query_context_suggestion(self):
        """全量检索生成写前上下文建议文件。"""
        result = rag_query(self.book_root, "盘龙戒指秘密", top_k=3)
        ctx = result.get("context_suggestion")
        if ctx:
            self.assertIn("file", ctx)
            self.assertIn("top_chapters", ctx)
            ctx_path = os.path.join(self.book_root, "追踪", "next_plot_context.md")
            self.assertTrue(os.path.isfile(ctx_path))

    def test_light_scene_query(self):
        """含轻场景关键词的查询走快速匹配分支。"""
        result = rag_query(self.book_root, "林雷赶路", top_k=3)
        self.assertTrue(result["triggered"])
        self.assertTrue(result.get("light_mode"))

    def test_light_mode_explicit(self):
        """显式指定 light=True 走快速匹配。"""
        result = rag_query(self.book_root, "林雷", top_k=3, light=True)
        self.assertTrue(result.get("light_mode"))

    def test_light_mode_returns_entity_matches(self):
        """轻场景模式返回实体匹配结果。"""
        result = rag_query(self.book_root, "林雷", top_k=5, light=True)
        self.assertTrue(result["triggered"])
        # 林雷出现在第1、2、4章的实体中
        chapters = [r["chapter"] for r in result["results"]]
        self.assertIn(1, chapters)

    def test_no_index_returns_error(self):
        """索引不存在时返回错误信息。"""
        empty_book = Path(self.tmpdir) / "empty_book"
        (empty_book / "正文").mkdir(parents=True)
        (empty_book / "追踪").mkdir(parents=True)
        result = rag_query(str(empty_book), "林雷", top_k=3)
        self.assertFalse(result["triggered"])
        self.assertIn("error", result)

    def test_query_top_k_limit(self):
        """top_k 限制返回结果数量。"""
        result = rag_query(self.book_root, "林雷", top_k=2)
        self.assertLessEqual(len(result["results"]), 2)

    def test_query_no_match_returns_empty(self):
        """无匹配查询返回空结果但 triggered=True。"""
        result = rag_query(self.book_root, "zzznonexistent", top_k=3)
        self.assertTrue(result["triggered"])
        self.assertIsInstance(result["results"], list)

    def test_query_snippet_present(self):
        """检索结果包含正文片段（非空）。"""
        result = rag_query(self.book_root, "林雷盘龙戒指", top_k=3)
        for r in result["results"]:
            self.assertTrue(r.get("snippet"))


# ---------------------------------------------------------------------------
# is_light_scene
# ---------------------------------------------------------------------------

class TestIsLightScene(unittest.TestCase):
    """is_light_scene 轻场景关键词判定测试。"""

    def test_light_keywords(self):
        """含轻场景关键词返回 True。"""
        self.assertTrue(is_light_scene("赶路过场"))
        self.assertTrue(is_light_scene("日常对话"))
        self.assertTrue(is_light_scene("出发"))
        self.assertTrue(is_light_scene("夜宿客栈"))

    def test_non_light(self):
        """不含轻场景关键词返回 False。"""
        self.assertFalse(is_light_scene("林雷战斗"))
        self.assertFalse(is_light_scene("盘龙戒指秘密"))

    def test_empty_query(self):
        """空查询返回 False。"""
        self.assertFalse(is_light_scene(""))


# ---------------------------------------------------------------------------
# CLI 子进程测试
# ---------------------------------------------------------------------------

class TestCLI(_BookFixture):
    """CLI 子进程测试：build / query / status。"""

    def _run_cli(self, *args):
        """运行 rag_retriever.py 子进程，返回 CompletedProcess。"""
        cmd = [sys.executable, SCRIPT_PATH] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_cli_build(self):
        """CLI build 命令成功构建索引。"""
        result = self._run_cli("build", self.book_root)
        self.assertEqual(result.returncode, 0)
        idx_path = os.path.join(self.book_root, "追踪", "rag_index.json")
        self.assertTrue(os.path.isfile(idx_path))
        self.assertIn("RAG 索引已构建", result.stdout)

    def test_cli_build_no_chapters(self):
        """CLI build 无章节文件时返回错误码 2。"""
        empty_book = Path(self.tmpdir) / "empty_book"
        (empty_book / "正文").mkdir(parents=True)
        (empty_book / "追踪").mkdir(parents=True)
        result = self._run_cli("build", str(empty_book))
        self.assertEqual(result.returncode, 2)

    def test_cli_query(self):
        """CLI query 命令返回检索结果。"""
        # 先构建索引
        self._run_cli("build", self.book_root)
        result = self._run_cli("query", self.book_root, "林雷魔法试炼", "--top", "3")
        self.assertEqual(result.returncode, 0)
        self.assertIn("RAG 检索结果", result.stdout)

    def test_cli_query_light(self):
        """CLI query --light 命令走轻场景快速匹配分支。"""
        self._run_cli("build", self.book_root)
        result = self._run_cli("query", self.book_root, "林雷", "--light")
        self.assertEqual(result.returncode, 0)
        self.assertIn("轻场景", result.stdout)

    def test_cli_status(self):
        """CLI status 命令输出索引状态信息。"""
        self._run_cli("build", self.book_root)
        result = self._run_cli("status", self.book_root)
        self.assertEqual(result.returncode, 0)
        self.assertIn("RAG 检索器状态", result.stdout)
        self.assertIn("索引版本", result.stdout)
        self.assertIn("覆盖率", result.stdout)

    def test_cli_status_no_index(self):
        """CLI status 无索引时正常输出未构建状态。"""
        result = self._run_cli("status", self.book_root)
        self.assertEqual(result.returncode, 0)
        self.assertIn("未构建", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
