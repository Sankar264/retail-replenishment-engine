#!/usr/bin/env python
"""Package the repository into a clean, deterministic .zip (skips caches and the large full dataset).

    python scripts/package_zip.py [--out yottaflex-replenishment.zip] [--include-data]
"""
import argparse
import os
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv"}
SKIP_PREFIX = ("data/full", "data/small", "data/tiny")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / f"{ROOT.name}.zip"))
    ap.add_argument("--include-data", action="store_true", help="also include data/full etc.")
    a = ap.parse_args()
    out = pathlib.Path(a.out).resolve()
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fn in os.walk(ROOT):
            dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
            for f in sorted(fn):
                p = pathlib.Path(dp) / f
                rel = p.relative_to(ROOT).as_posix()
                if p.resolve() == out or f.endswith((".pyc", ".zip")):
                    continue
                if not a.include_data and rel.startswith(SKIP_PREFIX):
                    continue
                z.write(p, f"{ROOT.name}/{rel}")
                n += 1
    print(f"wrote {out} ({n} files, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
