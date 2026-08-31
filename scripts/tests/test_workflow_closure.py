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
    "on_page_requirements",
}
ROUTES = (
    "references/workflow/revision.md",
    "references/workflow/beat-pipeline.md",
    "references/craft/editorial-team.md",
)
TEMPORAL_P1_SEMANTICS = (
    r"正文结果(?:已可|可以|已经)判定.{0,100}"
    r"整体因果(?:也)?(?:已可|可以|已经)判定.{0,120}"
    r"动作链.{0,20}可行.{0,160}"
    r"读者.{0,80}(?:(?:无法|不能).{0,20}重建.{0,60}窗口消耗|"
    r"(?:无法|不能).{0,20}(?:判断|确定).{0,80}(?:时间证据|时间).{0,80}"
    r"(?:改变|影响|导致).{0,80}后续选择).{0,100}P1"
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
        for field in ("allowed_events", "forbidden_releases", "sources", "on_page_requirements"):
            self.assertIsInstance(intent[field], list)
        self.assertIsInstance(intent["hook_question"], str)

    def test_intent_template_exposes_on_page_requirements(self):
        intent = json.loads((ROOT / "assets/templates/chapter-intent.json").read_text(encoding="utf-8"))
        self.assertEqual(intent.get("on_page_requirements"), [])

    def test_isolated_agents_name_every_required_intent_field(self):
        # Deployment copies roles alone: a link to an absent skill is not an input contract.
        for role in ("planning-editor", "novelist", "anti-ai-editor", "consistency-reviewer"):
            with self.subTest(role=role):
                prompt = (ROOT / "assets/agents" / (role + ".md")).read_text(encoding="utf-8")
                missing = {field for field in INTENT_FIELDS if field not in prompt}
                self.assertFalse(missing, "standalone role loses fields: " + str(sorted(missing)))

    def test_editorial_team_carries_on_page_requirements(self):
        brief = self.section("references/craft/editorial-team.md", "## 唯一 Chapter Brief 契约")
        for marker in ("on_page_requirements", "来源明确要求", "正文可直接指认"):
            with self.subTest(marker=marker):
                self.assertIn(marker, brief)

    def test_chapter_loop_allows_empty_on_page_requirements_when_source_has_none(self):
        step = self.section("references/workflow/chapter-loop.md", "### Step 3A：形成章意图（blocking）")
        self.assertIn("来源没有明确要求时填 []", step)
        self.assertIn("已提取条目无法定位来源证据", step)

    def test_scene_rendering_defines_shared_delivery_audit(self):
        document = "references/craft/scene-rendering.md"
        section_markers = {
            "### 正文证据": ("逐项", "可定位", "自然", "无歧义", "不要求照抄", "隐含推断"),
            "### 转折桥": ("改变前", "可见触发", "具体行动", "即时后果", "保留", "不得新造"),
            "### 动作预算": ("串行", "并行", "倒计时", "必要验收", "无法容纳"),
            "### 物件归属": ("持有者或位置", "唯一", "主体", "动词", "不得新增"),
        }
        for heading, markers in section_markers.items():
            with self.subTest(section=heading):
                section = self.section(document, heading)
                for marker in markers:
                    self.assertIn(marker, section)
        audit = self.section(document, "## 场景交付审计卡")
        for marker in ("on_page_requirements", "关键事实或因果无法判定", "blocking/P0", "文学细腻度",
                       "P1/P2", "不阻断", "私有", "不输出", "不固定四段式"):
            with self.subTest(marker=marker):
                self.assertIn(marker, audit)
        custody = self.section(document, "### 物件归属")
        self.assertIn("再次依赖该物件前", custody)

    def test_scene_rendering_defines_temporal_action_loop(self):
        temporal = self.section("references/craft/scene-rendering.md", "### 时间行动闭环")
        for marker in (
            "合法时间来源", "现场已建立事实", "时间证据", "改变后续行动",
            "哪一步", "消耗了窗口", "不设最低报秒次数",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, temporal)
        audit = self.section("references/craft/scene-rendering.md", "## 场景交付审计卡")
        temporal_normalized = " ".join(temporal.split())
        audit_normalized = " ".join(audit.split())
        self.assertRegex(temporal_normalized, r"(?:不得|不能).{0,40}(?:新增|擅造).{0,30}(?:计时器|测时)")
        self.assertRegex(audit_normalized, r"擅造未授权时间来源.{0,80}(?:blocking/P0|P0)")
        self.assertRegex(audit_normalized, r"动作链可行.{0,80}(?:窗口消耗|时间消耗).{0,80}P1")
        self.assertRegex(audit_normalized, r"时长.{0,80}(?:压力递进|自然度).{0,80}P2")
        self.assertNotRegex(temporal_normalized, r"(?:每隔|每过)\s*\d+\s*(?:秒|分钟)")
        self.assertNotRegex(temporal_normalized, r"每(?:个|项)动作.{0,30}(?:必须|都要).{0,30}(?:报时|时钟|阻力)")
        self.assertNotRegex(temporal_normalized, r"至少\s*\d+\s*(?:次|个).{0,20}(?:报时|时间锚点|报告)")

    def test_scene_rendering_keeps_temporal_actions_only_when_they_add_function(self):
        detail = self.section("references/craft/scene-rendering.md", "### 情绪兑现与回合详略")
        for marker in ("时间消耗", "过程进展", "风险变化", "必要验收", "新增功能"):
            with self.subTest(marker=marker):
                self.assertIn(marker, detail)
        self.assertIn("才删去或并入前句", detail)

    def test_novelist_closes_temporal_action_loop_without_stopwatch_template(self):
        preflight = self.section("assets/agents/novelist.md", "## 输出前私有预检")
        preflight_flat = " ".join(preflight.split())
        for marker in (
            "合法时间来源", "不新造计时器", "时间证据", "改变后续行动",
            "哪一步消耗", "不设报秒次数",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, preflight)
        self.assertRegex(preflight_flat, r"动作链可行.{0,100}(?:窗口消耗|后果选择).{0,80}P1")
        self.assertRegex(
            preflight_flat,
            r"正文结果与整体因果已可判定.{0,100}动作链可行但仅剩窗口消耗或时间证据如何导致后续选择无法重建.{0,80}P1",
        )
        self.assertRegex(preflight_flat, r"时长与选择已可重建.{0,80}(?:压力递进|自然度).{0,80}P2")
        self.assertNotRegex(preflight_flat, r"(?:每隔|每过)\s*\d+\s*(?:秒|分钟)")
        self.assertNotRegex(preflight_flat, r"每(?:个|项)动作.{0,30}(?:必须|都要).{0,30}(?:报时|时钟|阻力)")
        self.assertNotRegex(preflight_flat, r"至少\s*\d+\s*(?:次|个).{0,20}(?:报时|时间锚点|报告)")

    def test_consistency_reviewer_separates_temporal_p0_p1_and_p2(self):
        prompt = (ROOT / "assets/agents/consistency-reviewer.md").read_text(encoding="utf-8")
        checklist = self.section("assets/agents/consistency-reviewer.md", "## 必查清单（不得省略）")
        prompt_flat = " ".join(prompt.split())
        checklist_flat = " ".join(checklist.split())
        for marker in ("合法时间来源", "时间证据", "改变后续行动", "哪一步消耗"):
            with self.subTest(marker=marker):
                self.assertIn(marker, checklist)
        self.assertRegex(prompt_flat, r"未授权.{0,40}(?:计时器|测时来源).{0,80}P0")
        self.assertRegex(prompt_flat, r"动作链可行.{0,100}(?:窗口消耗|后果选择).{0,80}P1")
        self.assertRegex(
            prompt_flat,
            r"正文结果与整体因果已可判定.{0,100}动作链可行但仅剩窗口消耗或时间证据如何导致后续选择无法重建.{0,80}P1",
        )
        self.assertRegex(prompt_flat, r"时长与选择已可重建.{0,80}(?:压力递进|自然度).{0,80}P2")
        self.assertNotRegex(checklist_flat, r"(?:每隔|每过)\s*\d+\s*(?:秒|分钟)")
        self.assertNotRegex(checklist_flat, r"每(?:个|项)动作.{0,30}(?:必须|都要).{0,30}(?:报时|时钟|阻力)")
        self.assertNotRegex(checklist_flat, r"至少\s*\d+\s*(?:次|个).{0,20}(?:报时|时间锚点|报告)")

    def test_chapter_loop_repairs_temporal_perceptibility_inside_existing_audit(self):
        audit = self.section("references/workflow/chapter-loop.md", "## 交付前场景审计（blocking）")
        audit_compact = "".join(audit.split())
        for marker in (
            "合法时间来源", "时间证据", "改变后续行动", "哪一步消耗",
            "不新增持久 schema", "不设最低报秒次数",
        ):
            with self.subTest(marker=marker):
                self.assertIn("".join(marker.split()), audit_compact)
        self.assertIn("关键事实或整体因果无法判定", audit_compact)
        self.assertNotIn("关键事实或因果无法判定", audit_compact)
        self.assertRegex(audit_compact, r"未授权.{0,40}(?:计时器|测时来源).{0,80}(?:blocking/P0|P0)")
        self.assertRegex(audit_compact, TEMPORAL_P1_SEMANTICS)
        counterexamples = (
            "正文结果尚无法判定，但整体因果已可判定，动作链可行；读者仍无法重建窗口消耗，归 P1。",
            "正文结果并非已可判定，整体因果已可判定，动作链可行；读者仍无法重建窗口消耗，归 P1。",
            "正文结果已可判定，整体因果并非已可判定，动作链可行；读者仍无法重建窗口消耗，归 P1。",
        )
        for counterexample in counterexamples:
            with self.subTest(counterexample=counterexample):
                self.assertNotRegex("".join(counterexample.split()), TEMPORAL_P1_SEMANTICS)
        self.assertRegex(audit_compact, r"时长与选择已可重建.{0,80}(?:压力递进|自然度).{0,80}P2")
        self.assertNotRegex(audit_compact, r"(?:每隔|每过)\s*\d+\s*(?:秒|分钟)")
        self.assertNotRegex(audit_compact, r"每(?:个|项)动作.{0,30}(?:必须|都要).{0,30}(?:报时|时钟|阻力)")
        self.assertNotRegex(audit_compact, r"至少\s*\d+\s*(?:次|个).{0,20}(?:报时|时间锚点|报告)")

    def test_editorial_spawn_carries_temporal_contract_to_reviewer(self):
        step5 = self.section("references/workflow/editorial-spawn.md", "### Step 5：并行审核（反AI编辑 + 连载核实官）")
        self.assertIn("[TO: consistency-reviewer]", step5)
        reviewer_message = step5.split("[TO: consistency-reviewer]", 1)[1].split("```", 1)[0]
        reviewer_compact = "".join(reviewer_message.split())
        for marker in ("合法时间来源", "时间证据", "改变后续行动", "哪一步消耗", "不另起第二套修复轮次"):
            with self.subTest(scope="review", marker=marker):
                self.assertIn("".join(marker.split()), reviewer_compact)
        self.assertIn("关键事实或整体因果无法判定", reviewer_compact)
        self.assertNotIn("关键事实或因果无法判定", reviewer_compact)
        self.assertRegex(reviewer_compact, r"未授权.{0,40}(?:计时器|测时来源).{0,80}(?:blocking/P0|P0)")
        self.assertRegex(reviewer_compact, TEMPORAL_P1_SEMANTICS)
        self.assertRegex(reviewer_compact, r"时长与选择已可重建.{0,80}(?:压力递进|自然度).{0,80}P2")
        self.assertNotRegex(reviewer_compact, r"(?:每隔|每过)\s*\d+\s*(?:秒|分钟)")
        self.assertNotRegex(reviewer_compact, r"每(?:个|项)动作.{0,30}(?:必须|都要).{0,30}(?:报时|时钟|阻力)")
        self.assertNotRegex(reviewer_compact, r"至少\s*\d+\s*(?:次|个).{0,20}(?:报时|时间锚点|报告)")
        step6 = self.section("references/workflow/editorial-spawn.md", "### Step 6：汇总判定（总编辑裁决）")
        step6_compact = "".join(step6.split())
        self.assertIn("关键事实或整体因果无法判定", step6_compact)
        self.assertNotIn("关键事实或因果无法判定", step6_compact)
        self.assertRegex(step6_compact, r"未授权.{0,40}(?:计时器|测时来源).{0,80}(?:blocking/P0|P0)")
        self.assertRegex(step6_compact, TEMPORAL_P1_SEMANTICS)
        self.assertRegex(step6_compact, r"时长与选择已可重建.{0,80}(?:压力递进|自然度).{0,80}P2")
        self.assertNotRegex(step6_compact, r"(?:每隔|每过)\s*\d+\s*(?:秒|分钟)")
        self.assertNotRegex(step6_compact, r"每(?:个|项)动作.{0,30}(?:必须|都要).{0,30}(?:报时|时钟|阻力)")
        self.assertNotRegex(step6_compact, r"至少\s*\d+\s*(?:次|个).{0,20}(?:报时|时间锚点|报告)")

    @staticmethod
    def _normalize_contract(value):
        return re.sub(r"\s+", "", value)

    def _temporal_contract_carriers(self):
        canonical = self.section("references/craft/scene-rendering.md", "### 时间行动闭环")
        novelist = self.section("assets/agents/novelist.md", "## 输出前私有预检")
        reviewer_checklist = self.section("assets/agents/consistency-reviewer.md", "## 必查清单（不得省略）")
        reviewer_severity = self.section("assets/agents/consistency-reviewer.md", "## 报告格式")
        chapter_audit = self.section("references/workflow/chapter-loop.md", "## 交付前场景审计（blocking）")
        step5 = self.section("references/workflow/editorial-spawn.md", "### Step 5：并行审核（反AI编辑 + 连载核实官）")
        reviewer_message = step5.split("[TO: consistency-reviewer]", 1)[1].split("```", 1)[0]
        step6 = self.section("references/workflow/editorial-spawn.md", "### Step 6：汇总判定（总编辑裁决）")
        return {
            "canonical": self._normalize_contract(canonical),
            "novelist": self._normalize_contract(novelist),
            "reviewer": self._normalize_contract(reviewer_checklist + reviewer_severity),
            "chapter_audit": self._normalize_contract(chapter_audit),
            "editorial_step5_message": self._normalize_contract(reviewer_message),
            "editorial_step6": self._normalize_contract(step6),
        }

    @staticmethod
    def _parallel_merge_patterns():
        return {
            "merge_boundary": re.compile(
                r"(?:"
                r"(?<!不把)(?<!不将)受保护(?:的)?下游(?:动作|状态)"
                r"(?:或(?:受保护(?:的)?)?(?:下游)?(?:动作|状态))?"
                r"(?:(?!(?:没有|未|不|并非|不是|无需|无须)).){0,12}(?:锁在|置于|限定在).{0,24}"
                r"(?:多个|多项).{0,16}前置(?:分支|动作).{0,24}"
                r"(?:汇合条件|汇合屏障|汇合点)(?:之后|后)"
                r"|"
                r"(?<!不把)(?<!不将)受保护(?:的)?下游(?:动作|状态)"
                r"(?:或(?:受保护(?:的)?)?(?:下游)?(?:动作|状态))?"
                r"(?:(?!(?:没有|未|不|并非|不是|无需|无须)).){0,12}(?:必须|须)?等"
                r"(?:所有|全部|多个|多项).{0,8}前置(?:分支|动作).{0,8}汇合"
                r"(?:条件|屏障|点)?(?:之后|后)?(?:才能|才)(?:发生|生效|触发|造成)"
                r")"
            ),
            "parallel_stops_at_merge": re.compile(
                r"并行(?:(?!(?:不|非|未|没有)).){0,24}"
                r"(?:(?:只|仅)(?:可|能)?(?:运行|推进|进行|到达)|(?:但)?止步于).{0,16}"
                r"(?:汇合屏障|汇合点)"
            ),
            "no_early_downstream_effect": re.compile(
                r"(?:"
                r"(?:全部|所有).{0,16}(?:前置|条件).{0,16}(?:满足|完成).{0,40}(?:前|之前)"
                r".{0,32}(?:中间效果|任一分支)(?:(?!(?:并非|并不是|不是|不一定不能)).){0,32}"
                r"(?:不得|不能).{0,20}(?:提前)?(?:触发|造成).{0,32}"
                r"受保护(?:的)?下游(?:动作|状态)"
                r"(?:或(?:受保护(?:的)?)?(?:下游)?(?:动作|状态))?"
                r"|"
                r"汇合(?:条件|屏障|点)?完成(?:之前|前)"
                r"(?:(?!(?:并非|并不是|不是|不一定不能)).){0,12}(?:不得|不能)(?:让|使)?"
                r"受保护(?:的)?(?:下游)?(?:动作|状态)(?:变化)?(?:发生|生效|触发|造成)"
                r"|"
                r"汇合(?:条件|屏障|点)?完成(?:之前|前)"
                r"(?:(?!(?:并非|并不是|不是|不一定不能)).){0,12}"
                r"受保护(?:的)?(?:下游)?(?:动作|状态)(?:变化)?"
                r"(?:(?!(?:并非|并不是|不是|不一定不能)).){0,12}"
                r"(?:不得|不能)(?:发生|生效|触发|造成)"
                r")"
            ),
            "early_trigger_is_existing_p0": re.compile(
                r"提前(?:触发|造成|生效)(?:(?!(?:不|非|未|没有)).){0,24}(?:属于|视为).{0,12}"
                r"(?:既有|原有).{0,12}顺序错误.{0,24}(?:blocking/P0|P0)"
            ),
            "joint_action_starts_together": re.compile(
                r"只有输入明确把受保护下游动作指定为多名参与者共同或同时执行时，"
                r"汇合完成只解除前置屏障；全部指定参与者就位前，任何一人不得单独启动，"
                r"动作须从起始即共同或同时执行。“一人先启动、他人随后加入”"
                r"仍属于既有顺序错误，按blocking/P0"
            ),
            "authorized_merge_remedy": re.compile(
                r"(?:准备动作|前置动作).{0,24}(?:本身|自身).{0,12}(?:触发|造成).{0,40}"
                r"(?<!无)(?:须|必须|应当)(?:(?!(?:不|非|未|没有)).){0,8}在授权事实内.{0,24}"
                r"保持.{0,20}受保护状态.{0,12}不发生.{0,32}"
                r"(?:改为)?串行.{0,12}(?:或|/|、).{0,12}重组.{0,32}"
                r"(?:无法|不能).{0,16}(?:解决|修复).{0,16}(?:阻断|BLOCKED)"
            ),
            "branch_elapsed_trace": {
                "major_window_branch": re.compile(
                    r"(?:(?:承担|占据|消耗).{0,16}(?:主要|大部|核心).{0,12}(?:窗口|时限).{0,20}"
                    r"(?:串行|并行).{0,8}(?:分支|路径)|"
                    r"(?:串行|并行).{0,8}(?:分支|路径).{0,20}(?:承担|占据|消耗).{0,12}"
                    r"(?:窗口|时限).{0,12}(?:主要|大部|核心).{0,8}(?:耗时|消耗))"
                ),
                "not_start_and_finish_only": re.compile(
                    r"(?:不得|不能|不可).{0,12}(?:只|仅).{0,12}(?:写|交代|呈现).{0,10}"
                    r"(?:起点|开始).{0,16}(?:完成|结束|结果|完成口令)"
                ),
                "negated_start_finish_prohibition": re.compile(
                    r"(?:(?:并非|并不是|不是|未必).{0,4}(?:不得|不能|不可|禁止)|"
                    r"(?:没有|未曾).{0,4}禁止).{0,12}(?:只|仅).{0,12}"
                    r"(?:写|交代|呈现).{0,10}(?:起点|开始).{0,16}(?:完成|结束|结果|完成口令)"
                ),
                "authorized_action_source": re.compile(
                    r"(?:授权(?:动作|行动)|既有授权(?:动作|行动)|已授权(?:动作|行动))"
                ),
                "process_evidence": re.compile(
                    r"(?:(?:中间|过程).{0,6}(?:进展|推进)|阻力.{0,6}(?:变化|增减|升降)|"
                    r"(?:累积|累计).{0,12}(?:身体|环境).{0,8}(?:反馈|反应|代价))"
                ),
                "elapsed_reconstructable": re.compile(
                    r"(?:读者.{0,12}(?:重建|还原).{0,12}(?:如何)?耗时|"
                    r"(?:使|让).{0,12}耗时.{0,12}(?:被)?读者.{0,8}(?:重建|还原)|"
                    r"(?:使|让).{0,12}读者.{0,12}(?:重建|还原).{0,12}(?:如何)?耗时)"
                ),
                "no_new_action_tool_or_fact": re.compile(
                    r"(?:不得|不能|不可).{0,16}(?:新增|添加).{0,8}(?:新)?动作.{0,8}"
                    r"(?:工具|器具).{0,8}事实"
                ),
                "no_mechanical_reporting": re.compile(
                    r"(?:不得|不能|不可).{0,32}(?:机械报时|机械播报|按表机械播报)"
                ),
                "allows_new_content": re.compile(
                    r"(?<!不)(?:可以|可|允许)(?!被).{0,12}(?:为此)?(?:新增|添加).{0,16}"
                    r"(?:动作|工具|器具|事实)"
                ),
            },
            "functional_p1": re.compile(
                r"(?:只有|仅当)(?:上述|前述).{0,12}(?:报时|读数).{0,12}功能(?:违例|违反|缺口).{0,24}"
                r"(?:无|没有|不存在).{0,16}(?:独立|其他|另有).{0,8}P0.{0,18}"
                r"(?:才|方).{0,8}(?:归|按|列为).{0,6}P1.{0,16}(?:不阻断|non-blocking)"
            ),
            "p0_precedence": re.compile(
                r"(?:若|如|一旦).{0,16}(?:同时|还).{0,12}(?:命中|存在|触发).{0,12}"
                r"(?:既有|独立|其他).{0,8}P0.{0,16}P0.{0,8}(?:优先|为准)"
            ),
        }

    def test_explicit_countdown_scope_requires_each_readout_to_change_action(self):
        normalize = self._normalize_contract

        condition = re.compile(
            r"(?:若|当)输入.{0,20}(?:明确|显式).{0,24}(?:限定|限制|要求).{0,32}"
            r"(?:倒计时|报时|读数).{0,32}(?:只|仅).{0,24}(?:改变|影响).{0,20}(?:程序|行动|选择)"
        )
        retained_readout = re.compile(
            r"(?:(?:保留|留下).{0,16}(?:逐条|每条|各自|均).{0,8}(?:显式)?(?:倒计时|报时|读数)|"
            r"(?:保留|留下).{0,16}(?:显式)?(?:倒计时|报时|读数).{0,12}(?:逐条|每条|各自|均))"
            r".{0,16}(?:改变|影响).{0,16}(?:后续)?(?:行动|选择|取舍)"
        )
        pure_progress = re.compile(
            r"(?:只报进度|纯进度).{0,16}(?:报时|读数).{0,20}(?:删去|删除|删掉).{0,16}"
            r"(?:或|/).{0,12}(?:改用|改成|换成|换作|替换).{0,20}非计时.{0,12}(?:过程|证据)"
        )
        overall_rule = re.compile(
            r"输入.{0,16}(?:未|没有|无).{0,16}(?:该|此)?(?:限定|限制|要求).{0,28}"
            r"(?:仍|继续|沿用|执行|按).{0,20}(?:整体|全段).{0,16}至少一项.{0,20}"
            r"(?:改变|影响).{0,16}(?:行动|选择)"
        )
        no_global_duty = re.compile(
            r"(?:不|不得).{0,16}(?:扩张|推定|推成|视为).{0,20}"
            r"(?:逐条|每条|每次|所有|全局).{0,16}(?:义务|规则|要求)"
        )
        per_readout_obligation = re.compile(
            r"(?:(?:每次|每条|每个|所有|全部).{0,8}(?:倒计时|报时|读数)|"
            r"(?:倒计时|报时|读数).{0,12}(?:逐条|逐一|每次|每条|各自|全部))"
            r".{0,20}(?:必须|都须|都要|均须|一律|须).{0,20}"
            r"(?:改变|影响).{0,20}(?:行动|选择|取舍|分工|顺序|风险判断|验收)"
        )
        new_mechanism = re.compile(
            r"(?<!不)(?<!不得)(?<!不应)(?:新增|创建|设置).{0,24}(?:schema|计数器|角色|修复轮次)"
        )
        functional_later_readout = {
            "legal_countdown": re.compile(
                r"(?:现场|场内).{0,12}(?:合法|已授权).{0,4}(?:倒计时|倒数)"
            ),
            "multi_phase_window": re.compile(
                r"(?:限时行动|时限行动|倒计时|倒数).{0,16}(?:跨越|贯穿|覆盖).{0,12}"
                r"(?:多个|两个以上|多段).{0,6}(?:阶段|行动阶段)"
            ),
            "later_readout_changes_choice": re.compile(
                r"(?:后续|后段|稍后).{0,12}(?:剩余时间)?(?:读数|余量|时间证据).{0,24}"
                r"(?:改变|调整|缩减|促使).{0,32}(?:行动范围|范围|风险判断|验收)"
            ),
            "at_decision_point": re.compile(
                r"(?:在|于)(?:该|实际|对应)?(?:决策点|取舍当下|作出取舍的当下).{0,8}"
                r"(?:呈现|写出|放入)?"
            ),
            "negated_decision_point_placement": re.compile(
                r"(?:不|未|没有|并非)(?:曾)?(?:在|于)(?:该|实际|对应)?"
                r"(?:决策点|取舍当下|作出取舍的当下).{0,8}(?:呈现|写出|放入)"
            ),
            "cannot_omit_functional_readout": re.compile(
                r"(?:不得|不能|不可).{0,16}(?:避免|防止).{0,8}"
                r"(?:机械报时|机械报数|机械报告).{0,8}(?:为由|而).{0,12}"
                r"(?:省略|删掉|删除).{0,12}(?:有功能|有效)"
            ),
            "no_new_choice_no_readout": re.compile(
                r"(?:若|如|当).{0,8}(?:后续)?(?:没有|未|不再).{0,12}(?:新的?)?"
                r"(?:选择|决策|取舍).{0,6}(?:变化|改变).{0,12}(?:则|就).{0,6}"
                r"(?:不|不要|无需).{0,6}(?:新增|增加|补报|补写).{0,4}(?:读数|报时)?"
            ),
            "no_minimum_count": re.compile(
                r"(?:不设|不设置|不存在|没有|不要求).{0,10}(?:最低|最少).{0,8}"
                r"(?:报时|报告|读数)?次数"
            ),
            "unconditional_readout": re.compile(
                r"(?:无论|不论).{0,20}(?:是否|有没有).{0,12}(?:改变|调整).{0,20}"
                r"(?:都|均|一律).{0,12}(?:新增|增加|呈现|报告)"
            ),
            "fixed_or_minimum_cadence": re.compile(
                r"(?:(?:每隔|每过).{0,8}[0-9一二三四五六七八九十百]+(?:秒|分钟).{0,12}(?:报时|读数)|"
                r"(?:至少|最低).{0,4}[0-9一二三四五六七八九十百]+(?:次|个).{0,8}(?:报时|读数|报告))"
            ),
        }
        global_scope_reset = re.compile(r"(?:无论输入是否限定|任何情况下|全局规则要求)")

        def has_unconditional_per_readout_obligation(value):
            for sentence in re.split(r"[。！？]", normalize(value)):
                condition_active = False
                for clause in re.split(r"[；;]", sentence):
                    for match in per_readout_obligation.finditer(clause):
                        prefix = clause[:match.start()]
                        reset_scope = bool(global_scope_reset.search(prefix))
                        if reset_scope:
                            condition_active = False
                        local_condition = not reset_scope and condition.search(prefix)
                        if not condition_active and not local_condition:
                            return True
                    if global_scope_reset.search(clause):
                        condition_active = False
                    elif condition.search(clause):
                        condition_active = True
            return False

        def has_functional_later_readout_contract(value):
            normalized = normalize(value)
            required = (
                "legal_countdown",
                "multi_phase_window",
                "later_readout_changes_choice",
                "at_decision_point",
                "cannot_omit_functional_readout",
                "no_new_choice_no_readout",
                "no_minimum_count",
            )
            return (
                all(functional_later_readout[name].search(normalized) for name in required)
                and not functional_later_readout["unconditional_readout"].search(normalized)
                and not functional_later_readout["fixed_or_minimum_cadence"].search(normalized)
                and not functional_later_readout["negated_decision_point_placement"].search(normalized)
            )

        carriers = self._temporal_contract_carriers()
        for scope, contract in carriers.items():
            with self.subTest(scope=scope, rule="conditional"):
                self.assertRegex(contract, condition)
            with self.subTest(scope=scope, rule="retained_readout"):
                self.assertRegex(contract, retained_readout)
            with self.subTest(scope=scope, rule="pure_progress"):
                self.assertRegex(contract, pure_progress)
            with self.subTest(scope=scope, rule="default_overall"):
                self.assertRegex(contract, overall_rule)
                self.assertRegex(contract, no_global_duty)
            with self.subTest(scope=scope, rule="no_unconditional_per_readout"):
                self.assertFalse(has_unconditional_per_readout_obligation(contract))
            with self.subTest(scope=scope, rule="no_new_mechanism"):
                self.assertNotRegex(contract, r"(?:每隔|每过)\d+(?:秒|分钟).{0,20}(?:报时|读数)")
                self.assertNotRegex(contract, r"至少\d+(?:次|个).{0,20}(?:报时|读数|报告)")
                self.assertNotRegex(contract, r"(?:必须|要求|应).{0,16}(?:固定报时频率|最低报时次数)")
                self.assertNotRegex(contract, new_mechanism)
            with self.subTest(scope=scope, rule="functional_later_readout"):
                self.assertTrue(has_functional_later_readout_contract(contract))

        for marker in ("取舍", "分工", "顺序", "风险判断", "验收"):
            self.assertIn(marker, carriers["canonical"])
        for marker in ("阻力", "过程进展", "并行汇合", "验收等待", "非计时证据"):
            self.assertIn(marker, carriers["canonical"])
        valid_conditional = (
            "若输入明确限定显式报时只在改变行动选择时出现，"
            "保留的显式读数逐条核查，每条都须改变后续选择。"
        )
        contradictory_global = valid_conditional + "每次报时都必须改变行动。"
        self.assertFalse(has_unconditional_per_readout_obligation(valid_conditional))
        self.assertTrue(has_unconditional_per_readout_obligation(contradictory_global))

        valid_semicolon = (
            "若输入明确限定显式报时只在改变行动选择时出现；"
            "保留的每条报时都须改变后续选择。"
        )
        with self.subTest(fixture="semicolon_scope"):
            self.assertFalse(has_unconditional_per_readout_obligation(valid_semicolon))

        non_reset_global_mentions = {
            "post_obligation_global_label": (
                "若输入明确限定显式报时只在改变行动选择时出现；"
                "保留的每条报时都须改变后续选择，并非全局规则。"
            ),
            "negated_global_duty": (
                "若输入明确限定显式报时只在改变行动选择时出现；"
                "不得扩张为每次报时都须改变行动的全局义务。"
            ),
        }
        for fixture, value in non_reset_global_mentions.items():
            with self.subTest(fixture=fixture):
                self.assertFalse(has_unconditional_per_readout_obligation(value))

        reset_globals = {
            "standalone_any_case": (
                "若输入明确限定显式报时只在改变行动选择时出现；"
                "任何情况下均采用下列规则；"
                "每次报时都必须改变行动。"
            ),
            "regardless_of_input": (
                "若输入明确限定显式报时只在改变行动选择时出现；"
                "无论输入是否限定，每次报时都必须改变行动。"
            ),
            "global_rule": (
                "若输入明确限定显式报时只在改变行动选择时出现；"
                "全局规则要求每次报时都必须改变行动。"
            ),
            "any_case": (
                "若输入明确限定显式报时只在改变行动选择时出现；"
                "任何情况下，每次报时都必须改变行动。"
            ),
        }
        for fixture, value in reset_globals.items():
            with self.subTest(fixture=fixture):
                self.assertTrue(has_unconditional_per_readout_obligation(value))

        negated_new_mechanism = normalize("不应新增持久 schema。")
        with self.subTest(fixture="negated_new_mechanism"):
            self.assertNotRegex(negated_new_mechanism, new_mechanism)

        functional_later_readout_fixtures = {
            "functional_later_readout": (
                True,
                None,
                "现场已有合法倒计时且限时行动跨越多个阶段时，若后续某个剩余时间读数会实际改变"
                "行动范围、风险判断或验收选择，须在该决策点呈现该读数；不得以避免机械报时为由"
                "省略有功能的后续读数。若后续没有新的选择变化，则不新增读数；仍不设最低报时次数。",
            ),
            "functional_later_readout_reworded": (
                True,
                None,
                "当现场合法倒数贯穿两个以上行动阶段，后段余量如会促使角色缩减行动范围，"
                "就应把该余量放在作出取舍的当下；不能借防止机械报数而删掉这类有效提示。"
                "后续若没有产生新的决策改变，则不要补报，也不存在最低次数要求。",
            ),
            "add_later_readout_regardless_of_choice_change": (
                False,
                ("forbidden", "unconditional_readout"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变行动范围，"
                "须在该决策点呈现；不得以避免机械报时为由省略有功能的后续读数。"
                "无论后续是否改变选择，都须增加剩余时间读数；仍不设最低报时次数。",
            ),
            "omit_functional_readout_to_avoid_mechanical_reporting": (
                False,
                ("required", "cannot_omit_functional_readout"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变风险判断，"
                "须在该决策点呈现；为避免机械报时，可以省略有功能的后续读数。"
                "若后续没有新的选择变化，则不新增读数；仍不设最低报时次数。",
            ),
            "functional_readout_after_decision": (
                False,
                ("required", "at_decision_point"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变验收选择，"
                "但允许在决定作出后再补记；不得以避免机械报时为由省略有功能的后续读数。"
                "若后续没有新的选择变化，则不新增读数；仍不设最低报时次数。",
            ),
            "negated_decision_point_placement": (
                False,
                ("forbidden", "negated_decision_point_placement"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变验收选择，"
                "不在该决策点呈现读数；不得以避免机械报时为由省略有功能的后续读数。"
                "若后续没有新的选择变化，则不新增读数；仍不设最低报时次数。",
            ),
            "absent_actual_decision_point_placement": (
                False,
                ("forbidden", "negated_decision_point_placement"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变验收选择，"
                "没有在实际决策点写出读数；不得以避免机械报时为由省略有功能的后续读数。"
                "若后续没有新的选择变化，则不新增读数；仍不设最低报时次数。",
            ),
            "fixed_reporting_cadence": (
                False,
                ("forbidden", "fixed_or_minimum_cadence"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变行动范围，"
                "须在该决策点呈现；不得以避免机械报时为由省略有功能的后续读数。"
                "若后续没有新的选择变化，则不新增读数；每隔十秒报时。",
            ),
            "minimum_reporting_count": (
                False,
                ("forbidden", "fixed_or_minimum_cadence"),
                "现场已有合法倒计时且限时行动跨越多个阶段。后续剩余时间读数会改变行动范围，"
                "须在该决策点呈现；不得以避免机械报时为由省略有功能的后续读数。"
                "若后续没有新的选择变化，则不新增读数；仍不设最低报时次数，但至少三次报时。",
            ),
        }
        for fixture, (should_match, failed_boundary, value) in functional_later_readout_fixtures.items():
            with self.subTest(fixture=fixture):
                if failed_boundary:
                    kind, rule = failed_boundary
                    if kind == "required":
                        self.assertIsNone(functional_later_readout[rule].search(normalize(value)))
                    else:
                        self.assertIsNotNone(functional_later_readout[rule].search(normalize(value)))
                self.assertEqual(has_functional_later_readout_contract(value), should_match)

    def test_parallel_merge_contract_preserves_barrier_and_scoped_remedies(self):
        normalize = self._normalize_contract
        carriers = self._temporal_contract_carriers()
        patterns = self._parallel_merge_patterns()
        branch_elapsed_patterns = patterns["branch_elapsed_trace"]

        def has_branch_elapsed_trace_contract(value):
            normalized = normalize(value)
            required = (
                "major_window_branch",
                "not_start_and_finish_only",
                "authorized_action_source",
                "process_evidence",
                "elapsed_reconstructable",
                "no_new_action_tool_or_fact",
                "no_mechanical_reporting",
            )
            return (
                all(branch_elapsed_patterns[name].search(normalized) for name in required)
                and not branch_elapsed_patterns["allows_new_content"].search(normalized)
                and not branch_elapsed_patterns["negated_start_finish_prohibition"].search(normalized)
            )
        protected_scope_trigger = re.compile(
            r"若输入或`?on_page_requirements`?.{0,20}(?<!不)(?:将|把)"
            r"受保护(?:的)?下游(?:动作|状态)"
        )

        for scope, contract in carriers.items():
            with self.subTest(scope=scope, rule="protected_scope_trigger"):
                self.assertRegex(contract, protected_scope_trigger)
            for rule in (
                "merge_boundary",
                "parallel_stops_at_merge",
                "no_early_downstream_effect",
                "early_trigger_is_existing_p0",
                "joint_action_starts_together",
            ):
                with self.subTest(scope=scope, rule=rule):
                    self.assertRegex(contract, patterns[rule])
            with self.subTest(scope=scope, rule="branch_elapsed_trace"):
                self.assertTrue(has_branch_elapsed_trace_contract(contract))
            with self.subTest(scope=scope, rule="explicit_readout_p1_scope"):
                self.assertIn("上述显式报时/读数功能违例", contract)
                self.assertRegex(contract, patterns["functional_p1"])
                self.assertRegex(contract, patterns["p0_precedence"])

        self.assertRegex(carriers["canonical"], patterns["authorized_merge_remedy"])
        negative_fixtures = {
            "negated_merge_lock": (
                "merge_boundary",
                "受保护下游动作没有锁在多个前置分支的汇合条件之后。",
            ),
            "missing_protected_scope": (
                "merge_boundary",
                "多个前置分支位于汇合条件之前，并行准备仅可推进到汇合屏障。",
            ),
            "negated_only": (
                "parallel_stops_at_merge",
                "并行准备不是只推进到汇合屏障。",
            ),
            "negated_parallel_stop": (
                "parallel_stops_at_merge",
                "并行准备不只推进到汇合屏障。",
            ),
            "negated_cannot": (
                "no_early_downstream_effect",
                "所有前置条件完成之前，任一分支不是不能提前造成受保护下游状态。",
            ),
            "double_negated_early_effect": (
                "no_early_downstream_effect",
                "全部前置条件满足之前，任一分支的中间效果并非不得提前触发或造成受保护下游动作或状态变化。",
            ),
            "negated_belongs": (
                "early_trigger_is_existing_p0",
                "提前触发并非属于既有顺序错误，按 blocking/P0 处理。",
            ),
            "negated_existing_p0": (
                "early_trigger_is_existing_p0",
                "提前触发不属于既有顺序错误，按 blocking/P0 处理。",
            ),
            "remedy_without_authority": (
                "authorized_merge_remedy",
                "准备动作本身会触发受保护下游状态，须保持受保护状态不发生，"
                "改为串行或重组；无法解决则阻断。",
            ),
            "remedy_outside_authority": (
                "authorized_merge_remedy",
                "准备动作本身会触发受保护下游状态，须不在授权事实内保持受保护状态不发生，"
                "改为串行或重组；无法解决则阻断。",
            ),
        }
        for fixture, (rule, value) in negative_fixtures.items():
            with self.subTest(fixture=fixture):
                self.assertNotRegex(normalize(value), patterns[rule])

        bounded_matchers = {
            key: value for key, value in patterns.items() if key != "branch_elapsed_trace"
        }
        bounded_matchers["protected_scope_trigger"] = protected_scope_trigger
        quality_boundary_negative_fixtures = {
            "negated_input_scope_and_merge_lock": (
                ("protected_scope_trigger", "merge_boundary"),
                "若输入或 on_page_requirements 不把受保护下游动作锁在多个前置分支的汇合条件之后",
            ),
            "negated_input_scope_and_merge_lock_with_jiang": (
                ("protected_scope_trigger", "merge_boundary"),
                "若输入或 on_page_requirements 不将受保护下游动作锁在多个前置分支的汇合条件之后",
            ),
            "protected_action_does_not_need_to_wait": (
                ("merge_boundary",),
                "受保护下游动作无需等所有前置分支汇合后才能发生",
            ),
            "branch_not_necessarily_cannot_trigger_early": (
                ("no_early_downstream_effect",),
                "所有前置条件完成之前，任一分支不一定不能提前造成受保护下游状态",
            ),
            "remedy_no_need_for_authorized_facts": (
                ("authorized_merge_remedy",),
                "准备动作本身会触发受保护下游状态，无须在授权事实内保持受保护状态不发生，"
                "改为串行或重组；无法解决则阻断",
            ),
            "implicit_joint_action_requirement_without_explicit_input": (
                ("joint_action_starts_together",),
                "若受保护下游动作本身仍明确要求多名指定参与者共同或同时执行，"
                "汇合完成只解除前置屏障；全部指定参与者就位前，任何一人不得单独启动，"
                "动作须从起始即共同或同时执行。“一人先启动、他人随后加入”仍属于既有顺序错误，"
                "按 blocking/P0 处理。",
            ),
            "staggered_joint_start_allowed": (
                ("joint_action_starts_together",),
                "只有输入明确把受保护下游动作指定为多名参与者共同或同时执行时，"
                "汇合完成只解除前置屏障；一人可先启动、他人随后加入，最后共同执行。",
            ),
        }
        for fixture, (rules, value) in quality_boundary_negative_fixtures.items():
            for rule in rules:
                with self.subTest(fixture=fixture, rule=rule):
                    self.assertNotRegex(normalize(value), bounded_matchers[rule])

        branch_elapsed_fixtures = {
            "start_and_completion_only": (
                False,
                ("required", "not_start_and_finish_only"),
                "承担主要窗口消耗的串行或并行分支，只写起点和完成口令即可。"
                "从授权动作中呈现阻力变化，让读者重建如何耗时；不得新增动作、工具、事实或机械报时。",
            ),
            "negated_start_and_finish_prohibition": (
                False,
                ("forbidden", "negated_start_finish_prohibition"),
                "承担主要窗口消耗的串行或并行分支，并非不得只写起点和完成口令。"
                "从授权动作中呈现阻力变化，让读者重建如何耗时；不得新增动作、工具、事实或机械报时。",
            ),
            "double_negated_start_and_finish_prohibition": (
                False,
                ("forbidden", "negated_start_finish_prohibition"),
                "承担主要窗口消耗的串行或并行分支，不是不能只写开始和结果。"
                "从授权动作中呈现阻力变化，让读者重建如何耗时；不得新增动作、工具、事实或机械报时。",
            ),
            "new_action_or_tool_allowed": (
                False,
                ("forbidden", "allows_new_content"),
                "承担主要窗口消耗的串行或并行分支，不得只写起点和完成口令；"
                "须用授权动作中的阻力变化，让读者能重建该分支如何耗时；"
                "不得为此新增动作、工具、事实或机械报时，但可为此新增动作或工具。",
            ),
            "missing_authorized_process_evidence": (
                False,
                ("required", "process_evidence"),
                "承担主要窗口消耗的串行或并行分支，不得只写起点和完成口令；"
                "须从授权动作取材，让读者能重建该分支如何耗时；"
                "不得为此新增动作、工具、事实或机械报时。",
            ),
            "missing_elapsed_reconstruction": (
                False,
                ("required", "elapsed_reconstructable"),
                "承担主要窗口消耗的串行或并行分支，不得只写起点和完成口令；"
                "须用授权动作中的阻力变化；不得为此新增动作、工具、事实或机械报时。",
            ),
        }
        for fixture, (should_match, failed_boundary, value) in branch_elapsed_fixtures.items():
            with self.subTest(fixture=fixture):
                kind, rule = failed_boundary
                if kind == "required":
                    self.assertIsNone(branch_elapsed_patterns[rule].search(normalize(value)))
                else:
                    self.assertIsNotNone(branch_elapsed_patterns[rule].search(normalize(value)))
                self.assertEqual(has_branch_elapsed_trace_contract(value), should_match)

        positive_fixtures = {
            "protected_waits_for_merge": (
                "merge_boundary",
                "受保护下游动作必须等所有前置分支汇合后才能发生。",
            ),
            "protected_scope": (
                "merge_boundary",
                "受保护的下游状态置于多项前置动作的汇合点后。",
            ),
            "parallel_stops_at_barrier": (
                "parallel_stops_at_merge",
                "并行准备但止步于汇合屏障。",
            ),
            "parallel_limit": (
                "parallel_stops_at_merge",
                "并行分支只运行到汇合点。",
            ),
            "protected_state_cannot_take_effect": (
                "no_early_downstream_effect",
                "汇合完成前不能让受保护状态生效。",
            ),
            "early_effect_prohibition": (
                "no_early_downstream_effect",
                "所有条件完成之前，任一分支不能造成受保护的下游状态变化。",
            ),
            "existing_p0": (
                "early_trigger_is_existing_p0",
                "提前造成视为原有顺序错误，按 P0 处理。",
            ),
            "authorized_remedy": (
                "authorized_merge_remedy",
                "前置动作自身会造成该变化，须在授权事实内保持受保护状态不发生，"
                "改为串行或重组；不能修复则 BLOCKED。",
            ),
            "parallel_can_only_advance_to_barrier": (
                "parallel_stops_at_merge",
                "并行准备只能推进到汇合屏障",
            ),
            "protected_state_must_not_take_effect_before_merge": (
                "no_early_downstream_effect",
                "汇合完成前，受保护状态不得生效",
            ),
            "early_effect_is_existing_p0": (
                "early_trigger_is_existing_p0",
                "提前生效属于既有顺序错误，按 P0 处理",
            ),
            "explicit_joint_start": (
                "joint_action_starts_together",
                "只有输入明确把受保护下游动作指定为多名参与者共同或同时执行时，"
                "汇合完成只解除前置屏障；全部指定参与者就位前，任何一人不得单独启动，"
                "动作须从起始即共同或同时执行。“一人先启动、他人随后加入”仍属于既有顺序错误，"
                "按 blocking/P0 处理。",
            ),
            "authorized_branch_elapsed_trace": (
                "branch_elapsed_trace",
                "承担主要窗口消耗的串行或并行分支，不得只写起点和完成口令；"
                "须用授权动作中的中间进展、阻力变化或累积身体/环境反馈，"
                "让读者能重建该分支如何耗时；不得为此新增动作、工具、事实或机械报时。",
            ),
            "authorized_branch_elapsed_trace_reworded": (
                "branch_elapsed_trace",
                "凡串行或并行路径承担窗口中的主要耗时，不能仅交代开始和结束；"
                "应从既有授权行动里写出阻力增减，"
                "使耗时可被读者还原；不得借此添加新动作、器具、事实，也不能按表机械播报。",
            ),
        }
        for fixture, (rule, value) in positive_fixtures.items():
            with self.subTest(fixture=fixture):
                if rule == "branch_elapsed_trace":
                    self.assertTrue(has_branch_elapsed_trace_contract(value))
                else:
                    self.assertRegex(normalize(value), patterns[rule])

        scoped_minimal_fix_patterns = {
            "only_this_readout": re.compile(
                r"(?:上述|该类).{0,12}(?:显式)?(?:报时|读数).{0,12}P1.{0,24}`?minimal_fix`?.{0,16}"
                r"(?:只|仅).{0,8}(?:处理|修复).{0,8}(?:该|对应)(?:报时|读数)"
            ),
            "pure_progress_fix": re.compile(
                r"纯进度(?:报时|读数).{0,12}(?:删除|删去|删掉).{0,8}(?:或|/).{0,8}"
                r"(?:替换|改用|改成|换成|换作).{0,16}非计时(?:过程)?证据"
            ),
            "missing_functional_readout_fix": re.compile(
                r"遗漏.{0,8}有功能的?(?:后续)?读数.{0,16}(?:只|仅).{0,8}(?:在|于).{0,8}"
                r"(?:对应|该).{0,8}决策点.{0,8}(?:补入|补写|增加).{0,20}合法.{0,12}读数"
            ),
            "preserve_unrelated_actions": re.compile(
                r"不得.{0,8}(?:改写|调整).{0,8}无关动作.{0,8}(?:或|/|、).{0,8}"
                r"(?:新增|添加).{0,8}(?:工具|计时器)"
            ),
        }
        forbidden_readout_remedy = re.compile(
            r"(?:(?:补入|补写|增加).{0,12}读数(?:时|并|后).{0,8}"
            r"(?:改写|调整|重排).{0,12}(?:动作链|无关动作)|"
            r"(?:补入|补写|增加).{0,12}读数前.{0,8}"
            r"(?:新增|添加).{0,12}(?:工具|计时器)|"
            r"(?:新增|添加).{0,12}(?:工具|计时器).{0,12}(?:后|来|以便).{0,8}"
            r"(?:补入|补写|增加).{0,12}读数)"
        )
        category_specific_fix = re.compile(
            r"(?:其他|其余).{0,8}(?:类别|问题).{0,16}(?:按|依).{0,8}(?:各自|对应).{0,12}最小修复"
        )

        def has_scoped_minimal_fix_contract(value):
            normalized = normalize(value)
            return (
                all(pattern.search(normalized) for pattern in scoped_minimal_fix_patterns.values())
                and category_specific_fix.search(normalized)
                and not forbidden_readout_remedy.search(normalized)
            )

        for scope, contract in carriers.items():
            with self.subTest(scope=scope, rule="minimal_fix_scope"):
                self.assertTrue(has_scoped_minimal_fix_contract(contract))
            with self.subTest(scope=scope, rule="category_specific_fix"):
                self.assertRegex(contract, category_specific_fix)

        valid_minimal_fix_contract = (
            "上述显式报时/读数 P1 的 minimal_fix 只处理该读数："
            "纯进度读数删除或替换为非计时过程证据；遗漏有功能的后续读数只在对应决策点"
            "补入来自既有合法时间来源的读数；不得改写无关动作或新增工具。"
            "其他类别按各自问题作最小修复。"
        )
        minimal_fix_fixtures = {
            "scoped_delete_replace_or_insert": (
                True,
                valid_minimal_fix_contract,
            ),
            "rewrite_action_chain_while_inserting": (
                False,
                valid_minimal_fix_contract + "但补入读数时改写动作链。",
            ),
            "add_tool_before_inserting": (
                False,
                valid_minimal_fix_contract + "但补入读数前新增计时工具。",
            ),
        }
        for fixture, (should_match, value) in minimal_fix_fixtures.items():
            with self.subTest(fixture=fixture):
                normalized = normalize(value)
                self.assertTrue(
                    all(pattern.search(normalized) for pattern in scoped_minimal_fix_patterns.values())
                    and category_specific_fix.search(normalized),
                    "禁用 forbidden 检查时，完整正向合同应误过",
                )
                if not should_match:
                    self.assertRegex(normalized, forbidden_readout_remedy)
                self.assertEqual(has_scoped_minimal_fix_contract(value), should_match)

    def test_novelist_has_scene_audit_blocked_protocol(self):
        protocol = self.section("assets/agents/novelist.md", "## 互斥输出协议")
        for marker in ("code: scene_audit_blocked", "blocking:"):
            with self.subTest(scope="protocol", marker=marker):
                self.assertIn(marker, protocol)
        preflight = self.section("assets/agents/novelist.md", "## 输出前私有预检")
        for marker in ("关键事实或因果无法判定", "blocking/P0", "文学细腻度", "P1/P2", "不阻断"):
            with self.subTest(scope="preflight", marker=marker):
                self.assertIn(marker, preflight)

    def test_standalone_roles_preserve_on_page_evidence_contract(self):
        contracts = {
            "planning-editor": (
                "只提取来源明确要求必须在正文可直接指认的条件，写入 on_page_requirements；"
                "不得把编辑偏好升级为 P0。"
            ),
            "novelist": (
                "将每项 on_page_requirements 自然落地，不要求照抄题面，但交付稿须能逐项定位无歧义证据。"
            ),
            "anti-ai-editor": (
                "润色不得误删 on_page_requirements 的唯一正文证据；若改写，证据功能必须仍在。"
            ),
            "consistency-reviewer": (
                "对 on_page_requirements 逐项给出正文证据；明确要求缺失、顺序错误或行动主体被替代时按 "
                "blocking/P0 报告。"
            ),
        }
        for role, contract in contracts.items():
            with self.subTest(role=role):
                prompt = (ROOT / "assets/agents" / (role + ".md")).read_text(encoding="utf-8")
                self.assertIn(contract, prompt.replace("`", ""))

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

    def test_anti_ai_editor_requires_recovery_closure_deletion_test(self):
        review = self.section("assets/agents/anti-ai-editor.md", "## 恢复后文学复审")
        self.assertRegex(
            review,
            r"恢复正文(?:的)?后半(?:段)?(?:或|/|、)收束处.{0,80}状态或责任总结.{0,80}逐句删除测试",
        )
        self.assertIn("因果、P0 与连续性", review)
        self.assertIn("不得补造替代事实", review)

    def test_full_chapter_editor_deletes_redundant_relationship_explanations(self):
        review = self.section("assets/agents/anti-ai-editor.md", "## 关系解释删除测试").replace("`", "")
        self.assertIn("直接关系结论，逐句删除测试", review)
        self.assertIn("同一局部是否已有动作、称谓、停顿、物件交接或选择后果", review)
        self.assertIn("无新增信息", review)
        self.assertIn("删后若会损失关系状态或互动功能则保留", review)
        self.assertIn("不得为了 show don't tell 补造", review)
        self.assertIn("on_page_requirements", review)

    def test_relationship_review_preserves_necessary_state_and_excludes_fragments(self):
        review = self.section("assets/agents/anti-ai-editor.md", "## 关系解释删除测试")
        self.assertIn("必要的新状态、因果、策略、视角知识或互动功能必须保留，只做最小的当前 POV 改写", review)
        fragment = self.section("assets/agents/anti-ai-editor.md", "## 片段模式")
        self.assertIn("不执行关系解释删除测试", fragment)

    def test_anti_ai_style_distinguishes_necessary_state_checks_from_redundant_recap(self):
        guidance = self.section("references/craft/anti-ai-style.md", "## 状态核对与状态复盘")
        self.assertIn("必要状态核对", guidance)
        for function in ("改变悬疑", "改变行动", "改变读者认知"):
            self.assertIn(function, guidance)
        self.assertIn("无新增戏剧功能的状态复盘", guidance)
        self.assertIn("不能仅因“仍”“依旧”等词机械删除", guidance)

    def test_chapter_loop_runs_literary_review_after_hard_checks_before_delivery(self):
        flow = (ROOT / "references/workflow/chapter-loop.md").read_text(encoding="utf-8")
        hard_checks = "恢复/一致性/P0 硬检查通过"
        literary_review = "独立文学复审通过"
        rerun_passed = "连续性/P0 硬检查重新通过"
        delivery = "正式交付"
        for marker in (hard_checks, literary_review, rerun_passed, delivery):
            self.assertIn(marker, flow)
        self.assertLess(flow.index(hard_checks), flow.index(literary_review))
        self.assertLess(flow.index(literary_review), flow.index(rerun_passed))
        self.assertLess(flow.index(rerun_passed), flow.index(delivery))
        self.assertIn("硬检查失败不得被文学复审覆盖", flow)
        self.assertIn("文学修改后必须重新运行连续性/P0 硬检查", flow)

    def test_relationship_deletion_review_stays_inside_existing_delivery_loop(self):
        flow = (ROOT / "references/workflow/chapter-loop.md").read_text(encoding="utf-8")
        relation = "关系解释删除测试"
        audit_heading = "## 交付前场景审计（blocking）"
        recovery = "恢复或中断续写后的交付顺序"
        debt = "**欠账门**"
        for marker in (relation, audit_heading, recovery, debt):
            self.assertIn(marker, flow)
        self.assertLess(flow.index(audit_heading), flow.index(relation))
        self.assertLess(flow.index(relation), flow.index(recovery))
        self.assertLess(flow.index(recovery), flow.index(debt))
        section = flow[flow.index(audit_heading):flow.index(recovery)]
        for marker in ("完整章节", "恢复续写", "片段模式", "共享现有", "两轮", "不新建"):
            self.assertIn(marker, section)
        self.assertRegex(
            flow,
            r"\*\*欠账门\*\*：本章追踪文件未全部更新前，禁止开写下一章。会话中断后恢复写作时，\s*先核对",
        )

    def test_chapter_loop_runs_scene_audit_before_formal_delivery(self):
        audit = self.section("references/workflow/chapter-loop.md", "## 交付前场景审计（blocking）")
        for marker in ("场景交付审计通过", "连续性/P0 硬检查重新通过", "正式交付",
                       "on_page_requirements", "转折桥", "动作预算", "物件归属", "共享现有最多两轮",
                       "关键事实或整体因果无法判定", "blocking/P0", "文学细腻度", "P1/P2", "不阻断"):
            self.assertIn(marker, audit)
        self.assertLess(audit.index("场景交付审计通过"), audit.index("连续性/P0 硬检查重新通过"))
        self.assertLess(audit.index("连续性/P0 硬检查重新通过"), audit.index("正式交付"))
        self.assertRegex(
            audit,
            r"任一项未过不得\s*`?commit`?\s*/\s*`?正式交付`?",
        )

    def test_scene_audit_prop_custody_is_required_before_reliance(self):
        contracts = {
            "references/workflow/chapter-loop.md": "## 交付前场景审计（blocking）",
            "assets/agents/consistency-reviewer.md": "## 必查清单（不得省略）",
        }
        for document, heading in contracts.items():
            with self.subTest(document=document):
                section = self.section(document, heading)
                self.assertIn("再次依赖该物件前", section)

    def test_scene_audit_rechecks_only_after_actual_prose_change(self):
        audit = self.section("references/workflow/chapter-loop.md", "## 交付前场景审计（blocking）")
        self.assertRegex(
            audit,
            r"场景审计或文学性修复实际修改正文[\s\S]{0,120}连续性/P0 硬检查重新通过",
        )
        self.assertRegex(
            audit,
            r"场景审计和文学性修复都未修改正文[\s\S]{0,120}沿用既有验证结果[\s\S]{0,120}不新增轮次",
        )

    def test_novelist_scene_audit_budget_branches_are_unambiguous(self):
        protocol = self.section("assets/agents/novelist.md", "## 互斥输出协议")
        self.assertRegex(
            protocol,
            r"repair_round\s*>=\s*2[\s\S]{0,120}blocking/P0[\s\S]{0,120}gate_blocked",
        )
        self.assertRegex(
            protocol,
            r"repair_round\s*<\s*2[\s\S]{0,120}无法在授权内修复[\s\S]{0,120}scene_audit_blocked",
        )
        preflight = self.section("assets/agents/novelist.md", "## 输出前私有预检")
        for marker in ("生成内", "最小自校", "不作为独立 workflow 返工轮次", "不回传审计卡"):
            with self.subTest(scope="preflight", marker=marker):
                self.assertIn(marker, preflight)
        prompt = (ROOT / "assets/agents/novelist.md").read_text(encoding="utf-8")
        self.assertNotIn("由 workflow 统一登记", prompt)

    def test_repair_round_is_transient_and_handed_to_each_novelist_call(self):
        novelist_input = self.section("assets/agents/novelist.md", "## 先验收输入")
        for marker in ("repair_round", "瞬时调用信封", "不属于 Chapter Brief", "不新增持久 schema"):
            with self.subTest(scope="novelist_input", marker=marker):
                self.assertIn(marker, novelist_input)
        handoff = self.section("references/workflow/chapter-loop.md", "### Step 3A：形成章意图（blocking）")
        step4 = self.section("references/workflow/editorial-spawn.md", "### Step 4：写作（写作特工按 Brief 写正文）")
        self.assertIn("repair_round", handoff)
        self.assertRegex(handoff, r"初次调用为\s*0")
        self.assertRegex(handoff, r"每次提交后因 P0\s*重写递增")
        self.assertRegex(handoff, r"最多\s*2")
        self.assertIn("repair_round", step4)
        self.assertRegex(step4, r"每次提交后因 P0\s*重写递增")
        self.assertRegex(step4, r"最多\s*2")
        self.assertRegex(
            step4,
            r"editorial_state\.json.*rewrite_round[\s\S]{0,120}repair_round",
        )
        for marker in ("首次无值为 0", "恢复会话沿用已有值", "不得默认重置"):
            with self.subTest(scope="editorial_spawn_resume", marker=marker):
                self.assertIn(marker, step4)

    def test_brief_regeneration_cannot_reset_same_task_repair_round(self):
        circuit_breaker = self.section("references/workflow/editorial-spawn.md", "### 规则1：单章返工上限 2 次")
        self.assertRegex(
            circuit_breaker,
            r"Brief[\s\S]*?重新生成[\s\S]{0,120}(?:不得|不能)[\s\S]{0,120}同章同任务[\s\S]*清零",
        )
        self.assertRegex(circuit_breaker, r"真正的新任务[\s\S]{0,80}边界")

    def test_editorial_spawn_persists_round_before_next_novelist_call(self):
        step4 = self.section("references/workflow/editorial-spawn.md", "### Step 4：写作（写作特工按 Brief 写正文）")
        self.assertRegex(
            step4,
            r"原子(?:更新|写入)[\s\S]{0,120}editorial_state\.json\.rewrite_round\s*=\s*min\(previous\s*\+\s*1,\s*2\)",
        )
        self.assertRegex(
            step4,
            r"持久化[\s\S]{0,120}再从该值构造[\s\S]{0,120}repair_round[\s\S]{0,120}下一次.*SendMessage",
        )
        self.assertRegex(step4, r"恢复[\s\S]{0,120}读取同一持久值")

    def test_editorial_teamdelete_keeps_same_task_repair_round(self):
        initialization = self.section("references/workflow/editorial-spawn.md", "### Step 2：创建团队（声明四角色）")
        self.assertRegex(initialization, r"初次初始化\s*0[\s\S]{0,120}无同章同任务历史")
        lifecycle = self.section("references/workflow/editorial-spawn.md", "## SendMessage / TeamDelete 生命周期管理")
        self.assertRegex(
            lifecycle,
            r"不恢复[\s\S]{0,120}TeamDelete[\s\S]{0,120}重新开始[\s\S]{0,120}同章同任务[\s\S]{0,120}不得清零",
        )
        circuit_breaker = self.section("references/workflow/editorial-spawn.md", "### 规则1：单章返工上限 2 次")
        self.assertRegex(circuit_breaker, r"作者明确宣布[\s\S]{0,80}新的任务边界")
        self.assertRegex(circuit_breaker, r"换团队[\s\S]{0,80}会话[\s\S]{0,80}重做 Brief[\s\S]{0,80}不得")

    def test_editorial_spawn_dispatches_legal_blocked_before_prose_checks(self):
        step4 = self.section("references/workflow/editorial-spawn.md", "### Step 4：写作（写作特工按 Brief 写正文）")
        for code in ("required_context_missing", "required_context_over_budget", "outline_underfilled",
                     "scene_audit_blocked", "gate_blocked"):
            with self.subTest(code=code):
                self.assertIn(code, step4)
        self.assertRegex(
            step4,
            r"先解析[\s\S]{0,40}互斥输出[\s\S]{0,300}合法无正文 `?BLOCKED`?[\s\S]{0,300}传播阻断并停止[\s\S]{0,120}不进入 NOVEL_TEXT",
        )
        self.assertRegex(step4, r"不自动重写、不额外消耗轮次")
        self.assertRegex(step4, r"格式非法[\s\S]{0,80}P0[\s\S]{0,80}阻断")
        self.assertLess(step4.index("scene_audit_blocked"), step4.index("正文隔离检查"))
        self.assertLess(step4.index("gate_blocked"), step4.index("正文隔离检查"))

    def test_editorial_spawn_gives_reviewer_shared_scene_audit_contract(self):
        step5 = self.section("references/workflow/editorial-spawn.md", "### Step 5：并行审核（反AI编辑 + 连载核实官）")
        for marker in ("完整 Chapter Brief", "on_page_requirements", "共享场景渲染/审计规则的实际内容",
                       "硬锚点", "转折桥", "倒计时行动预算", "道具交接", "再次依赖该物件前",
                       "不另起第二套修复轮次"):
            with self.subTest(scope="reviewer_message", marker=marker):
                self.assertIn(marker, step5)
        step6 = self.section("references/workflow/editorial-spawn.md", "### Step 6：汇总判定（总编辑裁决）")
        for marker in ("硬锚点", "转折桥", "倒计时行动预算", "道具交接", "blocking/P0", "P1/P2"):
            with self.subTest(scope="summary", marker=marker):
                self.assertIn(marker, step6)


if __name__ == "__main__":
    unittest.main()
