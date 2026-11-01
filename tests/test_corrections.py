"""Regression tests for review corrections C01-C11 (fail-closed gate, arithmetic, lead-time validity, publication, checksums)."""
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import export, pipeline, replenishment, validate
from src.util import load_config
from tests.helpers import result


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="yfx_corr_"))


# ---------------- C01: validation is a publication gate ----------------
def test_failed_baseline_blocks_publication(monkeypatch):
    orig = validate.run_validation

    def broken(tables, aux, cfg):
        rep = orig(tables, aux, cfg)
        rep["summary"]["structural_violations"] = 1
        rep["summary"]["failed_structural_checks"] = ["reconcile.forecast_bounds"]
        return rep
    monkeypatch.setattr(validate, "run_validation", broken)
    out = _tmp() / "o"
    with pytest.raises(pipeline.ValidationGateError):
        pipeline.run("tiny", out=out, verbose=False, write_docs=False)
    assert not (out / "tables").exists() and not (out / "checksums.json").exists()
    assert list((out / "failed_attempts").glob("*/diagnostics.json"))


def test_unplanned_post_injection_failure_blocks_publication(monkeypatch):
    orig = validate.run_validation
    calls = {"n": 0}

    def second_call_breaks(tables, aux, cfg):
        rep = orig(tables, aux, cfg)
        calls["n"] += 1
        if calls["n"] == 2:
            rep["summary"]["structural_violations"] = 2
            rep["summary"]["failed_structural_checks"] = ["reconcile.order_value=qty*unit_cost"]
        return rep
    monkeypatch.setattr(validate, "run_validation", second_call_breaks)
    with pytest.raises(pipeline.ValidationGateError):
        pipeline.run("tiny", out=_tmp() / "o", verbose=False, write_docs=False)


def test_cli_exit_code_nonzero_on_gate_failure(monkeypatch):
    monkeypatch.setattr(pipeline, "_gate_baseline", lambda base: (_ for _ in ()).throw(pipeline.ValidationGateError("forced")))
    with pytest.raises(SystemExit) as e:
        pipeline.main(["--scale", "tiny", "--out", str(_tmp() / "o"), "--quiet", "--no-docs"])
    assert e.value.code == 2


# ---------------- C02: recommendation arithmetic ----------------
def _validated(po_mut):
    r = result()
    tables = dict(r["tables"])
    po = tables["purchase_recommendation"].copy()
    po_mut(po)
    tables["purchase_recommendation"] = po
    return validate.run_validation(tables, r["aux"], r["cfg"])


def test_wrong_order_value_is_detected():
    def mut(po):
        i = po.index[po["status"] == "DRAFT"][0]
        po.loc[i, "order_value"] = float(po.loc[i, "order_value"]) + 999.0
    assert "reconcile.order_value=qty*unit_cost" in _validated(mut)["summary"]["failed_structural_checks"]


def test_policy_link_to_wrong_store_sku_is_flagged_even_if_fk_exists():
    def mut(po):
        idx = po.index[po["policy_id"].notna()]
        a, b = idx[0], idx[-1]
        po.loc[a, "policy_id"], po.loc[b, "policy_id"] = po.loc[b, "policy_id"], po.loc[a, "policy_id"]
    rep = _validated(mut)
    if len(result()["tables"]["purchase_recommendation"].dropna(subset=["policy_id"])) > 1:
        assert "reconcile.policy_id_points_to_same_store_sku" in rep["summary"]["failed_structural_checks"]


def test_pack_size_fixture_keeps_monetary_arithmetic_consistent():
    r = result()
    chk = {c["check"]: c for c in r["inj"]["checks"]}
    assert chk["reconcile.order_value=qty*unit_cost"]["violations"] == 0
    assert chk["detect.order_qty_not_multiple_of_pack_size"]["violations"] > 0


def test_injected_discontinued_drafts_have_creation_events_and_no_stale_exceptions():
    r = result()
    gt = r["ground_truth"]
    ids_ = set(gt[gt["issue_type"] == "DISCONTINUED_SKU_RECOMMENDED"]["entity_id"])
    ev = r["tables"]["status_event"]
    assert ids_ <= set(ev[(ev["entity_type"] == "PURCHASE_RECOMMENDATION") & (ev["new_status"] == "DRAFT")]["entity_id"])
    assert not (set(r["tables"]["exception_log"]["entity_id"]) & ids_)


# ---------------- C03: populations are separate and labelled ----------------
def test_clean_baseline_tables_are_kept_and_kpis_are_labelled():
    r = result()
    clean = pd.read_csv(r["out_dir"] / "clean_baseline" / "tables" / "purchase_recommendation.csv")
    assert (clean["status"] != "BLOCKED").sum() == r["summary"]["replenishment"]["n_orders_drafted"]
    assert "CLEAN" in r["summary"]["replenishment"]["population"]
    assert "AFTER" in r["summary"]["post_injection_evaluation"]["population"]
    discont = r["ground_truth"][r["ground_truth"]["issue_type"] == "DISCONTINUED_SKU_RECOMMENDED"]["entity_id"]
    assert (clean[clean["po_id"].isin(discont)]["status"] == "BLOCKED").all()          # baseline copy was NOT mutated


# ---------------- C04: lead-time validity ----------------
def _lt(rows):
    return pd.DataFrame(rows, columns=["lt_obs_id", "supplier_id", "sku_id", "order_date", "receipt_date", "lead_time_days"])


def test_positive_but_inconsistent_lead_time_is_excluded():
    rows = [(f"LT-{i:07d}", "SUP-000001", "SKU-000001", "2026-01-01", "2026-01-03", 999) for i in range(1, 6)]
    st, bad = replenishment.lead_time_stats(_lt(rows), "2026-12-31")
    assert len(st) == 0 and len(bad) == 5


def test_exactly_five_good_observations_are_used():
    rows = [(f"LT-{i:07d}", "SUP-000001", "SKU-000001", "2026-01-01", f"2026-01-{2 + i:02d}", 1 + i) for i in range(1, 6)]
    st, bad = replenishment.lead_time_stats(_lt(rows), "2026-12-31")
    assert int(st["n_obs"].iloc[0]) == 5 and len(bad) == 0 and st["lt_mean"].iloc[0] == 4.0


def test_fewer_than_five_good_are_reported_with_their_count():
    rows = [(f"LT-{i:07d}", "SUP-000001", "SKU-000001", "2026-01-01", "2026-01-04", 3) for i in range(1, 4)]
    st, _ = replenishment.lead_time_stats(_lt(rows), "2026-12-31")
    assert int(st["n_obs"].iloc[0]) == 3


def test_mixed_good_and_bad_rows_only_good_reach_statistics():
    rows = [("LT-0000001", "S", "K", "2026-01-01", "2026-01-04", 3), ("LT-0000002", "S", "K", "2026-01-05", "2026-01-03", -2),
            ("LT-0000003", "S", "K", "2026-01-01", "2026-01-03", 999), ("LT-0000004", "S", "K", "2026-01-01", "not-a-date", 2),
            ("LT-0000005", "S", "K", "2026-01-01", "2026-01-02", float("inf")), ("LT-0000006", "S", "K", "2026-01-01", "2026-01-02", float("nan")),
            ("LT-0000007", "S", "K", "2026-01-01", "2026-01-05", 4)]
    st, bad = replenishment.lead_time_stats(_lt(rows), "2026-12-31")
    assert int(st["n_obs"].iloc[0]) == 2 and st["lt_mean"].iloc[0] == 3.5
    assert set(bad["lt_obs_id"]) == {"LT-0000002", "LT-0000003", "LT-0000004", "LT-0000005", "LT-0000006"}


def test_future_receipts_are_not_available_at_cutoff():
    rows = [("LT-0000001", "S", "K", "2026-01-01", "2026-01-04", 3), ("LT-0000002", "S", "K", "2026-02-01", "2026-02-04", 3)]
    st, bad = replenishment.lead_time_stats(_lt(rows), "2026-01-31")
    assert int(st["n_obs"].iloc[0]) == 1 and len(bad) == 0


# ---------------- C05: publication & history ----------------
def test_failure_does_not_replace_active_artifacts_and_retry_publishes(monkeypatch):
    out = _tmp() / "o"
    a = pipeline.run("tiny", out=out, verbose=False, write_docs=False)
    sums_a = json.loads((out / "checksums.json").read_text())
    orig = pipeline._gate_baseline
    monkeypatch.setattr(pipeline, "_gate_baseline", lambda b: (_ for _ in ()).throw(pipeline.ValidationGateError("forced")))
    with pytest.raises(pipeline.ValidationGateError):
        pipeline.run("tiny", out=out, verbose=False, write_docs=False)
    assert json.loads((out / "checksums.json").read_text()) == sums_a                 # A still active
    monkeypatch.setattr(pipeline, "_gate_baseline", orig)
    c = pipeline.run("tiny", out=out, verbose=False, write_docs=False)
    assert json.loads((out / "checksums.json").read_text()) == sums_a                 # same seed -> same business content
    events = [json.loads(x) for x in (out / "run_ledger.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["STARTED", "SUCCEEDED", "STARTED", "FAILED", "STARTED", "SUCCEEDED"]
    assert len({e["attempt_id"] for e in events}) == 3
    assert (out / "_history" / a["attempt_id"]).exists()                                # earlier success archived, not overwritten
    assert not list(out.parent.glob(".o.stage-*"))                                      # no stale staging dirs


# ---------------- C06: checksum coverage ----------------
def test_checksums_cover_metrics_and_report_and_detect_change():
    out = result()["out_dir"]
    sums = export.checksum_tree(out)
    assert any(k.startswith("metrics/") for k in sums) and "reports/report.html" in sums
    assert not any(k.split("/")[-1] in ("run_attempt.json", "run_ledger.jsonl") or k.split("/")[0] in ("_history", "failed_attempts") for k in sums)
    copy = _tmp() / "c"
    shutil.copytree(out, copy)
    (copy / "metrics" / "data_profile.json").write_text("{}")
    assert export.checksum_tree(copy) != sums


# ---------------- C07: config and master-data validation ----------------
@pytest.mark.parametrize("override", [{"holdout_days": 500}, {"forecast_horizon_days": -1}, {"n_days": 0}, {"density": [0.9, 0.1]}])
def test_invalid_config_is_rejected(override):
    with pytest.raises(ValueError):
        load_config("tiny", overrides=override)


def test_invalid_pack_size_is_not_silently_normalised():
    with pytest.raises(ValueError):
        replenishment.order_quantity(10, 0, 5, 1e9)
    with pytest.raises(ValueError):
        replenishment.order_quantity(10, -3, 5, 1e9)


def test_range_check_flags_bad_master_data():
    r = result()
    tables = dict(r["tables"])
    ss = tables["supplier_sku"].copy()
    ss.loc[ss.index[0], "pack_size"] = 0
    tables["supplier_sku"] = ss
    assert "range:supplier_sku.pack_size" in validate.run_validation(tables, r["aux"], r["cfg"])["summary"]["failed_structural_checks"]


# ---------------- C08: approval outcomes are rule-derived ----------------
def test_approval_events_follow_documented_rules():
    r = result()
    po, ev = r["tables"]["purchase_recommendation"], r["tables"]["status_event"]
    lim = float(r["cfg"]["replenishment"]["auto_approve_value_limit"])
    appr = ev[(ev["entity_type"] == "PURCHASE_RECOMMENDATION") & (ev["new_status"] == "APPROVED")]
    assert (appr["reason"] == "AUTO_APPROVE_RULE").all()
    m = po[po["po_id"].isin(appr["entity_id"])]
    assert (m["order_value"] <= lim).all() and (m["confidence"] != "LOW_CONFIDENCE").all()


# ---------------- C09: exact reorder-point boundary (hand calculated) ----------------
def test_inventory_position_equal_to_reorder_point_triggers_an_order():
    # d=2/day, L=5, SS=4 -> ROP = 2*5+4 = 14 ; R=7 -> S = 2*(5+7)+4 = 28 ; IP = 14 -> raw = 14
    rop, S, ip = 14.0, 28.0, 14
    assert replenishment.reorder_needed(ip, rop) is True
    assert replenishment.reorder_needed(15, rop) is False
    raw = max(0.0, S - ip)
    assert raw == 14.0
    assert replenishment.order_quantity(raw, 6, 12, float("inf"))[:2] == (18, "DRAFT")      # 14 -> 3 packs of 6 = 18 >= MOQ 12


# ---------------- C11: unavailable metrics render as N/A ----------------
def test_html_renders_missing_metrics_as_na():
    summary = {"scale": "x", "seed": 1, "rows": {"sales_history": 1}, "replenishment": {"n_orders_drafted": 0, "n_blocked": 0},
               "post_injection_evaluation": {}, "validation": {"baseline_structural_violations": 0}, "detector_scores": {}, "data_profile": {},
               "holdout": {"hybrid_vs_naive_wape_improvement_pct": 0, "train_end_date": "a", "test_start_date": "b", "test_end_date": "c",
                           "methods": {"m": {"overall_daily": {"wape": None, "mae": 1.0, "bias": None, "mase": None}, "overall_weekly": {"wape": None}}}}}
    assert "N/A" in pipeline._html_report(summary)