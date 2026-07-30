#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_outline_anchor.py — 测试 outline_anchor.py 大纲锚点核心功能。

运行方式：
    python scripts/tests/test_outline_anchor.py
"""

import io
import json
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

import outline_anchor
from outline_anchor import (
    cmd_init,
    cmd_inject,
    cmd_check,
    cmd_advance,
    cmd_status,
    _load,
    _find_volume,
    _anchor_path,
)


class _Args:
    """简易 args 替身，供 cmd_* 函数使用。"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _AnchorTestCase(unittest.TestCase):
    """所有锚点测试的基类：重置 outline_anchor.DEFAULT_SCHEMA 的共享可变字段。

    注：被测代码 cmd_init 使用 dict(DEFAULT_SCHEMA) 浅拷贝，导致
    volumes 列表在多次调用间共享。这里在每个测试前重置，保证隔离。
    """

    def setUp(self):
        outline_anchor.DEFAULT_SCHEMA = {
            "total_chapters": 0,
            "total_volumes": 0,
            "current_chapter": 0,
            "current_volume": 0,
            "progress_pct": 0.0,
            "volumes": [],
        }


class TestInit(_AnchorTestCase):
    """cmd_init 初始化锚点文件。"""

    def test_init_creates_file(self):
        """init 生成 outline_anchors.json 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            args = _Args(total=300, volumes=8)
            with redirect_stdout(io.StringIO()):
                rc = cmd_init(tmp, args)
            self.assertEqual(rc, 0)
            path = _anchor_path(tmp)
            self.assertTrue(os.path.isfile(path))

    def test_init_volume_skeleton(self):
        """init 生成卷级骨架，卷数与参数一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            args = _Args(total=100, volumes=4)
            with redirect_stdout(io.StringIO()):
                cmd_init(tmp, args)
            data, _ = _load(tmp)
            self.assertEqual(data["total_chapters"], 100)
            self.assertEqual(data["total_volumes"], 4)
            self.assertEqual(len(data["volumes"]), 4)
            # 第1卷起点为第1章
            self.assertEqual(data["volumes"][0]["chapter_start"], 1)
            # 最后卷终点为 total
            self.assertEqual(data["volumes"][-1]["chapter_end"], 100)

    def test_init_progress_pct(self):
        """init 进度百分比计算正确。"""
        with tempfile.TemporaryDirectory() as tmp:
            args = _Args(total=100, volumes=4)
            with redirect_stdout(io.StringIO()):
                cmd_init(tmp, args)
            data, _ = _load(tmp)
            # 4 卷，每卷 25%
            self.assertAlmostEqual(data["volumes"][0]["progress_start_pct"], 0.0)
            self.assertAlmostEqual(data["volumes"][0]["progress_end_pct"], 25.0)
            self.assertAlmostEqual(data["volumes"][-1]["progress_end_pct"], 100.0)


class TestInject(_AnchorTestCase):
    """cmd_inject 锚点注入。"""

    def _init_book(self, tmp, total=300, volumes=8):
        args = _Args(total=total, volumes=volumes)
        with redirect_stdout(io.StringIO()):
            cmd_init(tmp, args)

    def test_inject_outputs_constraint_text(self):
        """inject 输出包含大纲锚点约束文本。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=300, volumes=8)
            args = _Args(chapter=37, output=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cmd_inject(tmp, args)
            self.assertEqual(rc, 0)
            output = buf.getvalue()
            self.assertIn("大纲锚点约束", output)
            self.assertIn("第37章", output)
            self.assertIn("全书进度", output)
            self.assertIn("本卷进度", output)

    def test_inject_stage_position(self):
        """inject 根据进度输出阶段定位。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=300, volumes=8)
            # 第30章 / 300 = 10% < 30% → 开篇期
            args = _Args(chapter=30, output=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_inject(tmp, args)
            self.assertIn("开篇期", buf.getvalue())

    def test_inject_writes_output_file(self):
        """inject 配合 --output 写入文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=300, volumes=8)
            out = "大纲/约束_第37章.md"
            args = _Args(chapter=37, output=out)
            with redirect_stdout(io.StringIO()):
                rc = cmd_inject(tmp, args)
            self.assertEqual(rc, 0)
            out_path = os.path.join(tmp, out)
            self.assertTrue(os.path.isfile(out_path))
            content = Path(out_path).read_text(encoding="utf-8")
            self.assertIn("第37章", content)

    def test_inject_missing_anchor_file(self):
        """锚点文件不存在时返回错误码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            args = _Args(chapter=37, output=None)
            with redirect_stdout(io.StringIO()):
                rc = cmd_inject(tmp, args)
            self.assertEqual(rc, 2)

    def test_inject_chapter_out_of_range(self):
        """章节号超出卷范围返回错误码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=100, volumes=4)
            # 第500章超出全书范围
            args = _Args(chapter=500, output=None)
            with redirect_stdout(io.StringIO()):
                rc = cmd_inject(tmp, args)
            self.assertEqual(rc, 2)


class TestCheckQuota(_AnchorTestCase):
    """cmd_check 配额检查。"""

    def _init_book(self, tmp, total=300, volumes=8):
        args = _Args(total=total, volumes=volumes)
        with redirect_stdout(io.StringIO()):
            cmd_init(tmp, args)

    def test_check_a_quota_at_low_progress_fails(self):
        """进度 < 15% 时触发 A 配额 → 违规（exit 1）。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=300, volumes=8)
            # 第30章 / 300 = 10% < 15%
            args = _Args(chapter=30, quota="A", last_c_chapter=None)
            with redirect_stdout(io.StringIO()):
                rc = cmd_check(tmp, args)
            self.assertEqual(rc, 1)

    def test_check_c_quota_at_low_progress_fails(self):
        """进度 < 40% 时触发 C 配额 → 违规（exit 1）。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=300, volumes=8)
            # 第100章 / 300 ≈ 33% < 40%
            args = _Args(chapter=100, quota="C", last_c_chapter=None)
            with redirect_stdout(io.StringIO()):
                rc = cmd_check(tmp, args)
            self.assertEqual(rc, 1)

    def test_check_quota_compatible_passes(self):
        """进度足够时配额兼容 → 通过（exit 0）。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=100, volumes=4)
            # 第95章 / 100 = 95%，A 在卷末 80% 后可触发
            # 第4卷章节范围 76-100，95 章卷内进度 (95-76+1)/25 = 80% ≥ 80%
            args = _Args(chapter=95, quota="A", last_c_chapter=None)
            with redirect_stdout(io.StringIO()):
                rc = cmd_check(tmp, args)
            self.assertEqual(rc, 0)

    def test_check_no_quota_passes(self):
        """未声明配额 → 通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=100, volumes=4)
            args = _Args(chapter=50, quota=None, last_c_chapter=None)
            with redirect_stdout(io.StringIO()):
                rc = cmd_check(tmp, args)
            self.assertEqual(rc, 0)


class TestAdvance(_AnchorTestCase):
    """cmd_advance 推进章节指针。"""

    def _init_book(self, tmp, total=300, volumes=8):
        args = _Args(total=total, volumes=volumes)
        with redirect_stdout(io.StringIO()):
            cmd_init(tmp, args)

    def test_advance_updates_pointer(self):
        """advance 更新 current_chapter 与 progress_pct。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=300, volumes=8)
            args = _Args(chapter=50, volume_end=False)
            with redirect_stdout(io.StringIO()):
                rc = cmd_advance(tmp, args)
            self.assertEqual(rc, 0)
            data, _ = _load(tmp)
            self.assertEqual(data["current_chapter"], 50)
            self.assertAlmostEqual(data["progress_pct"], round(50 / 300 * 100, 1))

    def test_advance_updates_current_volume(self):
        """advance 更新 current_volume。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=100, volumes=4)
            # 第4卷章节范围 76-100
            args = _Args(chapter=80, volume_end=False)
            with redirect_stdout(io.StringIO()):
                cmd_advance(tmp, args)
            data, _ = _load(tmp)
            self.assertEqual(data["current_volume"], 4)

    def test_advance_volume_end_marker(self):
        """advance --volume-end 标记卷完结。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_book(tmp, total=100, volumes=4)
            args = _Args(chapter=25, volume_end=True)  # 第1卷末
            with redirect_stdout(io.StringIO()):
                rc = cmd_advance(tmp, args)
            self.assertEqual(rc, 0)
            data, _ = _load(tmp)
            vol1 = data["volumes"][0]
            self.assertTrue(vol1["resolved"])

    def test_advance_missing_anchor_file(self):
        """锚点文件不存在时返回错误码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            args = _Args(chapter=50, volume_end=False)
            with redirect_stdout(io.StringIO()):
                rc = cmd_advance(tmp, args)
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
