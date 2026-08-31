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
from unittest.mock import patch

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
    cmd_prepare,
    cmd_track,
    SNAPSHOT_TRACKING_FILES,
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
        # 完整五表是可恢复快照的最低合同。
        for filename in SNAPSHOT_TRACKING_FILES:
            (self.root / "追踪" / filename).write_text(filename, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_snapshot_creates_backup(self):
        """创建快照应生成备份目录。"""
        ts = create_snapshot(self.root)
        self.assertIsNotNone(ts)
        snap_dir = self.root / "追踪" / ".snapshots" / f"snapshot_{ts}"
        self.assertTrue(snap_dir.exists())
        manifest = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), set(SNAPSHOT_TRACKING_FILES))

    def test_snapshot_failure_does_not_publish_or_remove_existing_snapshot(self):
        """未完成的暂存副本不能覆盖或删除已发布的快照。"""
        old_ts = create_snapshot(self.root)
        old_dir = self.root / "追踪" / ".snapshots" / f"snapshot_{old_ts}"
        with patch("novel_flow.shutil.copy2", side_effect=OSError("disk full")):
            self.assertIsNone(create_snapshot(self.root))
        self.assertTrue(old_dir.is_dir())
        self.assertTrue((old_dir / "manifest.json").is_file())

    def test_create_snapshot_refuses_pending_chapter_transaction(self):
        """快照不能在多文件 commit 的中途读取出自洽但混合的五表。"""
        import chapter_transaction
        with patch.object(chapter_transaction, "pending_transaction",
                          return_value={"status": "committing"}):
            self.assertIsNone(create_snapshot(self.root))

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

    def test_restore_holds_shared_transaction_lock_through_directory_swap(self):
        """追踪目录交换期间共享锁必须连续，不能留下 Windows workaround 空窗。"""
        import chapter_transaction
        ts = create_snapshot(self.root)
        tracking = self.root / "追踪"
        real_replace = os.replace
        observed_swap = []

        def checked_replace(source, destination):
            if Path(source) == tracking:
                observed_swap.append(True)
                with self.assertRaises(chapter_transaction.TransactionError):
                    with chapter_transaction.transaction_lock(self.root):
                        pass
            return real_replace(source, destination)

        with patch("novel_flow.os.replace", side_effect=checked_replace):
            ok, message = restore_snapshot(self.root, ts)
        self.assertTrue(ok, message)
        self.assertTrue(observed_swap)

    def test_restore_recovers_durable_interrupted_directory_move_before_retry(self):
        """进程死在 tracking->backup 后，重跑 rollback 应先恢复再继续。"""
        ts = create_snapshot(self.root)
        tracking = self.root / "追踪"
        backup = self.root / ".tracking-restore-crash"
        stage_root = self.root / ".restore-crash"
        stage_root.mkdir()
        os.replace(tracking, backup)
        (self.root / ".snapshot-restore.json").write_text(json.dumps({
            "version": 1,
            "status": "tracking_moved",
            "snapshot": ts,
            "backup": backup.name,
            "stage": stage_root.name,
        }), encoding="utf-8")

        ok, message = restore_snapshot(self.root, ts)
        self.assertTrue(ok, message)
        self.assertTrue(tracking.is_dir())
        self.assertFalse((self.root / ".snapshot-restore.json").exists())

    def test_restore_failure_recovery_reacquires_root_lock(self):
        """注入第二次 rename 失败时，journal 回滚本身也必须位于互斥区。"""
        import chapter_transaction
        import novel_flow
        ts = create_snapshot(self.root)
        tracking = self.root / "追踪"
        real_replace = os.replace
        real_recover = novel_flow._recover_interrupted_snapshot_restore
        injected = {"done": False}

        def fail_install_once(source, destination):
            source_path = Path(source)
            if (not injected["done"] and Path(destination) == tracking
                    and source_path.parent.name.startswith(".restore-")):
                injected["done"] = True
                raise OSError("injected install failure")
            return real_replace(source, destination)

        def checked_recover(book_dir):
            with self.assertRaises(chapter_transaction.TransactionError):
                with chapter_transaction.transaction_lock(self.root):
                    pass
            return real_recover(book_dir)

        with patch("novel_flow.os.replace", side_effect=fail_install_once), \
             patch("novel_flow._recover_interrupted_snapshot_restore", side_effect=checked_recover):
            ok, message = restore_snapshot(self.root, ts)
        self.assertFalse(ok)
        self.assertIn("injected install failure", message)
        self.assertTrue(tracking.is_dir())

    def test_restore_nonexistent_snapshot(self):
        """恢复不存在的快照应失败。"""
        ok, msg = restore_snapshot(self.root, "99999999_999999")
        self.assertFalse(ok)

    def test_restore_rejects_missing_or_tampered_manifest_before_changing_tracking(self):
        """旧式不完整快照或 hash 损坏必须 fail-closed，不能留下混合版本。"""
        ts = create_snapshot(self.root)
        snap_dir = self.root / "追踪" / ".snapshots" / f"snapshot_{ts}"
        target = self.root / "追踪" / "伏笔台账.md"
        target.write_text("current", encoding="utf-8")
        (snap_dir / "manifest.json").unlink()
        ok, msg = restore_snapshot(self.root, ts)
        self.assertFalse(ok)
        self.assertIn("完整性", msg)
        self.assertEqual(target.read_text(encoding="utf-8"), "current")

        ts = create_snapshot(self.root)
        snap_dir = self.root / "追踪" / ".snapshots" / f"snapshot_{ts}"
        (snap_dir / "伏笔台账.md").write_text("tampered", encoding="utf-8")
        ok, msg = restore_snapshot(self.root, ts)
        self.assertFalse(ok)
        self.assertIn("完整性", msg)
        self.assertEqual(target.read_text(encoding="utf-8"), "current")

    def test_restore_and_track_refuse_pending_chapter_transaction(self):
        """legacy 追踪/回滚路径不得绕过未完成的 chapter transaction。"""
        ts = create_snapshot(self.root)
        import chapter_transaction
        pending = {"status": "prepared"}
        with patch.object(chapter_transaction, "pending_transaction", return_value=pending), \
             patch.object(chapter_transaction, "recovery_command", return_value="recover-command"):
            ok, message = restore_snapshot(self.root, ts)
            tracked = cmd_track(self.root, 1)
        self.assertFalse(ok)
        self.assertIn("transaction_incomplete", message)
        self.assertFalse(tracked["all_done"])
        self.assertIn("transaction_incomplete", tracked["error"])


class TestPrepareQueries(unittest.TestCase):
    """写前检索必须使用章纲/brief 中真实的位置参数。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "追踪").mkdir()
        outline = self.root / "大纲" / "章纲_第2章.md"
        outline.parent.mkdir()
        outline.write_text("本章目标：林枝在旧宅发现暗门\n关键实体：林枝\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_passes_real_positional_query_and_entity(self):
        """semantic 用 BOOK QUERY，图谱用 BOOK NODE，绝不传无效 --chapter。"""
        calls = []
        def run(name, args, book_dir):
            calls.append((name, args))
            return 0, "brief", ""
        with patch("novel_flow.run_script", side_effect=run):
            result = cmd_prepare(self.root, 2, object())
        by_name = {name: args for name, args in calls}
        self.assertEqual(by_name["entity_index.py"], ["semantic", str(self.root), "林枝在旧宅发现暗门"])
        self.assertEqual(by_name["story_graph.py"], ["query", str(self.root), "林枝"])
        self.assertTrue(result["all_ready"])

    def test_prepare_treats_explicit_zero_hits_as_nonblocking_skip(self):
        """已有真实查询但明确零命中是条件跳过，不应阻断写作。"""
        def run(name, args, book_dir):
            if name == "entity_index.py":
                return 1, "未找到相关章节", ""
            if name == "story_graph.py":
                return 0, '{"matched": []}', ""
            return 0, "brief", ""
        with patch("novel_flow.run_script", side_effect=run):
            result = cmd_prepare(self.root, 2, object())
        skipped = {step["name"]: step for step in result["steps"] if step.get("status") == "skipped"}
        self.assertEqual(set(skipped), {"entity_retrieval", "graph_query"})
        self.assertTrue(result["all_ready"])

    def test_prepare_extracts_query_and_entity_from_published_outline_template(self):
        """模板的核心事件段和出场人物列表也必须产出真实查询参数。"""
        outline = self.root / "大纲" / "章纲_第2章.md"
        outline.write_text(
            "## 核心事件\n林枝在旧宅发现暗门。\n\n## 出场人物\n- 主要：林枝\n- 次要：管家\n",
            encoding="utf-8",
        )
        calls = []
        def run(name, args, book_dir):
            calls.append((name, args))
            return 0, "brief", ""
        with patch("novel_flow.run_script", side_effect=run):
            cmd_prepare(self.root, 2, object())
        by_name = {name: args for name, args in calls}
        self.assertEqual(by_name["entity_index.py"], ["semantic", str(self.root), "林枝在旧宅发现暗门。"])
        self.assertEqual(by_name["story_graph.py"], ["query", str(self.root), "林枝"])

    def test_prepare_keeps_invalid_query_invocation_blocking(self):
        """参数错误或崩溃不是零命中，必须使 prepare 失败。"""
        def run(name, args, book_dir):
            if name == "entity_index.py":
                return 2, "", "unrecognized arguments"
            return 0, "brief", ""
        with patch("novel_flow.run_script", side_effect=run):
            result = cmd_prepare(self.root, 2, object())
        self.assertFalse(result["all_ready"])
        entity = next(step for step in result["steps"] if step["name"] == "entity_retrieval")
        self.assertFalse(entity["success"])


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
