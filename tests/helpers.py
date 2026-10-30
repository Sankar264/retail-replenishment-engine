"""Shared, cached pipeline run for tests (works under pytest and under tests/run_all.py)."""
import functools
import tempfile
from pathlib import Path

from src.pipeline import run


@functools.lru_cache(maxsize=None)
def result(scale: str = "tiny"):
    out = Path(tempfile.mkdtemp(prefix=f"yfx_test_{scale}_"))
    return run(scale, out=out, do_inject=True, verbose=False, write_docs=False)
