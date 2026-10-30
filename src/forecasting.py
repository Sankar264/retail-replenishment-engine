"""Demand forecasting on censored data with a strict temporal holdout.

Key ideas
* Stockout days are CENSORED (unobserved demand), not zero demand: they are masked out of training.
  Censoring is detected from the data rules (flag OR zero sales with nothing on the shelf), so mislabelled
  stockouts (injected edge case 1) are still handled.
* Models: naive_last28, seasonal_naive (weekday means), SES, SBA (Croston) and a segment-aware HYBRID
  (SES for smooth/erratic, SBA for intermittent/lumpy, cohort fallback for new SKUs) with promo,
  weekday and category-seasonal adjustments estimated on training data only.
* Temporal holdout: train on days [0, c), test on [c, c+H). Nothing at or after the cutoff is used to fit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import ids
from .util import codes, day_index

ALPHA = 0.1
SEGMENTS = ["SMOOTH", "ERRATIC", "INTERMITTENT", "LUMPY", "NEW"]


@dataclass
class Mats:
    """Dense [pairs x days] views of the relational tables (the engine only ever reads tables)."""
    pairs: pd.DataFrame            # store_id, sku_id, store_idx, sku_idx, cat_idx, vol, supplier-free
    units: np.ndarray              # float32, units sold (0 where inactive)
    active: np.ndarray             # bool, pair listed/alive that day
    oh_end: np.ndarray             # int32 closing on-hand
    flag: np.ndarray               # bool, recorded stockout_flag
    depth: np.ndarray              # float32 promo depth
    pos: np.ndarray                # int32 inventory position at close (on_hand+on_order+in_transit)
    start: str
    n_days: int
    dow0: int
    n_cat: int

    @property
    def censored(self) -> np.ndarray:
        """Stockout censoring rule: recorded flag OR (nothing sold AND nothing left on the shelf)."""
        return self.active & (self.flag | ((self.units == 0) & (self.oh_end == 0)))

    @property
    def valid(self) -> np.ndarray:
        return self.active & ~self.censored


def build_mats(tables: dict, aux: dict) -> Mats:
    stores, skus = aux["store_ids"], aux["sku_ids"]
    D, start = aux["n_days"], aux["start"]
    ss = tables["store_sku"]
    s_idx = codes(ss["store_id"], stores)
    k_idx = codes(ss["sku_id"], skus)
    pair_key = s_idx * len(skus) + k_idx
    order = np.argsort(pair_key, kind="stable")
    assert np.all(order == np.arange(len(order))), "store_sku must be sorted by (store_id, sku_id)"
    P = len(ss)
    cat_names = sorted(set(tables["sku"]["category"]))
    cat_of_sku = codes(tables["sku"]["category"], cat_names)
    vol_of_sku = tables["sku"]["volume_per_unit"].to_numpy()

    def locate(df):
        s = codes(df["store_id"], stores)
        k = codes(df["sku_id"], skus)
        key = s * len(skus) + k
        p = np.searchsorted(pair_key, key)
        if len(p) and (p.max() >= P or np.any(pair_key[np.minimum(p, P - 1)] != key)):
            raise ValueError("orphan (store, sku) key found outside the assortment matrix")
        return p, day_index(df["date"], start)

    units = np.zeros((P, D), dtype=np.float32)
    active = np.zeros((P, D), dtype=bool)
    flag = np.zeros((P, D), dtype=bool)
    depth = np.zeros((P, D), dtype=np.float32)
    sh = tables["sales_history"]
    p, d = locate(sh)
    units[p, d] = sh["units_sold"].to_numpy()
    active[p, d] = True
    flag[p, d] = sh["stockout_flag"].to_numpy().astype(bool)
    depth[p, d] = sh["promo_depth"].to_numpy()
    inv = tables["inventory_snapshot"]
    p2, d2 = locate(inv)
    oh = np.zeros((P, D), dtype=np.int32)
    pos = np.zeros((P, D), dtype=np.int32)
    oh[p2, d2] = inv["on_hand"].to_numpy()
    pos[p2, d2] = (inv["on_hand"].to_numpy() + inv["on_order"].to_numpy() + inv["in_transit"].to_numpy())
    pairs = pd.DataFrame({
        "store_id": np.asarray(ss["store_id"]).astype(str), "sku_id": np.asarray(ss["sku_id"]).astype(str),
        "store_idx": s_idx, "sku_idx": k_idx, "cat_idx": cat_of_sku[k_idx], "vol": vol_of_sku[k_idx],
    })
    return Mats(pairs, units, active, oh, flag, depth, pos, start, D, date.fromisoformat(start).weekday(), len(cat_names))


# --------------------------------------------------------------------------- helpers
def _nanmean(x: np.ndarray, valid: np.ndarray, axis: int = 1) -> np.ndarray:
    n = valid.sum(axis)
    s = np.where(valid, x, 0.0).sum(axis)
    return np.where(n > 0, s / np.maximum(n, 1), np.nan)


def classify(units: np.ndarray, valid: np.ndarray, min_hist: int) -> np.ndarray:
    """Syntetos-Boylan demand classes from in-stock days; NEW when history is too short."""
    n_valid = valid.sum(1)
    nz = valid & (units > 0)
    n_nz = nz.sum(1)
    adi = np.where(n_nz > 0, n_valid / np.maximum(n_nz, 1), np.inf)
    mean_nz = np.where(n_nz > 0, np.where(nz, units, 0).sum(1) / np.maximum(n_nz, 1), 0.0)
    var_nz = np.where(n_nz > 1, np.where(nz, (units - mean_nz[:, None]) ** 2, 0).sum(1) / np.maximum(n_nz - 1, 1), 0.0)
    cv2 = np.where(mean_nz > 0, var_nz / np.maximum(mean_nz, 1e-9) ** 2, 0.0)
    seg = np.where(adi < 1.32, np.where(cv2 < 0.49, "SMOOTH", "ERRATIC"), np.where(cv2 < 0.49, "INTERMITTENT", "LUMPY"))
    return np.where(n_valid < min_hist, "NEW", seg).astype(object)


def _uplift(depth: np.ndarray, elas: np.ndarray) -> np.ndarray:
    return np.power(1.0 - depth, -elas)


def _fit_adjustments(m: Mats, c: int):
    """Promo elasticity, weekday profile and category-month seasonality - TRAINING DATA ONLY (days < c)."""
    units, valid, depth = m.units[:, :c], m.valid[:, :c], m.depth[:, :c]
    cat = m.pairs["cat_idx"].to_numpy()
    promo = valid & (depth > 0)
    base = valid & (depth == 0)
    n_b, n_p = base.sum(1), promo.sum(1)
    mean_b = np.where(n_b >= 20, np.where(base, units, 0).sum(1) / np.maximum(n_b, 1), np.nan)
    ok = (n_p >= 3) & ~np.isnan(mean_b) & (mean_b > 0)
    exp_units = np.where(ok, mean_b * n_p, 0.0)
    act_units = np.where(ok, np.where(promo, units, 0).sum(1), 0.0)
    mean_depth = np.where(ok, np.where(promo, depth, 0).sum(1) / np.maximum(n_p, 1), 0.0)
    elas = np.full(m.n_cat, 1.5)
    for k in range(m.n_cat):
        sel = ok & (cat == k)
        if sel.sum() >= 3 and exp_units[sel].sum() > 0 and act_units[sel].sum() > 0:
            ratio = act_units[sel].sum() / exp_units[sel].sum()
            md = mean_depth[sel].mean()
            if md > 0:
                elas[k] = float(np.clip(np.log(max(ratio, 1e-6)) / -np.log(1 - md), 0.0, 4.0))
    adj = units / _uplift(depth, elas[cat][:, None])
    # weekday profile per category
    dow = (m.dow0 + np.arange(c)) % 7
    wk = np.ones((m.n_cat, 7))
    for k in range(m.n_cat):
        sel = (cat == k)
        if not sel.any():
            continue
        vk, ak = valid[sel], adj[sel]
        means = np.array([ak[:, dow == w][vk[:, dow == w]].mean() if vk[:, dow == w].any() else np.nan for w in range(7)])
        overall = ak[vk].mean() if vk.any() else np.nan
        if overall and overall > 0 and not np.isnan(means).any():
            wk[k] = means / overall
            wk[k] /= wk[k].mean()
    # category-month seasonality from pair-normalised series
    level = _nanmean(adj, valid)
    y = np.where(valid & (level[:, None] > 0.05), adj / np.maximum(level[:, None], 1e-9), np.nan)
    dates = pd.to_datetime(m.start) + pd.to_timedelta(np.arange(c), unit="D")
    months = dates.month.to_numpy()
    seas = np.ones((m.n_cat, 13))
    for k in range(m.n_cat):
        sel = cat == k
        for mo in range(1, 13):
            cols = months == mo
            if cols.sum() >= 14 and sel.any():
                vals = y[sel][:, cols]
                vals = vals[~np.isnan(vals)]
                if vals.size > 30:
                    seas[k, mo] = float(np.clip(vals.mean(), 0.4, 3.0))
    # Seasonal indices are only trusted when the training window spans a full year (all 12 months observed);
    # otherwise de-seasonalising with partial coverage would bias the level (documented design choice).
    covered = sum(1 for mo in range(1, 13) if (months == mo).sum() >= 14)
    if covered < 12:
        seas[:] = 1.0
    return elas, wk, seas, months


def _ses(z: np.ndarray, valid: np.ndarray, init: np.ndarray) -> np.ndarray:
    level = init.copy()
    for t in range(z.shape[1]):
        v = valid[:, t]
        level[v] = ALPHA * z[v, t] + (1 - ALPHA) * level[v]
    return level


def _sba(z: np.ndarray, valid: np.ndarray) -> np.ndarray:
    P, c = z.shape
    nz = valid & (z > 0)
    n_nz = nz.sum(1)
    size = np.where(n_nz > 0, np.where(nz, z, 0).sum(1) / np.maximum(n_nz, 1), 0.0)
    interval = np.where(n_nz > 0, valid.sum(1) / np.maximum(n_nz, 1), 1e9)
    interval = np.maximum(interval, 1.0)
    q = np.ones(P)
    for t in range(c):
        v = valid[:, t]
        hit = v & (z[:, t] > 0)
        size[hit] = ALPHA * z[hit, t] + (1 - ALPHA) * size[hit]
        interval[hit] = ALPHA * q[hit] + (1 - ALPHA) * interval[hit]
        q[hit] = 1
        q[v & ~hit] += 1
    rate = np.where(n_nz > 0, size / interval * (1 - ALPHA / 2), 0.0)
    return rate


@dataclass
class FCResult:
    pred: dict                # method -> [P, H] daily forecasts
    segment: np.ndarray       # [P]
    method: np.ndarray        # [P] hybrid method label
    sigma_d: np.ndarray       # [P] std of daily in-stock demand (training)
    n_valid: np.ndarray
    horizon_dates: pd.DatetimeIndex


def forecast(m: Mats, c: int, H: int, min_hist: int, with_baselines: bool = True) -> FCResult:
    """Fit on days [0, c) and forecast days [c, c+H). Future promo calendar is a planned input; sales are never read."""
    P = m.units.shape[0]
    cat = m.pairs["cat_idx"].to_numpy()
    store = m.pairs["store_idx"].to_numpy()
    units_all, valid_all = m.units, m.valid
    u = units_all[:, :c].astype(np.float64)
    valid = valid_all[:, :c]
    depth = m.depth[:, :c]
    elas, wk, seas, months = _fit_adjustments(m, c)
    seg = classify(u, valid, min_hist)
    n_valid = valid.sum(1)
    dow_tr = (m.dow0 + np.arange(c)) % 7
    adj = u / _uplift(depth, elas[cat][:, None])
    z = adj / (wk[cat][:, dow_tr] * seas[cat][:, months])
    z = np.where(valid, z, 0.0)
    init = np.where(n_valid > 0, np.where(valid, z, 0).sum(1) / np.maximum(n_valid, 1), 0.0)
    ses_rate = _ses(z, valid, init)
    sba_rate = _sba(z, valid)

    # horizon calendar
    hdates = pd.to_datetime(m.start) + pd.to_timedelta(np.arange(c, c + H), unit="D")
    dow_h = (m.dow0 + np.arange(c, c + H)) % 7
    mon_h = hdates.month.to_numpy()
    depth_h = np.zeros((P, H), dtype=np.float32)
    avail = max(0, min(H, m.n_days - c))
    if avail:
        depth_h[:, :avail] = m.depth[:, c:c + avail]
    mult = wk[cat][:, dow_h] * seas[cat][:, mon_h] * _uplift(depth_h, elas[cat][:, None])

    # cohort fallback for new / short-history pairs: category x store mean level of mature pairs
    mature = (n_valid >= min_hist) & (init > 0)
    cat_mean = np.array([init[mature & (cat == k)].mean() if (mature & (cat == k)).any() else np.nan for k in range(m.n_cat)])
    overall = float(init[mature].mean()) if mature.any() else float(np.nanmean(init[init > 0])) if (init > 0).any() else 0.0
    cat_mean = np.where(np.isnan(cat_mean), overall, cat_mean)
    n_store = int(store.max()) + 1 if P else 0
    store_idx = np.ones(n_store)
    for s in range(n_store):
        sel = mature & (store == s)
        if sel.sum() >= 3:
            exp = cat_mean[cat[sel]].sum()
            store_idx[s] = float(np.clip(init[sel].sum() / exp, 0.3, 3.0)) if exp > 0 else 1.0
    fallback = cat_mean[cat] * store_idx[store]
    w = np.clip(n_valid / float(min_hist), 0, 1)
    new_rate = w * init + (1 - w) * fallback

    smooth = np.isin(seg, ["SMOOTH", "ERRATIC"])
    level = np.where(seg == "NEW", new_rate, np.where(smooth, ses_rate, sba_rate))
    label = np.where(seg == "NEW", np.where(n_valid >= 7, "COHORT_BLEND", "COHORT_FALLBACK"),
                     np.where(smooth, "HYBRID_SES", "HYBRID_SBA")).astype(object)
    pred = {"hybrid": np.maximum(level, 0)[:, None] * mult}
    if with_baselines:
        last = valid[:, max(0, c - 28):c]
        n28 = np.maximum(last.sum(1), 1)
        naive = np.where(last, u[:, max(0, c - 28):c], 0).sum(1) / n28
        pred["naive_last28"] = np.repeat(naive[:, None], H, axis=1)
        lo = max(0, c - 56)
        prof = np.zeros((P, 7))
        for wd in range(7):
            cols = np.nonzero(dow_tr[lo:] == wd)[0] + lo
            vv = valid[:, cols]
            prof[:, wd] = np.where(vv.sum(1) > 0, np.where(vv, u[:, cols], 0).sum(1) / np.maximum(vv.sum(1), 1), naive)
        pred["seasonal_naive"] = prof[:, dow_h]
        pred["ses"] = np.repeat(np.maximum(ses_rate, 0)[:, None], H, axis=1) * 1.0
        pred["sba"] = np.repeat(np.maximum(sba_rate, 0)[:, None], H, axis=1)
    # dispersion of in-stock daily demand over the last 90 valid days
    lo90 = max(0, c - 90)
    v90 = valid[:, lo90:c]
    mu90 = _nanmean(u[:, lo90:c], v90)
    var90 = np.where(v90.sum(1) > 1, np.where(v90, (u[:, lo90:c] - np.nan_to_num(mu90)[:, None]) ** 2, 0).sum(1) / np.maximum(v90.sum(1) - 1, 1), 0.0)
    sigma = np.sqrt(var90)
    sigma = np.where(seg == "NEW", np.maximum(sigma, np.sqrt(np.maximum(level, 0) * 1.5)), sigma)
    return FCResult(pred, seg, label, sigma, n_valid, hdates)


# --------------------------------------------------------------------------- evaluation
def _metrics(a: np.ndarray, f: np.ndarray, mask: np.ndarray, scale: np.ndarray | None = None) -> dict:
    if not mask.any():
        return {"n_obs": 0, "wape": None, "mae": None, "bias": None, "mase": None}
    err = np.where(mask, f - a, 0.0)
    tot = float(np.where(mask, a, 0).sum())
    n = int(mask.sum())
    out = {
        "n_obs": n,
        "wape": float(np.abs(err).sum() / tot) if tot > 0 else None,
        "mae": float(np.abs(err).sum() / n),
        "bias": float(err.sum() / tot) if tot > 0 else None,
        "mase": None,
    }
    if scale is not None:
        n_p = mask.sum(1)
        mae_p = np.abs(err).sum(1) / np.maximum(n_p, 1)
        ok = (n_p > 0) & (scale > 0)
        if ok.any():
            out["mase"] = float((mae_p[ok] / scale[ok]).mean())
    return out


def evaluate_holdout(m: Mats, holdout_days: int, min_hist: int) -> dict:
    c = m.n_days - holdout_days
    H = holdout_days
    fc = forecast(m, c, H, min_hist)
    actual = m.units[:, c:c + H].astype(np.float64)
    mask = m.valid[:, c:c + H]  # in-stock, non-censored test days
    # MASE scale: in-sample one-step naive MAE on consecutive valid training days
    tr, vtr = m.units[:, :c].astype(np.float64), m.valid[:, :c]
    both = vtr[:, 1:] & vtr[:, :-1]
    diff = np.where(both, np.abs(tr[:, 1:] - tr[:, :-1]), 0).sum(1) / np.maximum(both.sum(1), 1)
    seg = fc.segment
    # weekly buckets
    nw = H // 7
    def weekly(arr, msk):
        a = arr[:, :nw * 7].reshape(arr.shape[0], nw, 7)
        mk = msk[:, :nw * 7].reshape(msk.shape[0], nw, 7)
        return a, mk
    res = {"cutoff_day_index": int(c), "train_days": int(c), "test_days": int(H),
           "train_end_date": str(fc.horizon_dates[0].date() - timedelta(days=1)),
           "test_start_date": str(fc.horizon_dates[0].date()), "test_end_date": str(fc.horizon_dates[-1].date()),
           "metric_basis": "in-stock, non-flagged test days only (stockout-censored days excluded)",
           "methods": {}}
    a_w, mk_w = weekly(actual, mask)
    for name, f in fc.pred.items():
        entry = {"overall_daily": _metrics(actual, f, mask, diff), "by_segment": {}}
        f_w, _ = weekly(f, mask)
        wk_a = np.where(mk_w, a_w, 0).sum(2)
        wk_f = np.where(mk_w, f_w, 0).sum(2)
        wk_m = mk_w.sum(2) >= 4
        entry["overall_weekly"] = _metrics(wk_a, wk_f, wk_m)
        for sname in SEGMENTS:
            sel = seg == sname
            if sel.any():
                e = _metrics(actual[sel], f[sel], mask[sel], diff[sel])
                e["weekly_wape"] = _metrics(wk_a[sel], wk_f[sel], wk_m[sel])["wape"]
                e["n_pairs"] = int(sel.sum())
                entry["by_segment"][sname] = e
        res["methods"][name] = entry
    base = res["methods"]["naive_last28"]["overall_daily"]["wape"]
    hyb = res["methods"]["hybrid"]["overall_daily"]["wape"]
    res["hybrid_vs_naive_wape_improvement_pct"] = (None if not base or hyb is None else round(100 * (base - hyb) / base, 2))
    res["censored_test_days_excluded"] = int((m.active[:, c:c + H] & ~mask).sum())
    res["segment_counts"] = {s: int((seg == s).sum()) for s in SEGMENTS}
    return res


def build_forecast_table(m: Mats, tables: dict, aux: dict, cfg: dict) -> tuple[pd.DataFrame, FCResult]:
    """Month-ahead forecast (period = cfg['forecast_month']) for every pair whose SKU is ACTIVE at the as-of date."""
    H = int(cfg["forecast_horizon_days"])
    D = m.n_days
    fc = forecast(m, D, H, int(cfg["min_history_days"]), with_baselines=False)
    sku = tables["sku"]
    as_of = cfg["as_of_date"]
    launched = sku["launch_date"].to_numpy() <= as_of
    disc = sku["discontinue_date"].notna().to_numpy() & (sku["discontinue_date"].fillna("9999").to_numpy() <= as_of)
    sku_ok = launched & ~disc
    pr = m.pairs
    ok = sku_ok[pr["sku_idx"].to_numpy()]
    rows = np.nonzero(ok)[0]
    rate = fc.pred["hybrid"][rows].mean(1)
    total = fc.pred["hybrid"][rows].sum(1)
    sd_tot = fc.sigma_d[rows] * np.sqrt(H)
    ym = cfg["forecast_month"]
    first = date.fromisoformat(ym + "-01")
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    st, sk = pr["store_id"].to_numpy()[rows], pr["sku_id"].to_numpy()[rows]
    out = pd.DataFrame({
        "forecast_id": ids.forecast_ids(st, sk, ym),
        "store_id": st, "sku_id": sk,
        "forecast_month": ym, "period_start": first.isoformat(), "period_end": last.isoformat(),
        "method": fc.method[rows], "segment": fc.segment[rows], "horizon_days": H,
        "forecast_units": np.round(total, 2), "daily_rate": np.round(rate, 4),
        "lower": np.round(np.maximum(total - 1.645 * sd_tot, 0), 2), "upper": np.round(total + 1.645 * sd_tot, 2),
        "training_cutoff_date": aux["end"],
        "confidence": np.where(fc.segment[rows] == "NEW", "LOW_CONFIDENCE", "NORMAL"),
    })
    out["_row"] = rows
    return out, fc
