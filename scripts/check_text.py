#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_text.py — 章节机械闸口 v3.1（纯标准库，无第三方依赖）。

检查四类确定性问题：
  1. 字数：是否达到平台/更新计划要求的上下限（按非空白字符数与汉字数统计）。
  2. 一级禁用词：AI 高频口癖（清单见 references/craft/anti-ai-style.md）。
     自动加载书籍工程的题材专属词表：依次尝试 正文/禁用词.txt、设定/禁用词.txt。
     v3.0：禁用词.txt 中 ! 前缀的行表示豁免词（加入白名单）。
  3. 毒句式：高置信度的 AI 腔句式模式（正则），含 v2.1 扩充的实战漏网句式。
  4. 伏笔超期（可选）：--ledger 指向伏笔台账，--current-chapter 给出当前章号，
     超期未回收报 FAIL，临近回收窗口报 WARN。

v3.1 新增能力：
  - 多维退化检测（scan_degradation）：不再只看禁用词频次，而是从五个维度
    综合判断「文本是否在退化」——
      ① 禁用词退化：同一禁用词 >3 次
      ② 句式退化：同一句首模式（前6字）≥4 句连排
      ③ 段落退化：连续 ≥3 段长度差 ≤5 字（AI 排比段落典型特征）
      ④ 情绪词退化：同一情绪词在全章出现 ≥4 次（泛化失焦）
      ⑤ 动词退化：同一动作动词在全章出现 ≥8 次（复读指纹）
  - 碎句号双门槛增强：在原句数门槛基础上增加「短句字数占比 ≥60%」
    作为第二门槛，降低误报率（对话密集的章节短句多但不是电报体）。
  - --degradation 子命令：输出退化检测专项报告。

v3.0 新增能力：
  - 扩展 AI 模式检测维度（7 类段落级检测）：
      微动作复读（段内「了下/了一下」≥3 次，电报体指纹）
      抽象总结复读（段内「命运/齿轮/才刚刚开始/一切/注定」≥2 个关键词）
      套词密度（15 个比喻套词的段落密度）
      解释链密度（连续 ≥3 句含因果/解释标记）
      监控动作清单（连续 ≥3 句「主语+动词」同一句式开头）
      引号强调滥用（同一自然段内引号内容 ≥4 个且非对话）
      工程词泄漏扩展（细纲/情节点/章纲/大纲/读者/作者/本章目标/伏笔/钩子等）
  - 新增 --deslop 模式：量化六级打分
      （禁用词密度/连续排比段数/心理词占比/对话标签密度/平均段落句数/重复描写密度），
      输出轻/中/重分级建议。
  - 新增 --whitelist 参数：显式指定白名单文件路径；
      设定/禁用词.txt 中 ! 前缀的行自动作为豁免词加载。

v2.1 新增能力：
  - 叙述/对话分离：引号（""「」）内为对话，引号外为叙述。多数 AI 腔规则只扫叙述
    （对话里口语化的「知道」「像」是正常中文），套词/毒句式在叙述中判 blocking、
    在对话中降 advisory。
  - 严重度分级：blocking（确定性 AI 腔，命中即改，计入未通过）与
    advisory（密度/读感提示，需人工判断，默认不计入未通过；--fail-on=all 时计入）。
  - 新增规则类别（叙述域）：
      blocking：否定排比（没有X，没有Y）、反序对比（是A，不是B）、音量反差腔
        （声音不大…却…）、预告式收尾（没人知道/才刚刚开始，文末窗口）、
        章尾状态总结体（这一夜注定/命运的齿轮，文末窗口）、Gate G 解释腔
        （她不知道的是/之所以…是因为/这意味着）、工程词泄漏（本章/伏笔/细纲/读者
        等写作工程词入正文）、拒绝语残留（作为AI/我无法…）。
      advisory：碎句号电报体（连续 ≥6 个 ≤5 字叙述短句）、长段落（>200 字）、
        微动作复读（V了下/了一下 高密度）、监控摄像头式动作清单、抽象总结密度
        （命运/棋局/前所未有…）、比喻密度、解释链密度、引号强调滥用、
        复读句（同句 ≥3 次）、结尾截断（末行无终止标点）。
  - Gate F 修复：末段判定在无空行分段的文本中正确取「最后若干行」，预览显示
    真正的结尾部分。
  - 门禁状态落盘（--gate-state）：把本次检查结果写入 追踪/门禁/gate_ch{N}.json
    （章节、时间戳、passed、blocking/advisory 计数、AI 味分数、章节文件 mtime）。
    写下一章前用 --verify-prev 查验上一章门禁：缺失/未通过/写后改动（mtime 不符）
    均判 FAIL。「欠账门」由此从文字约定变成跨会话可验证的机器状态。
  - 豁免标记：正文首 5 行内含 <!-- 闸口:跳过 --> 时整章跳过全部扫描（作者显式豁免）。
  - 退化检测增强：同一禁用词 >3 次 WARN + 复读句 + 截断 + 拒绝语 + 工程词泄漏。

--gate-report 输出完整 7 Gate + 扩充规则检测报告。
--style-stats 输出六维文风统计（平均句长/对话占比/段落中位长度/标点节奏/
高频词Top20/句式偏好），与 style_fingerprint.py 的 extract 输出一致。

用法：
  python3 scripts/check_text.py "正文/第037章_标题.md" --min-chars 2000 --max-chars 3500
  python3 scripts/check_text.py chapter.md --ledger "追踪/伏笔台账.md" --current-chapter 37
  python3 scripts/check_text.py chapter.md --gate-report --gate-state
  python3 scripts/check_text.py chapter.md --verify-prev --current-chapter 38
  python3 scripts/check_text.py chapter.md --style-stats
  python3 scripts/check_text.py chapter.md --deslop          # 六级量化打分
  python3 scripts/check_text.py chapter.md --whitelist "设定/豁免词.txt"

退出码：0 = 全部通过；1 = 有 blocking 命中/字数越限/伏笔超期/门禁查验失败
（--fail-on=all 时 advisory 也算）；2 = 参数/文件错误。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import statistics
import sys

# 导入AI评分阈值（单源真相）
try:
    from config import AI_SCORE_THRESHOLDS
except ImportError:
    AI_SCORE_THRESHOLDS = {"low": 20, "medium": 40, "high": 100}

# 让本脚本能导入同目录的 style_fingerprint.py（共享六维文风逻辑）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    import style_fingerprint as sf
    _HAS_SF = True
except Exception:  # 导入失败时退回内置三维度统计，保证脚本可独立运行
    sf = None
    _HAS_SF = False

# 一级禁用词（与 references/craft/anti-ai-style.md 第二节保持一致，改动需同步）
BANNED_WORDS = [
    "仿佛", "似乎", "不禁", "不由得", "一丝",
    "眼底闪过", "嘴角勾起", "嘴角上扬", "意味深长", "若有所思",
    "不容置疑", "空气仿佛凝固", "时间仿佛静止",
    "众所周知", "值得一提", "不得不说",
]

# 毒句式（正则模式 + 说明）——叙述域 blocking，对话域 advisory
TOXIC_PATTERNS = [
    (re.compile(r"不是[^。！？\n]{1,30}[，,][^。！？\n]{0,12}而是"), "not-is-comparison", "「不是A，而是B」句式"),
    (re.compile(r"没有[^。！？\n]{1,20}[，,]\s*只有"), "no-only", "「没有X，只有Y」句式"),
    (re.compile(r"这一刻[，,]"), "this-moment", "「这一刻，」起手式"),
    # v2.1 实战漏网句式（blocking）
    (re.compile(r"(?:没有|无)[^。！？\n]{1,14}[，,](?:也)?(?:没有|无)[^。！？\n]{1,14}"),
     "negation-parade", "否定排比（没有X，没有Y连排）"),
    (re.compile(r"是[^。！？\n]{1,20}[，,]\s*(?:而)?不是[^。！？\n]{1,20}"),
     "reverse-not-is", "反序对比（是A，不是B）"),
    (re.compile(r"声音(?:不大|不高|很轻|轻柔|平静|平淡|低)[^。！？\n]{0,20}却"),
     "voice-contrast", "音量反差腔（声音不大…却…）"),
]

# Gate C 心理告知：情绪词表（用于「他很/她很/他感到/她感到+情绪词」匹配）
EMOTION_WORDS = [
    "紧张", "愤怒", "失落", "难过", "开心", "高兴", "悲伤", "害怕", "恐惧", "担忧",
    "焦虑", "兴奋", "激动", "失望", "委屈", "心痛", "心酸", "震惊", "诧异", "惊讶",
    "尴尬", "羞愧", "自责", "愧疚", "感动", "温暖", "寒心", "心寒", "绝望", "无助",
    "孤独", "寂寞", "思念", "想念", "留恋", "不舍", "释然", "坦然", "平静", "冷静",
    "镇定", "慌张", "慌乱", "惊慌", "错愕", "愕然", "释怀", "痛苦", "痛心", "心碎",
    "心急", "焦急", "急躁", "不安", "忐忑", "纠结", "矛盾", "犹豫", "迟疑", "警惕",
    "戒备", "警觉", "怀疑", "猜忌", "嫉妒", "羡慕", "崇拜", "敬佩", "钦佩", "佩服",
    "轻蔑", "鄙视", "不屑", "厌恶", "讨厌", "烦躁", "烦闷", "郁闷", "抑郁", "沉闷",
    "沉重", "轻松", "放松", "舒畅", "畅快", "痛快", "爽快", "欣慰", "欣喜", "狂喜",
    "惊喜", "欢喜", "喜悦", "哀伤", "忧愁", "忧郁", "忧伤", "伤感", "感伤", "惆怅",
    "怅然", "茫然", "迷茫", "彷徨", "无奈", "心虚", "心慌", "心乱", "心冷", "心热",
]

# Gate C 心理告知句式（叙述域候选，需人工确认）
GATE_C_PATTERNS = [
    (re.compile(r"(?:他|她)(?:很|感到)(?:" + "|".join(EMOTION_WORDS) + r")"),
     "心理告知·直接陈述情绪"),
    (re.compile(r"心中(?:涌起|暗道|一惊|一紧|一凉|一喜|一暖|一沉|一凛|一颤|一寒|一动)"),
     "心理告知·心中句式"),
    (re.compile(r"一股[一-鿿㐀-䶿豈-﫿]{1,6}涌上心头"),
     "心理告知·一股X涌上心头"),
]

# Gate G 解释腔/上帝感（叙述域 blocking）——叙述者跳出角色当下解释/剧透/定性
GATE_G_PATTERNS = [
    (re.compile(r"[他她]不知道的是"), "explainer-tone", "「他不知道的是」上帝视角剧透"),
    (re.compile(r"之所以[^。！？\n]{1,24}是因为"), "explainer-tone", "「之所以…是因为」解释因果"),
    (re.compile(r"这意味着"), "explainer-tone", "「这意味着」叙述者定性"),
    (re.compile(r"事实证明"), "explainer-tone", "「事实证明」叙述者裁判"),
]

# 工程词泄漏（标题行以外正文不得出现；blocking）。角色在故事内真实阅读/讨论
# 「第X章」文本属例外，用 <!-- 闸口:跳过 --> 或人工判断豁免。
# v3.0 扩展：细纲/情节点/章纲/大纲/读者/作者/本章目标/伏笔/钩子 等元信息词混入正文。
META_LEAK_PATTERNS = [
    (re.compile(r"第[一二三四五六七八九十百千万两0-9]+章"), "meta-leak", "工程词「第X章」入正文"),
    (re.compile(r"上一章|上章|前一章|本章|这一章|下一章"), "meta-leak", "工程词「上/下一章」入正文"),
    (re.compile(r"前文|后文|伏笔|细纲|章纲|大纲"), "meta-leak", "工程词（前文/伏笔/细纲…）入正文"),
    # v3.0 新增元信息词
    (re.compile(r"情节点|本章目标|钩子|铺垫"), "meta-leak", "工程词（情节点/本章目标/钩子…）入正文"),
    (re.compile(r"读者(?:们)?(?:会|可能|应该|一定)?(?:觉得|看到|读到|发现)"), "meta-leak",
     "叙述者点名「读者」出戏"),
    (re.compile(r"作者(?:们)?(?:想|要|希望|将|会)?(?:表达|呈现|告诉|描写|刻画)"), "meta-leak",
     "叙述者点名「作者」出戏"),
]

# 拒绝语/AI 助手腔残留（blocking）
REFUSAL_PATTERNS = [
    (re.compile(r"作为(?:一个)?AI|作为人工智能|作为语言模型"), "refusal-tone", "AI 助手身份残留"),
    (re.compile(r"我无法(?:继续|提供|完成)|很抱歉[^。！？\n]{0,12}无法"), "refusal-tone", "拒绝语残留"),
]

# 抽象总结复读（advisory，密度型）：模板化拔高
ABSTRACT_SUMMARY_PATTERNS = [
    re.compile(r"这一刻[，,]?[^\n。！？!?]{0,24}(?:终于|才)(?:明白|意识到)"),
    re.compile(r"从这一刻开始"),
    re.compile(r"(?:命运|宿命)[^\n。！？!?]{0,28}(?:齿轮|棋局|獠牙|改写|推向|安排)"),
    re.compile(r"早已[^\n。！？!?]{0,8}(?:布好|安排好)"),
    re.compile(r"前所未有的(?:决意|清醒|勇气|力量|恐惧|平静|信念)"),
    re.compile(r"(?:反击|复仇|战争|较量|故事|命运)[^\n。！？!?]{0,12}才刚刚开始"),
    re.compile(r"(?:新的开始|全新的开始)"),
]
ABSTRACT_MIN_HITS = 3
ABSTRACT_PER_KILO = 4.0

# 预告式收尾 / 章尾状态总结（文末窗口 blocking）
TRAILER_ENDING_PATTERNS = [
    (re.compile(r"(?:没人|没有人)知道"), "trailer-ending", "预告式收尾「没人知道…」"),
    (re.compile(r"才刚刚开始|正要开始|即将开始"), "trailer-ending", "预告式收尾「才刚刚开始」"),
    (re.compile(r"即将拉开|拉开序幕"), "trailer-ending", "预告式收尾「拉开序幕」"),
    (re.compile(r"正朝着[^\n。！？!?]{0,20}(?:压|逼|走)"), "trailer-ending", "预告式收尾「正朝着…压过去」"),
]
TRAILER_SUMMARY_PATTERNS = [
    (re.compile(r"这一夜注定"), "trailer-summary", "章尾状态总结「这一夜注定」"),
    (re.compile(r"这一切都结束了|一切尘埃落定"), "trailer-summary", "章尾状态总结「尘埃落定」"),
    (re.compile(r"新的人生|新的篇章|新的旅程|踏上新的"), "trailer-summary", "章尾状态总结「新的人生」"),
    (re.compile(r"命运的齿轮"), "trailer-summary", "章尾状态总结「命运的齿轮」"),
]

# 微动作复读（advisory，密度型）：V了下/了一下 式轻量补语高密度 = 删减过头的电报体指纹
MICRO_TIC_PATTERN = re.compile(r"了(?:[一两三几半])?[下阵圈道声眼口气会]")
MICRO_TIC_MIN_HITS = 5
MICRO_TIC_PER_KILO = 6.0

# 监控摄像头式动作清单（advisory）：同段连续摆放通用动作动词，缺视角温度
ACTION_LIST_VERBS = re.compile(
    r"伸手|抬手|探手|拿起|拿过|取出|取过|掏出|摸出|抓起|攥住|握住|捏住|按住|"
    r"推开|拉开|打开|关上|放下|递给|挑开|掀开|扯开|拧开|倒出|端起|转身|回头|"
    r"抬头|低头|弯腰|俯身|走到|走向|坐下|站起|看向|看着|盯着|扫过")
ACTION_LIST_MIN_HITS = 5
ACTION_LIST_MIN_SEPARATORS = 4

# 比喻密度（advisory）：叙述里比喻标记成片复现
METAPHOR_PATTERN = re.compile(r"好像|仿佛|如同|宛如|犹如|好似|似的|像是?")
METAPHOR_PER_KILO = 5.0
METAPHOR_MIN_HITS = 4

# v3.0 套词密度（advisory）：15 个比喻套词的段落密度
FORMULA_WORDS = ["仿佛", "似乎", "宛如", "犹如", "好似", "恍若", "如同",
                 "好像", "像是", "似的", "不禁", "不由得", "一丝",
                 "悄然而至", "油然而生", "呼之欲出"]
FORMULA_PER_KILO = 8.0
FORMULA_MIN_HITS = 6

# v3.0 段落级微动作复读（段内「了下/了一下」≥3 次）
MICRO_TIC_PARA_PATTERN = re.compile(r"了(?:[一两三几半])?[下阵圈道声眼口气会]")
MICRO_TIC_PARA_MIN = 3

# v3.0 段落级抽象总结复读（段内关键词 ≥2 个）
ABSTRACT_SUMMARY_KEYWORDS = ["命运", "齿轮", "才刚刚开始", "一切", "注定",
                             "宿命", "棋局", "獠牙", "改写", "安排",
                             "早已", "布好", "安排好", "前所未有"]
ABSTRACT_SUMMARY_PARA_MIN = 2

# v3.0 解释链密度（连续 ≥3 句含因果/解释标记）
CAUSAL_MARKERS_RE = re.compile(
    r"因为|所以|由于|因此|于是|之所以|是因为|这意味着|这说明|"
    r"可见|毕竟|事实上|实际上|显然|换句话说|也就是说|原来|"
    r"他不知道的是|她不知道的是")
CAUSAL_CHAIN_MIN = 3

# v3.0 监控动作清单（连续 ≥3 句「主语+动词」同一句式开头）
# 主语指代：他/她/它/这/那/我/你 + 通用动词
SUBJ_VERB_RE = re.compile(
    r"^(他|她|它|这|那|我|你|其)[^。！？\n]{0,6}(伸手|抬手|探手|拿起|拿过|取出|掏出|"
    r"抓起|攥住|握住|按住|推开|拉开|打开|关上|放下|转身|回头|抬头|低头|"
    r"弯腰|俯身|走到|走向|坐下|站起|看向|看着|盯着|扫过|点|摇|笑|说)")
ACTION_LIST_SENT_MIN = 3

# v3.0 引号强调滥用（同一自然段内引号内容 ≥4 个且非对话）
QUOTE_EMPHASIS_PARA_RE = re.compile(r"[「\"][^」\"\n]{1,8}[」\"]")
QUOTE_EMPHASIS_PARA_MIN = 4

# 解释链密度（advisory）：叙述者判断链聚集
REASONING_PATTERN = re.compile(
    r"[他她]知道|[他她]明白|[他她]意识到|这说明|这意味着|可见|毕竟|事实上|实际上|"
    r"显然|不可否认|换句话说|也就是说|原来")
REASONING_PER_KILO = 4.0
REASONING_MIN_HITS = 4

# 引号强调（advisory）：叙述里 1-4 字短词加引号强调（对话行豁免）
QUOTE_EMPHASIS_RE = re.compile(r"[「\"][^」\"\n]{1,4}[」\"]")
QUOTE_EMPHASIS_MIN_HITS = 3
QUOTE_EMPHASIS_PER_KILO = 3.0
DIALOGUE_TAG_RE = re.compile(r"[说问喊道答叫骂吼哭笑嘟囔嘀咕吩咐解释回应接道]{1,2}[：:]?$")

# 碎句号（advisory）：连续 ≥N 个叙述短句（每句可见字数 ≤M）无呼吸
STUTTER_MIN_RUN = 6
STUTTER_MAX_SENT = 8

# 长段落（advisory）：单段字符数超阈值
LONG_PARA_CHARS = 200

# 复读句（advisory）：≥8 字的相同叙述句出现 ≥3 次
REPEAT_MIN_LEN = 8
REPEAT_MIN_COUNT = 3

# 引号识别（对话域 vs 叙述域）
QUOTE_RE = re.compile(r'"[^"\n]*"|「[^」\n]*」')

# Gate F 结尾升华：总结性语句片段
SUBLIMATION_PHRASES = [
    "这次经历", "他知道", "这一刻", "这一切", "成长了", "明白了",
    "让他明白", "让她明白", "让他懂得", "让她懂得", "从此",
    "他终于明白", "她终于明白", "他终于懂了", "她终于懂了",
    "他意识到", "她意识到", "他懂得", "她懂得", "这一切都",
]
SUMMARY_WORDS = ["明白", "懂得", "成长", "意识到", "感受", "体会", "改变", "意义",
                 "价值", "终于", "从此", "蜕变", "释怀"]
ACTION_WORDS = ["走", "说", "看", "拿", "放下", "转身", "推", "拉", "笑", "哭",
                "点头", "摇头", "站", "坐", "跑", "跳", "打", "踢", "挥", "握",
                "抬", "推开门", "走出", "坐下", "起身", "闭上眼", "深吸"]

CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")

SKIP_MARKER = "<!-- 闸口:跳过 -->"


def count_chars(text):
    """返回 (非空白字符数, 汉字数)。网文平台字数口径一般接近前者。"""
    non_ws = len(re.sub(r"\s", "", text))
    cjk = len(CJK_RE.findall(text))
    return non_ws, cjk


def load_wordlist(path):
    """加载禁用词表。v3.0：! 前缀的行作为豁免词单独返回。

    返回 (禁用词列表, 豁免词集合)。! 前缀的行不进入禁用词，而是加入豁免词集合。
    """
    words = []
    exemptions = set()
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            w = line.strip()
            if not w or w.startswith("#"):
                continue
            if w.startswith("!"):
                ex = w[1:].strip()
                if ex:
                    exemptions.add(ex)
            else:
                words.append(w)
    return words, exemptions


def auto_wordlists(chapter_path):
    """自动发现书籍工程里的题材专属词表：正文/禁用词.txt、设定/禁用词.txt。"""
    d = os.path.dirname(os.path.abspath(chapter_path))
    candidates = [
        os.path.join(d, "禁用词.txt"),
        os.path.join(d, os.pardir, "设定", "禁用词.txt"),
    ]
    found, seen = [], set()
    for c in candidates:
        c = os.path.normpath(c)
        if c not in seen and os.path.isfile(c):
            found.append(c)
            seen.add(c)
    return found


def find_whitelist(chapter_path):
    """从章节文件所在目录向上查找书籍工程根目录的 .deslop-whitelist。"""
    d = os.path.dirname(os.path.abspath(chapter_path))
    seen = set()
    while d and d not in seen:
        seen.add(d)
        candidate = os.path.join(d, ".deslop-whitelist")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def load_whitelist(path):
    words = set()
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):
                words.add(w)
    return words


def is_whitelisted(word, line, whitelist):
    """判断一处禁用词命中是否被白名单豁免（规则见 anti-ai-style.md）。"""
    if not whitelist:
        return False
    if word in whitelist:
        return True
    for wl in whitelist:
        if len(wl) > len(word) and word in wl and wl in line:
            return True
    return False


def strip_dialogue(line):
    """把行内引号对话替换为占位符，返回叙述域文本。"""
    return QUOTE_RE.sub("「」", line)


def narration_len(text):
    """叙述域可见字数（去空白与引号内容）。"""
    return len(re.sub(r"\s", "", strip_dialogue(text)))


def has_skip_marker(text):
    """首 5 行内含豁免标记则整章跳过。"""
    head = "\n".join(text.splitlines()[:5])
    return SKIP_MARKER in head


def is_title_line(idx, line):
    """首行且形如 markdown 标题或「第X章 …」视为标题行（工程词豁免）。"""
    if idx != 1:
        return False
    s = line.strip()
    return s.startswith("#") or bool(re.match(r"^第\s*\d+\s*章", s))


def scan_lines(lines, words, whitelist=None):
    """逐行扫描禁用词与毒句式（叙述/对话分域）。

    返回 (banned_hits, toxic_hits)：
      banned_hits = [(行号, 命中词, 行内容, severity)]
      toxic_hits  = [(行号, rule_id, 标签, 匹配串, 行内容, severity)]
    叙述域 = blocking，对话域 = advisory；命中白名单的禁用词跳过。
    """
    whitelist = whitelist or set()
    banned_hits = []
    toxic_hits = []
    for i, line in enumerate(lines, 1):
        narration = strip_dialogue(line)
        for w in words:
            if w in narration:
                if is_whitelisted(w, line, whitelist):
                    continue
                banned_hits.append((i, w, line.strip(), "blocking"))
            elif w in line:  # 仅对话内命中
                if is_whitelisted(w, line, whitelist):
                    continue
                banned_hits.append((i, w, line.strip(), "advisory"))
        for pat, rule_id, label in TOXIC_PATTERNS:
            m = pat.search(narration)
            if m:
                toxic_hits.append((i, rule_id, label, m.group(0), line.strip(), "blocking"))
                continue
            m2 = pat.search(line)
            if m2:
                toxic_hits.append((i, rule_id, label, m2.group(0), line.strip(), "advisory"))
    return banned_hits, toxic_hits


def scan_gate_c(lines):
    """Gate C 心理告知机器检测（叙述域），返回 [(行号, 标签, 匹配串, 行内容)]。"""
    hits = []
    for i, line in enumerate(lines, 1):
        narration = strip_dialogue(line)
        for pat, label in GATE_C_PATTERNS:
            for m in pat.finditer(narration):
                hits.append((i, label, m.group(0), line.strip()))
    return hits


def scan_blocking_patterns(lines):
    """Gate G / 工程词泄漏 / 拒绝语（叙述域 blocking）。

    返回 [(行号, rule_id, 标签, 匹配串, 行内容)]。标题行豁免工程词。
    """
    hits = []
    for i, line in enumerate(lines, 1):
        narration = strip_dialogue(line)
        for pat, rule_id, label in GATE_G_PATTERNS + REFUSAL_PATTERNS:
            m = pat.search(narration)
            if m:
                hits.append((i, rule_id, label, m.group(0), line.strip()))
        if is_title_line(i, line):
            continue
        for pat, rule_id, label in META_LEAK_PATTERNS:
            m = pat.search(narration)
            if m:
                hits.append((i, rule_id, label, m.group(0), line.strip()))
    return hits


def scan_trailer(text):
    """预告式收尾 / 章尾状态总结（文末窗口 blocking），返回 [(标签, 匹配串)]。"""
    tail = strip_dialogue(text[-160:])
    hits = []
    for pat, rule_id, label in TRAILER_ENDING_PATTERNS + TRAILER_SUMMARY_PATTERNS:
        m = pat.search(tail)
        if m:
            hits.append((label, m.group(0)))
    return hits


def scan_paragraph_tics(text):
    """v3.0 段落级 AI 模式检测（advisory，7 类）。

    返回 [(rule_id, 标签, 证据说明)]。检测维度：
      微动作复读 / 抽象总结复读 / 套词密度 / 解释链密度 /
      监控动作清单 / 引号强调滥用。
    （工程词泄漏扩展由 scan_blocking_patterns 处理。）
    """
    hits = []
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    # 1. 段落级微动作复读（段内「了下/了一下」≥3 次）
    micro_paras = []
    for p in paras:
        narration = strip_dialogue(p)
        cnt = len(MICRO_TIC_PARA_PATTERN.findall(narration))
        if cnt >= MICRO_TIC_PARA_MIN:
            micro_paras.append((cnt, p))
    if micro_paras:
        micro_paras.sort(key=lambda x: -x[0])
        worst_cnt, worst_para = micro_paras[0]
        preview = worst_para.strip().replace("\n", " ")
        preview = preview if len(preview) <= 50 else preview[:47] + "..."
        hits.append(("micro-tic-para", "段落级微动作复读（段内「了下/了一下」≥3 次，电报体指纹）",
                     f"{len(micro_paras)} 段触发，最高 {worst_cnt} 次/段：{preview}"))

    # 2. 段落级抽象总结复读（段内关键词 ≥2 个）
    abs_paras = []
    for p in paras:
        narration = strip_dialogue(p)
        found_kw = [kw for kw in ABSTRACT_SUMMARY_KEYWORDS if kw in narration]
        if len(found_kw) >= ABSTRACT_SUMMARY_PARA_MIN:
            abs_paras.append((found_kw, p))
    if abs_paras:
        all_kws = sorted({kw for kws, _ in abs_paras for kw in kws})
        preview = abs_paras[0][1].strip().replace("\n", " ")
        preview = preview if len(preview) <= 50 else preview[:47] + "..."
        hits.append(("abstract-summary-para", "段落级抽象总结复读（段内≥2个拔高关键词）",
                     f"{len(abs_paras)} 段触发，关键词：{'、'.join(all_kws[:6])}：{preview}"))

    # 3. 套词密度（15 个比喻套词的段落密度）
    kilo = max(narration_len(text) / 1000.0, 0.001)
    formula_total = 0
    for w in FORMULA_WORDS:
        formula_total += text.count(w)
    if formula_total >= FORMULA_MIN_HITS and formula_total / kilo >= FORMULA_PER_KILO:
        hits.append(("formula-density", "套词密度过高（仿佛/似乎/宛如等15词成片复现）",
                     f"命中 {formula_total} 处 / {kilo:.1f} 千字（阈值 ≥{FORMULA_MIN_HITS} 且 ≥{FORMULA_PER_KILO}/千字）"))

    # 4. 解释链密度（连续 ≥3 句含因果/解释标记）
    worst_chain = 0
    worst_chain_sent = ""
    for p in paras:
        narration = strip_dialogue(p)
        sents = [s for s in re.split(r"[。！？!?…]+", narration) if s.strip()]
        run = 0
        local_max = 0
        local_sent = ""
        for s in sents:
            if CAUSAL_MARKERS_RE.search(s):
                run += 1
                if run > local_max:
                    local_max = run
                    local_sent = s.strip()
            else:
                run = 0
        if local_max > worst_chain:
            worst_chain = local_max
            worst_chain_sent = local_sent
    if worst_chain >= CAUSAL_CHAIN_MIN:
        preview = worst_chain_sent if len(worst_chain_sent) <= 50 else worst_chain_sent[:47] + "..."
        hits.append(("causal-chain-tic", "解释链密度过高（连续≥3句含因果/解释标记）",
                     f"最长连续 {worst_chain} 句：{preview}"))

    # 5. 监控动作清单（连续 ≥3 句「主语+动词」同一句式开头）
    worst_action = 0
    worst_action_preview = ""
    for p in paras:
        narration = strip_dialogue(p)
        # 按句号/逗号切分句首检测
        sents = re.split(r"[。！？!?…，,]+", narration)
        sents = [s.strip() for s in sents if s.strip()]
        run = 0
        local_max = 0
        local_sent = ""
        for s in sents:
            if SUBJ_VERB_RE.match(s):
                run += 1
                if run > local_max:
                    local_max = run
                    local_sent = s
            else:
                run = 0
        if local_max > worst_action:
            worst_action = local_max
            worst_action_preview = local_sent
    if worst_action >= ACTION_LIST_SENT_MIN:
        preview = worst_action_preview if len(worst_action_preview) <= 50 else worst_action_preview[:47] + "..."
        hits.append(("action-sent-list", "监控动作清单（连续≥3句「主语+动词」同一句式开头）",
                     f"最长连续 {worst_action} 句：{preview}"))

    # 6. 引号强调滥用（同一自然段内引号内容 ≥4 个且非对话）
    worst_qe_para = None
    worst_qe_count = 0
    for p in paras:
        qe_hits = []
        for m in QUOTE_EMPHASIS_PARA_RE.finditer(p):
            # 排除对话：引号后紧跟对话标签
            tail = p[m.end():m.end() + 6]
            if DIALOGUE_TAG_RE.search(tail):
                continue
            qe_hits.append(m.group(0))
        if len(qe_hits) >= QUOTE_EMPHASIS_PARA_MIN and len(qe_hits) > worst_qe_count:
            worst_qe_count = len(qe_hits)
            worst_qe_para = qe_hits
    if worst_qe_para:
        preview = "、".join(worst_qe_para[:4])
        hits.append(("quote-emphasis-para", "引号强调滥用（同一自然段内引号内容≥4个且非对话）",
                     f"单段 {worst_qe_count} 个强调引号：{preview}"))

    return hits


def scan_density(text, non_ws):
    """密度型 advisory 检测（叙述域）。

    返回 [(rule_id, 标签, 证据说明)]。证据说明给出命中数与阈值，便于人工判断。
    """
    narration = strip_dialogue(text)
    kilo = max(narration_len(text) / 1000.0, 0.001)
    hits = []

    # 抽象总结
    found = 0
    for pat in ABSTRACT_SUMMARY_PATTERNS:
        found += len(pat.findall(narration))
    if found >= ABSTRACT_MIN_HITS and found / kilo >= ABSTRACT_PER_KILO:
        hits.append(("abstract-summary-tic", "抽象总结密度过高",
                     f"命中 {found} 处 / {kilo:.1f} 千字（阈值 ≥{ABSTRACT_MIN_HITS} 且 ≥{ABSTRACT_PER_KILO}/千字）"))

    # 微动作复读
    micro = len(MICRO_TIC_PATTERN.findall(narration))
    if micro >= MICRO_TIC_MIN_HITS and micro / kilo >= MICRO_TIC_PER_KILO:
        hits.append(("micro-action-tic", "微动作复读（V了下/了一下 高密度，电报体指纹）",
                     f"命中 {micro} 处 / {kilo:.1f} 千字（阈值 ≥{MICRO_TIC_MIN_HITS} 且 ≥{MICRO_TIC_PER_KILO}/千字）"))

    # 比喻密度
    meta = len(METAPHOR_PATTERN.findall(narration))
    if meta >= METAPHOR_MIN_HITS and meta / kilo >= METAPHOR_PER_KILO:
        hits.append(("metaphor-density-tic", "比喻密度过高（像/仿佛/如同 成片复现）",
                     f"命中 {meta} 处 / {kilo:.1f} 千字（阈值 ≥{METAPHOR_MIN_HITS} 且 ≥{METAPHOR_PER_KILO}/千字）"))

    # 解释链密度
    chain = len(REASONING_PATTERN.findall(narration))
    if chain >= REASONING_MIN_HITS and chain / kilo >= REASONING_PER_KILO:
        hits.append(("reasoning-chain-tic", "解释链密度过高（知道/明白/这意味着 聚集）",
                     f"命中 {chain} 处 / {kilo:.1f} 千字（阈值 ≥{REASONING_MIN_HITS} 且 ≥{REASONING_PER_KILO}/千字）"))

    # 引号强调（对话行豁免）
    qe = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        for m in QUOTE_EMPHASIS_RE.finditer(s):
            tail = s[m.end():].strip()
            head = s[:m.start()].strip()
            # 引号后紧跟对话标签（说/问/道…）或引号前是标签动词 → 对话，跳过
            if DIALOGUE_TAG_RE.search(tail[:4]) or re.search(r"[说问喊道答叫骂吼哭笑]$", head):
                continue
            qe += 1
    if qe >= QUOTE_EMPHASIS_MIN_HITS and qe / kilo >= QUOTE_EMPHASIS_PER_KILO:
        hits.append(("quote-emphasis-tic", "引号强调滥用（叙述里短词加引号）",
                     f"命中 {qe} 处 / {kilo:.1f} 千字（阈值 ≥{QUOTE_EMPHASIS_MIN_HITS} 且 ≥{QUOTE_EMPHASIS_PER_KILO}/千字）"))

    return hits


def scan_structure(text):
    """结构型 advisory 检测：碎句号 / 长段落 / 动作清单 / 复读句 / 截断。

    返回 [(rule_id, 标签, 证据说明)]。
    """
    hits = []
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    # 长段落
    long_paras = [p for p in paras if len(re.sub(r"\s", "", p)) > LONG_PARA_CHARS]
    if long_paras:
        worst = max(len(re.sub(r"\s", "", p)) for p in long_paras)
        hits.append(("long-paragraph", "长段落（建议按镜头断段）",
                     f"{len(long_paras)} 段超 {LONG_PARA_CHARS} 字，最长 {worst} 字"))

    # 碎句号：跨全文的叙述短句连排
    sents = []
    for line in text.splitlines():
        narration = strip_dialogue(line).strip()
        if not narration:
            continue
        for s in re.split(r"[。！？!?…]+", narration):
            s = s.strip("，,、；;：: \t")
            if s:
                sents.append(s)
    run = 0
    worst_run = 0
    for s in sents:
        if len(s) <= STUTTER_MAX_SENT:
            run += 1
            worst_run = max(worst_run, run)
        else:
            run = 0
    if worst_run >= STUTTER_MIN_RUN:
        # v3.1 双门槛：短句字数占比 ≥60% 才报电报体（降低对话密集章节误报）
        short_chars = sum(len(s) for s in sents[:worst_run] if len(s) <= STUTTER_MAX_SENT)
        total_chars_in_run = sum(len(s) for s in sents[:worst_run]) or 1
        short_ratio = short_chars / total_chars_in_run
        if short_ratio >= 0.60:
            hits.append(("period-stutter", "碎句号电报体（连续短叙述句无呼吸）",
                         f"最长连排 {worst_run} 句（每句 ≤{STUTTER_MAX_SENT} 字，短句占比 {short_ratio:.0%}，阈值 ≥60%）"))
        else:
            hits.append(("period-stutter-advisory", "碎句号倾向（短句连排但短句字数占比未达门槛）",
                         f"最长连排 {worst_run} 句，但短句字数占比 {short_ratio:.0%} < 60%，可能是对话密集而非电报体"))

    # 动作清单（逐段判定，取最严重一段作证；证据窗口定位到动词密集区）
    worst = None
    for p in paras:
        narration = strip_dialogue(p)
        verbs = ACTION_LIST_VERBS.findall(narration)
        seps = len(re.findall(r"[，,、]", narration))
        if len(verbs) >= ACTION_LIST_MIN_HITS and seps >= ACTION_LIST_MIN_SEPARATORS:
            score = len(verbs) + seps
            if worst is None or score > worst[0]:
                worst = (score, len(verbs), seps, p.strip())
    if worst:
        _, nv, ns, para = worst
        m_first = ACTION_LIST_VERBS.search(strip_dialogue(para))
        start = max(m_first.start() - 10, 0) if m_first else 0
        window = para[start:start + 60]
        preview = window if len(window) <= 60 else window[:57] + "..."
        hits.append(("action-list-tic", "监控摄像头式动作清单（步骤表，缺视角温度）",
                     f"单段动作动词 {nv} 个 / 逗号 {ns} 个：{preview}"))

    # 复读句
    counter = {}
    for s in sents:
        if len(s) >= REPEAT_MIN_LEN:
            counter[s] = counter.get(s, 0) + 1
    repeated = [(s, c) for s, c in counter.items() if c >= REPEAT_MIN_COUNT]
    if repeated:
        repeated.sort(key=lambda x: -x[1])
        s, c = repeated[0]
        preview = s if len(s) <= 30 else s[:27] + "..."
        hits.append(("repeat-sentence", "复读句（同句反复出现）",
                     f"「{preview}」出现 {c} 次（共 {len(repeated)} 句复读）"))

    # 结尾截断
    tail_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if tail_lines:
        last = tail_lines[-1]
        if last and last[-1] not in "。！？!?\"」』…—~":
            hits.append(("truncation", "结尾疑似截断（末行无终止标点）",
                         f"末行：{last if len(last) <= 40 else last[:37] + '...'}"))

    return hits


def get_last_paragraph(text):
    """取末段（最后一个非空段落，按空行分段）。

    v2.1 修复：无空行分段的长文本（每行一段的网文常见形态）取最后 3 行，
    避免把全文开头当作「末段预览」。
    """
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return ""
    last = paras[-1].strip()
    if len(paras) == 1 or len(last) > 300:
        lines = [ln for ln in last.splitlines() if ln.strip()]
        if len(lines) > 3:
            last = "\n".join(lines[-3:]).strip()
    return last


def classify_ending(last_para):
    """判定末段类型：感慨/总结 vs 动作/场景。"""
    has_summary = any(p in last_para for p in SUBLIMATION_PHRASES)
    has_summary_word = any(w in last_para for w in SUMMARY_WORDS)
    has_action = any(w in last_para for w in ACTION_WORDS)
    if has_summary or has_summary_word:
        return "感慨/总结"
    if has_action:
        return "动作/场景"
    return "未明确"


def scan_gate_f(text):
    """Gate F 结尾升华检测，返回 (是否命中, 命中短语列表, 末段类型, 末段预览)。"""
    last = get_last_paragraph(text)
    if not last:
        return False, [], "未明确", ""
    hit_phrases = [p for p in SUBLIMATION_PHRASES if p in last]
    ending_type = classify_ending(last)
    flat = last.replace("\n", " / ")
    preview = flat if len(flat) <= 60 else flat[:57] + "..."
    return bool(hit_phrases), hit_phrases, ending_type, preview


def check_ledger(ledger_path, current_chapter):
    """解析伏笔台账四态表，返回 (超期FAIL列表, 临近WARN列表)。

    依赖台账模板的分节标题（🔴/🟡/🟢/✅ 或 超期/活跃/长线/已回收）
    与表格列序：🟡 表第 4 列为「预期回收」。
    """
    with open(ledger_path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    section = None
    fails, warns = [], []
    for line in text.splitlines():
        h = re.match(r"^#{1,4}\s*(.+)", line)
        if h:
            t = h.group(1)
            if "🔴" in t or "超期" in t:
                section = "overdue"
            elif "🟡" in t or "活跃" in t:
                section = "active"
            elif "🟢" in t or "长线" in t:
                section = "long"
            elif "✅" in t or "已回收" in t:
                section = "done"
            else:
                section = None
            continue
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or not cells[0] or cells[0] == "ID" or set(cells[0]) <= set("-: "):
            continue
        fid = cells[0]
        if section == "overdue":
            fails.append(f"{fid}：台账中已标 🔴 超期，尚未处理")
        elif section == "active":
            expect = cells[3] if len(cells) > 3 else ""
            if "卷" in expect:  # 跨卷计划不按章号判定
                continue
            m = re.search(r"\d+", expect)
            if not m:
                continue
            n = int(m.group())
            if n < current_chapter:
                fails.append(f"{fid}：预期第{n}章回收，当前第{current_chapter}章，已超期 {current_chapter - n} 章")
            elif n - current_chapter <= 5:
                warns.append(f"{fid}：预期第{n}章回收，临近窗口（还剩 {n - current_chapter} 章）")
    return fails, warns


# ---------- 门禁状态落盘 ----------

def extract_chapter_number(path):
    """从文件名提取章号（第XXX章），找不到返回 None。"""
    base = os.path.basename(path)
    m = re.search(r"第\s*(\d+)\s*章", base)
    return int(m.group(1)) if m else None


def gate_dir_for(chapter_path):
    """门禁目录：章节文件上一级目录的 追踪/门禁/（书籍工程布局）。"""
    book_root = os.path.dirname(os.path.dirname(os.path.abspath(chapter_path)))
    return os.path.join(book_root, "追踪", "门禁")


def gate_state_path(chapter_path, chapter_no):
    return os.path.join(gate_dir_for(chapter_path), f"gate_ch{chapter_no}.json")


def write_gate_state(chapter_path, chapter_no, result):
    """把检查结果写入 追踪/门禁/gate_ch{N}.json。rhythm 段由 rhythm_guard 合并。"""
    gdir = gate_dir_for(chapter_path)
    os.makedirs(gdir, exist_ok=True)
    path = os.path.join(gdir, f"gate_ch{chapter_no}.json")
    existing = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = {}
    st = os.stat(chapter_path)
    state = {
        "chapter": chapter_no,
        "chapter_file": os.path.basename(chapter_path),
        "chapter_mtime": st.st_mtime,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "passed": result["passed"],
        "blocking": result["blocking"],
        "advisory": result["advisory"],
        "ai_score": result["ai_score"],
        "categories": result["categories"],
    }
    if isinstance(existing.get("rhythm"), dict):
        state["rhythm"] = existing["rhythm"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return path


def verify_prev_gate(chapter_path, current_chapter):
    """查验上一章门禁状态，返回 (ok, messages)。

    判定：gate_ch{N-1}.json 必须存在、passed 为 true、且章节文件 mtime 与记录一致
    （防止过闸后又改动正文不重扫）。上一章正文文件缺失时只做存在性+passed 查验。
    """
    prev = current_chapter - 1
    if prev < 1:
        return True, ["第 1 章无需查验上一章门禁"]
    gdir = gate_dir_for(chapter_path)
    path = os.path.join(gdir, f"gate_ch{prev}.json")
    if not os.path.isfile(path):
        return False, [f"上一章（第{prev}章）门禁状态缺失：{path}；"
                       f"先对上一章运行 --gate-report --gate-state 补账"]
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        return False, [f"上一章门禁文件损坏：{e}"]
    msgs = []
    ok = True
    if not state.get("passed"):
        ok = False
        msgs.append(f"上一章（第{prev}章）门禁未通过（blocking={state.get('blocking')}），"
                    f"欠账未清，禁止开写本章")
    prev_file = state.get("chapter_file")
    recorded_mtime = state.get("chapter_mtime")
    if prev_file and recorded_mtime:
        book_root = os.path.dirname(os.path.dirname(os.path.abspath(chapter_path)))
        prev_path = os.path.join(book_root, "正文", prev_file)
        if os.path.isfile(prev_path):
            actual = os.stat(prev_path).st_mtime
            if abs(actual - float(recorded_mtime)) > 1.0:
                ok = False
                msgs.append(f"上一章正文在过闸后有改动（{prev_file}），需重跑门禁")
    if ok:
        msgs.append(f"上一章（第{prev}章）门禁已通过"
                    f"（checked_at: {state.get('checked_at', '?')}）")
        rhythm = state.get("rhythm")
        if isinstance(rhythm, dict):
            if rhythm.get("passed") is False:
                msgs.append(f"注意：上一章节奏配额检查未通过（fails={rhythm.get('fails')}），"
                            f"建议先处理")
            else:
                msgs.append("上一章节奏配额检查已通过")
    return ok, msgs


def deslop_score(text, words, whitelist):
    """v3.0 --deslop 模式：六级量化打分，输出轻/中/重分级建议。

    六级指标（每级 0-100，总分=加权平均）：
      1. 禁用词密度：禁用词命中数 / 千字
      2. 连续排比段数：连续出现否定排比/反序对比的段数
      3. 心理词占比：心理告知句式命中数 / 总句数
      4. 对话标签密度：对话标签（说/问/道）数 / 千字
      5. 平均段落句数：单段句数偏离理想区间（3-6句）
      6. 重复描写密度：复读句与微动作复读命中数 / 千字

    返回 (总分明细字典, 分级, 建议)。
    """
    non_ws, _ = count_chars(text)
    kilo = max(non_ws / 1000.0, 0.001)
    lines = text.splitlines()
    narration = strip_dialogue(text)

    # 1. 禁用词密度（叙述域）
    banned_count = 0
    for w in words:
        if w in whitelist:
            continue
        banned_count += narration.count(w)
    banned_density = banned_count / kilo
    score_banned = min(100.0, banned_density * 25.0)

    # 2. 连续排比段数
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    para_flags = []
    for p in paras:
        pn = strip_dialogue(p)
        if any(pat.search(pn) for pat, _, _ in TOXIC_PATTERNS[:4]):
            para_flags.append(1)
        else:
            para_flags.append(0)
    # 计算最长连续排比段
    max_run = 0
    run = 0
    for f in para_flags:
        if f:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    score_parallel = min(100.0, max_run * 30.0)

    # 3. 心理词占比
    gate_c_hits = scan_gate_c(lines)
    sents = [s for s in re.split(r"[。！？!?…]+", text) if s.strip()]
    total_sents = max(len(sents), 1)
    psych_ratio = len(gate_c_hits) / total_sents
    score_psych = min(100.0, psych_ratio * 500.0)

    # 4. 对话标签密度
    tag_count = 0
    for line in lines:
        if DIALOGUE_TAG_RE.search(line.strip()[-4:]):
            tag_count += 1
    tag_density = tag_count / kilo
    score_tag = min(100.0, tag_density * 20.0)

    # 5. 平均段落句数（偏离 3-6 句理想区间）
    para_sent_counts = []
    for p in paras:
        pn = strip_dialogue(p)
        ps = [s for s in re.split(r"[。！？!?…]+", pn) if s.strip()]
        para_sent_counts.append(len(ps))
    if para_sent_counts:
        avg_para_sent = sum(para_sent_counts) / len(para_sent_counts)
        # 偏离度：3-6 为理想，偏离越远分越高
        if avg_para_sent < 3:
            score_sent = min(100.0, (3 - avg_para_sent) * 40.0)
        elif avg_para_sent > 6:
            score_sent = min(100.0, (avg_para_sent - 6) * 25.0)
        else:
            score_sent = max(0.0, 20.0 - abs(avg_para_sent - 4.5) * 8.0)
    else:
        avg_para_sent = 0
        score_sent = 50.0

    # 6. 重复描写密度
    structure_hits = scan_structure(text)
    para_tics = scan_paragraph_tics(text)
    repeat_count = len(structure_hits) + len(para_tics)
    repeat_density = repeat_count / kilo
    score_repeat = min(100.0, repeat_density * 30.0)

    # 加权总分
    total = (score_banned * 0.25 + score_parallel * 0.15 + score_psych * 0.20
             + score_tag * 0.10 + score_sent * 0.15 + score_repeat * 0.15)

    if total < 30:
        level = "轻度"
        advice = "文风整体健康，保持现状。重点关注标记偏高的维度即可。"
    elif total < 60:
        level = "中度"
        advice = "存在明显 AI 腔倾向，建议针对偏高维度做一轮脱水改写。"
    else:
        level = "重度"
        advice = "AI 腔严重，强烈建议整章重写：删排比、拆长段、心理外化、对话标签多样化。"

    detail = {
        "banned_density": round(score_banned, 1),
        "parallel_streak": round(score_parallel, 1),
        "psych_ratio": round(score_psych, 1),
        "tag_density": round(score_tag, 1),
        "para_sent_dev": round(score_sent, 1),
        "repeat_density": round(score_repeat, 1),
        "total": round(total, 1),
        "level": level,
        "raw": {
            "banned_count": banned_count,
            "banned_per_kilo": round(banned_density, 2),
            "max_parallel_run": max_run,
            "psych_hits": len(gate_c_hits),
            "psych_ratio": round(psych_ratio, 4),
            "tag_count": tag_count,
            "tag_per_kilo": round(tag_density, 2),
            "avg_para_sent": round(avg_para_sent, 2),
            "repeat_count": repeat_count,
        },
    }
    return detail, level, advice


def print_deslop_report(text, words, whitelist):
    """输出 --deslop 六级量化打分报告。"""
    detail, level, advice = deslop_score(text, words, whitelist)
    sep = "=" * 16
    print(f"\n{sep} Deslop 六级量化打分 {sep}")
    print(f"  1. 禁用词密度   : {detail['banned_density']:>5.1f}/100"
          f"  （命中 {detail['raw']['banned_count']} 处，{detail['raw']['banned_per_kilo']}/千字）")
    print(f"  2. 连续排比段数 : {detail['parallel_streak']:>5.1f}/100"
          f"  （最长连排 {detail['raw']['max_parallel_run']} 段）")
    print(f"  3. 心理词占比   : {detail['psych_ratio']:>5.1f}/100"
          f"  （{detail['raw']['psych_hits']} 处 / {detail['raw']['psych_ratio']*100:.1f}% 句）")
    print(f"  4. 对话标签密度 : {detail['tag_density']:>5.1f}/100"
          f"  （{detail['raw']['tag_count']} 处，{detail['raw']['tag_per_kilo']}/千字）")
    print(f"  5. 平均段落句数 : {detail['para_sent_dev']:>5.1f}/100"
          f"  （平均 {detail['raw']['avg_para_sent']} 句/段，理想 3-6）")
    print(f"  6. 重复描写密度 : {detail['repeat_density']:>5.1f}/100"
          f"  （{detail['raw']['repeat_count']} 处）")
    print(f"  {'─'*44}")
    print(f"  加权总分       : {detail['total']:>5.1f}/100  [{level}]")
    print(f"  建议：{advice}")
    print(f"{sep}{sep}{sep}\n")
    return detail


def print_style_stats(text):
    """文风量化统计。优先使用 style_fingerprint 的六维逻辑，缺失时退回三维度。"""
    non_ws, _ = count_chars(text)
    if non_ws == 0:
        print("文风统计：文件为空")
        return
    if _HAS_SF:
        m = sf.compute_six_dimensions(text)
        pr = m["punct_rhythm"]
        sp = m["sentence_pattern"]
        print("文风统计（六维）：")
        print(f"  平均句长：{m['avg_sent_len']:.1f} 字")
        print(f"  对话占比：{m['dialogue_ratio']:.1f}%")
        print(f"  段落中位长度：{m['median_para_len']:.0f} 字（共 {len([p for p in text.splitlines() if p.strip()])} 段）")
        print(f"  标点节奏：？{pr['q']:.1f}% / ！{pr['e']:.1f}% / ……{pr['ellipsis']:.1f}%")
        print(f"  句式偏好：长短句交替比 {sp['alternation_ratio']:.2f}（短句 {sp['short_count']} / 长句 {sp['long_count']}）")
        if m["top_words"]:
            tw = "、".join(f"{w}({c})" for w, c in m["top_words"][:20])
            print(f"  高频词Top20：{tw}")
        return
    sents = [s for s in re.split(r"[。！？!?…]+", text) if s.strip()]
    avg_sent = non_ws / max(len(sents), 1)
    quotes = re.findall(r"「[^」]*」|“[^”]*”", text)
    dialogue = sum(len(re.sub(r"\s", "", q)) for q in quotes)
    paras = [len(re.sub(r"\s", "", p)) for p in text.splitlines() if p.strip()]
    median_para = statistics.median(paras) if paras else 0
    print(f"文风统计：平均句长 {avg_sent:.1f} 字 / 对话占比 {dialogue / non_ws * 100:.0f}% / "
          f"段落中位长度 {median_para:.0f} 字（共 {len(paras)} 段）")


def scan_degradation(text, words, whitelist):
    """v3.1 多维退化检测：从五个维度综合判断文本是否在退化。

    返回 [(rule_id, 标签, 证据说明)]。每个维度独立检测，可同时触发多个。
    比原有「禁用词 >3 次」退化检测更全面，覆盖句式/段落/情绪/动词四个新维度。
    """
    hits = []
    narration = strip_dialogue(text)
    non_ws_n = narration_len(text)
    lines = text.splitlines()

    # ① 禁用词退化：同一禁用词 >3 次（叙述域）
    for w in words:
        if w in whitelist:
            continue
        cnt = narration.count(w)
        if cnt > 3:
            hits.append(("degradation-banned", f"禁用词退化：「{w}」出现 {cnt} 次",
                         f"同一禁用词 >3 次（叙述域），疑似 AI 反复使用同一词"))

    # ② 句式退化：同一句首模式（前6字）≥4 句连排
    sents_in_narration = [s.strip() for s in re.split(r"[。！？!?…]+", narration) if s.strip()]
    if len(sents_in_narration) >= 4:
        prefixes = [s[:6] for s in sents_in_narration if len(s) >= 4]
        max_run = 0
        current_prefix = ""
        current_run = 0
        worst_prefix = ""
        for pfx in prefixes:
            if pfx == current_prefix:
                current_run += 1
                if current_run > max_run:
                    max_run = current_run
                    worst_prefix = current_prefix
            else:
                current_prefix = pfx
                current_run = 1
        if max_run >= 4:
            preview = worst_prefix if len(worst_prefix) <= 10 else worst_prefix[:10] + "..."
            hits.append(("degradation-syntax", f"句式退化：「{preview}」开头连排 {max_run} 句",
                         f"同一句首模式 ≥4 句连排，句式单调退化"))

    # ③ 段落退化：连续 ≥3 段长度差 ≤5 字（AI 排比段落典型特征）
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) >= 3:
        para_lens = [len(re.sub(r"\s", "", strip_dialogue(p))) for p in paras]
        max_para_run = 0
        current_para_run = 1
        for i in range(1, len(para_lens)):
            if abs(para_lens[i] - para_lens[i - 1]) <= 5:
                current_para_run += 1
                max_para_run = max(max_para_run, current_para_run)
            else:
                current_para_run = 1
        if max_para_run >= 3:
            hits.append(("degradation-paragraph", f"段落退化：连续 {max_para_run} 段长度差 ≤5 字",
                         f"AI 生成的排比段落长度过于均匀（连续 ≥3 段差 ≤5 字）"))

    # ④ 情绪词退化：同一情绪词在全章出现 ≥4 次
    emotion_counts = {}
    for w in EMOTION_WORDS:
        cnt = text.count(w)
        if cnt >= 4:
            emotion_counts[w] = cnt
    if emotion_counts:
        worst_emotion = max(emotion_counts, key=emotion_counts.get)
        worst_count = emotion_counts[worst_emotion]
        hits.append(("degradation-emotion", f"情绪词退化：「{worst_emotion}」出现 {worst_count} 次",
                     f"同一情绪词 ≥4 次（共 {len(emotion_counts)} 个情绪词超限），情绪泛化失焦"))

    # ⑤ 动词退化：同一动作动词在全章出现 ≥8 次
    action_counts = {}
    for verb in ["转身", "回头", "抬头", "低头", "看向", "看着", "盯着",
                 "走到", "坐下", "站起", "推开门", "走出", "深吸", "闭眼"]:
        cnt = narration.count(verb)
        if cnt >= 8:
            action_counts[verb] = cnt
    if action_counts:
        worst_verb = max(action_counts, key=action_counts.get)
        worst_v_count = action_counts[worst_verb]
        hits.append(("degradation-verb", f"动词退化：「{worst_verb}」出现 {worst_v_count} 次",
                     f"同一动作动词 ≥8 次（共 {len(action_counts)} 个动词超限），动作复读指纹"))

    return hits


def print_degradation_report(text, words, whitelist):
    """v3.1 --degradation 专项报告。"""
    hits = scan_degradation(text, words, whitelist)
    sep = "=" * 16
    print(f"\n{sep} 多维退化检测报告 v3.1 {sep}")
    if not hits:
        print("  未检测到退化模式（五维度全部通过）")
    else:
        print(f"  检测到 {len(hits)} 项退化：")
        for rule_id, label, evidence in hits:
            print(f"    [{rule_id}] {label}")
            print(f"        {evidence}")
    print(f"{sep}{sep}{sep}\n")
    return hits


def print_gate_report(text, lines, words, whitelist, non_ws):
    """输出 7 Gate + 扩充规则检测报告，返回 (统计字典)。"""
    banned_hits, toxic_hits = scan_lines(lines, words, whitelist)
    gate_c_hits = scan_gate_c(lines)
    blocking_hits = scan_blocking_patterns(lines)
    trailer_hits = scan_trailer(text)
    density_hits = scan_density(text, non_ws)
    structure_hits = scan_structure(text)
    para_tics_hits = scan_paragraph_tics(text)
    gate_f_hit, gate_f_phrases, ending_type, ending_preview = scan_gate_f(text)

    banned_blocking = [h for h in banned_hits if h[3] == "blocking"]
    banned_advisory = [h for h in banned_hits if h[3] == "advisory"]
    toxic_blocking = [h for h in toxic_hits if h[5] == "blocking"]
    toxic_advisory = [h for h in toxic_hits if h[5] == "advisory"]

    sep = "=" * 16
    print(f"\n{sep} 7 Gate 检测报告（叙述/对话分域 · blocking/advisory 分级）{sep}")

    # Gate A
    print("\n【Gate A 禁用词】")
    if whitelist:
        print(f"  白名单：已加载 {len(whitelist)} 词")
    if banned_hits:
        print(f"  命中 {len(banned_hits)} 处（叙述 {len(banned_blocking)} blocking / 对话 {len(banned_advisory)} advisory）：")
        for lineno, word, line, sev in banned_hits:
            preview = line if len(line) <= 60 else line[:57] + "..."
            print(f"    第{lineno}行 [{sev}] {word}")
            print(f"        {preview}")
    else:
        print("  命中 0 处")

    # Gate B
    print("\n【Gate B 毒句式】")
    if toxic_hits:
        print(f"  命中 {len(toxic_hits)} 处（叙述 {len(toxic_blocking)} blocking / 对话 {len(toxic_advisory)} advisory）：")
        for lineno, rule_id, label, match, line, sev in toxic_hits:
            preview = line if len(line) <= 60 else line[:57] + "..."
            print(f"    第{lineno}行 [{sev}] {label}：{match}")
            print(f"        {preview}")
    else:
        print("  命中 0 处")

    # Gate C
    print("\n【Gate C 心理告知】（叙述域机器候选，需人工确认）")
    if gate_c_hits:
        print(f"  候选 {len(gate_c_hits)} 处：")
        for lineno, label, match, line in gate_c_hits:
            preview = line if len(line) <= 60 else line[:57] + "..."
            print(f"    第{lineno}行 [{label}] {match}")
            print(f"        {preview}")
    else:
        print("  候选 0 处")

    # Gate G + 工程词 + 拒绝语
    print("\n【Gate G 解释腔 / 工程词泄漏 / 拒绝语】（blocking）")
    if blocking_hits:
        print(f"  命中 {len(blocking_hits)} 处：")
        for lineno, rule_id, label, match, line in blocking_hits:
            preview = line if len(line) <= 60 else line[:57] + "..."
            print(f"    第{lineno}行 [{label}] {match}")
            print(f"        {preview}")
    else:
        print("  命中 0 处")

    # 文末窗口
    print("\n【预告式收尾 / 章尾状态总结】（文末窗口 blocking）")
    if trailer_hits:
        for label, match in trailer_hits:
            print(f"    [{label}] {match}")
    else:
        print("  命中 0 处")

    # Gate F
    print("\n【Gate F 结尾升华】")
    print(f"  末段类型：{ending_type}")
    if ending_preview:
        print(f"  末段预览：{ending_preview}")
    if gate_f_hit:
        print(f"  [WARN] 末段含总结性语句：{'、'.join(gate_f_phrases)}")
        if ending_type == "感慨/总结":
            print("  → 建议改为动作/场景收尾，删掉总结性语句")
    else:
        print("  末段未检出总结性语句")

    # 密度/结构 advisory
    print("\n【密度检测】（advisory，人工判断）")
    if density_hits:
        for rule_id, label, evidence in density_hits:
            print(f"    [advisory] {label}")
            print(f"        {evidence}")
    else:
        print("  未触发")
    print("\n【结构检测】（advisory，人工判断）")
    if structure_hits:
        for rule_id, label, evidence in structure_hits:
            print(f"    [advisory] {label}")
            print(f"        {evidence}")
    else:
        print("  未触发")

    # v3.0 段落级 AI 模式检测
    print("\n【段落级 AI 模式检测】（advisory，人工判断）")
    if para_tics_hits:
        for rule_id, label, evidence in para_tics_hits:
            print(f"    [advisory] {label}")
            print(f"        {evidence}")
    else:
        print("  未触发")

    # 退化检测
    degradation = []
    for w in words:
        if w in whitelist:
            continue
        cnt = text.count(w)
        if cnt > 3:
            degradation.append((w, cnt))
    # v3.1 多维退化检测
    multi_degradation = scan_degradation(text, words, whitelist)
    print(f"\n{sep} 退化检测总结 {sep}")
    if degradation:
        degradation.sort(key=lambda x: -x[1])
        print(f"  出现 >3 次的禁用词（共 {len(degradation)} 个）：")
        for w, c in degradation:
            print(f"    [WARN] {w}：{c} 次（疑似 AI 反复使用同一词）")
    else:
        print("  无禁用词出现 >3 次")
    if multi_degradation:
        print(f"\n  多维退化检测（v3.1，共 {len(multi_degradation)} 项）：")
        for rule_id, label, evidence in multi_degradation:
            print(f"    [{rule_id}] {label}")
            print(f"        {evidence}")

    # 量化打分
    n_blocking = (len(banned_blocking) + len(toxic_blocking) + len(blocking_hits)
                  + len(trailer_hits))
    n_advisory = (len(banned_advisory) + len(toxic_advisory) + len(gate_c_hits)
                  + len(density_hits) + len(structure_hits) + len(para_tics_hits))
    kilo = non_ws / 1000.0
    weighted = (len(banned_blocking) * 2 + len(toxic_blocking) * 3
                + len(blocking_hits) * 3 + len(trailer_hits) * 3
                + len(gate_c_hits) * 1 + n_advisory * 1)
    per_kilo = weighted / kilo if kilo > 0 else 0.0
    ai_score = min(100.0, per_kilo)
    low_threshold = AI_SCORE_THRESHOLDS.get("low", 20)
    med_threshold = AI_SCORE_THRESHOLDS.get("medium", 40)
    level = "轻度" if ai_score < low_threshold else ("中度" if ai_score < med_threshold else "重度")
    print(f"\n{sep} 量化打分 {sep}")
    print(f"  blocking 命中 {n_blocking} 处 / advisory 命中 {n_advisory} 处")
    print(f"  加权 {weighted} / {kilo:.1f} 千字 → AI 味分数 {ai_score:.1f}/100（{level}）")
    print(f"  （0-{low_threshold} 轻度，{low_threshold}-{med_threshold} 中度，>{med_threshold} 重度）")
    print(f"{sep}{sep}{sep}\n")

    return {
        "banned_blocking": len(banned_blocking),
        "banned_advisory": len(banned_advisory),
        "toxic_blocking": len(toxic_blocking),
        "toxic_advisory": len(toxic_advisory),
        "gate_c": len(gate_c_hits),
        "gate_g_meta_refusal": len(blocking_hits),
        "trailer": len(trailer_hits),
        "density_advisory": len(density_hits),
        "structure_advisory": len(structure_hits),
        "para_tics_advisory": len(para_tics_hits),
        "gate_f": 1 if gate_f_hit else 0,
        "degradation_advisory": len(multi_degradation),
        "blocking": n_blocking,
        "advisory": n_advisory + len(multi_degradation),
        "ai_score": round(ai_score, 1),
    }


# ============================================================
# v3.2 增强：20种AI模式整合检测 + 段落重复度 + 跳过密度 + 退化指纹
# ============================================================

# --- 过渡词模板化检测 ---
TRANSITION_TIC_WORDS = [
    "然而", "不过", "但是", "与此同时", "就在这时",
    "话分两头", "另一边", "与此同时", "殊不知", "岂不知",
]
TRANSITION_TIC_PER_KILO = 5.0
TRANSITION_TIC_MIN_HITS = 4

# --- 信息倾倒检测 ---
INFO_DUMP_PATTERN = re.compile(
    r"(?:共.{1,6}大境界|分.{1,4}层|共有.{1,6}种|总计.{1,6}|"
    r"分别是.{10,}|依次为.{10,}|第一.{2,8}第二.{2,8}第三)"
)

# --- 巧合推进检测 ---
COINCIDENCE_PATTERN = re.compile(
    r"(?:恰好|凑巧|正好|偏偏|无独有偶|机缘巧合|就在此时|"
    r"恰在此时|恰巧|赶巧)"
)
COINCIDENCE_PER_KILO = 3.0
COINCIDENCE_MIN_HITS = 3

# --- 静态描写检测（无动作推进的纯描写段） ---
STATIC_DESC_PATTERN = re.compile(
    r"(?:天空|大地|山川|河流|建筑|街道|氛围|气息|光影|色彩)"
)
STATIC_DESC_MIN_CHARS = 150
STATIC_DESC_ACTION_RATIO = 0.1  # 动作词占比 < 10% 判为静态

# --- 句长单调检测 ---
SENT_LEN_MONOTONY_WINDOW = 10  # 连续10句句长方差 < 5 判为单调


def scan_ai_patterns(text, lines=None, words=None, whitelist=None):
    """v3.2 综合AI模式检测：整合20种AI写作模式，返回统一格式命中列表。

    整合已有检测器 + 新增4种模式，输出统一结构：
    [(rule_id, 标签, 证据说明, severity)]

    severity: "blocking" / "advisory"
    """
    if lines is None:
        lines = text.splitlines()
    if words is None:
        words = BANNED_WORDS
    whitelist = whitelist or set()
    non_ws = len(re.sub(r"\s", "", text))
    kilo = max(non_ws / 1000.0, 0.001)

    hits = []

    # === 已有检测器整合 ===

    # 1. 禁用词命中（blocking）
    banned, toxic = scan_lines(lines, words, whitelist)
    if banned:
        hits.append(("ai-banned-words", f"禁用词命中 {len(banned)} 处",
                     f"命中词: {', '.join(set(b[1] for b in banned[:5]))}",
                     "blocking"))

    # 2. 毒句式（blocking）
    if toxic:
        hits.append(("ai-toxic-syntax", f"毒句式命中 {len(toxic)} 处",
                     f"句式: {', '.join(set(t[2] for t in toxic[:3]))}",
                     "blocking"))

    # 3. 解释腔（blocking）
    gate_g = scan_blocking_patterns(lines)
    if gate_g:
        hits.append(("ai-explainer-tone", f"解释腔命中 {len(gate_g)} 处",
                     "上帝视角剧透/解释因果/叙述者定性",
                     "blocking"))

    # 4. 拒绝语（blocking）
    refusal_hits = [h for h in gate_g if h[1] == "refusal-tone"]
    if refusal_hits:
        hits.append(("ai-refusal-tone", f"AI助手身份残留 {len(refusal_hits)} 处",
                     "AI拒绝语或身份声明残留", "blocking"))

    # 5. 心理告知（advisory）
    gate_c = scan_gate_c(lines)
    if gate_c:
        hits.append(("ai-psych-telling", f"心理告知命中 {len(gate_c)} 处",
                     "直接陈述情绪而非展示", "advisory"))

    # 6. 预告式收尾（blocking）
    trailer = scan_trailer(text)
    if trailer:
        hits.append(("ai-trailer-ending", f"预告式收尾 {len(trailer)} 处",
                     "「才刚刚开始」类预告句式", "blocking"))

    # 7. 密度型检测（advisory）
    density = scan_density(text, non_ws)
    density_map = {
        "abstract-summary-tic": ("ai-abstract-summary", "抽象总结密度过高"),
        "micro-action-tic": ("ai-micro-action", "微动作复读密度过高"),
        "metaphor-density-tic": ("ai-metaphor-density", "比喻密度过高"),
        "reasoning-chain-tic": ("ai-reasoning-chain", "解释链密度过高"),
        "quote-emphasis-tic": ("ai-quote-emphasis", "引号强调滥用"),
    }
    for d in density:
        rule_id = d[0]
        if rule_id in density_map:
            ai_id, label = density_map[rule_id]
            hits.append((ai_id, label, d[2], "advisory"))

    # 8. 结构型检测（advisory）
    struct = scan_structure(text)
    struct_map = {
        "long-paragraph": ("ai-long-paragraph", "长段落"),
        "period-stutter": ("ai-period-stutter", "碎句号电报体"),
        "action-list-tic": ("ai-action-list", "动作清单"),
        "repeat-sentence": ("ai-repeat-sentence", "复读句"),
        "truncation": ("ai-truncation", "结尾疑似截断"),
    }
    for s in struct:
        rule_id = s[0]
        if rule_id in struct_map:
            ai_id, label = struct_map[rule_id]
            hits.append((ai_id, label, s[2], "advisory"))

    # 9. 段落级检测（advisory）
    para_tics = scan_paragraph_tics(text)
    para_map = {
        "causal-chain-tic": ("ai-causal-chain", "因果链密度过高"),
        "formula-density": ("ai-formula-density", "套词密度过高"),
        "action-sent-list": ("ai-action-list-para", "段落级动作清单"),
    }
    for p in para_tics:
        rule_id = p[0]
        if rule_id in para_map:
            ai_id, label = para_map[rule_id]
            hits.append((ai_id, label, p[2], "advisory"))

    # === 新增检测器 ===

    # 10. 过渡词模板化（advisory）
    transition_count = 0
    transition_words_hit = set()
    for line in lines:
        for w in TRANSITION_TIC_WORDS:
            cnt = line.count(w)
            if cnt > 0:
                transition_count += cnt
                transition_words_hit.add(w)
    if transition_count >= TRANSITION_TIC_MIN_HITS or \
       transition_count / kilo >= TRANSITION_TIC_PER_KILO:
        hits.append(("ai-transition-tic",
                     f"过渡词模板化 {transition_count} 处",
                     f"高频过渡词: {', '.join(sorted(transition_words_hit)[:5])}",
                     "advisory"))

    # 11. 信息倾倒（advisory）
    info_dumps = INFO_DUMP_PATTERN.findall(text)
    if info_dumps:
        hits.append(("ai-info-dump",
                     f"信息倾倒 {len(info_dumps)} 处",
                     "大段设定/数值/分类直接灌入正文",
                     "advisory"))

    # 12. 巧合推进（advisory）
    coincidences = COINCIDENCE_PATTERN.findall(text)
    if len(coincidences) >= COINCIDENCE_MIN_HITS or \
       len(coincidences) / kilo >= COINCIDENCE_PER_KILO:
        hits.append(("ai-coincidence",
                     f"巧合推进 {len(coincidences)} 处",
                     "过多使用「恰好/凑巧/偏偏」推进剧情",
                     "advisory"))

    # 13. 句长单调（advisory）
    sents = [len(re.sub(r"\s", "", s)) for s in re.split(r"[。！？!?…]+", text) if s.strip()]
    if len(sents) >= SENT_LEN_MONOTONY_WINDOW:
        # 检查滑动窗口
        for i in range(len(sents) - SENT_LEN_MONOTONY_WINDOW + 1):
            window = sents[i:i + SENT_LEN_MONOTONY_WINDOW]
            if max(window) - min(window) <= 5 and max(window) > 0:
                hits.append(("ai-sent-len-monotony",
                             f"句长单调（连续{SENT_LEN_MONOTONY_WINDOW}句方差极小）",
                             f"句长范围 {min(window)}-{max(window)} 字",
                             "advisory"))
                break

    # 14. 静态描写过多（advisory）
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    static_count = 0
    for para in paras:
        para_chars = len(re.sub(r"\s", "", para))
        if para_chars >= STATIC_DESC_MIN_CHARS:
            static_hits = len(STATIC_DESC_PATTERN.findall(para))
            action_hits = len(ACTION_LIST_VERBS.findall(para))
            if static_hits >= 2 and action_hits / max(para_chars / 10, 1) < STATIC_DESC_ACTION_RATIO:
                static_count += 1
    if static_count >= 2:
        hits.append(("ai-static-description",
                     f"静态描写段 {static_count} 处",
                     "无动作推进的纯环境/氛围描写过多",
                     "advisory"))

    # 15. 对话标签单一（advisory）
    tag_matches = DIALOGUE_TAG_RE.findall(text)
    if tag_matches:
        unique_tags = set(t.strip() for t in tag_matches if t.strip())
        if len(tag_matches) >= 8 and len(unique_tags) <= 2:
            hits.append(("ai-tag-monotony",
                         f"对话标签单一（{len(tag_matches)}处仅用{len(unique_tags)}种）",
                         f"重复标签: {', '.join(sorted(unique_tags))}",
                         "advisory"))

    # 16. 段落节奏均一（advisory）
    para_lens = [len(re.sub(r"\s", "", p)) for p in paras if p.strip()]
    if len(para_lens) >= 6:
        avg_len = sum(para_lens) / len(para_lens)
        deviation = sum(abs(l - avg_len) for l in para_lens) / len(para_lens)
        if deviation < avg_len * 0.15 and avg_len > 20:
            hits.append(("ai-para-rhythm-uniform",
                         f"段落节奏均一（平均偏差 {deviation:.0f} 字）",
                         f"平均段落 {avg_len:.0f} 字，偏差仅 {deviation/avg_len*100:.0f}%",
                         "advisory"))

    # 17. 跳过密度（advisory）
    skip_result = scan_skip_density(text, non_ws)
    if skip_result["is_skipping"]:
        hits.append(("ai-skip-density",
                     f"跳过密度过高（{skip_result['scene_jumps']}处场景跳转）",
                     skip_result["evidence"],
                     "advisory"))

    # 18. 段落重复度（advisory）
    rep_result = scan_paragraph_repetition(text)
    if rep_result["has_repetition"]:
        hits.append(("ai-paragraph-repetition",
                     f"跨段落重复（{rep_result['repeated_count']}对）",
                     rep_result["evidence"],
                     "advisory"))

    # 19. 情绪标签直接陈述（advisory，与心理告知互补）
    emotion_labels = re.findall(
        r"(?:他|她|它|这|那)(?:感到了|觉得|感到|感觉到)([^\s，。！？]{2,6})",
        text
    )
    if len(emotion_labels) >= 3:
        hits.append(("ai-emotion-labeling",
                     f"情绪标签直接陈述 {len(emotion_labels)} 处",
                     f"标签词: {', '.join(set(emotion_labels[:5]))}",
                     "advisory"))

    # 20. 镜像场景检测（advisory）
    mirror_count = 0
    for i, para in enumerate(paras):
        if i + 1 < len(paras):
            p1_chars = set(re.sub(r"\s", "", para))
            p2_chars = set(re.sub(r"\s", "", paras[i + 1]))
            if p1_chars and p2_chars:
                overlap = len(p1_chars & p2_chars) / len(p1_chars | p2_chars)
                if overlap > 0.7:
                    mirror_count += 1
    if mirror_count >= 2:
        hits.append(("ai-mirror-scene",
                     f"镜像场景 {mirror_count} 对",
                     "相邻段落用词高度重叠，疑似AI对称结构",
                     "advisory"))

    return hits


def scan_paragraph_repetition(text):
    """v3.2 跨段落重复度检测。

    检测不同段落之间是否存在高度相似的句式或用词，
    超越 scan_structure 中的单句复读，捕捉段落级的模式重复。

    Returns:
        dict: {
            "has_repetition": bool,
            "repeated_count": int,
            "pairs": [(idx1, idx2, similarity)],
            "evidence": str,
        }
    """
    paras = [re.sub(r"\s", "", p) for p in re.split(r"\n\s*\n", text) if p.strip()]
    pairs = []

    for i in range(len(paras)):
        for j in range(i + 1, min(i + 5, len(paras))):  # 只比相邻5段
            p1, p2 = paras[i], paras[j]
            if len(p1) < 15 or len(p2) < 15:
                continue

            # 方法1: 字符集重叠度
            s1, s2 = set(p1), set(p2)
            if not s1 or not s2:
                continue
            char_overlap = len(s1 & s2) / len(s1 | s2)

            # 方法2: 句首模式重复（前4字）
            prefix1 = p1[:4] if len(p1) >= 4 else p1
            prefix2 = p2[:4] if len(p2) >= 4 else p2
            prefix_match = prefix1 == prefix2 and len(prefix1) >= 3

            # 方法3: N-gram 重叠
            ngrams1 = set(p1[k:k+3] for k in range(len(p1) - 2))
            ngrams2 = set(p2[k:k+3] for k in range(len(p2) - 2))
            if ngrams1 and ngrams2:
                ngram_overlap = len(ngrams1 & ngrams2) / len(ngrams1 | ngrams2)
            else:
                ngram_overlap = 0

            similarity = max(char_overlap, ngram_overlap)
            if similarity > 0.6 or prefix_match:
                pairs.append((i, j, round(similarity, 2)))

    repeated_count = len(pairs)
    has_repetition = repeated_count >= 2

    if has_repetition:
        evidence_parts = [f"段{p[0]+1}↔段{p[1]+1}({p[2]:.0%})" for p in pairs[:3]]
        evidence = f"重复段落对: {'; '.join(evidence_parts)}"
    else:
        evidence = ""

    return {
        "has_repetition": has_repetition,
        "repeated_count": repeated_count,
        "pairs": pairs,
        "evidence": evidence,
    }


def scan_skip_density(text, non_ws):
    """v3.2 跳过密度检测：检测事件推进过快（叙述跳过太多细节）。

    指标：
    1. 场景跳转标记密度（——/※/★/---/分割线）
    2. 时间压缩标记密度（几天后/数日后/转眼/不久后/一个月后）
    3. 对话占比过高（>60%时可能缺乏叙述铺垫）
    4. 平均段落长度过短（<30字时可能信息密度过低）

    Returns:
        dict: {
            "is_skipping": bool,
            "scene_jumps": int,
            "time_compressors": int,
            "dialogue_ratio": float,
            "avg_para_len": float,
            "evidence": str,
        }
    """
    kilo = max(non_ws / 1000.0, 0.001)

    # 场景跳转标记
    scene_markers = re.findall(r"(?:^---+$|^※|^★|^◇|^[＝=]{3,}|^-{3,})", text, re.MULTILINE)
    scene_jumps = len(scene_markers)

    # 时间压缩标记
    time_patterns = re.findall(
        r"(?:几天后|数日后|转眼|不久后|一个月后|数月后|半年后|一年后|"
        r"第二天|几天之后|数周后|半年之后|时光飞逝|日子一天天过去)",
        text
    )
    time_compressors = len(time_patterns)

    # 对话占比
    quotes = re.findall(r"「[^」]*」|\"[^\"]*\"", text)
    dialogue_chars = sum(len(re.sub(r"\s", "", q)) for q in quotes)
    dialogue_ratio = dialogue_chars / non_ws * 100 if non_ws else 0

    # 平均段落长度
    paras = [len(re.sub(r"\s", "", p)) for p in text.splitlines() if p.strip()]
    avg_para_len = sum(paras) / len(paras) if paras else 0

    # 判定：场景跳转 ≥3 且时间压缩 ≥2，或对话占比 >65% 且平均段落 <25
    is_skipping = (scene_jumps >= 3 and time_compressors >= 2) or \
                  (dialogue_ratio > 65 and avg_para_len < 25 and non_ws > 500)

    evidence_parts = []
    if scene_jumps:
        evidence_parts.append(f"场景跳转{scene_jumps}处")
    if time_compressors:
        evidence_parts.append(f"时间压缩{time_compressors}处")
    if dialogue_ratio > 50:
        evidence_parts.append(f"对话占比{dialogue_ratio:.0f}%")
    if avg_para_len < 30 and paras:
        evidence_parts.append(f"平均段落{avg_para_len:.0f}字")

    return {
        "is_skipping": is_skipping,
        "scene_jumps": scene_jumps,
        "time_compressors": time_compressors,
        "dialogue_ratio": round(dialogue_ratio, 1),
        "avg_para_len": round(avg_para_len, 1),
        "evidence": "；".join(evidence_parts) if evidence_parts else "",
    }


def degradation_fingerprint(degradation_hits, ai_hits=None):
    """v3.2 退化指纹生成：将退化检测结果编码为可追踪的指纹字符串。

    用于跨章节追踪退化趋势：相同指纹反复出现说明作者未改进。

    Args:
        degradation_hits: scan_degradation() 返回的命中列表
        ai_hits: scan_ai_patterns() 返回的命中列表（可选）

    Returns:
        dict: {
            "fingerprint": str,       # 退化指纹（如 "D:B2,S1,P0,E0,V3"）
            "ai_fingerprint": str,    # AI模式指纹（如 "A:B3,T1,P2"）
            "combined_hash": str,     # 组合哈希（前8位）
            "severity": str,          # "clean" / "light" / "moderate" / "severe"
            "categories": list,       # 触发的类别列表
        }
    """
    # 退化指纹：D:B{n},S{n},P{n},E{n},V{n}
    # B=banned, S=syntax, P=paragraph, E=emotion, V=verb
    deg_counts = {"B": 0, "S": 0, "P": 0, "E": 0, "V": 0}
    deg_map = {
        "degradation-banned": "B",
        "degradation-syntax": "S",
        "degradation-paragraph": "P",
        "degradation-emotion": "E",
        "degradation-verb": "V",
    }
    for h in degradation_hits:
        rule_id = h[0] if isinstance(h, (list, tuple)) else h
        if rule_id in deg_map:
            deg_counts[deg_map[rule_id]] += 1

    fingerprint = f"D:{','.join(f'{k}{v}' for k, v in deg_counts.items())}"

    # AI模式指纹
    ai_counts = {}
    ai_categories = []
    if ai_hits:
        for h in ai_hits:
            rule_id = h[0]
            severity = h[3] if len(h) > 3 else "advisory"
            prefix = "B" if severity == "blocking" else "A"
            short = rule_id.replace("ai-", "")[:3].upper()
            key = f"{prefix}:{short}"
            ai_counts[key] = ai_counts.get(key, 0) + 1
            if rule_id not in ai_categories:
                ai_categories.append(rule_id)

    ai_fingerprint = " ".join(f"{k}({v})" for k, v in sorted(ai_counts.items()))

    # 组合哈希
    combined = fingerprint + "|" + ai_fingerprint
    combined_hash = hashlib.md5(combined.encode("utf-8")).hexdigest()[:8]

    # 严重度判定
    total_deg = sum(deg_counts.values())
    total_blocking = sum(1 for h in (ai_hits or []) if len(h) > 3 and h[3] == "blocking")
    total_advisory = sum(1 for h in (ai_hits or []) if len(h) > 3 and h[3] == "advisory")

    if total_blocking >= 3 or total_deg >= 4:
        severity = "severe"
    elif total_blocking >= 1 or total_deg >= 2 or total_advisory >= 5:
        severity = "moderate"
    elif total_deg >= 1 or total_advisory >= 2:
        severity = "light"
    else:
        severity = "clean"

    return {
        "fingerprint": fingerprint,
        "ai_fingerprint": ai_fingerprint or "A:none",
        "combined_hash": combined_hash,
        "severity": severity,
        "categories": ai_categories,
    }


def print_ai_pattern_report(text, lines=None, words=None, whitelist=None):
    """v3.2 输出20种AI模式检测报告。"""
    if lines is None:
        lines = text.splitlines()
    hits = scan_ai_patterns(text, lines, words, whitelist)

    print(f"\n{'='*60}")
    print(f"  AI模式检测报告（20种模式整合扫描）")
    print(f"{'='*60}")

    if not hits:
        print("  ✓ 未检测到AI写作模式")
        print(f"{'='*60}")
        return {"total": 0, "blocking": 0, "advisory": 0}

    blocking = [h for h in hits if h[3] == "blocking"]
    advisory = [h for h in hits if h[3] == "advisory"]

    print(f"\n  命中统计：{len(hits)} 项（blocking {len(blocking)} / advisory {len(advisory)}）")
    print(f"  {'─'*56}")

    for h in hits:
        rule_id, label, evidence, severity = h
        icon = "✗" if severity == "blocking" else "△"
        print(f"  {icon} [{rule_id}] {label}")
        if evidence:
            print(f"      → {evidence}")

    print(f"{'='*60}")

    return {
        "total": len(hits),
        "blocking": len(blocking),
        "advisory": len(advisory),
    }


def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="章节机械闸口 v3.0：字数 + 禁用词 + 毒句式 + 7 Gate + 扩充规则 + 伏笔超期 + 门禁落盘 + 段落级AI模式检测 + deslop量化打分")
    ap.add_argument("file", help="章节正文文件路径（UTF-8）")
    ap.add_argument("--min-chars", type=int, default=0, help="字数下限（按非空白字符数，默认不检查）")
    ap.add_argument("--max-chars", type=int, default=0, help="字数上限（默认不检查）")
    ap.add_argument("--extra-words", default=None, help="追加禁用词表（每行一个词，# 开头为注释，! 前缀为豁免词）")
    ap.add_argument("--no-auto-words", action="store_true", help="禁用 正文/设定 目录词表的自动加载")
    ap.add_argument("--ledger", default=None, help="伏笔台账路径（配合 --current-chapter 检查超期）")
    ap.add_argument("--current-chapter", type=int, default=0, help="当前章号（检查伏笔超期/门禁落盘时必填）")
    ap.add_argument("--style-stats", action="store_true", help="输出六维文风量化统计（不影响通过判定）")
    ap.add_argument("--gate-report", action="store_true", help="输出 7 Gate + 扩充规则检测报告")
    ap.add_argument("--deslop", action="store_true",
                    help="输出六级量化打分（禁用词密度/连续排比/心理词占比/对话标签密度/段落句数/重复描写），轻/中/重分级")
    ap.add_argument("--degradation", action="store_true",
                    help="v3.1 输出多维退化检测专项报告（禁用词/句式/段落/情绪/动词五维度）")
    ap.add_argument("--ai-patterns", action="store_true",
                    help="v3.2 输出20种AI模式整合检测报告（含段落重复度/跳过密度/退化指纹）")
    ap.add_argument("--whitelist", default=None,
                    help="白名单文件路径（每行一个豁免词，# 注释）；设定/禁用词.txt 中 ! 前缀的行也会自动加入")
    ap.add_argument("--fail-on", choices=["blocking", "all"], default="blocking",
                    help="未通过口径：blocking=只计确定性命中（默认）；all=advisory 也计入")
    ap.add_argument("--gate-state", action="store_true",
                    help="把本次检查结果写入 追踪/门禁/gate_ch{N}.json（需 --current-chapter 或文件名含章号）")
    ap.add_argument("--verify-prev", action="store_true",
                    help="写本章前查验上一章门禁状态（欠账门；需 --current-chapter 或文件名含章号）")
    args = ap.parse_args()

    try:
        with open(args.file, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        print(f"错误：无法读取文件 {args.file}: {e}", file=sys.stderr)
        return 2

    # 章号解析（--verify-prev / --gate-state 需要）
    chapter_no = args.current_chapter or extract_chapter_number(args.file)

    # 欠账门：写本章前查验上一章
    if args.verify_prev:
        if not chapter_no:
            print("错误：--verify-prev 需要 --current-chapter 或文件名含「第XXX章」", file=sys.stderr)
            return 2
        ok, msgs = verify_prev_gate(args.file, chapter_no)
        print("欠账门查验（上一章门禁状态）：")
        for m in msgs:
            print(f"  {'[OK]' if ok else '[FAIL]'} {m}")
        if not ok:
            print("\n结果：未通过（欠账未清，禁止开写本章）")
            return 1
        print()

    # 豁免标记
    if has_skip_marker(text):
        print(f"检测到豁免标记 {SKIP_MARKER}，整章跳过扫描（作者显式豁免）")
        if args.gate_state and chapter_no:
            path = write_gate_state(args.file, chapter_no, {
                "passed": True, "blocking": 0, "advisory": 0, "ai_score": 0.0,
                "categories": {"skipped": 1},
            })
            print(f"门禁状态已写入：{path}")
        print("结果：通过（豁免）")
        return 0

    # 汇总禁用词表：内置 + 自动发现 + 显式指定
    words = list(BANNED_WORDS)
    wordlists = [] if args.no_auto_words else auto_wordlists(args.file)
    if args.extra_words:
        wordlists.append(args.extra_words)
    # v3.0：从词表加载的豁免词集合
    exemptions = set()
    for wl in wordlists:
        try:
            wl_words, wl_exemptions = load_wordlist(wl)
            words += wl_words
            exemptions |= wl_exemptions
            if wl_exemptions:
                print(f"已加载词表：{wl}（禁用词 {len(wl_words)}，豁免词 {len(wl_exemptions)}）")
            else:
                print(f"已加载词表：{wl}")
        except OSError as e:
            print(f"错误：无法读取词表 {wl}: {e}", file=sys.stderr)
            return 2

    # 白名单：v3.0 支持 --whitelist 显式指定 + 设定/禁用词.txt 中 ! 前缀 + 工程根 .deslop-whitelist
    whitelist = set(exemptions)
    wl_path = find_whitelist(args.file)
    if wl_path:
        try:
            whitelist |= load_whitelist(wl_path)
            print(f"已加载白名单：{wl_path}（{len(whitelist)} 词）")
        except OSError as e:
            print(f"警告：无法读取白名单 {wl_path}: {e}", file=sys.stderr)
    if args.whitelist:
        try:
            whitelist |= load_whitelist(args.whitelist)
            print(f"已加载白名单：{args.whitelist}（合并后 {len(whitelist)} 词）")
        except OSError as e:
            print(f"错误：无法读取白名单 {args.whitelist}: {e}", file=sys.stderr)
            return 2

    # 去重禁用词（保留顺序）
    seen = set()
    dedup_words = []
    for w in words:
        if w not in seen:
            seen.add(w)
            dedup_words.append(w)
    words = dedup_words

    non_ws, cjk = count_chars(text)
    print(f"字数：{non_ws}（非空白字符）/ {cjk}（汉字）")
    if args.style_stats:
        print_style_stats(text)

    # v3.0 --deslop 模式：六级量化打分
    if args.deslop:
        deslop_detail = print_deslop_report(text, words, whitelist)

    # v3.1 --degradation 模式：多维退化检测
    if args.degradation:
        print_degradation_report(text, words, whitelist)

    if args.ai_patterns:
        print_ai_pattern_report(text, lines, words, whitelist)
        # 退化指纹
        deg_hits = scan_degradation(text, words, whitelist)
        ai_hits = scan_ai_patterns(text, lines, words, whitelist)
        fp = degradation_fingerprint(deg_hits, ai_hits)
        print(f"\n  退化指纹: {fp['fingerprint']}")
        print(f"  AI指纹:   {fp['ai_fingerprint']}")
        print(f"  组合哈希: {fp['combined_hash']}")
        print(f"  严重度:   {fp['severity']}")

    failed = False
    stats = {"blocking": 0, "advisory": 0, "ai_score": 0.0, "categories": {}}

    if args.min_chars and non_ws < args.min_chars:
        print(f"[FAIL] 字数不足：{non_ws} < 下限 {args.min_chars}")
        failed = True
    if args.max_chars and non_ws > args.max_chars:
        print(f"[FAIL] 字数超限：{non_ws} > 上限 {args.max_chars}")
        failed = True

    lines = text.splitlines()

    if args.gate_report:
        stats = print_gate_report(text, lines, words, whitelist, non_ws)
        if stats["blocking"]:
            failed = True
        if args.fail_on == "all" and stats["advisory"]:
            failed = True
    else:
        banned_hits, toxic_hits = scan_lines(lines, words, whitelist)
        blocking_hits = scan_blocking_patterns(lines)
        trailer_hits = scan_trailer(text)
        hits = ([(ln, "禁用词", w, line, sev) for ln, w, line, sev in banned_hits]
                + [(ln, "毒句式", f"{label}: {match}", line, sev)
                   for ln, _, label, match, line, sev in toxic_hits]
                + [(ln, "解释腔/工程词/拒绝语", f"{label}: {match}", line, "blocking")
                   for ln, _, label, match, line in blocking_hits]
                + [(0, "文末窗口", f"{label}: {match}", "", "blocking")
                   for label, match in trailer_hits])
        if hits:
            n_blocking = sum(1 for h in hits if h[4] == "blocking")
            if n_blocking:
                failed = True
            if args.fail_on == "all" and len(hits) > n_blocking:
                failed = True
            print(f"\n命中 {len(hits)} 处（blocking {n_blocking} / advisory {len(hits) - n_blocking}，需人工改写）：")
            for lineno, kind, word, line, sev in hits:
                loc = f"第{lineno}行" if lineno else "文末"
                preview = line if len(line) <= 60 else line[:57] + "..."
                print(f"  {loc} [{sev}] [{kind}] {word}\n      {preview}")
            stats = {"blocking": n_blocking, "advisory": len(hits) - n_blocking,
                     "ai_score": 0.0, "categories": {}}

    if args.ledger:
        if not chapter_no:
            print("错误：--ledger 需配合 --current-chapter 使用", file=sys.stderr)
            return 2
        try:
            fails, warns = check_ledger(args.ledger, chapter_no)
        except OSError as e:
            print(f"错误：无法读取台账 {args.ledger}: {e}", file=sys.stderr)
            return 2
        for w in warns:
            print(f"[WARN] 伏笔临近回收窗口：{w}")
        if fails:
            failed = True
            print(f"\n伏笔超期 {len(fails)} 项（需处理后开写下一章）：")
            for item in fails:
                print(f"  [FAIL] {item}")

    # 门禁状态落盘
    if args.gate_state:
        if not chapter_no:
            print("错误：--gate-state 需要 --current-chapter 或文件名含「第XXX章」", file=sys.stderr)
            return 2
        path = write_gate_state(args.file, chapter_no, {
            "passed": not failed,
            "blocking": stats.get("blocking", 0),
            "advisory": stats.get("advisory", 0),
            "ai_score": stats.get("ai_score", 0.0),
            "categories": {k: v for k, v in stats.items()
                           if k not in ("blocking", "advisory", "ai_score", "categories")},
        })
        print(f"门禁状态已写入：{path}")

    if failed:
        print("\n结果：未通过")
        return 1
    print("结果：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
