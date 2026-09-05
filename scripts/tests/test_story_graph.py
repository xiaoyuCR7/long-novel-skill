#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_story_graph.py — 测试 story_graph.py 知识图谱核心功能。

覆盖：角色节点提取、实体节点与边提取、图谱构建、级联标记、
      Mermaid 导出、备份、CLI 子命令（build / extract / cascade）。

运行方式：
    python scripts/tests/test_story_graph.py
"""

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_graph
from story_graph import (
    CHARACTER_STATE_FILE,
    CHAPTER_SUMMARY_FILE,
    EDGE_TYPES,
    ENTITY_INDEX_FILE,
    GRAPH_FILE,
    VERSION,
    backup_graph,
    build_graph,
    cascade_mark,
    export_mermaid,
    extract_character_nodes,
    extract_entity_nodes,
    load_json,
    save_json,
    update_chapter,
)


# =========================================================
# 测试基类
# =========================================================

class _BaseGraphTest(unittest.TestCase):
    """基类：提供临时书籍目录与文件写入辅助。"""

    def setUp(self):
        """每个测试创建独立的临时目录，测试结束自动清理。"""
        self.book_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.book_root, ignore_errors=True)

    # ---- 文件写入辅助 ----

    def _write(self, rel_path, content):
        """写入文本文件到 book_root 下的相对路径，自动创建父目录。"""
        path = self.book_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_json(self, rel_path, data):
        """写入 JSON 文件到 book_root 下的相对路径。"""
        path = self.book_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 路径辅助 ----

    def _graph_path(self):
        """返回图谱文件路径。"""
        return self.book_root / "追踪" / GRAPH_FILE

    def _build_and_save(self):
        """构建图谱并保存到磁盘，返回图谱字典。"""
        graph = build_graph(self.book_root)
        save_json(self._graph_path(), graph)
        return graph


# =========================================================
# 角色节点提取
# =========================================================

class TestExtractCharacterNodes(_BaseGraphTest):
    """extract_character_nodes：从角色状态文件提取角色节点。"""

    def test_extract_two_characters(self):
        """正常解析两个角色段落，返回两个结构正确的节点。"""
        self._write(
            f"追踪/{CHARACTER_STATE_FILE}",
            "# 角色状态\n\n"
            "## 林雷\n状态：修炼中\n境界：七级战士\n\n"
            "## 贝贝\n状态：沉睡进化\n身份：神兽貔貅\n",
        )
        nodes = extract_character_nodes(self.book_root)
        self.assertEqual(len(nodes), 2)

        labels = {n["label"] for n in nodes}
        self.assertEqual(labels, {"林雷", "贝贝"})

        for n in nodes:
            self.assertEqual(n["type"], "character")
            self.assertTrue(n["id"].startswith("char_"))
            self.assertFalse(n["cascade_pending"])
            self.assertIn("status_snippet", n["props"])

    def test_missing_file_returns_empty(self):
        """角色状态文件不存在时返回空列表。"""
        nodes = extract_character_nodes(self.book_root)
        self.assertEqual(nodes, [])


# =========================================================
# 实体节点与边提取
# =========================================================

class TestExtractEntityNodes(_BaseGraphTest):
    """extract_entity_nodes：从 entity_index.json 或章节摘要提取实体。"""

    def test_extract_from_entity_index(self):
        """从 entity_index.json 提取实体节点，类型与章节信息正确。"""
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "寒霜剑": {"type": "item", "chapters": [1, 3]},
                "龙巢": {"type": "location", "chapters": [1, 2]},
                "黑龙帮": {"type": "faction", "chapters": [2, 3]},
            },
            "chapter_entities": {},
        })
        nodes, edges = extract_entity_nodes(self.book_root)

        node_map = {n["label"]: n for n in nodes}
        self.assertIn("寒霜剑", node_map)
        self.assertEqual(node_map["寒霜剑"]["type"], "item")
        self.assertEqual(node_map["寒霜剑"]["first_appear_chapter"], 1)
        self.assertEqual(node_map["寒霜剑"]["last_updated_chapter"], 3)

        self.assertEqual(node_map["龙巢"]["type"], "location")
        self.assertEqual(node_map["黑龙帮"]["type"], "faction")

    def test_fallback_to_summaries(self):
        """无 entity_index.json 时回退到章节摘要提取实体。"""
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n"
            "### 第1章\n"
            "- **关键实体**: item:寒霜剑, location:龙巢\n",
        )
        nodes, edges = extract_entity_nodes(self.book_root)

        node_map = {n["label"]: n for n in nodes}
        self.assertIn("寒霜剑", node_map)
        self.assertEqual(node_map["寒霜剑"]["type"], "item")
        self.assertIn("龙巢", node_map)
        self.assertEqual(node_map["龙巢"]["type"], "location")

    def test_accepts_flat_entity_index_schema(self):
        """实体派生索引的实际 flat {实体:[章号]} schema 也可构图。"""
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {"月蚀契约": [2, 5]})
        nodes, _ = extract_entity_nodes(self.book_root)
        node = next(n for n in nodes if n["label"] == "月蚀契约")
        self.assertEqual(node["first_appear_chapter"], 2)
        self.assertEqual(node["last_updated_chapter"], 5)

    def test_formal_template_accepts_plain_key_entity_line(self):
        """图谱从正式模板的 `- 关键实体：` 行派生实体。"""
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "### 第1章\n- 发生了什么：林雷杀死贝贝。\n"
            "- 状态变化：林雷负伤。\n- 伏笔进出：埋入追杀。\n"
            "- 新登场：无。\n- 关键实体：character:林雷、character:贝贝。\n"
            "- 承上：无。\n- 启下：逃亡。\n",
        )
        nodes, edges = extract_entity_nodes(self.book_root)
        self.assertEqual({n["label"] for n in nodes}, {"林雷", "贝贝"})
        self.assertEqual(edges[0]["type"], "kills")

    def test_save_json_propagates_atomic_replace_failure(self):
        """图谱 JSON 原子替换失败需要传播给调用者。"""
        with patch("common.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_json(self._graph_path(), {"nodes": []})

    def test_update_chapter_reads_formal_plain_key_entity_line(self):
        """增量图谱更新也读取正式模板的普通关键实体行。"""
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "### 第2章\n- 发生了什么：林雷找到月蚀契约。\n"
            "- 状态变化：林雷决定追查。\n- 伏笔进出：埋入印记。\n"
            "- 新登场：无。\n- 关键实体：character:林雷、item:月蚀契约。\n"
            "- 承上：失钥。\n- 启下：北港。\n",
        )
        save_json(self._graph_path(), {"nodes": [], "edges": [], "stats": {}})
        result = update_chapter(self.book_root, 2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["added_nodes"], 2)

    def test_extract_edges_from_summaries(self):
        """从章节摘要的关系语句中提取边。"""
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "林雷": {"type": "character", "chapters": [1]},
                "贝贝": {"type": "character", "chapters": [1]},
            },
        })
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n"
            "### 第1章\n"
            "林雷杀死贝贝\n",
        )
        nodes, edges = extract_entity_nodes(self.book_root)

        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge["type"], "kills")
        self.assertEqual(edge["label"], EDGE_TYPES["kills"])
        self.assertEqual(edge["source"], "character_林雷")
        self.assertEqual(edge["target"], "character_贝贝")
        self.assertEqual(edge["chapter"], 1)

    def test_missing_files_returns_empty(self):
        """无任何实体文件时返回空节点和空边。"""
        nodes, edges = extract_entity_nodes(self.book_root)
        self.assertEqual(nodes, [])
        self.assertEqual(edges, [])


# =========================================================
# 图谱构建
# =========================================================

class TestBuildGraph(_BaseGraphTest):
    """build_graph：构建完整知识图谱。"""

    def setUp(self):
        super().setUp()
        self._write(
            f"追踪/{CHARACTER_STATE_FILE}",
            "# 角色状态\n\n"
            "## 林雷\n状态：修炼中\n\n"
            "## 贝贝\n状态：沉睡\n",
        )
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "寒霜剑": {"type": "item", "chapters": [1, 3]},
                "龙巢": {"type": "location", "chapters": [1, 2]},
            },
        })
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n### 第1章\n- **关键实体**: 寒霜剑\n",
        )

    def test_build_graph_structure(self):
        """构建图谱：版本、统计、节点、边字段齐全。"""
        graph = build_graph(self.book_root)

        self.assertEqual(graph["version"], VERSION)
        self.assertIn("updated_at", graph)
        self.assertIn("stats", graph)
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)

        # 2 角色 + 2 实体 = 4 节点
        self.assertEqual(graph["stats"]["total_nodes"], 4)
        self.assertEqual(graph["stats"]["total_edges"], 0)

        node_types = graph["stats"]["node_types"]
        self.assertEqual(node_types.get("character"), 2)
        self.assertEqual(node_types.get("item"), 1)
        self.assertEqual(node_types.get("location"), 1)

    def test_build_graph_from_scratch(self):
        """from_scratch=True 时忽略已有图谱，重新构建。"""
        # 先保存一个假图谱
        save_json(self._graph_path(), {"version": "0.0.0", "nodes": [], "edges": []})

        graph = build_graph(self.book_root, from_scratch=True)
        self.assertEqual(graph["version"], VERSION)
        self.assertEqual(graph["stats"]["total_nodes"], 4)

    def test_build_graph_with_edges(self):
        """构建图谱时从章节摘要提取关系边。"""
        # 覆盖实体索引与摘要，加入能产生边的内容
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "张三": {"type": "character", "chapters": [1]},
                "李四": {"type": "character", "chapters": [1]},
            },
        })
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n### 第1章\n张三杀死李四\n",
        )
        graph = build_graph(self.book_root)

        self.assertGreater(len(graph["edges"]), 0)
        edge = graph["edges"][0]
        self.assertEqual(edge["type"], "kills")
        self.assertEqual(edge["source"], "character_张三")
        self.assertEqual(edge["target"], "character_李四")

    def test_build_graph_empty(self):
        """无任何源文件时构建空图谱。"""
        empty_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty_root, ignore_errors=True)

        graph = build_graph(empty_root)
        self.assertEqual(graph["stats"]["total_nodes"], 0)
        self.assertEqual(graph["stats"]["total_edges"], 0)
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["edges"], [])


# =========================================================
# 级联标记
# =========================================================

class TestCascadeMark(_BaseGraphTest):
    """cascade_mark：改纲后标记受影响节点。"""

    def setUp(self):
        super().setUp()
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "寒霜剑": {"type": "item", "chapters": [1, 3]},
                "龙巢": {"type": "location", "chapters": [2]},
                "黑龙帮": {"type": "faction", "chapters": [3]},
            },
        })
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n### 第1章\n- **关键实体**: 寒霜剑\n",
        )
        self._build_and_save()

    def test_cascade_marks_affected_nodes(self):
        """last_updated_chapter >= from_chapter 的节点被标记。"""
        result = cascade_mark(self.book_root, from_chapter=3,
                              change_description="改主线")
        self.assertTrue(result["ok"])

        affected_ids = {n["id"] for n in result["affected_nodes"]}
        # 寒霜剑(3) 和 黑龙帮(3) 被标记，龙巢(2) 不被标记
        self.assertIn("item_寒霜剑", affected_ids)
        self.assertIn("faction_黑龙帮", affected_ids)
        self.assertNotIn("location_龙巢", affected_ids)
        self.assertEqual(len(affected_ids), 2)

    def test_cascade_writes_pending_flag(self):
        """被标记节点的 cascade_pending 写入磁盘为 True。"""
        cascade_mark(self.book_root, from_chapter=2)

        graph = load_json(self._graph_path())
        pending = [n for n in graph["nodes"] if n.get("cascade_pending")]
        # from_chapter=2: 寒霜剑(3), 龙巢(2), 黑龙帮(3) 全部 >= 2
        self.assertEqual(len(pending), 3)

    def test_cascade_creates_backup(self):
        """级联标记前自动创建备份文件。"""
        cascade_mark(self.book_root, from_chapter=2)

        backups = list(self.book_root.glob("追踪/*.bak.json"))
        self.assertEqual(len(backups), 1)
        # 备份内容应与原文件一致
        original = load_json(self._graph_path())
        backup = json.loads(backups[0].read_text(encoding="utf-8"))
        # 备份是级联前的状态，节点数应一致
        self.assertEqual(
            len(backup.get("nodes", [])),
            len(original.get("nodes", [])),
        )

    def test_cascade_no_graph(self):
        """图谱不存在时返回错误。"""
        empty_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty_root, ignore_errors=True)

        result = cascade_mark(empty_root, from_chapter=1)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


# =========================================================
# Mermaid 导出
# =========================================================

class TestExportMermaid(_BaseGraphTest):
    """export_mermaid：导出图谱为 Mermaid 格式。"""

    def setUp(self):
        super().setUp()
        self._write(f"追踪/{CHARACTER_STATE_FILE}", "## 林雷\n状态：修炼\n")
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "林雷": {"type": "character", "chapters": [1]},
                "贝贝": {"type": "character", "chapters": [1]},
            },
        })
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n### 第1章\n林雷杀死贝贝\n",
        )
        self._build_and_save()

    def test_export_returns_mermaid_text(self):
        """导出返回 Mermaid 文本，包含 graph TD 头、节点标签和边箭头。"""
        text = export_mermaid(self.book_root)

        self.assertTrue(text.startswith("graph TD"))
        self.assertIn("林雷", text)
        self.assertIn("贝贝", text)
        # 应包含边（--> 箭头）
        self.assertIn("-->", text)

    def test_export_no_graph(self):
        """图谱不存在时返回占位文本。"""
        empty_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty_root, ignore_errors=True)

        text = export_mermaid(empty_root)
        self.assertIn("graph TD", text)
        self.assertIn("图谱不存在", text)

    def test_export_to_file(self):
        """导出到文件，文件内容与返回值一致。"""
        out = self.book_root / "graph.mmd"
        text = export_mermaid(self.book_root, output_path=out)

        self.assertTrue(out.exists())
        self.assertEqual(out.read_text(encoding="utf-8"), text)


# =========================================================
# 备份
# =========================================================

class TestBackupGraph(_BaseGraphTest):
    """backup_graph：备份图谱文件。"""

    def test_backup_existing_file(self):
        """备份已存在的文件，返回备份路径且内容一致。"""
        original = self.book_root / "story_graph.json"
        original.write_text('{"version": "1.0"}', encoding="utf-8")

        backup = backup_graph(original)
        self.assertIsNotNone(backup)
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), original.read_bytes())
        self.assertIn(".bak.json", backup.name)

    def test_backup_nonexistent_file(self):
        """文件不存在时返回 None。"""
        path = self.book_root / "nonexistent.json"
        result = backup_graph(path)
        self.assertIsNone(result)


class TestAssertionEvidence(_BaseGraphTest):
    """词面命中仅生成可复核候选，不能证明故事事实。"""

    def setUp(self):
        super().setUp()
        for name in ("林辰", "苏明", "沈宁"):
            self._write(f"设定/角色/{name}.md", f"# {name}\n")

    def _extract(self, text):
        self._write("正文/第001章_测试.md", text)
        return story_graph.extract_from_chapter(self.book_root, 1)

    def test_declarative_candidate_has_exact_source_evidence(self):
        text = "# 第1章\n\n林辰杀死苏明。\n"
        result = self._extract(text)
        self.assertEqual(len(result["new_edges"]), 1)
        edge = result["new_edges"][0]
        self.assertEqual(edge.get("status"), "unconfirmed")
        self.assertTrue(edge.get("semantic_review_required"))
        self.assertEqual(edge["assertion_kind"], "declarative")
        evidence = edge["evidence"]
        self.assertEqual(evidence["chapter"], 1)
        self.assertEqual(evidence["source_path"], "正文/第001章_测试.md")
        self.assertEqual(evidence["source_hash"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(text[slice(*evidence["span"])], evidence["text"])
        self.assertEqual(text[slice(*evidence["match_span"])], "林辰杀死苏明")

    def test_question_hypothesis_negation_and_quoted_claim_stay_unconfirmed(self):
        cases = [
            ('他问：“林辰杀苏明？”', "question"),
            ("如果林辰杀死苏明，沈宁就会追查。", "hypothetical"),
            ("林辰没有杀死苏明。", "negated"),
            ('沈宁说：“林辰杀死苏明。”', "quoted_claim"),
            ("听说林辰杀死苏明。", "quoted_claim"),
        ]
        for text, kind in cases:
            with self.subTest(text=text):
                edges = self._extract(text)["new_edges"]
                self.assertEqual(len(edges), 1)
                edge = edges[0]
                self.assertEqual(edge["source_label"], "林辰")
                self.assertEqual(edge["target_label"], "苏明")
                self.assertEqual(edge.get("assertion_kind"), kind)
                self.assertEqual(edge.get("status"), "unconfirmed")
                self.assertTrue(edge.get("semantic_review_required"))

    def test_longer_names_and_unknown_aliases_do_not_become_known_entities(self):
        self._write("设定/角色/林辰天.md", "# 林辰天\n")
        result = self._extract("林辰天杀死苏明。")
        self.assertEqual(result["characters_found"], ["林辰天", "苏明"])
        self.assertEqual(result["new_edges"][0]["source_label"], "林辰天")
        self.assertEqual(self._extract("林辰杀死苏明月。小辰杀死苏明。")["new_edges"], [])

    def test_role_change_requires_current_known_name_not_invented_alias(self):
        result = self._extract("沈宁杀死苏明。")
        self.assertEqual(result["new_edges"][0]["source_label"], "沈宁")
        self.assertEqual(self._extract("阿宁杀死苏明。")["new_edges"], [])

    def test_no_ownership_inference_from_giving_or_accompanying_people(self):
        result = self._extract("林辰带着苏明。林辰给苏明。")
        self.assertEqual(result["new_edges"], [])

    def test_repeated_mentions_keep_distinct_support_and_context(self):
        result = self._extract('林辰杀死苏明。他问：“林辰杀死苏明？”')
        self.assertEqual([e.get("assertion_kind") for e in result["new_edges"]],
                         ["declarative", "question"])

    def test_extract_update_preserves_node_identity_and_replaces_old_source(self):
        self._write_json(f"追踪/{GRAPH_FILE}", {
            "nodes": [{"id": "character_林辰", "label": "林辰", "type": "character", "props": {"note": "保留"}}],
            "edges": [],
        })
        self._extract("林辰杀死苏明。")
        first = story_graph.extract_and_update(self.book_root, 1)
        self.assertTrue(first["ok"])
        graph = load_json(self._graph_path())
        self.assertEqual(len([n for n in graph["nodes"] if n["label"] == "林辰"]), 1)
        self.assertEqual(graph["edges"][0]["source"], "character_林辰")
        old_hash = graph["edges"][0]["evidence"]["source_hash"]
        repeat = story_graph.extract_and_update(self.book_root, 1)
        self.assertEqual(repeat["added_nodes"], 0)
        self.assertEqual(repeat["added_edges"], 0)
        self._extract("沈宁杀死苏明。")
        story_graph.extract_and_update(self.book_root, 1)
        graph = load_json(self._graph_path())
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["source"], "char_沈宁")
        self.assertNotEqual(graph["edges"][0]["evidence"]["source_hash"], old_hash)
        self._extract("沈宁望着窗外。")
        story_graph.extract_and_update(self.book_root, 1)
        self.assertEqual(load_json(self._graph_path())["edges"], [])

    def test_query_marks_changed_or_missing_source_stale_without_writing(self):
        self._write_json(f"追踪/{GRAPH_FILE}", {"nodes": [], "edges": []})
        self._extract("林辰杀死苏明。")
        story_graph.extract_and_update(self.book_root, 1)
        graph_bytes = self._graph_path().read_bytes()
        self._extract("林辰没有杀死苏明。")
        edge = story_graph.query_graph(self.book_root, "林辰")["edges"][0]
        self.assertEqual(edge.get("status"), "stale")
        self.assertTrue(edge.get("semantic_review_required"))
        self.assertIn("来源已变更", export_mermaid(self.book_root))
        (self.book_root / "正文/第001章_测试.md").unlink()
        self.assertEqual(story_graph.query_graph(self.book_root, "林辰")["edges"][0]["status"], "stale")
        self.assertEqual(self._graph_path().read_bytes(), graph_bytes)

    def test_legacy_semantic_edges_are_readable_but_unconfirmed(self):
        graph = {"nodes": [
            {"id": "a", "label": "林辰", "type": "character"},
            {"id": "b", "label": "苏明", "type": "character"},
        ], "edges": [{"source": "a", "target": "b", "type": "kills", "label": "杀死", "chapter": 1, "props": {}}]}
        self._write_json(f"追踪/{GRAPH_FILE}", graph)
        result = story_graph.query_graph(self.book_root, "林辰")
        self.assertEqual(result["edges"][0].get("status"), "legacy_unconfirmed")
        self.assertTrue(result["edges"][0].get("semantic_review_required"))
        self.assertIn("未确认", export_mermaid(self.book_root))
        self.assertIn("杀死", export_mermaid(self.book_root))
        self.assertEqual(load_json(self._graph_path()), graph)

    def test_summary_build_and_update_share_evidence_rules(self):
        source = "### 第1章\n- 发生了什么：如果林辰杀死苏明，沈宁就会追查。\n- 关键实体：character:林辰、character:苏明。\n"
        self._write(f"追踪/{CHAPTER_SUMMARY_FILE}", source)
        graph = self._build_and_save()
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0].get("assertion_kind"), "hypothetical")
        evidence = graph["edges"][0]["evidence"]
        self.assertEqual(source[slice(*evidence["span"])], evidence["text"])
        self.assertEqual(update_chapter(self.book_root, 1)["added_edges"], 0)
        self._write(f"追踪/{CHAPTER_SUMMARY_FILE}", source.replace("如果林辰杀死苏明，沈宁就会追查", "林辰没有杀死苏明"))
        update_chapter(self.book_root, 1)
        graph = load_json(self._graph_path())
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["assertion_kind"], "negated")

    def test_each_chapter_keeps_its_own_evidence(self):
        self._write_json(f"追踪/{GRAPH_FILE}", {"nodes": [], "edges": []})
        self._extract("林辰杀死苏明。")
        self._write("正文/第002章_测试.md", "林辰杀死苏明。")
        story_graph.extract_and_update(self.book_root, 1)
        story_graph.extract_and_update(self.book_root, 2)
        self.assertEqual({e["chapter"] for e in load_json(self._graph_path())["edges"]}, {1, 2})

    def test_reextraction_keeps_unattributed_legacy_and_structural_edges(self):
        legacy = {"source": "a", "target": "b", "type": "kills", "label": "杀死", "chapter": 1}
        structural = {"source": "a", "target": "b", "type": "appears_in", "label": "出现于", "chapter": 1}
        self._write_json(f"追踪/{GRAPH_FILE}", {
            "nodes": [{"id": "a", "label": "林辰", "type": "character"},
                      {"id": "b", "label": "苏明", "type": "character"}],
            "edges": [legacy, structural],
        })
        self._extract("林辰站在门外。")
        story_graph.extract_and_update(self.book_root, 1)
        self.assertEqual(load_json(self._graph_path())["edges"], [legacy, structural])
        result = story_graph.query_graph(self.book_root, "林辰")
        self.assertEqual([e["status"] for e in result["edges"]], ["legacy_unconfirmed", "structural"])

    def test_existing_duplicate_labels_do_not_leave_dangling_legacy_edges(self):
        self._write_json(f"追踪/{GRAPH_FILE}", {
            "nodes": [{"id": "char_林辰", "label": "林辰", "type": "character"},
                      {"id": "character_林辰", "label": "林辰", "type": "character"},
                      {"id": "b", "label": "苏明", "type": "character"}],
            "edges": [{"source": "char_林辰", "target": "b", "type": "kills", "label": "杀死", "chapter": 1}],
        })
        self._extract("林辰站在门外。")
        story_graph.extract_and_update(self.book_root, 1)
        graph = load_json(self._graph_path())
        ids = {n["id"] for n in graph["nodes"]}
        self.assertTrue(all(e["source"] in ids and e["target"] in ids for e in graph["edges"]))

    def test_query_depth_two_reaches_second_hop(self):
        self._write_json(f"追踪/{GRAPH_FILE}", {
            "nodes": [{"id": n, "label": n, "type": "character"} for n in ("林辰", "苏明", "沈宁")],
            "edges": [{"source": "林辰", "target": "苏明", "type": "kills", "label": "杀死"},
                      {"source": "苏明", "target": "沈宁", "type": "hates", "label": "仇恨"}],
        })
        result = story_graph.query_graph(self.book_root, "林辰", depth=2)
        self.assertEqual({n["label"] for n in result["nodes"]}, {"林辰", "苏明", "沈宁"})
        self.assertEqual(len(result["edges"]), 2)

    def test_revision_impact_separates_source_mentions_from_possible_dependents(self):
        self._write_json(f"追踪/{GRAPH_FILE}", {
            "nodes": [{"id": n, "label": n, "type": "character"} for n in ("林辰", "苏明", "沈宁")],
            "edges": [
                {"source": "林辰", "target": "苏明", "type": "kills", "label": "杀死", "chapter": 2},
                {"source": "苏明", "target": "沈宁", "type": "hates", "label": "仇恨", "chapter": 3},
            ],
        })
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {"林辰": [1, 5], "沈宁": [7]})
        self._extract("林辰独自站在门前。")
        before = {p.relative_to(self.book_root): p.read_bytes() for p in self.book_root.rglob("*") if p.is_file()}
        result = story_graph.impact_analysis(self.book_root, "林辰", chapter=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["definite_entities"], ["林辰"])
        self.assertEqual(result["definite_chapters"], [1])
        self.assertEqual(set(result["possible_entities"]), {"苏明", "沈宁"})
        self.assertEqual(set(result["possible_chapters"]), {2, 3, 5, 7})
        self.assertTrue(result["semantic_review_required"])
        self.assertTrue(result["read_only"])
        self.assertTrue(result["references"])
        after = {p.relative_to(self.book_root): p.read_bytes() for p in self.book_root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


# =========================================================
# CLI 子命令
# =========================================================

class TestCLI(_BaseGraphTest):
    """CLI 子命令：build / extract / cascade。"""

    def _run_cli(self, *args):
        """运行 story_graph.py 子命令，返回 CompletedProcess。"""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "story_graph.py"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_cli_build(self):
        """build 子命令构建图谱并写入磁盘。"""
        self._write(f"追踪/{CHARACTER_STATE_FILE}", "## 林雷\n状态：修炼\n")
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {"寒霜剑": {"type": "item", "chapters": [1]}},
        })

        result = self._run_cli("build", str(self.book_root))
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertTrue(output["ok"])
        self.assertIn("stats", output)
        self.assertTrue(self._graph_path().exists())

    def test_cli_cascade(self):
        """cascade 子命令标记受影响节点。"""
        self._write_json(f"追踪/{ENTITY_INDEX_FILE}", {
            "entities": {
                "寒霜剑": {"type": "item", "chapters": [1, 3]},
                "龙巢": {"type": "location", "chapters": [2]},
            },
        })
        self._write(
            f"追踪/{CHAPTER_SUMMARY_FILE}",
            "# 章节摘要\n\n### 第1章\n- **关键实体**: 寒霜剑\n",
        )

        # 先 build
        build_result = self._run_cli("build", str(self.book_root))
        self.assertEqual(build_result.returncode, 0, build_result.stderr)

        # 再 cascade
        result = self._run_cli(
            "cascade", str(self.book_root),
            "--from-chapter", "3", "--desc", "改纲测试",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertTrue(output["ok"])
        # 寒霜剑 last_updated=3 >= 3 → 被标记
        self.assertGreaterEqual(len(output["affected_nodes"]), 1)

    def test_cli_extract(self):
        """extract 子命令从正文章节提取实体和关系。"""
        self._write("设定/角色/林雷.md", "# 林雷")
        self._write("设定/角色/贝贝.md", "# 贝贝")
        self._write("设定/世界观.md", "# 世界观\n\n地点：龙巢\n")
        self._write("正文/第001章_待写.md", "林雷杀死贝贝。林雷前往龙巢。")

        result = self._run_cli(
            "extract", str(self.book_root), "--chapter", "1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertEqual(output["chapter"], 1)
        self.assertIn("林雷", output["characters_found"])
        self.assertIn("贝贝", output["characters_found"])
        self.assertIn("龙巢", output["locations_found"])
        self.assertGreater(len(output["new_edges"]), 0)

        # 验证 kills 边被提取
        kill_edges = [e for e in output["new_edges"] if e["type"] == "kills"]
        self.assertEqual(len(kill_edges), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
