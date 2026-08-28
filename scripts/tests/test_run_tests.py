"""Exercise real unittest pass/skip/fail outcomes through the default runner."""
from pathlib import Path
import subprocess
import sys
import textwrap
import types
import unittest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import run_tests


class TestRunTests(unittest.TestCase):
    def fixture(self, outcome):
        name = "_runner_fixture_" + outcome
        module = types.ModuleType(name)
        def test_case(case):
            if outcome in {"subfail", "subskip"}:
                for number in (1, 2):
                    with case.subTest(number=number):
                        if outcome == "subskip":
                            case.skipTest("real subtest skip")
                        case.fail("real subtest failure")
                return
            if outcome == "skip":
                case.skipTest("real skip")
            if outcome == "fail":
                case.fail("real failure")
            case.assertEqual(2 + 2, 4)
        module.Fixture = type("Fixture", (unittest.TestCase,), {"test_case": test_case})
        if outcome.startswith("class_"):
            def setup_class(cls):
                if outcome.startswith("class_skip"):
                    raise unittest.SkipTest("real class skip")
                raise RuntimeError("real class setup error")
            module.Fixture.setUpClass = classmethod(setup_class)
            if outcome.endswith("_mixed"):
                module.Other = type("Other", (unittest.TestCase,), {"test_case": test_case})
        if outcome == "import_error":
            def missing(attribute):
                if attribute == "load_tests":
                    raise ImportError("real load_tests import error")
                raise AttributeError(attribute)
            module.__getattr__ = missing
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        return name

    def test_run_module_counts_real_skipped_case_separately(self):
        passed, total, elapsed, result = run_tests.run_module(self.fixture("skip"))
        self.assertEqual((passed, total), (0, 1))
        self.assertEqual(len(result.skipped), 1)
        self.assertTrue(result.wasSuccessful())
        self.assertGreaterEqual(elapsed, 0)

    def test_run_module_counts_real_passing_case(self):
        passed, total, _, result = run_tests.run_module(self.fixture("pass"))
        self.assertEqual((passed, total), (1, 1))
        self.assertEqual(result.skipped, [])
        self.assertTrue(result.wasSuccessful())

    def test_run_module_counts_real_failing_case(self):
        passed, total, _, result = run_tests.run_module(self.fixture("fail"))
        self.assertEqual((passed, total), (0, 1))
        self.assertEqual(len(result.failures), 1)
        self.assertFalse(result.wasSuccessful())
        self.assertIn("real failure", result._captured_output)

    def test_real_loader_import_error_is_a_failed_result_not_zero_success(self):
        passed, total, _, result = run_tests.run_module(self.fixture("import_error"))
        self.assertEqual((passed, total), (0, 1))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 1)
        self.assertIn("real load_tests import error", result._captured_output)

    def test_multiple_failed_subtests_count_one_failed_test_without_negative_passed(self):
        passed, total, _, result = run_tests.run_module(self.fixture("subfail"))
        self.assertEqual((passed, total), (0, 1))
        self.assertEqual(len(result.failures), 2)

    def test_multiple_skipped_subtests_count_one_skipped_test_without_negative_passed(self):
        passed, total, _, result = run_tests.run_module(self.fixture("subskip"))
        self.assertEqual((passed, total), (0, 1))
        self.assertEqual(len(result.skipped), 2)

    def test_class_skip_is_reported_without_inventing_a_run_method(self):
        passed, total, _, result = run_tests.run_module(self.fixture("class_skip"))
        self.assertEqual((passed, total, result.testsRun), (0, 0, 0))
        self.assertEqual(run_tests._result_counts(result), (0, 1, 0))
        self.assertNotIsInstance(result.skipped[0][0], unittest.TestCase)
        self.assertTrue(result.wasSuccessful())

    def test_class_error_is_reported_without_inventing_a_run_method(self):
        passed, total, _, result = run_tests.run_module(self.fixture("class_error"))
        self.assertEqual((passed, total, result.testsRun), (0, 0, 0))
        self.assertEqual(run_tests._result_counts(result), (0, 0, 1))
        self.assertNotIsInstance(result.errors[0][0], unittest.TestCase)
        self.assertFalse(result.wasSuccessful())

    def test_fixture_outcome_does_not_subtract_another_real_passing_method(self):
        for outcome, expected in (("class_skip_mixed", (1, 1, 0)),
                                  ("class_error_mixed", (1, 0, 1))):
            with self.subTest(outcome=outcome):
                passed, total, _, result = run_tests.run_module(self.fixture(outcome))
                self.assertEqual((passed, total, result.testsRun), (1, 1, 1))
                self.assertEqual(run_tests._result_counts(result), expected)

    def test_cli_summary_and_exit_for_real_pass_skip_and_fail(self):
        code = textwrap.dedent("""
            import sys, types, unittest
            sys.path.insert(0, sys.argv[1])
            import run_tests
            outcome = sys.argv[2]
            module = types.ModuleType('_runner_cli_fixture')
            def test_case(case):
                if outcome in {'subfail', 'subskip'}:
                    for number in (1, 2):
                        with case.subTest(number=number):
                            if outcome == 'subskip':
                                case.skipTest('real subtest skip')
                            case.fail('real subtest failure')
                    return
                if outcome == 'skip':
                    case.skipTest('real skip')
                if outcome == 'fail':
                    case.fail('real failure')
                case.assertEqual(2 + 2, 4)
            module.Fixture = type('Fixture', (unittest.TestCase,), {'test_case': test_case})
            if outcome.startswith('class_'):
                def setup_class(cls):
                    if outcome.startswith('class_skip'):
                        raise unittest.SkipTest('real class skip')
                    raise RuntimeError('real class setup error')
                module.Fixture.setUpClass = classmethod(setup_class)
                if outcome.endswith('_mixed'):
                    module.Other = type('Other', (unittest.TestCase,), {'test_case': test_case})
            if outcome == 'import_error':
                def missing(attribute):
                    if attribute == 'load_tests':
                        raise ImportError('real load_tests import error')
                    raise AttributeError(attribute)
                module.__getattr__ = missing
            sys.modules[module.__name__] = module
            run_tests.TEST_MODULES = [module.__name__]
            sys.exit(run_tests.main(['run_tests.py', module.__name__]))
        """)
        for outcome, passed, total, skipped, failed, exit_code in (
                ("pass", 1, 1, 0, 0, 0), ("skip", 0, 1, 1, 0, 0), ("fail", 0, 1, 0, 1, 1),
                ("import_error", 0, 1, 0, 1, 1), ("subfail", 0, 1, 0, 1, 1), ("subskip", 0, 1, 1, 0, 0),
                ("class_skip", 0, 0, 1, 0, 0), ("class_error", 0, 0, 0, 1, 1),
                ("class_skip_mixed", 1, 1, 1, 0, 0), ("class_error_mixed", 1, 1, 0, 1, 1)):
            with self.subTest(outcome=outcome):
                result = subprocess.run([sys.executable, "-c", code, str(TESTS), outcome],
                                        capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                summary = next(line for line in result.stdout.splitlines() if line.startswith("总计："))
                self.assertIn(f"{passed}/{total} 通过", summary)
                self.assertIn(f"跳过 {skipped}", summary)
                self.assertIn(f"失败 {failed}", summary)
                self.assertIn("fixture级结果不计入方法分母", result.stdout)

    def test_default_runner_includes_its_regressions(self):
        self.assertIn("test_run_tests", run_tests.TEST_MODULES)


if __name__ == "__main__":
    unittest.main()
