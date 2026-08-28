#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py — long-novel-skill 测试套件运行器（纯标准库）。

用法：
    python scripts/tests/run_tests.py               # 运行所有测试
    python scripts/tests/run_tests.py test_common   # 运行指定测试模块
    python scripts/tests/run_tests.py test_common test_check_text  # 运行多个

输出格式：
    === long-novel-skill 测试套件 ===

    test_common.py ............... 15/15 通过，跳过 0，失败 0
    test_check_text.py ........... 7/8 通过，跳过 1，失败 0
    ...

    总计：37/38 通过，跳过 1，失败 0，耗时 2.3s
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
    "test_source_materialize",
    "test_resume",
    "test_run_tests",
    "test_static_check",
    "test_benchmark",
    "test_rhythm_guard",
    "test_entity_index",
    "test_outline_anchor",
    # 以下模块历史上未接入默认运行器（v7.0 补齐，覆盖 744 测试函数）
    "test_ai_patterns",
    "test_anti_resolution",
    "test_content_expander",
    "test_e2e",
    "test_entry_mode",
    "test_quality_score",
    "test_rag_retriever",
    "test_ranking_crawler",
    "test_story_graph",
    "test_style_fingerprint",
    "test_timeline_manager",
    "test_skill_contract",
    "test_dashboard",
    "test_release_contract",
    "test_chapter_transaction",
    "test_gate_artifacts_contract",
    "test_style_exemptions",
    "test_workflow_closure",
]

# 测试目录与 scripts 目录
TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent

# 把 scripts 与 tests 目录加入 sys.path
for p in (str(SCRIPTS_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _format_line(name, passed, total, width=40, skipped=0, failed=0):
    """分别列出通过、跳过、失败，分母为测试方法数（不含子测试数）。"""
    dots_count = max(1, width - len(name) - len(f" {passed}/{total} 通过") - 2)
    dots = "." * dots_count
    return f"{name} {dots} {passed}/{total} 通过，跳过 {skipped}，失败 {failed}"


def _result_counts(result):
    """Count methods once; fixture outcomes are reported but never deducted."""
    def parent_test(case):
        parent = getattr(case, "test_case", None)
        return parent if isinstance(parent, unittest.TestCase) else case
    failed = {parent_test(case) for case, _ in result.failures + result.errors}
    failed.update(result.unexpectedSuccesses)
    skipped = {parent_test(case) for case, _ in result.skipped} - failed
    unsuccessful_methods = {case for case in failed | skipped if isinstance(case, unittest.TestCase)}
    return result.testsRun - len(unsuccessful_methods), len(skipped), len(failed)


def run_module(module_name):
    """运行单个测试模块，返回 (passed, total, elapsed, result)。

    测试执行期间重定向 stdout/stderr，避免被测代码的错误输出污染报告。
    若该模块有失败用例，则把捕获的输出拼到返回的 result 中便于排查。
    """
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except (ImportError, AttributeError) as e:
        result = _make_failed_result(e)
        return 0, result.testsRun, 0.0, result

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
    passed, _, _ = _result_counts(result)
    return passed, total, elapsed, result


def _make_failed_result(error):
    """Preserve a real loader exception as an unsuccessful unittest result."""
    result = unittest.TestResult()
    case = unittest.FunctionTestCase(lambda: None, description="test module import")
    result.startTest(case)
    result.addError(case, (type(error), error, error.__traceback__))
    result.stopTest(case)
    result._captured_output = str(error)
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
    print("计数：分母为运行的方法数；跳过/失败含fixture结果，fixture级结果不计入方法分母。")
    print()

    total_passed = 0
    total_tests = 0
    total_skipped = 0
    total_failed = 0
    total_start = time.time()

    for mod in modules:
        passed, total, elapsed, result = run_module(mod)
        total_passed += passed
        total_tests += total
        _, skipped, failed = _result_counts(result)
        total_skipped += skipped
        total_failed += failed
        print(_format_line(f"{mod}.py", passed, total, skipped=skipped, failed=failed))
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
    print(f"总计：{total_passed}/{total_tests} 通过，跳过 {total_skipped}，失败 {total_failed}，耗时 {total_elapsed:.1f}s")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
