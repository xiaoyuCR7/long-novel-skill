#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dashboard 安全编辑契约测试。"""

import hashlib
import http.client
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dashboard import (  # noqa: E402
    EDITABLE_EXTENSIONS,
    MAX_REQUEST_BYTES,
    DEFAULT_HOST,
    DashboardHandler,
    EditableFileError,
    FileConflictError,
    atomic_save,
    file_snapshot,
    recoverable_delete,
    resolve_editable_path,
    revision_for,
    main,
)
import dashboard  # noqa: E402


@contextmanager
def running_dashboard(book_dir, bind_host=None):
    handler = type("TestDashboardHandler", (DashboardHandler,), {"book_dir": book_dir, "bind_host": bind_host})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    server.test_errors = []
    server.handle_error = lambda request, client: server.test_errors.append(sys.exc_info())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("Dashboard HTTP thread did not stop")


def request_json(server, method, path, payload=None, *, raw=None, content_type=None,
                 headers=None, authenticate=True):
    url = "http://127.0.0.1:{}{}".format(server.server_port, path)
    body = raw
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", content_type or "application/json; charset=utf-8")
    if authenticate and method in ("POST", "DELETE"):
        _, session = request_json(server, "GET", "/api/session")
        request.add_header("Origin", "http://127.0.0.1:{}".format(server.server_port))
        request.add_header("X-Dashboard-Token", session.get("token", ""))
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class DashboardPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_resolve_rejects_empty_absolute_escape_and_directory(self):
        for value in ("", str((self.root / "absolute.md").resolve()), "../outside.md", "设定"):
            with self.subTest(value=value), self.assertRaises(EditableFileError):
                resolve_editable_path(self.root, value)

    def test_resolve_accepts_only_documented_extensions(self):
        self.assertEqual(
            EDITABLE_EXTENSIONS,
            {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini"},
        )
        with self.assertRaises(EditableFileError):
            resolve_editable_path(self.root, "正文/程序.py")

    @unittest.skipUnless(hasattr(os, "symlink"), "platform has no symlink support")
    def test_resolve_rejects_symlink_escape(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        link = self.root / "设定"
        try:
            os.symlink(str(outside), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available to this user")
        with self.assertRaises(EditableFileError):
            resolve_editable_path(self.root, "设定/越界.md")

    def test_snapshot_returns_utf8_metadata_and_authoritative_revision(self):
        path = self.root / "设定" / "世界观.md"
        path.parent.mkdir()
        path.write_bytes("旧内容\n".encode("utf-8"))

        snapshot = file_snapshot(self.root, "设定/./世界观.md")

        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["path"], "设定/世界观.md")
        self.assertEqual(snapshot["content"], "旧内容\n")
        self.assertEqual(snapshot["chars"], 4)
        self.assertEqual(snapshot["extension"], ".md")
        self.assertEqual(
            snapshot["revision"],
            hashlib.sha256("旧内容\n".encode("utf-8")).hexdigest(),
        )
        self.assertIsInstance(snapshot["mtime_ns"], int)

    def test_snapshot_rejects_invalid_utf8(self):
        path = self.root / "设定" / "坏文件.md"
        path.parent.mkdir()
        path.write_bytes(b"\xff")
        with self.assertRaises(EditableFileError):
            file_snapshot(self.root, "设定/坏文件.md")

    def test_empty_revision_is_sha256_of_empty_bytes(self):
        self.assertEqual(revision_for(b""), hashlib.sha256(b"").hexdigest())


class DashboardMutationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_file(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return path

    def test_atomic_save_rejects_stale_revision_without_overwrite(self):
        path = self.make_file("正文/第001章.md", "版本一")
        stale = file_snapshot(self.root, "正文/第001章.md")["revision"]
        path.write_bytes("外部修改".encode("utf-8"))

        with self.assertRaises(FileConflictError):
            atomic_save(self.root, "正文/第001章.md", "用户修改", stale)

        self.assertEqual(path.read_text(encoding="utf-8"), "外部修改")
        self.assertFalse((path.parent / ".第001章.md.dashboard-backup").exists())

    def test_invalid_unicode_content_is_rejected_before_any_backup(self):
        path = self.make_file("设定/世界观.md", "旧")
        with self.assertRaises(EditableFileError):
            atomic_save(self.root, "设定/世界观.md", "\ud800", revision_for(path.read_bytes()))
        self.assertEqual(path.read_text(encoding="utf-8"), "旧")
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_unicode_and_null_paths_are_rejected_before_filesystem_use(self):
        for path in ("设定/\ud800.md", "设定/\0.md"):
            with self.subTest(path=repr(path)), self.assertRaises(EditableFileError):
                atomic_save(self.root, path, "正文", revision_for(b""))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_atomic_save_creates_backup_and_returns_new_snapshot(self):
        path = self.make_file("设定/世界观.md", "旧")
        old = file_snapshot(self.root, "设定/世界观.md")

        saved = atomic_save(self.root, "设定/世界观.md", "新内容", old["revision"])

        backup = path.parent / ".世界观.md.dashboard-backup"
        self.assertEqual(path.read_text(encoding="utf-8"), "新内容")
        self.assertEqual(backup.read_text(encoding="utf-8"), "旧")
        self.assertEqual(Path(saved["backup"]), backup)
        self.assertEqual(saved["content"], "新内容")
        self.assertNotEqual(saved["revision"], old["revision"])

    def test_atomic_save_can_safely_create_from_empty_revision(self):
        saved = atomic_save(
            self.root,
            "大纲/新卷.md",
            "第一卷",
            revision_for(b""),
        )
        self.assertEqual(saved["content"], "第一卷")
        self.assertIsNone(saved["backup"])

    def test_atomic_save_cleans_temporary_file_when_replace_fails(self):
        path = self.make_file("设定/世界观.md", "旧")
        old = file_snapshot(self.root, "设定/世界观.md")

        with mock.patch("dashboard.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                atomic_save(self.root, "设定/世界观.md", "新", old["revision"])

        self.assertEqual(path.read_text(encoding="utf-8"), "旧")
        self.assertEqual(list(path.parent.glob(".世界观.md.*.tmp")), [])

    def test_atomic_save_rechecks_revision_immediately_before_replace(self):
        path = self.make_file("设定/竞态.md", "原版")
        old = file_snapshot(self.root, "设定/竞态.md")
        real_fsync = os.fsync
        changed = [False]

        def external_edit_after_first_flush(fd):
            real_fsync(fd)
            if not changed[0]:
                path.write_bytes("外部抢先修改".encode("utf-8"))
                changed[0] = True

        with mock.patch("dashboard.os.fsync", side_effect=external_edit_after_first_flush):
            with self.assertRaises(FileConflictError):
                atomic_save(self.root, "设定/竞态.md", "页面修改", old["revision"])

        self.assertEqual(path.read_text(encoding="utf-8"), "外部抢先修改")
        self.assertEqual(list(path.parent.glob(".竞态.md.*.tmp")), [])

    def test_recoverable_delete_rejects_stale_revision(self):
        path = self.make_file("设定/角色.md", "甲")
        stale = file_snapshot(self.root, "设定/角色.md")["revision"]
        path.write_bytes("乙".encode("utf-8"))
        with self.assertRaises(FileConflictError):
            recoverable_delete(self.root, "设定/角色.md", stale)
        self.assertEqual(path.read_text(encoding="utf-8"), "乙")

    def test_recoverable_delete_moves_content_to_collision_safe_trash(self):
        path = self.make_file("正文/第002章.md", "不能丢")
        revision = file_snapshot(self.root, "正文/第002章.md")["revision"]

        deleted = recoverable_delete(self.root, "正文/第002章.md", revision)

        trash = Path(deleted["trash_path"])
        self.assertFalse(path.exists())
        self.assertTrue(trash.is_file())
        self.assertEqual(trash.read_text(encoding="utf-8"), "不能丢")
        self.assertEqual(trash.parent, self.root / "追踪" / ".dashboard-trash")
        self.assertIn("第002章.md", trash.name)

    def test_recoverable_delete_rechecks_revision_before_move(self):
        path = self.make_file("正文/竞态删除.md", "原版")
        revision = file_snapshot(self.root, "正文/竞态删除.md")["revision"]
        real_trash_directory = dashboard._trash_directory

        def external_edit_before_move(root):
            trash = real_trash_directory(root)
            path.write_bytes("外部抢先修改".encode("utf-8"))
            return trash

        with mock.patch("dashboard._trash_directory", side_effect=external_edit_before_move):
            with self.assertRaises(FileConflictError):
                recoverable_delete(self.root, "正文/竞态删除.md", revision)

        self.assertEqual(path.read_text(encoding="utf-8"), "外部抢先修改")


class DashboardHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        path = self.root / "设定" / "世界观.md"
        path.parent.mkdir(parents=True)
        path.write_bytes("旧世界".encode("utf-8"))

    def tearDown(self):
        self.temp.cleanup()

    def test_get_post_delete_round_trip_preserves_unicode(self):
        query = urllib.parse.urlencode({"path": "设定/世界观.md"})
        with running_dashboard(self.root) as server:
            status, snapshot = request_json(server, "GET", "/api/file?" + query)
            self.assertEqual(status, 200)
            self.assertEqual(snapshot["content"], "旧世界")

            status, saved = request_json(
                server,
                "POST",
                "/api/file",
                {"path": snapshot["path"], "content": "新世界🌙", "revision": snapshot["revision"]},
            )
            self.assertEqual(status, 200)
            self.assertEqual(saved["content"], "新世界🌙")

            status, deleted = request_json(
                server,
                "DELETE",
                "/api/file",
                {"path": saved["path"], "revision": saved["revision"]},
            )
            self.assertEqual(status, 200)
            self.assertTrue(Path(deleted["trash_path"]).exists())

    def test_untrusted_host_cannot_read_private_data_or_session_token(self):
        query = urllib.parse.urlencode({"path": "设定/世界观.md"})
        with running_dashboard(self.root) as server:
            for path in ("/api/file?" + query, "/api/status", "/api/session", "/api/chapters",
                         "/api/quality-trend", "/api/foreshadowing", "/api/file-tree"):
                with self.subTest(path=path):
                    status, data = request_json(server, "GET", path, headers={
                        "Host": "attacker.example:{}".format(server.server_port),
                        "Origin": "http://attacker.example:{}".format(server.server_port),
                    })
                    self.assertEqual(status, 403)
                    self.assertIn("error", data)
                    self.assertNotIn("旧世界", json.dumps(data, ensure_ascii=False))
                    self.assertNotIn("token", data)
            self.assertEqual(server.test_errors, [])

    def test_explicit_non_loopback_hostname_matches_only_configured_host_and_interface(self):
        with running_dashboard(self.root, bind_host="my-dashboard.example") as server:
            host = "my-dashboard.example:{}".format(server.server_port)
            headers = {"Host": host, "Origin": "http://" + host}
            status, session = request_json(server, "GET", "/api/session", headers=headers)
            self.assertEqual(status, 200)
            headers["X-Dashboard-Token"] = session["token"]
            file = self.root / "设定/世界观.md"
            status, _ = request_json(server, "POST", "/api/file", {
                "path": "设定/世界观.md", "content": "授权更新", "revision": revision_for(file.read_bytes()),
            }, headers=headers, authenticate=False)
            self.assertEqual(status, 200)
            status, _ = request_json(server, "GET", "/api/session", headers={"Host": "elsewhere.example"})
            self.assertEqual(status, 403)

    def test_mutations_require_trusted_host_same_origin_and_session_token(self):
        file = self.root / "设定/世界观.md"
        payload = {"path": "设定/世界观.md", "content": "恶意覆盖", "revision": revision_for(file.read_bytes())}
        with running_dashboard(self.root) as server:
            _, session = request_json(server, "GET", "/api/session")
            origin = "http://127.0.0.1:{}".format(server.server_port)
            valid = {"Origin": origin, "X-Dashboard-Token": session.get("token", "")}
            invalid = [
                {}, {"Origin": origin}, {"X-Dashboard-Token": valid["X-Dashboard-Token"]},
                dict(valid, **{"X-Dashboard-Token": "wrong"}),
                dict(valid, Origin="http://attacker.example"),
                dict(valid, Origin="null"), dict(valid, Origin="http://["),
                dict(valid, Origin=origin + "/path"),
                dict(valid, Origin=origin.replace("http:", "https:")),
                dict(valid, Host="attacker.example:{}".format(server.server_port),
                     Origin="http://attacker.example:{}".format(server.server_port)),
            ]
            for method in ("POST", "DELETE"):
                for headers in invalid:
                    with self.subTest(method=method, headers=headers):
                        status, error = request_json(server, method, "/api/file", payload,
                                                     headers=headers, authenticate=False)
                        self.assertEqual(status, 403)
                        self.assertIn("error", error)
                        self.assertEqual(file.read_text(encoding="utf-8"), "旧世界")
            self.assertEqual(server.test_errors, [])
            self.assertEqual(list(file.parent.iterdir()), [file])

    def test_delete_rejects_surrogate_path_without_creating_trash(self):
        with running_dashboard(self.root) as server:
            status, data = request_json(server, "DELETE", "/api/file", {
                "path": "设定/\ud800.md", "revision": revision_for(b""),
            })
            self.assertEqual(status, 400)
            self.assertIn("error", data)
            self.assertFalse((self.root / "追踪").exists())
            self.assertEqual(server.test_errors, [])

    def test_malformed_duplicate_host_and_cross_origin_session_are_structured_403(self):
        with running_dashboard(self.root) as server:
            for host in ("", "[", "127.0.0.1:bad", "user@127.0.0.1", "127.0.0.1/path",
                         "127.0.0.1:1", "127.0.0.1:99999", "127.0.0.1,evil.example"):
                with self.subTest(host=host):
                    status, data = request_json(server, "GET", "/api/session", headers={"Host": host})
                    self.assertEqual(status, 403)
                    self.assertIn("error", data)
            status, data = request_json(server, "GET", "/api/session", headers={"Origin": "http://evil.example"})
            self.assertEqual(status, 403)
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.putrequest("GET", "/api/session")
            connection.putheader("Host", "evil.example")
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            self.assertIn("error", json.loads(response.read()))
            connection.close()
            self.assertEqual(server.test_errors, [])

    def test_session_token_is_stable_per_server_and_distinct_across_servers(self):
        with running_dashboard(self.root) as one, running_dashboard(self.root) as two:
            status, first = request_json(one, "GET", "/api/session")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(first["token"]), 32)
            self.assertEqual(first, request_json(one, "GET", "/api/session")[1])
            self.assertNotEqual(first, request_json(two, "GET", "/api/session")[1])

    def test_surrogate_json_content_or_path_returns_400_without_side_effects(self):
        file = self.root / "设定/世界观.md"
        with running_dashboard(self.root) as server:
            for path, content in (("设定/世界观.md", "\ud800"), ("设定/\ud800.md", "新"),
                                  ("设定/\0.md", "新")):
                with self.subTest(path=repr(path), content=repr(content)):
                    status, error = request_json(server, "POST", "/api/file", {
                        "path": path, "content": content, "revision": revision_for(file.read_bytes())})
                    self.assertEqual(status, 400)
                    self.assertIn("error", error)
                    self.assertEqual(file.read_text(encoding="utf-8"), "旧世界")
                    self.assertEqual(list(file.parent.iterdir()), [file])
            self.assertEqual(server.test_errors, [])

    def test_stale_post_and_delete_return_409_without_overwrite(self):
        query = urllib.parse.urlencode({"path": "设定/世界观.md"})
        with running_dashboard(self.root) as server:
            _, snapshot = request_json(server, "GET", "/api/file?" + query)
            stale = "0" * 64
            status, error = request_json(
                server,
                "POST",
                "/api/file",
                {"path": snapshot["path"], "content": "覆盖", "revision": stale},
            )
            self.assertEqual(status, 409)
            self.assertIn("外部修改", error["error"])
            self.assertEqual((self.root / "设定" / "世界观.md").read_text(encoding="utf-8"), "旧世界")

            status, _ = request_json(
                server,
                "DELETE",
                "/api/file",
                {"path": snapshot["path"], "revision": stale},
            )
            self.assertEqual(status, 409)
            self.assertTrue((self.root / "设定" / "世界观.md").exists())

    def test_bad_json_media_type_and_oversized_body_are_rejected(self):
        with running_dashboard(self.root) as server:
            status, error = request_json(server, "POST", "/api/file", raw=b"{")
            self.assertEqual(status, 400)
            self.assertNotIn("Traceback", json.dumps(error))

            status, _ = request_json(
                server, "POST", "/api/file", raw=b"{}", content_type="text/plain"
            )
            self.assertEqual(status, 415)

            captured = io.StringIO()
            with mock.patch("sys.stderr", captured):
                status, _ = request_json(
                    server,
                    "POST",
                    "/api/file",
                    raw=b" " * (MAX_REQUEST_BYTES + 1),
                )
            self.assertEqual(status, 413)
            self.assertNotIn("Traceback", captured.getvalue())
            self.assertEqual(server.test_errors, [])

    def test_security_and_routing_status_codes(self):
        cases = [
            ("../outside.md", 403),
            ("设定/程序.py", 415),
        ]
        with running_dashboard(self.root) as server:
            for relative, expected in cases:
                with self.subTest(relative=relative):
                    query = urllib.parse.urlencode({"path": relative})
                    status, error = request_json(server, "GET", "/api/file?" + query)
                    self.assertEqual(status, expected)
                    self.assertIn("error", error)

            status, _ = request_json(server, "GET", "/api/unknown")
            self.assertEqual(status, 404)
            status, _ = request_json(server, "POST", "/api/unknown", {})
            self.assertEqual(status, 404)

    @unittest.skipUnless(hasattr(os, "symlink"), "platform has no symlink support")
    def test_symlink_access_returns_403(self):
        outside = self.root.parent / (self.root.name + "-http-outside")
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        link = self.root / "正文"
        try:
            os.symlink(str(outside), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available to this user")
        with running_dashboard(self.root) as server:
            query = urllib.parse.urlencode({"path": "正文/越界.md"})
            status, _ = request_json(server, "GET", "/api/file?" + query)
            self.assertEqual(status, 403)


class DashboardCliTests(unittest.TestCase):
    def test_default_host_is_numeric_loopback(self):
        self.assertEqual(DEFAULT_HOST, "127.0.0.1")

    def test_non_loopback_host_prints_exposure_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "正文").mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = ["dashboard.py", str(root), "--host", "0.0.0.0", "--port", "0"]
            with mock.patch.object(sys, "argv", argv), mock.patch(
                "dashboard.http.server.HTTPServer", side_effect=OSError("stop")
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                result = main()
            self.assertEqual(result, 3)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertIn("警告", combined)
            self.assertIn("网络", combined)


class DashboardFrontendContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required to execute the original browser JavaScript")
    def test_original_javascript_editor_behaviors(self):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("dashboard_frontend.test.js"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_editor_has_accessible_controls_and_conflict_contract(self):
        root = Path(__file__).resolve().parents[2]
        html = (root / "assets" / "dashboard" / "index.html").read_text(encoding="utf-8")

        for fragment in (
            'id="file-editor"',
            'id="save-file"',
            'id="delete-file"',
            'id="file-dirty"',
            'id="conflict-banner"',
            'aria-label="文件内容编辑器"',
            "let openFile",
            "res.status===409",
            "beforeunload",
            "confirm(",
            "openFile.path",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, html)

    def test_conflict_and_delete_failures_do_not_clear_editor_buffer(self):
        root = Path(__file__).resolve().parents[2]
        html = (root / "assets" / "dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn("showConflict", html)
        self.assertIn("keepEditorBuffer", html)
        self.assertIn("openFile.dirty", html)

    def test_runner_and_readme_include_dashboard_safety_contract(self):
        root = Path(__file__).resolve().parents[2]
        runner = (root / "scripts" / "tests" / "run_tests.py").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn('"test_dashboard"', runner)
        for fragment in (
            "127.0.0.1",
            ".md/.txt/.json/.yaml/.yml/.toml/.ini",
            "409",
            "os.replace",
            ".dashboard-backup",
            "追踪/.dashboard-trash/",
            "--host",
            "身份认证",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, readme)


if __name__ == "__main__":
    unittest.main()
