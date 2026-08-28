"""Real CLI calibration: exact, author-approved style exceptions never skip gates."""
import json
from pathlib import Path
import subprocess
import sys

import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "check_text.py"
TEXT = "她不是不想回家，而是不敢带着这封信回去。"


def make_book(tmp_path, *, text=TEXT, record=None):
    prose = tmp_path / "正文" / "第001章.md"
    prose.parent.mkdir()
    prose.write_text(text + "\n", encoding="utf-8")
    if record is None:
        record = {"chapter": prose.name, "line": 1, "text": TEXT,
                  "rule": "not-is-comparison", "reason": "区分意愿与恐惧，不是空泛反转",
                  "authority": "作者本轮要求保留该句"}
    (tmp_path / "设定").mkdir(exist_ok=True)
    (tmp_path / "设定/文风豁免.json").write_text(
        json.dumps({"version": 1, "exemptions": [record]}, ensure_ascii=False), encoding="utf-8")
    return prose, record


def run_gate(prose, *args):
    return subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), str(prose),
                           "--gate-state", "--current-chapter", "1", *args],
                          capture_output=True, encoding="utf-8")


class TestStyleExemptions(unittest.TestCase):
    def test_author_approved_exact_rule_is_retained_and_audited(self):
        for flags in [(), ("--gate-report",), ("--ai-patterns", "--gate-report")]:
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                prose, record = make_book(tmp_path)
                before = prose.read_bytes()
                result = run_gate(prose, *flags)
                assert result.returncode == 0, result.stdout + result.stderr
                assert prose.read_bytes() == before
                gate = json.loads((tmp_path / "追踪/门禁/gate_ch1.json").read_text(encoding="utf-8"))
                assert gate["passed"] and gate["blocking"] == 0
                assert gate["style_exemptions"] == [record]
                assert not gate["categories"].get("skipped")

    def test_exception_uses_same_narration_domain_as_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            # Punctuation inside quotes is removed by the existing narration scanner.
            text = '她不是「累了。想睡。」，而是不想让他追问。'
            record = {"chapter": "第001章.md", "line": 1, "text": text,
                      "rule": "not-is-comparison", "reason": "保留引用借口与真实意图的区分",
                      "authority": "作者明确保留该句"}
            prose, _ = make_book(tmp_path, text=text, record=record)
            result = run_gate(prose, "--gate-report")
            assert result.returncode == 0, result.stdout + result.stderr
            gate = json.loads((tmp_path / "追踪/门禁/gate_ch1.json").read_text(encoding="utf-8"))
            assert gate["style_exemptions"] == [record]

    def test_exception_does_not_cover_other_scope(self):
        for change in [{"chapter": "第002章.md"}, {"line": 2},
                {"text": "她不是不想回去，而是不敢回去。"},
                {"rule": "no-only"}]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                prose, record = make_book(tmp_path)
                record.update(change)
                (tmp_path / "设定/文风豁免.json").write_text(
                    json.dumps({"version": 1, "exemptions": [record]}, ensure_ascii=False), encoding="utf-8")
                result = run_gate(prose, "--gate-report")
                assert result.returncode == 1, result.stdout + result.stderr

    def test_exception_never_skips_other_hits(self):
        for suffix in ["\n作为一个AI，我无法完成任务。", "\n本章目标是收回伏笔。",
                "\n没有退路，只有前进。", "\n" + TEXT]:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                prose, _ = make_book(tmp_path, text=TEXT + suffix)
                result = run_gate(prose, "--gate-report")
                assert result.returncode == 1, result.stdout + result.stderr

    def test_invalid_exemption_fails_closed(self):
        for change in [{"rule": "meta-leak"}, {"rule": "refusal-tone"},
                {"rule": "ai-banned-words"}, {"reason": ""},
                {"authority": ""}, {"line": True}, {"line": -1}]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                prose, record = make_book(tmp_path)
                record.update(change)
                (tmp_path / "设定/文风豁免.json").write_text(
                    json.dumps({"version": 1, "exemptions": [record]}, ensure_ascii=False), encoding="utf-8")
                result = run_gate(prose)
                assert result.returncode == 2, result.stdout + result.stderr

    def test_author_banned_word_in_approved_sentence_still_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            prose, _ = make_book(tmp_path)
            settings = tmp_path / "设定"
            settings.mkdir(exist_ok=True)
            (settings / "禁用词.txt").write_text("回家\n", encoding="utf-8")
            result = run_gate(prose, "--gate-report")
            assert result.returncode == 1
            assert "回家" in result.stdout

    def test_budget_still_blocks_with_valid_style_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            prose, _ = make_book(tmp_path)
            assert run_gate(prose, "--min-chars", "500").returncode == 1

    def test_existing_exact_phrase_whitelist_preserves_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            text = "门内似乎有人，她没有推门。"
            prose, _ = make_book(tmp_path, text=text)
            (tmp_path / ".deslop-whitelist").write_text(text + "\n", encoding="utf-8")
            assert run_gate(prose, "--gate-report").returncode == 0

    def test_punctuation_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            prose = tmp_path / "fragment.md"
            prose.write_text("“那我也——”\n“你去。”\n", encoding="utf-8")
            before = prose.read_bytes()
            result = subprocess.run([sys.executable, "-B", str(SCRIPT.with_name("normalize_punct.py")),
                                     str(prose), "--check"], capture_output=True, encoding="utf-8")
            assert result.returncode == 1
            assert prose.read_bytes() == before
            assert not prose.with_suffix(".md.bak").exists()

    def test_explanation_rule_can_be_scoped_without_whitelisting_other_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            text = "这意味着她得自己作出选择。"
            record = {"chapter": "第001章.md", "line": 1, "text": text,
                      "rule": "explainer-tone", "reason": "保留限知视角当场推断",
                      "authority": "作者确认这一句的叙事距离"}
            prose, _ = make_book(tmp_path, text=text, record=record)
            result = run_gate(prose, "--gate-report")
            assert result.returncode == 0, result.stdout + result.stderr
            prose.write_text(text + "\n事实证明，他从未失败。\n", encoding="utf-8")
            assert run_gate(prose, "--gate-report").returncode == 1

    def test_malformed_policy_cannot_silently_pass_clean_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            prose, _ = make_book(tmp_path, text="她把信放在桌上。")
            (tmp_path / "设定/文风豁免.json").write_text("{broken", encoding="utf-8")
            assert run_gate(prose).returncode == 2

    def test_invalid_policy_invalidates_previous_success_record(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            prose, _ = make_book(tmp_path)
            assert run_gate(prose).returncode == 0
            (tmp_path / "设定/文风豁免.json").write_text("{broken", encoding="utf-8")
            assert run_gate(prose).returncode == 2
            gate = json.loads((tmp_path / "追踪/门禁/gate_ch1.json").read_text(encoding="utf-8"))
            assert gate["passed"] is False

    def test_exemption_is_not_discovered_in_another_book_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            outer, _ = make_book(tmp_path)
            inner = tmp_path / "nested-book" / "正文" / outer.name
            inner.parent.mkdir(parents=True)
            inner.write_bytes(outer.read_bytes())
            assert run_gate(inner, "--gate-report").returncode == 1

    def test_invalid_policy_schema_is_rejected(self):
        for payload in [{"version": True, "exemptions": []},
                {"version": 2, "exemptions": []},
                {"version": 1, "exemptions": {}}, []]:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                prose, _ = make_book(tmp_path, text="她把信放在桌上。")
                (tmp_path / "设定/文风豁免.json").write_text(json.dumps(payload), encoding="utf-8")
                assert run_gate(prose).returncode == 2

    def test_scanner_api_cannot_exempt_refusal_even_without_policy_loader(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import check_text
        text = "作为一个AI，我无法完成任务。"
        hits = check_text.scan_blocking_patterns(
            [text], style_exemptions=[{"line": 1, "text": text, "rule": "refusal-tone"}])
        assert any(hit[1] == "refusal-tone" for hit in hits)

if __name__ == "__main__":
    unittest.main()
