"""Raw-file preservation and no-overwrite regressions using real files."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))


class TestSourceMaterialize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "中文 原稿.txt"
        self.target = self.root / "保留 原稿.md"
        self.assertIsNotNone(importlib.util.find_spec("source_materialize"),
                             "raw source materialization API is missing")
        import source_materialize
        self.api = source_materialize

    def test_preserves_raw_byte_matrix(self):
        for payload in (b"", b"line\n", b"line", b"line\r\nlast\r\n",
                        b"\xef\xbb\xbf" + "旧稿\r\n末句".encode("utf-8"),
                        "中文\n末句\n".encode("utf-8"), b"\xff\xfe\x00\x01"):
            with self.subTest(payload=payload):
                self.source.write_bytes(payload)
                target = self.root / (str(len(list(self.root.iterdir()))) + ".md")
                result = self.api.copy_source(self.source, target)
                self.assertEqual(self.source.read_bytes(), payload)
                self.assertEqual(target.read_bytes(), payload)
                self.assertEqual(result["status"], "copied")
                self.assertEqual(result["representation"], "file_bytes")
                self.assertEqual(result["bytes"], len(payload))
                self.assertEqual(result["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
                self.assertEqual(Path(result["source"]), self.source)
                self.assertEqual(Path(result["destination"]), target)

    def test_existing_identical_is_not_rewritten(self):
        self.source.write_bytes(b"same\r\n")
        self.target.write_bytes(self.source.read_bytes())
        stamp = self.target.stat()
        result = self.api.copy_source(self.source, self.target)
        self.assertEqual(result["status"], "identical")
        self.assertEqual(self.target.stat().st_mtime_ns, stamp.st_mtime_ns)
        self.assertEqual(self.target.stat().st_ino, stamp.st_ino)

    def test_same_source_target_is_identical_without_rewrite(self):
        self.source.write_bytes(b"self")
        stamp = self.source.stat()
        self.assertEqual(self.api.copy_source(self.source, self.source)["status"], "identical")
        self.assertEqual(self.source.stat().st_mtime_ns, stamp.st_mtime_ns)

    def test_different_existing_target_is_never_overwritten(self):
        self.source.write_bytes(b"source")
        self.target.write_bytes(b"user-owned")
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.api.copy_source(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"user-owned")
        self.assertEqual(self.source.read_bytes(), b"source")

    def test_missing_source_and_directory_source_fail_without_target(self):
        for source in (self.source, self.root):
            with self.subTest(source=source):
                with self.assertRaises((OSError, ValueError, RuntimeError)):
                    self.api.copy_source(source, self.target)
                self.assertFalse(self.target.exists())

    def test_missing_destination_parent_and_directory_target_fail(self):
        self.source.write_bytes(b"source")
        for target in (self.root / "missing" / "new.md", self.root):
            with self.subTest(target=target):
                with self.assertRaises((OSError, ValueError, RuntimeError)):
                    self.api.copy_source(self.source, target)
        self.assertFalse((self.root / "missing").exists())

    def make_link(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("OS does not permit real symlinks: " + str(exc))

    def test_source_destination_and_ancestor_links_are_rejected(self):
        self.source.write_bytes(b"source")
        link = self.root / "linked.txt"
        self.make_link(link, self.source)
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.api.copy_source(link, self.target)
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.api.copy_source(self.source, link)
        folder = self.root / "alias"
        self.make_link(folder, self.root, directory=True)
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.api.copy_source(self.source, folder / "new.md")
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.api.copy_source(folder / self.source.name, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.source.read_bytes(), b"source")

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_windows_junction_ancestor_is_rejected(self):
        self.source.write_bytes(b"source")
        folder = self.root / "junction"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(folder), str(self.root)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(ValueError, "link|reparse"):
            self.api.copy_source(folder / self.source.name, self.target)
        with self.assertRaisesRegex(ValueError, "link|reparse"):
            self.api.copy_source(self.source, folder / "target.txt")
        self.assertFalse(self.target.exists())

    def test_source_change_during_copy_fails_before_publication(self):
        self.source.write_bytes(b"original")
        original_fsync = os.fsync
        def mutate(fd):
            original_fsync(fd)
            self.source.write_bytes(b"modified")
        with patch.object(self.api.os, "fsync", side_effect=mutate):
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                self.api.copy_source(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.source.read_bytes(), b"modified")

    def test_same_size_source_change_with_restored_mtime_is_detected(self):
        self.source.write_bytes(b"original")
        stamp = self.source.stat()
        original_fsync = os.fsync
        def mutate(fd):
            original_fsync(fd)
            self.source.write_bytes(b"modified")
            os.utime(self.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with patch.object(self.api.os, "fsync", side_effect=mutate):
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                self.api.copy_source(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_corrupt_written_bytes_fail_readback(self):
        self.source.write_bytes(b"original")
        original_fsync = os.fsync
        def corrupt(fd):
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"corrupt!")
            original_fsync(fd)
        with patch.object(self.api.os, "fsync", side_effect=corrupt):
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                self.api.copy_source(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_flush_failure_and_interrupt_leave_no_success_target(self):
        self.source.write_bytes(b"source")
        for error in (OSError("disk failure"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.api.os, "fsync", side_effect=error):
                    with self.assertRaises(type(error)):
                        self.api.copy_source(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_atomic_publish_race_preserves_new_user_target(self):
        self.source.write_bytes(b"source")
        original_link = os.link
        def race(source, target, **kwargs):
            Path(target).write_bytes(b"user-raced")
            return original_link(source, target, **kwargs)
        with patch.object(self.api.os, "link", side_effect=race):
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                self.api.copy_source(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"user-raced")

    def test_unsupported_hard_link_fails_without_target(self):
        self.source.write_bytes(b"source")
        with patch.object(self.api.os, "link", side_effect=OSError("hard links unsupported")):
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                self.api.copy_source(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_partial_existing_file_is_not_success(self):
        self.source.write_bytes(b"complete source")
        self.target.write_bytes(b"complete")
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.api.copy_source(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"complete")

    def test_cli_success_conflict_and_arguments(self):
        self.source.write_bytes("原稿\r\n末句".encode("utf-8"))
        command = [sys.executable, str(SCRIPTS / "source_materialize.py")]
        copied = subprocess.run(command + [str(self.source), str(self.target)], capture_output=True, encoding="utf-8")
        self.assertEqual(copied.returncode, 0, copied.stderr)
        self.assertEqual(json.loads(copied.stdout)["status"], "copied")
        identical = subprocess.run(command + [str(self.source), str(self.target)], capture_output=True, encoding="utf-8")
        self.assertEqual(json.loads(identical.stdout)["status"], "identical")
        self.target.write_bytes(b"user")
        conflict = subprocess.run(command + [str(self.source), str(self.target)], capture_output=True, encoding="utf-8")
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(conflict.stdout, "")
        self.assertTrue(conflict.stderr)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)

    def materialize_text(self):
        self.assertTrue(callable(getattr(self.api, "materialize_text_source", None)),
                        "conversation-string materialization API is missing")
        return self.api.materialize_text_source(self.source, self.target)

    def test_conversation_json_string_preserves_exact_utf8_representation(self):
        for value in ("", "末句无LF", "首句\r\n末句\r\n", "\ufeff开头BOM\n末句", "末句有LF\n"):
            with self.subTest(value=value):
                self.source.write_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"))
                before = self.source.read_bytes()
                result = self.materialize_text()
                self.assertEqual(self.target.read_bytes(), value.encode("utf-8"))
                self.assertEqual(self.source.read_bytes(), before)
                self.assertEqual(result["representation"], "conversation_string_utf8")
                self.assertEqual(result["sha256"], hashlib.sha256(self.target.read_bytes()).hexdigest())
                self.assertEqual(result["bytes"], len(value.encode("utf-8")))
                self.assertEqual(result["status"], "copied")
                self.target.unlink()

    def test_conversation_json_non_strings_and_malformed_json_are_rejected(self):
        for payload in (b'42', b'null', b'{"text": "not a single string"}', b'[]', b'broken'):
            with self.subTest(payload=payload):
                self.source.write_bytes(payload)
                self.assertTrue(callable(getattr(self.api, "materialize_text_source", None)),
                                "conversation-string materialization API is missing")
                with self.assertRaises((ValueError, RuntimeError)):
                    self.api.materialize_text_source(self.source, self.target)
                self.assertFalse(self.target.exists())

    def test_conversation_json_existing_target_is_identical_or_refused(self):
        self.source.write_bytes(json.dumps("末句").encode("utf-8"))
        self.target.write_bytes("末句".encode("utf-8"))
        stamp = self.target.stat()
        self.assertEqual(self.materialize_text()["status"], "identical")
        self.assertEqual(self.target.stat().st_mtime_ns, stamp.st_mtime_ns)
        self.target.write_bytes(b"user-owned")
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.materialize_text()
        self.assertEqual(self.target.read_bytes(), b"user-owned")

    def test_conversation_json_change_during_write_is_rejected(self):
        self.source.write_bytes(b'"original"')
        self.assertTrue(callable(getattr(self.api, "materialize_text_source", None)),
                        "conversation-string materialization API is missing")
        original_fsync = os.fsync
        def mutate(fd):
            original_fsync(fd)
            self.source.write_bytes(b'"modified"')
        with patch.object(self.api.os, "fsync", side_effect=mutate):
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                self.api.materialize_text_source(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_conversation_json_cli(self):
        self.source.write_bytes(json.dumps("原稿\r\n末句", ensure_ascii=False).encode("utf-8"))
        command = [sys.executable, str(SCRIPTS / "source_materialize.py"),
                   "--text-json", str(self.source), str(self.target)]
        result = subprocess.run(command, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["representation"], "conversation_string_utf8")
        self.assertEqual(self.target.read_bytes(), "原稿\r\n末句".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
