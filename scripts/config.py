#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py — 全局配置常量（纯标准库）。

所有脚本的配置项集中在此，便于统一管理。
修改一处即全局生效，避免散落在各脚本中的魔法数字。

v6.1 新增：环境变量覆盖。所有带 LNS_ 前缀的环境变量可覆盖对应常量，
便于 CI/CD 管道、测试环境、不同平台配置的灵活调整，无需改代码。
"""

import os

# =============================================================================
# Skill 版本
# =============================================================================

SKILL_VERSION = "7.0.0"
SKILL_NAME = "long-novel-skill"


# =============================================================================
# 环境变量覆盖工具
# =============================================================================

def _env_int(key: str, default: int) -> int:
    """从环境变量读取整数，格式：LNS_{KEY}。失败返回 default。"""
    val = os.environ.get(f"LNS_{key}")
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    """从环境变量读取浮点数，格式：LNS_{KEY}。失败返回 default。"""
    val = os.environ.get(f"LNS_{key}")
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default

# =============================================================================
# 书籍工程目录结构
# =============================================================================

BOOK_DIRS = {
    "outline": "大纲",
    "setting": "设定",
    "manuscript": "正文",
    "tracking": "追踪",
    "benchmark": "对标",
    "reference": "参考资料",
}

TRACKING_FILES = {
    "foreshadow": "伏笔台账.md",
    "character_state": "角色状态.md",
    "chapter_summary": "章节摘要.md",
    "timeline": "时间线.md",
    "rhythm_quota": "节奏配额.md",
    "entity_index": "entity_index.json",
    "story_graph": "story_graph.json",
}

SETTING_FILES = {
    "genre_profile": "题材定位.md",
    "worldview": "世界观.md",
    "style_anchor": "文风锚.md",
    "reader_contract": "读者契约.md",
    "banned_words": "禁用词.txt",
    "characters_dir": "角色",
}

# =============================================================================
# 章节命名格式
# =============================================================================

CHAPTER_FILE_PATTERN = r"第(\d+)章"
OUTLINE_FILE_PATTERN = r"章纲_第(\d+)章"

# =============================================================================
# 字数限制
# =============================================================================

DEFAULT_MIN_CHARS = _env_int("DEFAULT_MIN_CHARS", 2000)
DEFAULT_MAX_CHARS = _env_int("DEFAULT_MAX_CHARS", 4500)
SHORT_STORY_MIN_CHARS = _env_int("SHORT_STORY_MIN_CHARS", 4000)
SHORT_STORY_MAX_CHARS = _env_int("SHORT_STORY_MAX_CHARS", 30000)

# =============================================================================
# 节奏配额
# =============================================================================

RHYTHM_QUOTA_TYPES = ["A", "B", "C"]
RHYTHM_COOLDOWN_CHAPTERS = _env_int("RHYTHM_COOLDOWN_CHAPTERS", 2)  # A/B/C触发后冷却章数
MAX_RECENT_CHAPTERS_FOR_QUOTA = _env_int("MAX_RECENT_CHAPTERS_FOR_QUOTA", 3)

# =============================================================================
# 事件矩阵单一来源（v7.0：收敛 rhythm_guard/event_matrix 两处重复定义）
# =============================================================================
# cooldown = 同型事件冷却章数；consecutive_limit = 同型事件连续出现上限；
# quota = 映射到的 A/B/C 节奏配额（None 表示无映射）。
# 注意：本表「cooldown」与「节奏配额冷却 RHYTHM_COOLDOWN_CHAPTERS / rhythm_guard.QUOTA_COOLDOWN」
# 是两个独立概念，不可混用——前者约束同型事件，后者约束 A/B/C 档位节奏。
EVENT_META = {
    "conflict": {"name": "冲突爽点", "cooldown": 2, "consecutive_limit": 2, "quota": "A",
                 "desc": "打脸/对决/爽点爆发"},
    "bond": {"name": "人物羁绊", "cooldown": 3, "consecutive_limit": 3, "quota": "B",
             "desc": "师徒/友情/情感深化"},
    "faction": {"name": "势力经营", "cooldown": 4, "consecutive_limit": 2, "quota": None,
                "desc": "宗门/势力/组织运作"},
    "world": {"name": "风土人情", "cooldown": 3, "consecutive_limit": 2, "quota": None,
              "desc": "世界观/风物/民俗"},
    "crisis": {"name": "危机升级", "cooldown": 2, "consecutive_limit": 2, "quota": None,
               "desc": "威胁逼近/压力升级"},
    "revelation": {"name": "核心秘密", "cooldown": 5, "consecutive_limit": 1, "quota": "C",
                   "desc": "身世/真相/核心揭秘"},
}

# =============================================================================
# 上下文管理（v6.1：动态上下文阶段配置）
# =============================================================================

DEFAULT_MAX_CONTEXT_CHARS = _env_int("DEFAULT_MAX_CONTEXT_CHARS", 8000)
DEFAULT_RECENT_CHAPTERS = _env_int("DEFAULT_RECENT_CHAPTERS", 10)

# 静态默认预算比例（用于回退）；动态选取时按阶段覆盖
CONTEXT_BUDGET_RATIOS = {
    "chapter_brief": 0.15,
    "character_cards": 0.20,
    "recent_summaries": 0.30,
    "foreshadowing": 0.15,
    "style_anchor": 0.10,
    "rhythm_quota": 0.10,
}

# v6.1 动态上下文阶段定义：根据全书进度切换预算比例
# 四阶段：开篇(0-5%) / 发展(5-30%) / 深水(30-75%) / 收束(75-100%)
# v7.0 补全组件：outline_anchor / entity_context / character_state / world_setting
CONTEXT_STAGES = {
    "opening": {
        "range": (0.0, 0.05),
        "ratios": {
            "chapter_brief": 0.18,      # 开篇章纲更重要
            "character_cards": 0.25,    # 角色卡需要更多
            "recent_summaries": 0.10,   # 没几章可回顾
            "foreshadowing": 0.08,
            "rhythm_quota": 0.08,
            "outline_anchor": 0.05,
            "entity_context": 0.03,
            "character_state": 0.10,    # 活跃角色当前状态
            "world_setting": 0.08,      # 关键设定约束
            "style_anchor": 0.05,       # 奠定文风
        },
    },
    "development": {
        "range": (0.05, 0.30),
        "ratios": {
            "chapter_brief": 0.12,
            "character_cards": 0.16,
            "recent_summaries": 0.20,
            "foreshadowing": 0.13,
            "rhythm_quota": 0.10,
            "outline_anchor": 0.06,
            "entity_context": 0.05,
            "character_state": 0.08,
            "world_setting": 0.05,
            "style_anchor": 0.05,
        },
    },
    "deepwater": {
        "range": (0.30, 0.75),
        "ratios": {
            "chapter_brief": 0.10,      # 章纲权重降
            "character_cards": 0.12,    # 角色都熟了
            "recent_summaries": 0.25,   # 近章回顾最关键
            "foreshadowing": 0.18,      # 伏笔堆积期
            "rhythm_quota": 0.08,
            "outline_anchor": 0.06,
            "entity_context": 0.06,
            "character_state": 0.07,
            "world_setting": 0.05,
            "style_anchor": 0.03,
        },
    },
    "finale": {
        "range": (0.75, 1.0),
        "ratios": {
            "chapter_brief": 0.08,
            "character_cards": 0.08,
            "recent_summaries": 0.16,
            "foreshadowing": 0.30,      # 回收期，伏笔信息量最大
            "rhythm_quota": 0.08,
            "outline_anchor": 0.06,
            "entity_context": 0.04,
            "character_state": 0.06,
            "world_setting": 0.04,
            "style_anchor": 0.03,
            "milestone": 0.07,          # 里程碑（终局储备）
        },
    },
}

# =============================================================================
# RAG 检索
# =============================================================================

RAG_DEFAULT_TOP_K = _env_int("RAG_DEFAULT_TOP_K", 4)
RAG_DEFAULT_CANDIDATE_K = _env_int("RAG_DEFAULT_CANDIDATE_K", 8)
RAG_CACHE_FILE = "query_cache.json"
RAG_LIGHT_SCENE_KEYWORDS = ["赶路", "过场", "日常", "过渡", "休息"]

# =============================================================================
# 编辑团队
# =============================================================================

EDITORIAL_AGENTS = {
    "planning-editor": "策划主编",
    "novelist": "写作特工",
    "anti-ai-editor": "反AI编辑",
    "consistency-reviewer": "连载核实官",
}
MAX_REWRITE_ROUNDS = _env_int("MAX_REWRITE_ROUNDS", 2)
MAX_CONDITIONAL_CHAPTERS = _env_int("MAX_CONDITIONAL_CHAPTERS", 3)

# =============================================================================
# 知识图谱
# =============================================================================

GRAPH_NODE_TYPES = ["character", "event", "location", "item", "faction", "secret", "rule"]
GRAPH_EDGE_TYPES = [
    "owns", "kills", "betrays", "allies", "loves", "hates", "mentors",
    "rivals", "belongs_to", "located_at", "reveals", "causes",
    "participates_in", "appears_in",
]

# =============================================================================
# Beat Sheet
# =============================================================================

BEAT_MIN_COUNT = _env_int("BEAT_MIN_COUNT", 3)
BEAT_MAX_COUNT = _env_int("BEAT_MAX_COUNT", 7)
BEAT_DEFAULT_TARGET_CHARS = _env_int("BEAT_DEFAULT_TARGET_CHARS", 3000)

# =============================================================================
# 门禁
# =============================================================================

GATE_NAMES = {
    "gate_a": "禁用词",
    "gate_b": "毒句式",
    "gate_c": "心理告知",
    "gate_d": "节奏均匀",
    "gate_e": "对话腔调",
    "gate_f": "结尾升华",
    "gate_g": "解释腔",
}

# =============================================================================
# AI 去味
# =============================================================================

AI_SCORE_THRESHOLDS = {
    "low": 20,      # 0-20 轻度AI味（per-kilo加权分）
    "medium": 40,   # 20-40 中度AI味
    "high": 100,    # >40 重度AI味
}
DESLOP_MAX_DELETE_RATIO = _env_float("DESLOP_MAX_DELETE_RATIO", 0.15)  # 单次去味最多删除15%

# =============================================================================
# 流程执行器（v6.1 新增：幂等回滚相关）
# =============================================================================

# 执行锁文件路径（相对书籍工程根目录）
FLOW_LOCK_FILE = "追踪/.flow_lock.json"
# 快照目录（执行前备份关键追踪文件）
FLOW_SNAPSHOT_DIR = "追踪/.snapshots"
# 快照保留数量上限
FLOW_SNAPSHOT_MAX_KEEP = _env_int("FLOW_SNAPSHOT_MAX_KEEP", 10)
# 脚本执行超时秒数
FLOW_SCRIPT_TIMEOUT = _env_int("FLOW_SCRIPT_TIMEOUT", 120)

# =============================================================================
# 静态检查（v6.1 新增）
# =============================================================================

# 角色名一致性：正文出现的角色名必须在 设定/角色/ 有对应卡
STATIC_CHECK_STRICT_CHARACTER = False  # 非严格模式：只报 WARN
# 时间线一致性：章节间时间推进不能倒退（static_check 的 C1 兼容检查）
STATIC_CHECK_TIMELINE = True

# =============================================================================
# 时间线管理模块（timeline_manager.py，v7.0 新增）
# =============================================================================

TIMELINE_JSON_FILE = "timeline.json"                 # 机器可读时间线文件
TIMELINE_MAX_SILENT_GAP = _env_int("TIMELINE_MAX_SILENT_GAP", 30)  # 相邻章静默时间跳转上限（天）
TIMELINE_CHECK_ENABLED = True                        # 五类冲突检测开关
# 伏笔状态一致性：正文中回收的伏笔必须在台账标记为已回收
STATIC_CHECK_FORESHADOW = True

# =============================================================================
# Benchmark（v6.1 新增）
# =============================================================================

BENCHMARK_SAMPLE_DIR = "benchmark_samples"
BENCHMARK_METRICS = [
    "ai_score",        # AI 味分数
    "gate_pass_rate",  # 门禁通过率
    "avg_sent_len",    # 平均句长
    "dialogue_ratio",  # 对话占比
    "rhythm_balance",  # 节奏均衡度
]


# =============================================================================
# 多 LLM 配置（v6.2 新增：三优先级加载）
# =============================================================================
# 设计原则：
#   1. 零依赖原则：有 PyYAML 用 YAML，没装就降级 INI，再不行环境变量
#   2. 三优先级：环境变量 > 书籍工程.lns_config.yaml/ini > 默认值
#   3. 密钥脱敏：日志和序列化时自动隐藏 API Key
# =============================================================================

# 支持的 LLM Provider 列表（用于校验）
SUPPORTED_LLM_PROVIDERS = [
    "openai",      # GPT-4o / GPT-4
    "anthropic",   # Claude 3.5 Sonnet / Claude 3 Opus
    "kimi",        # Kimi / Moonshot
    "glm",         # 智谱 GLM-4
    "minimax",     # MiniMax
    "qwen",        # 通义千问
    "deepseek",    # DeepSeek
    "default",     # 平台自带（靠AI客户端处理）
]

# 环境变量到 Provider 的映射（支持常见命名）
LLM_ENV_PROVIDER_MAP = {
    "OPENAI_API_KEY": "openai",
    "ANTHROPIC_API_KEY": "anthropic",
    "KIMI_API_KEY": "kimi",
    "MOONSHOT_API_KEY": "kimi",
    "GLM_API_KEY": "glm",
    "ZHIPU_API_KEY": "glm",
    "MINIMAX_API_KEY": "minimax",
    "QWEN_API_KEY": "qwen",
    "DASHSCOPE_API_KEY": "qwen",
    "DEEPSEEK_API_KEY": "deepseek",
}

# 配置文件名（按优先级）
LLM_CONFIG_FILES = [".lns_config.yaml", ".lns_config.yml", ".lns_config.ini"]


def load_llm_config(book_dir=None):
    """加载 LLM 配置（三优先级，零依赖）。

    优先级：
      1. 环境变量（LNS_LLM_PROVIDER / *_API_KEY）
      2. 书籍工程配置文件（.lns_config.yaml / .lns_config.ini）
      3. 默认值（platform-default）

    Args:
        book_dir: 书籍工程目录（可选，用于查找配置文件）

    Returns:
        dict: {
            "provider": str,          # LLM 提供商
            "model": str,             # 模型名
            "api_key": str or None,   # API Key（需要脱敏展示时用 mask_llm_key()）
            "base_url": str or None,  # API Base URL（可选）
            "source": str,            # 配置来源：environment / yaml_file / ini_file / default
        }
    """
    # 优先级 1：环境变量
    for env_var, provider in LLM_ENV_PROVIDER_MAP.items():
        api_key = os.environ.get(env_var)
        if api_key:
            model_env = f"{provider.upper()}_MODEL"
            return {
                "provider": provider,
                "model": os.environ.get(model_env, "default"),
                "api_key": api_key,
                "base_url": os.environ.get(f"{provider.upper()}_BASE_URL"),
                "source": "environment",
            }
    # LNS_ 前缀显式指定
    if os.environ.get("LNS_LLM_PROVIDER"):
        return {
            "provider": os.environ["LNS_LLM_PROVIDER"],
            "model": os.environ.get("LNS_LLM_MODEL", "default"),
            "api_key": os.environ.get("LNS_LLM_API_KEY"),
            "base_url": os.environ.get("LNS_LLM_BASE_URL"),
            "source": "environment",
        }

    # 优先级 2：书籍工程配置文件
    if book_dir:
        from pathlib import Path
        book = Path(book_dir).resolve()
        for cfg_name in LLM_CONFIG_FILES:
            cfg_path = book / cfg_name
            if not cfg_path.exists():
                continue
            try:
                if cfg_name.endswith((".yaml", ".yml")):
                    result = _parse_llm_yaml(cfg_path)
                    if result:
                        return result
                elif cfg_name.endswith(".ini"):
                    result = _parse_llm_ini(cfg_path)
                    if result:
                        return result
            except Exception:
                pass  # 配置解析失败就尝试下一个

    # 优先级 3：默认值（平台自带）
    return {
        "provider": "default",
        "model": "platform-default",
        "api_key": None,
        "base_url": None,
        "source": "default",
    }


def _parse_llm_yaml(cfg_path):
    """解析 YAML 配置（有 PyYAML 才用，没装返回 None）。"""
    try:
        import yaml  # 延迟导入
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "llm" in data:
            llm = data["llm"]
            return {
                "provider": llm.get("provider", "default"),
                "model": llm.get("model", "default"),
                "api_key": llm.get("api_key"),
                "base_url": llm.get("base_url"),
                "source": "yaml_file",
            }
        elif isinstance(data, dict) and "provider" in data:
            # 直接扁平结构也支持
            return {
                "provider": data.get("provider", "default"),
                "model": data.get("model", "default"),
                "api_key": data.get("api_key"),
                "base_url": data.get("base_url"),
                "source": "yaml_file",
            }
    except (ImportError, Exception):
        pass
    return None


def _parse_llm_ini(cfg_path):
    """解析 INI 配置（标准库 configparser，零依赖）。"""
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read(cfg_path, encoding="utf-8")
        if cp.has_section("llm"):
            return {
                "provider": cp.get("llm", "provider", fallback="default"),
                "model": cp.get("llm", "model", fallback="default"),
                "api_key": cp.get("llm", "api_key", fallback=None),
                "base_url": cp.get("llm", "base_url", fallback=None),
                "source": "ini_file",
            }
    except Exception:
        pass
    return None


def mask_llm_key(api_key):
    """脱敏 API Key（用于日志和展示）。

    例：sk-abc123def456 -> sk-ab*********56
    """
    if not api_key:
        return "(none)"
    if len(api_key) <= 6:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * (len(api_key) - 6)}{api_key[-2:]}"
