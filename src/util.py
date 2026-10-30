"""Shared helpers: config loading, deterministic RNG streams, hashing, key encoding."""
from __future__ import annotations

import hashlib
import zlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config(scale: str = "starter", seed: int | None = None, overrides: dict | None = None) -> dict:
    """Merge defaults + preset (+ CLI overrides) into one flat config dict."""
    with open(ROOT / "config" / "config.yaml", "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if scale not in raw["presets"]:
        raise ValueError(f"unknown scale '{scale}', choose one of {sorted(raw['presets'])}")
    cfg = {k: v for k, v in raw.items() if k not in ("presets", "defaults")}
    cfg.update(raw["defaults"])
    cfg.update(raw["presets"][scale])
    if seed is not None:
        cfg["seed"] = int(seed)
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    cfg["scale"] = scale
    end = date.fromisoformat(cfg["end_date"])
    cfg["start_date"] = (end - timedelta(days=int(cfg["n_days"]) - 1)).isoformat()
    return cfg


def rng_for(seed: int, name: str) -> np.random.Generator:
    """Independent, reproducible RNG stream per named stage (crc32 is stable across processes)."""
    return np.random.default_rng(np.random.SeedSequence([int(seed), zlib.crc32(name.encode("utf-8"))]))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def codes(series: pd.Series, categories) -> np.ndarray:
    """Integer codes of `series` w.r.t. a master id list (-1 => orphan key)."""
    return np.asarray(pd.Categorical(series, categories=list(categories)).codes, dtype=np.int64)


def day_index(series: pd.Series, start: str) -> np.ndarray:
    """ISO date strings -> integer day offsets from `start`."""
    d = pd.to_datetime(pd.Series(np.asarray(series).astype(str)), format="%Y-%m-%d").to_numpy().astype("datetime64[D]")
    return (d - np.datetime64(start, "D")).astype(np.int64)


def row_keys(df: pd.DataFrame, stores, skus, start: str, n_days: int, date_col: str = "date"):
    """(store, sku, date) -> sortable int64 key. Returns (key, store_idx, sku_idx, day)."""
    s = codes(df["store_id"], stores)
    k = codes(df["sku_id"], skus)
    d = day_index(df[date_col], start)
    key = (s * len(skus) + k) * int(n_days) + d
    return key, s, k, d


def add_days(iso: str, n: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=int(n))).isoformat()
