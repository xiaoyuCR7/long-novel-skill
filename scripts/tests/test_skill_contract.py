#!/usr/bin/env python3
"""Tests for the deterministic SKILL.md contract audit."""

import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


from skill_contract import audit_skill, referenced_local_paths


class TestSkillContract(unittest.TestCase):
    def _write_skill(self, root, body):
        root.mkdir()
        (root / "SKILL.md").write_text(body, encoding="utf-8")

    def test_rejects_unsupported_top_level_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo-skill"
            self._write_skill(
                root,
                "---\n"
                "name: demo-skill\n"
                "description: Use when checking a demo skill.\n"
                "activation: automatic\n"
                "---\n"
                "Body.\n",
            )

            report = audit_skill(root)

        self.assertEqual(report.errors, ["unsupported_frontmatter:activation"])

    def test_reports_missing_explicit_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo-skill"
            self._write_skill(
                root,
                "---\n"
                "name: demo-skill\n"
                "description: Use when checking a demo skill.\n"
                "---\n"
                "Read `references/missing.md`.\n"
                "Run `python scripts/missing.py`.\n",
            )

            report = audit_skill(root)

        self.assertEqual(
            report.errors,
            [
                "missing_path:references/missing.md",
                "missing_path:scripts/missing.py",
            ],
        )

    def test_accepts_dot_as_the_current_skill_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo-skill"
            self._write_skill(
                root,
                "---\n"
                "name: demo-skill\n"
                "description: Use when checking a demo skill.\n"
                "---\n"
                "Body.\n",
            )
            previous_directory = os.getcwd()
            try:
                os.chdir(str(root))
                report = audit_skill(Path("."))
            finally:
                os.chdir(previous_directory)

        self.assertEqual(report.errors, [])

    def test_linked_worktree_uses_the_common_repository_name(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            common_git = base / "long-novel-skill" / ".git"
            gitdir = common_git / "worktrees" / "skill-superiority"
            gitdir.mkdir(parents=True)
            root = base / "checkouts" / "skill-superiority"
            root.parent.mkdir()
            self._write_skill(
                root,
                "---\n"
                "name: long-novel-skill\n"
                "description: Use when checking a linked worktree.\n"
                "---\n"
                "Body.\n",
            )
            (root / ".git").write_text(
                "gitdir: " + str(gitdir) + "\n",
                encoding="utf-8",
            )

            report = audit_skill(root)

        self.assertEqual(report.errors, [])

    def test_plain_directory_still_requires_name_to_match_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "renamed-folder"
            self._write_skill(
                root,
                "---\n"
                "name: long-novel-skill\n"
                "description: Use when checking an ordinary skill directory.\n"
                "---\n"
                "Body.\n",
            )

            report = audit_skill(root)

        self.assertEqual(report.errors, ["name_mismatch:renamed-folder"])

    def test_ignores_url_path_fragments_inside_backticks(self):
        paths = referenced_local_paths(
            "See `https://example.com/references/guide.md` for details."
        )

        self.assertEqual(paths, set())

    def test_python_command_only_tracks_the_executable_script(self):
        paths = referenced_local_paths(
            "Run `python scripts/tool.py --output assets/generated.json`."
        )

        self.assertEqual(paths, {"scripts/tool.py"})

    def test_python_command_tracks_script_with_a_url_argument(self):
        paths = referenced_local_paths(
            "Run `python scripts/tool.py --source https://example.com/data.json`."
        )

        self.assertEqual(paths, {"scripts/tool.py"})

    def test_repository_skill_contract_is_clean(self):
        repository_root = Path(__file__).resolve().parents[2]

        report = audit_skill(repository_root)

        self.assertEqual(report.errors, [])

    def test_legacy_basename_prefers_unique_descendant_in_its_own_run(self):
        from skill_contract import _resolve_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "evaluations/runs/first/run-log.md"
            local = document.parent / "blind/reviewer-provenance.json"
            other = root / "evaluations/runs/second/blind/reviewer-provenance.json"
            for path in (local, other):
                path.parent.mkdir(parents=True)
                path.write_text("{}", encoding="utf-8")
            self.assertEqual(_resolve_reference(root, document, "reviewer-provenance.json"),
                             "evaluations/runs/first/blind/reviewer-provenance.json")

    def test_root_basename_resolution_ignores_nested_worktree_copies(self):
        from skill_contract import _resolve_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "README.md"
            source = root / "scripts/tool.py"
            worktree_copy = root / ".worktrees/candidate/scripts/tool.py"
            document.write_text("`tool.py`", encoding="utf-8")
            for path in (source, worktree_copy):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            resolved = _resolve_reference(root, document, "tool.py")

        self.assertEqual(resolved, "scripts/tool.py")

    def test_root_basename_outside_link_is_reported_without_crashing(self):
        from unittest import mock
        from skill_contract import _resolve_reference
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "demo-skill"
            document = root / "README.md"
            linked = root / "nested/tool.py"
            outside = base / "outside/tool.py"
            for path in (document, linked, outside):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            real_resolve = Path.resolve

            def resolve_like_outside_link(path, *args, **kwargs):
                if path == linked:
                    return outside
                return real_resolve(path, *args, **kwargs)

            with mock.patch.object(Path, "resolve", resolve_like_outside_link):
                resolved = _resolve_reference(root, document, "tool.py")

        self.assertEqual(resolved, "!outside:tool.py")

    def test_legacy_ambiguous_descendants_remain_unresolved(self):
        from skill_contract import _resolve_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "evaluations/runs/first/run-log.md"
            for child in ("blind-a", "blind-b"):
                path = document.parent / child / "reviewer-provenance.json"
                path.parent.mkdir(parents=True)
                path.write_text("{}", encoding="utf-8")
            self.assertEqual(_resolve_reference(root, document, "reviewer-provenance.json"),
                             "evaluations/runs/first/reviewer-provenance.json")

    def test_explicit_missing_path_does_not_use_descendant_fallback(self):
        from skill_contract import _resolve_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "evaluations/runs/first/run-log.md"
            path = document.parent / "blind/reviewer-provenance.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(_resolve_reference(root, document,
                             "evaluations/runs/first/reviewer-provenance.json"),
                             "evaluations/runs/first/reviewer-provenance.json")

    def _linked_fixture(self, directory, reference):
        root = Path(directory) / "demo-skill"
        self._write_skill(root, "---\nname: demo-skill\ndescription: Use when testing.\n---\n"
                          "Read [guide](references/guide.md).\n")
        (root / "references").mkdir()
        (root / "references/guide.md").write_text(reference, encoding="utf-8")
        return root

    def test_audits_missing_second_level_relative_markdown_and_backtick_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._linked_fixture(directory, "See [next](nested/missing.md) and `other.md`.\n")
            errors = audit_skill(root).errors
        self.assertIn("missing_path:references/nested/missing.md", errors)
        self.assertIn("missing_path:references/other.md", errors)

    def test_audits_fenced_python_subcommands_and_flags_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._linked_fixture(directory, '```bash\npython scripts/tool.py wrong "{book}"\n'
                                       'python scripts/tool.py build "{book}" --typo\n```\n')
            (root / "scripts").mkdir()
            (root / "scripts/tool.py").write_text(
                "import argparse\nraise RuntimeError('DO NOT EXECUTE')\n"
                "p = argparse.ArgumentParser()\ns = p.add_subparsers()\n"
                "b = s.add_parser('build')\nb.add_argument('book')\nb.add_argument('--json', action='store_true')\n",
                encoding="utf-8")
            errors = audit_skill(root).errors
        self.assertTrue(any("unknown_subcommand:scripts/tool.py:wrong" in x for x in errors), errors)
        self.assertTrue(any("unknown_flag:scripts/tool.py:--typo" in x for x in errors), errors)

    def test_rejects_a_flag_from_another_subcommand(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._linked_fixture(directory, '`python scripts/tool.py read --write-only`')
            (root / "scripts").mkdir()
            (root / "scripts/tool.py").write_text(
                "import argparse\np = argparse.ArgumentParser()\ns = p.add_subparsers()\n"
                "a = s.add_parser('read')\nb = s.add_parser('write')\nb.add_argument('--write-only')\n",
                encoding="utf-8")
            errors = audit_skill(root).errors
        self.assertTrue(any("unknown_flag:scripts/tool.py:--write-only" in x for x in errors), errors)

    def test_dynamic_project_paths_urls_and_argument_values_are_not_repo_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._linked_fixture(directory, '`追踪/章节摘要.md` `{book}/chapter.md` '
                                       '[web](https://example.com/references/no.md)\n'
                                       '```bash\npython scripts/tool.py "{book}" --output assets/generated.json\n```')
            (root / "scripts").mkdir()
            (root / "scripts/tool.py").write_text(
                "import argparse\np = argparse.ArgumentParser()\np.add_argument('book')\np.add_argument('--output')\n",
                encoding="utf-8")
            errors = audit_skill(root).errors
        self.assertEqual(errors, [])

    def test_critical_route_cannot_be_orphaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._linked_fixture(directory, "Body.\n")
            (root / "references/workflow").mkdir()
            (root / "references/workflow/chapter-loop.md").write_text("critical", encoding="utf-8")
            errors = audit_skill(root).errors
        self.assertIn("unreachable_route:references/workflow/chapter-loop.md", errors)

    def _command_fixture(self, directory, commands, declarations):
        root = self._linked_fixture(directory, "```bash\n" + commands + "\n```\n")
        (root / "scripts").mkdir()
        (root / "scripts/tool.py").write_text(
            "import argparse\nraise RuntimeError('never execute')\n" + declarations, encoding="utf-8")
        return root

    def test_readme_is_an_audit_root_for_invalid_commands_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._command_fixture(directory, "", "p=argparse.ArgumentParser()\np.add_argument('--ok')\n")
            (root / "README.md").write_text(
                "[missing](references/readme-missing.md)\n```bash\npython scripts/tool.py --typo value\n```",
                encoding="utf-8")
            errors = audit_skill(root).errors
        self.assertIn("missing_path:references/readme-missing.md", errors)
        self.assertTrue(any("unknown_flag:scripts/tool.py:--typo" in error for error in errors), errors)

    def test_missing_required_flags_and_positional_arguments_are_rejected(self):
        declarations = ("p=argparse.ArgumentParser()\ns=p.add_subparsers(dest='command', required=True)\n"
                        "a=s.add_parser('validate')\na.add_argument('book')\n"
                        "a.add_argument('--transaction', required=True)\na.add_argument('--min-chars', required=True)\n")
        for command, expected in (("validate book", "--transaction"),
                                  ("validate --transaction tx --min-chars 10", "book")):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                root = self._command_fixture(directory, "python scripts/tool.py " + command, declarations)
                errors = audit_skill(root).errors
                self.assertTrue(any("missing_required:" in error and expected in error for error in errors), errors)

    def test_missing_flag_values_and_nargs_are_rejected(self):
        declarations = ("p=argparse.ArgumentParser()\np.add_argument('book')\np.add_argument('--chapter', required=True)\n"
                        "p.add_argument('--pair', nargs=2)\np.add_argument('--items', nargs='+')\n")
        for tail, expected in (("book --chapter", "--chapter"),
                               ("book --chapter --pair a b", "--chapter"),
                               ("book --chapter 1 --pair a", "--pair"),
                               ("book --chapter 1 --items", "--items")):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as directory:
                root = self._command_fixture(directory, "python scripts/tool.py " + tail, declarations)
                errors = audit_skill(root).errors
                self.assertTrue(any("missing_value:" in error and expected in error for error in errors), errors)

    def test_unique_abbreviation_and_placeholder_values_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._command_fixture(directory,
                'python scripts/tool.py revise "{book}" --desc "{描述}" --items "{item1}" "{item2}"',
                "p=argparse.ArgumentParser()\ns=p.add_subparsers(dest='command')\na=s.add_parser('revise')\n"
                "a.add_argument('book')\na.add_argument('--description', required=True)\n"
                "a.add_argument('--items', nargs='+')\na.add_argument('--optional', nargs='?')\n"
                "a.add_argument('extras', nargs='*')\n")
            self.assertEqual(audit_skill(root).errors, [])

    def test_disabled_or_ambiguous_abbreviation_is_rejected(self):
        for constructor, extra in (("allow_abbrev=False", ""),
                                   ("", "p.add_argument('--descending')\n")):
            with self.subTest(constructor=constructor), tempfile.TemporaryDirectory() as directory:
                root = self._command_fixture(directory, "python scripts/tool.py --desc value",
                    "p=argparse.ArgumentParser(" + constructor + ")\np.add_argument('--description')\n" + extra)
                self.assertTrue(audit_skill(root).errors)

    def test_real_transaction_required_arguments_are_checked_statically(self):
        from skill_contract import _audit_command
        root = Path(__file__).resolve().parents[2]
        for args, expected in ((["prepare", "book", "--chapter"], "missing_value"),
                               (["validate", "book"], "missing_required")):
            with self.subTest(args=args):
                errors = _audit_command(root, root / "SKILL.md", "scripts/chapter_transaction.py", args)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_argparse_declaration_helper_is_extracted_without_executing_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._command_fixture(directory, "python scripts/tool.py stats chapter.md --output report.md",
                "p=argparse.ArgumentParser()\ns=p.add_subparsers(dest='command')\n"
                "def add_files(parser, with_output=True):\n"
                "    parser.add_argument('files', nargs='+')\n"
                "    if with_output:\n        parser.add_argument('--output')\n"
                "a=s.add_parser('stats')\nadd_files(a)\n")
            self.assertEqual(audit_skill(root).errors, [])

    def test_text_fences_are_proposals_not_executable_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._linked_fixture(directory, "接口提案（未实现）：\n```text\npython scripts/future.py --plan\n```\n")
            self.assertEqual(audit_skill(root).errors, [])

    def test_dashboard_and_outline_change_routes_have_distinct_stop_points(self):
        root = Path(__file__).resolve().parents[2]
        for file in ("SKILL.md", "references/workflow/task-router.md"):
            content = (root / file).read_text(encoding="utf-8")
            self.assertIn("Dashboard", content)
            self.assertIn("补纲/改纲", content)
        router = (root / "references/workflow/task-router.md").read_text(encoding="utf-8")
        self.assertIn("backup", router)
        self.assertIn("cascade", router)
        self.assertIn("anchor", router)
        self.assertIn("rebuild", router)

    def test_scene_example_does_not_introduce_unlicensed_clues(self):
        root = Path(__file__).resolve().parents[2]
        content = (root / "references/craft/scene-rendering.md").read_text(encoding="utf-8")
        before, after = content.split("### Before：", 1)[1].split("### After：", 1)
        after = after.split("## 去 AI", 1)[0]
        for clue in ("银盐", "收据", "母亲身旁"):
            if clue in after:
                self.assertIn(clue, before, "unauthorized clue: " + clue)

    def test_chapter_workflows_use_staged_gates_and_the_executable_transaction(self):
        from skill_contract import _commands
        root = Path(__file__).resolve().parents[2]
        loop = (root / "references/workflow/chapter-loop.md").read_text(encoding="utf-8")
        commands = list(_commands(loop))
        actions = {args[0] for script, args in commands if script == "scripts/chapter_transaction.py"}
        self.assertTrue({"prepare", "validate", "commit", "recover"}.issubset(actions))
        # Declaration-only preflight is read-only and must precede prepare;
        # actual prose gates still write only the staged gate state.
        prepare_at = next(i for i, (script, args) in enumerate(commands)
                          if script == "scripts/chapter_transaction.py" and args[0] == "prepare")
        preflights = [(i, args) for i, (script, args) in enumerate(commands)
                      if script == "scripts/rhythm_guard.py" and "--chapter-file" not in args]
        self.assertEqual(len(preflights), 1)
        for index, args in preflights:
            self.assertLess(index, prepare_at)
            self.assertNotIn("--gate-state", args)
            self.assertIn("--declare", args)
            self.assertEqual(args[args.index("--quota") + 1], "{book}/追踪/节奏配额.md")
        gates = [(script, args) for script, args in commands[prepare_at:]
                 if script in ("scripts/check_text.py", "scripts/rhythm_guard.py")]
        self.assertEqual({script for script, _ in gates},
                         {"scripts/check_text.py", "scripts/rhythm_guard.py"})
        for script, args in gates:
            self.assertIn("--gate-state", args)
            self.assertTrue(any(value.startswith("{stage}/正文/") for value in args), script)
            tracking_flag = "--ledger" if script.endswith("check_text.py") else "--quota"
            self.assertTrue(args[args.index(tracking_flag) + 1].startswith("{stage}/追踪/"))
        daily = (root / "references/workflow/daily-failfast.md").read_text(encoding="utf-8")
        self.assertIn('python scripts/chapter_transaction.py status "{book}"', daily)
        self.assertIn('python scripts/chapter_transaction.py recover "{book}"', daily)

    def test_advanced_arc_guidance_does_not_restore_fixed_emotion_rules(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "references/craft/emotional-arc.md").read_text(encoding="utf-8")
        for retired in ("同一种需求连续供应不超过 3 章", "≥4 次转换：**禁止**",
                        "日常章必有微型钩子", "连续 2 章以上读者弃书",
                        "持续时间超过 500 字 = 读者疲劳", "眼泪是最廉价的悲伤",
                        "台词越直白，", "全程中档到快档，不插入慢档",
                        "章尾情绪状态决定追读率", "情绪换台的数学依据"):
            self.assertFalse(retired in text, "retired prescription: " + retired)
        for mode in ("ending_mode", "closed", "finale"):
            self.assertIn(mode, text)

    def test_pacing_review_uses_staged_workflow_and_closed_endings(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "references/craft/pacing-review.md").read_text(encoding="utf-8")
        for retired in ("写正文 → 标点归一化", "写入 `追踪/门禁/pacing_review_ch",
                        "章末悬念为「无」且非慢档收尾章",
                        "日常章也应有微型阻碍", "要求下章补回进度"):
            self.assertFalse(retired in text, "retired workflow: " + retired)
        for required in ("ending_mode", "closed", "finale", "stage", "validate", "commit", "工程外"):
            self.assertIn(required, text)

    def test_pacing_and_hooks_does_not_restore_unconditional_hook_requirements(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "references/craft/pacing-and-hooks.md").read_text(encoding="utf-8")
        # These are known conflicting instructions, not a prose-quality score.
        for retired in ("每章必须至少有 1 个钩子", "最低钩子数",
                        "（没有 = 水章）", "（不受影响 = 注水）",
                        "不受影响就该删或并", "三要素缺一不可",
                        "必须有羁绊深化、风土人情、微型伏笔"):
            self.assertNotIn(retired, text)
        for required in ("ending_mode", "serial", "closed", "finale", "hook_question",
                         "rhythm_guard.py", "同时触发 ≥2 项 = 越界"):
            self.assertIn(required, text)

    def test_reverse_brake_respects_closure_without_changing_quota_rules(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "references/craft/reverse-brake.md").read_text(encoding="utf-8")
        for retired in ("每章必须新增至少一个未解决的问题", "非冲突场景必须至少埋一个微型伏笔",
                        "每解决 1 个问题，新增 1.5 个问题", "需要补伏笔或删除",
                        "必须暴露一个更大的隐患", "必须引出一个更大的疑问"):
            self.assertFalse(retired in text, "retired prescription: " + retired)
        for required in ("ending_mode", "closed", "finale", "hook_question",
                         "触发 A 后，接下来 2 章不得再触发 A",
                         "触发 B 后，接下来 1 章不得再触发 B",
                         "触发 C 后，接下来 3 章不得再触发 C",
                         "每 5 章必须至少出现一次 `bond_deepening` 或 `world_painting`"):
            self.assertIn(required, text)

    def test_quality_checklist_respects_previous_ending_and_functional_pacing(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "references/craft/quality-checklist.md").read_text(encoding="utf-8")
        # Guard the reproduced entry-point conflicts, not literary quality.
        for retired in ("本章开头 10% 内要接住上一章的钩子", "卷末有快档爆发",
                        "全卷低压 = 无聊"):
            self.assertFalse(retired in text, "retired checklist rule: " + retired)
        before = text.split("## 三、单章写前", 1)[1].split("## 四、单章写后", 1)[0]
        handoff = before.split("- [ ] 3.", 1)[1].split("- [ ] 4.", 1)[0]
        for required in ("ending_mode", "serial", "closed", "finale", "10%",
                         "承接已完成的结果", "不擅自续章"):
            self.assertIn(required, handoff)
        for required in ("快档 ≤2-3 次", "慢档每 3-4 章至少 1 章", "占比 ≥60%",
                         "间隔至少 2 章", "同时触发 ≥2 项 = 越界", "低压本身不等于无聊",
                         "卷末爆发仅在已授权", "不能口头豁免"):
            self.assertIn(required, text)
        publishing = text.split("## 六、发布前", 1)[1].split("## 检查流程总览", 1)[0]
        opening = publishing.split("- [ ] 10.", 1)[1]
        for required in ("serial", "closed/finale", "不倒推新增钩子"):
            self.assertIn(required, opening)

    def test_cross_review_respects_endings_and_shared_repair_budget(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "references/workflow/cross-review.md").read_text(encoding="utf-8")
        for retired in ("若答不上来 = 追读动力不足", "`追踪/cross_review/",
                        "轮次记入 JSON** 的 `round` 字段，跨章累计",
                        "第31章注水，整章无信息推进"):
            self.assertFalse(retired in text, "retired cross-review rule: " + retired)
        for required in ("ending_mode", "serial", "closed", "finale", "hook_question",
                         "closure_requirements", "最小结尾契约", "不给大纲、人物卡、创作意图",
                         "不提供预定评分", "不因没有下一章问题判失败", "正文内部一致性",
                         "工程外", "不写入 stage", "同一任务", "机器、人工与跨审",
                         "共享最多 2 轮实际修复", "第三次改稿", "送审轮数", "停止"):
            self.assertIn(required, text)
        self.assertIn("P0 是「发出去就翻车」的级别，必须立即改、改完才发", text)

    def test_publishing_requests_route_to_a_safe_cover_workflow(self):
        repository_root = Path(__file__).resolve().parents[2]
        skill_text = (repository_root / "SKILL.md").read_text(encoding="utf-8")
        reference = repository_root / "references" / "workflow" / "publishing-pack.md"

        for keyword in ("简介", "标签", "封面", "上架物料"):
            self.assertIn(keyword, skill_text)
        self.assertIn("references/workflow/publishing-pack.md", skill_text)
        self.assertTrue(reference.is_file())

        reference_text = reference.read_text(encoding="utf-8")
        self.assertIn("image_tool_available", reference_text)
        self.assertIn("image_tool_unavailable", reference_text)
        self.assertIn("不得声称已生成", reference_text)


if __name__ == "__main__":
    unittest.main()
