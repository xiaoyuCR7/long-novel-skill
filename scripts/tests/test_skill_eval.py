"""Evaluation infrastructure must not manufacture model or literary success."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))


class TestSkillEval(unittest.TestCase):
    def engine(self):
        self.assertIsNotNone(importlib.util.find_spec("skill_eval"), "evaluation runner is missing")
        import skill_eval
        return skill_eval

    def artifacts(self, run):
        response, trace = run / "response.md", run / "trace.json"
        response.write_text("保留自然内心戏。", encoding="utf-8")
        trace.write_text('[{"tool":"read","path":"passage.md"}]', encoding="utf-8")
        return response, trace

    def directory_link(self, link, target):
        if os.name == "nt":
            result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J",
                                     str(link), str(target)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_catalog_covers_three_distinct_evidence_classes(self):
        engine = self.engine()
        suite = engine.load_suite()
        self.assertEqual(len(suite["cases"]), 24)
        for kind in ("defect", "clean", "generative"):
            self.assertEqual(sum(c["kind"] == kind for c in suite["cases"]), 8)
        self.assertGreaterEqual(len({c["genre"] for c in suite["cases"]}), 3)

    def test_cli_prepares_selected_fiction_suite_without_reviewer_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "fiction-run"
            suite = SCRIPTS.parent / "evals/fictional-world.json"
            command = [sys.executable, "-X", "utf8", str(SCRIPTS / "skill_eval.py"),
                       "prepare", "F03", str(run), "--suite", str(suite)]
            result = subprocess.run(command, capture_output=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["case_id"], "F03")
            self.assertEqual(receipt["model_execution"], "not_run")
            self.assertIn("系统", (run / "prompt.md").read_text(encoding="utf-8"))
            self.assertEqual({p.name for p in run.iterdir()}, {"prompt.md", "constraints.md", "run.json"})

    def test_preparation_contains_raw_inputs_not_answers_and_no_success(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            receipt = engine.prepare_case("D02", run)
            self.assertEqual(receipt["status"], "prepared")
            self.assertEqual(receipt["model_execution"], "not_run")
            self.assertTrue((run / "prompt.md").is_file())
            self.assertFalse((run / "expected.json").exists())
            self.assertNotIn("criteria", (run / "run.json").read_text(encoding="utf-8"))
            with self.assertRaises((ValueError, FileExistsError)):
                engine.prepare_case("D02", run)

    def test_suite_rejects_path_escape_and_duplicate_cases(self):
        engine = self.engine()
        suite = engine.load_suite()
        suite["cases"][0]["files"]["../outside"] = "bad"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.json"
            path.write_text(json.dumps(suite, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                engine.load_suite(path)
            suite["cases"][0]["files"].pop("../outside")
            suite["cases"].append(dict(suite["cases"][0]))
            path.write_text(json.dumps(suite), encoding="utf-8")
            with self.assertRaises(ValueError):
                engine.load_suite(path)

    def test_real_record_requires_artifacts_and_keeps_unreviewed_explicit(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            engine.prepare_case("C02", run)
            with self.assertRaises((ValueError, FileNotFoundError)):
                engine.record_run(run, run / "missing.md", run / "missing.json", "model-id")
            (run / "response.md").write_text("保留自然内心戏。", encoding="utf-8")
            (run / "trace.json").write_text('[{"tool":"read","path":"passage.md"}]', encoding="utf-8")
            record = engine.record_run(run, run / "response.md", run / "trace.json", "model-id")
            self.assertEqual(record["status"], "observed")
            self.assertEqual(record["semantic_review"]["status"], "not_run")
            self.assertEqual(len(record["response"]["sha256"]), 64)
            self.assertIsNone(record["passed"])

    def test_prepare_rejects_linked_ancestor_before_materialization(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target, link = root / "target", root / "link"
            target.mkdir()
            self.directory_link(link, target)
            try:
                with self.assertRaisesRegex(ValueError, "link|reparse"):
                    engine.prepare_case("D02", link / "run")
                self.assertEqual(list(target.iterdir()), [])
            finally:
                link.rmdir() if os.name == "nt" else link.unlink()

    def test_prepare_rejects_new_directory_inside_a_real_book(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp)
            (book / "追踪").mkdir()
            (book / "大纲").mkdir()
            run = book / "new-eval"
            with self.assertRaisesRegex(ValueError, "book"):
                engine.prepare_case("D02", run)
            self.assertFalse(run.exists())

    def test_record_rejects_linked_run_directory_without_writing_observation(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, link = root / "run", root / "link"
            engine.prepare_case("D02", run)
            response, trace = self.artifacts(run)
            self.directory_link(link, run)
            try:
                with self.assertRaisesRegex(ValueError, "link|reparse"):
                    engine.record_run(link, response, trace, "model-id")
                self.assertFalse((run / "observation.json").exists())
            finally:
                link.rmdir() if os.name == "nt" else link.unlink()

    def test_record_rejects_hardlinked_receipt_inputs_and_artifacts(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = root / "baseline"
            engine.prepare_case("D02", baseline)
            self.artifacts(baseline)
            for number, name in enumerate(("run.json", "passage.md", "response.md", "trace.json")):
                with self.subTest(name=name):
                    run = root / str(number)
                    shutil.copytree(baseline, run)
                    response, trace = run / "response.md", run / "trace.json"
                    os.link(str(run / name), str(root / ("alias-" + str(number))))
                    with self.assertRaisesRegex(ValueError, "hard.link"):
                        engine.record_run(run, response, trace, "model-id")
                    self.assertFalse((run / "observation.json").exists())

    def test_record_rejects_malformed_receipt_without_claiming_observation(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            baseline = engine.prepare_case("D02", run)
            response, trace = self.artifacts(run)
            malformed = [{"status": "prepared"}, dict(baseline, schema_version=True),
                         dict(baseline, passed=True), dict(baseline, model_execution="completed"),
                         dict(baseline, case_id=""), dict(baseline, prepared_at="not-a-date"),
                         dict(baseline, input_hashes={"../outside": "a" * 64}),
                         dict(baseline, input_hashes={"prompt.md": "not-a-hash"})]
            for number, receipt in enumerate(malformed):
                with self.subTest(receipt=receipt):
                    current = Path(temp) / ("malformed-" + str(number))
                    shutil.copytree(run, current)
                    response, trace = current / "response.md", current / "trace.json"
                    (current / "run.json").write_text(json.dumps(receipt), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        engine.record_run(current, response, trace, "model-id")
                    self.assertFalse((current / "observation.json").exists())

    def test_record_rejects_duplicate_receipt_json_keys(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            baseline = engine.prepare_case("D02", run)
            response, trace = self.artifacts(run)
            duplicate = '{"schema_version":2,' + json.dumps(baseline)[1:]
            (run / "run.json").write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                engine.record_run(run, response, trace, "model-id")
            self.assertFalse((run / "observation.json").exists())

    def test_record_rejects_input_drift_and_leaves_receipt_unchanged(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            engine.prepare_case("D02", run)
            response, trace = self.artifacts(run)
            before = (run / "run.json").read_bytes()
            (run / "passage.md").write_text("源文本在准备之后被改写。", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input.*changed|input.*mismatch"):
                engine.record_run(run, response, trace, "model-id")
            self.assertEqual((run / "run.json").read_bytes(), before)
            self.assertFalse((run / "observation.json").exists())

    def test_record_requires_identifiable_tool_or_action_records(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            engine.prepare_case("D02", run)
            response, trace = self.artifacts(run)
            for number, invalid in enumerate(([{}], [{"tool": 1}], [{"action": " "}], [{"path": "passage.md"}])):
                with self.subTest(trace=invalid):
                    current = Path(temp) / ("invalid-trace-" + str(number))
                    shutil.copytree(run, current)
                    current_response, current_trace = current / "response.md", current / "trace.json"
                    current_trace.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "trace"):
                        engine.record_run(current, current_response, current_trace, "model-id")
                    self.assertFalse((current / "observation.json").exists())
            trace.write_text('[{"action":"respond","note":"No tool was needed for this response."}]', encoding="utf-8")
            result = engine.record_run(run, response, trace, "model-id")
            self.assertEqual(result["model_execution"], "artifacts_supplied")
            self.assertIsNone(result["passed"])

    def test_suite_rejects_windows_reserved_names_and_case_collisions(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.json"
            suite = engine.load_suite()
            invalid = [{"NUL.txt": "x"}, {"folder/COM1.md": "x"}, {"PROMPT.MD": "x"},
                       {"observation.json": "x"}, {"run.json/nested.md": "x"},
                       {"text.md": "x", "TEXT.MD": "y"}, {"folder": "x", "FOLDER/child.md": "y"},
                       {"./prompt.md": "x"}, {"nested//file.md": "x"}, {"bad?name.md": "x"}]
            for files in invalid:
                with self.subTest(files=files):
                    suite["cases"][0]["files"] = files
                    path.write_text(json.dumps(suite), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        engine.load_suite(path)

    def test_cli_emits_utf8_even_under_ascii_stdio(self):
        fixture = {"documents": [{"id": "证据", "text": "铜钥匙"}],
                   "queries": [{"id": "提问💡", "query": "铜钥匙", "relevant": ["证据"]}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            environment = dict(os.environ, PYTHONIOENCODING="ascii")
            result = subprocess.run([sys.executable, str(SCRIPTS / "skill_eval.py"), "retrieval",
                                     "--fixture", str(path)], capture_output=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.decode("utf-8"))["rows"][0]["id"], "提问💡")

    def test_retrieval_metrics_handle_multiple_gold_evidence_and_misses(self):
        engine = self.engine()
        fixture = {"documents": [{"id": "a", "text": "铜钥匙由林枝保管。"},
                                  {"id": "b", "text": "唐序后来拿走铜钥匙。"}],
                   "queries": [{"id": "q", "query": "铜钥匙", "relevant": ["a", "b"]}]}
        result = engine.retrieval_eval(fixture, top_k=1)
        self.assertEqual(result["recall_at_k"], 0.5)
        self.assertEqual(result["mean_reciprocal_rank"], 1.0)
        self.assertEqual(result["scope"], "synthetic_retrieval_fixture")
        fixture["queries"][0]["query"] = "zzzzzz"
        self.assertEqual(engine.retrieval_eval(fixture)["recall_at_k"], 0.0)


if __name__ == "__main__":
    unittest.main()
