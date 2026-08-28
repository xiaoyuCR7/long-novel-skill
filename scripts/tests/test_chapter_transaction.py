"""Real temporary-book transaction and interruption regressions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import check_text
import novel_flow
import resume


class TestChapterTransaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / "book"
        self.book.mkdir()
        result = subprocess.run([sys.executable, str(SCRIPTS / "init_book.py"),
                                 "test", "--dir", str(self.book)],
                                capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.book = self.book / "test"
        spec = importlib.util.find_spec("chapter_transaction")
        self.assertIsNotNone(spec, "executable chapter transaction protocol is missing")
        import chapter_transaction
        self.tx = chapter_transaction

    def prepared(self):
        journal = self.tx.prepare(self.book, 1)
        stage = Path(journal["stage_root"])
        prose = stage / "正文" / "第001章.md"
        prose.write_text("# 第001章\n\n林枝把钥匙放进口袋，推开了门。\n", encoding="utf-8")
        summary = stage / "追踪" / "章节摘要.md"
        summary.write_text("## 近 10 章详记\n### 第1章 门\n" + "\n".join(
            "- {}：{}".format(k, "旧钥匙" if k == "关键实体" else "无")
            for k in ("发生了什么", "状态变化", "伏笔进出", "新登场", "关键实体", "承上", "启下")), encoding="utf-8")
        quota = stage / "追踪" / "节奏配额.md"
        quota.write_text("## A/B/C 配额记录\n| 章节 | 配额 | 触发内容 |\n|---|---|---|\n"
                         "## 事件冷却记录\n| 章节 | 事件类型 | 事件内容 |\n|---|---|---|\n| 1 | world_painting | 开门 |\n"
                         "## 档位记录\n| 章节 | 档位 |\n|---|---|\n| 1 | 中 |\n", encoding="utf-8")
        (stage / "追踪/时间线.md").write_text("| 章节 | 故事内时间 | 事件 | 时间标记 |\n"
                                              "|---|---|---|---|\n| 1 | 上午 | 开门 | 当日 |\n", encoding="utf-8")
        return stage, prose

    def validated(self):
        stage, prose = self.prepared()
        self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
        return stage, prose

    def test_stage_validation_and_commit_share_current_prose_tracking_gate_index(self):
        before = (self.book / "追踪" / "章节摘要.md").read_bytes()
        stage, prose = self.validated()
        self.assertEqual((self.book / "追踪" / "章节摘要.md").read_bytes(), before)
        self.assertFalse((self.book / "正文" / prose.name).exists())
        gate = json.loads((stage / "追踪/门禁/gate_ch1.json").read_text(encoding="utf-8"))
        self.assertTrue(gate["passed"])
        self.assertTrue(gate["rhythm"]["passed"])
        self.assertEqual(gate["chapter_sha256"], hashlib.sha256(prose.read_bytes()).hexdigest())
        self.assertEqual(gate["chapter_file"], prose.name)
        self.tx.commit(self.book, self_review_confirmed=True)
        index = json.loads((self.book / "追踪/entity_index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["旧钥匙"], [1])
        self.assertEqual(resume.check_gate(str(self.book), 1, str(self.book / "正文" / prose.name))[0], [])
        self.assertTrue(check_text.verify_prev_gate(str(self.book / "正文/第002章.md"), 2)[0])
        self.assertIsNone(self.tx.pending_transaction(self.book))

    def test_checkpoint_covers_all_targets_and_absence(self):
        stage, prose = self.prepared()
        journal = self.tx.load_journal(self.book)
        self.assertEqual(len(journal["targets"]), 8)
        self.assertIsNone(journal["before"]["正文/第001章.md"])
        self.assertIsNone(journal["before"]["追踪/门禁/gate_ch1.json"])
        self.assertTrue((Path(journal["checkpoint_root"]) / "追踪/角色状态.md").is_file())

    def test_no_quota_row_commits_without_inventing_a_breakthrough(self):
        stage, prose = self.prepared()
        quota = stage / "追踪/节奏配额.md"
        text = quota.read_text(encoding="utf-8")
        text = text.replace("## 事件冷却记录", "| 1 | - | 没有主线突破 |\n## 事件冷却记录", 1)
        quota.write_text(text, encoding="utf-8")
        self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
        self.tx.commit(self.book, self_review_confirmed=True)
        self.assertIn("| 1 | - |", (self.book / "追踪/节奏配额.md").read_text(encoding="utf-8"))
        self.assertTrue((self.book / "正文" / prose.name).is_file())
        self.assertIsNone(self.tx.pending_transaction(self.book))

    def test_resume_accepts_current_chapter_quota_label_variants_after_commit(self):
        stage, _ = self.prepared()
        quota = stage / "追踪/节奏配额.md"
        quota_text = quota.read_text(encoding="utf-8")
        quota.write_text(quota_text.replace("| 1 |", "| 第1章 |"), encoding="utf-8")
        self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
        self.tx.commit(self.book, self_review_confirmed=True)
        quota = self.book / "追踪/节奏配额.md"
        for label in ("1", "第1章", "  1  ", "第 1 章", "001", "第001章", "\t第 001 章\t"):
            with self.subTest(label=label):
                quota.write_text(quota_text.replace("| 1 |", f"| {label} |"), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / "resume.py"), str(self.book), "--json"],
                    capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["debts"], [])
                self.assertIn("节奏配额已回写", report["notes"])
                self.assertEqual((report["last_chapter"], report["next_chapter"]), (1, 2))

    def test_resume_still_reports_missing_quota_and_other_real_debts(self):
        _, prose = self.validated()
        self.tx.commit(self.book, self_review_confirmed=True)
        quota = self.book / "追踪/节奏配额.md"
        header = "## 档位记录\n| 章节 | 档位 |\n|---|---|\n"
        for row in ("| 0 | 中 |", "| 2 | 中 |", "| 11 | 中 |", "| 第11章 | 中 |",
                    "| 第 002 章 | 中 |", "| 2 | 第1章已完成 |", "正文提到第1章。", ""):
            with self.subTest(row=row):
                quota.write_text(header + row + "\n", encoding="utf-8")
                debts, notes = resume.check_tracking_sync(str(self.book), 1)
                self.assertEqual(debts, ["节奏配额.md 缺第1章记录：补 A/B/C 触发 + 事件 + 档位"])
                self.assertNotIn("节奏配额已回写", notes)

        quota.write_text(header + "| 第001章 | 中 |\n", encoding="utf-8")
        (self.book / "追踪/章节摘要.md").write_text("### 第2章 尚未回写当前章\n", encoding="utf-8")
        (self.book / "追踪/伏笔台账.md").write_text(
            "## 🔴 超期\n| ID | 说明 |\n|---|---|\n| F001 | 尚未处理 |\n", encoding="utf-8")
        (self.book / "正文" / prose.name).write_text("过闸后修改的正文。\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "resume.py"), str(self.book), "--json"],
            capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report["debts"]), 3, report)
        self.assertTrue(any("章节摘要.md 缺第1章条目" in debt for debt in report["debts"]))
        self.assertTrue(any("正文在过闸后有改动" in debt for debt in report["debts"]))
        self.assertTrue(any("F001" in debt and "超期" in debt for debt in report["debts"]))
        self.assertIn("节奏配额已回写", report["notes"])

    def test_scoped_style_policy_is_snapshotted_and_audited_on_commit(self):
        text = "她不是不想回家，而是不敢带着这封信回去。"
        record = {"chapter": "第001章.md", "line": 3, "text": text,
                  "rule": "not-is-comparison", "reason": "保留意愿与恐惧的区别",
                  "authority": "作者要求保留该句"}
        policy = self.book / "设定/文风豁免.json"
        policy.write_text(json.dumps({"version": 1, "exemptions": [record]}, ensure_ascii=False),
                          encoding="utf-8")
        stage, prose = self.prepared()
        self.assertEqual(policy.read_bytes(), (stage / "设定/文风豁免.json").read_bytes())
        prose.write_text("# 第001章\n\n" + text + "\n", encoding="utf-8")
        self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
        self.tx.commit(self.book, self_review_confirmed=True)
        gate = json.loads((self.book / "追踪/门禁/gate_ch1.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["style_exemptions"], [record])
        self.assertTrue(gate["passed"])
        self.assertTrue(gate["rhythm"]["passed"])

    def test_style_policy_cannot_be_added_inside_stage(self):
        stage, _ = self.prepared()
        (stage / "设定/文风豁免.json").write_text(
            json.dumps({"version": 1, "exemptions": []}), encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "stage_changed_outside_transaction"):
            self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")

    def test_style_policy_external_edit_invalidates_validated_transaction(self):
        policy = self.book / "设定/文风豁免.json"
        policy.write_text(json.dumps({"version": 1, "exemptions": []}), encoding="utf-8")
        self.validated()
        policy.write_text(json.dumps({"version": 1, "exemptions": []}) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "state_conflict"):
            self.tx.commit(self.book, self_review_confirmed=True)

    def test_invalid_stage_tracking_does_not_validate_old_canonical_ledger(self):
        stage, _ = self.prepared()
        (stage / "追踪/伏笔台账.md").write_text("broken", encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "tracking"):
            self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
        self.assertFalse((self.book / "正文/第001章.md").exists())

    def test_validation_requires_all_tracking_files(self):
        stage, _ = self.prepared()
        (stage / "追踪/角色状态.md").unlink()
        with self.assertRaisesRegex(self.tx.TransactionError, "missing"):
            self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")

    def test_failed_gate_preserves_canonical_state(self):
        stage, prose = self.prepared()
        prose.write_text("作为一个AI，我无法完成任务。", encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "gate_blocked"):
            self.tx.validate(self.book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
        self.assertFalse((self.book / "正文/第001章.md").exists())

    def test_commit_failure_restores_existing_and_removes_new_files(self):
        before = self.tx.book_hashes(self.book)
        self.validated()
        original = self.tx._install_file
        calls = []
        def fail_once(source, target):
            calls.append(str(target))
            if len(calls) == 5:
                raise OSError("disk fault")
            return original(source, target)
        with patch.object(self.tx, "_install_file", side_effect=fail_once):
            with self.assertRaisesRegex(self.tx.TransactionError, "transaction_incomplete"):
                self.tx.commit(self.book, self_review_confirmed=True)
        self.assertEqual(self.tx.book_hashes(self.book), before)
        self.assertEqual(self.tx.load_journal(self.book)["status"], "recovered")

    def test_process_interruption_persists_journal_and_recovers_on_next_run(self):
        before = self.tx.book_hashes(self.book)
        self.validated()
        original = self.tx._install_file
        calls = []
        def crash(source, target):
            calls.append(str(target))
            original(source, target)
            if len(calls) == 3:
                raise SystemExit("power loss")
        with patch.object(self.tx, "_install_file", side_effect=crash):
            with self.assertRaises(SystemExit):
                self.tx.commit(self.book, self_review_confirmed=True)
        self.assertEqual(self.tx.pending_transaction(self.book)["status"], "committing")
        self.tx.recover(self.book)
        self.assertEqual(self.tx.book_hashes(self.book), before)
        self.tx.prepare(self.book, 1)

    def test_canonical_external_change_cannot_be_overwritten(self):
        self.validated()
        target = self.book / "追踪/角色状态.md"
        target.write_text("author edit", encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "state_conflict"):
            self.tx.commit(self.book, self_review_confirmed=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "author edit")
        self.assertFalse((self.book / "正文/第001章.md").exists())

    def test_recovery_does_not_clobber_external_edits_after_interruption(self):
        self.validated()
        original = self.tx._install_file
        def crash(source, target):
            original(source, target)
            raise SystemExit("power loss")
        with patch.object(self.tx, "_install_file", side_effect=crash):
            with self.assertRaises(SystemExit):
                self.tx.commit(self.book, self_review_confirmed=True)
        target = self.book / "正文/第001章.md"
        target.write_text("author rescue", encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "state_conflict"):
            self.tx.recover(self.book)
        self.assertEqual(target.read_text(encoding="utf-8"), "author rescue")
        self.assertIsNotNone(self.tx.pending_transaction(self.book))

    def test_stage_edit_after_validation_requires_revalidation(self):
        stage, prose = self.validated()
        prose.write_text("new draft", encoding="utf-8")
        with self.assertRaisesRegex(self.tx.TransactionError, "stage_changed"):
            self.tx.commit(self.book, self_review_confirmed=True)

    def test_pending_transaction_blocks_prepare_resume_and_legacy_prepare(self):
        self.prepared()
        with self.assertRaisesRegex(self.tx.TransactionError, "recover"):
            self.tx.prepare(self.book, 2)
        result = subprocess.run([sys.executable, str(SCRIPTS / "resume.py"), str(self.book), "--json"],
                                capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("chapter_transaction.py recover", result.stdout)
        result = novel_flow.cmd_prepare(self.book, 2, object())
        self.assertFalse(result["all_ready"])
        self.assertIn("transaction_incomplete", result["error"])
        acquired, message = novel_flow.acquire_lock(self.book, "daily", 2)
        self.assertFalse(acquired)
        self.assertIn("transaction_incomplete", message)

    def test_commit_detects_edit_to_an_already_installed_target(self):
        self.validated()
        original = self.tx._install_file
        def concurrent_edit(source, target):
            original(source, target)
            if target.name == "entity_index.json":
                (self.book / "正文/第001章.md").write_text("foreign edit", encoding="utf-8")
        with patch.object(self.tx, "_install_file", side_effect=concurrent_edit):
            with self.assertRaisesRegex(self.tx.TransactionError, "state_conflict"):
                self.tx.commit(self.book, self_review_confirmed=True)
        self.assertIsNotNone(self.tx.pending_transaction(self.book))
        self.assertEqual((self.book / "正文/第001章.md").read_text(encoding="utf-8"), "foreign edit")

    def test_gate_hash_detects_same_mtime_edit(self):
        _, prose = self.validated()
        self.tx.commit(self.book, self_review_confirmed=True)
        target = self.book / "正文" / prose.name
        stamp = target.stat().st_mtime
        target.write_text("changed", encoding="utf-8")
        os.utime(str(target), (stamp, stamp))
        self.assertTrue(resume.check_gate(str(self.book), 1, str(target))[0])
        self.assertFalse(check_text.verify_prev_gate(str(self.book / "正文/第002章.md"), 2)[0])

    def test_commit_requires_explicit_review_confirmation(self):
        self.validated()
        with self.assertRaisesRegex(self.tx.TransactionError, "self_review"):
            self.tx.commit(self.book)

    def test_nested_lock_rejects_concurrent_transaction(self):
        with self.tx.transaction_lock(self.book):
            with self.assertRaisesRegex(self.tx.TransactionError, "locked"):
                self.tx.prepare(self.book, 1)

    def test_legacy_acquire_cannot_enter_between_prepare_check_and_journal(self):
        original = self.tx.book_hashes
        result = []
        first = [True]
        def interleave(book):
            if first[0]:
                first[0] = False
                thread = threading.Thread(target=lambda: result.append(
                    novel_flow.acquire_lock(self.book, "daily", 1)), daemon=True)
                thread.start()
                thread.join(3)
                self.assertFalse(thread.is_alive(), "legacy lock acquisition must not hang")
            return original(book)
        with patch.object(self.tx, "book_hashes", side_effect=interleave):
            journal = self.tx.prepare(self.book, 1)
        self.assertEqual(journal["status"], "prepared")
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0][0], "new prepare and legacy writer both acquired ownership")
        self.assertFalse((self.book / "追踪/.flow_lock.json").exists())

    def test_prepare_cannot_enter_during_legacy_pending_check_and_creation(self):
        original = novel_flow._lock_path
        result = []
        def try_prepare():
            try:
                self.tx.prepare(self.book, 1)
                result.append("acquired")
            except self.tx.TransactionError as exc:
                result.append(str(exc))
        def interleave(book):
            thread = threading.Thread(target=try_prepare, daemon=True)
            thread.start()
            thread.join(3)
            self.assertFalse(thread.is_alive(), "new transaction acquisition must not hang")
            return original(book)
        with patch.object(novel_flow, "_lock_path", side_effect=interleave):
            acquired, message = novel_flow.acquire_lock(self.book, "daily", 1)
        self.assertTrue(acquired, message)
        self.assertEqual(result, ["transaction_locked"])
        self.assertIsNone(self.tx.pending_transaction(self.book))


if __name__ == "__main__":
    unittest.main()
