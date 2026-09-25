"""
Minimal stdlib-only test runner. This project's real test suite (test_rules.py,
test_toc_parser.py) uses plain `assert` statements and is written to be pytest-
compatible -- once you `pip install pytest` you can just run `pytest tests/` normally.
This runner exists only because pytest could not be installed in the sandbox this
platform was originally scaffolded in (outbound package installs were blocked); it
discovers and runs the same test functions with no dependencies at all.
"""
import sys
import traceback
import importlib
import inspect


def run_module(module_name: str) -> tuple[int, int]:
    mod = importlib.import_module(module_name)
    test_fns = [
        (name, fn) for name, fn in inspect.getmembers(mod, inspect.isfunction)
        if name.startswith("test_") and fn.__module__ == module_name
    ]
    passed = 0
    failed = 0
    for name, fn in test_fns:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}")
            print(f"        {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)
            failed += 1
    return passed, failed


if __name__ == "__main__":
    modules = sys.argv[1:] or ["test_rules", "test_toc_parser"]
    total_passed = 0
    total_failed = 0
    for m in modules:
        print(f"\n=== {m} ===")
        p, f = run_module(m)
        total_passed += p
        total_failed += f
    print(f"\n{'='*40}\nTOTAL: {total_passed} passed, {total_failed} failed")
    sys.exit(1 if total_failed else 0)
