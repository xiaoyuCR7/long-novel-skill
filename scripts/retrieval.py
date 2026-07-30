#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retrieval.py — 统一检索系统 v1.0.0（纯标准库，无第三方依赖）。

合并 entity_index.py + rag_retriever.py，从 common.py 导入共享 BM25Index，
消除 ~400 行重复代码。统一索引文件为 追踪/retrieval_index.json。

核心功能：
  1) build    — 构建统一索引（实体映射+章节RAG索引+增量更新）
  2) query    — BM25 两级语义检索（粗筛BM25 + 精排TF-IDF）
  3) entities — 精确实体→章节查找（含模糊回退）
  4) grep     — 在正文中抓取实体/关键词出现的原文行
  5) status   — 索引覆盖率、缓存命中率、情绪/实体统计
  6) context  — 生成写前上下文建议（next_plot_context.md）

用法：
  python scripts/retrieval.py build "{书名目录}"
  python scripts/retrieval.py query "{书名目录}" "林雷的战斗场景" --top 4
  python scripts/retrieval.py entities "{书名目录}" 林雷 盘龙戒指
  python scripts/retrieval.py grep "{书名目录}" 林雷 --chapters 1 3 5
  python scripts/retrieval.py status "{书名目录}"
  python scripts/retrieval.py context "{书名目录}" "查询文本"

退出码：0 = 成功；1 = 查询无命中；2 = 参数/文件错误。
"""

import argparse
import glob
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter

# 从 common.py 导入共享 BM25 实现（单源真相）
try:
    from common import BM25Index, tokenize_chinese
    _USE_COMMON_BM25 = True
except ImportError:
    _USE_COMMON_BM25 = False

# ---------------------------------------------------------------------------
# 常量 / 配置
# ---------------------------------------------------------------------------

INDEX_FILE = "retrieval_index.json"
CACHE_FILE = "retrieval_cache.json"
NEXT_PLOT_CTX_FILE = "next_plot_context.md"

BM25_K1 = 1.5
BM25_B = 0.75
INDEX_VERSION = "2.0.0"  # v2.0: 合并 entity_index + rag_retriever

# 轻场景关键词
LIGHT_SCENE_KEYWORDS = [
    "赶路", "过场", "日常", "过渡", "转场", "路途", "行路",
    "出发", "启程", "到达", "抵达", "离开", "告别", "休息", "夜宿",
]

# 中文停用字
_STOP_CHARS = set("的了吗呢吧啊呀哦嗯么着过在有了是不也就都还要这个那个一个什么怎么哪里为什么")

# 摘要解析正则
ENTRY_RE = re.compile(r"^###\s*第\s*(\d+)\s*章[：:\s]*(.*)$", re.M)
ENTITY_FIELD_RE = re.compile(r"关键实体[：:](.*?)(?:\n\s*-\s|\n###|\Z)", re.S)
EMOTION_FIELD_RE = re.compile(r"情绪基调[：:](.*?)(?:\n|$)", re.S)
SUMMARY_FIELD_RE = re.compile(r"章节摘要[：:](.*?)(?:\n\s*-\s|\n关键|\n情绪|\n###|\Z)", re.S)

# 旧文件名（迁移用）
OLD_ENTITY_INDEX_FILE = "entity_index.json"
OLD_RAG_INDEX_FILE = "rag_index.json"
OLD_QUERY_CACHE_FILE = "query_cache.json"
OLD_RAG_CACHE_FILE = "rag_cache.json"

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _reconfigure_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _tokenize_chinese(text):
    """简易中文分词（common.py 不可用时的回退实现）。"""
    if _USE_COMMON_BM25:
        return tokenize_chinese(text)
    chars = [c for c in text if c.strip() and c not in _STOP_CHARS]
    unigrams = chars
    bigrams = [text[i:i + 2] for i in range(len(text) - 1)
               if text[i] not in _STOP_CHARS and text[i + 1] not in _STOP_CHARS]
    return unigrams + bigrams


def _file_hash(path, block_size=8192):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _parse_entities(field_text):
    text = re.sub(r"[（(][^）)]*[）)]", " ", field_text)
    parts = re.split(r"[，,、/；;\n]+", text)
    out = []
    for p in parts:
        p = p.strip().strip("。 ")
        if p and len(p) <= 20:
            out.append(p)
    return out


def _extract_emotion_tags(text):
    m = EMOTION_FIELD_RE.search(text)
    if not m:
        return []
    raw = m.group(1).strip()
    tags = re.split(r"[，,、/；;]+", raw)
    return [t.strip() for t in tags if t.strip() and len(t.strip()) <= 10]


def _extract_summary_text(text):
    m = SUMMARY_FIELD_RE.search(text)
    if m:
        return m.group(1).strip().strip("。 ")
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("关键") and not line.startswith("情绪"):
            return line[:200]
    return ""


def _get_prose_path(book_root, chapter_num):
    prose_dir = os.path.join(book_root, "正文")
    pattern = os.path.join(prose_dir, f"*{chapter_num:03d}*.md")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    pattern2 = os.path.join(prose_dir, f"*第*{chapter_num}*章*.md")
    matches2 = glob.glob(pattern2)
    return matches2[0] if matches2 else None


def _read_snippet(file_path, query_tokens, max_len=300):
    if not os.path.isfile(file_path):
        return ""
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except (OSError, ValueError):
        return ""
    paragraphs = re.split(r"\n\s*\n", content)
    query_set = set(query_tokens)
    best_score, best_para = 0, ""
    for para in paragraphs:
        para_tokens = set(_tokenize_chinese(para))
        overlap = len(para_tokens & query_set)
        if overlap > best_score and len(para.strip()) > 10:
            best_score = overlap
            best_para = para.strip()
    if best_para:
        return best_para[:max_len] + ("..." if len(best_para) > max_len else "")
    return content[:200].strip() + "..."


def _load_chapter_meta(book_root, chapter_num):
    meta_path = os.path.join(book_root, "追踪", "chapter_meta", f"第{chapter_num}章.meta.json")
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_light_scene(query):
    return any(kw in query for kw in LIGHT_SCENE_KEYWORDS)


# ---------------------------------------------------------------------------
# 本地 BM25Index（common.py 不可用时的回退）
# ---------------------------------------------------------------------------

class _LocalBM25Index:
    """BM25 回退实现（仅在 common.BM25Index 不可用时使用）。"""

    def __init__(self, documents, k1=BM25_K1, b=BM25_B):
        self.k1 = k1
        self.b = b
        self.doc_ids = [d[0] for d in documents]
        self.doc_tokens = {}
        self.doc_len = {}
        self.df = Counter()
        self.avgdl = 0.0
        self._build(documents)

    def _build(self, documents):
        total_len = 0
        for doc_id, text in documents:
            tokens = _tokenize_chinese(text)
            self.doc_tokens[doc_id] = tokens
            self.doc_len[doc_id] = len(tokens)
            total_len += len(tokens)
            for term in set(tokens):
                self.df[term] += 1
        n = len(documents)
        self.avgdl = total_len / n if n > 0 else 0.0

    def idf(self, term):
        n = len(self.doc_ids)
        df = self.df.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def score(self, query_tokens, doc_id):
        if doc_id not in self.doc_tokens:
            return 0.0
        doc_tokens = self.doc_tokens[doc_id]
        dl = self.doc_len[doc_id]
        tf_map = Counter(doc_tokens)
        score = 0.0
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf_val = self.idf(qt)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf_val * numerator / denominator
        return score

    def search(self, query_tokens, top_k=8):
        results = []
        for doc_id in self.doc_ids:
            s = self.score(query_tokens, doc_id)
            if s > 0:
                doc_tf = Counter(self.doc_tokens[doc_id])
                matched = [(t, doc_tf[t]) for t in query_tokens if t in doc_tf]
                matched.sort(key=lambda x: -x[1])
                results.append((doc_id, s, matched[:10]))
        results.sort(key=lambda x: -x[1])
        return results[:top_k]


def _make_bm25(documents):
    """工厂函数：优先使用 common.BM25Index，回退到本地实现。"""
    if _USE_COMMON_BM25:
        return BM25Index(documents, k1=BM25_K1, b=BM25_B)
    return _LocalBM25Index(documents)


def _tfidf_rerank(query_tokens, candidates_text, top_k=4):
    if not candidates_text:
        return []
    n = len(candidates_text)
    df = Counter()
    doc_tokens_map = {}
    for doc_id, text in candidates_text:
        tokens = _tokenize_chinese(text)
        doc_tokens_map[doc_id] = tokens
        for term in set(tokens):
            df[term] += 1
    results = []
    for doc_id, text in candidates_text:
        tokens = doc_tokens_map[doc_id]
        tf_map = Counter(tokens)
        dl = len(tokens)
        avgdl = sum(len(t) for t in doc_tokens_map.values()) / max(n, 1)
        score = 0.0
        matched = []
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf_val = math.log((n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
            norm_tf = tf / (tf + 1.5 * (0.25 + 0.75 * dl / max(avgdl, 1)))
            s = idf_val * norm_tf
            score += s
            matched.append((qt, tf, round(s, 4)))
        if score > 0:
            matched.sort(key=lambda x: -x[2])
            results.append((doc_id, score, matched[:8]))
    results.sort(key=lambda x: -x[1])
    return results[:top_k]


def _relevance_label(score):
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# 索引 IO + 旧文件迁移
# ---------------------------------------------------------------------------

def _index_path(book_root):
    return os.path.join(book_root, "追踪", INDEX_FILE)


def _cache_path(book_root):
    return os.path.join(book_root, "追踪", CACHE_FILE)


def _context_path(book_root):
    return os.path.join(book_root, "追踪", NEXT_PLOT_CTX_FILE)


def _migrate_old_files(book_root):
    """首次运行时迁移旧的 entity_index.json 和 rag_index.json 到统一索引。"""
    tracking_dir = os.path.join(book_root, "追踪")
    new_path = _index_path(book_root)

    if os.path.isfile(new_path):
        return  # 已存在统一索引

    # 尝试合并旧数据
    old_entity = os.path.join(tracking_dir, OLD_ENTITY_INDEX_FILE)
    old_rag = os.path.join(tracking_dir, OLD_RAG_INDEX_FILE)

    migrated = False
    chapters = []

    if os.path.isfile(old_rag):
        try:
            with open(old_rag, "r", encoding="utf-8-sig") as f:
                rag_data = json.load(f)
            if isinstance(rag_data, dict) and "chapters" in rag_data:
                chapters = rag_data.get("chapters", [])
                migrated = True
        except (OSError, ValueError):
            pass

    # 合并实体索引中的实体信息
    entity_map = {}
    if os.path.isfile(old_entity):
        try:
            with open(old_entity, "r", encoding="utf-8-sig") as f:
                entity_data = json.load(f)
            if isinstance(entity_data, dict):
                entity_map = entity_data
                migrated = True
        except (OSError, ValueError):
            pass

    if migrated:
        # 将实体映射合并进章节条目
        for ch in chapters:
            chap = ch.get("chapter")
            if chap is not None:
                ch_entities = [ent for ent, chaps in entity_map.items() if chap in chaps]
                existing = set(ch.get("entities", []))
                for e in ch_entities:
                    if e not in existing:
                        ch.setdefault("entities", []).append(e)

        index_data = {
            "version": INDEX_VERSION,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_chapters": len(chapters),
            "indexed_chapters": len(chapters),
            "chapters": chapters,
            "entity_map": entity_map,
            "_migrated_from": "entity_index.json + rag_index.json",
        }
        os.makedirs(tracking_dir, exist_ok=True)
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        return True
    return False


def load_index(book_root):
    path = _index_path(book_root)
    if not os.path.isfile(path):
        _migrate_old_files(book_root)
    if not os.path.isfile(path):
        return None, path
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f), path
    except (OSError, ValueError):
        return None, path


def save_index(book_root, index_data):
    path = _index_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def load_cache(book_root):
    path = _cache_path(book_root)
    if not os.path.isfile(path):
        return {}, path
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f), path
    except (OSError, ValueError):
        return {}, path


def save_cache(book_root, cache):
    path = _cache_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _cache_key(query, top_k, light=False, index_hash=""):
    raw = json.dumps({"q": query, "top": top_k, "light": light, "ih": index_hash}, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _index_hash(index_data):
    if not index_data:
        return ""
    raw = f"{index_data.get('last_updated', '')}|{index_data.get('total_chapters', 0)}|{index_data.get('indexed_chapters', 0)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

# ---------------------------------------------------------------------------
# build — 构建统一索引
# ---------------------------------------------------------------------------


def _scan_chapters(book_root):
    prose_dir = os.path.join(book_root, "正文")
    if not os.path.isdir(prose_dir):
        return []
    chapters = []
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        basename = os.path.basename(path)
        m = re.search(r"第\s*(\d+)\s*章", basename)
        if m:
            chap = int(m.group(1))
            chapters.append((chap, basename, path))
    chapters.sort(key=lambda x: x[0])
    return chapters


def _scan_summary_entries(book_root):
    summary_path = os.path.join(book_root, "追踪", "章节摘要.md")
    if not os.path.isfile(summary_path):
        return {}
    with open(summary_path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    entries = list(ENTRY_RE.finditer(text))
    result = {}
    for idx, m in enumerate(entries):
        chap = int(m.group(1))
        start = m.start()
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        result[chap] = text[start:end]
    return result


def cmd_build(book_root):
    chapters = _scan_chapters(book_root)
    if not chapters:
        print("错误：正文目录下未找到章节文件", file=sys.stderr)
        return 2

    summary_entries = _scan_summary_entries(book_root)
    old_index, _ = load_index(book_root)
    old_chapters = {}
    if old_index and "chapters" in old_index:
        for ch in old_index["chapters"]:
            old_chapters[ch["chapter"]] = ch

    updated, skipped = 0, 0
    new_entries = []
    entity_map = {}

    for chap, basename, file_path in chapters:
        content_hash = _file_hash(file_path)
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
            char_count = len(re.sub(r"\s+", "", content))
        except (OSError, ValueError):
            char_count = 0

        entry_body = summary_entries.get(chap, "")
        summary_text = _extract_summary_text(entry_body)
        entities = []
        emotion_tags = []
        if entry_body:
            em = ENTITY_FIELD_RE.search(entry_body)
            if em:
                entities = _parse_entities(em.group(1))
            emotion_tags = _extract_emotion_tags(entry_body)

        title_match = re.search(r"第\s*\d+\s*章[：:\s]*(.*)\.md$", basename)
        title = title_match.group(1).strip() if title_match else ""
        if not title and entry_body:
            tm2 = ENTRY_RE.search(entry_body)
            if tm2 and tm2.group(2):
                title = tm2.group(2).strip()
        if not title:
            title = f"第{chap}章"

        old_entry = old_chapters.get(chap)
        if old_entry and old_entry.get("content_hash") == content_hash:
            new_entries.append(old_entry)
            skipped += 1
            for ent in old_entry.get("entities", []):
                entity_map.setdefault(ent, []).append(chap)
            continue

        entry = {
            "chapter": chap,
            "title": title,
            "file": os.path.relpath(file_path, book_root).replace("\\", "/"),
            "summary": summary_text,
            "entities": entities,
            "char_count": char_count,
            "emotion_tags": emotion_tags,
            "content_hash": content_hash,
            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        new_entries.append(entry)
        updated += 1

    # 构建实体映射（从章节摘要直接生成，比从摘要提取更全面）
    for ch in new_entries:
        for ent in ch.get("entities", []):
            entity_map.setdefault(ent, [])
            if ch["chapter"] not in entity_map[ent]:
                entity_map[ent].append(ch["chapter"])
    for ent in entity_map:
        entity_map[ent].sort()

    new_entries.sort(key=lambda x: x["chapter"])
    index_data = {
        "version": INDEX_VERSION,
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_chapters": len(chapters),
        "indexed_chapters": len(new_entries),
        "chapters": new_entries,
        "entity_map": entity_map,
    }
    save_index(book_root, index_data)

    print(f"检索索引已构建：{_index_path(book_root)}")
    print(f"  总章节：{len(chapters)}  已索引：{len(new_entries)}  实体：{len(entity_map)}")
    print(f"  新增/更新：{updated}  跳过（未变）：{skipped}")
    return 0


# ---------------------------------------------------------------------------
# entities — 精确实体查找
# ---------------------------------------------------------------------------


def cmd_entities(book_root, entity_names, use_grep=False):
    index_data, path = load_index(book_root)
    if not index_data:
        print(f"错误：索引不存在 {path}，先运行 build", file=sys.stderr)
        return 2

    entity_map = index_data.get("entity_map", {})
    if not entity_map:
        print("索引中无实体数据")
        return 1

    missing = []
    found_any = False
    for ent_name in entity_names:
        chapters = entity_map.get(ent_name)
        if not chapters:
            fuzzy = {k: v for k, v in entity_map.items() if ent_name in k or k in ent_name}
            if fuzzy:
                for k, v in sorted(fuzzy.items()):
                    print(f"「{ent_name}」未直接命中；近似实体「{k}」→ 第 {', '.join(map(str, v))} 章")
                    found_any = True
            else:
                missing.append(ent_name)
            continue
        print(f"「{ent_name}」→ 出现在第 {', '.join(map(str, chapters))} 章")
        found_any = True

    if missing:
        print(f"未命中实体：{'、'.join(missing)}")

    if not found_any:
        return 1
    return 0


# ---------------------------------------------------------------------------
# grep — 原文行抓取
# ---------------------------------------------------------------------------

def cmd_grep(book_root, queries, chapters=None):
    hits = []
    prose_dir = os.path.join(book_root, "正文")
    files = {}
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = re.search(r"第\s*(\d+)\s*章", os.path.basename(path))
        if m:
            files[int(m.group(1))] = path

    if chapters:
        target_chaps = chapters
    else:
        target_chaps = list(files.keys())

    for chap in sorted(target_chaps):
        path = files.get(chap)
        if not path:
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            for i, line in enumerate(f, 1):
                for q in queries:
                    if q in line:
                        s = line.strip()
                        hits.append((chap, i, s if len(s) <= 80 else s[:77] + "..."))

    if not hits:
        print(f"未找到匹配行（查询：{'、'.join(queries)}）")
        return 1

    for chap, line_no, line in hits:
        print(f"第{chap}章 L{line_no}：{line}")
    return 0


# ---------------------------------------------------------------------------
# query — BM25 两级语义检索
# ---------------------------------------------------------------------------


def cmd_query(book_root, query, top_k=5, light=False):
    if not query:
        print("错误：query 模式需要查询文本", file=sys.stderr)
        return 2

    index_data, _ = load_index(book_root)
    if not index_data or "chapters" not in index_data:
        print("错误：检索索引不存在，请先运行 build", file=sys.stderr)
        return 2

    chapters = index_data["chapters"]
    if not chapters:
        print("索引为空")
        return 1

    # 缓存
    cache, _ = load_cache(book_root)
    ih = _index_hash(index_data)
    key = _cache_key(query, top_k, light, ih)
    if key in cache:
        cached = cache[key]
        print(f"（命中查询缓存，查询时间：{cached.get('time', '?')}）")
        results = cached.get("results", [])
        _print_query_results(results, query, top_k)
        return 0 if results else 1

    query_tokens = _tokenize_chinese(query)

    # 轻场景
    if light or is_light_scene(query):
        results = _light_search(chapters, query_tokens, top_k)
        _print_query_results(results, query, top_k, light=True)
        cache[key] = {"query": query, "top": top_k, "light": light, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
        save_cache(book_root, cache)
        return 0 if results else 1

    # 全量检索：BM25 粗筛 + TF-IDF 精排
    docs = []
    for ch in chapters:
        text_parts = [ch.get("summary", "")]
        text_parts.append(" ".join(ch.get("entities", [])))
        text_parts.append(" ".join(ch.get("emotion_tags", [])))
        text_parts.append(ch.get("title", ""))
        docs.append((ch["chapter"], " ".join(text_parts)))

    bm25 = _make_bm25(docs)
    coarse = bm25.search(query_tokens, top_k=8)
    if not coarse:
        print("未找到相关章节")
        return 1

    chapter_map = {ch["chapter"]: ch for ch in chapters}
    candidate_texts = []
    for chap, _, _ in coarse:
        ch = chapter_map.get(chap)
        if ch:
            rich_text = f"{ch.get('title', '')} {ch.get('summary', '')} {' '.join(ch.get('entities', []))} {' '.join(ch.get('emotion_tags', []))}"
            candidate_texts.append((chap, rich_text))

    reranked = _tfidf_rerank(query_tokens, candidate_texts, top_k=top_k)
    bm25_scores = {chap: score for chap, score, _ in coarse}
    max_combined = 0.0
    results = []

    for chap, tfidf_score, matched in reranked:
        bm25_score = bm25_scores.get(chap, 0)
        combined = bm25_score * 0.6 + tfidf_score * 0.4
        ch = chapter_map.get(chap)
        if not ch:
            continue

        matched_keywords = []
        for token, _, _ in matched:
            if token in query and token not in matched_keywords:
                matched_keywords.append(token)
            else:
                for i in range(len(query) - 1):
                    bigram = query[i:i + 2]
                    if bigram == token and bigram not in matched_keywords:
                        matched_keywords.append(bigram)

        for ent in ch.get("entities", []):
            if any(t in ent or ent in t for t in query_tokens if len(t) >= 2):
                if ent not in matched_keywords and len(matched_keywords) < 6:
                    matched_keywords.append(ent)

        prose_path = _get_prose_path(book_root, chap)
        snippet = ""
        if prose_path:
            snippet = _read_snippet(prose_path, query_tokens, max_len=300)
        if not snippet:
            snippet = ch.get("summary", "")[:200]

        results.append({
            "chapter": chap,
            "title": ch["title"],
            "raw_score": combined,
            "matched_keywords": matched_keywords[:5],
            "snippet": snippet,
        })
        if combined > max_combined:
            max_combined = combined

    # 归一化
    for r in results:
        r["score"] = round(r["raw_score"] / max(max_combined, 0.001), 4)
        r["relevance"] = _relevance_label(r["score"])
        del r["raw_score"]

    results.sort(key=lambda x: -x["score"])
    results = results[:top_k]
    _print_query_results(results, query, top_k)

    cache[key] = {"query": query, "top": top_k, "light": light, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    save_cache(book_root, cache)

    return 0 if results else 1


def _light_search(chapters, query_tokens, top_k):
    results = []
    query_set = set(query_tokens)
    for ch in chapters:
        score = 0.0
        matched = []
        for ent in ch.get("entities", []):
            ent_tokens = set(_tokenize_chinese(ent))
            overlap = len(query_set & ent_tokens)
            if overlap > 0:
                score += overlap * 0.3
                matched.append(ent)
        if score > 0:
            results.append({
                "chapter": ch["chapter"],
                "title": ch["title"],
                "score": round(min(score, 1.0), 4),
                "matched_keywords": matched[:5],
                "snippet": ch.get("summary", "")[:200],
                "relevance": _relevance_label(score),
            })
    results.sort(key=lambda x: -x["score"])
    return results[:top_k]


def _print_query_results(results, query, top_k, light=False):
    light_tag = " [轻场景]" if light else ""
    print(f"检索结果（查询：{repr(query)}，Top {top_k}）{light_tag}")
    print(f"{'章节':<12} {'相关度':<10} {'关键词':<30} 片段")
    print("-" * 90)
    rel_map = {"high": "高", "medium": "中", "low": "低"}
    for r in results:
        rel = rel_map.get(r.get("relevance", "low"), "低")
        kw = "、".join(r.get("matched_keywords", [])[:4]) or "-"
        snip = r.get("snippet", "")[:40] or "-"
        print(f"第{r['chapter']}章：{r['title']:<8} {rel}({r['score']:.4f})  {kw:<30} {snip}")


# ---------------------------------------------------------------------------
# context — 写前上下文建议
# ---------------------------------------------------------------------------

def cmd_context(book_root, query, top_k=5):
    if not query:
        print("错误：需要查询文本", file=sys.stderr)
        return 2

    index_data, _ = load_index(book_root)
    if not index_data:
        return 2

    chapters = index_data.get("chapters", [])
    docs = []
    for ch in chapters:
        text_parts = [ch.get("summary", ""), " ".join(ch.get("entities", [])),
                      " ".join(ch.get("emotion_tags", [])), ch.get("title", "")]
        docs.append((ch["chapter"], " ".join(text_parts)))

    query_tokens = _tokenize_chinese(query)
    bm25 = _make_bm25(docs)
    coarse = bm25.search(query_tokens, top_k=top_k)
    top_chapters = [c[0] for c in coarse[:3]]

    ctx_path = _context_path(book_root)
    os.makedirs(os.path.dirname(ctx_path), exist_ok=True)
    rel_map = {"high": "高", "medium": "中", "low": "低"}
    chapter_map = {ch["chapter"]: ch for ch in chapters}

    lines = ["# 写前上下文建议", "", f"## 检索查询\n{query}", "", f"## 推荐回读章节（Top {min(3, len(top_chapters))}）", ""]
    for chap in top_chapters:
        ch = chapter_map.get(chap)
        if not ch:
            continue
        lines.append(f"### 第{chap}章：{ch.get('title', '')}")
        if ch.get("entities"):
            lines.append(f"- 关键实体：{'、'.join(ch['entities'][:8])}")
        if ch.get("summary"):
            lines.append(f"- 摘要：> {ch['summary'][:150]}")
        lines.append("")

    lines.append("---")
    lines.append(f"*生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}*")
    with open(ctx_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    rel_path = os.path.relpath(ctx_path, book_root).replace("\\", "/")
    print(f"写前上下文建议已写入：{rel_path}")
    print(f"  推荐回读：{', '.join(f'第{c}章' for c in top_chapters)}")
    return 0


# ---------------------------------------------------------------------------
# status — 索引状态
# ---------------------------------------------------------------------------

def cmd_status(book_root):
    index_data, idx_path = load_index(book_root)
    cache_data, _ = load_cache(book_root)

    print("=" * 50)
    print("统一检索系统状态")
    print("=" * 50)

    if not index_data:
        print(f"索引文件：{idx_path}")
        print("状态：未构建（请先运行 build）")
        print(f"缓存条目：{len(cache_data)}")
        return 0

    chapters = index_data.get("chapters", [])
    total = index_data.get("total_chapters", 0)
    indexed = index_data.get("indexed_chapters", 0)
    coverage = (indexed / total * 100) if total > 0 else 0
    entity_count = len(index_data.get("entity_map", {}))
    last_updated = index_data.get("last_updated", "未知")
    version = index_data.get("version", "未知")

    print(f"索引文件：{idx_path}")
    print(f"索引版本：{version}")
    print(f"最后更新：{last_updated}")
    print(f"总章节数：{total}")
    print(f"已索引章：{indexed}")
    print(f"实体数量：{entity_count}")
    print(f"覆盖率：  {coverage:.1f}%")

    all_emotions = Counter()
    total_chars = 0
    for ch in chapters:
        total_chars += ch.get("char_count", 0)
        for tag in ch.get("emotion_tags", []):
            all_emotions[tag] += 1

    print(f"总字数：  {total_chars:,}")
    if all_emotions:
        print(f"高频情绪：{'、'.join(f'{e[0]}({e[1]})' for e in all_emotions.most_common(5))}")

    print("-" * 50)
    print(f"缓存条目：{len(cache_data)}")
    return 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    _reconfigure_streams()

    ap = argparse.ArgumentParser(description="统一检索系统 v2.0：build/query/entities/grep/status/context")
    ap.add_argument("mode", choices=["build", "query", "entities", "grep", "status", "context"])
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("queries", nargs="*", help="query 模式：查询文本；entities/grep 模式：实体名")
    ap.add_argument("--top", type=int, default=5, help="返回前 N 条结果（默认 5）")
    ap.add_argument("--light", action="store_true", help="轻场景模式，跳过全量检索")
    ap.add_argument("--chapters", type=int, nargs="*", help="grep 模式：指定章节号")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)

    if args.mode == "build":
        return cmd_build(book_root)
    elif args.mode == "query":
        return cmd_query(book_root, " ".join(args.queries) if args.queries else "", args.top, args.light)
    elif args.mode == "entities":
        return cmd_entities(book_root, args.queries)
    elif args.mode == "grep":
        return cmd_grep(book_root, args.queries, args.chapters)
    elif args.mode == "status":
        return cmd_status(book_root)
    elif args.mode == "context":
        return cmd_context(book_root, " ".join(args.queries) if args.queries else "", args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
