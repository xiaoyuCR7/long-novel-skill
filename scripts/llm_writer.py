#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_writer.py — 多 LLM 写作引擎 v1.0.0（纯标准库，无第三方依赖）。

利用 config.py 的 load_llm_config() 调用 8 种 LLM provider 生成章节正文。
provider="default" 时为 pass-through 模式：输出 system prompt + context 供 AI 客户端消费。

用法:
  python scripts/llm_writer.py write "{书名目录}" --chapter N
  python scripts/llm_writer.py write "{书名目录}" --chapter N --dry-run
  python scripts/llm_writer.py config "{书名目录}"

退出码：0 = 成功；1 = API 错误；2 = 参数错误。
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from config import load_llm_config, mask_llm_key, SUPPORTED_LLM_PROVIDERS
    from common import read_text
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False


def _read_context(book_root, chapter_num):
    """读取写前上下文：章纲+人物卡+近章摘要。"""
    context = {"章纲": "", "人物卡": [], "摘要": ""}

    outline_path = os.path.join(book_root, "大纲", f"章纲_第{chapter_num:03d}章.md")
    if os.path.isfile(outline_path):
        context["章纲"] = open(outline_path, "r", encoding="utf-8-sig").read()[:3000]

    summary_path = os.path.join(book_root, "追踪", "章节摘要.md")
    if os.path.isfile(summary_path):
        context["摘要"] = open(summary_path, "r", encoding="utf-8-sig").read()[-4000:]

    chars_dir = os.path.join(book_root, "设定", "角色")
    if os.path.isdir(chars_dir):
        for f in sorted(os.listdir(chars_dir))[:5]:
            if f.endswith(".md"):
                char_text = open(os.path.join(chars_dir, f), "r", encoding="utf-8-sig").read()[:500]
                context["人物卡"].append(f"{f[:-3]}: {char_text}")

    return context


def _build_prompt(context):
    """构建写作 prompt。"""
    parts = ["你是网文作者，请续写下一章正文。", ""]
    if context["章纲"]:
        parts.append(f"## 本章章纲\n{context['章纲']}")
    if context["人物卡"]:
        parts.append(f"## 出场人物\n" + "\n".join(context["人物卡"]))
    if context["摘要"]:
        parts.append(f"## 近章剧情\n{context['摘要']}")
    parts.append("\n## 要求\n纯正文输出，不含大纲语言、TODO标记、作者按。每章2500-3500字。")
    return "\n\n".join(parts)


def cmd_write(book_root, args):
    """write 子命令。"""
    if not HAS_CONFIG:
        print("错误：无法导入 config.load_llm_config", file=sys.stderr); return 2

    llm_config = load_llm_config(book_root)
    context = _read_context(book_root, args.chapter)
    prompt = _build_prompt(context)

    if args.dry_run:
        print(f"=== LLM 配置 ===")
        print(f"Provider: {llm_config['provider']}")
        print(f"Model: {llm_config['model']}")
        if llm_config.get("api_key"):
            print(f"API Key: {mask_llm_key(llm_config['api_key'])}")
        print(f"Source: {llm_config['source']}")
        print(f"\n=== 上下文大小 ===")
        print(f"章纲: {len(context['章纲'])} 字符")
        print(f"人物卡: {len(context['人物卡'])} 张")
        print(f"摘要: {len(context['摘要'])} 字符")
        print(f"\n=== Prompt (前500字) ===")
        print(prompt[:500])
        return 0

    # default provider: pass-through 模式
    if llm_config["provider"] == "default":
        print(prompt)
        print("\n---")
        print("[提示] provider=default，请将上述 prompt 粘贴至 AI 客户端写作。")
        print("[提示] 配置其他 provider 请创建 .lns_config.yaml 或在环境变量设置 API Key。")
        return 0

    # 调用 API
    api_key = llm_config.get("api_key")
    if not api_key:
        print("错误：未配置 API Key。设置环境变量或创建 .lns_config.yaml", file=sys.stderr)
        return 1

    # 构建 API 请求（支持 OpenAI 兼容格式）
    api_url = llm_config.get("base_url") or "https://api.openai.com/v1/chat/completions"
    model = llm_config.get("model", "gpt-4")

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是专业网文作者，擅长中文长篇创作。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": getattr(args, 'max_tokens', 4000) or 4000,
        "temperature": 0.8,
    }).encode("utf-8")

    req = urllib.request.Request(api_url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]

        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"已写入：{args.output}")
        else:
            print(content)
        return 0
    except urllib.error.HTTPError as e:
        print(f"API 错误：HTTP {e.code} - {e.reason}", file=sys.stderr)
        try:
            print(e.read().decode()[:500], file=sys.stderr)
        except Exception:
            pass
        return 1
    except Exception as e:
        print(f"请求失败：{e}", file=sys.stderr)
        return 1


def cmd_config(book_root, args):
    """显示 LLM 配置。"""
    if not HAS_CONFIG:
        print("错误：无法导入 config.load_llm_config", file=sys.stderr); return 2

    llm = load_llm_config(book_root)
    print(f"Provider:   {llm['provider']}")
    print(f"Model:      {llm['model']}")
    if llm.get("api_key"):
        print(f"API Key:    {mask_llm_key(llm['api_key'])}")
    else:
        print(f"API Key:    (未配置)")
    if llm.get("base_url"):
        print(f"Base URL:   {llm['base_url']}")
    print(f"Source:     {llm['source']}")
    print(f"\n支持的 Provider: {', '.join(SUPPORTED_LLM_PROVIDERS) if HAS_CONFIG else 'N/A'}")
    print(f"\n配置方式:")
    print(f"  1. 环境变量: LNS_LLM_PROVIDER=openai LNS_LLM_API_KEY=sk-...")
    print(f"  2. 配置文件: 书籍目录/.lns_config.yaml 或 .lns_config.ini")
    return 0


def main():
    ap = argparse.ArgumentParser(description="多 LLM 写作引擎 v1.0.0")
    ap.add_argument("command", choices=["write", "config"])
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--chapter", type=int, default=0, help="章号")
    ap.add_argument("--dry-run", action="store_true", help="仅输出 prompt 不调用 API")
    ap.add_argument("--output", default=None, help="输出文件路径")
    ap.add_argument("--max-tokens", type=int, default=4000, help="最大生成 token 数")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)

    if args.command == "write":
        return cmd_write(book_root, args)
    elif args.command == "config":
        return cmd_config(book_root, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
