"""Inject the five required, LABELLED edge cases into an already-validated clean baseline.

Each injector touches only its own target rows and writes one ground-truth record per injected issue.
Labels live ONLY in ground_truth (never in input tables - there is no `is_anomaly` column anywhere).
Tables are modified in place (the clean baseline has been validated and its metrics saved before this step).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import ids
from .util import add_days, row_keys, rng_for

GT_COLS = ["issue_id", "issue_type", "entity_type", "entity_id", "store_id", "sku_id", "field", "injected_value",
           "expected_value", "expected_decision", "description"]
ISSUE_TYPES = ["STOCKOUT_AS_ZERO_DEMAND", "PACK_SIZE_VIOLATION", "DISCONTINUED_SKU_RECOMMENDED", "NEGATIVE_LEAD_TIME", "FORECAST_LEAKAGE"]


def inject(tables: dict, censored: pd.DataFrame, aux: dict, cfg: dict) -> pd.DataFrame:
    n = int(cfg["inject_per_type"])
    rng = rng_for(int(cfg["seed"]), "inject")
    gt: list[dict] = []

    def rec(issue_type, entity_type, entity_id, store_id, sku_id, field, injected, expected, decision, desc):
        gt.append(dict(issue_type=issue_type, entity_type=entity_type, entity_id=entity_id, store_id=store_id, sku_id=sku_id,
                       field=field, injected_value=injected, expected_value=expected, expected_decision=decision, description=desc))

    # 1. Stockout mistaken for zero demand: a censored (lost-sale) zero-sales day is relabelled as an ordinary zero-demand day.
    sales, inv = tables["sales_history"], tables["inventory_snapshot"]
    cand = censored[censored["units_sold"] == 0]
    if len(cand):
        pick = cand.iloc[np.sort(rng.choice(len(cand), min(n, len(cand)), replace=False))]
        key_s, *_ = row_keys(sales, aux["store_ids"], aux["sku_ids"], aux["start"], aux["n_days"])
        key_i, *_ = row_keys(inv, aux["store_ids"], aux["sku_ids"], aux["start"], aux["n_days"])
        key_p, *_ = row_keys(pick, aux["store_ids"], aux["sku_ids"], aux["start"], aux["n_days"])
        ps, pi_ = np.searchsorted(key_s, key_p), np.searchsorted(key_i, key_p)
        assert np.array_equal(key_s[ps], key_p) and np.array_equal(key_i[pi_], key_p)
        f_s = sales["stockout_flag"].to_numpy().copy()
        f_i = inv["stockout_flag"].to_numpy().copy()
        f_s[ps] = 0
        f_i[pi_] = 0
        sales["stockout_flag"] = f_s
        inv["stockout_flag"] = f_i
        for (_, r) in pick.iterrows():
            rec("STOCKOUT_AS_ZERO_DEMAND", "SALES_HISTORY", r["sale_id"], str(r["store_id"]), str(r["sku_id"]), "stockout_flag", 0, 1,
                "TREAT_AS_CENSORED", f"zero-sales day with empty shelf relabelled as zero demand; true demand {int(r['true_demand'])}")

    # 2. Reorder quantity ignores pack size.
    po = tables["purchase_recommendation"]
    ok = (po["status"] == "DRAFT") & (po["reason_code"] == "REORDER_POINT") & (po["pack_size"] > 1) & (po["recommended_qty"] > po["moq"])
    idx = np.nonzero(ok.to_numpy())[0]
    if len(idx):
        sel = np.sort(rng.choice(idx, min(n, len(idx)), replace=False))
        qty = po["recommended_qty"].to_numpy().copy()
        orig = qty[sel].copy()
        qty[sel] = orig - 1
        po["recommended_qty"] = qty
        for j, o in zip(sel, orig):
            r = po.iloc[j]
            rec("PACK_SIZE_VIOLATION", "PURCHASE_RECOMMENDATION", r["po_id"], r["store_id"], r["sku_id"], "recommended_qty", int(o - 1), int(o),
                "ROUND_UP_TO_PACK", f"quantity {int(o - 1)} is not a multiple of pack_size {int(r['pack_size'])}")

    # 3. Discontinued SKU recommended: a correctly blocked recommendation is flipped to an orderable DRAFT.
    ok = (po["status"] == "BLOCKED") & (po["reason_code"] == "DISCONTINUED_SKU") & po["pack_size"].notna()
    idx = np.nonzero(ok.to_numpy())[0]
    if len(idx):
        sel = np.sort(rng.choice(idx, min(n, len(idx)), replace=False))
        qty = po["recommended_qty"].to_numpy().copy()
        stat = po["status"].to_numpy().astype(object).copy()
        val = po["order_value"].to_numpy().copy()
        for j in sel:
            q = int(np.ceil(po["moq"].iat[j] / po["pack_size"].iat[j]) * po["pack_size"].iat[j])
            qty[j], stat[j] = q, "DRAFT"
            val[j] = round(q * float(po["unit_cost"].iat[j]), 2)
        po["recommended_qty"], po["status"], po["order_value"] = qty, stat, val
        for j in sel:
            r = po.iloc[j]
            rec("DISCONTINUED_SKU_RECOMMENDED", "PURCHASE_RECOMMENDATION", r["po_id"], r["store_id"], r["sku_id"], "status", "DRAFT", "BLOCKED",
                "BLOCK", "recommendation created after the SKU's discontinue_date")

    # 4. Negative lead time: manual-entry delivery records with receipt before order (units 0 => no inventory side effects).
    lt = tables["lead_time_observation"]
    if len(lt):
        tpl = lt.iloc[np.sort(rng.choice(len(lt), min(n, len(lt)), replace=False))]
        new = []
        base_n = len(lt)
        for k, (_, r) in enumerate(tpl.iterrows()):
            gap = int(rng.integers(1, 6))
            order_date = str(r["order_date"])
            lid = ids.lt_obs_id(base_n + k + 1)
            new.append(dict(lt_obs_id=lid, supplier_id=str(r["supplier_id"]), sku_id=str(r["sku_id"]), store_id=str(r["store_id"]),
                            order_date=order_date, receipt_date=add_days(order_date, -gap), lead_time_days=-gap, units_received=0,
                            delay_flag=0, source="MANUAL_ENTRY"))
            rec("NEGATIVE_LEAD_TIME", "LEAD_TIME_OBSERVATION", lid, str(r["store_id"]), str(r["sku_id"]), "lead_time_days", -gap, None,
                "EXCLUDE_AND_FLAG", "receipt_date earlier than order_date")
        add = pd.DataFrame(new)
        for col in ("supplier_id", "sku_id", "store_id", "order_date", "receipt_date"):
            lt[col] = lt[col].astype(str)
        tables["lead_time_observation"] = pd.concat([lt, add[lt.columns]], ignore_index=True)

    # 5. Forecast uses future sales: training cutoff placed inside the forecast period.
    fc = tables["forecast"]
    if len(fc):
        sel = np.sort(rng.choice(len(fc), min(n, len(fc)), replace=False))
        cut = fc["training_cutoff_date"].to_numpy().astype(object).copy()
        orig = cut[sel].copy()
        for j in sel:
            cut[j] = add_days(str(fc["period_start"].iat[j]), 14)
        fc["training_cutoff_date"] = cut
        for j, o in zip(sel, orig):
            r = fc.iloc[j]
            rec("FORECAST_LEAKAGE", "FORECAST", r["forecast_id"], r["store_id"], r["sku_id"], "training_cutoff_date", str(cut[j]), str(o),
                "REJECT", "training cutoff is inside the forecast period (uses future sales)")

    out = pd.DataFrame(gt, columns=GT_COLS[1:])
    out.insert(0, "issue_id", [f"ISSUE-{i + 1:05d}" for i in range(len(out))])
    return out
