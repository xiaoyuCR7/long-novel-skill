#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_e2e.py — 端到端集成测试（纯标准库）。

模拟真实使用场景：初始化书籍工程 → 写入章节正文 → 运行7Gate门禁
→ 质量基线评测 → 静态一致性检查。

覆盖完整工作流，验证各脚本之间的协同工作是否正常。

用法：
    python scripts/tests/test_e2e.py
    python -m unittest scripts.tests.test_e2e
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path

# 把 scripts 目录加入 sys.path
_SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SCRIPT_DIR.parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent

for p in (str(_SCRIPTS_DIR), str(_SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from check_text import (
    BANNED_WORDS,
    count_chars,
    scan_lines,
    scan_blocking_patterns,
    scan_degradation,
    scan_structure,
    extract_chapter_number,
    strip_dialogue,
    deslop_score,
)
from benchmark import (
    evaluate_chapter,
    evaluate_book,
    trend_analysis,
    _cjk_chars,
)
from static_check import (
    CheckResult,
    check_character,
    check_timeline,
    check_sync,
    check_wordcount,
    _count_chinese_chars,
    _collect_chapter_files,
)
from novel_flow import (
    acquire_lock,
    release_lock,
    create_snapshot,
    restore_snapshot,
)
from context_manager import (
    get_dynamic_budget_ratios,
    determine_stage,
)


class TestE2EBookshelfInit(unittest.TestCase):
    """书籍工程初始化端到端测试（通过 CLI 调用）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_"))
        self.book_dir = self.tmpdir / "测试小说"
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_init_cli_creates_structure(self):
        """通过 CLI 调用 init_book，验证完整目录结构。"""
        script = _SCRIPTS_DIR / "init_book.py"
        # init_book.py 的 title 是位置参数，--dir 指定父目录
        result = subprocess.run(
            [sys.executable, str(script), "测试小说",
             "--dir", str(self.tmpdir),
             "--genre", "都市", "--platform", "番茄"],
            capture_output=True, text=True, timeout=30,
        )

        self.assertEqual(result.returncode, 0,
                         f"init_book 应成功退出，stderr: {result.stderr}")

        # 验证核心目录
        for d in ["大纲", "正文", "设定", "追踪"]:
            self.assertTrue((self.book_dir / d).is_dir(),
                            f"目录应存在: {d}")

        # 验证追踪文件
        tracking = ["伏笔台账.md", "角色状态.md", "章节摘要.md",
                    "时间线.md", "节奏配额.md"]
        for f in tracking:
            path = self.book_dir / "追踪" / f
            self.assertTrue(path.is_file(), f"追踪文件应存在: {f}")
            self.assertGreater(path.stat().st_size, 0,
                               f"追踪文件不应为空: {f}")

        # 验证设定文件
        settings = ["题材定位.md", "读者契约.md", "文风锚.md"]
        for f in settings:
            self.assertTrue((self.book_dir / "设定" / f).is_file(),
                            f"设定文件应存在: {f}")

        # 验证题材定位被预填
        profile = (self.book_dir / "设定" / "题材定位.md").read_text(
            encoding="utf-8")
        self.assertIn("测试小说", profile)
        self.assertIn("都市", profile)
        self.assertIn("番茄", profile)

    def test_init_cli_rejects_existing(self):
        """已存在的书籍目录默认不应覆盖。"""
        script = _SCRIPTS_DIR / "init_book.py"

        # 第一次初始化
        r1 = subprocess.run(
            [sys.executable, str(script), "测试",
             "--dir", str(self.tmpdir),
             "--genre", "玄幻", "--platform", "起点"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r1.returncode, 0)

        # 修改一个文件
        test_marker = "<!-- 测试标记 -->"
        ledger = self.tmpdir / "测试" / "追踪" / "伏笔台账.md"
        original = ledger.read_text(encoding="utf-8")
        ledger.write_text(test_marker + "\n" + original, encoding="utf-8")

        # 第二次初始化（无 --force）
        r2 = subprocess.run(
            [sys.executable, str(script), "测试",
             "--dir", str(self.tmpdir),
             "--genre", "玄幻", "--platform", "起点"],
            capture_output=True, text=True, timeout=30,
        )
        # 非零退出码表示拒绝覆盖
        self.assertNotEqual(r2.returncode, 0,
                            "已存在目录默认应拒绝覆盖")

        # 文件应保持不变
        content = ledger.read_text(encoding="utf-8")
        self.assertIn(test_marker, content,
                      "非强制模式下不应覆盖已有文件")


class TestE2ECheckTextPipeline(unittest.TestCase):
    """门禁检查端到端测试。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_gate_"))
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_full_gate_analysis_on_chapter(self):
        """对完整章节内容执行全套门禁分析。"""
        chapter = """\
第001章 寒门少年觉醒时

林辰睁开眼睛的时候，发现自己正躺在一张破旧的木板床上。

屋顶的瓦片有好几处裂缝，阳光透过缝隙斜射进来，在地面上投下斑驳的光影。空气中弥漫着一股淡淡的霉味，混合着廉价香烛的气息。

"我……回来了？"

林辰猛地坐起身，低头看着自己的双手。

那是一双年轻而瘦削的手，骨节分明，掌心带着几道薄薄的老茧。

这不是他在秘境中被敌人围攻时那双布满裂痕、鲜血淋漓的手。

"真的重生了……"林辰喃喃自语，眼眶微微发热。

他记得很清楚，上一世他为了争夺上古秘境中的纯阳道种，被六大世家联手围攻，最终在绝境中引爆修为，与敌人同归于尽。

那场爆炸惊天动地，方圆百里化为齑粉。

他以为自己必死无疑，没想到竟然重生回到了高三这一年。

就在这时，一股暖流忽然从他的丹田深处涌出，顺着经脉流转全身。

"这是……纯阳道种？！"林辰心中一震。

下一刻，无数信息涌入脑海。

百倍悟性——修炼任何功法都能瞬间领悟，举一反三！
纯阳真气——至阳至刚，净化一切阴邪！
道种空间——内部时间流速是外界的十倍！

"没想到纯阳道种竟然跟着我一起重生了！"林辰激动得浑身发抖。

有了这三样东西，这一世，他定要踏上武道巅峰，不再让任何人践踏自己的尊严！

"林辰，起来了没有？再不走就要迟到了！"门外传来王胖子的声音。

林辰深吸一口气，压下心中的激动。

"来了。"他沉声应道。

今天，就是武道路上的第一步。
"""
        lines = chapter.strip().splitlines()
        whitelist = set()

        # 1. 字数统计（count_chars 返回 tuple: (non_ws, cjk)）
        non_ws, cjk = count_chars(chapter)
        self.assertGreater(non_ws, 500)
        self.assertGreater(cjk, 400)

        # 2. 禁用词扫描（scan_lines 返回 (banned_hits, toxic_hits)）
        banned, toxic = scan_lines(lines, BANNED_WORDS, whitelist)
        self.assertIsInstance(banned, list)
        self.assertIsInstance(toxic, list)

        # 3. 结构检查（scan_structure 返回 list of tuples）
        struct_hits = scan_structure(chapter)
        self.assertIsInstance(struct_hits, list)

        # 4. 退化检测（scan_degradation 返回 list of tuples）
        deg_hits = scan_degradation(chapter, BANNED_WORDS, whitelist)
        self.assertIsInstance(deg_hits, list)

        # 5. 阻断模式检测（scan_blocking_patterns 返回 list of tuples）
        blocking_hits = scan_blocking_patterns(lines)
        self.assertIsInstance(blocking_hits, list)

        # 6. 去AI味评分（deslop_score 返回 (dict, level, advice)）
        score_dict, level, advice = deslop_score(chapter, BANNED_WORDS, whitelist)
        self.assertIsInstance(score_dict, dict)
        self.assertIn("total", score_dict)
        self.assertIn("level", score_dict)
        self.assertIsInstance(level, str)
        self.assertIsInstance(advice, str)
        total_score = score_dict["total"]
        self.assertGreaterEqual(total_score, 0)
        self.assertLessEqual(total_score, 100)

    def test_chapter_number_extraction(self):
        """章节号提取应支持多种命名格式。"""
        self.assertEqual(extract_chapter_number("第001章_测试.md"), 1)
        self.assertEqual(extract_chapter_number("第37章.md"), 37)
        self.assertEqual(extract_chapter_number("Chapter_10.txt"), None)
        self.assertIsNone(extract_chapter_number("不是章节.md"))

    def test_strip_dialogue_basic(self):
        """对话剥离应正确替换引号内容为占位符。"""
        line = '他说：「你好。」然后转身离开。'
        result = strip_dialogue(line)
        self.assertIsInstance(result, str)
        self.assertIn("「」", result)
        # 叙述部分应保留
        self.assertIn("然后转身离开", result)

    def test_strip_dialogue_preserves_narration(self):
        """纯叙述行应原样返回。"""
        line = "林辰走在山间小路上，远处的炊烟袅袅升起。"
        result = strip_dialogue(line)
        self.assertEqual(result, line)


class TestE2EBenchmarkPipeline(unittest.TestCase):
    """质量基线评测端到端测试。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_bench_"))
        self.book_dir = self.tmpdir / "评测测试"
        (self.book_dir / "正文").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def _write_chapter(self, num, text):
        path = self.book_dir / "正文" / f"第{num:03d}章_测试.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_evaluate_single_chapter(self):
        """单章质量评测应返回多维度评分。"""
        text = """\
林辰推开武道馆的大门，一股炽热的气息扑面而来。

场馆中央，数十名学员正在进行力量测试。拳靶上的数字不断跳动，伴随着一声声闷响。

"下一个，赵天霸！"

随着教练的喊声，一名身材高大的少年走到拳靶前。他活动了一下手腕，眼神中带着几分嚣张。

"看好了！"赵天霸低喝一声，右拳猛然轰出。

嘭——

拳靶剧烈晃动，数字跳到了八百二十六。

"八百多斤！不愧是赵少！"周围的学员纷纷议论。

赵天霸得意地扬了扬下巴，目光扫过人群，最后落在角落里的林辰身上。

"某些人啊，淬体三重都费劲，还来凑什么热闹。"他嗤笑一声。

众人的目光齐刷刷地投向林辰，有同情，有幸灾乐祸。

林辰面无表情，仿佛没听见。

他在等一个一鸣惊人的机会。
"""
        ch_path = self._write_chapter(1, text)

        result = evaluate_chapter(ch_path)
        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result, "评测不应返回错误")
        # 实际返回的键
        self.assertIn("file", result)
        self.assertIn("chars", result)
        self.assertIn("cjk", result)
        self.assertIn("ai_score", result)
        self.assertIn("avg_sent_len", result)
        self.assertIn("dialogue_ratio", result)
        self.assertIn("rhythm_balance", result)
        self.assertIn("gate_pass_rate", result)

        # 分数范围校验
        for key in ["ai_score", "rhythm_balance"]:
            self.assertGreaterEqual(result[key], 0,
                                    f"{key} 应 >= 0")
            self.assertLessEqual(result[key], 100,
                                 f"{key} 应 <= 100")

    def test_evaluate_book_multiple_chapters(self):
        """全书评测应返回章节列表和汇总统计。"""
        chapters_text = [
            # 第1章
            "林辰推开武道馆的大门，一股炽热的气息扑面而来。" * 10,
            # 第2章
            "赵天霸得意地扬了扬下巴，目光扫过人群。" * 12,
            # 第3章
            "林辰面无表情，他在等一个一鸣惊人的机会。" * 15,
        ]
        for i, text in enumerate(chapters_text, 1):
            self._write_chapter(i, text)

        result = evaluate_book(self.book_dir)
        self.assertNotIn("error", result, "全书评测不应返回错误")
        self.assertIn("chapters", result)
        self.assertIn("summary", result)
        self.assertIn("total_chapters", result)
        self.assertEqual(result["total_chapters"], 3)

    def test_trend_analysis(self):
        """趋势分析应返回各指标的变化方向。"""
        # 创建6章内容（trend_analysis 默认需要 >= 5 章）
        chapters_text = [
            "林辰推开武道馆的大门，一股炽热的气息扑面而来。" * 10,
            "赵天霸得意地扬了扬下巴，目光扫过人群。" * 12,
            "林辰面无表情，他在等一个一鸣惊人的机会。" * 11,
            "教练皱了皱眉，似乎对这个结果不太满意。" * 13,
            "苏清雪站在角落，安静地看着这一切。" * 14,
            "比赛结束后，林辰独自离开场馆。" * 10,
        ]
        for i, text in enumerate(chapters_text, 1):
            self._write_chapter(i, text)

        result = trend_analysis(self.book_dir)
        self.assertNotIn("error", result, "趋势分析不应返回错误")
        self.assertIn("trend", result)
        self.assertIn("last_n", result)
        self.assertIn("total_chapters", result)


class TestE2EStaticCheckPipeline(unittest.TestCase):
    """静态一致性检查端到端测试。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_static_"))
        self.book_dir = self.tmpdir / "静态检查测试"
        (self.book_dir / "正文").mkdir(parents=True)
        (self.book_dir / "追踪" / "门禁").mkdir(parents=True)
        (self.book_dir / "设定" / "角色").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def _write_chapter(self, num, text):
        path = self.book_dir / "正文" / f"第{num:03d}章_测试.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_wordcount_check_single_chapter(self):
        """单章字数检查应返回 PASS（无法对比）。"""
        text = "这是一段测试文字。" * 20
        self._write_chapter(1, text)

        result = check_wordcount(self.book_dir, 1)
        self.assertIsInstance(result, CheckResult)
        self.assertEqual(result.status, "PASS")

    def test_wordcount_check_multi_chapter(self):
        """多章字数检查应能对比相邻章节。"""
        self._write_chapter(1, "短章。" * 5)
        self._write_chapter(2, "这是一段较长的章节内容。" * 50)

        result = check_wordcount(self.book_dir)
        self.assertIsInstance(result, CheckResult)
        # 字数差异大应返回 WARN 或 FAIL
        self.assertIn(result.status, ["WARN", "FAIL", "PASS"])

    def test_character_check(self):
        """角色一致性检查应能检测到正文角色。"""
        # 写入角色卡
        (self.book_dir / "设定" / "角色" / "林辰.md").write_text(
            "# 林辰\n\n男主角。", encoding="utf-8")
        (self.book_dir / "追踪" / "角色状态.md").write_text(
            "# 角色状态\n\n## 林辰\n- 境界：淬体三重\n",
            encoding="utf-8")

        # 写正文（含角色名）
        self._write_chapter(1, "林辰走了过来。苏清雪点了点头。")

        result = check_character(self.book_dir, 1)
        self.assertIsInstance(result, CheckResult)

    def test_collect_chapter_files(self):
        """章节文件收集应正确排序。"""
        self._write_chapter(3, "c")
        self._write_chapter(1, "a")
        self._write_chapter(2, "b")

        files = _collect_chapter_files(self.book_dir / "正文")
        self.assertEqual(len(files), 3)
        # 返回 [(num, Path), ...] 按章号排序
        self.assertEqual(files[0][0], 1)
        self.assertEqual(files[2][0], 3)
        self.assertIn("第001章", files[0][1].name)
        self.assertIn("第003章", files[2][1].name)


class TestE2ENovelFlow(unittest.TestCase):
    """工作流管理端到端测试（锁+快照）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_flow_"))
        self.book_dir = self.tmpdir / "流程测试"
        (self.book_dir / "追踪").mkdir(parents=True)
        (self.book_dir / "大纲").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_lock_and_snapshot_workflow(self):
        """完整的锁+快照+回滚工作流测试。"""
        # 写入初始文件（create_snapshot 只备份 追踪/ 目录下的文件）
        ledger = self.book_dir / "追踪" / "伏笔台账.md"
        ledger.write_text("初始内容 v1", encoding="utf-8")

        summary = self.book_dir / "追踪" / "章节摘要.md"
        summary.write_text("初始摘要", encoding="utf-8")

        # 1. 获取锁（需要 command 参数）
        locked, lock_msg = acquire_lock(self.book_dir, "write", 1)
        self.assertTrue(locked, "应能获取锁")

        # 2. 创建快照
        ts = create_snapshot(self.book_dir)
        self.assertIsNotNone(ts, "应创建快照成功")

        # 3. 修改文件
        ledger.write_text("修改后的内容 v2", encoding="utf-8")
        summary.write_text("修改后的摘要", encoding="utf-8")

        # 4. 回滚
        restored, restore_msg = restore_snapshot(self.book_dir, ts)
        self.assertTrue(restored, f"应能恢复快照: {restore_msg}")

        # 5. 验证追踪文件被还原
        self.assertEqual(ledger.read_text(encoding="utf-8"),
                         "初始内容 v1")
        self.assertEqual(summary.read_text(encoding="utf-8"),
                         "初始摘要")

        # 6. 释放锁（返回 None，不检查返回值）
        release_lock(self.book_dir)
        # 锁文件应已删除
        lock_file = self.book_dir / "追踪" / ".flow_lock.json"
        self.assertFalse(lock_file.exists(), "锁文件应已删除")

    def test_lock_prevents_concurrent_access(self):
        """已持有锁时再次获取应失败。"""
        # 第一次获取
        ok1, _ = acquire_lock(self.book_dir, "write", 1)
        self.assertTrue(ok1)

        # 第二次获取（应失败）
        ok2, msg = acquire_lock(self.book_dir, "write", 2)
        self.assertFalse(ok2, "重复获取锁应失败")
        self.assertIn("锁", msg)

        # 释放后应能重新获取
        release_lock(self.book_dir)
        ok3, _ = acquire_lock(self.book_dir, "write", 3)
        self.assertTrue(ok3)
        release_lock(self.book_dir)


class TestE2EConfig(unittest.TestCase):
    """配置与动态上下文端到端测试。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_cfg_"))
        self.book_dir = self.tmpdir / "配置测试"
        (self.book_dir / "大纲").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_dynamic_budget_by_stage(self):
        """不同阶段的上下文预算比例应不同。"""
        # 实际阶段名：opening / development / deepwater / finale
        stages = ["opening", "development", "deepwater", "finale"]

        for stage in stages:
            ratios = get_dynamic_budget_ratios(stage)
            self.assertIsInstance(ratios, dict)
            self.assertGreater(len(ratios), 0,
                               f"{stage} 阶段应有预算组件")
            total = sum(ratios.values())
            self.assertAlmostEqual(total, 1.0, places=1,
                                   msg=f"{stage} 阶段预算比例之和应接近1")

    def test_dynamic_budget_invalid_stage_fallback(self):
        """无效阶段应返回默认预算。"""
        ratios = get_dynamic_budget_ratios("nonexistent")
        self.assertIsInstance(ratios, dict)
        total = sum(ratios.values())
        self.assertAlmostEqual(total, 1.0, places=1)

    def test_stage_determination(self):
        """进度百分比应映射到正确的阶段。"""
        # 创建含总章数的总纲
        (self.book_dir / "大纲" / "总纲.md").write_text(
            "全书共100章", encoding="utf-8")

        # 实际阶段名：opening / development / deepwater / finale
        self.assertEqual(determine_stage(self.book_dir, 1), "opening")
        self.assertEqual(determine_stage(self.book_dir, 15), "development")
        self.assertEqual(determine_stage(self.book_dir, 50), "deepwater")
        self.assertEqual(determine_stage(self.book_dir, 90), "finale")


class TestE2EFullIntegration(unittest.TestCase):
    """完整集成测试：模拟真实写书流程。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_e2e_full_"))
        self.book_dir = self.tmpdir / "全流程测试"
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_init_write_check_review_flow(self):
        """完整流程：初始化 → 写章 → 门禁 → 评测 → 静态检查。"""
        # Step 1: 初始化书籍（title 是位置参数）
        init_script = _SCRIPTS_DIR / "init_book.py"
        r_init = subprocess.run(
            [sys.executable, str(init_script), "全流程测试",
             "--dir", str(self.tmpdir),
             "--genre", "玄幻", "--platform", "起点"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r_init.returncode, 0, "初始化应成功")

        # Step 2: 写入章节
        chapter_text = """\
# 第001章 觉醒

黎明时分，天色微亮。

林凡从床上坐起，只觉得浑身酸痛。

"又是这个梦……"他揉了揉太阳穴。

最近一个月，他每晚都做同一个梦——梦里有一片无边无际的星海，星海中央悬浮着一枚九彩道种。每次他想伸手去抓，梦就醒了。

"林凡，起来修炼了！"门外传来父亲的声音。

"来了。"林凡应了一声，迅速穿好衣服。

今天是家族月度考核的日子。

如果不能突破淬体三重，他就要被发配到外门，一辈子只能做杂役。

"我不会认输的。"林凡握紧拳头，眼神坚定。

走出房门，清晨的阳光洒在他身上，暖洋洋的。

庭院里，已经有不少家族子弟在修炼了。

"哟，这不是我们的林大天才吗？怎么，还没突破淬体三重啊？"一个尖酸的声音响起。

林凡转头看去，说话的是林虎，族长家的二公子。

"关你什么事。"林凡淡淡道。

"呵，嘴还挺硬。等会儿考核的时候，我看你怎么哭。"林虎冷笑一声，扬长而去。

林凡没有理会他，自顾自地走到角落开始修炼。

《基础吐纳法》运转起来，天地间稀薄的灵气缓缓涌入体内。

就在这时——

轰！

林凡脑海中忽然一声巨响，那枚梦中的九彩道种，竟然真的出现了！

"这是……"林凡惊呆了。

下一刻，一股无比精纯的能量从道种中涌出，顺着经脉流遍全身。

咔嚓——

淬体三重，突破！

而且还在继续！

四重！五重！六重！

一直到淬体七重，势头才缓缓停下。

林凡猛地睁开眼睛，眼中精光四射。

"三十年河东，三十年河西，莫欺少年穷！"他在心中呐喊。

今天，就是他逆袭的开始！
"""
        chapter_path = self.book_dir / "正文" / "第001章_觉醒.md"
        chapter_path.write_text(chapter_text, encoding="utf-8")

        lines = chapter_text.strip().splitlines()
        whitelist = set()

        # Step 3: 门禁检查
        non_ws, cjk = count_chars(chapter_text)
        self.assertGreater(non_ws, 500,
                           "章节字数应 > 500")

        banned, toxic = scan_lines(lines, BANNED_WORDS, whitelist)
        self.assertIsInstance(banned, list)

        deg_hits = scan_degradation(chapter_text, BANNED_WORDS, whitelist)
        self.assertIsInstance(deg_hits, list)

        ai_score_dict, ai_level, ai_advice = deslop_score(chapter_text, BANNED_WORDS, whitelist)
        ai_score = ai_score_dict["total"]
        self.assertGreaterEqual(ai_score, 0)
        self.assertLessEqual(ai_score, 100)

        # Step 4: 质量评测
        bench_result = evaluate_chapter(chapter_path)
        self.assertNotIn("error", bench_result, "评测不应出错")
        self.assertIn("ai_score", bench_result)
        self.assertIn("rhythm_balance", bench_result)

        # Step 5: 静态一致性检查
        wc_result = check_wordcount(self.book_dir, 1)
        self.assertIsInstance(wc_result, CheckResult)

        # 输出总结
        print(f"\n{'='*50}")
        print(f"[E2E] 全流程测试完成")
        print(f"  章节字数: {non_ws} (汉字 {cjk})")
        print(f"  AI味评分: {ai_score:.1f}")
        print(f"  节奏均衡度: {bench_result.get('rhythm_balance', 'N/A')}")
        print(f"  对话占比: {bench_result.get('dialogue_ratio', 'N/A')}%")
        print(f"  字数检查: {wc_result.status}")
        print(f"{'='*50}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
