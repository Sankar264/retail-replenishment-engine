"""Validation suite: PK/FK/enum/required/date-order/reconciliation/lifecycle/duplicate checks + the five anomaly detectors.

Detectors use ONLY input tables and business rules (never the ground truth). Scoring against ground truth happens
separately in `score_detectors`. Baseline run must show 0 violations everywhere; the injected run must show violations
only in the five anomaly detectors, with precision = recall = 1 against the labels.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import ids, schema
from .util import codes, day_index, row_keys

ANOMALY_CHECKS = {
    "STOCKOUT_AS_ZERO_DEMAND": "detect.stockout_flagged_as_zero_demand",
    "PACK_SIZE_VIOLATION": "detect.order_qty_not_multiple_of_pack_size",
    "DISCONTINUED_SKU_RECOMMENDED": "detect.discontinued_sku_recommended",
    "NEGATIVE_LEAD_TIME": "detect.negative_lead_time",
    "FORECAST_LEAKAGE": "detect.forecast_uses_future_sales",
}
ID_FORMATS = {
    "supplier": ("supplier_id", ids.SUPPLIER_RE), "store": ("store_id", ids.STORE_RE), "sku": ("sku_id", ids.SKU_RE),
    "forecast": ("forecast_id", ids.FC_RE), "purchase_recommendation": ("po_id", ids.PO_RE),
    "lead_time_observation": ("lt_obs_id", ids.LT_RE), "reorder_policy": ("policy_id", ids.POLICY_RE),
}


class Checker:
    def __init__(self):
        self.results = []
        self.flagged: dict[str, set] = {}

    def add(self, name, category, table, checked, bad_idx=None, bad_ids=None, note=""):
        n_bad = int(len(bad_ids) if bad_ids is not None else (0 if bad_idx is None else len(bad_idx)))
        sample = [str(x) for x in (bad_ids[:5] if bad_ids is not None else [])]
        self.results.append(dict(check=name, category=category, table=table, rows_checked=int(checked), violations=n_bad,
                                 passed=n_bad == 0, sample=sample, note=note))
        if bad_ids is not None:
            self.flagged[name] = set(str(x) for x in bad_ids)


def _str(s) -> np.ndarray:
    return np.asarray(s).astype(str)


def _with_ids(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Materialise derived IDs for sales / inventory (they are not kept in memory for the big tables)."""
    if name == "sales_history" and "sale_id" not in df.columns:
        return df.assign(sale_id=ids.sale_ids(np.asarray(df["store_id"]), np.asarray(df["sku_id"]), np.asarray(df["date"])))
    if name == "inventory_snapshot" and "snapshot_id" not in df.columns:
        return df.assign(snapshot_id=ids.inventory_ids(np.asarray(df["store_id"]), np.asarray(df["sku_id"]), np.asarray(df["date"])))
    return df


def run_validation(tables: dict, aux: dict, cfg: dict) -> dict:
    ck = Checker()
    stores, skus = aux["store_ids"], aux["sku_ids"]
    D, start = aux["n_days"], aux["start"]
    as_of = cfg["as_of_date"]

    # -------- required fields, enums, id formats, primary keys, foreign keys -------------------------------
    for name in schema.ORDER:
        df = tables[name]
        spec = schema.T[name]
        n = len(df)
        missing = [c for c in schema.columns(name) if c not in df.columns and c not in ("sale_id", "snapshot_id")]
        ck.add(f"schema.columns_present:{name}", "schema", name, n, bad_ids=missing)
        for c in spec["cols"]:
            if c["name"] not in df.columns:
                continue
            col = df[c["name"]]
            if c["required"]:
                nulls = int(col.isna().sum())
                ck.add(f"required:{name}.{c['name']}", "required", name, n, bad_idx=range(nulls))
            ev = schema.enum_values(c)
            if ev:
                vc = col.value_counts(dropna=True)
                bad = int(sum(cnt for val, cnt in vc.items() if str(int(val) if c["type"] == "bool" else val) not in ev))
                ck.add(f"enum:{name}.{c['name']}", "enum", name, n, bad_idx=range(bad))
        dfi = _with_ids(name, df) if name in ("sales_history", "inventory_snapshot") else df
        pk = spec["pk"]
        if name in ("sales_history", "inventory_snapshot"):
            key, *_ = row_keys(df, stores, skus, start, D)
            dups = len(key) - len(np.unique(key))
            ck.add(f"pk_unique:{name}", "primary_key", name, n, bad_idx=range(dups), note="(store, sku, date) grain; id is a deterministic function of the grain")
            pat = ids.SALE_RE if name == "sales_history" else ids.INV_RE
            sample = dfi[pk[0]].to_numpy()[:: max(1, n // 20000)]
            bad = [x for x in sample if not pat.match(x)]
            ck.add(f"id_format:{name}.{pk[0]}", "id_format", name, len(sample), bad_ids=bad, note="sampled")
        else:
            dups = df[pk].astype(str).duplicated().sum()
            ck.add(f"pk_unique:{name}", "primary_key", name, n, bad_idx=range(int(dups)))
            if name in ID_FORMATS:
                col, pat = ID_FORMATS[name]
                bad = [x for x in _str(df[col]) if not pat.match(x)]
                ck.add(f"id_format:{name}.{col}", "id_format", name, n, bad_ids=bad)
        for cols, parent, pcols in spec["fks"]:
            child = tables[name][cols].dropna()
            if len(child) == 0:
                ck.add(f"fk:{name}({','.join(cols)})->{parent}", "foreign_key", name, 0, bad_idx=[])
                continue
            par = tables[parent][pcols]
            cats = [pd.unique(np.asarray(par[p0]).astype(str)) for p0 in pcols]
            cc = [codes(child[c0], cat) for c0, cat in zip(cols, cats)]
            if len(cols) == 1:
                bad = int((cc[0] < 0).sum())
            else:
                width = len(cats[1]) + 1
                pcodes = codes(par[pcols[0]], cats[0]) * width + codes(par[pcols[1]], cats[1])
                bad = int(((cc[0] < 0) | (cc[1] < 0) | ~np.isin(cc[0] * width + cc[1], pcodes)).sum())
            ck.add(f"fk:{name}({','.join(cols)})->{parent}", "foreign_key", name, len(child), bad_idx=range(bad))

    sku = tables["sku"]
    sales, inv, lt = tables["sales_history"], tables["inventory_snapshot"], tables["lead_time_observation"]
    n_s = len(sales)
    sk_i = codes(sales["sku_id"], skus)
    k_s, ps, ks, ds = row_keys(sales, stores, skus, start, D)
    k_i, *_ = row_keys(inv, stores, skus, start, D)

    # -------- date ordering & lifecycle --------------------------------------------------------------------
    launch = day_index(sku["launch_date"], start)
    disc_raw = sku["discontinue_date"].fillna("2999-12-31")
    disc = (pd.to_datetime(disc_raw, format="%Y-%m-%d").to_numpy().astype("datetime64[D]") - np.datetime64(start, "D")).astype(np.int64)
    ck.add("lifecycle.no_sales_before_launch", "lifecycle", "sales_history", n_s, bad_idx=np.nonzero(ds < launch[sk_i])[0])
    ck.add("lifecycle.no_sales_on_or_after_discontinue", "lifecycle", "sales_history", n_s, bad_idx=np.nonzero(ds >= disc[sk_i])[0])
    ck.add("date_order:sku.launch<discontinue", "date_order", "sku", len(sku), bad_idx=np.nonzero(disc <= launch)[0])
    ss = tables["supplier_sku"]
    both = ss["effective_to"].notna()
    ck.add("date_order:supplier_sku.effective_from<effective_to", "date_order", "supplier_sku", len(ss),
           bad_idx=np.nonzero((ss.loc[both, "effective_from"] >= ss.loc[both, "effective_to"]).to_numpy())[0])
    pol = tables["reorder_policy"]
    pb = pol["effective_to"].notna()
    ck.add("date_order:reorder_policy.effective_from<effective_to", "date_order", "reorder_policy", len(pol),
           bad_idx=np.nonzero((pol.loc[pb, "effective_from"] >= pol.loc[pb, "effective_to"]).to_numpy())[0])
    ck.add("date_order:reorder_policy.cutoff<effective_from", "date_order", "reorder_policy", len(pol),
           bad_idx=np.nonzero((pol["computed_from_cutoff"] >= pol["effective_from"]).to_numpy())[0])
    ck.add("lifecycle.one_active_policy_per_store_sku", "lifecycle", "reorder_policy", len(pol),
           bad_idx=range(int(pol[pol["status"] == "ACTIVE"][["store_id", "sku_id"]].duplicated().sum())))
    # primary supplier overlap
    prim = ss[ss["is_primary"] == 1].sort_values(["sku_id", "effective_from"])
    nxt_from = prim.groupby("sku_id")["effective_from"].shift(-1)
    ck.add("lifecycle.primary_supplier_no_overlap", "lifecycle", "supplier_sku", len(prim),
           bad_idx=np.nonzero((nxt_from.notna() & (prim["effective_to"].isna() | (prim["effective_to"] >= nxt_from))).to_numpy())[0])
    # status events: legal chains, no resurrection, status consistent with the SKU table
    legal_pairs = {
        "SKU": {(None, "PLANNED"), (None, "ACTIVE"), ("PLANNED", "ACTIVE"), ("ACTIVE", "DISCONTINUED")},
        "PURCHASE_RECOMMENDATION": {(None, "DRAFT"), ("DRAFT", "APPROVED"), ("DRAFT", "CANCELLED")},
        "REORDER_POLICY": {(None, "ACTIVE"), ("ACTIVE", "SUPERSEDED")},
    }
    ev = tables["status_event"].sort_values(["entity_type", "entity_id", "event_id"], kind="stable").reset_index(drop=True)
    old = ev["old_status"].astype(object).where(ev["old_status"].notna(), None)
    new_s = ev["new_status"].astype(object)
    same = (ev["entity_id"].to_numpy()[1:] == ev["entity_id"].to_numpy()[:-1]) & (ev["entity_type"].to_numpy()[1:] == ev["entity_type"].to_numpy()[:-1])
    prev_new = pd.Series(np.concatenate([[None], new_s.to_numpy()[:-1]]), dtype=object)
    first = np.concatenate([[True], ~same])
    chain_ok = np.where(first, old.isna().to_numpy(), (old.to_numpy() == prev_new.to_numpy()))
    pair_ok = np.array([(None if pd.isna(o) else o, n) in legal_pairs.get(t, set()) for o, n, t in zip(ev["old_status"], new_s, ev["entity_type"])])
    dates_s = ev["event_date"].astype(str).to_numpy()
    date_ok = np.concatenate([[True], np.where(same, dates_s[1:] >= dates_s[:-1], True)])
    bad = ev["entity_id"].to_numpy()[~(chain_ok & pair_ok & date_ok)].tolist()
    ck.add("lifecycle.status_event_transitions_legal", "lifecycle", "status_event", len(ev), bad_ids=bad)
    last_status = ev[ev["entity_type"] == "SKU"].groupby("entity_id")["new_status"].last()
    cur = sku.set_index("sku_id")["status"]
    mism = [i for i in cur.index if last_status.get(i) != cur[i]]
    ck.add("lifecycle.sku_status_matches_last_event", "lifecycle", "sku", len(cur), bad_ids=mism)

    # -------- reconciliation (derived values come from source rows) -----------------------------------------
    same_grain = np.array_equal(k_s, k_i)
    ck.add("reconcile.sales_and_inventory_same_grain", "reconciliation", "inventory_snapshot", n_s, bad_idx=[] if same_grain else [0])
    if same_grain:
        recon = (inv["on_hand_start"].to_numpy().astype(np.int64) + inv["receipts"].to_numpy() - sales["units_sold"].to_numpy()) != inv["on_hand"].to_numpy()
        ck.add("reconcile.on_hand=start+receipts-sold", "reconciliation", "inventory_snapshot", n_s, bad_idx=np.nonzero(recon)[0])
        over = sales["units_sold"].to_numpy() > inv["on_hand_start"].to_numpy() + inv["receipts"].to_numpy()
        ck.add("reconcile.units_sold<=available_stock", "reconciliation", "sales_history", n_s, bad_idx=np.nonzero(over)[0])
        pair = k_i // D
        cont = (pair[1:] == pair[:-1]) & (k_i[1:] - k_i[:-1] == 1)
        brk = cont & (inv["on_hand_start"].to_numpy()[1:] != inv["on_hand"].to_numpy()[:-1])
        ck.add("reconcile.opening_balance=previous_closing", "reconciliation", "inventory_snapshot", int(cont.sum()), bad_idx=np.nonzero(brk)[0])
        ck.add("reconcile.stockout_flag_sales=inventory", "reconciliation", "inventory_snapshot", n_s,
               bad_idx=np.nonzero(sales["stockout_flag"].to_numpy() != inv["stockout_flag"].to_numpy())[0])
        # receipts by (pair, receipt day) must equal lead_time_observation units
        lt_ok = lt[lt["units_received"] > 0]
        lk, *_ = row_keys(lt_ok.assign(date=lt_ok["receipt_date"]), stores, skus, start, D)
        agg = pd.Series(lt_ok["units_received"].to_numpy()).groupby(lk).sum()
        got = pd.Series(inv["receipts"].to_numpy(), index=k_i)
        got = got[got > 0]
        diff = agg.reindex(got.index.union(agg.index)).fillna(0) != got.reindex(got.index.union(agg.index)).fillna(0)
        ck.add("reconcile.receipts=sum(lead_time_observation.units)", "reconciliation", "inventory_snapshot", len(got), bad_idx=range(int(diff.sum())))
    rev = np.abs(sales["net_revenue"].to_numpy() - np.round(sales["units_sold"].to_numpy() * sales["price"].to_numpy(), 2)) > 0.011
    ck.add("reconcile.net_revenue=units*price", "reconciliation", "sales_history", n_s, bad_idx=np.nonzero(rev)[0])
    promo_bad = (sales["on_promo"].to_numpy() == 1) != (sales["promo_depth"].to_numpy() > 0)
    ck.add("reconcile.on_promo<=>promo_depth>0", "reconciliation", "sales_history", n_s, bad_idx=np.nonzero(promo_bad)[0])
    neg = (inv[["on_hand", "on_order", "in_transit", "receipts", "on_hand_start"]].to_numpy() < 0).any(1)
    ck.add("range.inventory_non_negative", "range", "inventory_snapshot", len(inv), bad_idx=np.nonzero(neg)[0])
    lt_ok_rows = lt[(lt["source"] == "RECEIPT")]
    d_calc = day_index(lt_ok_rows["receipt_date"], start) - day_index(lt_ok_rows["order_date"], start)
    ck.add("reconcile.lead_time_days=receipt-order", "reconciliation", "lead_time_observation", len(lt_ok_rows),
           bad_idx=np.nonzero(d_calc != lt_ok_rows["lead_time_days"].to_numpy())[0])
    man = lt[lt["source"] == "MANUAL_ENTRY"]
    if len(man):
        d2 = day_index(man["receipt_date"], start) - day_index(man["order_date"], start)
        ck.add("reconcile.lead_time_days=receipt-order(manual)", "reconciliation", "lead_time_observation", len(man),
               bad_idx=np.nonzero(d2 != man["lead_time_days"].to_numpy())[0])
    fc = tables["forecast"]
    ck.add("reconcile.forecast_bounds", "reconciliation", "forecast", len(fc),
           bad_idx=np.nonzero(((fc["lower"] > fc["forecast_units"]) | (fc["upper"] < fc["forecast_units"])).to_numpy())[0])
    ck.add("reconcile.forecast_id_matches_keys", "id_format", "forecast", len(fc),
           bad_ids=fc["forecast_id"][fc["forecast_id"].astype(str) != pd.Series(ids.forecast_ids(_str(fc["store_id"]), _str(fc["sku_id"]), cfg["forecast_month"]), index=fc.index)].tolist())

    # -------- duplicates -------------------------------------------------------------------------------------
    po = tables["purchase_recommendation"]
    ck.add("duplicate.purchase_recommendation_per_store_sku_period", "duplicate", "purchase_recommendation", len(po),
           bad_idx=range(int(po[["store_id", "sku_id"]].astype(str).duplicated().sum())))
    ck.add("duplicate.forecast_per_store_sku_month", "duplicate", "forecast", len(fc),
           bad_idx=range(int(fc[["store_id", "sku_id", "forecast_month"]].astype(str).duplicated().sum())))

    # -------- business-rule acceptance criteria on recommendations -------------------------------------------
    nb = po[po["status"] != "BLOCKED"]
    ck.add("business.moq_respected", "business_rule", "purchase_recommendation", len(nb), bad_idx=np.nonzero((nb["recommended_qty"] < nb["moq"]).to_numpy())[0])
    sup = tables["supplier_sku"]
    pr = sup[(sup["is_primary"] == 1)]
    from .replenishment import active_supplier
    act = active_supplier(sup, as_of)
    nb = nb[nb["reason_code"].isin(["REORDER_POINT", "CAPACITY_REDUCED"])]
    nb_sup = nb["sku_id"].astype(str).map(act["supplier_id"])
    ck.add("business.recommendation_has_valid_supplier", "business_rule", "purchase_recommendation", len(nb),
           bad_idx=np.nonzero((nb_sup.isna() | (nb_sup != nb["supplier_id"].astype(str))).to_numpy())[0])
    sel = po[po["reason_code"].isin(["REORDER_POINT", "CAPACITY_REDUCED"]) & (po["status"] != "BLOCKED")]
    cap = tables["store"].set_index("store_id")["capacity_units"]
    last_day = D - 1
    pos_vol = _position_volume(tables, aux)
    used = pos_vol.reindex(cap.index).fillna(0.0)
    vol = sku.set_index("sku_id")["volume_per_unit"]
    add_v = (sel["recommended_qty"].to_numpy() * sel["sku_id"].astype(str).map(vol).to_numpy())
    tot_add = pd.Series(add_v, index=sel["store_id"].astype(str).to_numpy()).groupby(level=0).sum()
    over_stores = [s for s in tot_add.index if used.get(s, 0.0) + tot_add[s] > cap[s] + 1e-6]
    ck.add("business.capacity_respected_per_store", "business_rule", "purchase_recommendation", len(tot_add), bad_ids=over_stores)
    ck.add("business.blocked_has_zero_qty", "business_rule", "purchase_recommendation", int((po["status"] == "BLOCKED").sum()),
           bad_idx=np.nonzero(((po["status"] == "BLOCKED") & (po["recommended_qty"] != 0)).to_numpy())[0])

    # -------- the five anomaly detectors (rule-based, no ground truth) ---------------------------------------
    zero_empty = (sales["units_sold"].to_numpy() == 0) & (inv["on_hand"].to_numpy() == 0) & (sales["stockout_flag"].to_numpy() == 0)
    zi = np.nonzero(zero_empty)[0]
    sub = sales.iloc[zi]
    ck.add(ANOMALY_CHECKS["STOCKOUT_AS_ZERO_DEMAND"], "anomaly_detector", "sales_history", n_s,
           bad_ids=list(ids.sale_ids(np.asarray(sub["store_id"]), np.asarray(sub["sku_id"]), np.asarray(sub["date"]))),
           note="zero sales with empty shelf but stockout_flag=0 => censored demand mistaken for zero demand")
    nbp = po[(po["status"] != "BLOCKED") & po["pack_size"].notna()]
    bad = nbp[(nbp["recommended_qty"] % nbp["pack_size"].fillna(1).astype(int)) != 0]
    ck.add(ANOMALY_CHECKS["PACK_SIZE_VIOLATION"], "anomaly_detector", "purchase_recommendation", len(nbp), bad_ids=bad["po_id"].tolist())
    lau = sku.set_index("sku_id")
    created = po["created_at"].astype(str).str[:10]
    ld = po["sku_id"].astype(str).map(lau["launch_date"])
    dd = po["sku_id"].astype(str).map(lau["discontinue_date"])
    inactive = (ld > created) | (dd.notna() & (dd <= created))
    bad = po[(po["status"] != "BLOCKED") & inactive.fillna(False)]
    ck.add(ANOMALY_CHECKS["DISCONTINUED_SKU_RECOMMENDED"], "anomaly_detector", "purchase_recommendation", len(po), bad_ids=bad["po_id"].tolist(),
           note="orderable recommendation whose SKU is discontinued / not launched on the recommendation date")
    neg_lt = lt[(lt["lead_time_days"] < 0) | (_str(lt["receipt_date"]) < _str(lt["order_date"]))]
    ck.add(ANOMALY_CHECKS["NEGATIVE_LEAD_TIME"], "anomaly_detector", "lead_time_observation", len(lt), bad_ids=neg_lt["lt_obs_id"].tolist())
    leak = fc[fc["training_cutoff_date"].astype(str) >= fc["period_start"].astype(str)]
    ck.add(ANOMALY_CHECKS["FORECAST_LEAKAGE"], "anomaly_detector", "forecast", len(fc), bad_ids=leak["forecast_id"].tolist(),
           note="max(sales date used) must be < forecast period start")

    non_anom = [r for r in ck.results if r["category"] != "anomaly_detector"]
    anom = [r for r in ck.results if r["category"] == "anomaly_detector"]
    return {
        "checks": ck.results, "flagged": ck.flagged,
        "summary": {
            "n_checks": len(ck.results),
            "structural_checks": len(non_anom),
            "structural_violations": int(sum(r["violations"] for r in non_anom)),
            "failed_structural_checks": [r["check"] for r in non_anom if not r["passed"]],
            "anomaly_detector_violations": {r["check"]: r["violations"] for r in anom},
        },
    }


def _position_volume(tables: dict, aux: dict) -> pd.Series:
    """Volume occupied per store by the inventory position (on_hand+on_order+in_transit) on the last history day."""
    inv = tables["inventory_snapshot"]
    last = aux["end"]
    m = np.asarray(inv["date"]).astype(str) == last
    sub = inv[m]
    vol = tables["sku"].set_index("sku_id")["volume_per_unit"]
    v = pd.Series(np.asarray(sub["sku_id"]).astype(str)).map(vol).to_numpy()
    w = (sub["on_hand"].to_numpy() + sub["on_order"].to_numpy() + sub["in_transit"].to_numpy()) * v
    return pd.Series(w, index=np.asarray(sub["store_id"]).astype(str)).groupby(level=0).sum()


def score_detectors(report: dict, ground_truth: pd.DataFrame) -> dict:
    """Precision / recall of each rule-based detector against the separate ground truth file."""
    out = {}
    for issue, check in ANOMALY_CHECKS.items():
        truth = set(ground_truth[ground_truth["issue_type"] == issue]["entity_id"].astype(str))
        found = report["flagged"].get(check, set())
        tp = len(truth & found)
        fp = len(found - truth)
        fn = len(truth - found)
        out[issue] = {"injected": len(truth), "detected": len(found), "true_positives": tp, "false_positives": fp, "false_negatives": fn,
                      "precision": (tp / len(found)) if found else (1.0 if not truth else 0.0),
                      "recall": (tp / len(truth)) if truth else 1.0}
    return out
