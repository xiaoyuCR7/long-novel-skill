#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_quality_score.py — 测试 quality_score.py 章节质量多维评分系统。

覆盖工具函数（字数统计、段落/句子切分、对话提取、分数限幅、等级判定）、
AI腔控制评分维度，以及 CLI score 子命令的端到端子进程测试。

运行方式：
    python scripts/tests/test_quality_score.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_score import (
    count_chars,
    split_paragraphs,
    split_sentences,
    extract_dialogue,
    clamp_score,
    get_grade,
    score_ai_control,
    score_chapter,
    DEFAULT_THRESHOLD,
)


# =========================================================
# 测试用中文小说文本样本（含对话、动作、描写，300+ 汉字）
# =========================================================

SAMPLE_CHAPTER = """\
清晨的阳光透过窗帘缝隙洒进房间，空气中飘着淡淡的桂花香。

林辰睁开眼，盯着天花板看了好一会儿。昨晚的梦太真实了，梦里他站在悬崖边，脚下是深不见底的深渊，身后是追赶而来的黑衣人。

"又做这个梦了。"他翻身坐起，揉了揉发胀的太阳穴。

门外传来急促的敲门声。

"林辰！快点起来，今天武道馆有考核！"王胖子的大嗓门隔着门板都震得人耳朵疼。

"知道了，马上。"林辰应了一声，迅速穿好衣服。

他推开房门，走廊里已经人来人往。武道馆的考核每年只有一次，错过就要再等一年。林辰握了握拳头，掌心的老茧硬邦邦的，那是三年苦练留下的痕迹。

走到武道馆门口，赵天霸正靠在墙边，嘴角挂着一丝嘲讽。

"哟，林辰，今年还来丢人啊？"赵天霸嗤笑道。

林辰没搭理他，径直走进场馆。他知道，与其用嘴还击，不如用拳头说话。

考核开始，拳靶上的数字不断跳动。八百、九百、一千……

轮到林辰时，他右拳猛然轰出。

嘭——

拳靶剧烈晃动，数字停在一千二百。

全场安静了一瞬，随即爆发出阵阵惊叹。
"""

# 含AI腔的文本样本（禁用词、毒句式、结尾升华）
AI_HEAVY_TEXT = """\
他不禁缓缓抬起头，嘴角勾起一抹微笑，眼中闪过一丝复杂的神色。

这不是结束，而是新的开始。他深吸一口气，仿佛一切都豁然开朗。

他感到一阵心旷神怡，如释重负。之所以能够走到今天，是因为他从未放弃。

命运的齿轮缓缓转动，这意味着一切才刚刚开始。
"""

# 纯英文/数字文本（无汉字）
NO_CJK_TEXT = "Hello World 12345 abcdef"


class TestCountChars(unittest.TestCase):
    """字数统计功能。"""

    def test_pure_chinese(self):
        """纯中文文本统计正确。"""
        non_ws, cjk = count_chars("你好世界")
        self.assertEqual(non_ws, 4)
        self.assertEqual(cjk, 4)

    def test_mixed_text(self):
        """中英混合文本统计正确。"""
        non_ws, cjk = count_chars("Hello 世界 123")
        # 非空白：Hello(5) + 世界(2) + 123(3) = 10
        self.assertEqual(non_ws, 10)
        self.assertEqual(cjk, 2)

    def test_with_punctuation(self):
        """含标点的文本统计正确。"""
        non_ws, cjk = count_chars("你好，世界！")
        # 非空白：6（含标点），汉字：4
        self.assertEqual(non_ws, 6)
        self.assertEqual(cjk, 4)

    def test_whitespace_only(self):
        """纯空白文本返回零。"""
        non_ws, cjk = count_chars("  \n\t  ")
        self.assertEqual(non_ws, 0)
        self.assertEqual(cjk, 0)

    def test_empty_string(self):
        """空字符串返回零。"""
        non_ws, cjk = count_chars("")
        self.assertEqual(non_ws, 0)
        self.assertEqual(cjk, 0)

    def test_returns_tuple(self):
        """返回值为二元组。"""
        result = count_chars("测试")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_sample_chapter_has_enough_cjk(self):
        """样本章节汉字数大于300。"""
        non_ws, cjk = count_chars(SAMPLE_CHAPTER)
        self.assertGreater(cjk, 300)
        self.assertGreaterEqual(non_ws, cjk)


class TestSplitParagraphs(unittest.TestCase):
    """段落切分功能。"""

    def test_multiple_paragraphs(self):
        """空行分隔的文本正确切分。"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        paras = split_paragraphs(text)
        self.assertEqual(len(paras), 3)
        self.assertEqual(paras[0], "第一段内容。")
        self.assertEqual(paras[1], "第二段内容。")
        self.assertEqual(paras[2], "第三段内容。")

    def test_single_paragraph(self):
        """无空行的文本作为单段。"""
        text = "这是一段没有空行的文本内容。"
        paras = split_paragraphs(text)
        self.assertEqual(len(paras), 1)

    def test_strips_whitespace(self):
        """切分后去除首尾空白。"""
        text = "  第一段  \n\n  第二段  "
        paras = split_paragraphs(text)
        self.assertEqual(paras[0], "第一段")
        self.assertEqual(paras[1], "第二段")

    def test_empty_text(self):
        """空文本返回空列表。"""
        paras = split_paragraphs("")
        self.assertEqual(paras, [])

    def test_single_newline_no_split(self):
        """无空行时文本作为单段返回（不按单换行切分）。"""
        text = "第一行。\n第二行。\n第三行。"
        paras = split_paragraphs(text)
        # 无双换行时，整段文本作为一个段落返回
        self.assertEqual(len(paras), 1)

    def test_whitespace_only_returns_empty(self):
        """纯空白文本返回空列表。"""
        paras = split_paragraphs("  \n\n  \n\n  ")
        self.assertEqual(paras, [])

    def test_returns_list(self):
        """返回值为列表。"""
        result = split_paragraphs("测试文本")
        self.assertIsInstance(result, list)

    def test_sample_chapter_multiple_paragraphs(self):
        """样本章节切分出多个段落。"""
        paras = split_paragraphs(SAMPLE_CHAPTER)
        self.assertGreater(len(paras), 5)


class TestSplitSentences(unittest.TestCase):
    """句子切分功能。"""

    def test_chinese_punctuation(self):
        """中文句号问号叹号正确切分。"""
        text = "第一句。第二句！第三句？"
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 3)
        self.assertEqual(sentences[0], "第一句")
        self.assertEqual(sentences[1], "第二句")
        self.assertEqual(sentences[2], "第三句")

    def test_ellipsis(self):
        """省略号正确切分。"""
        text = "他说了一句…然后沉默了"
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 2)

    def test_english_punctuation(self):
        """英文标点正确切分。"""
        text = "Hello! How are you? I am fine."
        sentences = split_sentences(text)
        self.assertGreaterEqual(len(sentences), 2)

    def test_newline_split(self):
        """换行符也作为分隔符。"""
        text = "第一行\n第二行\n第三行"
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 3)

    def test_empty_text(self):
        """空文本返回空列表。"""
        sentences = split_sentences("")
        self.assertEqual(sentences, [])

    def test_strips_whitespace(self):
        """切分后去除首尾空白。"""
        text = "  第一句  。  第二句  。"
        sentences = split_sentences(text)
        self.assertEqual(sentences[0], "第一句")
        self.assertEqual(sentences[1], "第二句")

    def test_returns_list(self):
        """返回值为列表。"""
        result = split_sentences("测试。")
        self.assertIsInstance(result, list)

    def test_sample_chapter_multiple_sentences(self):
        """样本章节切分出多个句子。"""
        sentences = split_sentences(SAMPLE_CHAPTER)
        self.assertGreater(len(sentences), 10)


class TestExtractDialogue(unittest.TestCase):
    """对话提取功能。"""

    def test_corner_brackets(self):
        """日式角引号正确提取。"""
        text = "他说：「你好。」"
        dialogue = extract_dialogue(text)
        self.assertEqual(dialogue, "你好。")

    def test_white_corner_brackets(self):
        """白色角引号正确提取。"""
        text = "他说：『你好。』"
        dialogue = extract_dialogue(text)
        self.assertEqual(dialogue, "你好。")

    def test_multiple_dialogues(self):
        """多段对话用换行连接。"""
        text = "「第一句。」「第二句。」"
        dialogue = extract_dialogue(text)
        self.assertEqual(dialogue, "第一句。\n第二句。")

    def test_no_dialogue(self):
        """无对话返回空字符串。"""
        text = "这是一段没有对话的叙述文字。"
        dialogue = extract_dialogue(text)
        self.assertEqual(dialogue, "")

    def test_returns_string(self):
        """返回值为字符串。"""
        result = extract_dialogue("测试")
        self.assertIsInstance(result, str)

    def test_sample_chapter_extracts_dialogue(self):
        """样本章节提取出对话内容。"""
        dialogue = extract_dialogue(SAMPLE_CHAPTER)
        self.assertGreater(len(dialogue), 0)
        self.assertIn("又做这个梦了", dialogue)
        self.assertIn("知道了，马上", dialogue)

    def test_empty_text(self):
        """空文本返回空字符串。"""
        dialogue = extract_dialogue("")
        self.assertEqual(dialogue, "")


class TestClampScore(unittest.TestCase):
    """分数限幅功能。"""

    def test_normal_range(self):
        """正常范围内的分数不变。"""
        self.assertEqual(clamp_score(50.0), 50.0)
        self.assertEqual(clamp_score(75.5), 75.5)

    def test_above_100(self):
        """超过100分限幅为100。"""
        self.assertEqual(clamp_score(150.0), 100.0)
        self.assertEqual(clamp_score(100.0), 100.0)

    def test_below_0(self):
        """低于0分限幅为0。"""
        self.assertEqual(clamp_score(-10.0), 0.0)
        self.assertEqual(clamp_score(0.0), 0.0)

    def test_boundary_values(self):
        """边界值正确。"""
        self.assertEqual(clamp_score(0.0), 0.0)
        self.assertEqual(clamp_score(100.0), 100.0)

    def test_returns_numeric(self):
        """返回值为数值类型。"""
        result = clamp_score(50)
        self.assertIsInstance(result, (int, float))
        result_float = clamp_score(50.0)
        self.assertIsInstance(result_float, float)


class TestGetGrade(unittest.TestCase):
    """评分等级功能。"""

    def test_grade_a(self):
        """85分以上为A（优秀）。"""
        grade, label = get_grade(85)
        self.assertEqual(grade, "A")
        self.assertEqual(label, "优秀")
        grade, label = get_grade(100)
        self.assertEqual(grade, "A")
        self.assertEqual(label, "优秀")

    def test_grade_b(self):
        """70-84分为B（良好）。"""
        grade, label = get_grade(70)
        self.assertEqual(grade, "B")
        self.assertEqual(label, "良好")
        grade, label = get_grade(84)
        self.assertEqual(grade, "B")

    def test_grade_c(self):
        """55-69分为C（合格）。"""
        grade, label = get_grade(55)
        self.assertEqual(grade, "C")
        self.assertEqual(label, "合格")
        grade, label = get_grade(69)
        self.assertEqual(grade, "C")

    def test_grade_d(self):
        """40-54分为D（需修改）。"""
        grade, label = get_grade(40)
        self.assertEqual(grade, "D")
        self.assertEqual(label, "需修改")
        grade, label = get_grade(54)
        self.assertEqual(grade, "D")

    def test_grade_f(self):
        """0-39分为F（不合格）。"""
        grade, label = get_grade(0)
        self.assertEqual(grade, "F")
        self.assertEqual(label, "不合格")
        grade, label = get_grade(39)
        self.assertEqual(grade, "F")

    def test_returns_tuple(self):
        """返回值为二元组。"""
        result = get_grade(50)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_boundary_check(self):
        """等级边界值精确：上限属于高一级。"""
        # 84 → B, 85 → A
        self.assertEqual(get_grade(84)[0], "B")
        self.assertEqual(get_grade(85)[0], "A")
        # 69 → C, 70 → B
        self.assertEqual(get_grade(69)[0], "C")
        self.assertEqual(get_grade(70)[0], "B")
        # 54 → D, 55 → C
        self.assertEqual(get_grade(54)[0], "D")
        self.assertEqual(get_grade(55)[0], "C")
        # 39 → F, 40 → D
        self.assertEqual(get_grade(39)[0], "F")
        self.assertEqual(get_grade(40)[0], "D")


class TestScoreAiControl(unittest.TestCase):
    """AI腔控制评分功能。"""

    def test_return_structure(self):
        """返回结构包含 score、details、issues 三个键。"""
        result = score_ai_control(SAMPLE_CHAPTER)
        self.assertIsInstance(result, dict)
        self.assertIn("score", result)
        self.assertIn("details", result)
        self.assertIn("issues", result)

    def test_score_range(self):
        """评分在 0-100 范围内。"""
        result = score_ai_control(SAMPLE_CHAPTER)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_clean_text_high_score(self):
        """干净文本（无AI腔）得分较高。"""
        result = score_ai_control(SAMPLE_CHAPTER)
        self.assertGreater(result["score"], 50)

    def test_no_cjk_returns_zero(self):
        """无汉字文本返回0分。"""
        result = score_ai_control(NO_CJK_TEXT)
        self.assertEqual(result["score"], 0)
        self.assertIn("error", result["details"])
        self.assertIn("无汉字", result["issues"][0])

    def test_empty_text_returns_zero(self):
        """空文本返回0分。"""
        result = score_ai_control("")
        self.assertEqual(result["score"], 0)

    def test_ai_heavy_text_lower_score(self):
        """AI腔重的文本得分低于干净文本。"""
        clean_score = score_ai_control(SAMPLE_CHAPTER)["score"]
        ai_heavy_score = score_ai_control(AI_HEAVY_TEXT)["score"]
        self.assertLess(ai_heavy_score, clean_score,
                        "AI腔重的文本得分应低于干净文本")

    def test_ai_heavy_text_has_issues(self):
        """AI腔重的文本应检测出问题。"""
        result = score_ai_control(AI_HEAVY_TEXT)
        self.assertIsInstance(result["issues"], list)
        self.assertGreater(len(result["issues"]), 0)

    def test_details_structure(self):
        """details 包含关键检测指标。"""
        result = score_ai_control(SAMPLE_CHAPTER)
        details = result["details"]
        expected_keys = {
            "ai_word_density",
            "ai_word_hits",
            "toxic_hits",
            "engineering_leaks",
            "parallelism_count",
            "psych_density",
            "tag_density",
            "summary_ending",
        }
        self.assertTrue(expected_keys.issubset(details.keys()))

    def test_toxic_pattern_detection(self):
        """毒句式被正确检测。"""
        result = score_ai_control(AI_HEAVY_TEXT)
        details = result["details"]
        # AI_HEAVY_TEXT 含「不是…而是…」「之所以…是因为」等毒句式
        toxic_names = [h["pattern"] for h in details["toxic_hits"]]
        self.assertGreater(len(toxic_names), 0,
                           "应检测到毒句式")

    def test_engineering_word_detection(self):
        """工程词泄漏被正确检测。"""
        text = "这个伏笔和钩子很重要，读者会喜欢这个人设。"
        result = score_ai_control(text)
        details = result["details"]
        self.assertGreater(len(details["engineering_leaks"]), 0,
                           "应检测到工程词泄漏")

    def test_ai_word_detection(self):
        """禁用词被正确检测。"""
        result = score_ai_control(AI_HEAVY_TEXT)
        details = result["details"]
        # AI_HEAVY_TEXT 含「不禁」「缓缓」「嘴角勾起」等禁用词
        self.assertGreater(details["ai_word_density"], 0,
                           "禁用词密度应大于0")

    def test_summary_ending_detection(self):
        """结尾升华被正确检测。"""
        result = score_ai_control(AI_HEAVY_TEXT)
        details = result["details"]
        # AI_HEAVY_TEXT 最后一段含「这意味着」「一切」
        self.assertTrue(details["summary_ending"],
                        "应检测到结尾升华")

    def test_issues_is_list(self):
        """issues 为列表类型。"""
        result = score_ai_control(SAMPLE_CHAPTER)
        self.assertIsInstance(result["issues"], list)

    def test_score_is_numeric(self):
        """score 为数值类型。"""
        result = score_ai_control(SAMPLE_CHAPTER)
        self.assertIsInstance(result["score"], (int, float))


class TestScoreChapter(unittest.TestCase):
    """综合评分功能（集成测试）。"""

    def test_return_structure(self):
        """综合评分返回完整结构。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        self.assertIsInstance(result, dict)
        self.assertIn("total_score", result)
        self.assertIn("grade", result)
        self.assertIn("grade_label", result)
        self.assertIn("dimensions", result)
        self.assertIn("radar", result)
        self.assertIn("issues", result)
        self.assertIn("passed", result)
        self.assertIn("char_count", result)

    def test_total_score_range(self):
        """总分在 0-100 范围内。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        self.assertGreaterEqual(result["total_score"], 0)
        self.assertLessEqual(result["total_score"], 100)

    def test_dimensions_count(self):
        """包含七个维度。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        self.assertEqual(len(result["dimensions"]), 7)

    def test_radar_count(self):
        """雷达图包含七个维度数据。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        self.assertEqual(len(result["radar"]), 7)

    def test_chapter_number(self):
        """章号正确记录。"""
        result = score_chapter(SAMPLE_CHAPTER, 37)
        self.assertEqual(result["chapter"], 37)

    def test_grade_consistency(self):
        """等级与总分一致。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        total = result["total_score"]
        grade, _ = get_grade(total)
        self.assertEqual(result["grade"], grade)

    def test_passed_flag(self):
        """passed 标志与阈值一致。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        expected_passed = result["total_score"] >= DEFAULT_THRESHOLD
        self.assertEqual(result["passed"], expected_passed)

    def test_char_count_structure(self):
        """字数统计结构正确。"""
        result = score_chapter(SAMPLE_CHAPTER, 1)
        self.assertIn("total", result["char_count"])
        self.assertIn("chinese", result["char_count"])
        non_ws, cjk = count_chars(SAMPLE_CHAPTER)
        self.assertEqual(result["char_count"]["total"], non_ws)
        self.assertEqual(result["char_count"]["chinese"], cjk)


class TestCLIScore(unittest.TestCase):
    """CLI score 子命令测试（子进程调用）。"""

    def setUp(self):
        """创建临时目录和章节文件。"""
        self.tmpdir = Path(tempfile.mkdtemp(prefix="lns_qs_"))
        self.book_dir = self.tmpdir / "测试小说"
        (self.book_dir / "正文").mkdir(parents=True)
        self.chapter_path = self.book_dir / "正文" / "第001章_测试.md"
        self.chapter_path.write_text(SAMPLE_CHAPTER, encoding="utf-8")
        self.script = SCRIPT_DIR / "quality_score.py"
        self.addCleanup(shutil.rmtree, str(self.tmpdir), ignore_errors=True)

    def test_score_json_output(self):
        """score 命令输出合法 JSON 并成功退出。"""
        result = subprocess.run(
            [sys.executable, str(self.script), "score",
             str(self.chapter_path), "--chapter", "1"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                         f"score 应成功退出，stderr: {result.stderr}")
        data = json.loads(result.stdout)
        self.assertIn("total_score", data)
        self.assertIn("grade", data)
        self.assertIn("dimensions", data)
        self.assertEqual(data["chapter"], 1)

    def test_score_with_book_dir(self):
        """指定 --book-dir 时评分结果落盘到 JSON 文件。"""
        result = subprocess.run(
            [sys.executable, str(self.script), "score",
             str(self.chapter_path), "--chapter", "1",
             "--book-dir", str(self.book_dir)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                         f"score 应成功退出，stderr: {result.stderr}")
        score_file = self.book_dir / "追踪" / "质量评分" / "quality_ch1.json"
        self.assertTrue(score_file.exists(), "评分文件应已落盘")
        saved = json.loads(score_file.read_text(encoding="utf-8"))
        self.assertIn("total_score", saved)
        self.assertEqual(saved["chapter"], 1)

    def test_score_nonexistent_file(self):
        """不存在的文件返回退出码 2。"""
        result = subprocess.run(
            [sys.executable, str(self.script), "score",
             str(self.tmpdir / "不存在.md"), "--chapter", "1"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", result.stderr)

    def test_score_markdown_output(self):
        """--markdown 输出 Markdown 格式报告。"""
        result = subprocess.run(
            [sys.executable, str(self.script), "score",
             str(self.chapter_path), "--chapter", "1",
             "--markdown"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                         f"score --markdown 应成功退出，stderr: {result.stderr}")
        self.assertIn("质量评分报告", result.stdout)
        self.assertIn("维度评分", result.stdout)

    def test_score_low_quality_exit_code(self):
        """低质量文本（无汉字）退出码为 1（未通过阈值）。"""
        bad_path = self.book_dir / "正文" / "第002章_差.md"
        bad_path.write_text("Hello World 12345", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.script), "score",
             str(bad_path), "--chapter", "2"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 1,
                         "低质量文本应返回退出码 1（未通过阈值）")

    def test_score_chapter_number_in_output(self):
        """输出 JSON 中包含正确的章号。"""
        result = subprocess.run(
            [sys.executable, str(self.script), "score",
             str(self.chapter_path), "--chapter", "37"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                         f"score 应成功退出，stderr: {result.stderr}")
        data = json.loads(result.stdout)
        self.assertEqual(data["chapter"], 37)


if __name__ == "__main__":
    unittest.main(verbosity=2)
