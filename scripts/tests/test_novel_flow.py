#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_novel_flow.py — 测试 novel_flow.py 幂等回滚与执行锁。

运行方式：
    python scripts/tests/test_novel_flow.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from novel_flow import (
    acquire_lock,
    release_lock,
    force_unlock,
    create_snapshot,
    list_snapshots,
    restore_snapshot,
    find_book_dir,
    find_latest_chapter,
    check_tracking_sync,
)


class TestFindBookDir(unittest.TestCase):
    """测试目录查找。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_book_dir_with_tracking_and_outline(self):
        """同时存在 追踪/ 和 大纲/ 时识别为书籍目录。"""
        (self.root / "追踪").mkdir()
        (self.root / "大纲").mkdir()
        self.assertEqual(find_book_dir(str(self.root)), self.root)

    def test_find_book_dir_nested(self):
        """在子目录中查找书籍工程。"""
        book = self.root / "my_book"
        (book / "追踪").mkdir(parents=True)
        (book / "大纲").mkdir(parents=True)
        # 传入父目录，应能找到子目录中的工程
        found = find_book_dir(str(self.root))
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "my_book")

    def test_find_book_dir_missing(self):
        """缺少必要目录时返回 None。"""
        self.assertIsNone(find_book_dir(str(self.root)))


class TestAcquireLock(unittest.TestCase):
    """测试执行锁获取。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "追踪").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_lock_success(self):
        """首次获取锁应成功。"""
        ok, msg = acquire_lock(self.root, "write", 1)
        self.assertTrue(ok, msg)
        lock_file = self.root / "追踪" / ".flow_lock.json"
        self.assertTrue(lock_file.exists())

    def test_acquire_lock_conflict(self):
        """已有运行中锁时获取应失败。"""
        # 先获取一个锁
        ok, _ = acquire_lock(self.root, "write", 1)
        self.assertTrue(ok)
        # 再次获取应失败
        ok2, msg2 = acquire_lock(self.root, "write", 2)
        self.assertFalse(ok2)
        self.assertIn("锁冲突", msg2)

    def test_acquire_lock_after_release(self):
        """释放锁后可重新获取。"""
        acquire_lock(self.root, "write", 1)
        release_lock(self.root)
        ok, _ = acquire_lock(self.root, "write", 2)
        self.assertTrue(ok)

    def test_force_unlock_removes_lock(self):
        """强制清除锁后文件应不存在。"""
        acquire_lock(self.root, "write", 1)
        ok, msg = force_unlock(self.root)
        self.assertTrue(ok)
        lock_file = self.root / "追踪" / ".flow_lock.json"
        self.assertFalse(lock_file.exists())

    def test_force_unlock_when_no_lock(self):
        """无锁时强制清除应返回提示。"""
        ok, msg = force_unlock(self.root)
        self.assertFalse(ok)
        self.assertIn("无执行锁", msg)


class TestSnapshot(unittest.TestCase):
    """测试快照功能。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "追踪").mkdir(parents=True)
        # 创建一些追踪文件
        (self.root / "追踪" / "伏笔台账.md").write_text("test", encoding="utf-8")
        (self.root / "追踪" / "章节摘要.md").write_text("test", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_snapshot_creates_backup(self):
        """创建快照应生成备份目录。"""
        ts = create_snapshot(self.root)
        self.assertIsNotNone(ts)
        snap_dir = self.root / "追踪" / ".snapshots" / f"snapshot_{ts}"
        self.assertTrue(snap_dir.exists())

    def test_list_snapshots_returns_sorted(self):
        """列出快照应按时间倒序。"""
        ts1 = create_snapshot(self.root)
        ts2 = create_snapshot(self.root)
        snaps = list_snapshots(self.root)
        self.assertGreaterEqual(len(snaps), 2)
        # 最新快照应在最前
        self.assertEqual(snaps[0]["timestamp"], ts2)

    def test_restore_snapshot_restores_files(self):
        """恢复快照应还原文件内容。"""
        # 初始内容
        (self.root / "追踪" / "伏笔台账.md").write_text("original", encoding="utf-8")
        ts = create_snapshot(self.root)
        # 修改内容
        (self.root / "追踪" / "伏笔台账.md").write_text("modified", encoding="utf-8")
        # 恢复
        ok, msg = restore_snapshot(self.root, ts)
        self.assertTrue(ok)
        restored = (self.root / "追踪" / "伏笔台账.md").read_text(encoding="utf-8")
        self.assertEqual(restored, "original")

    def test_restore_nonexistent_snapshot(self):
        """恢复不存在的快照应失败。"""
        ok, msg = restore_snapshot(self.root, "99999999_999999")
        self.assertFalse(ok)


class TestFindLatestChapter(unittest.TestCase):
    """测试查找最新章节。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_chapters_returns_zero(self):
        """无正文时返回 0。"""
        self.assertEqual(find_latest_chapter(self.root), 0)

    def test_finds_latest_chapter(self):
        """正确识别最新章号。"""
        (self.root / "正文" / "第001章_开篇.md").write_text("a")
        (self.root / "正文" / "第010章_发展.md").write_text("b")
        (self.root / "正文" / "第005章_过渡.md").write_text("c")
        self.assertEqual(find_latest_chapter(self.root), 10)


class TestCheckTrackingSync(unittest.TestCase):
    """测试追踪同步检查。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "追踪").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync_with_summary_and_state(self):
        """追踪文件包含目标章节时应返回 True。"""
        (self.root / "追踪" / "章节摘要.md").write_text("### 第5章\n摘要内容", encoding="utf-8")
        (self.root / "追踪" / "角色状态.md").write_text("第5章 状态", encoding="utf-8")
        result = check_tracking_sync(self.root, 5)
        self.assertTrue(result["章节摘要"])
        self.assertTrue(result["角色状态"])

    def test_sync_missing_chapter(self):
        """追踪文件不包含目标章节时应返回 False。"""
        (self.root / "追踪" / "章节摘要.md").write_text("### 第3章\n摘要")
        result = check_tracking_sync(self.root, 5)
        self.assertFalse(result["章节摘要"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
