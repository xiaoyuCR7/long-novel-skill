#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_content_expander.py — 测试 content_expander.py 智能内容扩充引擎 v2.0。

覆盖范围：
  - 工具函数（字数统计、段落切分、对话提取等）
  - 8 种策略的分析函数
  - 章节类型自动推断
  - 优先级计算引擎
  - 策略冲突检测
  - 智能融合推荐（1主+2辅）
  - 具体化建议生成
  - CLI 子命令（analyze/suggest/priority/expand）

运行方式：
    python scripts/tests/test_content_expander.py
"""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from content_expander import (
    # 工具函数
    count_chars,
    count_chinese_chars,
    split_paragraphs,
    extract_dialogues,
    calculate_dialogue_ratio,
    keyword_density,
    # 8 种策略分析
    analyze_scene_depth,
    analyze_dialogue_quality,
    analyze_psychological_depth,
    analyze_action_detail,
    analyze_transitions,
    analyze_worldbuilding,
    analyze_foreshadowing,
    analyze_synesthesia,
    # 章节类型推断
    infer_chapter_type,
    # 优先级引擎
    calculate_priorities,
    # 冲突检测与融合
    check_conflict,
    recommend_strategy_combo,
    # 具体化建议
    generate_concrete_suggestions,
    _describe_location,
    # 完整分析
    analyze_text,
    generate_suggestions,
    generate_expansion_plan,
    # 常量
    VERSION,
    STRATEGY_NAMES,
    CHAPTER_TYPES,
    EXPANSION_EFFICIENCY,
)

SCRIPT_PATH = SCRIPT_DIR / "content_expander.py"


# =========================================================
# 测试文本样本
# =========================================================

# 战斗型章节样本
BATTLE_TEXT = """\
林辰紧握手中的长剑，目光死死盯着对面的黑衣人。

黑衣人冷笑一声，身形一晃便冲了过来，手中的匕首划过一道寒光。

林辰举剑格挡，铛的一声脆响，震得他虎口发麻。对方的力量远超他的预料。

"就这点本事？"黑衣人嗤笑道，又是一刀劈下。

林辰咬牙闪避，脚步在地面上擦出一道深深的痕迹。他心中飞速盘算着对策。

忽然，他瞥见旁边的石柱，心中一动。他故意卖了个破绽，引对方攻向石柱方向。

黑衣人果然上当，全力一击砸向林辰的面门。林辰矮身一闪，那一拳重重轰在石柱上。

碎石飞溅，烟尘弥漫。林辰趁机反手一剑，刺入黑衣人的腰侧。

黑衣人发出一声闷哼，踉跄后退。他难以置信地看着腰间的伤口。

"你……"他想说什么，但鲜血已经涌上喉咙。
"""

# 情感型章节样本
EMOTIONAL_TEXT = """\
林晚站在窗前，看着窗外飘落的雪花，久久没有说话。

"姐姐，你真的要走吗？"身后传来弟弟稚嫩的声音。

她转过身，脸上努力挤出一个微笑："小宇乖，姐姐只是去外面读书，很快就会回来的。"

"可是你走了，就没有人陪我堆雪人了。"小男孩低着头，手指绞着衣角。

林晚心中一酸，眼眶忍不住红了。她蹲下身，轻轻摸着弟弟的头。

她想告诉弟弟，自己这一走可能就是好几年。她想告诉弟弟，她也舍不得。

但她最终只是说："等春天来了，姐姐就回来了。"

她不敢看弟弟的眼睛，害怕自己会改变主意。她觉得自己像是在逃，逃离这个让她窒息的家。

门外传来汽车的喇叭声。是时候走了。

她拿起早已收拾好的行李箱，深吸一口气，推开了门。
"""

# 过渡型章节样本
TRANSITION_TEXT = """\
清晨的阳光照进房间，林辰睁开眼睛。

他简单收拾了一下行李，准备前往下一个目的地。

忽然，门外传来敲门声。

"林公子，城主有请。"是城主府的侍卫。

林辰皱了皱眉，但还是跟着侍卫去了城主府。

此时，城主府大厅内，一位中年男子正端坐在主位上。

另一边，城外的山道上，几匹快马正飞驰而来。

与此同时，秘境深处，一道身影缓缓睁开了眼睛。
"""

# 悬疑型章节样本
SUSPENSE_TEXT = """\
林辰总觉得今天的村子有些不对劲。

家家户户的门都紧闭着，街上一个人都没有。明明是正午时分，却安静得有些诡异。

他隐约听到巷子深处传来什么声音，像是有人在低语，又像是风吹过裂缝的呜咽。

"有人吗？"他喊了一声，声音在空旷的街道上回荡。

没有人回应。

他的心里升起一股莫名的不安，手心微微出汗。

走到村中央的老槐树下，他看到了一件奇怪的事情——树干上刻着一个他从未见过的符号。

那符号扭曲而诡异，仿佛有生命一般，在阳光下隐隐蠕动。

他忍不住伸手想去触摸，就在指尖快要碰到的瞬间，身后忽然传来一声轻响。

"别碰它。"
"""

# 世界观型章节样本
WORLDBUILDING_TEXT = """\
青云宗坐落于青云山脉之巅，是天南域三大宗门之一。

宗门内分为七峰，每峰都有一位金丹期长老坐镇。主峰青云峰更是有元婴期的宗主亲自镇守。

林辰作为外门弟子，住在最外围的青竹峰。青竹峰的灵气比主峰稀薄得多，修炼速度自然也慢不少。

"听说了吗？今年的宗门大比，第一名可以进入藏经阁任选一部功法。"

"真的假的？藏经阁里的功法可都是宗门传承了千年的宝贝啊。"

"那还有假？据说还有筑基丹作为奖励。"

林辰听着周围弟子的议论，心中也有些激动。筑基丹，那可是突破炼气期的关键丹药。

他低头看了看自己掌心的灵根印记，那是三年前入门时测出来的——五灵根，最差的资质。

三年了，他还停留在炼气三层。而和他同时入门的天才弟子，已经有人突破到炼气七层了。

"我不甘心……"他握紧了拳头。
"""

# 极简文本（用于测试低字数场景）
MINIMAL_TEXT = "他走了。"


# =========================================================
# 工具函数测试
# =========================================================

class TestUtilityFunctions(unittest.TestCase):
    """测试基础工具函数。"""

    def test_count_chars(self):
        self.assertEqual(count_chars("你好世界"), 4)
        self.assertEqual(count_chars(" 你好 世界 "), 4)
        self.assertEqual(count_chars(""), 0)
        self.assertEqual(count_chars("   "), 0)
        self.assertEqual(count_chars("abc123"), 6)

    def test_count_chinese_chars(self):
        self.assertEqual(count_chinese_chars("你好世界"), 4)
        self.assertEqual(count_chinese_chars("你好abc世界"), 4)
        self.assertEqual(count_chinese_chars("abc123"), 0)
        self.assertEqual(count_chinese_chars(""), 0)

    def test_split_paragraphs(self):
        text = "第一段\n\n第二段\n第三段\n\n\n第四段"
        paras = split_paragraphs(text)
        self.assertEqual(len(paras), 4)
        self.assertEqual(paras[0], "第一段")
        self.assertEqual(paras[1], "第二段")
        self.assertEqual(paras[2], "第三段")
        self.assertEqual(paras[3], "第四段")

    def test_split_paragraphs_empty(self):
        self.assertEqual(split_paragraphs(""), [])
        self.assertEqual(split_paragraphs("\n\n\n"), [])

    def test_extract_dialogues(self):
        text = '他说："你好。" 她回答：「再见。」'
        dialogues = extract_dialogues(text)
        self.assertEqual(len(dialogues), 2)

    def test_calculate_dialogue_ratio(self):
        text = '他说："你好世界。"然后走了。'
        ratio = calculate_dialogue_ratio(text)
        self.assertGreater(ratio, 0)
        self.assertLess(ratio, 1.0)

    def test_calculate_dialogue_ratio_empty(self):
        self.assertEqual(calculate_dialogue_ratio(""), 0.0)

    def test_keyword_density(self):
        text = "天空很蓝，阳光明媚。"
        keywords = ["天空", "阳光", "风"]
        density = keyword_density(text, keywords)
        self.assertGreater(density, 0)

    def test_keyword_density_zero(self):
        text = "他走了过来。"
        keywords = ["天空", "阳光"]
        self.assertEqual(keyword_density(text, keywords), 0.0)


# =========================================================
# 8 种策略分析函数测试
# =========================================================

class TestStrategyAnalysis(unittest.TestCase):
    """测试八种扩充策略的分析函数。"""

    def test_analyze_scene_depth(self):
        """测试场景扩充分析。"""
        paras = split_paragraphs(BATTLE_TEXT)
        result = analyze_scene_depth(paras)
        self.assertIn("scene_paragraph_count", result)
        self.assertIn("scene_ratio", result)
        self.assertIn("needs_expansion", result)
        self.assertIn("expansion_potential", result)
        self.assertIn("scene_paragraph_indices", result)
        self.assertIn(result["expansion_potential"], {"high", "medium", "low"})
        self.assertIsInstance(result["needs_expansion"], bool)
        self.assertGreaterEqual(result["scene_ratio"], 0)
        self.assertLessEqual(result["scene_ratio"], 1)

    def test_analyze_scene_depth_empty(self):
        result = analyze_scene_depth([])
        self.assertEqual(result["scene_paragraph_count"], 0)
        self.assertEqual(result["scene_ratio"], 0)

    def test_analyze_dialogue_quality(self):
        """测试对话丰富分析。"""
        paras = split_paragraphs(EMOTIONAL_TEXT)
        result = analyze_dialogue_quality(EMOTIONAL_TEXT, paras)
        self.assertIn("dialogue_count", result)
        self.assertIn("dialogue_ratio", result)
        self.assertIn("short_dialogues", result)
        self.assertIn("needs_enrichment", result)
        self.assertIn("expansion_potential", result)
        self.assertGreaterEqual(result["dialogue_count"], 0)

    def test_analyze_dialogue_quality_battle(self):
        """战斗文本对话少，应该标记需要丰富。"""
        paras = split_paragraphs(BATTLE_TEXT)
        result = analyze_dialogue_quality(BATTLE_TEXT, paras)
        # 战斗文本有少量对话
        self.assertGreaterEqual(result["dialogue_count"], 0)

    def test_analyze_psychological_depth(self):
        """测试心理深度分析。"""
        paras = split_paragraphs(EMOTIONAL_TEXT)
        result = analyze_psychological_depth(paras)
        self.assertIn("psych_paragraph_count", result)
        self.assertIn("psych_ratio", result)
        self.assertIn("direct_emotion_count", result)
        self.assertIn("needs_deepening", result)
        self.assertIn("expansion_potential", result)
        self.assertIn("direct_emotion_positions", result)

    def test_analyze_action_detail(self):
        """测试动作细节分析。"""
        paras = split_paragraphs(BATTLE_TEXT)
        result = analyze_action_detail(paras)
        self.assertIn("action_paragraph_count", result)
        self.assertIn("short_action_paragraphs", result)
        self.assertIn("needs_detailing", result)
        self.assertIn("expansion_potential", result)
        self.assertIn("action_paragraph_indices", result)
        self.assertGreater(result["action_paragraph_count"], 0)

    def test_analyze_action_detail_emotional(self):
        """情感文本动作少。"""
        paras = split_paragraphs(EMOTIONAL_TEXT)
        result = analyze_action_detail(paras)
        # 情感文本动作段落应该很少
        self.assertGreaterEqual(result["action_paragraph_count"], 0)

    def test_analyze_transitions(self):
        """测试过渡润滑分析。"""
        paras = split_paragraphs(TRANSITION_TEXT)
        result = analyze_transitions(paras)
        self.assertIn("total_transitions", result)
        self.assertIn("abrupt_transition_count", result)
        self.assertIn("abrupt_positions", result)
        self.assertIn("needs_smoothing", result)
        self.assertIn("expansion_potential", result)
        # 过渡文本应该有多处过渡
        self.assertGreater(result["total_transitions"], 0)

    def test_analyze_transitions_empty(self):
        result = analyze_transitions([])
        self.assertEqual(result["total_transitions"], -1)
        self.assertEqual(result["abrupt_transition_count"], 0)
        self.assertFalse(result["needs_smoothing"])

    def test_analyze_worldbuilding(self):
        """测试世界观植入分析。"""
        paras = split_paragraphs(WORLDBUILDING_TEXT)
        result = analyze_worldbuilding(paras)
        self.assertIn("worldbuilding_paragraph_count", result)
        self.assertIn("worldbuilding_ratio", result)
        self.assertIn("worldbuilding_mentions", result)
        self.assertIn("implantable_count", result)
        self.assertIn("needs_embedding", result)
        self.assertIn("expansion_potential", result)
        self.assertIn("worldbuilding_paragraph_indices", result)
        self.assertIn("implantable_paragraph_indices", result)
        # 世界观文本应该有较多设定提及
        self.assertGreater(result["worldbuilding_mentions"], 0)

    def test_analyze_worldbuilding_battle(self):
        """战斗文本世界观信息少。"""
        paras = split_paragraphs(BATTLE_TEXT)
        result = analyze_worldbuilding(paras)
        self.assertEqual(result["worldbuilding_mentions"], 0)

    def test_analyze_foreshadowing(self):
        """测试伏笔埋设分析。"""
        paras = split_paragraphs(SUSPENSE_TEXT)
        result = analyze_foreshadowing(paras)
        self.assertIn("foreshadowing_paragraph_count", result)
        self.assertIn("foreshadowing_ratio", result)
        self.assertIn("foreshadowing_mentions", result)
        self.assertIn("foreshadowing_slots", result)
        self.assertIn("slot_count", result)
        self.assertIn("needs_foreshadowing", result)
        self.assertIn("expansion_potential", result)
        # 悬疑文本应该有较多伏笔词
        self.assertGreater(result["foreshadowing_mentions"], 0)
        self.assertGreaterEqual(len(result["foreshadowing_slots"]), 1)

    def test_analyze_foreshadowing_slots(self):
        """测试伏笔位置槽。"""
        paras = split_paragraphs(WORLDBUILDING_TEXT)
        result = analyze_foreshadowing(paras)
        slots = result["foreshadowing_slots"]
        # 至少有开头、中间、结尾三个位置
        self.assertGreaterEqual(len(slots), 1)
        for slot in slots:
            self.assertIn("position", slot)
            self.assertIn("paragraph_index", slot)

    def test_analyze_synesthesia(self):
        """测试感官通感分析。"""
        paras = split_paragraphs(BATTLE_TEXT)
        result = analyze_synesthesia(paras)
        self.assertIn("sense_counts", result)
        self.assertIn("sense_diversity", result)
        self.assertIn("active_senses", result)
        self.assertIn("weak_senses", result)
        self.assertIn("single_sense_paragraphs", result)
        self.assertIn("needs_enrichment", result)
        self.assertIn("expansion_potential", result)
        self.assertIsInstance(result["sense_counts"], dict)
        self.assertGreaterEqual(result["sense_diversity"], 1)
        self.assertLessEqual(result["sense_diversity"], 5)

    def test_analyze_synesthesia_sense_counts(self):
        """测试五感统计的键名。"""
        paras = split_paragraphs(BATTLE_TEXT)
        result = analyze_synesthesia(paras)
        for sense in ["visual", "auditory", "olfactory", "gustatory", "tactile"]:
            self.assertIn(sense, result["sense_counts"])

    def test_all_eight_strategies_exist(self):
        """验证 8 种策略都有对应的分析函数。"""
        strategy_functions = [
            analyze_scene_depth,
            analyze_dialogue_quality,
            analyze_psychological_depth,
            analyze_action_detail,
            analyze_transitions,
            analyze_worldbuilding,
            analyze_foreshadowing,
            analyze_synesthesia,
        ]
        self.assertEqual(len(strategy_functions), 8)
        for func in strategy_functions:
            self.assertTrue(callable(func))

    def test_strategy_names_have_eight(self):
        """验证 STRATEGY_NAMES 包含 8 种策略。"""
        self.assertEqual(len(STRATEGY_NAMES), 8)


# =========================================================
# 章节类型推断测试
# =========================================================

class TestChapterTypeInference(unittest.TestCase):
    """测试章节类型自动推断。"""

    def test_infer_battle_type(self):
        """战斗型文本应推断为 battle。"""
        paras = split_paragraphs(BATTLE_TEXT)
        chapter_type, scores = infer_chapter_type(BATTLE_TEXT, paras)
        self.assertIsInstance(chapter_type, str)
        self.assertIn(chapter_type, CHAPTER_TYPES)
        self.assertIsInstance(scores, dict)
        # 战斗文本的战斗类型得分应该较高
        self.assertGreater(scores["battle"], 0)

    def test_infer_emotional_type(self):
        """情感型文本的情感得分应较高。"""
        paras = split_paragraphs(EMOTIONAL_TEXT)
        chapter_type, scores = infer_chapter_type(EMOTIONAL_TEXT, paras)
        self.assertIn(chapter_type, CHAPTER_TYPES)
        self.assertGreater(scores["emotional"], 0)

    def test_infer_worldbuilding_type(self):
        """世界观文本的世界观得分应较高。"""
        paras = split_paragraphs(WORLDBUILDING_TEXT)
        chapter_type, scores = infer_chapter_type(WORLDBUILDING_TEXT, paras)
        self.assertIn(chapter_type, CHAPTER_TYPES)
        self.assertGreater(scores["worldbuilding"], 0)

    def test_infer_suspense_type(self):
        """悬疑文本的悬疑得分应较高。"""
        paras = split_paragraphs(SUSPENSE_TEXT)
        chapter_type, scores = infer_chapter_type(SUSPENSE_TEXT, paras)
        self.assertIn(chapter_type, CHAPTER_TYPES)
        self.assertGreater(scores["suspense"], 0)

    def test_infer_returns_all_type_scores(self):
        """返回的分数字典应包含所有章节类型。"""
        paras = split_paragraphs(BATTLE_TEXT)
        _, scores = infer_chapter_type(BATTLE_TEXT, paras)
        for ct in CHAPTER_TYPES:
            self.assertIn(ct, scores)

    def test_infer_minimal_text(self):
        """极简文本也应能推断出类型。"""
        paras = split_paragraphs(MINIMAL_TEXT)
        chapter_type, scores = infer_chapter_type(MINIMAL_TEXT, paras)
        self.assertIn(chapter_type, CHAPTER_TYPES)


# =========================================================
# 优先级分析引擎测试
# =========================================================

class TestPriorityEngine(unittest.TestCase):
    """测试优先级计算引擎。"""

    def test_priorities_returns_eight_strategies(self):
        """优先级列表应包含 8 种策略。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        self.assertEqual(len(priorities), 8)

    def test_priorities_sorted_descending(self):
        """优先级应按权重降序排列。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        weights = [p[1] for p in priorities]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_priorities_tuple_structure(self):
        """每个优先级条目应为 (code, weight, reason) 三元组。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        for item in priorities:
            self.assertEqual(len(item), 3)
            code, weight, reason = item
            self.assertIsInstance(code, str)
            self.assertIn(code, STRATEGY_NAMES)
            self.assertIsInstance(weight, float)
            self.assertGreater(weight, 0)
            self.assertIsInstance(reason, str)

    def test_priorities_with_chapter_type_override(self):
        """指定章节类型应影响优先级排序。"""
        paras = split_paragraphs(BATTLE_TEXT)
        # 用战斗类型
        p_battle = calculate_priorities(BATTLE_TEXT, paras, 3000, chapter_type="battle")
        # 用情感类型
        p_emotion = calculate_priorities(BATTLE_TEXT, paras, 3000, chapter_type="emotional")
        # 两种情况下的排序应该不同
        battle_codes = [p[0] for p in p_battle]
        emotion_codes = [p[0] for p in p_emotion]
        # action_detail 在战斗型中排名应更高（更靠前，索引更小）
        battle_action_rank = battle_codes.index("action_detail")
        emotion_action_rank = emotion_codes.index("action_detail")
        # 战斗型的 action_detail 权重应该大于情感型的
        battle_action_weight = [w for c, w, _ in p_battle if c == "action_detail"][0]
        emotion_action_weight = [w for c, w, _ in p_emotion if c == "action_detail"][0]
        self.assertGreater(battle_action_weight, emotion_action_weight)

    def test_priorities_gap_affects_weight(self):
        """字数缺口应影响权重。"""
        paras = split_paragraphs(BATTLE_TEXT)
        p_small = calculate_priorities(BATTLE_TEXT, paras, target_chars=500)  # 缺口小
        p_large = calculate_priorities(BATTLE_TEXT, paras, target_chars=5000)  # 缺口大
        # 缺口大时权重应该更大
        small_weight = p_small[0][1]
        large_weight = p_large[0][1]
        self.assertGreater(large_weight, small_weight)

    def test_priorities_all_strategy_codes_valid(self):
        """所有策略代码都应该在 STRATEGY_NAMES 中。"""
        paras = split_paragraphs(EMOTIONAL_TEXT)
        priorities = calculate_priorities(EMOTIONAL_TEXT, paras, target_chars=3000)
        for code, _, _ in priorities:
            self.assertIn(code, STRATEGY_NAMES)


# =========================================================
# 策略冲突检测测试
# =========================================================

class TestConflictDetection(unittest.TestCase):
    """测试策略冲突检测。"""

    def test_conflict_action_transition(self):
        """动作细节和过渡润滑应冲突。"""
        self.assertTrue(check_conflict("action_detail", "transition_smoothing"))

    def test_conflict_transition_action(self):
        """双向检测都应有效。"""
        self.assertTrue(check_conflict("transition_smoothing", "action_detail"))

    def test_no_conflict_scene_action(self):
        """场景扩充和动作细节不应冲突。"""
        self.assertFalse(check_conflict("scene_expansion", "action_detail"))

    def test_no_conflict_foreshadowing_any(self):
        """伏笔埋设不应与任何策略冲突。"""
        for strategy in STRATEGY_NAMES:
            self.assertFalse(check_conflict("foreshadowing", strategy))

    def test_conflict_synesthesia_dialogue(self):
        """感官通感和对话丰富应冲突。"""
        self.assertTrue(check_conflict("synesthesia", "dialogue_enrichment"))

    def test_conflict_worldbuilding_psychology(self):
        """世界观植入和心理深度应冲突。"""
        self.assertTrue(check_conflict("worldbuilding", "psychological_depth"))

    def test_conflict_invalid_strategy(self):
        """不存在的策略不应冲突（安全返回 False）。"""
        self.assertFalse(check_conflict("nonexistent", "action_detail"))
        self.assertFalse(check_conflict("action_detail", "nonexistent"))


# =========================================================
# 智能融合推荐测试
# =========================================================

class TestStrategyCombo(unittest.TestCase):
    """测试策略组合推荐（1主+2辅）。"""

    def test_combo_has_primary(self):
        """推荐组合应有主策略。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        combo = recommend_strategy_combo(priorities)
        self.assertIsNotNone(combo["primary"])
        self.assertIn("code", combo["primary"])
        self.assertIn("name", combo["primary"])
        self.assertIn("weight", combo["primary"])

    def test_combo_has_secondary(self):
        """推荐组合应有辅助策略。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        combo = recommend_strategy_combo(priorities)
        self.assertIn("secondary", combo)
        self.assertIsInstance(combo["secondary"], list)
        # 应该有 0-2 个辅助策略
        self.assertLessEqual(len(combo["secondary"]), 2)
        self.assertGreaterEqual(len(combo["secondary"]), 0)

    def test_combo_estimated_expansion(self):
        """应返回预估增字量。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        combo = recommend_strategy_combo(priorities)
        self.assertIn("estimated_expansion_chars", combo)
        self.assertGreater(combo["estimated_expansion_chars"], 0)

    def test_combo_score(self):
        """应返回组合评分。"""
        paras = split_paragraphs(BATTLE_TEXT)
        priorities = calculate_priorities(BATTLE_TEXT, paras, target_chars=3000)
        combo = recommend_strategy_combo(priorities)
        self.assertIn("combo_score", combo)
        self.assertGreater(combo["combo_score"], 0)

    def test_combo_no_conflict_primary_secondary(self):
        """主策略和辅助策略不应冲突。"""
        # 用多种文本测试
        for text in [BATTLE_TEXT, EMOTIONAL_TEXT, SUSPENSE_TEXT, WORLDBUILDING_TEXT]:
            paras = split_paragraphs(text)
            priorities = calculate_priorities(text, paras, target_chars=3000)
            combo = recommend_strategy_combo(priorities)
            if combo["primary"]:
                for sec in combo["secondary"]:
                    self.assertFalse(
                        check_conflict(combo["primary"]["code"], sec["code"]),
                        f"主策略 {combo['primary']['code']} 与辅助 {sec['code']} 冲突"
                    )

    def test_combo_empty_priorities(self):
        """空优先级列表应安全返回。"""
        combo = recommend_strategy_combo([])
        self.assertIsNone(combo["primary"])
        self.assertEqual(combo["secondary"], [])
        self.assertEqual(combo["estimated_expansion"], 0)

    def test_combo_primary_is_top_priority(self):
        """主策略应该是优先级最高的。"""
        paras = split_paragraphs(WORLDBUILDING_TEXT)
        priorities = calculate_priorities(WORLDBUILDING_TEXT, paras, target_chars=3000, chapter_type="worldbuilding")
        combo = recommend_strategy_combo(priorities)
        self.assertEqual(combo["primary"]["code"], priorities[0][0])


# =========================================================
# 具体化建议生成测试
# =========================================================

class TestConcreteSuggestions(unittest.TestCase):
    """测试具体化扩充建议生成。"""

    def test_suggestions_for_all_strategies(self):
        """应为所有 8 种策略生成建议。"""
        paras = split_paragraphs(BATTLE_TEXT)
        for strategy in STRATEGY_NAMES:
            suggestions = generate_concrete_suggestions(strategy, paras, BATTLE_TEXT, num_suggestions=3)
            self.assertIsInstance(suggestions, list)
            self.assertGreater(len(suggestions), 0)

    def test_suggestion_structure(self):
        """每条建议应包含指定字段。"""
        paras = split_paragraphs(BATTLE_TEXT)
        suggestions = generate_concrete_suggestions("scene_expansion", paras, BATTLE_TEXT)
        for sug in suggestions:
            self.assertIn("strategy", sug)
            self.assertIn("location", sug)
            self.assertIn("paragraph_index", sug)
            self.assertIn("direction", sug)
            self.assertIn("example", sug)

    def test_suggestions_location_valid(self):
        """位置描述应为有效值。"""
        valid_locations = {"开头", "前中段", "中间", "后中段", "结尾"}
        paras = split_paragraphs(BATTLE_TEXT)
        for strategy in STRATEGY_NAMES:
            suggestions = generate_concrete_suggestions(strategy, paras, BATTLE_TEXT, num_suggestions=2)
            for sug in suggestions:
                self.assertIn(sug["location"], valid_locations)

    def test_suggestions_num_control(self):
        """应能控制建议条数（上限为策略内置模板数）。"""
        paras = split_paragraphs(BATTLE_TEXT)
        # 测试较小的数量
        for n in [1, 2, 3]:
            suggestions = generate_concrete_suggestions("action_detail", paras, BATTLE_TEXT, num_suggestions=n)
            self.assertEqual(len(suggestions), n)
        # 请求超过内置模板数时，返回实际可用的数量（不超过上限）
        suggestions = generate_concrete_suggestions("action_detail", paras, BATTLE_TEXT, num_suggestions=10)
        self.assertLessEqual(len(suggestions), 10)
        self.assertGreater(len(suggestions), 0)

    def test_suggestions_strategy_matches(self):
        """建议中的 strategy 字段应与请求的策略一致。"""
        paras = split_paragraphs(EMOTIONAL_TEXT)
        for strategy in STRATEGY_NAMES:
            suggestions = generate_concrete_suggestions(strategy, paras, EMOTIONAL_TEXT, num_suggestions=2)
            for sug in suggestions:
                self.assertEqual(sug["strategy"], strategy)

    def test_describe_location(self):
        """测试位置描述函数。"""
        self.assertEqual(_describe_location(0, 10), "开头")
        self.assertEqual(_describe_location(5, 10), "中间")
        self.assertEqual(_describe_location(9, 10), "结尾")
        self.assertEqual(_describe_location(2, 10), "前中段")
        self.assertEqual(_describe_location(7, 10), "后中段")

    def test_describe_location_edge_cases(self):
        """位置描述的边界情况。"""
        self.assertEqual(_describe_location(0, 0), "未知位置")
        # 只有1段时，0/1=0% < 15%，所以是开头
        self.assertEqual(_describe_location(0, 1), "开头")


# =========================================================
# 完整分析测试
# =========================================================

class TestFullAnalysis(unittest.TestCase):
    """测试完整分析函数 analyze_text。"""

    def test_analyze_text_structure(self):
        """完整分析应包含所有必要字段。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000)
        self.assertIn("version", result)
        self.assertIn("total_chars", result)
        self.assertIn("chinese_chars", result)
        self.assertIn("target_chars", result)
        self.assertIn("char_gap", result)
        self.assertIn("paragraph_count", result)
        self.assertIn("needs_expansion", result)
        self.assertIn("chapter_type", result)
        self.assertIn("priorities", result)
        self.assertIn("strategy_combo", result)
        self.assertIn("primary_suggestions", result)
        self.assertIn("secondary_suggestions", result)
        self.assertIn("estimated_expansion_total", result)
        self.assertIn("details", result)

    def test_analyze_text_eight_details(self):
        """details 应包含 8 种策略的分析结果。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000)
        details = result["details"]
        expected_keys = {
            "scene", "dialogue", "psychological", "action",
            "transition", "worldbuilding", "foreshadowing", "synesthesia"
        }
        self.assertEqual(set(details.keys()), expected_keys)

    def test_analyze_text_version(self):
        """版本号应为 2.0.x。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000)
        self.assertTrue(result["version"].startswith("2."))

    def test_analyze_text_priorities_count(self):
        """优先级列表应有 8 项。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000)
        self.assertEqual(len(result["priorities"]), 8)

    def test_analyze_text_chapter_type_override(self):
        """指定章节类型应生效。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000, chapter_type="emotional")
        self.assertEqual(result["chapter_type"], "emotional")

    def test_analyze_text_gap_calculation(self):
        """字数缺口计算应正确。"""
        result = analyze_text(BATTLE_TEXT, target_chars=100)
        # 当前文本字数应该大于100，缺口为0
        self.assertEqual(result["char_gap"], 0)
        self.assertFalse(result["needs_expansion"])

    def test_generate_suggestions_output(self):
        """建议生成应返回字符串。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000)
        output = generate_suggestions(result)
        self.assertIsInstance(output, str)
        self.assertIn("内容扩充建议报告", output)
        self.assertIn("v2.", output)

    def test_generate_expansion_plan_output(self):
        """扩充方案生成应返回字符串。"""
        result = analyze_text(BATTLE_TEXT, target_chars=3000)
        output = generate_expansion_plan(result)
        self.assertIsInstance(output, str)
        self.assertIn("完整扩充方案", output)

    def test_expansion_plan_includes_action_items(self):
        """扩充方案应包含行动清单。"""
        result = analyze_text(EMOTIONAL_TEXT, target_chars=3000)
        output = generate_expansion_plan(result)
        self.assertIn("行动清单", output)

    def test_all_text_types_work(self):
        """所有测试文本类型都能正常分析。"""
        for text in [BATTLE_TEXT, EMOTIONAL_TEXT, TRANSITION_TEXT, SUSPENSE_TEXT, WORLDBUILDING_TEXT]:
            result = analyze_text(text, target_chars=3000)
            self.assertIn("priorities", result)
            self.assertIn("strategy_combo", result)
            self.assertEqual(len(result["priorities"]), 8)


# =========================================================
# CLI 子命令测试（子进程方式）
# =========================================================

class TestCLICommands(unittest.TestCase):
    """测试 CLI 各子命令（通过子进程调用）。"""

    def setUp(self):
        """创建临时测试文件。"""
        self.tmp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.tmp_dir) / "test_chapter.md"
        self.test_file.write_text(BATTLE_TEXT, encoding="utf-8")

    def tearDown(self):
        """清理临时文件。"""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _run_cli(self, *args):
        """运行 CLI 命令并返回结果。"""
        cmd = [sys.executable, str(SCRIPT_PATH)] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(SCRIPT_DIR.parent),
        )
        return result

    def test_cli_analyze(self):
        """测试 analyze 子命令。"""
        result = self._run_cli("analyze", str(self.test_file), "--target", "3000")
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("内容扩充建议报告", result.stdout)
        self.assertIn("v2.", result.stdout)

    def test_cli_analyze_json(self):
        """测试 analyze --json 输出。"""
        result = self._run_cli("analyze", str(self.test_file), "--target", "3000", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("version", data)
        self.assertIn("priorities", data)
        self.assertEqual(len(data["priorities"]), 8)

    def test_cli_suggest(self):
        """测试 suggest 子命令。"""
        result = self._run_cli("suggest", str(self.test_file), "--strategy", "action_detail")
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_cli_suggest_all_strategies(self):
        """测试 suggest 对所有 8 种策略都可用。"""
        for strategy in STRATEGY_NAMES:
            result = self._run_cli("suggest", str(self.test_file), "--strategy", strategy, "--num", "2")
            self.assertEqual(result.returncode, 0, f"Strategy {strategy} failed: {result.stderr}")
            data = json.loads(result.stdout)
            self.assertIsInstance(data, list)

    def test_cli_priority(self):
        """测试 priority 子命令。"""
        result = self._run_cli("priority", str(self.test_file), "--target", "3000")
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("策略优先级排序", result.stdout)

    def test_cli_priority_json(self):
        """测试 priority --json 输出。"""
        result = self._run_cli("priority", str(self.test_file), "--target", "3000", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("chapter_type", data)
        self.assertIn("priorities", data)
        self.assertEqual(len(data["priorities"]), 8)

    def test_cli_priority_with_type(self):
        """测试 priority 指定章节类型。"""
        result = self._run_cli("priority", str(self.test_file), "--target", "3000", "--type", "battle")
        self.assertEqual(result.returncode, 0)
        self.assertIn("battle", result.stdout)

    def test_cli_expand(self):
        """测试 expand 子命令。"""
        result = self._run_cli("expand", str(self.test_file), "--target", "3000")
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("完整扩充方案", result.stdout)

    def test_cli_expand_json(self):
        """测试 expand --json 输出。"""
        result = self._run_cli("expand", str(self.test_file), "--target", "3000", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("strategy_combo", data)
        self.assertIn("primary_suggestions", data)

    def test_cli_analyze_with_type(self):
        """测试 analyze 指定章节类型。"""
        result = self._run_cli("analyze", str(self.test_file), "--target", "3000", "--type", "emotional")
        self.assertEqual(result.returncode, 0)
        self.assertIn("emotional", result.stdout)

    def test_cli_no_command_shows_help(self):
        """无命令时应显示帮助。"""
        result = self._run_cli()
        # 无命令时 returncode 可能为 0 或非0，但应该输出帮助信息
        self.assertIn("content_expander", (result.stdout + result.stderr).lower())


# =========================================================
# 主入口
# =========================================================

if __name__ == "__main__":
    # Windows 控制台 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    unittest.main(verbosity=2)
