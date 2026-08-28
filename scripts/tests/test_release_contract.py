#!/usr/bin/env python3
"""Repository-level release metadata and CI contract tests."""

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
TESTS_DIR = SCRIPTS_DIR / "tests"
for path in (SCRIPTS_DIR, TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config  # noqa: E402
import run_tests  # noqa: E402


class TestReleaseContract(unittest.TestCase):
    def test_style_exemption_regressions_are_in_default_runner(self):
        self.assertIn("test_style_exemptions", run_tests.TEST_MODULES)
        suite = unittest.defaultTestLoader.loadTestsFromName("test_style_exemptions")
        self.assertGreater(suite.countTestCases(), 0)

    def test_public_versions_are_v8(self):
        self.assertEqual(config.SKILL_VERSION, "8.0.0")
        self.assertEqual(json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))["version"], "8.0.0")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cli = (ROOT / "novel-cli.py").read_text(encoding="utf-8")
        self.assertIn("version: 8.0.0", skill)
        self.assertIn("**v8.0.0**", readme)
        self.assertIn("## v8.0.0", changelog)
        self.assertIn("v8.0.0", cli)

    def test_skill_json_counts_match_repository(self):
        metadata = json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))["metadata"]
        expected = {
            "scripts_count": len(list(SCRIPTS_DIR.glob("*.py"))),
            "tests_count": unittest.defaultTestLoader.loadTestsFromNames(run_tests.TEST_MODULES).countTestCases(),
            "craft_files_count": len(list((ROOT / "references" / "craft").glob("*.md"))),
            "workflow_files_count": len(list((ROOT / "references" / "workflow").glob("*.md"))),
            "reference_files_count": len(list((ROOT / "references").rglob("*.md"))),
        }
        for key, value in expected.items():
            self.assertEqual(metadata.get(key), value, "stale {}".format(key))

        server = (ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
        tools_count = len(re.findall(r"^\s*@mcp\.tool\(", server, flags=re.MULTILINE))
        skill_json = json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(skill_json["mcp_server"]["tools_count"], tools_count)

    def test_readme_distinguishes_evidence_levels_without_claiming_automation_is_enough(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for heading in ("已实现并自动验证", "有条件能力与降级", "建议性或人工判断"):
            self.assertIn(heading, readme)
        self.assertNotIn("全面超越两个开源 skill", readme)
        self.assertIn("不替代真实创作样本的匿名评审与长期连载检验", readme)
        self.assertNotIn("evaluations/", readme)

    def test_ci_runs_full_contract_and_version_checks(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/tests/run_tests.py", workflow)
        self.assertIn("python scripts/skill_contract.py .", workflow)
        self.assertIn("python scripts/version_sync.py --check", workflow)

    def test_release_is_self_contained_without_local_evaluation_artifacts(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/tests/run_tests.py", workflow)
        self.assertIn("python scripts/skill_contract.py .", workflow)
        self.assertIn("python scripts/version_sync.py --check", workflow)
        self.assertNotIn("evaluations/", workflow)

    def test_release_version_job_configures_python_with_a_with_block(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        version_job = workflow.split("  full-test:", 1)[0]
        self.assertRegex(
            version_job,
            r"uses: actions/setup-python@v5\s+with:\s+python-version: '3\.10'",
        )

    def test_release_notes_point_to_the_actual_changelog(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertNotIn("请查看 SKILL.md 中的更新日志", workflow)
        self.assertIn("CHANGELOG.md", workflow)


if __name__ == "__main__":
    unittest.main()
