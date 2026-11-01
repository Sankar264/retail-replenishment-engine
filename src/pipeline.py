"""End-to-end pipeline: generate -> forecast -> replenish -> validate baseline -> inject -> validate -> export.

    python -m src.pipeline --scale starter --seed 20261022 --out data/starter
"""
from __future__ import annotations

import argparse
import html
import json
import platform
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import export, forecasting, ids, inject, replenishment, schema, validate
from .generate import generate
from .util import ROOT, load_config, sha256_file

SOURCE_MANIFEST = {
    "provenance": "FULLY SYNTHETIC - no external data used",
    "external_datasets": [],
    "notes": ("All records are produced by src/generate.py from a fixed seed. No personal, confidential or third-party licensed "
              "data was collected, scraped or redistributed. Schema design was inspired by common retail replenishment "
              "data models (SKU / store / supplier master, sales and inventory snapshots) - no public dataset values were copied."),
    "fields_discarded": [],
    "transformations": [],
    "licence": "Code and generated data: MIT (see LICENSE).",
}


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
class ValidationGateError(RuntimeError):
    """Raised when the clean baseline or the labelled-anomaly run breaks its validation contract."""


def _ledger_append(final_dir: Path, rec: dict) -> None:
    final_dir.mkdir(parents=True, exist_ok=True)
    with open(final_dir / "run_ledger.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gate_baseline(base: dict) -> None:
    sm = base["summary"]
    det = {k: v for k, v in sm["anomaly_detector_violations"].items() if v}
    if sm["structural_violations"] or det:
        raise ValidationGateError(f"clean baseline violates its contract: failed checks={sm['failed_structural_checks']}, unexpected detector findings={det}")


def _gate_injected(inj: dict, scores: dict) -> None:
    sm = inj["summary"]
    if sm["structural_violations"]:
        raise ValidationGateError(f"injection caused UNPLANNED structural failures: {sm['failed_structural_checks']}")
    off = {k: v for k, v in scores.items() if v["false_positives"] or v["false_negatives"] or v["injected"] == 0}
    if off:
        raise ValidationGateError(f"detector findings do not reconcile to ground-truth labels: {off}")


def _publish(stage: Path, final_dir: Path, attempt_id: str) -> None:
    final_dir.mkdir(parents=True, exist_ok=True)
    keep = {"_history", "failed_attempts", "run_ledger.jsonl"}
    existing = [x for x in final_dir.iterdir() if x.name not in keep]
    if existing:
        prev = "previous"
        if (final_dir / "run_attempt.json").exists():
            try:
                prev = json.loads((final_dir / "run_attempt.json").read_text())["attempt_id"]
            except Exception:
                pass
        arch = final_dir / "_history" / prev
        arch.mkdir(parents=True, exist_ok=True)
        for x in existing:
            shutil.move(str(x), str(arch / x.name))
    for x in stage.iterdir():
        shutil.move(str(x), str(final_dir / x.name))
    shutil.rmtree(stage, ignore_errors=True)

def data_profile(tables: dict, m: forecasting.Mats, truth: dict, cfg: dict) -> dict:
    valid, active = m.valid, m.active
    units = m.units
    n_act = int(active.sum())
    instock = valid & True
    zero_instock = float(((units == 0) & instock).sum() / max(instock.sum(), 1))
    cat = m.pairs["cat_idx"].to_numpy()
    cat_names = sorted(set(tables["sku"]["category"]))
    rate = np.where(valid.sum(1) > 0, np.where(valid, units, 0).sum(1) / np.maximum(valid.sum(1), 1), 0)
    seg = forecasting.classify(units.astype(float), valid, int(cfg["min_history_days"]))
    dates = pd.to_datetime(m.start) + pd.to_timedelta(np.arange(m.n_days), unit="D")
    months = dates.month.to_numpy()
    season = {}
    for k, name in enumerate(cat_names):
        sel = (cat == k)
        if not sel.any():
            continue
        per_month = {}
        for mo in range(1, 13):
            cols = months == mo
            msk = valid[sel][:, cols]
            if msk.sum() > 0:
                per_month[str(mo)] = round(float(units[sel][:, cols][msk].mean()), 4)
        season[name] = per_month
    promo_days = valid & (m.depth > 0)
    lt = tables["lead_time_observation"]
    lt = lt[lt["lead_time_days"] >= 0]
    by_sup = lt.assign(supplier_id=np.asarray(lt["supplier_id"]).astype(str)).groupby("supplier_id")["lead_time_days"].agg(["mean", "std", "count"])
    ssc = tables["supplier_sku"]
    return {
        "history_days": int(m.n_days), "n_skus": int(len(tables["sku"])), "n_stores": int(len(tables["store"])),
        "n_store_sku_pairs": int(len(tables["store_sku"])), "assortment_density": round(len(tables["store_sku"]) / (len(tables["sku"]) * len(tables["store"])), 4),
        "sales_rows": int(len(tables["sales_history"])),
        "zero_sales_share_of_in_stock_days": round(zero_instock, 4),
        "stockout_flag_share_of_active_days": round(float((m.flag & active).sum() / max(n_act, 1)), 4),
        "simulated_fill_rate": round(truth["fill_rate"], 4),
        "mean_daily_units_per_pair_quantiles": {q: round(float(np.quantile(rate[rate > 0], v)), 4) for q, v in
                                                {"p10": .1, "p50": .5, "p90": .9, "p99": .99}.items()} if (rate > 0).any() else {},
        "demand_segments": {s: int((seg == s).sum()) for s in forecasting.SEGMENTS},
        "promo_day_share": round(float(promo_days.sum() / max(valid.sum(), 1)), 4),
        "promo_uplift_observed": round(float(units[promo_days].mean() / max(units[valid & (m.depth == 0)].mean(), 1e-9)), 3) if promo_days.any() else None,
        "category_monthly_mean_daily_units": season,
        "skus_by_status": {k: int(v) for k, v in tables["sku"]["status"].value_counts().sort_index().items()},
        "supplier_lead_time_days": {k: {"mean": round(float(v["mean"]), 2), "sd": round(float(v["std"]) if v["std"] == v["std"] else 0.0, 2), "n": int(v["count"])}
                                    for k, v in by_sup.iterrows()},
        "delayed_deliveries_share": round(float(tables["lead_time_observation"]["delay_flag"].mean()), 4),
        "pack_size_distribution": {str(k): int(v) for k, v in ssc["pack_size"].value_counts().sort_index().items()},
        "suppliers_with_multiple_skus": int((ssc.groupby("supplier_id")["sku_id"].nunique() > 1).sum()),
    }


def edge_case_coverage(tables: dict, kpis: dict, m: forecasting.Mats) -> dict:
    lt = tables["lead_time_observation"]
    lt = lt[lt["lead_time_days"] >= 0]
    n_by = lt.assign(s=np.asarray(lt["supplier_id"]).astype(str), k=np.asarray(lt["sku_id"]).astype(str)).groupby(["s", "k"]).size()
    zero_total = (m.units.sum(1) == 0) & m.active.any(1)
    no_so = ~(m.flag & m.active).any(1)
    po = tables["purchase_recommendation"]
    sku = tables["sku"]
    return {
        "normal": {"orders_drafted": kpis["n_orders_drafted"], "no_action_pairs": kpis["n_no_action_inventory_above_reorder_point"]},
        "boundary": {
            "orders_exactly_at_moq": kpis["orders_exactly_at_moq"],
            "pairs_inventory_position_equal_to_reorder_point": kpis["pairs_with_inventory_position_equal_reorder_point"],
            "skus_launching_on_first_day_of_window": int((sku["launch_date"] == m.start).sum()),
            "supplier_sku_with_single_observation": int((n_by == 1).sum()),
            "zero_sales_pairs_without_any_stockout": int((zero_total & no_so).sum()),
            "unit_tests": "tests/test_business_rules.py covers exact-MOQ, exact-ROP, pack/MOQ/capacity conflict boundaries",
        },
        "failure_exception": {"blocked_by_reason": kpis["blocked_by_reason"], "capacity_reduced": kpis["capacity_reduced"],
                              "skus_supplier_lapsed": int(sku["sku_id"].isin(po[po["reason_code"] == "NO_VALID_SUPPLIER"]["sku_id"]).sum())},
        "injected_labelled_anomalies": "see ground_truth/ground_truth.csv (5 issue types)",
    }


def _md_validation(base: dict, inj: dict | None, scores: dict | None, gt_counts: dict, cfg: dict, repro_note: str) -> str:
    def cat_table(rep):
        df = pd.DataFrame([r for r in rep["checks"] if r["category"] != "anomaly_detector"])
        g = df.groupby("category").agg(checks=("check", "count"), rows_checked=("rows_checked", "sum"), violations=("violations", "sum"), failed=("passed", lambda s: int((~s).sum())))
        return g
    lines = ["# Validation summary", "", f"Scale: `{cfg['scale']}` | seed: `{cfg['seed']}` | history: {cfg['start_date']} to {cfg['end_date']} ({cfg['n_days']} days)", "",
             "## 1. Clean baseline (before anomaly injection)", "",
             f"- Structural checks: **{base['summary']['structural_checks']}**, violations: **{base['summary']['structural_violations']}**",
             f"- Anomaly detectors on the clean baseline (expected 0): {base['summary']['anomaly_detector_violations']}", "",
             "| category | checks | rows checked | violations | failed checks |", "|---|---|---|---|---|"]
    for cat, r in cat_table(base).iterrows():
        lines.append(f"| {cat} | {int(r['checks'])} | {int(r['rows_checked'])} | {int(r['violations'])} | {int(r['failed'])} |")
    if inj is not None:
        lines += ["", "## 2. After labelled anomaly injection", "",
                  f"- Structural violations after injection (expected 0 - injections touch only their own rows): **{inj['summary']['structural_violations']}**",
                  f"- Failed structural checks: {inj['summary']['failed_structural_checks'] or 'none'}", "",
                  "| issue type | injected | detected | true pos. | false pos. | false neg. | precision | recall |", "|---|---|---|---|---|---|---|---|"]
        for k, v in scores.items():
            lines.append(f"| {k} | {v['injected']} | {v['detected']} | {v['true_positives']} | {v['false_positives']} | {v['false_negatives']} | {v['precision']:.3f} | {v['recall']:.3f} |")
        lines += ["", f"Ground-truth rows: {sum(gt_counts.values())} ({gt_counts}). Detectors use only input tables and rules; the labels live in `ground_truth/`."]
    lines += ["", "## 3. Reproducibility", "", repro_note, "",
              "## 4. All checks (baseline)", "", "| check | category | rows checked | violations |", "|---|---|---|---|"]
    for r in base["checks"]:
        lines.append(f"| `{r['check']}` | {r['category']} | {r['rows_checked']} | {r['violations']} |")
    return "\n".join(lines) + "\n"


def _html_report(summary: dict) -> str:
    def tbl(d, title):
        rows = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(json.dumps(v) if isinstance(v, (dict, list)) else str(v))}</td></tr>" for k, v in d.items())
        return f"<h2>{html.escape(title)}</h2><table>{rows}</table>"
    h = summary["holdout"]

    def fmt(x, spec=".3f"):
        return "N/A" if x is None or (isinstance(x, float) and x != x) else format(x, spec)
    mrows = "".join(
        f"<tr><td>{html.escape(str(n))}</td><td>{fmt(v['overall_daily'].get('wape'))}</td><td>{fmt(v['overall_weekly'].get('wape'))}</td><td>{fmt(v['overall_daily'].get('mae'))}</td>"
        f"<td>{fmt(v['overall_daily'].get('bias'), '+.3f')}</td><td>{fmt(v['overall_daily'].get('mase'))}</td></tr>" for n, v in h["methods"].items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Replenishment run report</title><style>
body{{font-family:system-ui,Segoe UI,Arial;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#1b2430}}
h1{{margin-bottom:.2rem}}h2{{margin-top:2rem;border-bottom:2px solid #1f3b8f;padding-bottom:.2rem;color:#1f3b8f}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}td,th{{border:1px solid #d9deea;padding:.35rem .6rem;text-align:left;vertical-align:top}}
th{{background:#eef2fb}}.cards{{display:flex;gap:1rem;flex-wrap:wrap}}.card{{flex:1 1 180px;background:#f5f7fd;border:1px solid #d9deea;border-radius:10px;padding:.8rem}}
.card b{{display:block;font-size:1.5rem;color:#1f3b8f}}</style></head><body>
<h1>SKU-location forecast &amp; replenishment - run report</h1><p>scale <b>{html.escape(summary['scale'])}</b>, seed <b>{summary['seed']}</b></p>
<div class="cards"><div class="card"><b>{summary['rows']['sales_history']:,}</b>sales rows</div>
<div class="card"><b>{summary['replenishment']['n_orders_drafted']:,}</b>orders drafted</div>
<div class="card"><b>{summary['replenishment']['n_blocked']:,}</b>blocked (exceptions)</div>
<div class="card"><b>{summary['validation']['baseline_structural_violations']}</b>baseline violations</div>
<div class="card"><b>{h['hybrid_vs_naive_wape_improvement_pct']}%</b>WAPE gain vs naive</div></div>
<h2>Temporal holdout ({h['train_end_date']} | test {h['test_start_date']} to {h['test_end_date']})</h2>
<table><tr><th>method</th><th>WAPE (daily)</th><th>WAPE (weekly)</th><th>MAE</th><th>bias</th><th>MASE</th></tr>{mrows}</table>
{tbl(summary['replenishment'], 'Replenishment KPIs')}{tbl(summary['detector_scores'], 'Anomaly detection vs ground truth')}{tbl(summary['data_profile'], 'Data profile')}
</body></html>"""


def run(scale: str = "starter", seed: int | None = None, out: str | Path | None = None, do_inject: bool = True, verbose: bool = True,
        write_docs: bool = True) -> dict:
    """Run the pipeline into a staging directory; publish to `out` only if every validation gate passes.

    A failed run never replaces the active outputs: diagnostics go to <out>/failed_attempts/<attempt_id>/ and the ledger
    (<out>/run_ledger.jsonl) records STARTED / SUCCEEDED / FAILED. A previous successful run is archived in <out>/_history/.
    """
    final_dir = Path(out) if out else ROOT / "data" / scale
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    stage = final_dir.parent / f".{final_dir.name}.stage-{attempt_id}"
    started = _now()
    _ledger_append(final_dir, {"event": "STARTED", "attempt_id": attempt_id, "at": started, "scale": scale, "seed": seed})
    try:
        res = _run_stage(scale, seed, stage, do_inject, verbose, write_docs, attempt_id, started)
    except BaseException as exc:
        diag = final_dir / "failed_attempts" / attempt_id
        diag.mkdir(parents=True, exist_ok=True)
        _dump(diag / "diagnostics.json", {"attempt_id": attempt_id, "error_type": type(exc).__name__, "error": str(exc), "at": _now()})
        shutil.rmtree(stage, ignore_errors=True)
        _ledger_append(final_dir, {"event": "FAILED", "attempt_id": attempt_id, "at": _now(), "error_type": type(exc).__name__, "error": str(exc)})
        raise
    _publish(stage, final_dir, attempt_id)
    _ledger_append(final_dir, {"event": "SUCCEEDED", "attempt_id": attempt_id, "at": _now()})
    res["out_dir"] = final_dir
    res["attempt_id"] = attempt_id
    return res


def _run_stage(scale, seed, out_dir: Path, do_inject: bool, verbose: bool, write_docs: bool, attempt_id: str, started: str) -> dict:
    t0 = time.time()
    cfg = load_config(scale, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (lambda *a: print(f"[{time.time() - t0:7.1f}s]", *a, flush=True)) if verbose else (lambda *a: None)

    log(f"generating masters + {cfg['n_skus']} SKUs x {cfg['n_stores']} stores x {cfg['n_days']} days (seed {cfg['seed']})")
    g = generate(cfg)
    tables, aux, censored, truth = g["tables"], g["aux"], g["censored_demand"], g["truth"]
    log(f"  sales rows={len(tables['sales_history']):,} lead-time obs={len(tables['lead_time_observation']):,} censored(lost-sale) rows={len(censored):,}")

    log("building matrices + temporal-holdout evaluation")
    m = forecasting.build_mats(tables, aux)
    holdout = forecasting.evaluate_holdout(m, int(cfg["holdout_days"]), int(cfg["min_history_days"]))
    log(f"  hybrid vs naive WAPE improvement: {holdout['hybrid_vs_naive_wape_improvement_pct']}%")

    log("month-ahead forecasts, reorder policies, purchase recommendations")
    fct, _ = forecasting.build_forecast_table(m, tables, aux, cfg)
    pol = replenishment.build_policy_table(m, tables, aux, cfg)
    po, exc, po_ev, kpis = replenishment.build_recommendations(m, tables, aux, cfg, fct, pol)
    tables["forecast"] = fct.drop(columns=["_row"]).reset_index(drop=True)
    tables["reorder_policy"] = pol.drop(columns=["_row"]).reset_index(drop=True)
    tables["purchase_recommendation"] = po
    tables["exception_log"] = exc
    # append-only lifecycle history for policies and recommendations
    ev = []
    for r in tables["reorder_policy"].itertuples(index=False):
        ev.append(("REORDER_POLICY", r.policy_id, None, "ACTIVE", r.effective_from, "POLICY_CREATED"))
        if r.status == "SUPERSEDED":
            ev.append(("REORDER_POLICY", r.policy_id, "ACTIVE", "SUPERSEDED", cfg["as_of_date"], "NEW_POLICY_VERSION"))
    for r in po[po["status"] == "DRAFT"].itertuples(index=False):
        ev.append(("PURCHASE_RECOMMENDATION", r.po_id, None, "DRAFT", cfg["as_of_date"], "RECOMMENDATION_CREATED"))
    for r in po_ev.itertuples(index=False):
        ev.append(tuple(r))
    old = tables["status_event"]
    new = pd.DataFrame(ev, columns=["entity_type", "entity_id", "old_status", "new_status", "event_date", "reason"])
    new.insert(0, "event_id", [ids.event_id(len(old) + i + 1) for i in range(len(new))])
    tables["status_event"] = pd.concat([old, new], ignore_index=True)
    log(f"  forecasts={len(fct):,} policies={len(pol):,} recommendations={len(po):,} (blocked {kpis['n_blocked']:,}) exceptions={len(exc):,}")

    profile = data_profile(tables, m, truth, cfg)
    coverage = edge_case_coverage(tables, kpis, m)
    hist_kpis = {
        "source": "historical simulation under the (noisy) planner policy that generated the history",
        "fill_rate": round(truth["fill_rate"], 4), "stockout_day_rate": round(truth["stockout_day_rate"], 4),
        "lost_units_to_stockouts": truth["lost_units"], "avg_on_hand_units_per_pair_day": round(truth["avg_on_hand_units"], 3),
        "avg_on_hand_value_per_pair_day": round(truth["avg_on_hand_value"], 2),
    }

    log("validating CLEAN baseline")
    base = validate.run_validation(tables, aux, cfg)
    log(f"  baseline structural violations: {base['summary']['structural_violations']} | detectors: {base['summary']['anomaly_detector_violations']}")
    _gate_baseline(base)                                    # fail closed: nothing is exported if the clean baseline is broken
    clean_po, clean_exc = tables["purchase_recommendation"].copy(), tables["exception_log"].copy()
    kpis["population"] = "CLEAN BASELINE (before anomaly injection)"

    gt = pd.DataFrame(columns=inject.GT_COLS)
    inj_rep, scores = None, None
    if do_inject:
        log("injecting labelled anomalies")
        gt = inject.inject(tables, censored, aux, cfg)
        inj_rep = validate.run_validation(tables, aux, cfg)
        scores = validate.score_detectors(inj_rep, gt)
        log(f"  injected={len(gt)} | structural violations after injection: {inj_rep['summary']['structural_violations']}")
        for k, v in scores.items():
            log(f"    {k}: injected={v['injected']} detected={v['detected']} precision={v['precision']:.2f} recall={v['recall']:.2f}")
        _gate_injected(inj_rep, scores)                     # fail closed: unplanned structural damage or unreconciled detectors

    log("exporting CSV / JSON / SQL / ground truth")
    info = export.export_all(tables, gt, censored, out_dir, cfg)
    (out_dir / "clean_baseline" / "tables").mkdir(parents=True, exist_ok=True)
    clean_po.to_csv(out_dir / "clean_baseline" / "tables" / "purchase_recommendation.csv", index=False, lineterminator="\n")
    clean_exc.to_csv(out_dir / "clean_baseline" / "tables" / "exception_log.csv", index=False, lineterminator="\n")
    gt_counts = {k: int(v) for k, v in gt["issue_type"].value_counts().sort_index().items()} if len(gt) else {}

    summary = {
        "scale": cfg["scale"], "seed": cfg["seed"], "rows": info["row_counts"],
        "data_profile": profile, "holdout": holdout, "replenishment": kpis, "historical_service_kpis": hist_kpis,
        "edge_case_coverage": coverage, "detector_scores": scores or {},
        "post_injection_evaluation": ({"population": "AFTER INJECTION (labelled anomalies present; not a business KPI)",
                                       "n_orders_drafted": int((tables["purchase_recommendation"]["status"] != "BLOCKED").sum()),
                                       "n_blocked": int((tables["purchase_recommendation"]["status"] == "BLOCKED").sum())} if do_inject else {}),
        "validation": {"baseline_structural_violations": base["summary"]["structural_violations"],
                       "baseline_anomaly_detector_violations": base["summary"]["anomaly_detector_violations"],
                       "injected_structural_violations": inj_rep["summary"]["structural_violations"] if inj_rep else None,
                       "injected_failed_structural_checks": inj_rep["summary"]["failed_structural_checks"] if inj_rep else None},
    }
    _dump(out_dir / "metrics" / "forecast_holdout_metrics.json", holdout)
    _dump(out_dir / "metrics" / "replenishment_kpis.json", {"recommendations": kpis, "historical_service": hist_kpis})
    _dump(out_dir / "metrics" / "data_profile.json", profile)
    _dump(out_dir / "metrics" / "edge_case_coverage.json", coverage)
    _dump(out_dir / "metrics" / "detector_scores.json", scores or {})
    _dump(out_dir / "metrics" / "validation_checks.json", {"baseline": base["checks"], "injected": inj_rep["checks"] if inj_rep else None})
    _dump(out_dir / "metrics" / "run_summary.json", summary)
    repro_note = ("Run `python -m src.reproduce --scale " + cfg["scale"] + "` (or `make reproduce`) - it executes this pipeline twice in separate "
                  "processes and compares row counts and SHA-256 checksums of every output file. Evidence: `reproducibility.json`.")
    (out_dir / "validation_summary.md").write_text(_md_validation(base, inj_rep, scores, gt_counts, cfg, repro_note), encoding="utf-8")
    (out_dir / "reports").mkdir(exist_ok=True)
    (out_dir / "reports" / "report.html").write_text(_html_report(summary), encoding="utf-8")
    _dump(out_dir / "source_manifest.json", SOURCE_MANIFEST)
    manifest = {
        "generator_command": f"python -m src.pipeline --scale {cfg['scale']} --seed {cfg['seed']} --out data/{cfg['scale']}",
        "seed": cfg["seed"], "scale": cfg["scale"], "parameters": {k: cfg[k] for k in sorted(cfg) if k not in ("replenishment",)},
        "replenishment": cfg["replenishment"], "row_counts": info["row_counts"], "sql_seed_mode": info["sql"],
        "ground_truth_rows": info["ground_truth_rows"], "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    _dump(out_dir / "run_manifest.json", manifest)
    if write_docs:
        d = ROOT / "docs"
        d.mkdir(exist_ok=True)
        (d / "data_dictionary.md").write_text(schema.data_dictionary_md(), encoding="utf-8")
        (d / "schema.sql").write_text(schema.ddl(), encoding="utf-8")
        (d / "erd.md").write_text("# Entity-relationship diagram\n\n" + schema.erd_mermaid() + "\n", encoding="utf-8")
        _dump(d / "source_manifest.json", SOURCE_MANIFEST)
    _dump(out_dir / "run_attempt.json", {"attempt_id": attempt_id, "started_at": started, "finished_at": _now(), "scale": cfg["scale"], "seed": cfg["seed"]})
    sums = export.checksum_tree(out_dir)
    _dump(out_dir / "checksums.json", sums)
    log("done (validated, publishing)")
    return {"cfg": cfg, "summary": summary, "tables": tables, "aux": aux, "ground_truth": gt, "base": base, "inj": inj_rep, "scores": scores, "out_dir": out_dir}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate synthetic retail data, forecast demand and recommend replenishment.")
    ap.add_argument("--scale", default="starter", choices=["tiny", "starter", "small", "full"])
    ap.add_argument("--seed", type=int, default=None, help="override config seed (default 20261022)")
    ap.add_argument("--out", default=None, help="output directory (default data/<scale>)")
    ap.add_argument("--no-inject", action="store_true", help="skip anomaly injection (clean baseline only)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-docs", action="store_true", help="do not (re)write docs/ files")
    a = ap.parse_args(argv)
    try:
        run(a.scale, a.seed, a.out, not a.no_inject, not a.quiet, not a.no_docs)
    except ValidationGateError as exc:
        print(f"VALIDATION GATE FAILED - nothing published: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
