#!/usr/bin/env python3
"""Behavioral tests for explicit, workspace-local author preferences."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "author_preferences.py"


class AuthorPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.area = self.workspace / ".novel"
        self.state_path = self.area / "author-preferences.json"

    def command(self, action, *args):
        return [sys.executable, str(SCRIPT), action, "--workspace",
                str(self.workspace), *map(str, args)]

    def run_cli(self, action, *args, ok=True):
        result = subprocess.run(self.command(action, *args), capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def payload(self, action, *args):
        return json.loads(self.run_cli(action, *args).stdout.decode("utf-8"))

    def remember(self, text="Prefer concrete verbs", key="diction", scope="global",
                 value="*", kind="prose_style", revision=None, event=None):
        if revision is None:
            revision = self.state()["revision"] if self.state_path.exists() else 0
        args = ["--author-confirmed", "--evidence", "Author explicitly asked to remember this.",
                "--expected-revision", revision, "--scope", scope, "--scope-value", value,
                "--kind", kind, "--key", key, "--text", text]
        if event:
            args += ["--event-id", event]
        return self.payload("remember", *args)

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def test_absent_query_and_check_do_not_create_state(self):
        query = self.payload("query")
        self.assertEqual(query["entries"], [])
        self.assertEqual(query["revision"], 0)
        self.assertEqual(query["omitted"], 0)
        self.assertFalse(self.payload("check")["exists"])
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_workspace_is_required(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "query"], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"--workspace", result.stderr)

    def test_missing_author_confirmation_or_evidence_never_writes(self):
        arguments = ["--scope", "global", "--scope-value", "*", "--kind", "prose_style",
                     "--key", "diction", "--text", "Prefer concrete verbs", "--expected-revision", 0]
        for extra in (["--evidence", "Some inferred pattern"],
                      ["--author-confirmed"], ["--author-confirmed", "--evidence", " "]):
            with self.subTest(extra=extra):
                self.run_cli("remember", *(arguments + extra), ok=False)
                self.assertEqual(list(self.workspace.iterdir()), [])

    def test_remember_preserves_evidence_and_returns_receipt(self):
        receipt = self.remember()
        self.assertEqual(receipt["action"], "remember")
        self.assertEqual(receipt["revision"], 1)
        entry = self.state()["entries"][0]
        self.assertEqual(entry["id"], receipt["id"])
        self.assertEqual(entry["revision"], 1)
        self.assertTrue(entry["active"])
        self.assertEqual(entry["history"][0]["evidence"], "Author explicitly asked to remember this.")
        self.assertEqual([p.name for p in self.area.iterdir()], ["author-preferences.json"])

    def test_scope_matching_and_kind_filtering_are_explicit(self):
        self.remember("Global style")
        self.remember("Book style", scope="book", value="Book A")
        self.remember("Other book style", scope="book", value="Book B")
        self.remember("Genre pacing", key="pacing", scope="genre", value="mystery", kind="story_design")
        self.remember("Workflow review", key="review", scope="workflow", value="revision", kind="workflow")
        self.assertEqual([e["text"] for e in self.payload("query")["entries"]], ["Global style"])
        result = self.payload("query", "--book", "Book A", "--genre", "mystery", "--workflow", "revision")
        self.assertEqual({e["text"] for e in result["entries"]}, {"Book style", "Genre pacing", "Workflow review"})
        self.assertEqual(result["shadowed"], 1)
        filtered = self.payload("query", "--book", "Book B", "--genre", "mystery", "--kind", "story_design")
        self.assertEqual([e["text"] for e in filtered["entries"]], ["Genre pacing"])

    def test_narrow_scope_wins_for_same_kind_and_key(self):
        for scope, value, text in [("global", "*", "Global"), ("genre", "mystery", "Genre"),
                                   ("workflow", "revision", "Workflow"), ("book", "Book A", "Book")]:
            self.remember(text, scope=scope, value=value)
        self.assertEqual(self.payload("query", "--genre", "mystery")["entries"][0]["text"], "Genre")
        result = self.payload("query", "--genre", "mystery", "--workflow", "revision")
        self.assertEqual(result["entries"][0]["text"], "Workflow")
        result = self.payload("query", "--genre", "mystery", "--workflow", "revision", "--book", "Book A")
        self.assertEqual(result["entries"][0]["text"], "Book")

    def test_same_scope_conflict_never_silently_replaces(self):
        self.remember()
        before = self.state_path.read_bytes()
        result = self.run_cli("remember", "--author-confirmed", "--evidence", "New explicit request",
                              "--expected-revision", 1, "--scope", "global", "--scope-value", "*",
                              "--kind", "prose_style", "--key", "diction", "--text", "Prefer abstract nouns", ok=False)
        self.assertIn(b"conflict", result.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_replace_keeps_id_and_source_history_then_forget_revokes(self):
        original = self.remember()
        replacement = self.payload("replace", "--id", original["id"], "--text", "Prefer plain diction",
                                   "--author-confirmed", "--evidence", "Author explicitly revised this preference.",
                                   "--expected-revision", 1)
        self.assertEqual(replacement["id"], original["id"])
        self.assertEqual(replacement["revision"], 2)
        entry = self.state()["entries"][0]
        self.assertEqual(entry["revision"], 2)
        self.assertEqual(entry["history"][0]["text"], "Prefer concrete verbs")
        self.assertEqual(entry["history"][1]["evidence"], "Author explicitly revised this preference.")
        before = self.state_path.read_bytes()
        self.run_cli("forget", "--id", original["id"], "--evidence", "Please forget", "--expected-revision", 2, ok=False)
        self.assertEqual(before, self.state_path.read_bytes())
        self.payload("forget", "--id", original["id"], "--author-confirmed", "--evidence", "Please forget",
                     "--expected-revision", 2)
        self.assertEqual(self.payload("query")["entries"], [])
        self.assertFalse(self.state()["entries"][0]["active"])
        self.assertEqual(self.state()["revision"], 3)

    def test_story_fact_kind_and_unspecific_scope_are_rejected(self):
        args = ["--author-confirmed", "--evidence", "Remember this", "--expected-revision", 0,
                "--key", "fact", "--text", "A character died"]
        self.run_cli("remember", *(args + ["--kind", "story_fact", "--scope", "global", "--scope-value", "*"]), ok=False)
        self.run_cli("remember", *(args + ["--kind", "prose_style", "--scope", "book", "--scope-value", "*"]), ok=False)
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_oversize_entries_are_omitted_whole_and_utf8_output_is_bounded(self):
        oversized = "必须完整保留" * 500
        self.remember(oversized, key="oversized")
        for number in range(7):
            self.remember("偏好使用具体动作描写。" * 8, key="rule-" + str(number))
        response = self.run_cli("query")
        self.assertLessEqual(len(response.stdout), 2048)
        result = json.loads(response.stdout.decode("utf-8"))
        self.assertGreater(result["omitted"], 0)
        self.assertEqual(len(result["entries"]) + result["omitted"], 8)
        full_entries = {entry["id"]: entry for entry in self.state()["entries"]}
        for entry in result["entries"]:
            self.assertEqual(entry["text"], full_entries[entry["id"]]["text"])
            self.assertNotEqual(entry["key"], "oversized")

    def _write_near_limit_state(self, remaining_bytes):
        """A valid portable LF snapshot close to the public 4 MiB state limit."""
        state = {"schema_version": 1, "revision": 200, "entries": [], "events": []}
        for number in range(200):
            entry_id = "%032x" % number
            evidence = "Explicit fixture authorization"
            entry = {"id": entry_id, "revision": 1, "scope": "global", "scope_value": "*",
                     "kind": "prose_style", "key": "fixture-%d" % number, "text": "x" * 10000,
                     "active": True, "history": [{"revision": 1, "action": "remember", "text": "x" * 10000,
                                                  "evidence": evidence, "at": "2026-09-05T00:00:00+00:00"}]}
            receipt = {"event_id": "fixture-event-%d" % number, "action": "remember", "id": entry_id,
                       "revision": number + 1, "entry_revision": 1}
            state["entries"].append(entry)
            state["events"].append({"event_id": receipt["event_id"], "fingerprint": "0" * 64,
                                    "receipt": receipt})
        target_bytes = 4 * 1024 * 1024 - remaining_bytes
        payload = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        padding = target_bytes - len(payload)
        self.assertGreaterEqual(padding, 0)
        for entry, event in zip(state["entries"], state["events"]):
            history = entry["history"][0]
            count = min(padding, 10000 - len(history["evidence"]))
            history["evidence"] += "e" * count
            padding -= count
            request = {"action": "remember", "scope": entry["scope"], "scope_value": entry["scope_value"],
                       "kind": entry["kind"], "key": entry["key"], "text": entry["text"], "id": None,
                       "evidence": history["evidence"]}
            request_bytes = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            event["fingerprint"] = hashlib.sha256(request_bytes).hexdigest()
        self.assertEqual(padding, 0)
        self.area.mkdir()
        self.state_path.write_bytes(json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
        self.assertEqual(self.state_path.stat().st_size, target_bytes)
        self.assertTrue(self.payload("check")["valid"])

    def test_near_limit_success_remains_readable_with_matching_receipt(self):
        self._write_near_limit_state(20000)
        receipt = self.remember(text="Short additional preference", key="additional", revision=200,
                                event="near-limit-success")
        self.assertEqual(receipt["revision"], 201)
        self.assertEqual(self.payload("check")["revision"], receipt["revision"])
        query = self.run_cli("query")
        self.assertEqual(json.loads(query.stdout)["revision"], receipt["revision"])
        self.assertLessEqual(len(query.stdout), 2048)
        self.assertLessEqual(self.state_path.stat().st_size, 4 * 1024 * 1024)

    @unittest.skipUnless(os.name == "nt", "Windows text-mode newline expansion")
    def test_actual_windows_state_size_limit_rejects_without_overwrite(self):
        self._write_near_limit_state(2000)
        before = self.state_path.read_bytes()
        result = self.run_cli("remember", "--author-confirmed", "--evidence", "Explicit additional preference",
                              "--expected-revision", 200, "--event-id", "near-limit-reject", "--scope", "global",
                              "--scope-value", "*", "--kind", "interaction", "--key", "additional", "--text", "Short",
                              ok=False)
        self.assertIn(b"exceeds size limit", result.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.payload("check")["revision"], 200)
        self.assertEqual(self.payload("query")["revision"], 200)
        self.assertEqual([path.name for path in self.area.iterdir()], ["author-preferences.json"])

    def test_malformed_state_is_never_treated_as_absent_or_overwritten(self):
        self.area.mkdir()
        for bad in [b"{broken", b"{}", b'{"schema_version":99}',
                    b'{"schema_version":1,"revision":0,"entries":{},"events":[]}']:
            self.state_path.write_bytes(bad)
            for action in ("query", "check"):
                self.run_cli(action, ok=False)
            self.run_cli("remember", "--author-confirmed", "--evidence", "Remember this",
                         "--expected-revision", 0, "--scope", "global", "--scope-value", "*",
                         "--kind", "prose_style", "--key", "diction", "--text", "Plain", ok=False)
            self.assertEqual(self.state_path.read_bytes(), bad)

    def test_stale_revision_does_not_overwrite_and_missing_revision_is_rejected(self):
        self.remember()
        before = self.state_path.read_bytes()
        args = ["--author-confirmed", "--evidence", "Remember this", "--scope", "global",
                "--scope-value", "*", "--kind", "interaction", "--key", "response", "--text", "Concise"]
        self.run_cli("remember", *args, ok=False)
        result = self.run_cli("remember", *(args + ["--expected-revision", 0]), ok=False)
        self.assertIn(b"revision", result.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_malformed_receipt_is_rejected_before_idempotent_replay(self):
        self.remember(event="author-message-1")
        state = self.state()
        state["events"][0]["receipt"]["entry_revision"] = 99
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        before = self.state_path.read_bytes()
        self.run_cli("check", ok=False)
        self.run_cli("remember", "--author-confirmed", "--evidence", "Author explicitly asked to remember this.",
                     "--expected-revision", 0, "--scope", "global", "--scope-value", "*",
                     "--kind", "prose_style", "--key", "diction", "--text", "Prefer concrete verbs",
                     "--event-id", "author-message-1", ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_concurrent_writers_with_same_revision_cannot_both_commit(self):
        args = ["--author-confirmed", "--evidence", "Explicit request", "--expected-revision", 0,
                "--scope", "global", "--scope-value", "*", "--kind", "interaction", "--text", "Concise"]
        processes = [subprocess.Popen(self.command("remember", *(args + ["--key", key])),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for key in ("first", "second")]
        outputs = [process.communicate(timeout=15) for process in processes]
        self.assertEqual(sorted(process.returncode for process in processes), [0, 2], outputs)
        self.assertEqual(self.state()["revision"], 1)
        self.assertEqual(len(self.state()["entries"]), 1)

    def test_idempotent_event_retry_returns_same_receipt_without_write(self):
        first = self.remember(event="author-message-1", revision=0)
        before = self.state_path.read_bytes()
        again = self.remember(event="author-message-1", revision=0)
        self.assertEqual(first, again)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.run_cli("remember", "--author-confirmed", "--evidence", "Different request",
                     "--expected-revision", 1, "--scope", "global", "--scope-value", "*",
                     "--kind", "prose_style", "--key", "other", "--text", "Other",
                     "--event-id", "author-message-1", ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_state_directory_symlink_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as external:
            try:
                self.area.symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest("OS does not permit symlinks: " + str(error))
            self.run_cli("query", ok=False)
            self.run_cli("remember", "--author-confirmed", "--evidence", "Remember this",
                         "--expected-revision", 0, "--scope", "global", "--scope-value", "*",
                         "--kind", "prose_style", "--key", "diction", "--text", "Plain", ok=False)
            self.assertEqual(list(Path(external).iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows directory junction")
    def test_windows_junction_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as external:
            result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J",
                                     str(self.area), external], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                self.run_cli("query", ok=False)
                self.run_cli("remember", "--author-confirmed", "--evidence", "Remember this",
                             "--expected-revision", 0, "--scope", "global", "--scope-value", "*",
                             "--kind", "prose_style", "--key", "diction", "--text", "Plain", ok=False)
                self.assertEqual(list(Path(external).iterdir()), [])
            finally:
                # rmdir removes this junction, without recursing into its target.
                self.area.rmdir()

    def test_hard_linked_state_is_rejected(self):
        self.remember()
        alias = self.workspace / "state-alias.json"
        os.link(str(self.state_path), str(alias))
        before = alias.read_bytes()
        self.run_cli("query", ok=False)
        self.run_cli("check", ok=False)
        self.assertEqual(alias.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
