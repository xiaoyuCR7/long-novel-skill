#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py — long-novel-skill 测试套件运行器（纯标准库）。

用法：
    python scripts/tests/run_tests.py               # 运行所有测试
    python scripts/tests/run_tests.py test_common   # 运行指定测试模块
    python scripts/tests/run_tests.py test_common test_check_text  # 运行多个

输出格式：
    === long-novel-skill 测试套件 ===

    test_common.py ............... 15/15 通过
    test_check_text.py ........... 8/8 通过
    ...

    总计：38/38 通过，耗时 2.3s
"""

import io
import os
import sys
import time
import unittest
from pathlib import Path

# 测试模块清单（按输出顺序）
TEST_MODULES = [
    "test_common",
    "test_check_text",
    "test_config",
    "test_novel_flow",
    "test_context_manager",
    "test_static_check",
    "test_benchmark",
    "test_rhythm_guard",
    "test_entity_index",
    "test_outline_anchor",
]

# 测试目录与 scripts 目录
TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent

# 把 scripts 与 tests 目录加入 sys.path
for p in (str(SCRIPTS_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _format_line(name, passed, total, width=40):
    """生成形如 'test_common.py ............... 15/15 通过' 的行。"""
    dots_count = max(1, width - len(name) - len(f" {passed}/{total} 通过") - 2)
    dots = "." * dots_count
    status = "通过" if passed == total else "部分通过"
    return f"{name} {dots} {passed}/{total} {status}"


def run_module(module_name):
    """运行单个测试模块，返回 (passed, total, elapsed, output_text)。

    测试执行期间重定向 stdout/stderr，避免被测代码的错误输出污染报告。
    若该模块有失败用例，则把捕获的输出拼到返回的 result 中便于排查。
    """
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except (ImportError, AttributeError) as e:
        return 0, 0, 0.0, _make_failed_result(str(e))

    captured = io.StringIO()
    runner = unittest.TextTestRunner(stream=captured, verbosity=0)
    start = time.time()
    # 同时重定向 stderr，避免被测代码的错误日志污染报告
    old_stderr = sys.stderr
    sys.stderr = captured
    try:
        result = runner.run(suite)
    finally:
        sys.stderr = old_stderr
    elapsed = time.time() - start

    # 把捕获的输出挂到 result 上，供失败时打印
    result._captured_output = captured.getvalue()
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    return passed, total, elapsed, result


def _make_failed_result(msg):
    """构造一个失败的空 result，用于导入失败场景。"""
    result = unittest.TestResult()
    result.testsRun = 0
    result._captured_output = msg
    return result


def main(argv):
    # Windows 控制台 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    # 解析参数：选择要运行的模块
    if len(argv) > 1:
        selected = argv[1:]
        # 校验模块名
        invalid = [m for m in selected if m not in TEST_MODULES]
        if invalid:
            print(f"错误：未知测试模块 {invalid}")
            print(f"可用模块：{', '.join(TEST_MODULES)}")
            return 2
        modules = selected
    else:
        modules = list(TEST_MODULES)

    print("=== long-novel-skill 测试套件 ===")
    print()

    total_passed = 0
    total_tests = 0
    total_start = time.time()

    for mod in modules:
        passed, total, elapsed, result = run_module(mod)
        total_passed += passed
        total_tests += total
        print(_format_line(f"{mod}.py", passed, total))
        # 有失败时打印详情
        if hasattr(result, "failures") and (result.failures or result.errors):
            for case, tb in result.failures + result.errors:
                # 取用例名
                name = case.id().split(".")[-1] if hasattr(case, "id") else str(case)
                print(f"    [FAIL] {name}")
                # 打印 traceback 最后几行
                tb_lines = tb.strip().splitlines()
                tail = tb_lines[-3:] if len(tb_lines) > 3 else tb_lines
                for ln in tail:
                    print(f"           {ln}")

    total_elapsed = time.time() - total_start
    print()
    status = "通过" if total_passed == total_tests else "部分通过"
    print(f"总计：{total_passed}/{total_tests} {status}，耗时 {total_elapsed:.1f}s")
    return 0 if total_passed == total_tests else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
