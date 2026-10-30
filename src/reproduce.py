"""Reproducibility proof: run the pipeline twice (separate processes, same seed) and compare row counts + SHA-256 checksums.

    python -m src.reproduce --scale starter
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .util import ROOT


def reproduce(scale: str, seed: int | None = None, evidence: Path | None = None, keep: bool = False) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="repro_"))
    runs = []
    try:
        for i in (1, 2):
            out = tmp / f"run{i}"
            cmd = [sys.executable, "-m", "src.pipeline", "--scale", scale, "--out", str(out), "--no-docs", "--quiet"]
            if seed is not None:
                cmd += ["--seed", str(seed)]
            subprocess.run(cmd, cwd=ROOT, check=True)
            runs.append(out)
        sums = [json.loads((r / "checksums.json").read_text()) for r in runs]
        counts = [json.loads((r / "run_manifest.json").read_text())["row_counts"] for r in runs]
        mismatched = sorted(k for k in set(sums[0]) | set(sums[1]) if sums[0].get(k) != sums[1].get(k))
        result = {
            "scale": scale, "seed": seed if seed is not None else 20261022, "runs": 2, "files_compared": len(sums[0]),
            "row_counts_identical": counts[0] == counts[1], "row_counts": counts[0],
            "all_checksums_identical": not mismatched, "mismatched_files": mismatched,
            "checksums_run1": sums[0],
        }
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    path = evidence or ROOT / "docs" / f"reproducibility_{scale}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="starter", choices=["tiny", "starter", "small", "full"])
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args(argv)
    r = reproduce(a.scale, a.seed)
    print(f"files compared: {r['files_compared']} | row counts identical: {r['row_counts_identical']} | checksums identical: {r['all_checksums_identical']}")
    if not (r["row_counts_identical"] and r["all_checksums_identical"]):
        print("MISMATCH:", r["mismatched_files"])
        sys.exit(1)


if __name__ == "__main__":
    main()
