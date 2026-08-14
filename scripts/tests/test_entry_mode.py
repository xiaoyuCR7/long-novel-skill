#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_entry_mode.py — entry_mode.py 单元测试（纯标准库）。

覆盖：
  - normalize_mode / normalize_persona
  - parse_rhythm_quota
  - recommend_entry_mode
  - recommend_persona
  - check_rotation
  - record_entry
  - CLI 子命令

用法：
    python scripts/tests/test_entry_mode.py
    python -m unittest scripts.tests.test_entry_mode
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

# 把 scripts 目录加入 sys.path
_SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SCRIPT_DIR.parent

for p in (str(_SCRIPTS_DIR), str(_SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from entry_mode import (
    ENTRY_MODES,
    PERSONAS,
    COMPATIBILITY,
    normalize_mode,
    normalize_persona,
    get_mode_display,
    get_persona_display,
    parse_rhythm_quota,
    find_quota_path,
    recommend_entry_mode,
    recommend_persona,
    check_rotation,
    record_entry,
)


class TestNormalizeMode(unittest.TestCase):
    """测试入口模式规范化。"""

    def test_normalize_by_code(self):
        """code 应直接匹配。"""
        self.assertEqual(normalize_mode("scene"), "scene")
        self.assertEqual(normalize_mode("action"), "action")
        self.assertEqual(normalize_mode("rhythm"), "rhythm")

    def test_normalize_by_name(self):
        """中文名应匹配。"""
        self.assertEqual(normalize_mode("场景切入"), "scene")
        self.assertEqual(normalize_mode("对话切入"), "dialogue")
        self.assertEqual(normalize_mode("动作切入"), "action")

    def test_normalize_by_alias(self):
        """别名应匹配。"""
        self.assertEqual(normalize_mode("场景"), "scene")
        self.assertEqual(normalize_mode("对话"), "dialogue")
        self.assertEqual(normalize_mode("动作"), "action")

    def test_normalize_by_english(self):
        """英文名应匹配。"""
        self.assertEqual(normalize_mode("Scene"), "scene")
        self.assertEqual(normalize_mode("Action"), "action")

    def test_normalize_partial_match(self):
        """包含关键词应匹配。"""
        self.assertEqual(normalize_mode("用场景切入开篇"), "scene")

    def test_normalize_invalid(self):
        """无效输入返回 None。"""
        self.assertIsNone(normalize_mode("不存在的模式"))
        self.assertIsNone(normalize_mode(""))
        self.assertIsNone(normalize_mode(None))


class TestNormalizePersona(unittest.TestCase):
    """测试人格规范化。"""

    def test_normalize_by_code(self):
        self.assertEqual(normalize_persona("blade"), "blade")
        self.assertEqual(normalize_persona("fire"), "fire")
        self.assertEqual(normalize_persona("witness"), "witness")

    def test_normalize_by_name(self):
        self.assertEqual(normalize_persona("冷峻派"), "blade")
        self.assertEqual(normalize_persona("热血派"), "fire")
        self.assertEqual(normalize_persona("旁观派"), "witness")

    def test_normalize_by_alias(self):
        self.assertEqual(normalize_persona("冷峻"), "blade")
        self.assertEqual(normalize_persona("热血"), "fire")
        self.assertEqual(normalize_persona("旁观"), "witness")

    def test_normalize_by_english(self):
        self.assertEqual(normalize_persona("The Blade"), "blade")
        self.assertEqual(normalize_persona("The Fire"), "fire")

    def test_normalize_invalid(self):
        self.assertIsNone(normalize_persona("不存在"))
        self.assertIsNone(normalize_persona(""))
        self.assertIsNone(normalize_persona(None))


class TestParseRhythmQuota(unittest.TestCase):
    """测试节奏配额文件解析。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_em_parse_"))
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def _write_quota(self, content):
        book_dir = self.tmpdir / "测试书"
        tracking = book_dir / "追踪"
        tracking.mkdir(parents=True)
        quota = tracking / "节奏配额.md"
        quota.write_text(content, encoding="utf-8")
        return quota

    def test_parse_empty_file(self):
        """空文件应返回空记录。"""
        quota = self._write_quota("")
        result = parse_rhythm_quota(quota)
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["gears"], [])

    def test_parse_with_entry_mode(self):
        """应正确解析含入口模式的表格。"""
        content = """\
# 节奏配额

## 入口模式与人格记录

| 章节 | 入口模式 | 人格 | 档位 |
|---|---|---|---|
| 第1章 | 场景切入 | 旁观派 | 中 |
| 第2章 | 对话切入 | 热血派 | 快 |
| 第3章 | 动作切入 | 冷峻派 | 快 |
"""
        quota = self._write_quota(content)
        result = parse_rhythm_quota(quota)
        self.assertEqual(len(result["entries"]), 3)
        self.assertEqual(result["entries"][0], (1, "scene", "witness"))
        self.assertEqual(result["entries"][1], (2, "dialogue", "fire"))
        self.assertEqual(result["entries"][2], (3, "action", "blade"))
        self.assertEqual(len(result["gears"]), 3)

    def test_parse_without_entry_mode(self):
        """无入口模式列的旧格式应正确解析档位。"""
        content = """\
| 章节 | 档位 | 类型 |
|---|---|---|
| 第1章 | A | 开篇高潮 |
| 第2章 | B | 冲突升级 |
"""
        quota = self._write_quota(content)
        result = parse_rhythm_quota(quota)
        # A/B/C 不是快/慢/中，所以 gear 为空
        # 但章节号应被提取
        self.assertEqual(len(result["entries"]), 2)

    def test_parse_dedup(self):
        """同一章节重复记录应去重，保留最后一条。"""
        content = """\
| 章节 | 入口模式 | 人格 |
|---|---|---|
| 第1章 | 场景切入 | 旁观派 |
| 第1章 | 对话切入 | 热血派 |
"""
        quota = self._write_quota(content)
        result = parse_rhythm_quota(quota)
        self.assertEqual(len(result["entries"]), 1)
        # 保留最后一条
        self.assertEqual(result["entries"][0], (1, "dialogue", "fire"))


class TestRecommendEntryMode(unittest.TestCase):
    """测试入口模式推荐。"""

    def test_recommend_empty_history(self):
        """无历史记录时应推荐所有模式。"""
        history = {"entries": [], "gears": []}
        results, next_chap = recommend_entry_mode(history, "快")
        self.assertEqual(next_chap, 1)
        self.assertEqual(len(results), 8)
        # 快档首选应为 action
        self.assertEqual(results[0][0], "action")

    def test_recommend_avoids_last_mode(self):
        """上一章使用的模式应在推荐中排到最后。"""
        history = {
            "entries": [(1, "action", None)],
            "gears": [],
        }
        results, next_chap = recommend_entry_mode(history, "快")
        self.assertEqual(next_chap, 2)
        # action 应排最后（分数最低）
        self.assertEqual(results[-1][0], "action")
        self.assertLess(results[-1][2], 0)  # 负分

    def test_recommend_gear_priority(self):
        """不同档位应有不同优先级。"""
        history = {"entries": [], "gears": []}
        results_fast, _ = recommend_entry_mode(history, "快")
        results_slow, _ = recommend_entry_mode(history, "慢")
        # 快档首选 action，慢档首选 scene
        self.assertEqual(results_fast[0][0], "action")
        self.assertEqual(results_slow[0][0], "scene")

    def test_recommend_recent_window(self):
        """近3章使用过的模式应降分。"""
        history = {
            "entries": [
                (1, "action", None),
                (2, "dialogue", None),
                (3, "sensory", None),
            ],
            "gears": [],
        }
        results, next_chap = recommend_entry_mode(history, "中")
        self.assertEqual(next_chap, 4)
        # 这三个模式不应在推荐前3名
        top3_codes = [r[0] for r in results[:3]]
        self.assertNotIn("action", top3_codes)
        self.assertNotIn("dialogue", top3_codes)
        self.assertNotIn("sensory", top3_codes)


class TestRecommendPersona(unittest.TestCase):
    """测试人格推荐。"""

    def test_recommend_empty_history(self):
        """无历史记录时应推荐所有人格。"""
        history = {"entries": [], "gears": []}
        results, next_chap = recommend_persona(history, "快")
        self.assertEqual(next_chap, 1)
        self.assertEqual(len(results), 3)
        # 快档首选 blade
        self.assertEqual(results[0][0], "blade")

    def test_recommend_avoids_consecutive(self):
        """连续使用达到上限的人格应被排除。"""
        history = {
            "entries": [
                (1, None, "blade"),
                (2, None, "blade"),
            ],
            "gears": [],
        }
        results, _ = recommend_persona(history, "快")
        # blade 已连续2次，上限3，仍可用但分数降低
        blade_result = [r for r in results if r[0] == "blade"][0]
        self.assertIn("已连续2章", blade_result[1])

    def test_recommend_witness_consecutive_limit(self):
        """旁观派连续2章应被禁止。"""
        history = {
            "entries": [
                (1, None, "witness"),
                (2, None, "witness"),
            ],
            "gears": [],
        }
        results, _ = recommend_persona(history, "慢")
        # witness 应分数最低
        witness_result = [r for r in results if r[0] == "witness"][0]
        self.assertLess(witness_result[2], 0)

    def test_recommend_with_mode_compat(self):
        """指定入口模式时应参考兼容性。"""
        history = {"entries": [], "gears": []}
        # action + blade 是 ✓ 推荐
        results_action_blade, _ = recommend_persona(history, "快", mode_code="action")
        blade_score = [r[2] for r in results_action_blade if r[0] == "blade"][0]
        witness_score = [r[2] for r in results_action_blade if r[0] == "witness"][0]
        # blade 应比 witness 高（action × witness 是 ✗ 不推荐）
        self.assertGreater(blade_score, witness_score)

    def test_recommend_gear_priority(self):
        """不同档位应有不同人格优先级。"""
        history = {"entries": [], "gears": []}
        results_fast, _ = recommend_persona(history, "快")
        results_slow, _ = recommend_persona(history, "慢")
        self.assertEqual(results_fast[0][0], "blade")
        self.assertEqual(results_slow[0][0], "witness")


class TestCheckRotation(unittest.TestCase):
    """测试轮换违规检查。"""

    def test_check_empty_history(self):
        """无历史记录应无违规。"""
        history = {"entries": [], "gears": []}
        fails, warns = check_rotation(history)
        self.assertEqual(fails, [])
        self.assertEqual(warns, [])

    def test_check_same_mode_consecutive(self):
        """连续两章相同入口模式应为 FAIL。"""
        history = {
            "entries": [
                (1, "action", None),
                (2, "action", None),
            ],
            "gears": [],
        }
        fails, warns = check_rotation(history, chapter=2)
        self.assertTrue(any("入口模式违规" in f for f in fails))

    def test_check_same_mode_in_window(self):
        """近3章同一模式超过1次应为 WARN。"""
        history = {
            "entries": [
                (1, "action", None),
                (2, "dialogue", None),
                (3, "action", None),
            ],
            "gears": [],
        }
        fails, warns = check_rotation(history, chapter=3)
        self.assertTrue(any("入口模式警告" in w for w in warns))

    def test_check_persona_consecutive_three(self):
        """连续3章同一人格应为 FAIL。"""
        history = {
            "entries": [
                (1, None, "blade"),
                (2, None, "blade"),
                (3, None, "blade"),
            ],
            "gears": [],
        }
        fails, warns = check_rotation(history, chapter=3)
        self.assertTrue(any("人格轮换违规" in f for f in fails))

    def test_check_witness_consecutive_two(self):
        """旁观派连续2章应为 WARN。"""
        history = {
            "entries": [
                (1, None, "witness"),
                (2, None, "witness"),
            ],
            "gears": [],
        }
        fails, warns = check_rotation(history, chapter=2)
        self.assertTrue(any("旁观派" in w for w in warns))

    def test_check_clean_history(self):
        """无违规的历史应全部通过。"""
        history = {
            "entries": [
                (1, "scene", "witness"),
                (2, "dialogue", "fire"),
                (3, "action", "blade"),
            ],
            "gears": [],
        }
        fails, warns = check_rotation(history, chapter=3)
        self.assertEqual(fails, [])
        self.assertEqual(warns, [])


class TestRecordEntry(unittest.TestCase):
    """测试记录功能。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_em_record_"))
        self.book_dir = self.tmpdir / "测试书"
        tracking = self.book_dir / "追踪"
        tracking.mkdir(parents=True)
        self.quota_path = tracking / "节奏配额.md"
        self.quota_path.write_text("# 节奏配额\n\n正文\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_record_creates_section(self):
        """首次记录应创建记录表。"""
        line = record_entry(self.quota_path, 1, "scene", "witness", "中")
        self.assertIsNotNone(line)
        self.assertIn("场景切入", line)
        self.assertIn("旁观派", line)

        content = self.quota_path.read_text(encoding="utf-8")
        self.assertIn("## 入口模式与人格记录", content)
        self.assertIn("第1章", content)

    def test_record_appends_to_existing(self):
        """已有记录表时应追加。"""
        record_entry(self.quota_path, 1, "scene", "witness", "中")
        record_entry(self.quota_path, 2, "dialogue", "fire", "快")

        content = self.quota_path.read_text(encoding="utf-8")
        self.assertIn("第1章", content)
        self.assertIn("第2章", content)
        self.assertIn("对话切入", content)
        self.assertIn("热血派", content)

    def test_record_replaces_existing_chapter(self):
        """同一章节记录应替换而非追加。"""
        record_entry(self.quota_path, 1, "scene", "witness", "中")
        record_entry(self.quota_path, 1, "action", "blade", "快")

        content = self.quota_path.read_text(encoding="utf-8")
        self.assertIn("动作切入", content)
        self.assertIn("冷峻派", content)
        # 旧记录应被替换
        self.assertNotIn("场景切入", content)

    def test_record_partial(self):
        """只记录入口模式（不记录人格）。"""
        line = record_entry(self.quota_path, 1, "scene", None, None)
        self.assertIsNotNone(line)
        self.assertIn("场景切入", line)
        self.assertIn("—", line)  # 人格和档位为 —


class TestCLISubcommands(unittest.TestCase):
    """测试 CLI 子命令。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_em_cli_"))
        self.book_dir = self.tmpdir / "测试书"
        tracking = self.book_dir / "追踪"
        tracking.mkdir(parents=True)
        self.quota_path = tracking / "节奏配额.md"
        # 写入含入口模式记录的配额文件
        self.quota_path.write_text(
            "# 节奏配额\n\n"
            "## 入口模式与人格记录\n\n"
            "| 章节 | 入口模式 | 人格 | 档位 |\n"
            "|---|---|---|---|\n"
            "| 第1章 | 场景切入 | 旁观派 | 中 |\n"
            "| 第2章 | 对话切入 | 热血派 | 快 |\n",
            encoding="utf-8"
        )
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_cli_list(self):
        """list 子命令应列出所有模式。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "list"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("8种章节入口模式", result.stdout)
        self.assertIn("3种小说家人格", result.stdout)
        self.assertIn("兼容性矩阵", result.stdout)

    def test_cli_recommend(self):
        """recommend 子命令应推荐入口模式。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "recommend",
             str(self.book_dir), "--gear", "快"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("推荐入口模式", result.stdout)
        self.assertIn("第3章", result.stdout)

    def test_cli_persona(self):
        """persona 子命令应推荐人格。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "persona",
             str(self.book_dir), "--gear", "中"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("人格推荐", result.stdout)

    def test_cli_persona_with_mode(self):
        """persona 子命令带 --mode 应显示兼容性信息。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "persona",
             str(self.book_dir), "--gear", "快", "--mode", "action"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("兼容性", result.stdout)

    def test_cli_record(self):
        """record 子命令应写入记录。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "record",
             str(self.book_dir), "--chapter", "3",
             "--mode", "action", "--persona", "blade", "--gear", "快"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("已记录", result.stdout)
        # 验证文件已更新
        content = self.quota_path.read_text(encoding="utf-8")
        self.assertIn("第3章", content)
        self.assertIn("动作切入", content)

    def test_cli_check(self):
        """check 子命令应检查轮换。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "check",
             str(self.book_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("轮换检查", result.stdout)

    def test_cli_invalid_mode(self):
        """record 子命令对无效模式应返回错误。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "record",
             str(self.book_dir), "--chapter", "3",
             "--mode", "不存在的模式"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_cli_missing_book_dir(self):
        """不存在的书名目录应返回错误。"""
        import subprocess
        script = _SCRIPTS_DIR / "entry_mode.py"
        result = subprocess.run(
            [sys.executable, str(script), "recommend",
             str(self.tmpdir / "不存在"), "--gear", "快"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)


class TestCompatibilityMatrix(unittest.TestCase):
    """测试兼容性矩阵完整性。"""

    def test_all_modes_have_all_personas(self):
        """每个入口模式都应有全部3个人格的兼容性。"""
        for mode in ENTRY_MODES:
            self.assertIn(mode["code"], COMPATIBILITY,
                          f"模式 {mode['code']} 缺失兼容性矩阵")
            for persona in PERSONAS:
                self.assertIn(persona["code"], COMPATIBILITY[mode["code"]],
                              f"模式 {mode['code']} 缺少人格 {persona['code']} 的兼容性")

    def test_all_compat_values_valid(self):
        """兼容性值应只有 y/o/d/x。"""
        valid = {"y", "o", "d", "x"}
        for mode_code, personas in COMPATIBILITY.items():
            for persona_code, compat in personas.items():
                self.assertIn(compat, valid,
                              f"无效兼容性值：{mode_code}×{persona_code}={compat}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
