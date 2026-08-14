#!/usr/bin/env python3
"""version_sync.py — 验证所有文件的版本号一致性。

用法:
  python scripts/version_sync.py --check    # CI 模式：不一致时 exit 1
  python scripts/version_sync.py            # 交互模式：报告版本号

退出码：0 = 一致；1 = 不一致；2 = 参数错误。
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_config_version():
    """从 config.py 读取规范版本号。"""
    config_path = ROOT / "scripts" / "config.py"
    if not config_path.exists():
        return None
    with open(config_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    m = re.search(r'SKILL_VERSION\s*=\s*"([^"]+)"', content)
    return m.group(1) if m else None


def read_skill_json_version():
    path = ROOT / "skill.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data.get("version")


def read_skill_md_version():
    path = ROOT / "SKILL.md"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            m = re.match(r"\s*version:\s*(\S+)", line)
            if m:
                return m.group(1).strip()
    return None


def read_readme_version():
    path = ROOT / "README.md"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    m = re.search(r"\*\*v?([\d.]+)\*\*", content)
    return m.group(1) if m else None


def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description="版本号一致性检查")
    ap.add_argument("--check", action="store_true", help="CI 模式：不一致时 exit 1")
    args = ap.parse_args()

    sources = {
        "config.py": read_config_version(),
        "skill.json": read_skill_json_version(),
        "SKILL.md": read_skill_md_version(),
        "README.md": read_readme_version(),
    }

    canonical = sources.get("config.py")
    if not canonical:
        print("错误：无法从 config.py 读取规范版本号", file=sys.stderr)
        return 2

    consistent = True
    for name, version in sources.items():
        if version is None:
            print(f"[WARN] {name}: 未找到版本号")
            consistent = False
        elif version != canonical:
            print(f"[FAIL] {name}: {version} ≠ {canonical} (config.py)")
            consistent = False
        else:
            print(f"[OK]   {name}: {version}")

    if consistent:
        print(f"\n所有文件版本号一致：v{canonical}")
        return 0
    else:
        print(f"\n版本号不一致！规范版本 (config.py)：v{canonical}")
        if args.check:
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
