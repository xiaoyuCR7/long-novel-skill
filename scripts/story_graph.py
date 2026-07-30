#!/usr/bin/env python3
"""轻量知识图谱：节点+边+版本，支撑百万字级联影响分析。

职责：
1. 从 entity_index.json + 章节摘要 构建节点（角色/事件/地点/物品/势力）
2. 从正文章节摘要的「关键实体」字段 + 关系描述 提取边（关系）
3. 改纲时级联标记受影响节点（cascade_pending）
4. 导出 Mermaid 可视化（可选）
5. 版本管理（每次更新写入时间戳，旧版保留备份）

数据落在 `追踪/story_graph.json`。
纯标准库，无第三方依赖。
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =========================================================
# 常量
# =========================================================

GRAPH_FILE = "story_graph.json"
ENTITY_INDEX_FILE = "entity_index.json"
CHAPTER_SUMMARY_FILE = "章节摘要.md"
CHARACTER_STATE_FILE = "角色状态.md"
VERSION = "1.1.0"

# 节点类型
NODE_TYPES = {"character", "event", "location", "item", "faction", "secret", "rule"}

# 边类型（关系）
EDGE_TYPES = {
    "owns": "拥有",
    "kills": "杀死",
    "betrays": "背叛",
    "allies": "结盟",
    "loves": "爱慕",
    "hates": "仇恨",
    "mentors": "师徒",
    "rivals": "竞争",
    "belongs_to": "属于",
    "located_at": "位于",
    "reveals": "揭露",
    "causes": "导致",
    "participates_in": "参与",
    "appears_in": "出现于",
}


# =========================================================
# 工具函数
# =========================================================

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> bool:
    try:
        ensure_dir(path.parent)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def backup_graph(path: Path) -> Optional[Path]:
    """备份当前图谱，返回备份路径。"""
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}_{ts}.bak.json")
    try:
        content = path.read_bytes()
        backup.write_bytes(content)
        return backup
    except OSError:
        return None


# =========================================================
# 节点提取
# =========================================================

def extract_character_nodes(
    book_root: Path,
) -> List[Dict[str, Any]]:
    """从角色状态文件提取角色节点。"""
    nodes = []
    char_state_path = book_root / "追踪" / CHARACTER_STATE_FILE
    text = read_text(char_state_path)
    if not text:
        return nodes

    # 解析角色状态文件的 ## 角色名 节
    sections = re.split(r"\n## ", text)
    for sec in sections[1:]:  # 跳过第一个（可能是前言）
        lines = sec.strip().split("\n", 1)
        name = lines[0].strip()
        status = lines[1].strip()[:200] if len(lines) > 1 else ""

        node_id = f"char_{name}"
        nodes.append({
            "id": node_id,
            "type": "character",
            "label": name,
            "props": {"status_snippet": status},
            "first_appear_chapter": None,
            "last_updated_chapter": None,
            "cascade_pending": False,
        })

    return nodes


def extract_entity_nodes(
    book_root: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """从 entity_index.json 和章节摘要提取非角色节点和边。"""
    nodes = []
    edges = []

    # 从 entity_index.json 提取实体
    entity_index = load_json(book_root / "追踪" / ENTITY_INDEX_FILE, {})
    entities = entity_index.get("entities", {})
    chapter_entities = entity_index.get("chapter_entities", {})

    if not entities:
        # 从章节摘要回退提取
        entities, chapter_entities = _extract_from_summaries(book_root)

    # 创建节点
    for entity_name, info in entities.items():
        if isinstance(info, dict):
            etype = info.get("type", "item")
            chapters = info.get("chapters", [])
        else:
            etype = "item"
            chapters = list(info) if isinstance(info, list) else []

        if etype not in NODE_TYPES:
            etype = "item"

        node_id = f"{etype}_{entity_name}"
        nodes.append({
            "id": node_id,
            "type": etype,
            "label": entity_name,
            "props": {},
            "first_appear_chapter": min(chapters) if chapters else None,
            "last_updated_chapter": max(chapters) if chapters else None,
            "cascade_pending": False,
        })

    # 从章节摘要提取关系边
    edges = _extract_edges_from_summaries(book_root, nodes)

    return nodes, edges


def _extract_from_summaries(
    book_root: Path,
) -> Tuple[Dict[str, Any], Dict[str, List[int]]]:
    """从章节摘要回退提取实体。"""
    entities: Dict[str, Any] = {}
    chapter_entities: Dict[str, List[int]] = defaultdict(list)

    summary_path = book_root / "追踪" / CHAPTER_SUMMARY_FILE
    text = read_text(summary_path)
    if not text:
        return entities, chapter_entities

    # 解析每章的「关键实体」字段
    chapter_blocks = re.split(r"\n### 第(\d+)章", text)
    for i in range(1, len(chapter_blocks), 2):
        try:
            ch_num = int(chapter_blocks[i])
        except ValueError:
            continue
        block = chapter_blocks[i + 1] if i + 1 < len(chapter_blocks) else ""

        # 提取关键实体行
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("- **关键实体**") or line.startswith("关键实体"):
                # 提取冒号后的内容
                parts = re.split(r"[：:]", line, maxsplit=1)
                if len(parts) > 1:
                    content = parts[1].strip()
                    # 分割实体（逗号/顿号/分号分隔）
                    for entity in re.split(r"[,，、;；]", content):
                        entity = entity.strip()
                        if not entity:
                            continue
                        # 尝试解析「类型:名称」格式
                        etype = "item"
                        ename = entity
                        if ":" in entity:
                            etype, ename = entity.split(":", 1)
                            etype = etype.strip()
                            ename = ename.strip()

                        if ename not in entities:
                            entities[ename] = {"type": etype, "chapters": []}
                        if ch_num not in entities[ename]["chapters"]:
                            entities[ename]["chapters"].append(ch_num)

    return entities, dict(chapter_entities)


def _extract_edges_from_summaries(
    book_root: Path,
    nodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """从章节摘要提取关系边。"""
    edges = []
    node_id_map = {n["label"]: n["id"] for n in nodes}

    summary_path = book_root / "追踪" / CHAPTER_SUMMARY_FILE
    text = read_text(summary_path)
    if not text:
        return edges

    # 简单关系提取：从摘要中找「A→动词→B」模式
    relation_patterns = [
        (r"([^\s]{1,8})杀死([^\s]{1,8})", "kills"),
        (r"([^\s]{1,8})背叛([^\s]{1,8})", "betrays"),
        (r"([^\s]{1,8})与([^\s]{1,8})结盟", "allies"),
        (r"([^\s]{1,8})与([^\s]{1,8})联手", "allies"),
        (r"([^\s]{1,8})爱上([^\s]{1,8})", "loves"),
        (r"([^\s]{1,8})仇恨([^\s]{1,8})", "hates"),
        (r"([^\s]{1,8})拜([^\s]{1,8})为师", "mentors"),
        (r"([^\s]{1,8})收([^\s]{1,8})为徒", "mentors"),
        (r"([^\s]{1,8})与([^\s]{1,8})竞争", "rivals"),
        (r"([^\s]{1,8})揭露([^\s]{1,8})", "reveals"),
        (r"([^\s]{1,8})导致([^\s]{1,8})", "causes"),
    ]

    seen_edges = set()
    chapter_blocks = re.split(r"\n### 第(\d+)章", text)

    for i in range(1, len(chapter_blocks), 2):
        try:
            ch_num = int(chapter_blocks[i])
        except ValueError:
            continue
        block = chapter_blocks[i + 1] if i + 1 < len(chapter_blocks) else ""

        for pattern, edge_type in relation_patterns:
            for m in re.finditer(pattern, block):
                a, b = m.group(1).strip(), m.group(2).strip()
                if a not in node_id_map or b not in node_id_map:
                    continue
                edge_key = (node_id_map[a], edge_type, node_id_map[b])
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({
                    "source": node_id_map[a],
                    "target": node_id_map[b],
                    "type": edge_type,
                    "label": EDGE_TYPES.get(edge_type, edge_type),
                    "chapter": ch_num,
                    "props": {},
                })

    return edges


# =========================================================
# v1.1 从正文直接提取（不依赖章节摘要）
# =========================================================

def extract_from_chapter(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    """从正文章节中自动提取实体和关系，不依赖章节摘要的「关键实体」字段。

    返回 {"chapter", "characters_found", "locations_found", "new_edges", "text_length"}
    """
    # 查找章节文件
    text_dir = book_root / "正文"
    chapter_file = text_dir / f"第{chapter:03d}章_待写.md"
    if not chapter_file.exists():
        chapter_file = text_dir / f"第{chapter}章_待写.md"
    if not chapter_file.exists():
        # 尝试其他命名模式
        for f in text_dir.glob(f"第{chapter:03d}章*.md"):
            chapter_file = f
            break
        if not chapter_file.exists():
            for f in text_dir.glob(f"第{chapter}章*.md"):
                chapter_file = f
                break

    if not chapter_file.exists():
        return {"chapter": chapter, "error": "章节文件不存在", "characters_found": [],
                "locations_found": [], "new_edges": [], "text_length": 0}

    text = chapter_file.read_text(encoding="utf-8")
    text_len = len(re.sub(r"\s", "", text))

    # ① 加载已知角色名（从设定/角色/*.md 文件名）
    char_dir = book_root / "设定" / "角色"
    known_chars = []
    if char_dir.exists():
        for f in char_dir.glob("*.md"):
            known_chars.append(f.stem)

    # 在正文中查找角色名
    chars_found = []
    for name in known_chars:
        if name in text:
            chars_found.append(name)

    # ② 加载已知地名（从设定/世界观.md）
    loc_file = book_root / "设定" / "世界观.md"
    known_locs = []
    if loc_file.exists():
        loc_text = loc_file.read_text(encoding="utf-8")
        # 匹配 「地点：」「城市：」「区域：」后的内容
        for pat in [r"(?:地点|城市|区域|地域|宗门|势力|国家)[：:]\s*([^\n，。；]+)",
                    r"\*\*(地点|城市|区域|地域|宗门|势力|国家)\*\*\s*[：:]\s*([^\n，。；]+)",
                    r"-?\s*(?:地点|城市|区域|地域|宗门|势力|国家)\s+([^\n，。；]{2,20})"]:
            for m in re.finditer(pat, loc_text):
                loc = m.group(1) if m.lastindex == 1 else m.group(1 if m.lastindex == 1 else len(m.groups()))
                if loc and len(loc) >= 2:
                    known_locs.append(loc.strip())

    # 去重
    known_locs = list(dict.fromkeys(known_locs))

    # 在正文中查找地名
    locs_found = []
    for loc in known_locs:
        if loc in text:
            locs_found.append(loc)

    # ③ 提取关系边（扩展关系模式）
    all_nodes = chars_found + locs_found
    new_edges = []
    seen = set()

    relation_patterns = [
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})杀(?:死|掉|害)?([一-鿿㐀-䶿豈-﫿]{2,8})", "kills"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})背叛([一-鿿㐀-䶿豈-﫿]{2,8})", "betrays"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:与|和)([一-鿿㐀-䶿豈-﫿]{2,8})(?:结盟|联手|联合|合作)", "allies"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})爱(?:上|慕)?([一-鿿㐀-䶿豈-﫿]{2,8})", "loves"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})仇恨([一-鿿㐀-䶿豈-﫿]{2,8})", "hates"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:拜|认)([一-鿿㐀-䶿豈-﫿]{2,8})(?:为师|做师傅)", "mentors"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:与|和)([一-鿿㐀-䶿豈-﫿]{2,8})(?:竞争|较量|比试|对战|战斗|对战)", "rivals"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})揭露([一-鿿㐀-䶿豈-﫿]{2,8})", "reveals"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})导致([一-鿿㐀-䶿豈-﫿]{2,8})", "causes"),
        # v1.1 新增模式
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:给|交给|送给|递)(?:给)?([一-鿿㐀-䶿豈-﫿]{2,8})", "owns"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:带|带着|携|携同)([一-鿿㐀-䶿豈-﫿]{2,8})", "owns"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:找|找到|寻得|寻获)([一-鿿㐀-䶿豈-﫿]{2,8})", "owns"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:打败|击败|战胜|击垮|击溃)([一-鿿㐀-䶿豈-﫿]{2,8})", "rivals"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:保护|守护|护|庇)(?:护)?([一-鿿㐀-䶿豈-﫿]{2,8})", "allies"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:前往|去往|赶到|奔赴|来到|抵达|进入)([一-鿿㐀-䶿豈-﫿]{2,8})", "located_at"),
        (r"([一-鿿㐀-䶿豈-﫿]{2,8})(?:出现|现身|来到|抵达|到达)(?:在|于|至)?([一-鿿㐀-䶿豈-﫿]{2,8})", "located_at"),
    ]

    for pattern, edge_type in relation_patterns:
        for m in re.finditer(pattern, text):
            a, b = m.group(1).strip(), m.group(2).strip()
            if a == b:
                continue
            if a not in all_nodes and b not in all_nodes:
                continue
            key = (a, edge_type, b)
            if key in seen:
                continue
            seen.add(key)
            new_edges.append({
                "source_label": a,
                "target_label": b,
                "type": edge_type,
                "label": EDGE_TYPES.get(edge_type, edge_type),
                "chapter": chapter,
            })

    return {
        "chapter": chapter,
        "file": str(chapter_file.name),
        "characters_found": chars_found,
        "locations_found": locs_found,
        "new_edges": new_edges,
        "text_length": text_len,
    }


def extract_and_update(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    """从章节正文提取实体和关系，并合并到知识图谱。"""
    extracted = extract_from_chapter(book_root, chapter)
    if "error" in extracted:
        return {"ok": False, "error": extracted["error"], "chapter": chapter}

    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return {"ok": False, "error": "图谱不存在，请先 build", "chapter": chapter}

    # 合并新节点
    added_nodes = 0
    existing_nodes = {n["label"]: n for n in graph.get("nodes", [])}

    for char_name in extracted["characters_found"]:
        node_id = f"char_{char_name}"
        if node_id not in existing_nodes:
            existing_nodes[node_id] = {
                "id": node_id,
                "type": "character",
                "label": char_name,
                "props": {},
                "first_appear_chapter": chapter,
                "last_updated_chapter": chapter,
                "cascade_pending": False,
            }
            added_nodes += 1

    for loc_name in extracted["locations_found"]:
        node_id = f"location_{loc_name}"
        if node_id not in existing_nodes:
            existing_nodes[node_id] = {
                "id": node_id,
                "type": "location",
                "label": loc_name,
                "props": {},
                "first_appear_chapter": chapter,
                "last_updated_chapter": chapter,
                "cascade_pending": False,
            }
            added_nodes += 1

    # 合并新边
    added_edges = 0
    seen_edges = {(e["source"], e["type"], e["target"]) for e in graph.get("edges", [])}
    for edge in extracted["new_edges"]:
        src_label = edge["source_label"]
        tgt_label = edge["target_label"]
        # 查找或创建节点 ID
        src_node = existing_nodes.get(f"char_{src_label}") or existing_nodes.get(f"location_{src_label}")
        tgt_node = existing_nodes.get(f"char_{tgt_label}") or existing_nodes.get(f"location_{tgt_label}")
        if not src_node or not tgt_node:
            continue
        src_id = src_node["id"]
        tgt_id = tgt_node["id"]
        edge_key = (src_id, edge["type"], tgt_id)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        graph["edges"].append({
            "source": src_id,
            "target": tgt_id,
            "type": edge["type"],
            "label": edge["label"],
            "chapter": chapter,
            "props": {},
        })
        added_edges += 1

    # 更新统计
    graph["nodes"] = list(existing_nodes.values())
    graph["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    type_counts = defaultdict(int)
    for n in graph["nodes"]:
        type_counts[n["type"]] += 1
    graph["stats"] = {
        "total_nodes": len(graph["nodes"]),
        "total_edges": len(graph["edges"]),
        "node_types": dict(type_counts),
    }

    save_json(graph_path, graph)

    return {
        "ok": True,
        "chapter": chapter,
        "added_nodes": added_nodes,
        "added_edges": added_edges,
        "total_nodes": len(graph["nodes"]),
        "total_edges": len(graph["edges"]),
        "saved_to": str(graph_path),
    }


# =========================================================
# 图谱构建
# =========================================================

def build_graph(
    book_root: Path,
    from_scratch: bool = False,
) -> Dict[str, Any]:
    """构建/更新知识图谱。

    Args:
        book_root: 书籍工程根目录
        from_scratch: 是否从头重建（忽略已有图谱）

    Returns:
        图谱字典
    """
    graph_path = book_root / "追踪" / GRAPH_FILE

    existing = None
    if not from_scratch and graph_path.exists():
        existing = load_json(graph_path)

    # 提取角色节点
    char_nodes = extract_character_nodes(book_root)

    # 提取实体节点和边
    entity_nodes, edges = extract_entity_nodes(book_root)

    # 合并节点（去重）
    all_nodes = {}
    for n in char_nodes + entity_nodes:
        nid = n["id"]
        if nid in all_nodes:
            # 合并：保留已有章节信息
            existing_n = all_nodes[nid]
            if n.get("first_appear_chapter"):
                if not existing_n.get("first_appear_chapter") or \
                   n["first_appear_chapter"] < existing_n["first_appear_chapter"]:
                    existing_n["first_appear_chapter"] = n["first_appear_chapter"]
            if n.get("last_updated_chapter"):
                if not existing_n.get("last_updated_chapter") or \
                   n["last_updated_chapter"] > existing_n["last_updated_chapter"]:
                    existing_n["last_updated_chapter"] = n["last_updated_chapter"]
            existing_n["props"].update(n.get("props", {}))
        else:
            all_nodes[nid] = n

    graph = {
        "version": VERSION,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(edges),
            "node_types": {},
        },
        "nodes": list(all_nodes.values()),
        "edges": edges,
    }

    # 统计节点类型
    type_counts = defaultdict(int)
    for n in all_nodes.values():
        type_counts[n["type"]] += 1
    graph["stats"]["node_types"] = dict(type_counts)

    return graph


def update_chapter(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    """增量更新：只从单章摘要提取新实体和关系，追加到已有图谱。

    每章写完后调用，避免全量 rebuild 的代价。
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        # 图谱不存在，降级为全量构建
        return {
            "ok": False,
            "error": "图谱不存在，请先 build",
            "fallback": "建议先运行: python story_graph.py build",
        }

    # 从单章摘要提取实体和关系
    summary_path = book_root / "追踪" / CHAPTER_SUMMARY_FILE
    text = read_text(summary_path)
    if not text:
        return {"ok": False, "error": "章节摘要文件不存在"}

    # 找到本章摘要块
    chapter_block = ""
    chapter_blocks = re.split(r"\n### 第(\d+)章", text)
    for i in range(1, len(chapter_blocks), 2):
        try:
            ch_num = int(chapter_blocks[i])
        except ValueError:
            continue
        if ch_num == chapter:
            chapter_block = chapter_blocks[i + 1] if i + 1 < len(chapter_blocks) else ""
            break

    if not chapter_block:
        return {"ok": False, "error": f"第{chapter}章摘要未找到"}

    # 从本章摘要提取实体
    new_entities: Dict[str, Any] = {}
    for line in chapter_block.split("\n"):
        line = line.strip()
        if line.startswith("- **关键实体**") or line.startswith("关键实体"):
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) > 1:
                content = parts[1].strip()
                for entity in re.split(r"[,，、;；]", content):
                    entity = entity.strip()
                    if not entity:
                        continue
                    etype = "item"
                    ename = entity
                    if ":" in entity:
                        etype, ename = entity.split(":", 1)
                        etype = etype.strip()
                        ename = ename.strip()
                    if etype not in NODE_TYPES:
                        etype = "item"
                    if ename not in new_entities:
                        new_entities[ename] = {"type": etype, "chapters": []}
                    if chapter not in new_entities[ename]["chapters"]:
                        new_entities[ename]["chapters"].append(chapter)

    # 提取关系边
    new_edges = []
    node_id_map = {n["label"]: n["id"] for n in graph.get("nodes", [])}
    # 也包含本章新发现的实体
    for ename, info in new_entities.items():
        etype = info["type"]
        node_id_map[ename] = f"{etype}_{ename}"

    relation_patterns = [
        (r"([^\s]{1,8})杀死([^\s]{1,8})", "kills"),
        (r"([^\s]{1,8})背叛([^\s]{1,8})", "betrays"),
        (r"([^\s]{1,8})与([^\s]{1,8})结盟", "allies"),
        (r"([^\s]{1,8})与([^\s]{1,8})联手", "allies"),
        (r"([^\s]{1,8})爱上([^\s]{1,8})", "loves"),
        (r"([^\s]{1,8})仇恨([^\s]{1,8})", "hates"),
        (r"([^\s]{1,8})拜([^\s]{1,8})为师", "mentors"),
        (r"([^\s]{1,8})收([^\s]{1,8})为徒", "mentors"),
        (r"([^\s]{1,8})与([^\s]{1,8})竞争", "rivals"),
        (r"([^\s]{1,8})揭露([^\s]{1,8})", "reveals"),
        (r"([^\s]{1,8})导致([^\s]{1,8})", "causes"),
    ]

    seen_edges = set()
    # 先加入已有边到 seen
    for edge in graph.get("edges", []):
        key = (edge["source"], edge["type"], edge["target"])
        seen_edges.add(key)

    for pattern, edge_type in relation_patterns:
        for m in re.finditer(pattern, chapter_block):
            a, b = m.group(1).strip(), m.group(2).strip()
            if a not in node_id_map or b not in node_id_map:
                continue
            edge_key = (node_id_map[a], edge_type, node_id_map[b])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            new_edges.append({
                "source": node_id_map[a],
                "target": node_id_map[b],
                "type": edge_type,
                "label": EDGE_TYPES.get(edge_type, edge_type),
                "chapter": chapter,
                "props": {},
            })

    # 合并新节点到图谱
    added_nodes = 0
    updated_nodes = 0
    existing_nodes = {n["id"]: n for n in graph.get("nodes", [])}

    for ename, info in new_entities.items():
        etype = info["type"]
        node_id = f"{etype}_{ename}"
        if node_id in existing_nodes:
            # 更新 last_updated_chapter
            n = existing_nodes[node_id]
            last_ch = n.get("last_updated_chapter")
            if last_ch is None or chapter > last_ch:
                n["last_updated_chapter"] = chapter
            updated_nodes += 1
        else:
            existing_nodes[node_id] = {
                "id": node_id,
                "type": etype,
                "label": ename,
                "props": {},
                "first_appear_chapter": chapter,
                "last_updated_chapter": chapter,
                "cascade_pending": False,
            }
            added_nodes += 1

    # 合并新边
    added_edges = 0
    for edge in new_edges:
        graph["edges"].append(edge)
        added_edges += 1

    # 更新统计
    graph["nodes"] = list(existing_nodes.values())
    graph["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    type_counts = defaultdict(int)
    for n in graph["nodes"]:
        type_counts[n["type"]] += 1
    graph["stats"] = {
        "total_nodes": len(graph["nodes"]),
        "total_edges": len(graph["edges"]),
        "node_types": dict(type_counts),
    }

    save_json(graph_path, graph)

    return {
        "ok": True,
        "chapter": chapter,
        "added_nodes": added_nodes,
        "updated_nodes": updated_nodes,
        "added_edges": added_edges,
        "total_nodes": len(graph["nodes"]),
        "total_edges": len(graph["edges"]),
        "saved_to": str(graph_path),
    }


# =========================================================
# 级联标记
# =========================================================

def cascade_mark(
    book_root: Path,
    from_chapter: int,
    change_description: str = "",
) -> Dict[str, Any]:
    """改纲后标记受影响节点。

    将所有 last_updated_chapter >= from_chapter 的节点标记为 cascade_pending=True。
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return {"ok": False, "error": "图谱不存在，请先 build"}

    backup_graph(graph_path)

    affected = []
    for node in graph.get("nodes", []):
        last_ch = node.get("last_updated_chapter")
        if last_ch is not None and last_ch >= from_chapter:
            node["cascade_pending"] = True
            affected.append({
                "id": node["id"],
                "label": node["label"],
                "type": node["type"],
                "last_updated": last_ch,
            })

    # 也标记涉及这些节点的边
    affected_ids = {a["id"] for a in affected}
    affected_edges = []
    for edge in graph.get("edges", []):
        if edge["source"] in affected_ids or edge["target"] in affected_ids:
            affected_edges.append(edge)

    graph["cascade"] = {
        "from_chapter": from_chapter,
        "description": change_description,
        "marked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "affected_nodes": len(affected),
        "affected_edges": len(affected_edges),
    }

    save_json(graph_path, graph)

    return {
        "ok": True,
        "affected_nodes": affected,
        "affected_edges_count": len(affected_edges),
        "total_nodes": len(graph.get("nodes", [])),
        "total_edges": len(graph.get("edges", [])),
    }


# =========================================================
# 查询
# =========================================================

def query_graph(
    book_root: Path,
    node_label: str,
    depth: int = 1,
) -> Dict[str, Any]:
    """查询节点及其邻接关系。

    Args:
        book_root: 书籍工程根目录
        node_label: 节点标签（模糊匹配）
        depth: 查询深度（1=直接邻居，2=邻居的邻居）

    Returns:
        查询结果
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return {"ok": False, "error": "图谱不存在，请先 build"}

    # 查找匹配节点
    matched = []
    for node in graph.get("nodes", []):
        if node_label.lower() in node["label"].lower():
            matched.append(node)

    if not matched:
        return {"ok": True, "matched": [], "message": f"未找到匹配 '{node_label}' 的节点"}

    # 查找邻接边
    result_nodes = []
    result_edges = []
    visited = set()

    for m in matched:
        visited.add(m["id"])
        result_nodes.append(m)

    current_depth = 0
    frontier = set(visited)

    while current_depth < depth:
        next_frontier = set()
        for edge in graph.get("edges", []):
            src = edge["source"]
            tgt = edge["target"]
            if src in frontier or tgt in frontier:
                if edge not in result_edges:
                    result_edges.append(edge)
                if src not in visited:
                    next_frontier.add(src)
                if tgt not in visited:
                    next_frontier.add(tgt)

        # 添加新发现的节点
        node_map = {n["id"]: n for n in graph.get("nodes", [])}
        for nid in next_frontier:
            if nid in node_map and nid not in visited:
                result_nodes.append(node_map[nid])
                visited.add(nid)

        frontier = next_frontier - visited
        current_depth += 1

    return {
        "ok": True,
        "query": node_label,
        "depth": depth,
        "matched": [{"id": m["id"], "label": m["label"], "type": m["type"]} for m in matched],
        "nodes": result_nodes,
        "edges": result_edges,
        "total_related": len(result_nodes),
    }


# =========================================================
# Mermaid 导出
# =========================================================

def export_mermaid(book_root: Path, output_path: Optional[Path] = None) -> str:
    """导出图谱为 Mermaid 格式。

    Returns:
        Mermaid 文本
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return "graph TD\n  A[图谱不存在]"

    lines = ["graph TD"]
    lines.append("  %% 知识图谱 — 自动生成于 " + graph.get("updated_at", ""))
    lines.append("")

    # 节点定义
    type_styles = {
        "character": "[/%s/]",
        "event": "[%s]",
        "location": "[(%s)]",
        "item": "([%s])",
        "faction": "{{%s}}",
        "secret": "[\"%s\"]",
        "rule": "{%s}",
    }

    node_ids = {}
    for i, node in enumerate(graph.get("nodes", [])):
        nid = node["id"]
        safe_id = f"n{i}"
        node_ids[nid] = safe_id
        style = type_styles.get(node["type"], "[%s]")
        label = node["label"]
        cascade = " ⚠" if node.get("cascade_pending") else ""
        lines.append(f"  {safe_id}{style % (label + cascade)}")

    lines.append("")

    # 边定义
    for edge in graph.get("edges", []):
        src = node_ids.get(edge["source"])
        tgt = node_ids.get(edge["target"])
        if src and tgt:
            label = edge["label"]
            ch = edge.get("chapter", "")
            ch_str = f"|Ch{ch}|" if ch else ""
            lines.append(f"  {src} -->{ch_str} {tgt}")

    mermaid_text = "\n".join(lines)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(mermaid_text)
        except OSError:
            pass

    return mermaid_text


# =========================================================
# 影响分析
# =========================================================

def impact_analysis(
    book_root: Path,
    node_label: str,
) -> Dict[str, Any]:
    """分析修改某个节点可能影响的级联范围。

    返回：直接受影响节点 + 间接受影响节点 + 影响路径。
    """
    query_result = query_graph(book_root, node_label, depth=2)
    if not query_result.get("ok"):
        return query_result

    matched = query_result.get("matched", [])
    if not matched:
        return query_result

    # 分析影响路径
    direct_impact = []
    indirect_impact = []
    node_ids = {n["id"] for n in query_result["nodes"]}
    matched_ids = {m["id"] for m in matched}

    for edge in query_result.get("edges", []):
        if edge["source"] in matched_ids and edge["target"] in node_ids:
            direct_impact.append({
                "from": edge["source"],
                "to": edge["target"],
                "relation": edge["label"],
                "chapter": edge.get("chapter"),
            })
        elif edge["target"] in matched_ids and edge["source"] in node_ids:
            direct_impact.append({
                "from": edge["source"],
                "to": edge["target"],
                "relation": edge["label"],
                "chapter": edge.get("chapter"),
            })

    # 间接影响 = 非直接但有边连接
    direct_pairs = {(d["from"], d["to"]) for d in direct_impact}
    for edge in query_result.get("edges", []):
        if (edge["source"], edge["target"]) not in direct_pairs:
            if edge["source"] in node_ids and edge["target"] in node_ids:
                indirect_impact.append({
                    "from": edge["source"],
                    "to": edge["target"],
                    "relation": edge["label"],
                    "chapter": edge.get("chapter"),
                })

    return {
        "ok": True,
        "node": node_label,
        "matched": matched,
        "direct_impact": direct_impact,
        "indirect_impact": indirect_impact,
        "total_impact": len(direct_impact) + len(indirect_impact),
    }


# =========================================================
# CLI
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="轻量知识图谱：节点+边+版本，支撑百万字级联影响分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/story_graph.py build "{书名目录}"
  python scripts/story_graph.py query "{书名目录}" 林雷
  python scripts/story_graph.py query "{书名目录}" 林雷 --depth 2
  python scripts/story_graph.py cascade "{书名目录}" --from-chapter 50 --desc "改主线"
  python scripts/story_graph.py impact "{书名目录}" 林雷
  python scripts/story_graph.py export "{书名目录}" --output graph.md
  python scripts/story_graph.py status "{书名目录}"
  python scripts/story_graph.py update "{书名目录}" --chapter 37
        """,
    )
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="构建/更新知识图谱")
    p_build.add_argument("book_root", help="书籍工程根目录")
    p_build.add_argument("--from-scratch", action="store_true", help="从头重建")

    p_query = sub.add_parser("query", help="查询节点及邻接关系")
    p_query.add_argument("book_root", help="书籍工程根目录")
    p_query.add_argument("node", help="节点标签（模糊匹配）")
    p_query.add_argument("--depth", type=int, default=1, help="查询深度（默认1）")

    p_cascade = sub.add_parser("cascade", help="改纲后标记受影响节点")
    p_cascade.add_argument("book_root", help="书籍工程根目录")
    p_cascade.add_argument("--from-chapter", type=int, required=True, help="改纲影响起始章节")
    p_cascade.add_argument("--desc", default="", help="改纲说明")

    p_impact = sub.add_parser("impact", help="分析修改某节点的级联影响")
    p_impact.add_argument("book_root", help="书籍工程根目录")
    p_impact.add_argument("node", help="节点标签")

    p_export = sub.add_parser("export", help="导出 Mermaid 可视化")
    p_export.add_argument("book_root", help="书籍工程根目录")
    p_export.add_argument("--output", help="输出文件路径")

    p_status = sub.add_parser("status", help="查看图谱状态")
    p_status.add_argument("book_root", help="书籍工程根目录")

    p_update = sub.add_parser("update", help="增量更新单章（每章写完后调用）")
    p_update.add_argument("book_root", help="书籍工程根目录")
    p_update.add_argument("--chapter", type=int, required=True, help="章节号")

    # v1.1 新增 extract 子命令
    p_extract = sub.add_parser("extract", help="从正文章节自动提取实体和关系")
    p_extract.add_argument("book_root", help="书籍工程根目录")
    p_extract.add_argument("--chapter", type=int, required=True, help="章节号")
    p_extract.add_argument("--update", action="store_true", help="提取后自动更新图谱")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    book_root = Path(args.book_root).expanduser().resolve()

    if args.command == "build":
        graph = build_graph(book_root, from_scratch=args.from_scratch)
        graph_path = book_root / "追踪" / GRAPH_FILE
        save_json(graph_path, graph)
        print(json.dumps({
            "ok": True,
            "stats": graph["stats"],
            "saved_to": str(graph_path),
        }, ensure_ascii=False, indent=2))

    elif args.command == "query":
        result = query_graph(book_root, args.node, args.depth)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "cascade":
        result = cascade_mark(book_root, args.from_chapter, args.desc)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "impact":
        result = impact_analysis(book_root, args.node)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "export":
        out = Path(args.output) if args.output else None
        text = export_mermaid(book_root, out)
        if not args.output:
            print(text)

    elif args.command == "status":
        graph_path = book_root / "追踪" / GRAPH_FILE
        graph = load_json(graph_path)
        if not graph:
            print(json.dumps({"ok": False, "error": "图谱不存在"}, ensure_ascii=False))
            sys.exit(1)
        cascade = graph.get("cascade", {})
        print(json.dumps({
            "ok": True,
            "stats": graph["stats"],
            "updated_at": graph.get("updated_at"),
            "cascade": cascade,
            "has_pending_cascade": any(
                n.get("cascade_pending") for n in graph.get("nodes", [])
            ),
        }, ensure_ascii=False, indent=2))

    elif args.command == "update":
        result = update_chapter(book_root, args.chapter)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "extract":
        if args.update:
            result = extract_and_update(book_root, args.chapter)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            result = extract_from_chapter(book_root, args.chapter)
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()