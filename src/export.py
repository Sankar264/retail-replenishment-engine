"""Export CSV / JSON / SQL seed data, ground truth, checksums and manifests (all deterministic - no timestamps)."""
from __future__ import annotations

import json
import sqlite3  # noqa: F401  (used by tests/docs for loading the seed)
from pathlib import Path

import numpy as np
import pandas as pd

from . import ids, schema
from .util import sha256_file

CHUNK = 500_000


def _ordered(name: str, df: pd.DataFrame) -> pd.DataFrame:
    cols = schema.columns(name)
    return df[[c for c in cols if c in df.columns]]


def _materialise_id(name: str, chunk: pd.DataFrame) -> pd.DataFrame:
    if name == "sales_history":
        chunk = chunk.assign(sale_id=ids.sale_ids(np.asarray(chunk["store_id"]), np.asarray(chunk["sku_id"]), np.asarray(chunk["date"])))
    elif name == "inventory_snapshot":
        chunk = chunk.assign(snapshot_id=ids.inventory_ids(np.asarray(chunk["store_id"]), np.asarray(chunk["sku_id"]), np.asarray(chunk["date"])))
    return chunk


def iter_rows_chunks(name: str, df: pd.DataFrame, chunk: int = CHUNK):
    for i in range(0, max(len(df), 1), chunk):
        part = _ordered(name, _materialise_id(name, df.iloc[i:i + chunk]))
        yield part


def write_csv(name: str, df: pd.DataFrame, path: Path) -> int:
    first = True
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for part in iter_rows_chunks(name, df):
            part.to_csv(fh, index=False, header=first, float_format="%.6g", lineterminator="\n")
            first = False
            n += len(part)
    return n


def _sql_val(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)) or (v is pd.NA) or (v is pd.NaT):
        return "NULL"
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return format(float(v), ".6g")
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(tables: dict, out_dir: Path, insert_max_rows: int) -> dict:
    """schema.sql (DDL) + seed.sql. Small tables use INSERT; big ones emit a COPY/.import hint against the CSV."""
    sql_dir = Path(out_dir) / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    (sql_dir / "schema.sql").write_text(schema.ddl(), encoding="utf-8")
    info = {}
    with open(sql_dir / "seed.sql", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(schema.ddl() + "\nBEGIN;\n")
        for name in schema.ORDER:
            df = tables[name]
            cols = schema.columns(name)
            if len(df) > insert_max_rows:
                fh.write(f"-- {name}: {len(df)} rows exceed the INSERT limit. Load from CSV instead:\n")
                fh.write(f"--   PostgreSQL: \\copy {name} ({', '.join(cols)}) FROM 'tables/{name}.csv' CSV HEADER\n")
                fh.write(f"--   SQLite:     .mode csv  /  .import --skip 1 tables/{name}.csv {name}\n")
                info[name] = "csv-only"
                continue
            for part in iter_rows_chunks(name, df, 5000):
                rows = [", ".join(_sql_val(v) for v in r) for r in part.itertuples(index=False, name=None)]
                if rows:
                    fh.write(f"INSERT INTO {name} ({', '.join(part.columns)}) VALUES\n(" + "),\n(".join(rows) + ");\n")
            info[name] = "insert"
        fh.write("COMMIT;\n")
    return info


def export_all(tables: dict, ground_truth: pd.DataFrame, censored: pd.DataFrame, out_dir: Path, cfg: dict) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)
    (out_dir / "json").mkdir(exist_ok=True)
    (out_dir / "ground_truth").mkdir(exist_ok=True)
    counts = {}
    for name in schema.ORDER:
        counts[name] = write_csv(name, tables[name], out_dir / "tables" / f"{name}.csv")
        if counts[name] <= int(cfg["json_max_rows"]):
            part = pd.concat(list(iter_rows_chunks(name, tables[name])), ignore_index=True) if counts[name] else tables[name]
            part = part.astype(object).where(part.notna(), None)
            records = part.to_dict(orient="records")
            with open(out_dir / "json" / f"{name}.json", "w", encoding="utf-8") as fh:
                json.dump(records, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    ground_truth.to_csv(out_dir / "ground_truth" / "ground_truth.csv", index=False, lineterminator="\n")
    gt_json = {
        "description": "Labelled injected anomalies. Never join into model inputs. entity_id references the primary key of entity_type.",
        "counts_by_issue_type": {k: int(v) for k, v in ground_truth["issue_type"].value_counts().sort_index().items()},
        "issues": json.loads(ground_truth.astype(object).where(ground_truth.notna(), None).to_json(orient="records")),
    }
    (out_dir / "ground_truth" / "ground_truth.json").write_text(json.dumps(gt_json, indent=1), encoding="utf-8")
    cen = censored[["sale_id", "store_id", "sku_id", "date", "true_demand", "units_sold", "lost_units"]]
    cen.to_csv(out_dir / "ground_truth" / "censored_demand.csv", index=False, lineterminator="\n")
    sql_info = write_sql(tables, out_dir, int(cfg["sql_insert_max_rows"]))
    return {"row_counts": counts, "sql": sql_info, "ground_truth_rows": int(len(ground_truth)), "censored_demand_rows": int(len(censored))}


# Operational files differ on every attempt by design (timestamps / random attempt id); everything else is hashed,
# INCLUDING metrics/ and reports/ (they are deterministic functions of the seed).
CHECKSUM_EXCLUDED = {"checksums.json": "the checksum file itself", "run_attempt.json": "attempt id + wall-clock times",
                     "run_ledger.jsonl": "append-only attempt ledger", "_history": "archived earlier attempts",
                     "failed_attempts": "diagnostics of failed attempts"}


def checksum_tree(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    res = {}
    for p in sorted(out_dir.rglob("*")):
        rel = p.relative_to(out_dir)
        if p.is_file() and p.name not in CHECKSUM_EXCLUDED and not (set(rel.parts) & set(CHECKSUM_EXCLUDED)):
            res[str(rel).replace("\\", "/")] = sha256_file(p)
    return res