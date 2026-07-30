#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_rhythm_guard.py — 测试 rhythm_guard.py 节奏守卫核心功能。

运行方式：
    python scripts/tests/test_rhythm_guard.py
"""

import io
import os
import sys
import tempfile
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
