#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""entity_index.py — 关键实体→章节索引 + BM25 两级语义检索 v2.1（纯标准库）。

v2.1: BM25Index 委托 common.py（消除重复代码）。
"""

import argparse
import glob
import json
import os
import re
import sys

ENTRY_RE = re.compile(r"^###\s*第\s*(\d+)\s*章.*$", re.M)
ENTITY_FIELD_RE = re.compile(r"关键实体[：:](.*?)(?:\n\s*-\s|\n###|\Z)", re.S)

# --- 从 common.py 导入共享实现（v2.1） ---
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from common import BM25Index, tokenize_chinese
    _USE_COMMON = True
except ImportError:
    _USE_COMMON = False

import math
import time
import hashlib
from collections import Counter

# 中文停用字（common.py 不可用时的回退）
_STOP_CHARS = set("的了吗呢吧啊呀哦嗯么着过在有了是不也就都还要这个那个一个什么怎么哪里为什么")

BM25_K1 = 1.5
BM25_B = 0.75
LIGHT_SCENE_KEYWORDS = ["赶路", "过场", "转场", "路途", "行路", "出发", "启程",
                        "到达", "抵达", "离开", "告别", "休息", "夜宿"]


def _tokenize_chinese(text):
    """简易中文分词（回退实现）。"""
    if _USE_COMMON:
        return tokenize_chinese(text)
    chars = [c for c in text if c.strip() and c not in _STOP_CHARS]
    unigrams = chars
    bigrams = [text[i:i+2] for i in range(len(text)-1)
               if text[i] not in _STOP_CHARS and text[i+1] not in _STOP_CHARS]
    return unigrams + bigrams


def parse_entities(field_text):
    text = re.sub(r"[（(][^）)]*[）)]", " ", field_text)
    parts = re.split(r"[，,、/；;\n]+", text)
    out = []
    for p in parts:
        p = p.strip().strip("。 ")
        if p and len(p) <= 20:
            out.append(p)
    return out


def build_index(book_root):
    summary = os.path.join(book_root, "追踪", "章节摘要.md")
    if not os.path.isfile(summary):
        raise FileNotFoundError(f"章节摘要.md 不存在：{summary}")
    with open(summary, "r", encoding="utf-8-sig") as f:
        text = f.read()
    entries = list(ENTRY_RE.finditer(text))
    index = {}
    for idx, m in enumerate(entries):
        chap = int(m.group(1))
        start = m.start()
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        body = text[start:end]
        fm = ENTITY_FIELD_RE.search(body)
        if not fm:
            continue
        for ent in parse_entities(fm.group(1)):
            index.setdefault(ent, [])
            if chap not in index[ent]:
                index[ent].append(chap)
    for ent in index:
        index[ent].sort()
    out_path = os.path.join(book_root, "追踪", "entity_index.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return index, out_path, len(entries)


def load_index(book_root):
    path = os.path.join(book_root, "追踪", "entity_index.json")
    if not os.path.isfile(path):
        return None, path
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f), path


def grep_chapters(book_root, entity, chapters):
    hits = []
    prose_dir = os.path.join(book_root, "正文")
    files = {}
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = re.search(r"第\s*(\d+)\s*章", os.path.basename(path))
        if m:
            files[int(m.group(1))] = path
    for chap in chapters:
        path = files.get(chap)
        if not path:
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            for i, line in enumerate(f, 1):
                if entity in line:
                    s = line.strip()
                    hits.append((chap, i, s if len(s) <= 60 else s[:57] + "..."))
    return hits


# BM25Index: 优先使用 common.py 版本，回退到本地
if _USE_COMMON:
    # common.BM25Index 接口兼容，直接使用
    pass
else:
    class BM25Index:
        """BM25 回退实现。"""
        def __init__(self, documents, k1=BM25_K1, b=BM25_B):
            self.k1 = k1; self.b = b
            self.doc_ids = [d[0] for d in documents]
            self.doc_tokens = {}; self.doc_len = {}; self.df = Counter(); self.avgdl = 0.0
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
            n = len(self.doc_ids); df = self.df.get(term, 0)
            return math.log((n - df + 0.5) / (df + 0.5) + 1)
        def score(self, query_tokens, doc_id):
            if doc_id not in self.doc_tokens: return 0.0
            doc_tokens = self.doc_tokens[doc_id]; dl = self.doc_len[doc_id]
            tf_map = Counter(doc_tokens); score = 0.0
            for qt in query_tokens:
                if qt not in tf_map: continue
                tf = tf_map[qt]; idf_val = self.idf(qt)
                score += idf_val * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
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
    if _USE_COMMON:
        return BM25Index(documents, k1=BM25_K1, b=BM25_B)
    return BM25Index(documents)


def _tfidf_rerank(query_tokens, candidates_text, top_k=4):
    if not candidates_text: return []
    n = len(candidates_text); df = Counter(); doc_tokens_map = {}
    for doc_id, text in candidates_text:
        tokens = _tokenize_chinese(text)
        doc_tokens_map[doc_id] = tokens
        for term in set(tokens): df[term] += 1
    results = []
    for doc_id, text in candidates_text:
        tokens = doc_tokens_map[doc_id]; tf_map = Counter(tokens); dl = len(tokens)
        avgdl = sum(len(t) for t in doc_tokens_map.values()) / max(n, 1)
        score = 0.0; matched = []
        for qt in query_tokens:
            if qt not in tf_map: continue
            tf = tf_map[qt]
            idf_val = math.log((n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
            norm_tf = tf / (tf + 1.5 * (0.25 + 0.75 * dl / max(avgdl, 1)))
            s = idf_val * norm_tf; score += s
            matched.append((qt, tf, round(s, 4)))
        if score > 0:
            matched.sort(key=lambda x: -x[2])
            results.append((doc_id, score, matched[:8]))
    results.sort(key=lambda x: -x[1])
    return results[:top_k]


def _query_cache_path(book_root):
    return os.path.join(book_root, "追踪", "query_cache.json")


def _cache_key(queries, top_k, light=False):
    raw = json.dumps({"q": queries, "top": top_k, "light": light}, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_query_cache(book_root):
    path = _query_cache_path(book_root)
    if not os.path.isfile(path): return {}, path
    try:
        with open(path, "r", encoding="utf-8-sig") as f: return json.load(f), path
    except (OSError, ValueError): return {}, path


def save_query_cache(book_root, cache):
    path = _query_cache_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def is_light_scene(queries):
    text = " ".join(queries)
    return any(kw in text for kw in LIGHT_SCENE_KEYWORDS)


def load_chapter_meta(book_root, chapter_num):
    meta_path = os.path.join(book_root, "追踪", "chapter_meta", f"第{chapter_num}章.meta.json")
    if not os.path.isfile(meta_path): return None
    try:
        with open(meta_path, "r", encoding="utf-8-sig") as f: return json.load(f)
    except (OSError, ValueError): return None


def _tf_score(query_tokens, doc_text):
    if not query_tokens: return 0.0
    doc_tokens = _tokenize_chinese(doc_text)
    if not doc_tokens: return 0.0
    doc_freq = Counter(doc_tokens); doc_total = len(doc_tokens)
    score = 0.0
    for qt in query_tokens:
        if qt in doc_freq: score += (doc_freq[qt] / (doc_total + 1))
    return score / len(query_tokens)


def _recency_boost(chapter_num, current_chapter, decay=0.02):
    if current_chapter is None or chapter_num is None: return 1.0
    distance = current_chapter - chapter_num
    if distance <= 0: return 1.0
    return math.exp(-decay * distance)


def semantic_search(book_root, queries, top_k=5, light=False):
    summary_path = os.path.join(book_root, "追踪", "章节摘要.md")
    if not os.path.isfile(summary_path):
        raise FileNotFoundError(f"章节摘要.md 不存在：{summary_path}")
    with open(summary_path, "r", encoding="utf-8-sig") as f: text = f.read()
    entries = list(ENTRY_RE.finditer(text))
    if not entries: return []
    if light or is_light_scene(queries):
        index, _ = load_index(book_root)
        if index:
            results = []
            query_tokens = [t for q in queries for t in _tokenize_chinese(q)]
            for ent, chapters in index.items():
                if any(qt in ent or ent in qt for qt in query_tokens):
                    for chap in chapters[:3]:
                        meta = load_chapter_meta(book_root, chap)
                        results.append((chap, 0.5, f"实体索引命中：{ent}", [(ent, 1)], meta))
            results.sort(key=lambda x: -x[1])
            return results[:top_k]
        return []
    docs = []; entry_data = []
    for idx, m in enumerate(entries):
        chap = int(m.group(1)); start = m.start()
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        body = text[start:end]
        docs.append((chap, body))
        first_line = body.split("\n", 1)[0].strip() if "\n" in body else body[:60]
        entry_data.append((chap, body, first_line))
    query_tokens = [t for q in queries for t in _tokenize_chinese(q)]
    bm25 = _make_bm25(docs)
    coarse = bm25.search(query_tokens, top_k=8)
    if not coarse: return []
    candidate_texts = [(chap, body) for chap, body, _ in entry_data if chap in [c[0] for c in coarse]]
    reranked = _tfidf_rerank(query_tokens, candidate_texts, top_k=max(top_k, 4))
    bm25_scores = {chap: score for chap, score, _ in coarse}
    body_map = {chap: body for chap, body, _ in entry_data}
    preview_map = {chap: preview for chap, _, preview in entry_data}
    results = []
    for chap, tfidf_score, matched in reranked:
        bm25_score = bm25_scores.get(chap, 0)
        combined = bm25_score * 0.6 + tfidf_score * 0.4
        preview = preview_map.get(chap, "")
        meta = load_chapter_meta(book_root, chap)
        results.append((chap, combined, preview, matched, meta))
    results.sort(key=lambda x: -x[1])
    return results[:top_k]


def cmd_semantic(book_root, args):
    if not args.queries:
        print("错误：semantic 模式需要至少一个查询文本", file=sys.stderr); return 2
    cache, cache_path = load_query_cache(book_root)
    key = _cache_key(args.queries, args.top, args.light)
    if key in cache:
        cached = cache[key]
        print(f"（命中查询缓存，查询时间：{cached.get('time', '?')}）")
        results = cached["results"]
    else:
        try:
            results = semantic_search(book_root, args.queries, args.top, args.light)
        except FileNotFoundError as e:
            print(f"错误：{e}", file=sys.stderr); return 2
        cache[key] = {"queries": args.queries, "top": args.top, "light": args.light,
                       "time": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
        save_query_cache(book_root, cache)
    if not results: print(f"未找到相关章节"); return 1
    light_tag = " [轻场景·实体索引]" if (args.light or is_light_scene(args.queries)) else ""
    print(f"BM25 两级检索结果（查询：{' / '.join(repr(q) for q in args.queries)}）{light_tag}")
    print(f"{'章节':<10} {'相关度':<10} {'匹配关键词':<24} 摘要预览"); print("-" * 80)
    for chap, score, preview, matched, meta in results:
        matched_str = ", ".join(f"{m[0]}({m[1]})" for m in matched[:4]) if matched else "-"
        print(f"第{chap}章{'':<5} {score:.4f}{'':<5} {matched_str:<24} {preview[:40]}")
        if meta:
            parts = []
            if meta.get("event_type"): parts.append(f"事件:{meta['event_type']}")
            if meta.get("mood"): parts.append(f"基调:{meta['mood']}")
            if meta.get("characters"): parts.append(f"角色:{','.join(meta['characters'][:3])}")
            if parts: print(f"{'':>16} 元数据：{' | '.join(parts)}")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try: stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError): pass

    ap = argparse.ArgumentParser(description="关键实体→章节索引 + BM25两级检索 v2.1")
    ap.add_argument("mode", choices=["build", "query", "semantic"])
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("queries", nargs="*")
    ap.add_argument("--grep", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--light", action="store_true")
    args = ap.parse_args()
    book_root = os.path.abspath(args.book_root)

    if args.mode == "semantic": return cmd_semantic(book_root, args)

    if args.mode == "build":
        try: index, out_path, n_entries = build_index(book_root)
        except FileNotFoundError as e: print(f"错误：{e}", file=sys.stderr); return 2
        print(f"索引已重建：{out_path}")
        print(f"  覆盖 {n_entries} 章摘要，聚合 {len(index)} 个实体")
        return 0

    if not args.queries: print("错误：query 模式需要一个或多个实体名", file=sys.stderr); return 2
    index, path = load_index(book_root)
    if index is None: print(f"错误：索引不存在 {path}，先运行 build", file=sys.stderr); return 2
    missing = []
    for ent in args.queries:
        chapters = index.get(ent)
        if not chapters:
            fuzzy = {k: v for k, v in index.items() if ent in k or k in ent}
            if fuzzy:
                for k, v in sorted(fuzzy.items()):
                    print(f"「{ent}」未直接命中；近似实体「{k}」→ 第 {', '.join(map(str, v))} 章")
            else: missing.append(ent)
            continue
        print(f"「{ent}」→ 出现在第 {', '.join(map(str, chapters))} 章")
        if args.grep:
            for chap, line_no, line in grep_chapters(book_root, ent, chapters):
                print(f"    第{chap}章 第{line_no}行：{line}")
    if missing: print(f"未命中实体：{'、'.join(missing)}"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
