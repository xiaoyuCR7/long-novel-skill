#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_rhythm_guard.py — 测试 rhythm_guard.py 节奏守卫核心功能。

运行方式：
    python scripts/tests/test_rhythm_guard.py
"""

import io
import json
import os
import sys
import tempfile
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rhythm_guard
from rhythm_guard import (
    QUOTA_COOLDOWN,
    EVENT_COOLDOWN,
    EVENT_COOLDOWN_NEW,
    parse_quota_file,
    run_checks,
    normalize_event,
    parse_event_records,
    check_gentle_window,
    check_event_cooldown_new,
    _parse_declare,
    _quota_letters,
)


def _make_quota_text(records=None):
    """构造节奏配额文件内容。

    records: 可选，dict 形如：
        {"quota": [(35,"A","...")], "events": [(35,"conflict","...")],
         "gears": [(35,"快")]}
    """
    records = records or {}
    lines = []
    lines.append("## A/B/C 配额记录")
    lines.append("| 章节 | 配额 | 触发内容 |")
    lines.append("|---|---|---|")
    for chap, q, content in records.get("quota", []):
        lines.append(f"| {chap} | {q} | {content} |")
    lines.append("")
    lines.append("## 事件冷却记录")
    lines.append("| 章节 | 事件类型 | 事件内容 |")
    lines.append("|---|---|---|")
    for chap, ev, content in records.get("events", []):
        lines.append(f"| {chap} | {ev} | {content} |")
    lines.append("")
    lines.append("## 档位记录")
    lines.append("| 章节 | 档位 |")
    lines.append("|---|---|")
    for chap, gear in records.get("gears", []):
        lines.append(f"| {chap} | {gear} |")
    return "\n".join(lines) + "\n"


class TestQuotaCheck(unittest.TestCase):
    """A/B/C 配额检查。"""

    def test_quota_overuse_fails(self):
        """本章同时声明 ≥2 项配额 → FAIL。"""
        records = {"quota": [], "events": [], "gears": []}
        # 声明同时触发 A 和 B
        fails, warns = run_checks(records, current=37,
                                  quota_set={"A", "B"}, event=None, gear=None)
        self.assertTrue(any("A/B/C 配额越界" in f for f in fails))

    def test_quota_cooldown_violation(self):
        """A 冷却期内再次声明 A → FAIL。"""
        records = {
            "quota": [(35, "A", "主线推进")],
            "events": [],
            "gears": [],
        }
        # A 冷却期 2 章，第 37 章距第 35 章 2 章 ≤ 2，应 FAIL
        fails, warns = run_checks(records, current=37,
                                  quota_set={"A"}, event=None, gear=None)
        self.assertTrue(any("A 冷却违规" in f for f in fails))

    def test_quota_cooldown_passed(self):
        """A 冷却期外声明 A → 通过。"""
        records = {
            "quota": [(34, "A", "主线推进")],
            "events": [],
            "gears": [],
        }
        # A 冷却期 2 章，第 37 章距第 34 章 3 章 > 2，应通过
        fails, warns = run_checks(records, current=37,
                                  quota_set={"A"}, event=None, gear=None)
        quota_fails = [f for f in fails if "冷却违规" in f and "A " in f]
        self.assertEqual(quota_fails, [])

    def test_quota_c_cooldown(self):
        """C 冷却期 3 章内再次声明 → FAIL。"""
        records = {
            "quota": [(36, "C", "揭露核心秘密")],
            "events": [],
            "gears": [],
        }
        # C 冷却期 3 章，第 38 章距第 36 章 2 章 ≤ 3
        fails, warns = run_checks(records, current=38,
                                  quota_set={"C"}, event=None, gear=None)
        self.assertTrue(any("C 冷却违规" in f for f in fails))

    def test_no_quota_no_fail(self):
        """不声明任何配额则无配额相关 FAIL。"""
        records = {"quota": [], "events": [], "gears": []}
        fails, warns = run_checks(records, current=37,
                                  quota_set=set(), event=None, gear=None)
        self.assertFalse(any("配额" in f for f in fails))


class TestCooldown(unittest.TestCase):
    """事件冷却检查。"""

    def test_event_cooldown_new_violation(self):
        """新版事件冷却违规：conflict 第35章触发，第37章再触发（冷却2章）→ FAIL。"""
        events_new = [(35, "conflict")]
        fails = check_event_cooldown_new(events_new, current_chapter=37,
                                         event="conflict")
        self.assertTrue(any("事件冷却违规" in f for f in fails))

    def test_event_cooldown_new_passed(self):
        """新版事件冷却通过：conflict 第34章触发，第37章再触发（间隔3章 > 2）→ 无违规。"""
        events_new = [(34, "conflict")]
        fails = check_event_cooldown_new(events_new, current_chapter=37,
                                         event="conflict")
        self.assertEqual(fails, [])

    def test_event_consecutive_limit(self):
        """事件连续上限：conflict 已连续 2 章，本章再触发（共 3 次）超上限 2 → FAIL。"""
        events_new = [(34, "conflict"), (35, "conflict")]
        fails = check_event_cooldown_new(events_new, current_chapter=36,
                                         event="conflict")
        self.assertTrue(any("连续上限" in f for f in fails))

    def test_normalize_event_aliases(self):
        """旧版别名规范化为新版事件类型。"""
        self.assertEqual(normalize_event("conflict_thrill"), "conflict")
        self.assertEqual(normalize_event("bond_deepening"), "bond")
        self.assertEqual(normalize_event("tension_escalation"), "crisis")
        self.assertEqual(normalize_event("revelation"), "revelation")

    def test_parse_event_records_from_quota(self):
        """从 A/B/C 配额记录中推断事件历史。"""
        records = {
            "quota": [(35, "A", "主线推进"), (36, "C", "揭露秘密")],
            "events": [],
            "gears": [],
        }
        events_new = parse_event_records(records)
        types = {e for _, e in events_new}
        # A → conflict，C → revelation
        self.assertIn("conflict", types)
        self.assertIn("revelation", types)

    def test_gentle_window_satisfied(self):
        """gentle_window：5章窗口内有 bond 或 world → 满足。"""
        events_new = [(35, "bond")]
        ok, _ = check_gentle_window(events_new, current_chapter=37)
        self.assertTrue(ok)

    def test_gentle_window_violated(self):
        """gentle_window：5章窗口内无 bond/world → 未满足。"""
        events_new = [(30, "conflict")]  # 窗口外
        ok, msg = check_gentle_window(events_new, current_chapter=37)
        self.assertFalse(ok)
        self.assertIn("gentle_window", msg)


class TestParseDeclare(unittest.TestCase):
    """--declare 字符串解析。"""

    def test_parse_full_declare(self):
        """完整声明 'A,conflict,快' 解析正确。"""
        quota_set, event, gear = _parse_declare("A,conflict,快")
        self.assertEqual(quota_set, {"A"})
        self.assertEqual(event, "conflict")
        self.assertEqual(gear, "快")

    def test_parse_gear_with_suffix(self):
        """档位带「档」字也能解析。"""
        _, _, gear = _parse_declare("慢档")
        self.assertEqual(gear, "慢")

    def test_parse_no_trigger(self):
        """「无/不触发」被忽略。"""
        quota_set, event, gear = _parse_declare("无,conflict,快")
        self.assertEqual(quota_set, set())


class TestR5EventContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.quota = self.root / "节奏配额.md"
        self.quota.write_text(_make_quota_text(), encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT_DIR / "rhythm_guard.py"),
                               "--quota", str(self.quota), "--chapter", "1", *args],
                              capture_output=True, encoding="utf-8")

    def test_canonical_and_legacy_record_round_trip(self):
        from validate_tracking import validate_quota
        from config import EVENT_META
        for event in list(EVENT_META) + list(rhythm_guard.EVENT_ALIASES):
            with self.subTest(event=event):
                self.quota.write_text(_make_quota_text(), encoding="utf-8")
                self.assertIsNotNone(rhythm_guard.record_event(self.quota, 1, event))
                self.assertEqual(validate_quota(self.quota), [])

    def test_normalizers_reject_guessed_prefixes(self):
        from event_matrix import normalize_event as matrix_normalize
        for event in ("daily", "conf", "conflict_typo", "world_painting_typo", "tension", "BAD"):
            with self.subTest(event=event):
                self.assertIsNone(normalize_event(event))
                self.assertIsNone(matrix_normalize(event))

    def test_declaration_rejects_unknown_and_conflicting_fields(self):
        for declaration in ("-,daily,慢", "BAD,world,慢", "-,world,bond,慢", "-,world,快,慢"):
            with self.subTest(declaration=declaration):
                with self.assertRaises(ValueError):
                    _parse_declare(declaration)

    def test_known_multi_quota_remains_a_violation_not_parse_error(self):
        quota, event, gear = _parse_declare("A+B,world,慢")
        self.assertEqual(quota, {"A", "B"})
        fails, _ = run_checks(parse_quota_file(self.quota), 1, quota, event, gear)
        self.assertTrue(any("配额越界" in item for item in fails))

    def test_invalid_declaration_does_not_create_gate(self):
        before = self.quota.read_bytes()
        proc = self.cli("--declare=-,daily,慢", "--gate-state")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("daily", proc.stderr)
        self.assertFalse((self.root / "门禁").exists())
        self.assertEqual(self.quota.read_bytes(), before)

    def test_invalid_history_is_not_silently_discarded(self):
        self.quota.write_text(_make_quota_text({"events": [(1, "daily", "日常")]}), encoding="utf-8")
        for args in (("--declare=-,world,慢", "--gate-state"), ("--recommend", "慢")):
            with self.subTest(args=args):
                proc = self.cli(*args)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn("daily", proc.stderr)
        self.assertFalse((self.root / "门禁").exists())

    def test_text_declaration_exact_event_and_html_gear(self):
        extract = rhythm_guard._extract_decl_from_text
        self.assertEqual(extract("<!-- quota:A event:conflict_thrill gear:快 -->"),
                         ({"A"}, "conflict_thrill", "快"))
        for text in ("> 节奏声明：配额 无，事件 daily，档位 慢",
                     "<!-- quota:- event:world_typo gear:慢 -->"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    extract(text)

    def test_invalid_text_declaration_does_not_create_gate(self):
        chapter = self.root / "第001章.md"
        chapter.write_text("<!-- quota:- event:daily gear:慢 -->", encoding="utf-8")
        proc = self.cli("--chapter-file", str(chapter), "--gate-state")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertFalse((self.root / "门禁").exists())

    def test_record_missing_file_does_not_claim_success(self):
        self.quota.unlink()
        proc = self.cli("--record", "world")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("已记录", proc.stdout)

    def test_existing_cooldowns_unchanged(self):
        self.assertEqual(EVENT_COOLDOWN_NEW,
                         {"conflict": 2, "bond": 3, "faction": 4, "world": 3, "crisis": 2, "revelation": 5})
        self.assertEqual(QUOTA_COOLDOWN, {"A": 2, "B": 1, "C": 3})

    def test_review_markdown_event_fields_preserve_cooldown_checks(self):
        extract = rhythm_guard._extract_decl_from_text
        for label in ("**事件类型**", "事件类型声明", "事件", "event"):
            with self.subTest(label=label):
                quota, event, gear = extract(f"- {label}：world\n- 档位：慢")
                self.assertEqual(event, "world")
                fails, _ = run_checks({"quota": [], "events": [(1, "world", "")], "gears": []},
                                      2, quota, event, gear)
                self.assertTrue(any("事件冷却" in item for item in fails))
                with self.assertRaises(ValueError):
                    extract(f"- {label}：daily\n- 档位：慢")

    def test_review_text_quota_uses_cli_contract(self):
        extract = rhythm_guard._extract_decl_from_text
        self.assertEqual(extract("<!-- quota:ABC event:world gear:慢 -->")[0], {"A", "B", "C"})
        for value in ("BAD", "ABCD"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    extract(f"<!-- quota:{value} event:world gear:慢 -->")

    def test_review_text_single_template_wrappers_and_cli_gates(self):
        extract = rhythm_guard._extract_decl_from_text
        self.assertEqual(extract("事件类型：[world_painting]\n档位：慢")[1], "world_painting")
        chapter = self.root / "第001章.md"
        for value, expected_code in (("ABC", 1), ("BAD", 2)):
            with self.subTest(value=value):
                chapter.write_text(f"<!-- quota:{value} event:world gear:慢 -->", encoding="utf-8")
                proc = self.cli("--chapter-file", str(chapter), "--gate-state")
                self.assertEqual(proc.returncode, expected_code, proc.stdout + proc.stderr)
                gate = self.root / "门禁/gate_ch1.json"
                if gate.exists():
                    self.assertFalse(json.loads(gate.read_text(encoding="utf-8"))["rhythm"]["passed"])

    def test_review_conflicting_text_gears_are_rejected(self):
        for text in ("<!-- event:world gear:快 -->\n<!-- gear:慢 -->",
                     "档位：快\n档位：慢", "档位：随便"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    rhythm_guard._extract_decl_from_text(text)

    def test_review_spaced_multi_quota_cannot_be_truncated(self):
        chapter = self.root / "第001章.md"
        for text in ("<!-- quota:A B event:world gear:慢 -->",
                     "配额：A + B\n事件：world\n档位：慢"):
            with self.subTest(text=text):
                chapter.write_text(text, encoding="utf-8")
                proc = self.cli("--chapter-file", str(chapter), "--gate-state")
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                gate = json.loads((self.root / "门禁/gate_ch1.json").read_text(encoding="utf-8"))
                self.assertFalse(gate["rhythm"]["passed"])

    def test_review_matrix_load_normalizes_old_names(self):
        from event_matrix import load_matrix
        tracking = self.root / "追踪"
        tracking.mkdir()
        source = tracking / "event_matrix.json"
        source.write_text(json.dumps({"records": [[1, "world_painting"]]}), encoding="utf-8")
        before = source.read_bytes()
        self.assertEqual(load_matrix(self.root)["records"], [(1, "world")])
        self.assertEqual(source.read_bytes(), before)
        proc = subprocess.run([sys.executable, "-B", str(SCRIPT_DIR / "event_matrix.py"),
                               "status", str(self.root)], capture_output=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("第1章: world", proc.stdout)

    def test_review_invalid_matrix_history_never_becomes_empty(self):
        tracking = self.root / "追踪"
        tracking.mkdir()
        source = tracking / "event_matrix.json"
        for content in ('{"records":[[1,"daily"]]}', '{broken', '{"records":null}',
                        '{"records":[[true,"world"]]}'):
            source.write_text(content, encoding="utf-8")
            before = source.read_bytes()
            for command, args in (("status", []), ("recommend", ["--gear", "慢"]),
                                  ("record", ["--event", "world", "--chapter", "2"])):
                with self.subTest(content=content, command=command):
                    proc = subprocess.run([sys.executable, "-B", str(SCRIPT_DIR / "event_matrix.py"),
                                           command, str(self.root), *args], capture_output=True, encoding="utf-8")
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)
                    self.assertEqual(source.read_bytes(), before)


class TestRhythmReport(unittest.TestCase):
    """节奏报告格式（parse_quota_file 解析）。"""

    def test_parse_quota_file_all_sections(self):
        """配额文件三节都能解析。"""
        text = _make_quota_text({
            "quota": [(35, "A", "主线推进")],
            "events": [(35, "conflict", "打脸长老")],
            "gears": [(35, "快")],
        })
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write(text)
            path = f.name
        try:
            records = parse_quota_file(path)
            self.assertEqual(len(records["quota"]), 1)
            self.assertEqual(records["quota"][0][0], 35)
            self.assertEqual(records["quota"][0][1], "A")
            self.assertEqual(len(records["events"]), 1)
            self.assertEqual(records["events"][0][1], "conflict")
            self.assertEqual(len(records["gears"]), 1)
            self.assertEqual(records["gears"][0][1], "快")
        finally:
            os.unlink(path)

    def test_parse_quota_file_skips_header(self):
        """跳过表头与分隔行。"""
        text = _make_quota_text({"quota": [(35, "A", "x")]})
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write(text)
            path = f.name
        try:
            records = parse_quota_file(path)
            # 只有一条数据记录
            self.assertEqual(len(records["quota"]), 1)
        finally:
            os.unlink(path)

    def test_consecutive_fast_gear_fails(self):
        """连续快档：上一章快 + 本章快 → FAIL。"""
        records = {
            "quota": [],
            "events": [],
            "gears": [(36, "快")],
        }
        fails, warns = run_checks(records, current=37,
                                  quota_set=set(), event=None, gear="快")
        self.assertTrue(any("连续快档" in f for f in fails))


if __name__ == "__main__":
    unittest.main(verbosity=2)
