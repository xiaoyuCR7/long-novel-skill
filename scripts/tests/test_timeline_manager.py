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


class TestTrackingAnchorCompatibility(unittest.TestCase):
    def validate(self, text):
        from validate_tracking import validate_timeline
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeline.md"
            path.write_text(text, encoding="utf-8")
            return validate_timeline(path)

    def test_native_template_anchors_and_chapter_table_share_a_valid_file(self):
        template = Path(__file__).resolve().parents[2] / "assets/templates/timeline.md"
        text = template.read_text(encoding="utf-8").replace("{N}", "1")
        self.assertEqual(self.validate(text), [])
        anchors = parse_anchors(text)
        self.assertEqual(anchors["A1"]["time_expr"], "穿越后第1天")
        self.assertEqual(anchors["A2"]["time_expr"], "9月1日")

    def test_valid_anchor_section_does_not_hide_invalid_chapter_rows(self):
        for row in ("| 第3章 | 当天 | 缺少时间标记列 |", "| 没有章号 | 当天 | 事件 | 当日 |"):
            with self.subTest(row=row):
                text = "## 时间锚点\n| A1 | 起点 | 第1天 |\n## 第1卷\n" + row
                issues = self.validate(text)
                self.assertEqual(len(issues), 1, issues)

    def test_invalid_anchor_is_not_accepted_as_chapter_or_ignored(self):
        for row in (
            "| A1 | 起点 | |", "| A1 | | 第1天 |", "| | 起点 | 第1天 |",
            "| Q1 | 起点 | 第1天 |", "| A1 | 起点 | 第1天 | 多余列 |",
            "Q1: 第1天", "A1: ", "A1 起点 = 第1天", "- A1: 第1天",
        ):
            with self.subTest(row=row):
                self.assertTrue(self.validate("## 时间锚点\n" + row), row)

    def test_native_anchor_text_and_heading_levels(self):
        for heading in ("# 时间锚点", "##时间锚点", "### 时间锚点（基准）"):
            for row in ("A1 | 起点 | 第1天", "A1: 第1天", "A1：第1天", "A1 = 第1天 # 起点"):
                with self.subTest(heading=heading, row=row):
                    text = heading + "\n" + row
                    self.assertIn("A1", parse_anchors(text))
                    self.assertEqual(self.validate(text), [])

    def test_native_anchor_block_boundaries_are_preserved(self):
        for heading in ("# 第1卷", "## 第1卷", "### 第1卷"):
            with self.subTest(heading=heading):
                text = "## 时间锚点\n| A1 | 起点 | 第1天 |\n" + heading + "\n| 第3章 | 当天 | 事件 |"
                self.assertEqual(len(self.validate(text)), 1)
        nested = "## 时间锚点\n#### 补充\n| A1 | 起点 | 第1天 |"
        self.assertIn("A1", parse_anchors(nested))
        self.assertEqual(self.validate(nested), [])
        unsupported = "#### 时间锚点\n| A1 | 起点 | 第1天 |"
        self.assertEqual(parse_anchors(unsupported), {})
        self.assertTrue(self.validate(unsupported))
        repeated = "## 时间锚点\nA1: 第1天\n## 第1卷\n## 时间锚点\nA2: 第2天"
        self.assertNotIn("A2", parse_anchors(repeated))
        self.assertTrue(self.validate(repeated))

    def test_tracking_quota_accepts_only_documented_no_quota_marker(self):
        # 同一追踪校验器：无配额记录必须与 rhythm_guard 的解释一致。
        from rhythm_guard import _quota_letters, parse_quota_file
        from validate_tracking import validate_quota
        for quota in ("-", "  -  ", "A", "B", "C", "", "D", "无", "--"):
            with self.subTest(quota=quota), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "quota.md"
                path.write_text(
                    "## A/B/C 配额记录\n| 1 | " + quota + " | 日常 |\n"
                    "## 事件冷却记录\n## 档位记录\n", encoding="utf-8",
                )
                if quota.strip() in ("-", "A", "B", "C"):
                    self.assertEqual(validate_quota(path), [])
                    if quota.strip() == "-":
                        self.assertEqual(_quota_letters(parse_quota_file(path)["quota"][0][1]), set())
                else:
                    self.assertTrue(validate_quota(path))


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
