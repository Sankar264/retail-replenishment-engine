import hashlib
import numpy as np
from src.generate import generate
from src.util import load_config


def _digest(tables):
    h = hashlib.sha256()
    for name in sorted(tables):
        df = tables[name]
        h.update(name.encode())
        h.update(str(len(df)).encode())
        h.update(df.astype(str).to_csv(index=False).encode())
    return h.hexdigest()


def test_same_seed_same_data_different_seed_different_data():
    cfg = load_config("tiny")
    a, b = generate(cfg), generate(cfg)
    assert {k: len(v) for k, v in a["tables"].items()} == {k: len(v) for k, v in b["tables"].items()}
    assert _digest(a["tables"]) == _digest(b["tables"])
    c = generate(load_config("tiny", seed=1))
    assert _digest(a["tables"]) != _digest(c["tables"])


def test_pipeline_twice_gives_identical_checksums():
    from src.reproduce import reproduce
    import tempfile, pathlib
    r = reproduce("tiny", evidence=pathlib.Path(tempfile.mkdtemp()) / "evidence.json")
    assert r["row_counts_identical"] and r["all_checksums_identical"], r["mismatched_files"]
