"""Reorder policies and purchase recommendations: safety stock, reorder point, pack/MOQ/capacity logic.

Formulae (documented in README):
  SS  = z * sqrt(L*sigma_d^2 + d_hat^2*sigma_L^2)      ROP = d_hat*L + SS      S = d_hat*(L+R) + SS
  IP  = on_hand + on_order + in_transit                trigger when IP <= ROP
  raw = max(0, S - IP) -> pack round-up -> MOQ -> pack round-up -> capacity cap (rounded down to pack)
Every blocked or reduced order carries an explicit reason_code (the exception path) and full lineage
(forecast_id, policy_id, supplier_id).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd

from . import ids
from .forecasting import Mats, forecast

REASONS = ["REORDER_POINT", "CAPACITY_REDUCED", "CAPACITY", "MOQ_CONFLICT", "DISCONTINUED_SKU",
           "NOT_YET_LAUNCHED", "NO_VALID_SUPPLIER", "INVALID_LEAD_TIME"]
CREATED_AT_SUFFIX = "T06:00:00Z"


def z_value(service_level: float) -> float:
    return NormalDist().inv_cdf(service_level)


def order_quantity(raw_qty: float, pack: int, moq: int, headroom_units: float) -> tuple[int, str, str]:
    """Turn a raw need into a legal order. Returns (qty, status, reason_code).

    Order of operations matters: pack round-up can exceed capacity and a capacity cap can break pack/MOQ, so the
    conflict is resolved explicitly and surfaced with a reason code instead of returning an illegal number.
    """
    pack = max(int(pack), 1)
    moq_r = int(math.ceil(round(moq / pack, 9))) * pack
    if raw_qty <= 0:
        return 0, "NO_ACTION", "REORDER_POINT"
    q1 = int(math.ceil(round(raw_qty / pack, 9))) * pack
    q2 = max(q1, moq_r)
    cap = int(math.floor(max(headroom_units, 0) / pack)) * pack if np.isfinite(headroom_units) else q2
    q3 = min(q2, cap)
    if q3 < moq_r or q3 == 0:
        return 0, "BLOCKED", ("CAPACITY" if cap == 0 else "MOQ_CONFLICT")
    return q3, "DRAFT", ("CAPACITY_REDUCED" if q3 < q2 else "REORDER_POINT")


def lead_time_stats(lt_obs: pd.DataFrame, cutoff_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per (supplier, sku) lead-time mean/sd from VALID observations received on/before cutoff.
    Negative or inconsistent observations are excluded and returned for the exception log."""
    df = lt_obs[["lt_obs_id", "supplier_id", "sku_id", "order_date", "receipt_date", "lead_time_days"]].copy()
    for col in ("supplier_id", "sku_id", "order_date", "receipt_date"):
        df[col] = np.asarray(df[col]).astype(str)
    df = df[df["receipt_date"] <= cutoff_date]
    bad = df["lead_time_days"].isna() | (df["lead_time_days"] < 0) | (df["receipt_date"] < df["order_date"])
    good = df[~bad]
    st = good.groupby(["supplier_id", "sku_id"])["lead_time_days"].agg(["count", "mean", "std"]).reset_index()
    st.columns = ["supplier_id", "sku_id", "n_obs", "lt_mean", "lt_sd"]
    st["lt_sd"] = st["lt_sd"].fillna(0.0)
    return st, df[bad]


def active_supplier(supplier_sku: pd.DataFrame, on_date: str) -> pd.DataFrame:
    """Primary SupplierSKU row effective on `on_date` (one per SKU, latest effective_from wins)."""
    ss = supplier_sku
    ok = (ss["effective_from"] <= on_date) & (ss["effective_to"].isna() | (ss["effective_to"] >= on_date)) & (ss["is_primary"] == 1)
    return ss[ok].sort_values(["sku_id", "effective_from"]).drop_duplicates("sku_id", keep="last").set_index("sku_id")


def _sku_state(sku: pd.DataFrame, on_date: str) -> np.ndarray:
    launched = sku["launch_date"].to_numpy() <= on_date
    disc = sku["discontinue_date"].notna().to_numpy() & (sku["discontinue_date"].fillna("9999-12-31").to_numpy() <= on_date)
    return np.where(~launched, "NOT_YET_LAUNCHED", np.where(disc, "DISCONTINUED", "ACTIVE"))


def compute_policies(m: Mats, tables: dict, aux: dict, cfg: dict, c: int, effective_from: str, version: int) -> pd.DataFrame:
    """Policy for every eligible pair using ONLY data before day index c (traceable via computed_from_cutoff)."""
    H = int(cfg["forecast_horizon_days"])
    rcfg = cfg["replenishment"]
    fc = forecast(m, c, H, int(cfg["min_history_days"]), with_baselines=False)
    cutoff_date = (date.fromisoformat(m.start) + timedelta(days=c - 1)).isoformat()
    pairs = m.pairs
    sku = tables["sku"]
    state = _sku_state(sku, effective_from)[pairs["sku_idx"].to_numpy()]
    eligible = (state == "ACTIVE") & m.active[:, c - 1]
    if version == 1:
        eligible &= fc.n_valid >= int(cfg["min_history_days"])
    sup = active_supplier(tables["supplier_sku"], effective_from)
    skus = pairs["sku_id"].to_numpy()
    has_sup = np.isin(skus, sup.index.to_numpy())
    eligible &= has_sup
    rows = np.nonzero(eligible)[0]
    st, _ = lead_time_stats(tables["lead_time_observation"], cutoff_date)
    st = st.set_index(["supplier_id", "sku_id"])
    out = []
    levels = rcfg["service_levels"]
    rate = fc.pred["hybrid"].mean(1)
    for r in rows:
        sku_id = skus[r]
        srow = sup.loc[sku_id]
        key = (srow["supplier_id"], sku_id)
        if key in st.index and st.loc[key, "n_obs"] >= 5:
            L, sdL, src = float(st.loc[key, "lt_mean"]), float(st.loc[key, "lt_sd"]), "OBSERVED"
        else:
            L, sdL, src = float(srow["mean_lead_time_days"]), float(srow["lead_time_sd"]), "PLANNING"
        seg = fc.segment[r]
        sl = float(levels[seg])
        z = z_value(sl)
        d = float(rate[r])
        sd = float(fc.sigma_d[r])
        R = int(rcfg["fast_review_period_days"] if d >= 2 else rcfg["review_period_days"])
        ss = z * math.sqrt(max(L * sd ** 2 + d ** 2 * sdL ** 2, 0.0))
        rop = d * L + ss
        S = d * (L + R) + ss
        out.append((pairs["store_id"].iat[r], sku_id, srow["supplier_id"], sl, round(z, 4), R, round(L, 3), round(sdL, 3), src,
                    round(d, 4), round(sd, 4), round(ss, 2), round(rop, 2), round(S, 2), seg, int(r)))
    df = pd.DataFrame(out, columns=["store_id", "sku_id", "supplier_id", "service_level", "z", "review_period_days",
                                    "mean_lead_time_days", "lead_time_sd", "lead_time_source", "daily_demand_est", "demand_sd",
                                    "safety_stock", "reorder_point", "order_up_to", "segment", "_row"])
    df["version"] = version
    df["effective_from"] = effective_from
    df["computed_from_cutoff"] = cutoff_date
    return df


def build_policy_table(m, tables, aux, cfg) -> pd.DataFrame:
    D = m.n_days
    as_of = cfg["as_of_date"]
    parts = []
    c1 = D // 2
    if c1 >= int(cfg["min_history_days"]) + 7:
        v1_from = (date.fromisoformat(m.start) + timedelta(days=c1)).isoformat()
        p1 = compute_policies(m, tables, aux, cfg, c1, v1_from, 1)
        p1["effective_to"] = (date.fromisoformat(as_of) - timedelta(days=1)).isoformat()
        p1["status"] = "SUPERSEDED"
        parts.append(p1)
    p2 = compute_policies(m, tables, aux, cfg, D, as_of, 2)
    p2["effective_to"] = None
    p2["status"] = "ACTIVE"
    parts.append(p2)
    pol = pd.concat(parts, ignore_index=True)
    pol = pol.sort_values(["store_id", "sku_id", "version"]).reset_index(drop=True)
    pol.insert(0, "policy_id", [ids.policy_id(i + 1) for i in range(len(pol))])
    return pol


def build_recommendations(m: Mats, tables: dict, aux: dict, cfg: dict, fc_table: pd.DataFrame, policies: pd.DataFrame):
    """Return (purchase_recommendation, exception_log, extra_events, kpis)."""
    D = m.n_days
    as_of = cfg["as_of_date"]
    pairs = m.pairs
    sku = tables["sku"]
    store = tables["store"]
    state = _sku_state(sku, as_of)[pairs["sku_idx"].to_numpy()]
    sup = active_supplier(tables["supplier_sku"], as_of)
    ssk = tables["supplier_sku"].sort_values(["sku_id", "effective_from"])
    last_any = ssk.drop_duplicates("sku_id", keep="last").set_index("sku_id")
    st, bad_lt = lead_time_stats(tables["lead_time_observation"], aux["end"])
    cur = policies[policies["status"] == "ACTIVE"].set_index("_row")
    fct = fc_table.set_index("_row")
    pos_last = m.pos[:, D - 1].astype(np.int64)
    oh_last = m.oh_end[:, D - 1].astype(np.int64)
    vol = pairs["vol"].to_numpy()
    store_cap = store["capacity_units"].to_numpy().astype(float)
    used = np.bincount(pairs["store_idx"].to_numpy(), weights=np.where(m.active[:, D - 1], pos_last * vol, 0.0), minlength=len(store))
    headroom = store_cap - used
    created = as_of + CREATED_AT_SUFFIX
    skus, stores_arr = pairs["sku_id"].to_numpy(), pairs["store_id"].to_numpy()

    recs, no_action = [], 0
    candidates = []
    for r in range(len(pairs)):
        s = state[r]
        sku_id = skus[r]
        base = dict(store_id=stores_arr[r], sku_id=sku_id, forecast_id=None, policy_id=None, supplier_id=None, raw_qty=0.0,
                    recommended_qty=0, pack_size=None, moq=None, inventory_position=None, reorder_point=None, order_up_to=None,
                    unit_cost=None, order_value=0.0, expected_lead_time_days=None, reason_code=None, status=None,
                    confidence=None, created_at=created, _row=r)
        last = last_any.loc[sku_id] if sku_id in last_any.index else None
        if last is not None:
            base.update(supplier_id=last["supplier_id"], pack_size=int(last["pack_size"]), moq=int(last["moq"]), unit_cost=float(last["unit_cost"]))
        if s != "ACTIVE":
            base.update(reason_code="DISCONTINUED_SKU" if s == "DISCONTINUED" else "NOT_YET_LAUNCHED", status="BLOCKED")
            recs.append(base)
            continue
        if sku_id not in sup.index:
            base.update(reason_code="NO_VALID_SUPPLIER", status="BLOCKED")
            recs.append(base)
            continue
        srow = sup.loc[sku_id]
        base.update(supplier_id=srow["supplier_id"], pack_size=int(srow["pack_size"]), moq=int(srow["moq"]), unit_cost=float(srow["unit_cost"]))
        if r not in cur.index or r not in fct.index:
            no_action += 1
            continue
        p, f = cur.loc[r], fct.loc[r]
        base.update(forecast_id=f["forecast_id"], policy_id=p["policy_id"], reorder_point=float(p["reorder_point"]),
                    order_up_to=float(p["order_up_to"]), inventory_position=int(pos_last[r]), confidence=f["confidence"],
                    expected_lead_time_days=float(p["mean_lead_time_days"]))
        if not (p["mean_lead_time_days"] > 0) or not np.isfinite(p["mean_lead_time_days"]):
            base.update(reason_code="INVALID_LEAD_TIME", status="BLOCKED")
            recs.append(base)
            continue
        if pos_last[r] > p["reorder_point"]:
            no_action += 1
            continue
        raw = round(max(0.0, float(p["order_up_to"]) - float(pos_last[r])), 2)
        base["raw_qty"] = raw
        cover = oh_last[r] / p["daily_demand_est"] if p["daily_demand_est"] > 0 else 1e9
        candidates.append((int(pairs["store_idx"].iat[r]), cover, sku_id, base))
    # capacity is a shared, finite resource per store: allocate to the most urgent (lowest days of cover) first
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    for s_idx, _, _, base in candidates:
        qty, status, reason = order_quantity(base["raw_qty"], base["pack_size"], base["moq"], headroom[s_idx] / max(vol[base["_row"]], 1e-9))
        if status == "NO_ACTION":
            no_action += 1
            continue
        base.update(recommended_qty=qty, status=status, reason_code=reason, order_value=round(qty * base["unit_cost"], 2))
        if qty > 0:
            headroom[s_idx] -= qty * vol[base["_row"]]
        recs.append(base)
    po = pd.DataFrame(recs)
    po = po.sort_values(["store_id", "sku_id"]).reset_index(drop=True)
    po.insert(0, "po_id", [ids.po_id(i + 1, int(as_of[:4])) for i in range(len(po))])

    # exception log (what the operations manager must look at)
    exc = []
    for _, r in po[po["status"] == "BLOCKED"].iterrows():
        exc.append(("BLOCKED_RECOMMENDATION", "PURCHASE_RECOMMENDATION", r["po_id"], r["store_id"], r["sku_id"], r["reason_code"],
                    f"blocked: {r['reason_code']}", "HIGH" if r["reason_code"] in ("CAPACITY", "MOQ_CONFLICT") else "MEDIUM"))
    for _, r in po[po["reason_code"] == "CAPACITY_REDUCED"].iterrows():
        exc.append(("REDUCED_RECOMMENDATION", "PURCHASE_RECOMMENDATION", r["po_id"], r["store_id"], r["sku_id"], "CAPACITY_REDUCED",
                    f"raw_qty {r['raw_qty']} reduced to {r['recommended_qty']} by store capacity", "MEDIUM"))
    for _, r in po[(po["confidence"] == "LOW_CONFIDENCE") & (po["status"] != "BLOCKED")].iterrows():
        exc.append(("LOW_CONFIDENCE_FORECAST", "PURCHASE_RECOMMENDATION", r["po_id"], r["store_id"], r["sku_id"], "LOW_CONFIDENCE",
                    "new/short-history SKU: cohort-based forecast", "LOW"))
    for _, r in bad_lt.iterrows():
        exc.append(("INVALID_LEAD_TIME_EXCLUDED", "LEAD_TIME_OBSERVATION", r["lt_obs_id"], None, r["sku_id"], "INVALID_LEAD_TIME",
                    "negative/inconsistent lead time excluded from statistics", "MEDIUM"))
    exc_df = pd.DataFrame(exc, columns=["exception_code", "entity_type", "entity_id", "store_id", "sku_id", "reason_code", "detail", "severity"])
    exc_df.insert(0, "exception_id", [ids.exception_id(i + 1) for i in range(len(exc_df))])

    # PO status events (history is appended, never overwritten): ops manager approves/cancels some drafts
    from .util import rng_for
    rr = rng_for(int(cfg["seed"]), "po_events")
    ev = []
    for _, r in po[po["status"] == "DRAFT"].iterrows():
        u = rr.random()
        if u < 0.65:
            ev.append(("PURCHASE_RECOMMENDATION", r["po_id"], "DRAFT", "APPROVED", (date.fromisoformat(as_of) + timedelta(days=1)).isoformat(), "OPS_APPROVAL"))
        elif u < 0.70:
            ev.append(("PURCHASE_RECOMMENDATION", r["po_id"], "DRAFT", "CANCELLED", (date.fromisoformat(as_of) + timedelta(days=2)).isoformat(), "OPS_CANCELLED"))
    ev_df = pd.DataFrame(ev, columns=["entity_type", "entity_id", "old_status", "new_status", "event_date", "reason"])

    nb = po[po["status"] != "BLOCKED"]
    kpis = {
        "as_of_date": as_of,
        "n_pairs_evaluated": int(len(pairs)),
        "n_no_action_inventory_above_reorder_point": int(no_action),
        "n_recommendations": int(len(po)),
        "n_orders_drafted": int(len(nb)),
        "n_blocked": int((po["status"] == "BLOCKED").sum()),
        "blocked_share": float((po["status"] == "BLOCKED").mean()) if len(po) else 0.0,
        "blocked_by_reason": {k: int(v) for k, v in po[po["status"] == "BLOCKED"]["reason_code"].value_counts().sort_index().items()},
        "capacity_reduced": int((po["reason_code"] == "CAPACITY_REDUCED").sum()),
        "ordered_units": int(nb["recommended_qty"].sum()),
        "ordered_value": round(float(nb["order_value"].sum()), 2),
        "low_confidence_orders": int(((po["confidence"] == "LOW_CONFIDENCE") & (po["status"] != "BLOCKED")).sum()),
        "orders_exactly_at_moq": int(((nb["recommended_qty"] == nb["moq"]) & (nb["recommended_qty"] > 0)).sum()),
        "pairs_with_inventory_position_equal_reorder_point": int(((po["inventory_position"].notna()) & (po["inventory_position"] == po["reorder_point"])).sum()),
        "store_capacity_headroom_after_orders_min": round(float(headroom.min()), 2) if len(headroom) else None,
    }
    return po.drop(columns=["_row"]), exc_df, ev_df, kpis
