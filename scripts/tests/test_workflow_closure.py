"""Executable documentation contracts; literary behavior needs separate agent probes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import chapter_transaction as transaction
from skill_contract import _commands

INTENT_FIELDS = {
    "goal", "state_before", "trigger", "choice_or_cost", "state_after",
    "allowed_events", "forbidden_releases", "emotion_transition", "pacing_tier",
    "quota", "style_authority", "sources", "ending_mode", "hook_question",
}
ROUTES = (
    "references/workflow/revision.md",
    "references/workflow/beat-pipeline.md",
    "references/craft/editorial-team.md",
)


class WorkflowClosureTests(unittest.TestCase):
    def test_documented_rhythm_preflight_blocks_before_prepare_without_writes(self):
        flow = (ROOT / "references/workflow/chapter-loop.md").read_text(encoding="utf-8")
        before_prepare = flow.split("### Step 3B：创建章事务", 1)[0]
        commands = [(script, args) for script, args in _commands(before_prepare)
                    if script == "scripts/rhythm_guard.py" and "--declare" in args]
        self.assertEqual(len(commands), 1, "chapter loop must preflight the declaration before prepare")
        script, arguments = commands[0]
        self.assertNotIn("--gate-state", arguments, "preflight must not write a premature gate")
        with tempfile.TemporaryDirectory() as directory:
            book = Path(directory)
            quota = book / "追踪/节奏配额.md"
            quota.parent.mkdir()
            quota.write_text(
                "## A/B/C 配额记录\n| 章节 | 配额 | 触发内容 |\n|---|---|---|\n"
                "## 事件冷却记录\n| 章节 | 事件类型 | 事件内容 |\n|---|---|---|\n"
                "| 2 | revelation | 第一项秘密 |\n"
                "## 档位记录\n| 章节 | 档位 |\n|---|---|\n| 2 | 中 |\n", encoding="utf-8")
            before = transaction.book_hashes(book)
            replacements = {"{book}": str(book), "{N}": "4", "{配额,事件类型,档位}": "无,revelation,中"}
            args = [arg for arg in arguments]
            for index, argument in enumerate(args):
                for key, value in replacements.items():
                    argument = argument.replace(key, value)
                args[index] = argument
            result = self.run_script(script, args)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("revelation", result.stdout)
            self.assertEqual(transaction.book_hashes(book), before)
            self.assertFalse((book / transaction.AREA).exists())

    def test_outline_template_exposes_closed_ending_mode(self):
        template = (ROOT / "assets/templates/outline-chapter.md").read_text(encoding="utf-8")
        for field in ("ending_mode", "serial", "closed", "finale", "hook_question", "closure_requirements"):
            self.assertIn(field, template)

    def section(self, document, heading):
        text = (ROOT / document).read_text(encoding="utf-8")
        match = re.search(r"(?m)^" + re.escape(heading) + r"[^\n]*\n", text)
        self.assertIsNotNone(match, "missing scoped contract: " + heading)
        remainder = text[match.end():]
        level = len(heading) - len(heading.lstrip("#"))
        return re.split(r"(?m)^#{1," + str(level) + r"} ", remainder, maxsplit=1)[0]

    def test_fragment_polish_does_not_inherit_whole_chapter_acceptance(self):
        # This checks routing boundaries, not whether an LLM preserves emotion well.
        fragment = self.section("assets/agents/anti-ai-editor.md", "## 片段模式")
        self.assertIn("不要求完整 Chapter Brief", fragment)
        self.assertIn("不 commit", fragment)
        self.assertIn("未完成整章核查", fragment)
        whole = self.section("assets/agents/anti-ai-editor.md", "## 完整章节/团队审核")
        self.assertIn("完整 Chapter Brief", whole)
        self.assertIn("BLOCKED", whole)

    def test_shared_tracking_step_routes_old_chapters_before_append_rules(self):
        step = self.section("references/workflow/chapter-loop.md", "## Step 7")
        old = self.section("references/workflow/chapter-loop.md", "### 旧章")
        new = self.section("references/workflow/chapter-loop.md", "### 新章")
        self.assertLess(step.index("### 旧章"), step.index("### 新章"))
        self.assertIn("revision.md", old)
        self.assertIn("Step 3", old)
        for filename in transaction.TRACKING:
            self.assertIn(filename, old, "old-chapter handling must cover all five tables")
        self.assertIn("最新已提交章", old)
        self.assertIn("追加", new)

    def run_script(self, script, arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / script)] + arguments,
            cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
            capture_output=True, encoding="utf-8", timeout=60,
        )

    def test_intent_template_exposes_complete_contract(self):
        intent = json.loads((ROOT / "assets/templates/chapter-intent.json").read_text(encoding="utf-8"))
        self.assertEqual(INTENT_FIELDS - intent.keys(), set())
        self.assertIn(intent["ending_mode"], {"serial", "closed", "finale"})
        for field in ("allowed_events", "forbidden_releases", "sources"):
            self.assertIsInstance(intent[field], list)
        self.assertIsInstance(intent["hook_question"], str)

    def test_isolated_agents_name_every_required_intent_field(self):
        # Deployment copies roles alone: a link to an absent skill is not an input contract.
        for role in ("planning-editor", "novelist", "anti-ai-editor", "consistency-reviewer"):
            with self.subTest(role=role):
                prompt = (ROOT / "assets/agents" / (role + ".md")).read_text(encoding="utf-8")
                missing = {field for field in INTENT_FIELDS if field not in prompt}
                self.assertFalse(missing, "standalone role loses fields: " + str(sorted(missing)))

    def make_book(self, base):
        result = self.run_script("scripts/init_book.py", ["test", "--dir", str(base)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        book = base / "test"
        (book / "正文/第001章_旧标题.md").write_text("# 第001章\n\n林枝把钥匙放在桌上。\n", encoding="utf-8")
        return book

    def fill_stage(self, stage, chapter_file):
        prose = stage / "正文" / chapter_file
        prose.write_text("# 第001章\n\n林枝把钥匙放进口袋，推开了门。\n", encoding="utf-8")
        fields = ("发生了什么", "状态变化", "伏笔进出", "新登场", "关键实体", "承上", "启下")
        (stage / "追踪/章节摘要.md").write_text(
            "## 近 10 章详记\n### 第1章 门\n" + "\n".join(
                "- {}：{}".format(field, "旧钥匙" if field == "关键实体" else "无") for field in fields),
            encoding="utf-8")
        (stage / "追踪/节奏配额.md").write_text(
            "## A/B/C 配额记录\n| 章节 | 配额 | 触发内容 |\n|---|---|---|\n"
            "## 事件冷却记录\n| 章节 | 事件类型 | 事件内容 |\n|---|---|---|\n| 1 | world_painting | 开门 |\n"
            "## 档位记录\n| 章节 | 档位 |\n|---|---|\n| 1 | 中 |\n", encoding="utf-8")
        (stage / "追踪/时间线.md").write_text(
            "| 章节 | 故事内时间 | 事件 | 时间标记 |\n|---|---|---|---|\n| 1 | 上午 | 开门 | 当日 |\n",
            encoding="utf-8")
        return prose

    def route_commands(self, route):
        commands = [(script, args) for script, args in _commands((ROOT / route).read_text(encoding="utf-8"))
                    if script == "scripts/chapter_transaction.py" and args[0] in {"prepare", "validate", "commit"}]
        self.assertEqual([args[0] for _, args in commands], ["prepare", "validate", "commit"], route)
        return commands

    def test_each_alternative_entry_executes_real_old_chapter_transaction(self):
        for route in ROUTES:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                commands = self.route_commands(route)
                base = Path(directory)
                book = self.make_book(base)
                # Intent / Beat / review notes stay outside both canonical book and stage.
                work = base / "work"
                work.mkdir()
                (work / "chapter-intent.json").write_text(
                    (ROOT / "assets/templates/chapter-intent.json").read_text(encoding="utf-8"), encoding="utf-8")
                before = transaction.book_hashes(book)
                replacements = {"{book}": str(book), "{N}": "1", "{下限}": "1", "{上限}": "1000",
                                "{配额,事件类型,档位}": "无,world_painting,中"}
                def execute(command):
                    script, args = command
                    args = [replacements.get(arg, arg) for arg in args]
                    result = self.run_script(script, args)
                    self.assertEqual(result.returncode, 0, route + "\n" + result.stdout + result.stderr)
                    return json.loads(result.stdout)
                prepared = execute(commands[0])
                self.assertEqual(prepared["chapter_file"], "第001章_旧标题.md")
                stage = Path(prepared["stage_root"])
                prose = self.fill_stage(stage, prepared["chapter_file"])
                execute(commands[1])
                self.assertEqual(transaction.book_hashes(book), before)
                # Machine validation is not semantic confirmation.
                with self.assertRaisesRegex(transaction.TransactionError, "self_review_confirmation_required"):
                    transaction.commit(book)
                execute(commands[2])
                self.assertEqual((book / "正文" / prose.name).read_bytes(), prose.read_bytes())
                self.assertEqual([p.name for p in (book / "正文").glob("*.md")], [prose.name])
                gate = json.loads((book / "追踪/门禁/gate_ch1.json").read_text(encoding="utf-8"))
                self.assertEqual(gate["chapter_sha256"], hashlib.sha256(prose.read_bytes()).hexdigest())
                self.assertTrue(gate["rhythm"]["passed"])
                self.assertIsNone(transaction.pending_transaction(book))

    def test_stage_plan_mutation_is_rejected_and_canonical_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            book = self.make_book(Path(directory))
            before = transaction.book_hashes(book)
            prepared = transaction.prepare(book, 1)
            stage = Path(prepared["stage_root"])
            self.fill_stage(stage, prepared["chapter_file"])
            (stage / "大纲").mkdir(exist_ok=True)
            (stage / "大纲/beat-sheet_第001章.md").write_text("uncommitted plan", encoding="utf-8")
            with self.assertRaisesRegex(transaction.TransactionError, "stage_changed_outside_transaction"):
                transaction.validate(book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
            self.assertEqual(transaction.book_hashes(book), before)

    def test_deslop_gate_writers_do_not_invalidate_active_transaction(self):
        document = (ROOT / "references/craft/deslop-engineering.md").read_text(encoding="utf-8")
        commands = [(script, args) for script, args in _commands(document)
                    if script == "scripts/check_text.py" and "--gate-state" in args]
        self.assertGreaterEqual(len(commands), 2)
        with tempfile.TemporaryDirectory() as directory:
            book = self.make_book(Path(directory))
            before = transaction.book_hashes(book)
            prepared = transaction.prepare(book, 1)
            stage = Path(prepared["stage_root"])
            self.fill_stage(stage, prepared["chapter_file"])
            for script, arguments in commands:
                self.assertTrue(arguments[0].startswith("{stage}/正文/"), arguments)
                args = [arg.replace("{stage}", str(stage)).replace("第037章_标题.md", prepared["chapter_file"])
                        for arg in arguments]
                for flag, value in (("--min-chars", "1"), ("--max-chars", "1000"), ("--current-chapter", "1")):
                    if flag in args:
                        args[args.index(flag) + 1] = value
                result = self.run_script(script, args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(transaction.book_hashes(book), before)
            transaction.validate(book, min_chars=1, max_chars=1000, declare="-,world_painting,中")
            transaction.commit(book, self_review_confirmed=True)
            self.assertIsNone(transaction.pending_transaction(book))


if __name__ == "__main__":
    unittest.main()
