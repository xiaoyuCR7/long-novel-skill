#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_story_graph.py — 测试 story_graph.py 知识图谱核心功能。

覆盖：角色节点提取、实体节点与边提取、图谱构建、级联标记、
      Mermaid 导出、备份、CLI 子命令（build / extract / cascade）。

运行方式：
    python scripts/tests/test_story_graph.py
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
