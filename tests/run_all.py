"""Minimal runner so the tests also work without pytest:  python tests/run_all.py"""
import importlib
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
failed = passed = 0
for p in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
    mod = importlib.import_module(f"tests.{p.stem}")
    for name in sorted(dir(mod)):
        if name.startswith("test_"):
            try:
                getattr(mod, name)()
                passed += 1
                print(f"PASS {p.stem}::{name}")
            except Exception:
                failed += 1
                print(f"FAIL {p.stem}::{name}")
                traceback.print_exc()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
