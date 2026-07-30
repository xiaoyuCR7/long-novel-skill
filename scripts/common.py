#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — 脚本共享工具函数（纯标准库，无第三方依赖）。

所有脚本通过 from common import * 或按需导入使用。
减少重复代码，集中管理书籍工程定位、文件读写、文本处理等通用逻辑。
"""

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# 预编译正则（全skill统一入口，任何脚本不得重复定义）
# =============================================================================
# 命名约定：
#   RE_XXX       = 通用正则（跨多个脚本使用）
#   _PRIVATE_RE   = 私有正则（仅common.py内部使用，以下划线开头）
# =============================================================================

# --- 章节相关（所有脚本共享）
RE_CHAPTER_NO = re.compile(r"第(\d+)章")
RE_CHAPTER_FILE = re.compile(r"^第(\d+)章")
RE_CHAPTER_TITLE = re.compile(r"第\s*(\d+)\s*章")
RE_OUTLINE_FILE = re.compile(r"章纲_第(\d+)章")
RE_SECTION_OUTLINE = re.compile(r"节纲_第\s*0*(\d+)\s*章")

# --- 中文文本处理（所有脚本共享）
RE_CHINESE_CHAR = re.compile(r"[\u4e00-\u9fff]")
RE_CJK_CHAR = re.compile(r"[一-鿿㐀-䶿豈-﫿]")  # 更全的中日韩字符范围
RE_CHINESE_WORD = re.compile(r"[\u4e00-\u9fff]{2,4}")
RE_CJK_RUN = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
RE_MULTI_BLANK_LINE = re.compile(r"\n{3,}")

# --- 句子/对话切分（所有脚本共享）
RE_SENT_SPLIT = re.compile(r"[。！？!?…]+")
RE_DIALOGUE = re.compile(r"「[^」]*」|\"[^\"]*\"|“[^”]*”")
RE_DIALOGUE_QUOTE = re.compile(r'"[^"\n]*"|「[^」\n]*」')
RE_END_MARK = re.compile(r"[。！？!?…]")
RE_ENDING_PUNCT = set("。！？!?\"」』…—~")

# --- 标点检测（所有脚本共享）
RE_ENG_COMMA = re.compile(r"(?<=[一-鿿㐀-䶿豈-﫿]),|,(?=[一-鿿㐀-䶿豈-﫿])")
RE_ENG_PERIOD = re.compile(r"(?<=[一-鿿㐀-䶿豈-﫿])\.(?=[一-鿿㐀-䶿豈-﫿])")
RE_ENG_SEMICOLON = re.compile(r";(?=[一-鿿㐀-䶿豈-﫿])")
RE_ELLIPSIS_STACK = re.compile(r"\.{4,}|…{2,}|…\.{2,}|\.{2,}…")
RE_ELLIPSIS = re.compile(r"…{1,}|\.{3,}|。{2,}")
RE_DASH = re.compile(r"——{0,}|—–|–—")
RE_DOUBLE_HYPHEN = re.compile(r"--")
RE_BANG_STACK = re.compile(r"！{2,}|!{2,}|！!|!！")
RE_QUESTION_STACK = re.compile(r"？{2,}|\?{2,}|？\?|\?？")
RE_SEPARATOR_LINE = re.compile(r"^\s*(?:——{2,}|—{3,}|\*{3,}|-{3,}|={3,}|_{3,})\s*$")
RE_FULL_SPACE = re.compile(r"　")
RE_TRAIL_WS = re.compile(r"[ \t]+$", re.M)

# --- 向后兼容别名（避免破坏现有代码，逐步迁移）
_CHAPTER_NO_RE = RE_CHAPTER_NO
_CHAPTER_FILE_RE = RE_CHAPTER_FILE
_OUTLINE_FILE_RE = RE_OUTLINE_FILE
_CHINESE_CHAR_RE = RE_CHINESE_CHAR
_CHINESE_WORD_RE = RE_CHINESE_WORD
_MULTI_BLANK_LINE_RE = RE_MULTI_BLANK_LINE


# =============================================================================
# BM25 中文检索引擎（v1.1.0 新增，entity_index.py 和 rag_retriever.py 共享）
# =============================================================================
# 设计原则：
#   1. 纯标准库，零第三方依赖
#   2. 中文分词：去停用字单字 + 滑窗双字词（无jieba依赖）
#   3. 两级检索：BM25粗筛 + TF-IDF精排
#   4. 支持序列化/反序列化（JSON）
# =============================================================================

import math as _math
from collections import Counter as _Counter

# BM25 标准参数
BM25_K1 = 1.5
BM25_B = 0.75

# 中文停用字（无jieba依赖的简易方案）
_STOP_CHARS = set(
    "的了吗呢吧啊呀哦嗯么着过在有了是不也就都还要这个那个一个什么怎么哪里为什么"
)

# 轻场景触发关键词（entity_index和rag_retriever共享）
LIGHT_SCENE_KEYWORDS = [
    "赶路", "过场", "日常", "过渡", "转场", "路途", "行路",
    "出发", "启程", "到达", "抵达", "离开", "告别", "休息", "夜宿",
]


def tokenize_chinese(text):
    """简易中文分词：去停用字单字 + 滑窗双字词。

    返回 list[str]：分词结果。
    纯标准库实现，不依赖 jieba。
    """
    chars = [c for c in text if c.strip() and c not in _STOP_CHARS]
    # 单字
    unigrams = chars
    # 双字词（滑窗）
    bigrams = [
        text[i:i + 2] for i in range(len(text) - 1)
        if text[i] not in _STOP_CHARS and text[i + 1] not in _STOP_CHARS
    ]
    return unigrams + bigrams


# 向后兼容别名
_tokenize_chinese = tokenize_chinese


class BM25Index:
    """BM25 索引：对文档集合建立倒排索引，支持 BM25 评分查询。

    标准 BM25 参数：k1=1.5, b=0.75。

    用法：
        docs = [(1, "第1章摘要文本"), (2, "第2章摘要文本")]
        idx = BM25Index(docs)
        tokens = tokenize_chinese("林雷的战斗")
        results = idx.search(tokens, top_k=8)
    """

    def __init__(self, documents, k1=BM25_K1, b=BM25_B):
        """documents: [(doc_id, text), ...]"""
        self.k1 = k1
        self.b = b
        self.doc_ids = [d[0] for d in documents]
        self.doc_tokens = {}   # doc_id -> [tokens]
        self.doc_len = {}      # doc_id -> int
        self.df = _Counter()   # term -> 文档频率
        self.avgdl = 0.0
        self._build(documents)

    def _build(self, documents):
        total_len = 0
        for doc_id, text in documents:
            tokens = tokenize_chinese(text)
            self.doc_tokens[doc_id] = tokens
            self.doc_len[doc_id] = len(tokens)
            total_len += len(tokens)
            # 统计文档频率（每个词在文档中出现只计一次）
            unique_terms = set(tokens)
            for term in unique_terms:
                self.df[term] += 1
        n = len(documents)
        self.avgdl = total_len / n if n > 0 else 0.0

    def idf(self, term):
        """计算 IDF：log((N - df + 0.5) / (df + 0.5) + 1)。"""
        n = len(self.doc_ids)
        df = self.df.get(term, 0)
        return _math.log((n - df + 0.5) / (df + 0.5) + 1)

    def score(self, query_tokens, doc_id):
        """计算单文档的 BM25 得分。"""
        if doc_id not in self.doc_tokens:
            return 0.0
        doc_tokens = self.doc_tokens[doc_id]
        dl = self.doc_len[doc_id]
        tf_map = _Counter(doc_tokens)
        score = 0.0
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf = self.idf(qt)
            # BM25 公式
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl) if self.avgdl > 0 else tf
            score += idf * numerator / denominator if denominator > 0 else 0
        return score

    def search(self, query_tokens, top_k=8):
        """检索 top-k 文档，返回 [(doc_id, score, matched_terms), ...]。

        matched_terms: [(term, frequency), ...] 按词频降序，最多返回10个。
        """
        results = []
        for doc_id in self.doc_ids:
            s = self.score(query_tokens, doc_id)
            if s > 0:
                doc_tf = _Counter(self.doc_tokens[doc_id])
                matched = [(t, doc_tf[t]) for t in query_tokens if t in doc_tf]
                matched.sort(key=lambda x: -x[1])
                results.append((doc_id, s, matched[:10]))
        results.sort(key=lambda x: -x[1])
        return results[:top_k]

    def to_dict(self):
        """序列化为 dict（用于保存到 JSON）。"""
        return {
            "k1": self.k1,
            "b": self.b,
            "doc_ids": self.doc_ids,
            "doc_tokens": self.doc_tokens,
            "doc_len": self.doc_len,
            "df": dict(self.df),
            "avgdl": self.avgdl,
        }

    @classmethod
    def from_dict(cls, data):
        """从 dict 反序列化。"""
        idx = cls.__new__(cls)
        idx.k1 = data.get("k1", BM25_K1)
        idx.b = data.get("b", BM25_B)
        idx.doc_ids = data.get("doc_ids", [])
        idx.doc_tokens = data.get("doc_tokens", {})
        idx.doc_len = data.get("doc_len", {})
        idx.df = _Counter(data.get("df", {}))
        idx.avgdl = data.get("avgdl", 0.0)
        return idx


def tfidf_rerank(query_tokens, candidates_text, top_k=4):
    """片段级 TF-IDF 精排（BM25粗筛后再精排）。

    candidates_text: [(doc_id, text), ...]
    返回: [(doc_id, score, matched_terms), ...]
    matched_terms: [(term, frequency, score), ...]
    """
    if not candidates_text:
        return []
    n = len(candidates_text)
    df = _Counter()
    doc_tokens_map = {}
    for doc_id, text in candidates_text:
        tokens = tokenize_chinese(text)
        doc_tokens_map[doc_id] = tokens
        for term in set(tokens):
            df[term] += 1
    results = []
    for doc_id, text in candidates_text:
        tokens = doc_tokens_map[doc_id]
        tf_map = _Counter(tokens)
        dl = len(tokens)
        avgdl = sum(len(t) for t in doc_tokens_map.values()) / max(n, 1)
        score = 0.0
        matched = []
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf = _math.log((n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
            # BM25-like TF normalization
            norm_tf = tf / (tf + 1.5 * (0.25 + 0.75 * dl / max(avgdl, 1)))
            s = idf * norm_tf
            score += s
            matched.append((qt, tf, round(s, 4)))
        if score > 0:
            matched.sort(key=lambda x: -x[2])
            results.append((doc_id, score, matched[:8]))
    results.sort(key=lambda x: -x[1])
    return results[:top_k]


# 向后兼容别名
_tfidf_rerank = tfidf_rerank


def is_light_scene(text_or_queries):
    """判断是否为轻场景查询（过场/赶路/日常等）。

    接受 str 或 list[str]。
    """
    if isinstance(text_or_queries, (list, tuple)):
        text = " ".join(str(q) for q in text_or_queries)
    else:
        text = str(text_or_queries)
    return any(kw in text for kw in LIGHT_SCENE_KEYWORDS)


# =============================================================================
# 文件 I/O
# =============================================================================

def read_text(path, encoding="utf-8-sig") -> Optional[str]:
    """安全读取文本文件，失败返回None。

    默认使用 utf-8-sig 编码（兼容 BOM），与现有脚本保持一致。
    """
    try:
        return Path(path).read_text(encoding=encoding)
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
        return None


def read_json(path, default=None) -> Any:
    """安全读取JSON文件，失败返回default。"""
    if default is None:
        default = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return default


def write_text(path, content, encoding="utf-8") -> bool:
    """安全写入文本文件。"""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return True
    except (IOError, PermissionError, OSError) as e:
        print(f"[ERROR] 写入失败 {path}: {e}", file=sys.stderr)
        return False


def write_json(path, data, indent=2) -> bool:
    """安全写入JSON文件（ensure_ascii=False）。"""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return True
    except (IOError, TypeError, PermissionError, OSError) as e:
        print(f"[ERROR] 保存JSON失败 {path}: {e}", file=sys.stderr)
        return False


def ensure_dir(path) -> Path:
    """确保目录存在，返回Path对象。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def backup_file(path) -> Optional[Path]:
    """备份文件，返回备份路径。失败返回None。

    备份命名：原文件名 + .bak.{时间戳}
    """
    src = Path(path)
    if not src.exists():
        return None
    try:
        backup_name = f"{src.name}.bak.{timestamp_compact()}"
        backup_path = src.parent / backup_name
        shutil.copy2(src, backup_path)
        return backup_path
    except OSError:
        return None


def file_exists(path) -> bool:
    """检查文件是否存在。"""
    return Path(path).is_file()


# =============================================================================
# 书籍工程定位
# =============================================================================

def find_book_dir(path) -> Optional[Path]:
    """从给定路径查找书籍工程目录（含 追踪/ 和 大纲/ 的目录）。

    查找逻辑：
    1. 当前路径本身是否为书籍工程
    2. 当前路径的子目录中是否有一个是书籍工程
    """
    p = Path(path)
    if not p.exists():
        return None
    # 自身检查
    if (p / "追踪").exists() and (p / "大纲").exists():
        return p
    # 子目录查找
    if p.is_dir():
        for child in p.iterdir():
            if child.is_dir() and (child / "追踪").exists():
                return child
    return None


def find_latest_chapter(book_dir) -> int:
    """找到最新章节号，返回章节号int。无章节返回0。

    扫描 大纲/ 目录中的章纲文件和 正文/ 目录中的正文文件，
    取最大章节号。
    """
    book = Path(book_dir)
    max_num = 0
    for d in [book / "大纲", book / "正文"]:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file():
                n = parse_chapter_number(f.name)
                if n is not None and n > max_num:
                    max_num = n
    return max_num


def find_chapter_file(book_dir, chapter_num) -> Optional[Path]:
    """查找指定章节号的正文文件，兼容多种命名格式。

    优先在 正文/ 目录查找，支持：
    - 第037章_xxx.md
    - 第37章 xxx.md
    - chapter_37.md
    """
    book = Path(book_dir)
    manuscript = book / "正文"
    if not manuscript.exists():
        return None
    num_str = str(chapter_num)
    for f in manuscript.iterdir():
        if not f.is_file():
            continue
        n = parse_chapter_number(f.name)
        if n is not None and n == chapter_num:
            return f
    return None


def find_chapter_outline(book_dir, chapter_num) -> Optional[Path]:
    """查找指定章节号的章纲文件，兼容多种命名格式。

    优先在 大纲/ 目录查找，支持：
    - 章纲_第037章.md
    - 第37章_章纲.md
    - 第37章_xxx.md
    """
    book = Path(book_dir)
    outline = book / "大纲"
    if not outline.exists():
        return None
    for f in outline.iterdir():
        if not f.is_file():
            continue
        n = parse_chapter_number(f.name)
        if n is not None and n == chapter_num:
            return f
    return None


# =============================================================================
# 对标消费链路（v1.1.0 新增，参考 oh-story 的双目录权威索引）
# =============================================================================
# 设计原则：
#   1. 三路径查找：项目级对标 → 全局拆文库 → 内置样例
#   2. 完整性检查：写前验证对标数据是否齐全
#   3. 零依赖：纯 pathlib + json，不引入外部库
# =============================================================================

def find_benchmark_path(book_dir, benchmark_name, sub_path=None):
    """对标书路径查找（三优先级权威索引）。

    优先级（从高到低）：
      1. {书籍工程}/对标/{书名}/          — 项目级，最权威，此书专属
      2. {工作区根}/拆文库/{书名}/         — 全局级，跨项目共享
      3. {skill根}/demo/拆文库/{书名}/      — 内置样例，开箱即用

    Args:
        book_dir: 书籍工程目录（用于定位1、2级路径）
        benchmark_name: 对标书名（如"盘龙"、"斗破苍穹"）
        sub_path: 可选，对标书内的子路径（如"剧情/情绪模块.md"）

    Returns:
        Path 或 None（找不到时返回None，不抛异常）

    用法：
        from common import find_benchmark_path
        path = find_benchmark_path("我的小说", "盘龙", "剧情/情绪模块.md")
        if path:
            text = read_text(path)
    """
    book = Path(book_dir).resolve()

    # 1. 项目级对标（优先级最高）
    project_benchmark = book / "对标" / benchmark_name
    if project_benchmark.exists():
        return project_benchmark / sub_path if sub_path else project_benchmark

    # 2. 全局拆文库（向上查找两级）
    for level in [1, 2]:
        if level <= len(book.parents):
            root = book.parents[level - 1]
            global_decon = root / "拆文库" / benchmark_name
            if global_decon.exists():
                return global_decon / sub_path if sub_path else global_decon

    # 3. 内置样例（skill自带的demo拆文库）
    skill_root = Path(__file__).resolve().parent.parent
    demo_decon = skill_root / "demo" / "拆文库" / benchmark_name
    if demo_decon.exists():
        return demo_decon / sub_path if sub_path else demo_decon

    return None


def list_benchmarks(book_dir=None):
    """列出所有可用的对标书（扫描三个路径）。

    返回：[{name, source, path}, ...]
    source: "project" / "global" / "demo"
    """
    results = []
    seen = set()

    def _scan_dir(d, source):
        if d and d.exists():
            for child in d.iterdir():
                if child.is_dir() and child.name not in seen:
                    seen.add(child.name)
                    results.append({
                        "name": child.name,
                        "source": source,
                        "path": str(child),
                    })

    if book_dir:
        book = Path(book_dir).resolve()
        _scan_dir(book / "对标", "project")
        for level in [1, 2]:
            if level <= len(book.parents):
                _scan_dir(book.parents[level - 1] / "拆文库", "global")

    skill_root = Path(__file__).resolve().parent.parent
    _scan_dir(skill_root / "demo" / "拆文库", "demo")

    return results


# 对标书完整性检查：哪些文件是"完整对标"必须有的
_REQUIRED_BENCHMARK_FILES = [
    ("剧情/情绪模块.md", "读者需求/情绪引擎/可复用模块"),
    ("剧情/节奏.md", "关键信息推进/情绪触动点/爆发节奏"),
    ("文风.md", "句长/标点/对话潜台词/原文锚点"),
]


def check_benchmark_completeness(book_dir, benchmark_name=None):
    """检查对标数据完整性（写前检查，避免对标数据缺失导致质量下降）。

    Args:
        book_dir: 书籍工程目录
        benchmark_name: 对标书名，None则从设定中自动提取

    Returns:
        dict: {
            "status": "ok" | "warn" | "fail",
            "benchmark_name": str,
            "missing": [(rel_path, description), ...],
            "found": [(rel_path, description), ...],
            "recommendations": [str, ...],
        }
    """
    book = Path(book_dir).resolve()

    # 自动提取主对标书（从设定/题材定位.md或读者契约.md）
    if benchmark_name is None:
        benchmark_name = _extract_main_benchmark(book)
        if benchmark_name is None:
            return {
                "status": "warn",
                "benchmark_name": None,
                "missing": [],
                "found": [],
                "recommendations": [
                    "未设置主对标书，跳过完整性检查。",
                    '可在「设定/题材定位.md」或「设定/读者契约.md」中填写主对标书字段。',
                ],
            }

    base = find_benchmark_path(book_dir, benchmark_name)
    if base is None:
        return {
            "status": "fail",
            "benchmark_name": benchmark_name,
            "missing": _REQUIRED_BENCHMARK_FILES[:],
            "found": [],
            "recommendations": [
                f'对标书「{benchmark_name}」在三个路径均未找到。',
                f'请先拆文：python novel-cli.py deconstruct <原文路径> --output "对标/{benchmark_name}"',
                f'或放到全局拆文库：<工作区>/拆文库/{benchmark_name}/',
            ],
        }

    missing = []
    found = []
    for rel_path, description in _REQUIRED_BENCHMARK_FILES:
        full = base / rel_path
        if full.exists():
            found.append((rel_path, description))
        else:
            missing.append((rel_path, description))

    if missing:
        return {
            "status": "fail",
            "benchmark_name": benchmark_name,
            "missing": missing,
            "found": found,
            "recommendations": [
                f'对标书「{benchmark_name}」缺少 {len(missing)} 个核心文件。',
                f'请重跑拆文七阶段管道，确保生成：{"、".join(m[0] for m in missing)}',
            ],
        }

    return {
        "status": "ok",
        "benchmark_name": benchmark_name,
        "missing": [],
        "found": found,
        "recommendations": [f'对标书「{benchmark_name}」数据完整，{len(found)}个核心文件齐备。'],
    }


def _extract_main_benchmark(book_dir):
    """从书籍设定中自动提取主对标书名。

    查找顺序：
      1. 设定/题材定位.md 中的「主对标书」或「对标」字段
      2. 设定/读者契约.md 中的「对标书」字段
      3. None（未找到）
    """
    book = Path(book_dir).resolve()
    candidate_files = [
        book / "设定" / "题材定位.md",
        book / "设定" / "读者契约.md",
    ]
    keywords = ["主对标书", "对标书", "对标作品", "参考作品", "对标"]

    for f in candidate_files:
        if not f.exists():
            continue
        text = read_text(f) or ""
        for line in text.splitlines():
            for kw in keywords:
                if kw in line:
                    # 提取冒号或空格后的书名
                    for sep in ["：", ":", " ", "　"]:
                        if sep in line:
                            name = line.split(sep, 1)[1].strip()
                            # 清理常见符号
                            name = name.strip("《》<>[]()（）『』「」\"'` \t")
                            if name and len(name) <= 30:
                                return name
    return None


# =============================================================================
# 文本处理
# =============================================================================

def count_chinese_chars(text) -> int:
    """统计中文字符数。"""
    return len(_CHINESE_CHAR_RE.findall(text))


def count_chars(text) -> int:
    """统计总字符数（不含空白）。"""
    return len(re.sub(r"\s+", "", text))


def split_paragraphs(text) -> List[str]:
    """按空行分段，返回非空段落列表。"""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def truncate_text(text, max_chars) -> str:
    """截断文本到指定字数，在段落边界截断。

    尽量在最后一个完整段落处截断，避免断句。
    """
    if count_chars(text) <= max_chars:
        return text
    paragraphs = split_paragraphs(text)
    result = []
    total = 0
    for p in paragraphs:
        if total + count_chars(p) > max_chars and result:
            break
        result.append(p)
        total += count_chars(p)
    return "\n\n".join(result)


def extract_chinese_words(text) -> List[str]:
    """提取中文词（2-4字连续中文字符串）。"""
    return _CHINESE_WORD_RE.findall(text)


def normalize_whitespace(text) -> str:
    """规范化空白：多个空行变一个，行首尾去空格。"""
    # 行首尾去空格
    lines = [line.strip() for line in text.split("\n")]
    # 多个空行变一个
    text = "\n".join(lines)
    text = _MULTI_BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


# =============================================================================
# 章节解析
# =============================================================================

def parse_chapter_number(filename) -> Optional[int]:
    """从文件名解析章节号，支持多种格式。

    支持格式：
    - 第037章_xxx.md -> 37
    - 第37章 xxx.md -> 37
    - 第37章.md -> 37
    - chapter_37.md -> 37
    - ch37.md -> 37
    """
    # 优先匹配"第N章"格式
    m = _CHAPTER_NO_RE.search(filename)
    if m:
        return int(m.group(1))
    # 兼容 chapter_N / chN 格式
    m = re.search(r"[Cc]hapter[_\-]?(\d+)", filename)
    if m:
        return int(m.group(1))
    m = re.search(r"[Cc]h(\d+)", filename)
    if m:
        return int(m.group(1))
    return None


def parse_summary_entries(summary_text) -> List[Dict]:
    """解析章节摘要，返回每章的摘要dict列表。

    期望格式：### 第N章 标题  下跟字段
    返回 [{"chapter": 37, "title": "...", "fields": {...}}, ...]
    """
    entries = []
    current = None
    for line in summary_text.split("\n"):
        # 匹配章节标题行
        m = re.match(r"###\s*第(\d+)章[：\s]*(.*)", line)
        if m:
            if current:
                entries.append(current)
            current = {
                "chapter": int(m.group(1)),
                "title": m.group(2).strip(),
                "fields": {},
            }
        elif current and line.startswith("- ") and "：" in line:
            # 解析字段行 "- 字段名：内容"
            key, _, value = line.lstrip("- ").partition("：")
            current["fields"][key.strip()] = value.strip()
    if current:
        entries.append(current)
    return entries


def parse_foreshadow_ledger(ledger_text) -> List[Dict]:
    """解析伏笔台账，返回伏笔条目列表。

    期望 Markdown 表格格式，提取 | F1-03 | ... | 行。
    返回 [{"id": "F1-03", "columns": [...]}, ...]
    """
    entries = []
    header_seen = False
    for line in ledger_text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header_seen = False
            continue
        # 跳过分隔行 |---|---|
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            header_seen = True
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not header_seen:
            continue  # 跳过表头
        if cells and re.match(r"^F\d+-\d+$", cells[0]):
            entries.append({
                "id": cells[0],
                "columns": cells[1:] if len(cells) > 1 else [],
            })
    return entries


# =============================================================================
# 时间与版本
# =============================================================================

def timestamp() -> str:
    """ISO格式时间戳（本地时间）。"""
    return datetime.now().isoformat(timespec="seconds")


def timestamp_compact() -> str:
    """紧凑时间戳 YYYYMMDD_HHMMSS。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_version() -> str:
    """返回skill版本号。"""
    # 从 config 导入，避免循环依赖直接读取
    try:
        from config import SKILL_VERSION
        return SKILL_VERSION
    except ImportError:
        return "unknown"


# =============================================================================
# 输出格式化
# =============================================================================

def print_json(data, indent=2):
    """打印JSON到stdout。"""
    print(json.dumps(data, ensure_ascii=False, indent=indent))


def print_table(headers, rows):
    """打印简单的ASCII表格。

    自动计算列宽，对齐输出。
    """
    if not rows:
        print("| " + " | ".join(headers) + " |")
        return
    # 计算每列最大宽度
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))
    # 表头
    header_line = "| " + " | ".join(
        str(h).ljust(col_widths[i]) for i, h in enumerate(headers)
    ) + " |"
    separator = "|-" + "-|-".join(
        "-" * col_widths[i] for i in range(len(headers))
    ) + "-|"
    print(header_line)
    print(separator)
    # 数据行
    for row in rows:
        cells = [str(c) for c in row]
        # 不足的列补空
        while len(cells) < len(headers):
            cells.append("")
        line = "| " + " | ".join(
            cells[i].ljust(col_widths[i]) for i in range(len(headers))
        ) + " |"
        print(line)


def print_section(title, char="="):
    """打印分节标题。"""
    width = max(40, len(title) + 4)
    print(f"\n{char * width}")
    print(f"{title:^{width}}")
    print(f"{char * width}")


# Windows 终端颜色代码
_COLORS = {
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def colorize(text, color) -> str:
    """简单的颜色输出（Windows兼容）。

    如果终端不支持颜色（如重定向到文件），原样返回文本。
    Windows 10+ 通过 os.system 激活 ANSI 支持。
    """
    if not sys.stdout.isatty():
        return text
    # Windows 激活 ANSI 转义序列
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # STD_OUTPUT_HANDLE = -11
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            return text
    code = _COLORS.get(color, "")
    reset = _COLORS.get("reset", "")
    return f"{code}{text}{reset}"


# =============================================================================
# 模块元信息
# =============================================================================

__version__ = "1.1.0"
__all__ = [
    # 文件 I/O
    "read_text", "read_json", "write_text", "write_json",
    "ensure_dir", "backup_file", "file_exists",
    # 书籍工程定位
    "find_book_dir", "find_latest_chapter", "find_chapter_file",
    "find_chapter_outline",
    # 文本处理
    "count_chinese_chars", "count_chars", "split_paragraphs",
    "truncate_text", "extract_chinese_words", "normalize_whitespace",
    # 章节解析
    "parse_chapter_number", "parse_summary_entries", "parse_foreshadow_ledger",
    # 时间与版本
    "timestamp", "timestamp_compact", "get_version",
    # 输出格式化
    "print_json", "print_table", "print_section", "colorize",
    # 预编译正则（全skill共享，v1.1.0新增）
    "RE_CHAPTER_NO", "RE_CHAPTER_FILE", "RE_CHAPTER_TITLE",
    "RE_OUTLINE_FILE", "RE_SECTION_OUTLINE",
    "RE_CHINESE_CHAR", "RE_CJK_CHAR", "RE_CHINESE_WORD", "RE_CJK_RUN",
    "RE_MULTI_BLANK_LINE",
    "RE_SENT_SPLIT", "RE_DIALOGUE", "RE_DIALOGUE_QUOTE",
    "RE_END_MARK", "RE_ENDING_PUNCT",
    "RE_ENG_COMMA", "RE_ENG_PERIOD", "RE_ENG_SEMICOLON",
    "RE_ELLIPSIS_STACK", "RE_ELLIPSIS", "RE_DASH", "RE_DOUBLE_HYPHEN",
    "RE_BANG_STACK", "RE_QUESTION_STACK", "RE_SEPARATOR_LINE",
    "RE_FULL_SPACE", "RE_TRAIL_WS",
    # BM25 检索引擎（v1.1.0新增，entity_index和rag_retriever共享）
    "BM25_K1", "BM25_B",
    "LIGHT_SCENE_KEYWORDS",
    "tokenize_chinese",
    "BM25Index",
    "tfidf_rerank",
    "is_light_scene",
    # 对标消费链路（v1.1.0新增，三路径权威索引）
    "find_benchmark_path",
    "list_benchmarks",
    "check_benchmark_completeness",
]
