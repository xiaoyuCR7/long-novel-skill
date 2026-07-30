#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_packager.py — 微Skill打包器 + 多平台Plugin生成器（企业级能力）。

功能：
  1. 微Skill打包：将长小说Skill拆成独立的微Skill，每个聚焦一个功能
  2. 多平台Plugin生成：为不同平台生成适配的plugin包

当前支持的平台：
  - claude_skill    — Claude Desktop Skill（SKILL.md + pyproject）
  - cursor_skill     — Cursor Rule（.cursorrules 格式）
  - trae_skill       — Trae Skill（与当前格式兼容）
  - vscode_snippet   — VSCode Code Snippets

用法：
  # 打包成微Skill
  python scripts/skill_packager.py list-micro-skills
  python scripts/skill_packager.py package-micro --skill quality_checker --output dist/

  # 生成多平台Plugin
  python scripts/skill_packager.py list-platforms
  python scripts/skill_packager.py generate-plugin --platform claude_skill --output dist/
  python scripts/skill_packager.py generate-all --output dist/
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 让脚本能导入同目录的模块
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import common

# =============================================================================
# 微Skill定义
# =============================================================================

# 每个微Skill对应一个独立的能力，可以单独发布
MICRO_SKILLS = {
    "quality_checker": {
        "name": "小说质量检查器",
        "description": "7 Gate门禁检查、AI味检测、风格指纹分析",
        "scripts": ["check_text.py", "style_fingerprint.py", "static_check.py"],
        "entry_script": "check_text.py",
        "docs": ["质量检查工作流.md"],
        "category": "quality",
    },
    "outline_manager": {
        "name": "大纲管理器",
        "description": "生成/拆分/锚定大纲，结构审查",
        "scripts": ["outline_splitter.py", "outline_anchor.py", "outline_exploder.py",
                   "plot_point_breaker.py", "graph_outline.py"],
        "entry_script": "outline_splitter.py",
        "docs": ["大纲工作流.md"],
        "category": "outline",
    },
    "entity_rag": {
        "name": "实体索引与RAG",
        "description": "人物/地点/事件索引，BM25检索，伏笔台账",
        "scripts": ["entity_index.py", "rag_retriever.py", "foreshadowing_ledger.py"],
        "entry_script": "entity_index.py",
        "docs": ["RAG工作流.md"],
        "category": "knowledge",
    },
    "rhythm_engine": {
        "name": "节奏引擎",
        "description": "节奏模式识别、节拍表生成、节奏卫士",
        "scripts": ["rhythm_patterns.py", "beat_sheet.py", "rhythm_guard.py"],
        "entry_script": "rhythm_patterns.py",
        "docs": ["节奏工作流.md"],
        "category": "rhythm",
    },
    "context_manager": {
        "name": "上下文管理器",
        "description": "创作上下文打包、前情摘要、实体状态",
        "scripts": ["context_manager.py"],
        "entry_script": "context_manager.py",
        "docs": ["上下文工作流.md"],
        "category": "context",
    },
    "benchmark_system": {
        "name": "对标管理系统",
        "description": "对标书管理、风格对标、3路径权威索引",
        "scripts": ["benchmark_index.py"],
        "entry_script": "benchmark_index.py",
        "docs": ["对标工作流.md"],
        "category": "benchmark",
    },
    "adaptive_engine": {
        "name": "自适应写作引擎",
        "description": "根据作者状态动态调整写作策略",
        "scripts": ["adaptive_engine.py"],
        "entry_script": "adaptive_engine.py",
        "docs": [],
        "category": "adaptive",
    },
    "dashboard": {
        "name": "创作工作台",
        "description": "本地Web Dashboard，可视化创作数据",
        "scripts": ["dashboard.py"],
        "entry_script": "dashboard.py",
        "docs": [],
        "category": "ui",
    },
}


def list_micro_skills() -> List[str]:
    """列出所有可用的微Skill。"""
    return list(MICRO_SKILLS.keys())


def get_micro_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    """获取微Skill定义。"""
    return MICRO_SKILLS.get(skill_id)


# =============================================================================
# 平台定义
# =============================================================================

PLATFORMS = {
    "claude_skill": {
        "name": "Claude Desktop Skill",
        "description": "Claude Desktop / Claude Code 原生Skill格式",
        "output_name": "long-novel-skill-claude",
    },
    "cursor_skill": {
        "name": "Cursor Rules",
        "description": "Cursor IDE 的 .cursorrules 规则文件",
        "output_name": "long-novel-skill-cursor",
    },
    "trae_skill": {
        "name": "Trae Skill",
        "description": "Trae IDE 的Skill格式（与当前格式一致）",
        "output_name": "long-novel-skill-trae",
    },
    "vscode_snippet": {
        "name": "VSCode Snippets",
        "description": "VSCode 代码片段（.code-snippets）",
        "output_name": "long-novel-skill-vscode",
    },
}


def list_platforms() -> List[str]:
    """列出所有支持的平台。"""
    return list(PLATFORMS.keys())


# =============================================================================
# 微Skill打包
# =============================================================================

def package_micro_skill(skill_id: str, output_dir: Path,
                         skill_root: Path) -> Path:
    """将单个微Skill打包到输出目录。

    返回生成的目录路径。
    """
    skill_def = get_micro_skill(skill_id)
    if not skill_def:
        raise ValueError(f"未知的微Skill: {skill_id}")

    # 创建输出目录
    skill_dir = output_dir / f"micro-{skill_id}"
    skill_dir.mkdir(parents=True, exist_ok=True)

    # 复制脚本（带依赖）
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    # 必需的依赖
    deps = ["common.py", "logger.py", "config.py"]
    for dep in deps:
        src = skill_root / "scripts" / dep
        if src.exists():
            shutil.copy2(src, scripts_dir / dep)

    # Skill自己的脚本
    for script_name in skill_def["scripts"]:
        src = skill_root / "scripts" / script_name
        if src.exists():
            shutil.copy2(src, scripts_dir / script_name)

    # 复制资源
    assets_src = skill_root / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, skill_dir / "assets", dirs_exist_ok=True)

    # 生成SKILL.md
    skill_md = _generate_micro_skill_md(skill_id, skill_def)
    common.write_text(skill_dir / "SKILL.md", skill_md)

    # 生成README
    readme = _generate_micro_readme(skill_id, skill_def)
    common.write_text(skill_dir / "README.md", readme)

    return skill_dir


def _generate_micro_skill_md(skill_id: str, skill_def: Dict[str, Any]) -> str:
    """为微Skill生成SKILL.md。"""
    entry = skill_def["entry_script"]
    lines = [
        f"# {skill_def['name']}（微Skill）",
        f"",
        f"{skill_def['description']}",
        f"",
        f"## 快速开始",
        f"",
        f"```bash",
        f"python scripts/{entry} --help",
        f"```",
        f"",
        f"## 功能模块",
        f"",
    ]
    for s in skill_def["scripts"]:
        lines.append(f"- `{s}`")
    lines.append(f"")
    lines.append(f"## 依赖")
    lines.append(f"")
    lines.append(f"- Python 3.8+（仅标准库）")
    lines.append(f"- common.py / logger.py / config.py（已包含）")
    lines.append(f"")
    if skill_def["docs"]:
        lines.append(f"## 文档")
        lines.append(f"")
        for d in skill_def["docs"]:
            lines.append(f"- {d}")
        lines.append(f"")
    return "\n".join(lines)


def _generate_micro_readme(skill_id: str, skill_def: Dict[str, Any]) -> str:
    """为微Skill生成README。"""
    return f"""# {skill_def['name']}

> 属于 long-novel-skill 系列的微Skill

{skill_def['description']}

## 安装

将本目录复制到你的Skills目录即可。

## 使用

```bash
python scripts/{skill_def['entry_script']} --help
```

## 相关微Skill

- quality_checker — 质量检查
- outline_manager — 大纲管理
- entity_rag — 实体索引与RAG
- rhythm_engine — 节奏引擎
- context_manager — 上下文管理
- benchmark_system — 对标系统
- adaptive_engine — 自适应写作
- dashboard — 创作工作台
"""


# =============================================================================
# 多平台Plugin生成
# =============================================================================

def generate_plugin(platform: str, output_dir: Path, skill_root: Path) -> Path:
    """为指定平台生成Plugin。

    返回生成的目录路径。
    """
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")

    plat_info = PLATFORMS[platform]
    plugin_dir = output_dir / plat_info["output_name"]
    plugin_dir.mkdir(parents=True, exist_ok=True)

    if platform == "claude_skill":
        _generate_claude_skill(plugin_dir, skill_root)
    elif platform == "cursor_skill":
        _generate_cursor_rules(plugin_dir, skill_root)
    elif platform == "trae_skill":
        _generate_trae_skill(plugin_dir, skill_root)
    elif platform == "vscode_snippet":
        _generate_vscode_snippets(plugin_dir, skill_root)

    return plugin_dir


def _generate_claude_skill(plugin_dir: Path, skill_root: Path):
    """生成Claude Desktop Skill格式。"""
    # 复制整个scripts目录
    scripts_src = skill_root / "scripts"
    if scripts_src.exists():
        shutil.copytree(scripts_src, plugin_dir / "scripts", dirs_exist_ok=True)

    # 复制SKILL.md（Claude的核心）
    skill_md_src = skill_root / "SKILL.md"
    if skill_md_src.exists():
        shutil.copy2(skill_md_src, plugin_dir / "SKILL.md")

    # 复制assets
    assets_src = skill_root / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, plugin_dir / "assets", dirs_exist_ok=True)

    # 生成pyproject.toml（Claude推荐）
    pyproject = f"""[project]
name = "long-novel-skill"
version = "6.1.0"
description = "企业级长篇小说创作辅助系统"
requires-python = ">=3.8"
dependencies = []  # 零依赖，仅标准库

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["scripts"]
"""
    common.write_text(plugin_dir / "pyproject.toml", pyproject)

    # 生成安装说明
    install = f"""# Claude Desktop Skill 安装

1. 将本目录复制到 Claude Skills 目录：
   - macOS: ~/Library/Application Support/Claude/Skills/
   - Windows: %APPDATA%\\Claude\\Skills\\
2. 重启 Claude Desktop
3. 在Skill列表中找到 "long-novel-skill"

## 使用

在对话中说：
- "帮我初始化一本小说"
- "检查这一章的质量"
- "给我生成一个大纲"
"""
    common.write_text(plugin_dir / "INSTALL_CLAUDE.md", install)


def _generate_cursor_rules(plugin_dir: Path, skill_root: Path):
    """生成Cursor Rules格式（.cursorrules）。"""
    # 复制核心脚本
    scripts_src = skill_root / "scripts"
    if scripts_src.exists():
        shutil.copytree(scripts_src, plugin_dir / "scripts", dirs_exist_ok=True)

    # 生成.cursorrules文件（Cursor原生格式）
    skill_md_src = skill_root / "SKILL.md"
    skill_content = common.read_text(skill_md_src) if skill_md_src.exists() else ""

    # 提取关键指令生成.cursorrules
    cursor_rules = f"""# Long Novel Skill — Cursor Rules

## 角色
你是资深AI Agent工程师和金牌小说创作者，精通长篇网络小说的工业化创作。

## 核心能力
{skill_content[:2000] if skill_content else '（见SKILL.md完整内容）'}

## 写作规范
- 目标：起点/番茄等男频长篇网络小说
- 单章目标：4000字左右
- 语言风格：简洁、画面感强、节奏明快
- 去AI味：避免毒句式（见static_check.py）

## 常用命令参考
```bash
python novel-cli.py init "书名" --genre 玄幻
python novel-cli.py check "书名目录" 第38章
python novel-cli.py write "书名目录" 38
python novel-cli.py dashboard "书名目录"
python novel-cli.py adaptive suggest "书名目录"
```

## 当用户请求写小说相关内容时
1. 先检查是否有书籍工程目录
2. 遵循7 Gate质量检查流程
3. 使用实体索引保持人物/设定一致性
4. 参考节奏引擎建议安排冲突和缓冲
"""
    common.write_text(plugin_dir / ".cursorrules", cursor_rules)

    # 同时放一份SKILL.md
    if skill_md_src.exists():
        shutil.copy2(skill_md_src, plugin_dir / "SKILL.md")

    # 安装说明
    install = f"""# Cursor Rules 安装

1. 将 `.cursorrules` 文件复制到你的项目根目录
2. 或者复制到 Cursor 的全局规则目录
3. 重启 Cursor

## 使用

打开 Cursor，它会自动读取 .cursorrules 文件。
在对话中可以直接说：
- "帮我写一章"
- "检查一下这章的质量"
- "生成一个大纲"
"""
    common.write_text(plugin_dir / "INSTALL_CURSOR.md", install)


def _generate_trae_skill(plugin_dir: Path, skill_root: Path):
    """生成Trae Skill格式（与当前格式一致）。"""
    # 基本就是整个项目的精简版
    scripts_src = skill_root / "scripts"
    if scripts_src.exists():
        shutil.copytree(scripts_src, plugin_dir / "scripts", dirs_exist_ok=True)

    assets_src = skill_root / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, plugin_dir / "assets", dirs_exist_ok=True)

    for f in ["SKILL.md", "novel-cli.py", "pyproject.toml"]:
        src = skill_root / f
        if src.exists():
            shutil.copy2(src, plugin_dir / f)

    install = f"""# Trae Skill 安装

1. 将本目录复制到 Trae Skills 目录
2. 在 Trae 中刷新 Skill 列表
3. 启用 long-novel-skill

## 使用

在对话中 @long-novel-skill 或直接说：
- "初始化一本小说"
- "检查质量"
- "生成大纲"
"""
    common.write_text(plugin_dir / "INSTALL_TRAE.md", install)


def _generate_vscode_snippets(plugin_dir: Path, skill_root: Path):
    """生成VSCode代码片段格式。"""
    # 提取常用的写作片段模板
    snippets = {}

    # 初始化书籍
    snippets["ln-init-book"] = {
        "prefix": ["ln-init", "novel-init"],
        "body": [
            "# ${1:书名}",
            "",
            "## 基本信息",
            "- 类型：${2:玄幻/都市/科幻...}",
            "- 平台：${3:起点/番茄/晋江...}",
            "- 目标字数：${4:100万}",
            "- 预计章数：${5:250}",
            "",
            "## 核心卖点",
            "${6:一句话说明这本书的独特之处}",
            "",
            "## 主角设定",
            "### ${7:主角名}",
            "- 身份：${8:}",
            "- 性格：${9:}",
            "- 核心矛盾：${10:}",
        ],
        "description": "初始化一本小说的基本信息",
    }

    # 章节模板
    snippets["ln-chapter-template"] = {
        "prefix": ["ln-chapter", "novel-chapter"],
        "body": [
            "# 第${1:001}章_${2:章节标题}",
            "",
            "<!-- 本章目标：${3:推进什么剧情} -->",
            "<!-- 关键事件：${4:发生了什么} -->",
            "<!-- 本章钩子：${5:结尾留什么悬念} -->",
            "",
            "${0:正文内容}",
        ],
        "description": "小说章节模板（含元信息注释）",
    }

    # 对话模板
    snippets["ln-dialogue"] = {
        "prefix": ["ln-dialog", "novel-dialog"],
        "body": [
            "\"${1:台词}\"${2:, ${3:动作/神态}}。",
        ],
        "description": "小说对话片段",
    }

    # 场景切换
    snippets["ln-scene-break"] = {
        "prefix": ["ln-break", "scene-break"],
        "body": [
            "",
            "——— ${1:时间/地点变化} ———",
            "",
        ],
        "description": "场景切换分隔符",
    }

    # 大纲节点
    snippets["ln-outline-node"] = {
        "prefix": ["ln-outline", "outline-node"],
        "body": [
            "## ${1:章节号}. ${2:标题}",
            "- **场景**：${3:地点/时间}",
            "- **POV**：${4:视角人物}",
            "- **核心事件**：${5:发生了什么}",
            "- **人物弧线**：${6:角色有什么变化}",
            "- **伏笔**：${7:埋设/回收什么伏笔}",
            "- **结尾钩子**：${8:留下什么悬念}",
        ],
        "description": "单章大纲节点模板",
    }

    # 人物卡
    snippets["ln-character-card"] = {
        "prefix": ["ln-char", "character-card"],
        "body": [
            "### ${1:人物名}",
            "- **身份**：${2:社会地位/职业}",
            "- **年龄**：${3:}",
            "- **外貌**：${4:标志性特征}",
            "- **性格**：${5:3个核心特质}",
            "- **动机**：${6:想要什么}",
            "- **秘密**：${7:隐藏了什么}",
            "- **人物弧线**：${8:从A到B的变化}",
            "- **关系网**：",
            "  - ${9:与主角的关系}",
        ],
        "description": "人物设定卡片模板",
    }

    common.write_json(plugin_dir / "long-novel-skill.code-snippets", snippets)

    # 使用说明
    install = f"""# VSCode Snippets 安装

1. 打开 VSCode
2. 按 `Ctrl+Shift+P` (Windows) / `Cmd+Shift+P` (Mac)
3. 输入 "Configure User Snippets"
4. 选择 "markdown.json" 或 "新建全局代码片段文件"
5. 将 `long-novel-skill.code-snippets` 的内容粘贴进去

## 可用片段

| 触发词 | 功能 |
|--------|------|
| ln-init | 初始化小说基本信息 |
| ln-chapter | 章节模板（含元信息） |
| ln-dialog | 对话片段 |
| ln-break | 场景切换分隔符 |
| ln-outline | 单章大纲节点 |
| ln-char | 人物设定卡片 |
"""
    common.write_text(plugin_dir / "INSTALL_VSCODE.md", install)


# =============================================================================
# 主入口
# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="微Skill打包器 + 多平台Plugin生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 微Skill
  python scripts/skill_packager.py list-micro-skills
  python scripts/skill_packager.py package-micro --skill quality_checker --output dist/

  # 多平台Plugin
  python scripts/skill_packager.py list-platforms
  python scripts/skill_packager.py generate-plugin --platform claude_skill --output dist/
  python scripts/skill_packager.py generate-all --output dist/
""",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # list-micro-skills
    p_lm = sub.add_parser("list-micro-skills", help="列出所有微Skill")

    # package-micro
    p_pm = sub.add_parser("package-micro", help="打包单个微Skill")
    p_pm.add_argument("--skill", required=True, help="微Skill ID")
    p_pm.add_argument("--output", default="dist", help="输出目录")

    # list-platforms
    p_lp = sub.add_parser("list-platforms", help="列出支持的平台")

    # generate-plugin
    p_gp = sub.add_parser("generate-plugin", help="生成指定平台的Plugin")
    p_gp.add_argument("--platform", required=True, help="平台名称")
    p_gp.add_argument("--output", default="dist", help="输出目录")

    # generate-all
    p_ga = sub.add_parser("generate-all", help="生成所有平台的Plugin")
    p_ga.add_argument("--output", default="dist", help="输出目录")

    args = ap.parse_args()
    skill_root = _SCRIPT_DIR.parent
    output_dir = Path(args.output).resolve() if hasattr(args, "output") else Path("dist")
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "list-micro-skills":
        for sid in list_micro_skills():
            s = get_micro_skill(sid)
            print(f"  {sid:20s} — {s['name']:12s}  {s['description']}")
        print(f"\n共 {len(MICRO_SKILLS)} 个微Skill")

    elif args.command == "package-micro":
        path = package_micro_skill(args.skill, output_dir, skill_root)
        print(f"✅ 微Skill已打包: {path}")

    elif args.command == "list-platforms":
        for pid in list_platforms():
            p = PLATFORMS[pid]
            print(f"  {pid:20s} — {p['name']:25s}  {p['description']}")
        print(f"\n共 {len(PLATFORMS)} 个平台")

    elif args.command == "generate-plugin":
        path = generate_plugin(args.platform, output_dir, skill_root)
        print(f"✅ {PLATFORMS[args.platform]['name']} Plugin已生成: {path}")

    elif args.command == "generate-all":
        for pid in list_platforms():
            path = generate_plugin(pid, output_dir, skill_root)
            print(f"✅ {PLATFORMS[pid]['name']}: {path}")
        print(f"\n全部 {len(PLATFORMS)} 个平台Plugin已生成到: {output_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
