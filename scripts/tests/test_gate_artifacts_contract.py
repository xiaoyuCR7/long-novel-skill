"""The documented machine artifact must match the real writers, not a mock schema."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import check_text
import rhythm_guard


class TestGateArtifactsContract(unittest.TestCase):
    def test_documented_declaration_matches_real_cli(self):
        reference = (SCRIPTS.parent / "references/craft/gate-artifacts-spec.md").read_text(encoding="utf-8")
        example = json.loads(re.search(r"```json\s*\n(.*?)\n```", reference, re.S).group(1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            quota = root / "追踪/节奏配额.md"
            quota.parent.mkdir()
            quota.write_text("## A/B/C 配额记录\n| 章节 | 配额 | 触发内容 |\n|---|---|---|\n"
                             "## 事件冷却记录\n| 章节 | 事件类型 | 事件内容 |\n|---|---|---|\n"
                             "## 档位记录\n| 章节 | 档位 |\n|---|---|\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "rhythm_guard.py"),
                                   "--quota", str(quota), "--chapter", "37", "--declare=-,world_painting,中",
                                   "--gate-state"], capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            actual = json.loads((root / "追踪/门禁/gate_ch37.json").read_text(encoding="utf-8"))
            self.assertEqual(example["rhythm"]["declare"], actual["rhythm"]["declare"])

    def test_reference_example_matches_real_text_and_rhythm_writers(self):
        reference = (SCRIPTS.parent / "references/craft/gate-artifacts-spec.md").read_text(encoding="utf-8")
        example = json.loads(re.search(r"```json\s*\n(.*?)\n```", reference, re.S).group(1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "正文").mkdir()
            (root / "追踪").mkdir()
            prose = root / "正文/第037章.md"
            prose.write_text("她把钥匙收进衣袋。", encoding="utf-8")
            path = check_text.write_gate_state(str(prose), 37, {
                "passed": True, "blocking": 0, "advisory": 0,
                "ai_score": 0.0, "categories": {}})
            rhythm_guard.merge_gate_rhythm(str(root / "追踪/节奏配额.md"), 37,
                                           True, 0, 0, "-,world_painting,中")
            actual = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(set(example), set(actual))
            for key in actual:
                self.assertEqual(type(example[key]), type(actual[key]), key)
            self.assertEqual(set(example["rhythm"]), set(actual["rhythm"]))
            for key in actual["rhythm"]:
                self.assertEqual(type(example["rhythm"][key]), type(actual["rhythm"][key]), key)
            self.assertEqual(actual["chapter_sha256"], hashlib.sha256(prose.read_bytes()).hexdigest())
            self.assertEqual(actual["chapter_file"], prose.name)
            self.assertEqual(Path(path).name, "gate_ch37.json")

    def test_text_pass_does_not_mask_rhythm_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "正文").mkdir()
            (root / "追踪").mkdir()
            prose = root / "正文/第001章.md"
            prose.write_text("门开了。", encoding="utf-8")
            path = check_text.write_gate_state(str(prose), 1, {
                "passed": True, "blocking": 0, "advisory": 0,
                "ai_score": 0.0, "categories": {}})
            rhythm_guard.merge_gate_rhythm(str(root / "追踪/节奏配额.md"), 1,
                                           False, 1, 0, "A,conflict,快")
            self.assertTrue(json.loads(Path(path).read_text(encoding="utf-8"))["passed"])
            self.assertFalse(check_text.verify_prev_gate(str(root / "正文/第002章.md"), 2)[0])
