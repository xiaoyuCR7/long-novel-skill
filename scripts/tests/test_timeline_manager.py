#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_timeline_manager.py — 章节时间线管理模块测试。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timeline_manager import (  # noqa: E402
    parse_timeline, parse_anchors, normalize_time, check_timeline,
    build_timeline_json, viz_mermaid, viz_ascii,
)

MD_NEW = """# 时间线

## 时间锚点
| A1 | 穿越起点 | 穿越后第1天 |
| A2 | 开学典礼 | 9月1日 |

## 第 1 卷
| 章节 | 故事内时间 | 事件 | 时间标记/约定 |
|------|-----------|------|--------------|
| 第1章 | 穿越后第1天 | 觉醒 | 七日后比武 |
| 第2章 | 穿越后第3天 | 修炼 |  |
| 第3章 | 穿越后第5天 | 突破 |  |
"""

MD_OLD = """# 时间线

## 第一卷：测试卷（前3章时间线）

### 9月3日（周一）—— 第1章
| 时间 | 事件 | 地点 | 涉及人物 |
|------|------|------|---------|
| 凌晨2:00 | 觉醒 | 家中 | 林辰 |

### 9月4日（周二）—— 第2章
| 时间 | 事件 |
|------|------|
| 上午 | 测试 |
"""


class TestParse(unittest.TestCase):
    def test_parse_new_table(self):
        data = parse_timeline(MD_NEW)
        self.assertEqual([c["chapter"] for c in data["chapters"]], [1, 2, 3])
        self.assertEqual(data["chapters"][0]["time_desc"], "穿越后第1天")
        self.assertEqual(data["chapters"][0]["promise"], "七日后比武")

    def test_parse_old_sections(self):
        data = parse_timeline(MD_OLD)
        self.assertEqual([c["chapter"] for c in data["chapters"]], [1, 2])
        self.assertTrue(data["chapters"][0]["time_desc"])

    def test_parse_anchors(self):
        anchors = parse_anchors(MD_NEW)
        self.assertIn("A1", anchors)
        self.assertEqual(anchors["A1"]["time_expr"], "穿越后第1天")
        self.assertIn("A2", anchors)


class TestNormalize(unittest.TestCase):
    def test_relative_days(self):
        self.assertEqual(normalize_time("穿越后第3天"), (3, "day"))
        self.assertEqual(normalize_time("第3天"), (3, "day"))

    def test_gregorian(self):
        self.assertEqual(normalize_time("9月3日"), (903, "day"))
        self.assertEqual(normalize_time("2024年5月10日"), (2024 * 400 + 5 * 30 + 10, "day"))

    def test_calendar_year(self):
        v = normalize_time("天元历300年春")
        self.assertIsNotNone(v)
        self.assertEqual(v[1], "day")
        self.assertEqual(v[0], 300 * 400)

    def test_anchor_ref(self):
        anchors = parse_anchors(MD_NEW)
        self.assertEqual(normalize_time("@A1+2", anchors), (3, "day"))
        self.assertEqual(normalize_time("@A2", anchors), (901, "day"))

    def test_unparseable(self):
        self.assertIsNone(normalize_time(""))
        self.assertIsNone(normalize_time("前世记忆"))


class TestCheck(unittest.TestCase):
    def test_clean_passes(self):
        issues, meta = check_timeline(None, md_text=MD_NEW)
        self.assertEqual(meta["error_count"], 0)
        self.assertEqual(meta["warn_count"], 0)

    def test_c1_regression(self):
        md = MD_NEW.replace("穿越后第5天", "穿越后第2天")  # ch3(2) < ch2(3) 倒退
        issues, meta = check_timeline(None, md_text=md)
        self.assertTrue(any(i["type"] == "C1_time_regression" for i in issues))

    def test_c2_silent_jump(self):
        md = MD_NEW.replace("穿越后第5天", "穿越后第100天")
        issues, meta = check_timeline(None, md_text=md)
        self.assertTrue(any(i["type"] == "C2_silent_time_jump" for i in issues))

    def test_c2_marked_jump_no_warn(self):
        md = MD_NEW.replace("第3章 | 穿越后第5天", "第3章 | 穿越后第100天").replace(
            "| 突破 |  |", "| 突破 | 三个月后 |")
        issues, meta = check_timeline(None, md_text=md)
        self.assertFalse(any(i["type"] == "C2_silent_time_jump" for i in issues))

    def test_c3_promise_overdue(self):
        md = MD_NEW.replace("穿越后第5天", "穿越后第12天")  # 七日后比武 → 第12天未兑现
        issues, meta = check_timeline(None, md_text=md)
        self.assertTrue(any(i["type"] == "C3_promise_overdue" for i in issues))

    def test_c5_branch_conflict(self):
        md = MD_NEW.rstrip() + "\n| 第4章 | 穿越后第5日 | 另一线 |  |"  # 同时间点(5)但描述不一致
        issues, meta = check_timeline(None, md_text=md)
        self.assertTrue(any(i["type"] == "C5_branch_time_conflict" for i in issues))


class TestBuild(unittest.TestCase):
    def test_build_writes_json(self):
        with tempfile.TemporaryDirectory() as td:
            book = Path(td) / "book"
            (book / "追踪").mkdir(parents=True)
            (book / "追踪" / "时间线.md").write_text(MD_NEW, encoding="utf-8")
            data, out_path = build_timeline_json(str(book))
            self.assertTrue(os.path.isfile(out_path))
            self.assertEqual(data["version"], "1.0.0")
            self.assertEqual(len(data["chapters"]), 3)


class TestViz(unittest.TestCase):
    def test_viz_mermaid(self):
        data = parse_timeline(MD_NEW)
        out = viz_mermaid(data)
        self.assertIn("```mermaid", out)
        self.assertIn("timeline", out)
        self.assertIn("第1章", out)

    def test_viz_ascii(self):
        data = parse_timeline(MD_NEW)
        out = viz_ascii(data)
        self.assertIn("第1章", out)
        self.assertIn("穿越后第1天", out)


if __name__ == "__main__":
    unittest.main()
