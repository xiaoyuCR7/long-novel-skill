#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""research_agent.py — 联网调研调度器 v1.0（纯标准库，无第三方依赖）。

题材-调研维度映射 + 搜索关键词生成 + 知识库缺口检测 + 调研结果结构化存储。

功能：
  1. 题材-调研维度映射：22 题材卡各对应一组调研维度，按题材自动补全
  2. 生成搜索关键词列表：按题材 + 主题生成结构化搜索词
  3. 知识库缺口检测：已有参考资料 vs 需要调研的维度，输出缺口清单
  4. 调研结果结构化存储：按维度分类存入 `参考资料/` 目录
  5. 调研日志记录：每次调研写入 `参考资料/调研日志.md`
  6. 与题材卡协作：题材卡已覆盖的维度标记为「已覆盖」，不重复调研

子命令：
  keywords    按题材+主题生成搜索关键词列表
  gaps        检测知识库缺口（已有 vs 需要）
  store       将调研结果结构化存储到参考资料目录
  plan        生成调研计划（含缺口 + 关键词 + 优先级）

用法：
  python scripts/research_agent.py keywords --genre 玄幻 --topic "炼丹体系"
  python scripts/research_agent.py gaps "{书名目录}"
  python scripts/research_agent.py store "{书名目录}" --dimension 世界观 --source "搜索结果文本"
  python scripts/research_agent.py plan "{书名目录}" --depth standard

退出码：0 = 通过；1 = 错误；2 = 参数错误。
"""

import argparse
import datetime
import json
import os
import re
import sys
import textwrap

# Windows 中文控制台兼容
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# ============================================================================
# 题材-调研维度映射
# 每类题材对应一组需要调研的知识维度。
# 维度定义：维度名 → 调研重点（一句话说明调研什么）
# ============================================================================

GENRE_RESEARCH_DIMENSIONS = {
    "xuanhuan-xiuxian": {
        "dimensions": {
            "修炼体系": "境界划分、功法等级、灵根/灵脉体系、丹药/法宝/符箓体系",
            "世界观架构": "大陆/界域分布、宗门/势力结构、上古遗迹/秘境设定",
            "战斗规范": "同境界战力对比、越级战斗的代价与限制、法宝/阵法在战斗中的使用规则",
            "资源体系": "灵石/灵药/材料的产出与流通、坊市/拍卖行的定价逻辑",
            "文化参照": "道家/佛家典籍中的修炼术语、古代神话中的神兽/法宝原型",
            "成长路径": "从凡人到顶峰的典型升级路径、各阶段的标志性事件与时长",
        },
        "search_prefixes": ["玄幻 修炼体系", "仙侠 境界划分", "修真 功法体系", "东方玄幻 世界观"],
    },
    "dushi": {
        "dimensions": {
            "都市背景": "目标城市的真实地理/商圈/交通/社区结构",
            "行业知识": "角色职业相关的行业运作规则、术语、薪资水平",
            "社会规则": "阶层差异、社交礼仪、职场/商场/官场规则",
            "科技装备": "相关科技产品的功能、价格、使用场景",
            "法律框架": "与剧情相关的法律条文、执法流程、灰色地带",
        },
        "search_prefixes": ["都市 行业知识", "现代都市 社会规则", "职场 行业术语"],
    },
    "dushi-naodong": {
        "dimensions": {
            "都市背景": "目标城市的真实地理/商圈/交通/社区结构",
            "系统设计": "同类系统流作品的系统设定模式、任务/奖励/商城机制",
            "行业知识": "角色职业相关的行业运作规则",
            "脑洞参照": "同类脑洞文的创新点与读者反馈",
            "科技/超自然": "金手指涉及的科学原理或超自然设定参考",
        },
        "search_prefixes": ["系统流 都市", "脑洞文 金手指", "签到流 系统设计"],
    },
    "lishi": {
        "dimensions": {
            "历史背景": "目标朝代的政治制度、官制、军制、科举/选官",
            "社会经济": "农业/商业/手工业状况、货币体系、税收制度",
            "日常生活": "衣食住行、节庆习俗、娱乐方式、称谓礼仪",
            "地理军事": "行政区划、军事要塞、交通路线、战争技术",
            "文化思想": "主流思想流派、文学艺术、科技发展水平",
            "关键人物": "该时期的重要历史人物及其事迹（用于架空参考）",
        },
        "search_prefixes": ["历史 朝代制度", "古代 社会生活", "历史 军事地理"],
    },
    "yanqing": {
        "dimensions": {
            "情感心理": "现代恋爱心理学知识、两性关系中的常见模式与冲突",
            "行业背景": "男女主角职业相关的行业知识",
            "社交场景": "约会/聚会/职场社交的真实场景与礼仪",
            "都市生活": "目标城市的真实生活细节（消费/交通/娱乐）",
            "甜宠/虐恋模式": "同类作品的常见情节模式与读者爽点",
        },
        "search_prefixes": ["言情 恋爱心理", "甜宠 情节设计", "现代言情 行业背景"],
    },
    "guyan": {
        "dimensions": {
            "古代制度": "目标朝代的政治制度、后宫/世家/贵族体系",
            "古代生活": "服饰/饮食/居住/出行/礼仪/节庆",
            "婚嫁制度": "古代婚姻制度、聘礼/嫁妆、妻妾/嫡庶规则",
            "经济文化": "商业/手工业/田产/货币/文学艺术",
            "女性处境": "该时期女性的社会地位、教育、职业可能",
        },
        "search_prefixes": ["古言 古代制度", "古代言情 世家", "古代 婚嫁制度"],
    },
    "haomen-zongcai": {
        "dimensions": {
            "豪门规则": "豪门家族的企业架构、继承规则、家族礼仪",
            "商业知识": "相关行业的企业运作、并购/上市/董事会机制",
            "上流社交": "高端社交场景（宴会/慈善/拍卖）、奢侈品/时尚",
            "契约/婚姻": "契约婚姻的法律与社会常识、先婚后爱的情节模式",
        },
        "search_prefixes": ["豪门总裁 商业", "霸道总裁 企业", "豪门 继承"],
    },
    "gongdou-zhaidou": {
        "dimensions": {
            "宫廷制度": "后宫品级、宫女/太监制度、宫廷礼仪与禁忌",
            "宅院规则": "妻妾/嫡庶制度、管家/丫鬟/婆子体系",
            "饮食服饰": "宫廷/世家饮食、品级对应的服饰规制",
            "权谋手段": "古代宫斗/宅斗的常见手段（下毒/陷害/党争）",
            "历史参照": "真实历史中的宫廷斗争案例",
        },
        "search_prefixes": ["宫斗 后宫制度", "宅斗 嫡庶", "古代宫廷 权谋"],
    },
    "xuanyi": {
        "dimensions": {
            "犯罪学": "犯罪心理、犯罪手法、证据学基础",
            "刑侦流程": "公安/刑侦的办案流程、取证规范、法律程序",
            "法医学": "尸检/毒理/DNA/痕迹检验的基本知识",
            "推理模式": "经典推理小说/影视的叙事模式与反转技巧",
            "社会背景": "案件发生地的社会生态、灰色地带、地下秩序",
        },
        "search_prefixes": ["悬疑 刑侦知识", "推理 犯罪学", "悬疑小说 推理模式"],
    },
    "xuanyi-lingyi": {
        "dimensions": {
            "民俗信仰": "中国民间信仰/禁忌/仪式/丧葬文化",
            "灵异传说": "各地灵异传说、鬼故事原型、怪谈类型",
            "道教/佛教": "驱邪/超度/符咒/法器体系",
            "恐怖心理": "恐怖氛围的营造技巧、读者恐惧心理机制",
            "风水命理": "风水/命理/相术的基本框架",
        },
        "search_prefixes": ["灵异 民俗", "恐怖 民间信仰", "灵异小说 道教"],
    },
    "kehuan": {
        "dimensions": {
            "科学原理": "与设定相关的物理学/生物学/计算机科学原理",
            "技术推演": "从现有技术到设定的合理推演路径",
            "未来社会": "未来可能的社会结构、伦理问题、经济模式",
            "太空/星际": "航天技术、星际航行、外星生态（如涉及）",
            "赛博朋克": "赛博格/义体/网络空间/巨型企业（如涉及）",
            "AI/机器人": "人工智能/机器人/意识上传的相关理论与伦理",
        },
        "search_prefixes": ["科幻 科学原理", "科幻 技术推演", "科幻 未来社会"],
    },
    "moshi": {
        "dimensions": {
            "灾难类型": "丧尸/病毒/核战/天灾/极寒的运作机制与科学基础",
            "生存知识": "野外生存/水源/食物/药品/武器/防御",
            "社会组织": "末日后的社会形态：幸存者营地/军阀/交易体系",
            "心理状态": "极端环境下的群体心理、道德滑坡、人性变化",
            "军事/武器": "各类武器/装备/战术的基本知识",
        },
        "search_prefixes": ["末世 生存知识", "末日 丧尸", "末世文 社会结构"],
    },
    "xihuan": {
        "dimensions": {
            "西方奇幻": "DND/中土/巫师等经典奇幻体系的种族/魔法/神灵",
            "中世纪欧洲": "封建制度/骑士/教会/城堡/庄园经济",
            "魔法体系": "元素魔法/奥术/神术/炼金术的体系化设计",
            "神话参照": "北欧/希腊/凯尔特神话中的神祇、怪物、传说",
            "异世界": "异世界题材的常见设定模式与创新方向",
        },
        "search_prefixes": ["西幻 魔法体系", "奇幻 中世纪", "西方奇幻 神话"],
    },
    "zhongtian": {
        "dimensions": {
            "农业技术": "古代/近代农业技术：作物/工具/水利/节气",
            "手工业": "纺织/陶瓷/冶金/造纸/酿酒等手工技术",
            "商业经营": "古代商业规则：货币/运输/仓储/集市/商帮",
            "基层治理": "古代乡村/县城的治理结构、保甲/里甲制度",
            "基建工程": "古代建筑/水利/道路工程的技术与工艺",
        },
        "search_prefixes": ["种田文 农业", "古代 手工业", "经营文 商业"],
    },
    "kuaichuan": {
        "dimensions": {
            "位面设计": "不同位面/世界的切换规则与逻辑一致性",
            "系统机制": "任务的种类/奖励/惩罚/商城/积分体系",
            "角色扮演": "穿越到不同身份后的角色适应与行为逻辑",
            "穿越目标": "各类型穿越的目的地设定（古代/现代/星际/特殊世界）",
        },
        "search_prefixes": ["快穿 系统设计", "快穿文 位面", "穿书 任务系统"],
    },
    "wuxian-zhutian": {
        "dimensions": {
            "无限流机制": "主神空间/轮回世界的规则、任务/奖励/惩罚体系",
            "副本设计": "各类型副本的世界观、任务目标、难度曲线",
            "能力体系": "强化/兑换/血统/技能树的体系化设计",
            "团队协作": "轮回者团队的构成/分工/信任/背叛",
            "诸天世界": "各诸天世界的力量体系与穿越规则",
        },
        "search_prefixes": ["无限流 副本设计", "诸天流 世界", "无限流 能力体系"],
    },
    "youxi": {
        "dimensions": {
            "游戏机制": "RPG/MMO/竞技类游戏的系统设计：等级/技能/装备/副本",
            "电竞生态": "电竞赛事/俱乐部/选手/解说/直播的运作模式",
            "游戏文化": "玩家社区/攻略/代练/工作室/交易市场",
            "VR/全息": "VR/AR/全息技术的现状与合理推演",
        },
        "search_prefixes": ["游戏文 电竞", "网游小说 系统设计", "游戏 电竞生态"],
    },
    "zhanshen-zhuixu": {
        "dimensions": {
            "军事知识": "特种兵/佣兵/军方的组织架构、战术、装备",
            "都市权力": "都市中的地下势力、家族企业、权力结构",
            "身份翻转": "隐藏身份/归来复仇的情节模式与爽点节奏",
            "商业/医疗": "相关产业的运作逻辑（如涉及医术/商业线）",
        },
        "search_prefixes": ["战神 军事", "赘婿 都市", "战神归来 身份"],
    },
    "niandai": {
        "dimensions": {
            "时代背景": "七八十年代/知青/改革开放的社会背景与政策",
            "日常生活": "该年代的衣食住行、票证/物价/工资水平",
            "社会关系": "大院子弟/知青/军婚/工人/农民的社会生态",
            "经济变迁": "从计划经济到市场经济的转型过程与关键节点",
            "文化娱乐": "该年代的流行文化、音乐、电影、文学",
        },
        "search_prefixes": ["年代文 七八十年代", "知青 生活", "年代 社会变迁"],
    },
    "yulequan": {
        "dimensions": {
            "娱乐圈生态": "影视/音乐/综艺产业的运作模式、资源分配",
            "明星体系": "艺人经纪/粉丝经济/热搜/营销/公关",
            "影视制作": "电影/电视剧的制作流程、投资/发行/宣传",
            "奖项/典礼": "主要奖项/颁奖典礼的规则与影响力",
            "饭圈文化": "粉丝群体的组织方式、应援/打榜/控评",
        },
        "search_prefixes": ["娱乐圈 产业", "明星 经纪", "娱乐圈文 影视制作"],
    },
    "shuangnanzhu": {
        "dimensions": {
            "双强设定": "双男主的能力互补、身份对等、势均力敌的设计",
            "兄弟情/羁绊": "男性友谊/兄弟情的深度刻画与情感张力",
            "冲突设计": "双男主之间的信任/背叛/救赎的故事模式",
            "行业背景": "两位主角各自职业/领域的行业知识",
        },
        "search_prefixes": ["双男主 设定", "双强 兄弟情", "双男主文 冲突"],
    },
    "kangzhan-diexue": {
        "dimensions": {
            "抗战历史": "抗日战争的时间线、重大战役、战略态势",
            "谍战技术": "情报传递/密码/暗杀/渗透/策反的手段",
            "组织架构": "军统/中统/地下党/日军特高课的组织与运作",
            "民国生活": "民国时期的城市/交通/服饰/饮食/货币",
            "武器装备": "抗战时期各方使用的武器装备与战术",
        },
        "search_prefixes": ["抗战 历史", "谍战 情报", "民国 生活"],
    },
}

# 通用调研维度（题材卡未覆盖的兜底维度）
GENERIC_DIMENSIONS = {
    "世界观": "故事世界的自然/社会/文化/规则体系",
    "职业知识": "主要角色职业所需的专业知识与术语",
    "历史背景": "故事时代的历史/社会/文化背景",
    "地理空间": "故事发生地的真实/虚构地理信息",
    "技术/魔法": "故事中特殊能力/技术/魔法的体系化知识",
    "读者偏好": "同类题材的读者爽点/雷区/阅读习惯",
}


def _genre_key(genre_name):
    """根据题材名或别名匹配题材卡 key。"""
    genre_name = genre_name.strip()
    # 精确匹配 key
    for key in GENRE_RESEARCH_DIMENSIONS:
        if key == genre_name:
            return key
    # 遍历别名（从题材卡名称推断）
    alias_map = {
        "玄幻": "xuanhuan-xiuxian", "东方玄幻": "xuanhuan-xiuxian",
        "仙侠": "xuanhuan-xiuxian", "修真": "xuanhuan-xiuxian",
        "修仙": "xuanhuan-xiuxian", "高武": "xuanhuan-xiuxian",
        "都市": "dushi", "都市异能": "dushi", "神豪": "dushi",
        "重生都市": "dushi", "文娱": "dushi",
        "都市脑洞": "dushi-naodong", "系统流": "dushi-naodong",
        "签到流": "dushi-naodong", "脑洞文": "dushi-naodong",
        "历史": "lishi", "架空历史": "lishi", "穿越历史": "lishi",
        "历史权谋": "lishi", "争霸": "lishi",
        "言情": "yanqing", "现言": "yanqing", "甜宠": "yanqing",
        "追妻": "yanqing", "婚恋": "yanqing",
        "古言": "guyan", "古代言情": "guyan", "古风世情": "guyan",
        "世家": "guyan", "贵女": "guyan", "侯门": "guyan",
        "豪门总裁": "haomen-zongcai", "总裁文": "haomen-zongcai",
        "霸道总裁": "haomen-zongcai", "霸总": "haomen-zongcai",
        "先婚后爱": "haomen-zongcai", "契约婚姻": "haomen-zongcai",
        "宫斗": "gongdou-zhaidou", "宅斗": "gongdou-zhaidou",
        "深宅": "gongdou-zhaidou", "后宅": "gongdou-zhaidou",
        "嫡庶": "gongdou-zhaidou", "宫廷": "gongdou-zhaidou",
        "悬疑": "xuanyi", "推理": "xuanyi", "刑侦": "xuanyi",
        "诡秘": "xuanyi", "探案": "xuanyi",
        "灵异": "xuanyi-lingyi", "恐怖": "xuanyi-lingyi",
        "惊悚": "xuanyi-lingyi", "诡异": "xuanyi-lingyi",
        "怪谈": "xuanyi-lingyi", "民俗恐怖": "xuanyi-lingyi",
        "科幻": "kehuan", "硬科幻": "kehuan", "软科幻": "kehuan",
        "赛博朋克": "kehuan", "星际": "kehuan",
        "末世": "moshi", "末日": "moshi", "废土": "moshi",
        "丧尸": "moshi", "末日求生": "moshi",
        "西幻": "xihuan", "奇幻": "xihuan", "魔法": "xihuan",
        "剑与魔法": "xihuan", "DND": "xihuan", "异世界": "xihuan",
        "种田": "zhongtian", "经营": "zhongtian", "基建": "zhongtian",
        "领地建设": "zhongtian",
        "快穿": "kuaichuan", "穿书": "kuaichuan", "位面穿梭": "kuaichuan",
        "无限流": "wuxian-zhutian", "诸天流": "wuxian-zhutian",
        "无限": "wuxian-zhutian", "诸天": "wuxian-zhutian",
        "副本流": "wuxian-zhutian", "主神空间": "wuxian-zhutian",
        "游戏": "youxi", "电竞": "youxi", "网游": "youxi",
        "虚拟现实": "youxi", "VR": "youxi", "全息": "youxi",
        "战神": "zhanshen-zhuixu", "赘婿": "zhanshen-zhuixu",
        "兵王": "zhanshen-zhuixu", "龙王": "zhanshen-zhuixu",
        "战神归来": "zhanshen-zhuixu", "上门女婿": "zhanshen-zhuixu",
        "年代": "niandai", "年代文": "niandai", "七八十年代": "niandai",
        "重生年代": "niandai", "知青": "niandai", "大院": "niandai",
        "娱乐圈": "yulequan", "星光璀璨": "yulequan",
        "影帝": "yulequan", "影后": "yulequan", "顶流": "yulequan",
        "双男主": "shuangnanzhu", "双强": "shuangnanzhu",
        "兄弟情": "shuangnanzhu",
        "抗战": "kangzhan-diexue", "谍战": "kangzhan-diexue",
        "军统": "kangzhan-diexue", "地下党": "kangzhan-diexue",
        "潜伏": "kangzhan-diexue", "特工": "kangzhan-diexue",
        "民国谍战": "kangzhan-diexue",
    }
    return alias_map.get(genre_name)


# ============================================================================
# 工具函数
# ============================================================================

def _find_book_dir(path):
    """查找书籍工程根目录（含追踪/ 与 大纲/ 的目录）。
    支持直接传入书籍目录或书籍目录下的子路径。
    """
    path = os.path.abspath(path)
    # 向上查找
    current = path
    for _ in range(5):
        if os.path.isdir(os.path.join(current, "追踪")) and \
           os.path.isdir(os.path.join(current, "大纲")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    # 如果传入路径本身就是，直接返回
    if os.path.isdir(os.path.join(path, "追踪")) and \
       os.path.isdir(os.path.join(path, "大纲")):
        return path
    return None


def _read_genre_positioning(book_dir):
    """从 设定/题材定位.md 读取主题材名称。"""
    gen_pos_path = os.path.join(book_dir, "设定", "题材定位.md")
    if not os.path.isfile(gen_pos_path):
        return None
    with open(gen_pos_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    # 尝试匹配题材名（取第一行或关键词行）
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 匹配常见格式：题材：xxx / 主题材：xxx / genre: xxx
        m = re.match(r"(?:题材|主题材|genre)\s*[:：]\s*(.+)", line, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # 取第一行非空非标题行
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def _list_existing_research(book_dir):
    """列出 参考资料/ 目录下已有的调研文件。返回 {维度名: 文件路径} 映射。"""
    ref_dir = os.path.join(book_dir, "参考资料")
    if not os.path.isdir(ref_dir):
        return {}
    existing = {}
    for fname in os.listdir(ref_dir):
        if fname.endswith(".md") and fname != "调研日志.md":
            fpath = os.path.join(ref_dir, fname)
            # 文件名去掉扩展名作为维度名
            dim_name = os.path.splitext(fname)[0]
            existing[dim_name] = fpath
    return existing


def _read_genre_card_coverage(genre_key):
    """判断题材卡已覆盖的维度（题材卡中明确写了的内容，不需要再调研）。
    返回题材卡已覆盖的维度名集合。
    """
    if not genre_key:
        return set()
    card_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references", "genres", f"{genre_key}.md"
    )
    if not os.path.isfile(card_path):
        return set()
    with open(card_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    # 题材卡的栏目名即为已覆盖维度
    covered = set()
    for m in re.finditer(r"^##\s+(.+)", content, re.MULTILINE):
        section = m.group(1).strip()
        covered.add(section)
    return covered


# ============================================================================
# 子命令实现
# ============================================================================

def cmd_keywords(args):
    """生成搜索关键词列表。"""
    genre_key = _genre_key(args.genre) if args.genre else None
    topic = args.topic.strip() if args.topic else ""

    if not genre_key and not topic:
        print("错误：至少需要 --genre 或 --topic 之一", file=sys.stderr)
        return 2

    keywords = []

    if genre_key and genre_key in GENRE_RESEARCH_DIMENSIONS:
        dims = GENRE_RESEARCH_DIMENSIONS[genre_key]
        # 从题材默认搜索前缀生成关键词
        for prefix in dims["search_prefixes"]:
            if topic:
                keywords.append(f"{prefix} {topic}")
            else:
                keywords.append(prefix)
        # 从各维度生成关键词
        for dim_name, dim_desc in dims["dimensions"].items():
            if topic:
                keywords.append(f"{dim_name} {topic}")
            else:
                keywords.append(f"{dim_name} {dim_desc.split('、')[0]}")
    elif topic:
        # 纯主题搜索
        keywords.append(topic)

    # 去重 + 排序
    keywords = sorted(set(keywords))

    print(f"题材: {args.genre or '（未指定）'}")
    print(f"主题: {topic or '（未指定）'}")
    print(f"生成 {len(keywords)} 个搜索关键词：")
    print()
    for i, kw in enumerate(keywords, 1):
        print(f"  {i:2d}. {kw}")

    # 输出 JSON 格式（方便 Agent 消费）
    if args.json:
        print()
        print("--- JSON ---")
        print(json.dumps({
            "genre": args.genre,
            "topic": topic,
            "genre_key": genre_key,
            "keywords": keywords,
            "count": len(keywords),
        }, ensure_ascii=False, indent=2))

    return 0


def cmd_gaps(args):
    """检测知识库缺口。"""
    book_dir = _find_book_dir(args.book_dir)
    if not book_dir:
        print(f"错误：未找到书籍工程目录（需含 追踪/ 和 大纲/）：{args.book_dir}",
              file=sys.stderr)
        return 2

    # 读取主题材
    genre_name = _read_genre_positioning(book_dir)
    genre_key = _genre_key(genre_name) if genre_name else None

    print(f"书籍工程: {book_dir}")
    print(f"主题材: {genre_name or '未找到'}")
    print(f"题材Key: {genre_key or '未匹配'}")
    print()

    # 获取需要的维度
    if genre_key and genre_key in GENRE_RESEARCH_DIMENSIONS:
        needed_dims = dict(GENRE_RESEARCH_DIMENSIONS[genre_key]["dimensions"])
    else:
        needed_dims = dict(GENERIC_DIMENSIONS)

    # 获取已有调研
    existing = _list_existing_research(book_dir)

    # 获取题材卡已覆盖的维度
    card_covered = _read_genre_card_coverage(genre_key)

    # 计算缺口
    gaps = {}
    covered = {}
    for dim_name, dim_desc in needed_dims.items():
        if dim_name in existing:
            covered[dim_name] = {
                "file": existing[dim_name],
                "desc": dim_desc,
            }
        elif dim_name in card_covered:
            covered[dim_name] = {
                "file": f"题材卡: {genre_key}.md",
                "desc": dim_desc,
                "note": "题材卡已覆盖",
            }
        else:
            gaps[dim_name] = dim_desc

    print(f"调研维度：共 {len(needed_dims)} 个")
    print(f"  已覆盖: {len(covered)} 个")
    print(f"  缺口:   {len(gaps)} 个")
    print()

    if covered:
        print("已覆盖维度：")
        for dim_name, info in covered.items():
            note = f" ({info.get('note', '')})" if info.get("note") else ""
            print(f"  [OK] {dim_name} → {info['file']}{note}")
        print()

    if gaps:
        print("知识缺口：")
        for dim_name, dim_desc in gaps.items():
            print(f"  [GAP] {dim_name}: {dim_desc}")
    else:
        print("  无知识缺口。")

    # JSON 输出
    if args.json:
        print()
        print("--- JSON ---")
        print(json.dumps({
            "book_dir": book_dir,
            "genre": genre_name,
            "genre_key": genre_key,
            "total_dimensions": len(needed_dims),
            "covered_count": len(covered),
            "gap_count": len(gaps),
            "covered": {k: v["file"] for k, v in covered.items()},
            "gaps": gaps,
        }, ensure_ascii=False, indent=2))

    return 0


def cmd_store(args):
    """将调研结果结构化存储到参考资料目录。"""
    book_dir = _find_book_dir(args.book_dir)
    if not book_dir:
        print(f"错误：未找到书籍工程目录：{args.book_dir}", file=sys.stderr)
        return 2

    dimension = args.dimension.strip()
    if not dimension:
        print("错误：--dimension 不能为空", file=sys.stderr)
        return 2

    # 确保参考资料目录存在
    ref_dir = os.path.join(book_dir, "参考资料")
    os.makedirs(ref_dir, exist_ok=True)

    # 读取来源内容
    source = args.source
    if args.source_file:
        try:
            with open(args.source_file, "r", encoding="utf-8-sig") as f:
                source = f.read()
        except OSError as e:
            print(f"错误：无法读取来源文件 {args.source_file}: {e}", file=sys.stderr)
            return 2

    if not source:
        print("错误：需要 --source 或 --source-file 提供调研内容", file=sys.stderr)
        return 2

    # 生成调研文件
    safe_dim = re.sub(r'[\\/:*?"<>|]', '_', dimension)
    safe_dim = safe_dim.replace(" ", "_")
    out_path = os.path.join(ref_dir, f"{safe_dim}.md")

    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    url_info = f"\n> 来源URL: {args.url}" if args.url else ""

    content = textwrap.dedent(f"""\
    # {dimension} — 调研资料

    > 调研时间: {timestamp}
    > 调研方式: 联网搜索{url_info}
    > 题材: {_read_genre_positioning(book_dir) or '未指定'}

    ---

    {source}
    """)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"调研结果已存储: {out_path}")
    print(f"  维度: {dimension}")
    print(f"  字数: {len(source)} 字符")

    # 记录调研日志
    _log_research(book_dir, dimension, safe_dim, args.url or "", timestamp)

    return 0


def _log_research(book_dir, dimension, safe_dim, url, timestamp):
    """记录调研到日志文件。"""
    log_path = os.path.join(book_dir, "参考资料", "调研日志.md")
    entry = (
        f"| {timestamp} | {dimension} | {safe_dim}.md | {url or '-'} |\n"
    )

    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8-sig") as f:
            existing = f.read()
        # 在表格末尾追加
        if "|---|---|---|---|" in existing:
            # 找到表格最后一行
            lines = existing.splitlines(keepends=True)
            # 在最后一行之后插入
            lines.append(entry)
            with open(log_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        else:
            # 表格不存在，追加新表
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
    else:
        # 新建日志文件
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# 调研日志\n\n")
            f.write("| 时间 | 调研维度 | 产出文件 | 来源URL |\n")
            f.write("|---|---|---|---|\n")
            f.write(entry)


def cmd_plan(args):
    """生成调研计划（含缺口 + 关键词 + 优先级）。"""
    book_dir = _find_book_dir(args.book_dir)
    if not book_dir:
        print(f"错误：未找到书籍工程目录：{args.book_dir}", file=sys.stderr)
        return 2

    depth = args.depth.strip()
    if depth not in ("quick", "standard", "deep"):
        print(f"错误：--depth 需为 quick/standard/deep，收到：{depth}", file=sys.stderr)
        return 2

    # 读取主题材
    genre_name = _read_genre_positioning(book_dir)
    genre_key = _genre_key(genre_name) if genre_name else None

    # 获取需要的维度
    if genre_key and genre_key in GENRE_RESEARCH_DIMENSIONS:
        genre_dims = GENRE_RESEARCH_DIMENSIONS[genre_key]
        needed_dims = dict(genre_dims["dimensions"])
        search_prefixes = genre_dims["search_prefixes"]
    else:
        needed_dims = dict(GENERIC_DIMENSIONS)
        search_prefixes = []

    # 获取已有调研
    existing = _list_existing_research(book_dir)
    card_covered = _read_genre_card_coverage(genre_key)

    # 计算缺口
    gaps = {}
    for dim_name, dim_desc in needed_dims.items():
        if dim_name not in existing and dim_name not in card_covered:
            gaps[dim_name] = dim_desc

    # 按深度过滤维度
    depth_limits = {
        "quick": 3,     # 快速调研最多 3 个维度
        "standard": 6,  # 标准调研最多 6 个维度
        "deep": len(needed_dims),  # 深度调研全部维度
    }
    limit = depth_limits[depth]

    # 优先级排序：缺口优先，按维度在定义中的顺序
    gap_items = list(gaps.items())
    gap_items = gap_items[:limit]

    # 生成关键词
    plan_keywords = []
    for dim_name, _dim_desc in gap_items:
        if search_prefixes:
            for prefix in search_prefixes[:2]:  # 每个维度1-2个前缀
                plan_keywords.append(f"{prefix} {dim_name}")
        else:
            plan_keywords.append(dim_name)

    plan_keywords = sorted(set(plan_keywords))

    # 输出计划
    print(f"调研计划 — {os.path.basename(book_dir)}")
    print(f"题材: {genre_name or '未指定'}")
    print(f"调研深度: {depth} ({limit} 个维度)")
    print(f"缺口总数: {len(gaps)}")
    print()

    print("调研维度（按优先级）：")
    for i, (dim_name, dim_desc) in enumerate(gap_items, 1):
        print(f"  {i}. {dim_name}")
        print(f"     {dim_desc}")
    print()

    print("搜索关键词：")
    for i, kw in enumerate(plan_keywords, 1):
        print(f"  {i:2d}. {kw}")
    print()

    print("执行步骤：")
    print("  1. 对上述关键词逐一执行联网搜索")
    print("  2. 将搜索结果按维度归类整理")
    print("  3. 运行 store 子命令存储：")
    for dim_name, _dim_desc in gap_items:
        safe_dim = re.sub(r'[\\/:*?"<>|]', '_', dim_name)
        print(f"     python scripts/research_agent.py store \"{book_dir}\" \\")
        print(f"       --dimension \"{dim_name}\" --source-file \"搜索结果.txt\"")
    print("  4. 调研日志会自动记录在 参考资料/调研日志.md")

    # JSON 输出
    if args.json:
        print()
        print("--- JSON ---")
        print(json.dumps({
            "book_dir": book_dir,
            "genre": genre_name,
            "genre_key": genre_key,
            "depth": depth,
            "dimension_limit": limit,
            "total_gaps": len(gaps),
            "plan_dimensions": [{"name": n, "desc": d} for n, d in gap_items],
            "keywords": plan_keywords,
        }, ensure_ascii=False, indent=2))

    return 0


# ============================================================================
# 主入口
# ============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="联网调研调度器：题材-维度映射 + 关键词生成 + 缺口检测 + 结构化存储",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            子命令说明：
              keywords  按题材+主题生成搜索关键词列表
              gaps      检测知识库缺口（已有 vs 需要）
              store     将调研结果结构化存储到参考资料目录
              plan      生成调研计划（含缺口 + 关键词 + 优先级）

            示例：
              %(prog)s keywords --genre 玄幻 --topic "炼丹体系"
              %(prog)s gaps "我的小说"
              %(prog)s store "我的小说" --dimension 世界观 --source "调研内容..."
              %(prog)s plan "我的小说" --depth standard
        """),
    )
    sub = ap.add_subparsers(dest="command", help="子命令")

    # keywords 子命令
    p_kw = sub.add_parser("keywords", help="生成搜索关键词列表")
    p_kw.add_argument("--genre", default=None, help="题材名（如 玄幻/都市/悬疑）")
    p_kw.add_argument("--topic", default=None, help="具体主题（如 炼丹体系/刑侦流程）")
    p_kw.add_argument("--json", action="store_true", help="额外输出 JSON 格式")

    # gaps 子命令
    p_gap = sub.add_parser("gaps", help="检测知识库缺口")
    p_gap.add_argument("book_dir", help="书籍工程目录路径")
    p_gap.add_argument("--json", action="store_true", help="额外输出 JSON 格式")

    # store 子命令
    p_store = sub.add_parser("store", help="存储调研结果")
    p_store.add_argument("book_dir", help="书籍工程目录路径")
    p_store.add_argument("--dimension", required=True, help="调研维度名称（如 世界观/修炼体系）")
    p_store.add_argument("--source", default="", help="调研内容文本（直接传入）")
    p_store.add_argument("--source-file", default=None, help="调研内容文件路径（从文件读取）")
    p_store.add_argument("--url", default="", help="调研来源 URL（可选，记入日志）")

    # plan 子命令
    p_plan = sub.add_parser("plan", help="生成调研计划")
    p_plan.add_argument("book_dir", help="书籍工程目录路径")
    p_plan.add_argument("--depth", default="standard",
                        help="调研深度：quick（≤3维）/ standard（≤6维）/ deep（全部）")
    p_plan.add_argument("--json", action="store_true", help="额外输出 JSON 格式")

    args = ap.parse_args()

    if not args.command:
        ap.print_help()
        return 2

    try:
        if args.command == "keywords":
            return cmd_keywords(args)
        elif args.command == "gaps":
            return cmd_gaps(args)
        elif args.command == "store":
            return cmd_store(args)
        elif args.command == "plan":
            return cmd_plan(args)
        else:
            print(f"错误：未知子命令 {args.command}", file=sys.stderr)
            return 2
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())