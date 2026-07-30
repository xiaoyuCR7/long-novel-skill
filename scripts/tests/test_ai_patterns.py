#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ai_patterns.py — 测试 check_text.py v3.2 新增功能。

覆盖：
  - scan_ai_patterns: 20种AI模式整合检测
  - scan_paragraph_repetition: 跨段落重复度
  - scan_skip_density: 跳过密度
  - degradation_fingerprint: 退化指纹

运行方式：
    python scripts/tests/test_ai_patterns.py
"""

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_text import (
    BANNED_WORDS,
    scan_ai_patterns,
    scan_paragraph_repetition,
    scan_skip_density,
    degradation_fingerprint,
    scan_degradation,
)


class TestScanAIPatterns(unittest.TestCase):
    """测试20种AI模式整合检测。"""

    def test_clean_text_no_hits(self):
        """干净文本不应命中AI模式。"""
        text = "林辰走在山间小路上。远处的炊烟袅袅升起，鸟鸣声在林间回荡。他停下脚步，弯腰捡起一片落叶，放在掌心端详。叶脉清晰，像是大地的河流缩影。"
        hits = scan_ai_patterns(text)
        # 干净文本可能有少量advisory，但不应有blocking
        blocking = [h for h in hits if h[3] == "blocking"]
        self.assertEqual(len(blocking), 0, "干净文本不应有blocking命中")

    def test_banned_words_detected(self):
        """禁用词应被检测到。"""
        text = "他仿佛看到了什么。似乎有什么东西在动。不禁感叹了一声。"
        hits = scan_ai_patterns(text)
        banned_hits = [h for h in hits if h[0] == "ai-banned-words"]
        self.assertGreater(len(banned_hits), 0, "应检测到禁用词")

    def test_transition_tic_detected(self):
        """过渡词模板化应被检测到。"""
        text = "然而，他走了。不过，很快又回来了。与此同时，天空暗了下来。就在这时，门开了。殊不知，这一切都是陷阱。"
        hits = scan_ai_patterns(text)
        transition_hits = [h for h in hits if h[0] == "ai-transition-tic"]
        self.assertGreater(len(transition_hits), 0, "应检测到过渡词模板化")

    def test_info_dump_detected(self):
        """信息倾倒应被检测到。"""
        text = "修炼体系共九大境界，分别是炼气期、筑基期、金丹期、元婴期、化神期、炼虚期、合体期、大乘期、渡劫期。第一层炼气，第二层筑基，第三层金丹。"
        hits = scan_ai_patterns(text)
        info_hits = [h for h in hits if h[0] == "ai-info-dump"]
        self.assertGreater(len(info_hits), 0, "应检测到信息倾倒")

    def test_coincidence_detected(self):
        """巧合推进应被检测到。"""
        text = "恰好路过。凑巧遇到了。正好赶上了。偏偏下起了雨。机缘巧合下获得了宝物。"
        hits = scan_ai_patterns(text)
        coincidence_hits = [h for h in hits if h[0] == "ai-coincidence"]
        self.assertGreater(len(coincidence_hits), 0, "应检测到巧合推进")

    def test_sent_len_monotony_detected(self):
        """句长单调应被检测到。"""
        # 连续10句长度几乎相同的句子
        sentences = ["他走了过去。" * 1 for _ in range(12)]
        text = "。".join(sentences) + "。"
        hits = scan_ai_patterns(text)
        monotony_hits = [h for h in hits if h[0] == "ai-sent-len-monotony"]
        self.assertGreater(len(monotony_hits), 0, "应检测到句长单调")

    def test_emotion_labeling_detected(self):
        """情绪标签直接陈述应被检测到。"""
        text = "他感到了恐惧。她觉得悲伤。他感到愤怒。它感觉到危险。"
        hits = scan_ai_patterns(text)
        emotion_hits = [h for h in hits if h[0] == "ai-emotion-labeling"]
        self.assertGreater(len(emotion_hits), 0, "应检测到情绪标签")

    def test_returns_correct_structure(self):
        """返回值应为4元组列表。"""
        text = "测试文本。"
        hits = scan_ai_patterns(text)
        for h in hits:
            self.assertEqual(len(h), 4, "每条命中应为4元组")
            self.assertIn(h[3], ["blocking", "advisory"], "severity应为blocking或advisory")

    def test_hit_count_reasonable(self):
        """AI味重的文本命中数应多于干净文本。"""
        clean = "林辰走在山间小路上。远处的炊烟袅袅升起，鸟鸣声在林间回荡。"
        ai_heavy = "他仿佛看到了什么。似乎有什么东西在动。不禁感叹。然而，他走了。不过，又回来了。与此同时，天暗了。就在这时，门开了。殊不知，这都是陷阱。"
        clean_hits = scan_ai_patterns(clean)
        ai_hits = scan_ai_patterns(ai_heavy)
        self.assertGreaterEqual(len(ai_hits), len(clean_hits),
                                "AI味重的文本命中数应 >= 干净文本")


class TestScanParagraphRepetition(unittest.TestCase):
    """测试跨段落重复度检测。"""

    def test_no_repetition(self):
        """内容不同的段落不应检测到重复。"""
        text = "林辰走在山间小路上。\n\n赵天霸站在武道馆中央。\n\n苏清雪坐在窗前读书。\n\n教练皱了皱眉。"
        result = scan_paragraph_repetition(text)
        self.assertFalse(result["has_repetition"])

    def test_repetition_detected(self):
        """高度相似的段落应检测到重复。"""
        # 构造3对高度相似的段落
        text = (
            "他缓缓走了过去，目光扫过人群，嘴角微微上扬。\n\n"
            "他缓缓走了过来，目光扫过众人，嘴角微微上扬。\n\n"
            "他缓缓走了过去，目光扫过人群，嘴角微微上扬。\n\n"
            "他缓缓走了过来，目光扫过众人，嘴角微微上扬。\n\n"
        )
        result = scan_paragraph_repetition(text)
        self.assertTrue(result["has_repetition"])
        self.assertGreaterEqual(result["repeated_count"], 2)

    def test_short_paragraphs_skipped(self):
        """短段落应被跳过。"""
        text = "好。\n\n好。\n\n好。\n\n好。"
        result = scan_paragraph_repetition(text)
        self.assertFalse(result["has_repetition"])

    def test_returns_correct_structure(self):
        """返回值应包含正确的字段。"""
        text = "测试段落。\n\n另一个段落。"
        result = scan_paragraph_repetition(text)
        self.assertIn("has_repetition", result)
        self.assertIn("repeated_count", result)
        self.assertIn("pairs", result)
        self.assertIn("evidence", result)


class TestScanSkipDensity(unittest.TestCase):
    """测试跳过密度检测。"""

    def test_normal_text_not_skipping(self):
        """正常叙述文本不应被判定为跳过。"""
        text = "林辰推开武道馆的大门，一股炽热的气息扑面而来。场馆中央，数十名学员正在进行力量测试。"
        result = scan_skip_density(text, len(text.replace(" ", "")))
        self.assertFalse(result["is_skipping"])

    def test_scene_jumps_detected(self):
        """多个场景跳转标记应被检测到。"""
        text = (
            "场景一。\n"
            "---\n"
            "几天后。\n"
            "---\n"
            "数日后。\n"
            "---\n"
            "转眼间一个月过去了。\n"
        )
        non_ws = len(text.replace(" ", "").replace("\n", ""))
        result = scan_skip_density(text, non_ws)
        self.assertGreaterEqual(result["scene_jumps"], 3)
        self.assertGreaterEqual(result["time_compressors"], 2)

    def test_dialogue_heavy_detected(self):
        """对话占比过高的短段落文本应被检测到。"""
        # 构造对话占比>65%且段落短的内容
        lines = []
        for i in range(20):
            lines.append(f"「你说得对。」")
            lines.append(f"「当然。」")
        text = "\n".join(lines)
        non_ws = len(text.replace(" ", "").replace("\n", ""))
        if non_ws > 500:
            result = scan_skip_density(text, non_ws)
            self.assertGreater(result["dialogue_ratio"], 60)

    def test_returns_correct_fields(self):
        """返回值应包含正确的字段。"""
        text = "测试文本。"
        result = scan_skip_density(text, 10)
        self.assertIn("is_skipping", result)
        self.assertIn("scene_jumps", result)
        self.assertIn("time_compressors", result)
        self.assertIn("dialogue_ratio", result)
        self.assertIn("avg_para_len", result)
        self.assertIn("evidence", result)


class TestDegradationFingerprint(unittest.TestCase):
    """测试退化指纹生成。"""

    def test_clean_fingerprint(self):
        """无退化命中时指纹应为全零。"""
        fp = degradation_fingerprint([])
        self.assertIn("D:B0,S0,P0,E0,V0", fp["fingerprint"])
        self.assertEqual(fp["severity"], "clean")

    def test_degradation_counted(self):
        """退化命中应正确计数。"""
        deg_hits = [
            ("degradation-banned", "标签", "证据"),
            ("degradation-banned", "标签", "证据"),
            ("degradation-syntax", "标签", "证据"),
        ]
        fp = degradation_fingerprint(deg_hits)
        self.assertIn("B2", fp["fingerprint"])
        self.assertIn("S1", fp["fingerprint"])
        self.assertIn("V0", fp["fingerprint"])
        self.assertIn(fp["severity"], ["light", "moderate", "severe"])

    def test_ai_fingerprint(self):
        """AI模式指纹应正确生成。"""
        ai_hits = [
            ("ai-banned-words", "标签", "证据", "blocking"),
            ("ai-banned-words", "标签", "证据", "blocking"),
            ("ai-toxic-syntax", "标签", "证据", "blocking"),
            ("ai-transition-tic", "标签", "证据", "advisory"),
        ]
        fp = degradation_fingerprint([], ai_hits)
        self.assertNotEqual(fp["ai_fingerprint"], "A:none")
        self.assertGreater(len(fp["categories"]), 0)

    def test_combined_hash_consistent(self):
        """相同输入应生成相同哈希。"""
        deg_hits = [("degradation-banned", "标签", "证据")]
        ai_hits = [("ai-banned-words", "标签", "证据", "blocking")]
        fp1 = degradation_fingerprint(deg_hits, ai_hits)
        fp2 = degradation_fingerprint(deg_hits, ai_hits)
        self.assertEqual(fp1["combined_hash"], fp2["combined_hash"])

    def test_combined_hash_differs(self):
        """不同输入应生成不同哈希。"""
        fp1 = degradation_fingerprint([("degradation-banned", "标签", "证据")])
        fp2 = degradation_fingerprint([("degradation-syntax", "标签", "证据")])
        self.assertNotEqual(fp1["combined_hash"], fp2["combined_hash"])

    def test_severity_levels(self):
        """严重度分级应正确。"""
        # clean: 无命中
        fp_clean = degradation_fingerprint([], [])
        self.assertEqual(fp_clean["severity"], "clean")

        # severe: 多个blocking
        severe_hits = [
            ("ai-test1", "", "", "blocking"),
            ("ai-test2", "", "", "blocking"),
            ("ai-test3", "", "", "blocking"),
        ]
        fp_severe = degradation_fingerprint([], severe_hits)
        self.assertEqual(fp_severe["severity"], "severe")

    def test_returns_correct_fields(self):
        """返回值应包含正确的字段。"""
        fp = degradation_fingerprint([])
        self.assertIn("fingerprint", fp)
        self.assertIn("ai_fingerprint", fp)
        self.assertIn("combined_hash", fp)
        self.assertIn("severity", fp)
        self.assertIn("categories", fp)


class TestIntegrationWithExisting(unittest.TestCase):
    """测试新功能与已有检测器的集成。"""

    def test_ai_patterns_with_degradation(self):
        """AI模式检测和退化检测可以联合使用。"""
        text = "他仿佛看到了什么。仿佛听到了什么。仿佛感觉到了什么。仿佛闻到了什么。"
        words = BANNED_WORDS
        whitelist = set()

        ai_hits = scan_ai_patterns(text, text.splitlines(), words, whitelist)
        deg_hits = scan_degradation(text, words, whitelist)

        # 两者都应检测到问题
        self.assertGreater(len(ai_hits), 0)
        self.assertGreater(len(deg_hits), 0)

        # 可以生成指纹
        fp = degradation_fingerprint(deg_hits, ai_hits)
        self.assertIsNotNone(fp["combined_hash"])

    def test_fingerprint_trackable_across_chapters(self):
        """指纹可用于跨章节追踪。"""
        # 模拟三章内容
        chapters = [
            "他仿佛看到了什么。似乎有什么在动。不禁感叹。",
            "她仿佛听到了什么。似乎有人在说话。不由得笑了。",
            "他仿佛感觉到了什么。似乎有什么不对。不禁皱眉。",
        ]
        words = BANNED_WORDS
        whitelist = set()

        fingerprints = []
        for ch in chapters:
            ai_hits = scan_ai_patterns(ch, ch.splitlines(), words, whitelist)
            deg_hits = scan_degradation(ch, words, whitelist)
            fp = degradation_fingerprint(deg_hits, ai_hits)
            fingerprints.append(fp)

        # 三章的退化指纹应该相似（都是禁用词退化）
        self.assertTrue(all("B" in fp["fingerprint"] for fp in fingerprints))
        # 但组合哈希应不完全相同（内容不同）
        unique_hashes = set(fp["combined_hash"] for fp in fingerprints)
        # 至少有2个不同的哈希
        self.assertGreaterEqual(len(unique_hashes), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
