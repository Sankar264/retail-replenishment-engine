import numpy as np
from src.replenishment import order_quantity
from tests.helpers import result


def test_quantity_is_pack_multiple_and_meets_moq():
    q, st, rc = order_quantity(7.2, 6, 12, float("inf"))
    assert (q, st, rc) == (12, "DRAFT", "REORDER_POINT")          # raw -> 12 (pack) ; MOQ 12 satisfied


def test_boundary_exactly_moq_and_exactly_pack():
    assert order_quantity(12.0, 6, 12, 1e9)[0] == 12              # raw == MOQ == 2 packs
    assert order_quantity(6.0, 6, 6, 1e9)[0] == 6                 # raw == one pack
    assert order_quantity(0.0, 6, 6, 1e9)[1] == "NO_ACTION"       # nothing needed


def test_capacity_cap_rounds_down_to_pack_and_flags_reduction():
    q, st, rc = order_quantity(30, 6, 6, 20)                      # headroom 20 -> 18 (3 packs)
    assert (q, st, rc) == (18, "DRAFT", "CAPACITY_REDUCED")


def test_capacity_conflicts_are_blocked_with_reason():
    assert order_quantity(30, 6, 12, 8)[1:] == ("BLOCKED", "MOQ_CONFLICT")    # headroom 8 -> 6 < MOQ 12
    assert order_quantity(30, 6, 6, 4)[1:] == ("BLOCKED", "CAPACITY")        # no full pack fits
    assert order_quantity(30, 6, 6, -5)[1:] == ("BLOCKED", "CAPACITY")       # negative headroom


def test_moq_not_multiple_of_pack_is_rounded_up():
    assert order_quantity(1, 6, 10, 1e9)[0] == 12


def test_all_orderable_recommendations_respect_pack_moq_capacity():
    r = result()
    # validation runs on the clean baseline BEFORE injection - these are the acceptance-criteria checks
    checks = {c["check"]: c for c in r["base"]["checks"]}
    for k in ["business.moq_respected", "business.capacity_respected_per_store", "business.recommendation_has_valid_supplier",
              "detect.order_qty_not_multiple_of_pack_size", "detect.discontinued_sku_recommended"]:
        assert checks[k]["violations"] == 0, k
    assert checks["business.moq_respected"]["rows_checked"] >= 0


def test_blocked_recommendations_have_reasons():
    po = result()["tables"]["purchase_recommendation"]
    b = po[po["status"] == "BLOCKED"]
    assert b["reason_code"].notna().all()
    assert (b["recommended_qty"] == 0).all()


def test_stockout_censoring_is_identified_and_separate_from_zero_demand():
    r = result()
    s, inv = r["tables"]["sales_history"], r["tables"]["inventory_snapshot"]
    zero_empty = (s["units_sold"] == 0) & (inv["on_hand"] == 0)
    assert zero_empty.sum() > 0
    # genuine zero-demand days (stock available) exist and are NOT flagged
    assert (((s["units_sold"] == 0) & (inv["on_hand"] > 0)) & (s["stockout_flag"] == 1)).sum() == 0
    assert ((s["units_sold"] == 0) & (inv["on_hand"] > 0)).sum() > 0
    assert r["summary"]["edge_case_coverage"]["failure_exception"] is not None


def test_ground_truth_is_separate_and_not_leaked_into_inputs():
    r = result()
    leaked = {"issue_type", "issue_id", "is_anomaly", "expected_decision", "true_demand", "units_demanded", "ground_truth"}
    for name, df in r["tables"].items():
        assert not (leaked & set(df.columns)), name
    assert (r["out_dir"] / "ground_truth" / "ground_truth.csv").exists()
    assert set(r["ground_truth"]["issue_type"]) == {"STOCKOUT_AS_ZERO_DEMAND", "PACK_SIZE_VIOLATION", "DISCONTINUED_SKU_RECOMMENDED",
                                                    "NEGATIVE_LEAD_TIME", "FORECAST_LEAKAGE"}


def test_detectors_find_every_injected_issue_exactly():
    for issue, s in result()["scores"].items():
        assert s["injected"] > 0, issue
        assert s["precision"] == 1.0 and s["recall"] == 1.0, (issue, s)


def test_no_sales_before_launch_or_after_discontinue():
    checks = {c["check"]: c for c in result()["base"]["checks"]}
    assert checks["lifecycle.no_sales_before_launch"]["violations"] == 0
    assert checks["lifecycle.no_sales_on_or_after_discontinue"]["violations"] == 0
