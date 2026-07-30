#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_style_fingerprint.py — 测试 style_fingerprint.py 文风指纹提取与对比（纯标准库）。

覆盖六维文风量化、容差解析、文风锚 Markdown 生成与解析、指标对比，
以及 extract / compare 两个 CLI 子命令的端到端调用。

运行方式：
    python scripts/tests/test_style_fingerprint.py
    python -m unittest scripts.tests.test_style_fingerprint
"""

import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path

# 把 scripts 目录加入 sys.path，以便直接 import style_fingerprint
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from style_fingerprint import (
    count_chars,
    compute_six_dimensions,
    parse_tolerance,
    format_anchor_md,
    parse_anchor_md,
    compare_metrics,
    DEFAULT_TOLERANCE,
)

# style_fingerprint.py 脚本绝对路径，供 CLI 子进程测试使用
SCRIPT_PATH = SCRIPT_DIR / "style_fingerprint.py"


# ---------------------------------------------------------------------------
# 真实中文小说样本（>=200 字），用作测试基准文本
# ---------------------------------------------------------------------------
SAMPLE_NOVEL = (
    "清晨的雾气尚未散尽，少年便背着一柄长剑走出了客栈。街道上空无一人，"
    "只有几只麻雀在屋檐下叽叽喳喳地叫着。他抬头望了一眼天色，眉头微微皱起，"
    "今日怕是又要赶上一整天的路。\n\n"
    "「你便是那个号称剑道天才的林晚舟？」一个苍老的声音从巷口传来。"
    "林晚舟停下脚步，转头看去，只见一位白发老者倚靠在墙边，手中拄着一根竹杖，"
    "目光却锐利如鹰。\n\n"
    "「前辈有何指教？」他不卑不亢地问道。老者嘿嘿一笑，从袖中取出一枚玉佩，"
    "随手抛了过来。「接住。」林晚舟抬手接住玉佩，只觉入手冰凉，"
    "玉佩表面刻着一个古篆字，隐隐有光流转其中。\n\n"
    "「这枚玉佩你替我保管三日。三日后，子时，城北枯井见。」"
    "老者说完这番话，身形一晃，竟凭空消失在浓雾之中。"
    "他握着玉佩站在原地，心中疑虑重重，这老者来历不明，所托之事又极为蹊跷，"
    "究竟是机缘，还是陷阱？"
)

# 对话密集、句子极短的样本，用于触发 compare 偏离
SAMPLE_DIALOGUE = (
    "「来了。」「走了。」「好的。」「不好。」\n\n"
    "「快跑！」「别跑！」「等等。」\n\n"
    "「什么？」「真的？」「骗人！」"
)


def _make_metrics(avg_sent_len=18.5, dialogue_ratio=32.0, median_para_len=45.0,
                  q=30.0, e=15.0, ellipsis=10.0, ratio=1.5,
                  short_count=6, long_count=4, top_words=None, non_ws=1000):
    """构造一份完整的六维指标字典，供对比测试使用。"""
    if top_words is None:
        top_words = [("林晚舟", 3), ("玉佩", 2)]
    return {
        "avg_sent_len": avg_sent_len,
        "dialogue_ratio": dialogue_ratio,
        "median_para_len": median_para_len,
        "punct_rhythm": {"q": q, "e": e, "ellipsis": ellipsis},
        "top_words": top_words,
        "sentence_pattern": {
            "alternation_ratio": ratio,
            "short_count": short_count,
            "long_count": long_count,
        },
        "non_ws": non_ws,
    }


# ---------------------------------------------------------------------------
# count_chars
# ---------------------------------------------------------------------------
class TestCountChars(unittest.TestCase):
    """count_chars 返回 (非空白字符数, 汉字数)。"""

    def test_pure_chinese(self):
        """纯中文文本：非空白数等于汉字数。"""
        non_ws, cjk = count_chars("你好世界")
        self.assertEqual(non_ws, 4)
        self.assertEqual(cjk, 4)

    def test_mixed_with_ascii_and_whitespace(self):
        """中英混合加空白：只统计汉字为 cjk，非空白含标点与字母。"""
        non_ws, cjk = count_chars("Hello 世界 123。")
        # 非空白：H e l l o 世 界 1 2 3 。 = 11
        self.assertEqual(non_ws, 11)
        self.assertEqual(cjk, 2)

    def test_whitespace_only(self):
        """纯空白：两者均为 0。"""
        non_ws, cjk = count_chars("   \n\t  ")
        self.assertEqual(non_ws, 0)
        self.assertEqual(cjk, 0)

    def test_empty_string(self):
        """空串：两者均为 0。"""
        non_ws, cjk = count_chars("")
        self.assertEqual(non_ws, 0)
        self.assertEqual(cjk, 0)

    def test_realistic_novel_sample(self):
        """真实小说样本：cjk > 0 且 cjk <= non_ws。"""
        non_ws, cjk = count_chars(SAMPLE_NOVEL)
        self.assertGreater(cjk, 200)
        self.assertLessEqual(cjk, non_ws)


# ---------------------------------------------------------------------------
# compute_six_dimensions
# ---------------------------------------------------------------------------
class TestComputeSixDimensions(unittest.TestCase):
    """compute_six_dimensions 返回七键字典。"""

    def test_returns_all_keys(self):
        """返回字典应包含全部七个键。"""
        m = compute_six_dimensions(SAMPLE_NOVEL)
        expected = {
            "avg_sent_len", "dialogue_ratio", "median_para_len",
            "punct_rhythm", "top_words", "sentence_pattern", "non_ws",
        }
        self.assertEqual(set(m.keys()), expected)

    def test_value_types(self):
        """各字段类型正确。"""
        m = compute_six_dimensions(SAMPLE_NOVEL)
        self.assertIsInstance(m["avg_sent_len"], float)
        self.assertIsInstance(m["dialogue_ratio"], float)
        self.assertIsInstance(m["median_para_len"], float)
        self.assertIsInstance(m["punct_rhythm"], dict)
        self.assertIsInstance(m["top_words"], list)
        self.assertIsInstance(m["sentence_pattern"], dict)
        self.assertIsInstance(m["non_ws"], int)

    def test_punct_rhythm_keys(self):
        """punct_rhythm 含 q / e / ellipsis 三个键。"""
        pr = compute_six_dimensions(SAMPLE_NOVEL)["punct_rhythm"]
        self.assertEqual(set(pr.keys()), {"q", "e", "ellipsis"})
        for v in pr.values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)

    def test_sentence_pattern_keys(self):
        """sentence_pattern 含 alternation_ratio / short_count / long_count。"""
        sp = compute_six_dimensions(SAMPLE_NOVEL)["sentence_pattern"]
        self.assertEqual(set(sp.keys()),
                         {"alternation_ratio", "short_count", "long_count"})
        self.assertIsInstance(sp["short_count"], int)
        self.assertIsInstance(sp["long_count"], int)

    def test_dialogue_ratio_in_percent_range(self):
        """对话占比应在 0~100 之间。"""
        ratio = compute_six_dimensions(SAMPLE_NOVEL)["dialogue_ratio"]
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 100.0)

    def test_dialogue_detected_in_sample(self):
        """含「」对话的样本，对话占比应大于 0。"""
        ratio = compute_six_dimensions(SAMPLE_NOVEL)["dialogue_ratio"]
        self.assertGreater(ratio, 0.0)

    def test_top_words_is_list_of_tuples(self):
        """top_words 是 (词, 次数) 列表。"""
        tw = compute_six_dimensions(SAMPLE_NOVEL)["top_words"]
        self.assertIsInstance(tw, list)
        if tw:
            word, count = tw[0]
            self.assertIsInstance(word, str)
            self.assertIsInstance(count, int)

    def test_empty_text(self):
        """空文本不报错，返回零值指标。"""
        m = compute_six_dimensions("")
        self.assertEqual(m["avg_sent_len"], 0.0)
        self.assertEqual(m["dialogue_ratio"], 0.0)
        self.assertEqual(m["median_para_len"], 0.0)
        self.assertEqual(m["non_ws"], 0)
        self.assertEqual(m["top_words"], [])

    def test_question_mark_counted_in_rhythm(self):
        """问号计入标点节奏的 q 维度。"""
        text = "他来了。他走了？去哪里？"
        pr = compute_six_dimensions(text)["punct_rhythm"]
        self.assertGreater(pr["q"], 0.0)


# ---------------------------------------------------------------------------
# parse_tolerance
# ---------------------------------------------------------------------------
class TestParseTolerance(unittest.TestCase):
    """parse_tolerance 解析容差字符串。"""

    def test_full_string(self):
        """完整五项字符串解析正确。"""
        tol = parse_tolerance("3,5,10,2,0.2")
        self.assertEqual(tol["sent"], 3.0)
        self.assertEqual(tol["dial"], 5.0)
        self.assertEqual(tol["para"], 10.0)
        self.assertEqual(tol["punct"], 2.0)
        self.assertAlmostEqual(tol["pat"], 0.2)

    def test_empty_string_returns_defaults(self):
        """空字符串返回默认容差。"""
        tol = parse_tolerance("")
        self.assertEqual(tol, DEFAULT_TOLERANCE)

    def test_none_returns_defaults(self):
        """None 返回默认容差。"""
        tol = parse_tolerance(None)
        self.assertEqual(tol, DEFAULT_TOLERANCE)

    def test_partial_string_keeps_defaults(self):
        """缺项用默认值补齐。"""
        tol = parse_tolerance("5,8")
        self.assertEqual(tol["sent"], 5.0)
        self.assertEqual(tol["dial"], 8.0)
        self.assertEqual(tol["para"], 10.0)   # 默认
        self.assertEqual(tol["punct"], 2.0)  # 默认
        self.assertAlmostEqual(tol["pat"], 0.2)  # 默认

    def test_extra_fields_ignored(self):
        """多余项被忽略。"""
        tol = parse_tolerance("1,2,3,4,0.5,6,7,8")
        self.assertEqual(tol["pat"], 0.5)

    def test_whitespace_tolerant(self):
        """含空格的字符串可正确解析。"""
        tol = parse_tolerance(" 3 , 5 , 10 , 2 , 0.2 ")
        self.assertEqual(tol["sent"], 3.0)
        self.assertAlmostEqual(tol["pat"], 0.2)

    def test_invalid_value_raises(self):
        """非数字项应抛出 ValueError。"""
        with self.assertRaises(ValueError):
            parse_tolerance("3,abc,10")

    def test_default_tolerance_values(self):
        """默认容差与文档一致。"""
        self.assertEqual(DEFAULT_TOLERANCE["sent"], 3.0)
        self.assertEqual(DEFAULT_TOLERANCE["dial"], 5.0)
        self.assertEqual(DEFAULT_TOLERANCE["para"], 10.0)
        self.assertEqual(DEFAULT_TOLERANCE["punct"], 2.0)
        self.assertAlmostEqual(DEFAULT_TOLERANCE["pat"], 0.2)


# ---------------------------------------------------------------------------
# format_anchor_md
# ---------------------------------------------------------------------------
class TestFormatAnchorMd(unittest.TestCase):
    """format_anchor_md 生成 Markdown 文风锚。"""

    def setUp(self):
        """每个测试用一份独立指标，避免互相污染。"""
        self.metrics = _make_metrics()
        self.tolerance = dict(DEFAULT_TOLERANCE)

    def test_contains_title(self):
        """标题应出现在输出首行。"""
        md = format_anchor_md(self.metrics, self.tolerance, title="测试锚点")
        self.assertTrue(md.startswith("# 测试锚点"))

    def test_default_title(self):
        """不传 title 时默认为“文风锚”。"""
        md = format_anchor_md(self.metrics, self.tolerance)
        self.assertTrue(md.startswith("# 文风锚"))

    def test_contains_baseline_section(self):
        """输出包含量化基线段。"""
        md = format_anchor_md(self.metrics, self.tolerance)
        self.assertIn("## 量化基线", md)
        self.assertIn("平均句长", md)
        self.assertIn("对话占比", md)
        self.assertIn("段落中位长度", md)
        self.assertIn("标点节奏", md)
        self.assertIn("句式偏好", md)

    def test_contains_top_words_section(self):
        """输出包含高频词段。"""
        md = format_anchor_md(self.metrics, self.tolerance)
        self.assertIn("## 高频词 Top20", md)
        self.assertIn("林晚舟", md)

    def test_sources_rendered(self):
        """样本来源应被渲染进 Markdown。"""
        md = format_anchor_md(self.metrics, self.tolerance,
                              sources=["第001章.md", "第002章.md"])
        self.assertIn("## 样本来源", md)
        self.assertIn("第001章.md", md)
        self.assertIn("第002章.md", md)

    def test_no_sources_omits_section(self):
        """不传 sources 时不出现样本来源段。"""
        md = format_anchor_md(self.metrics, self.tolerance)
        self.assertNotIn("## 样本来源", md)

    def test_empty_top_words(self):
        """top_words 为空时显示“（无）”。"""
        metrics = _make_metrics(top_words=[])
        md = format_anchor_md(metrics, self.tolerance)
        self.assertIn("（无）", md)

    def test_tolerance_values_in_output(self):
        """自定义容差值应出现在输出中。"""
        tol = {"sent": 4.0, "dial": 6.0, "para": 12.0, "punct": 3.0, "pat": 0.3}
        md = format_anchor_md(self.metrics, tol)
        self.assertIn("±4", md)
        self.assertIn("±6", md)
        self.assertIn("±12", md)


# ---------------------------------------------------------------------------
# parse_anchor_md
# ---------------------------------------------------------------------------
class TestParseAnchorMd(unittest.TestCase):
    """parse_anchor_md 把文风锚 Markdown 解析回指标与容差。"""

    def setUp(self):
        """用临时目录存放生成的锚文件。"""
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)
        self.metrics = _make_metrics()
        self.tolerance = {"sent": 3.0, "dial": 5.0, "para": 10.0,
                          "punct": 2.0, "pat": 0.2}
        self.anchor_path = os.path.join(self.tmpdir, "文风锚.md")

    def _cleanup(self):
        """清理临时目录。"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_anchor(self, **kwargs):
        """生成并写入文风锚，返回路径。"""
        md = format_anchor_md(self.metrics, self.tolerance, **kwargs)
        with open(self.anchor_path, "w", encoding="utf-8") as f:
            f.write(md)
        return self.anchor_path

    def test_round_trip_metrics(self):
        """format -> parse 往返：核心数值应一致。"""
        self._write_anchor(title="往返测试")
        m, _ = parse_anchor_md(self.anchor_path)
        self.assertAlmostEqual(m["avg_sent_len"], self.metrics["avg_sent_len"],
                               places=1)
        self.assertAlmostEqual(m["dialogue_ratio"], self.metrics["dialogue_ratio"],
                               places=1)
        self.assertAlmostEqual(m["median_para_len"], self.metrics["median_para_len"],
                               places=0)

    def test_round_trip_punct_rhythm(self):
        """标点节奏三维往返一致。"""
        self._write_anchor()
        m, _ = parse_anchor_md(self.anchor_path)
        pr = m["punct_rhythm"]
        self.assertAlmostEqual(pr["q"], self.metrics["punct_rhythm"]["q"], places=1)
        self.assertAlmostEqual(pr["e"], self.metrics["punct_rhythm"]["e"], places=1)
        self.assertAlmostEqual(pr["ellipsis"],
                               self.metrics["punct_rhythm"]["ellipsis"], places=1)

    def test_round_trip_sentence_pattern(self):
        """句式偏好交替比往返一致（短/长句数不解析回填）。"""
        self._write_anchor()
        m, _ = parse_anchor_md(self.anchor_path)
        self.assertAlmostEqual(
            m["sentence_pattern"]["alternation_ratio"],
            self.metrics["sentence_pattern"]["alternation_ratio"],
            places=2)

    def test_round_trip_tolerance(self):
        """容差往返一致。"""
        self._write_anchor()
        _, tol = parse_anchor_md(self.anchor_path)
        self.assertAlmostEqual(tol["sent"], self.tolerance["sent"])
        self.assertAlmostEqual(tol["dial"], self.tolerance["dial"])
        self.assertAlmostEqual(tol["para"], self.tolerance["para"])
        self.assertAlmostEqual(tol["punct"], self.tolerance["punct"])
        self.assertAlmostEqual(tol["pat"], self.tolerance["pat"])

    def test_custom_tolerance_round_trip(self):
        """自定义容差值往返保持。"""
        self.tolerance = {"sent": 4.0, "dial": 6.0, "para": 12.0,
                          "punct": 3.0, "pat": 0.3}
        self._write_anchor()
        _, tol = parse_anchor_md(self.anchor_path)
        self.assertAlmostEqual(tol["sent"], 4.0)
        self.assertAlmostEqual(tol["dial"], 6.0)
        self.assertAlmostEqual(tol["para"], 12.0)
        self.assertAlmostEqual(tol["punct"], 3.0)
        self.assertAlmostEqual(tol["pat"], 0.3)

    def test_parses_handwritten_markdown(self):
        """能解析手写的文风锚 Markdown。"""
        md = (
            "# 文风锚\n\n"
            "## 量化基线\n"
            "- 平均句长：20.5 字（容差 ±3）\n"
            "- 对话占比：40.0%（容差 ±5%）\n"
            "- 段落中位长度：50 字（容差 ±10）\n"
            "- 标点节奏：？25.0% / ！30.0% / ……5.0%（容差 ±2%）\n"
            "- 句式偏好：长短句交替比 2.00（短句 8 / 长句 4，容差 ±0.2）\n"
        )
        path = os.path.join(self.tmpdir, "手写锚.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        m, tol = parse_anchor_md(path)
        self.assertAlmostEqual(m["avg_sent_len"], 20.5)
        self.assertAlmostEqual(m["dialogue_ratio"], 40.0)
        self.assertAlmostEqual(m["median_para_len"], 50.0)
        self.assertAlmostEqual(m["punct_rhythm"]["q"], 25.0)
        self.assertAlmostEqual(m["punct_rhythm"]["e"], 30.0)
        self.assertAlmostEqual(m["punct_rhythm"]["ellipsis"], 5.0)
        self.assertAlmostEqual(m["sentence_pattern"]["alternation_ratio"], 2.0)
        self.assertAlmostEqual(tol["sent"], 3.0)
        self.assertAlmostEqual(tol["pat"], 0.2)

    def test_handles_bom(self):
        """utf-8-sig 编码（含 BOM）的文件可正常解析。"""
        self._write_anchor()
        # 覆写为带 BOM 的版本
        md = format_anchor_md(self.metrics, self.tolerance)
        with open(self.anchor_path, "w", encoding="utf-8-sig") as f:
            f.write(md)
        m, _ = parse_anchor_md(self.anchor_path)
        self.assertAlmostEqual(m["avg_sent_len"], self.metrics["avg_sent_len"],
                               places=1)


# ---------------------------------------------------------------------------
# compare_metrics
# ---------------------------------------------------------------------------
class TestCompareMetrics(unittest.TestCase):
    """compare_metrics 对比当前与锚指标，返回偏离描述列表。"""

    def setUp(self):
        """锚指标与默认容差。"""
        self.anchor = _make_metrics()
        self.tolerance = dict(DEFAULT_TOLERANCE)

    def test_no_deviation_when_identical(self):
        """完全相同的指标返回空列表。"""
        devs = compare_metrics(self.anchor, self.anchor, self.tolerance)
        self.assertEqual(devs, [])

    def test_sentence_length_deviation(self):
        """句长偏离超容差被检出。"""
        current = _make_metrics(avg_sent_len=35.0)  # 锚 18.5，差 16.5 > 3
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("节奏漂移" in d for d in devs))

    def test_sentence_length_within_tolerance(self):
        """句长偏离在容差内不被检出。"""
        current = _make_metrics(avg_sent_len=20.0)  # 差 1.5 < 3
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertFalse(any("节奏漂移" in d for d in devs))

    def test_dialogue_ratio_increase(self):
        """对话占比上升超容差标记“对话过多”。"""
        current = _make_metrics(dialogue_ratio=50.0)  # 锚 32.0，差 18 > 5
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("对话过多" in d for d in devs))

    def test_dialogue_ratio_decrease(self):
        """对话占比下降超容差标记“对话过少”。"""
        current = _make_metrics(dialogue_ratio=10.0)  # 差 -22 > 5
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("对话过少" in d for d in devs))

    def test_paragraph_length_deviation(self):
        """段落中位长度偏离超容差被检出。"""
        current = _make_metrics(median_para_len=80.0)  # 锚 45，差 35 > 10
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("段落习惯" in d for d in devs))

    def test_punct_rhythm_deviation(self):
        """标点节奏某维偏离超容差被检出。"""
        current = _make_metrics(q=60.0)  # 锚 30，差 30 > 2
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("情绪强度" in d for d in devs))

    def test_punct_rhythm_all_three_keys(self):
        """q / e / ellipsis 三维各自可被检出。"""
        for key, label in (("q", "？"), ("e", "！"), ("ellipsis", "……")):
            current = _make_metrics(**{key: 70.0})
            devs = compare_metrics(current, self.anchor, self.tolerance)
            self.assertTrue(any(label in d and "情绪强度" in d for d in devs),
                            f"应检出标点 {label} 偏离")

    def test_sentence_pattern_deviation(self):
        """句式偏好交替比偏离超容差被检出。"""
        current = _make_metrics(ratio=5.0)  # 锚 1.5，差 3.5 > 0.2
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("句式偏好" in d for d in devs))

    def test_multiple_deviations_count(self):
        """多维度同时偏离，返回多条描述。"""
        current = _make_metrics(avg_sent_len=40.0, dialogue_ratio=60.0,
                                median_para_len=90.0, q=70.0, ratio=6.0)
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertGreaterEqual(len(devs), 5)

    def test_deviation_messages_include_tolerance(self):
        """偏离描述中应包含容差信息。"""
        current = _make_metrics(avg_sent_len=40.0)
        devs = compare_metrics(current, self.anchor, self.tolerance)
        self.assertTrue(any("±3" in d for d in devs))


# ---------------------------------------------------------------------------
# CLI 子命令（extract / compare）子进程测试
# ---------------------------------------------------------------------------
class TestCLIExtract(unittest.TestCase):
    """extract 子命令的端到端子进程测试。"""

    def setUp(self):
        """准备临时目录与样章文件。"""
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)
        self.chapter = os.path.join(self.tmpdir, "第001章.md")
        with open(self.chapter, "w", encoding="utf-8") as f:
            f.write(SAMPLE_NOVEL)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, args):
        """运行 CLI 子进程，返回 CompletedProcess。"""
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH)] + args,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_extract_to_stdout(self):
        """不指定 --output 时打印 Markdown 到 stdout，退出码 0。"""
        r = self._run(["extract", self.chapter])
        self.assertEqual(r.returncode, 0,
                         f"extract 应成功，stderr: {r.stderr}")
        self.assertIn("# 文风锚", r.stdout)
        self.assertIn("## 量化基线", r.stdout)

    def test_extract_to_file(self):
        """--output 指定路径时生成文件，退出码 0。"""
        out = os.path.join(self.tmpdir, "设定", "文风锚.md")
        r = self._run(["extract", self.chapter, "--output", out])
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertTrue(os.path.exists(out))
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# 文风锚", content)
        self.assertIn("## 量化基线", content)

    def test_extract_custom_title(self):
        """--title 自定义标题出现在输出中。"""
        out = os.path.join(self.tmpdir, "锚.md")
        r = self._run(["extract", self.chapter, "--output", out,
                       "--title", "我的文风基线"])
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# 我的文风基线", content)

    def test_extract_with_custom_tolerance(self):
        """--tolerance 自定义容差写入文风锚。"""
        out = os.path.join(self.tmpdir, "锚.md")
        r = self._run(["extract", self.chapter, "--output", out,
                       "--tolerance", "4,6,12,3,0.3"])
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("±4", content)
        self.assertIn("±6", content)

    def test_extract_multiple_files(self):
        """多文件合并统计，样本来源全部出现。"""
        ch2 = os.path.join(self.tmpdir, "第002章.md")
        with open(ch2, "w", encoding="utf-8") as f:
            f.write(SAMPLE_NOVEL)
        r = self._run(["extract", self.chapter, ch2])
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("第001章.md", r.stdout)
        self.assertIn("第002章.md", r.stdout)

    def test_extract_invalid_tolerance_exits_2(self):
        """非法容差字符串返回退出码 2。"""
        out = os.path.join(self.tmpdir, "锚.md")
        r = self._run(["extract", self.chapter, "--output", out,
                       "--tolerance", "3,abc,10"])
        self.assertEqual(r.returncode, 2)

    def test_extract_missing_file_exits_2(self):
        """不存在的输入文件返回退出码 2。"""
        r = self._run(["extract", os.path.join(self.tmpdir, "不存在.md")])
        self.assertEqual(r.returncode, 2)


class TestCLICompare(unittest.TestCase):
    """compare 子命令的端到端子进程测试。"""

    def setUp(self):
        """准备锚文件与章节文件。"""
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)
        # 锚样本（叙述向）与对比样本（对话向）
        self.anchor_sample = os.path.join(self.tmpdir, "锚样本.md")
        self.current_sample = os.path.join(self.tmpdir, "当前章.md")
        self.dialogue_sample = os.path.join(self.tmpdir, "对话章.md")
        with open(self.anchor_sample, "w", encoding="utf-8") as f:
            f.write(SAMPLE_NOVEL)
        with open(self.current_sample, "w", encoding="utf-8") as f:
            f.write(SAMPLE_NOVEL)
        with open(self.dialogue_sample, "w", encoding="utf-8") as f:
            f.write(SAMPLE_DIALOGUE)
        # 用 extract 生成文风锚
        self.anchor_md = os.path.join(self.tmpdir, "设定", "文风锚.md")
        r = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "extract",
             self.anchor_sample, "--output", self.anchor_md],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(r.returncode, 0, f"生成锚失败: {r.stderr}")

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, args):
        """运行 compare CLI 子进程。"""
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH)] + args,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_compare_within_tolerance_exits_0(self):
        """相同文风的章节对比，六维在容差内，退出码 0。"""
        r = self._run(["compare", self.current_sample, self.anchor_md])
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("全部在容差内", r.stdout)

    def test_compare_with_deviation_exits_1(self):
        """文风明显偏离的章节对比，退出码 1，输出包含偏离描述。"""
        r = self._run(["compare", self.dialogue_sample, self.anchor_md])
        self.assertEqual(r.returncode, 1, f"stderr: {r.stderr}")
        self.assertIn("偏离", r.stdout)
        self.assertIn("[偏离]", r.stdout)

    def test_compare_prints_current_metrics(self):
        """compare 输出当前章节的六维指标。"""
        r = self._run(["compare", self.current_sample, self.anchor_md])
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("当前指标", r.stdout)
        self.assertIn("平均句长", r.stdout)
        self.assertIn("对话占比", r.stdout)

    def test_compare_override_tolerance(self):
        """--tolerance 覆盖锚中容差；放宽后原本的偏离可变为容差内。"""
        # 用对话章对比，默认容差下应有偏离（退出码 1）
        r_default = self._run(["compare", self.dialogue_sample, self.anchor_md])
        self.assertEqual(r_default.returncode, 1)
        # 放宽容差到极大值，应全部在容差内（退出码 0）
        r_loose = self._run(["compare", self.dialogue_sample, self.anchor_md,
                             "--tolerance", "999,999,999,999,999"])
        self.assertEqual(r_loose.returncode, 0, f"stderr: {r_loose.stderr}")
        self.assertIn("全部在容差内", r_loose.stdout)

    def test_compare_missing_current_exits_2(self):
        """当前章节文件不存在，退出码 2。"""
        r = self._run(["compare", os.path.join(self.tmpdir, "不存在.md"),
                       self.anchor_md])
        self.assertEqual(r.returncode, 2)

    def test_compare_missing_anchor_exits_2(self):
        """文风锚文件不存在，退出码 2。"""
        r = self._run(["compare", self.current_sample,
                       os.path.join(self.tmpdir, "无锚.md")])
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
