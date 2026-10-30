"""Deterministic synthetic retail data generator (masters first, then events).

Pipeline inside `generate()`:
  Supplier -> Store -> SKU -> SupplierSKU -> StoreSKU (assortment matrix)
  -> latent demand (intermittent + seasonal + promo + launch ramp)
  -> day-by-day inventory simulation under a *noisy planner* policy with stochastic supplier lead times
  -> SalesHistory / InventorySnapshot / LeadTimeObservation derived from the simulation (never independent).
Stockouts are recorded separately from zero demand; latent (true) demand lives only in the hidden
`censored_demand` ground-truth frame.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import ids
from .util import rng_for

# name, price_lo, price_hi, margin, volume/unit, pack options, seasonal amplitude, peak day-of-year, popularity shift
CATEGORIES = [
    ("Grocery", 1, 12, 0.30, 0.8, [6, 12, 24], 0.10, 355, 0.35),
    ("Beverages", 1, 8, 0.35, 1.2, [6, 12, 24], 0.25, 200, 0.35),
    ("Household", 3, 30, 0.35, 2.0, [1, 4, 6], 0.05, 90, 0.0),
    ("PersonalCare", 2, 25, 0.45, 0.6, [6, 12], 0.05, 1, 0.0),
    ("Electronics", 15, 400, 0.20, 1.5, [1, 2, 5], 0.35, 330, -0.8),
    ("Apparel", 10, 120, 0.50, 1.0, [1, 3, 6], 0.30, 340, -0.4),
    ("Toys", 5, 80, 0.45, 1.5, [1, 3, 6], 0.60, 345, -0.5),
    ("Garden", 4, 150, 0.40, 3.0, [1, 2, 4], 0.55, 160, -0.5),
    ("WinterSeasonal", 5, 100, 0.45, 2.0, [1, 3, 6], 0.70, 5, -0.6),
    ("SummerSeasonal", 3, 60, 0.45, 1.8, [1, 3, 6], 0.70, 190, -0.6),
]
CATEGORY_NAMES = [c[0] for c in CATEGORIES]
WEEKLY = np.array([0.88, 0.85, 0.90, 0.97, 1.10, 1.28, 1.02])  # Monday..Sunday
WEEKLY = WEEKLY / WEEKLY.mean()
FORMAT_SIZE = {"HYPER": 1.6, "SUPER": 1.0, "EXPRESS": 0.5}
FORMAT_DENSITY = {"HYPER": 1.4, "SUPER": 1.0, "EXPRESS": 0.6}
REGIONS = ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]
COUNTRIES = ["US", "MX", "CN", "VN", "IN", "DE", "PL", "BR"]
BIG = 10 ** 6  # sentinel "never"
MAX_LT = 45
SHIP_RATIO = 0.4  # share of the lead time spent "on order" before the shipment leaves the supplier


def _cat(codes: np.ndarray, categories) -> pd.Categorical:
    return pd.Categorical.from_codes(np.asarray(codes, dtype=np.int64), categories=list(categories))


def generate(cfg: dict) -> dict:
    seed = int(cfg["seed"])
    D = int(cfg["n_days"])
    n_sku, n_store, n_sup = int(cfg["n_skus"]), int(cfg["n_stores"]), int(cfg["n_suppliers"])
    start = date.fromisoformat(cfg["start_date"])
    dates = [start + timedelta(days=i) for i in range(D)]
    date_str = np.array([d.isoformat() for d in dates], dtype=object)
    dow = np.array([d.weekday() for d in dates])
    doy = np.array([d.timetuple().tm_yday for d in dates])
    sku_ids = [ids.sku_id(i + 1) for i in range(n_sku)]
    store_ids = [ids.store_id(i + 1) for i in range(n_store)]
    sup_ids = [ids.supplier_id(i + 1) for i in range(n_sup)]

    # ------------------------------------------------------------------ suppliers
    r = rng_for(seed, "supplier")
    reliability = np.round(r.uniform(0.72, 0.99, n_sup), 3)
    base_lt = np.clip(np.round(r.lognormal(np.log(8), 0.45, n_sup), 1), 2, 30)
    lt_cv = np.round(r.uniform(0.12, 0.45, n_sup) * (1.6 - reliability), 3)
    delay_prob = np.round((1 - reliability) * 0.5, 4)
    supplier = pd.DataFrame({
        "supplier_id": sup_ids,
        "name": [f"Supplier {i + 1:03d}" for i in range(n_sup)],
        "country": r.choice(COUNTRIES, n_sup),
        "reliability_score": reliability,
        "delay_probability": delay_prob,
        "status": "ACTIVE",
        "onboarded_date": [(start - timedelta(days=int(x))).isoformat() for x in r.integers(300, 3000, n_sup)],
    })

    # ------------------------------------------------------------------ stores
    r = rng_for(seed, "store")
    fmt = r.choice(["HYPER", "SUPER", "EXPRESS"], n_store, p=[0.2, 0.5, 0.3])
    store = pd.DataFrame({
        "store_id": store_ids,
        "name": [f"Store {i + 1:03d}" for i in range(n_store)],
        "region": r.choice(REGIONS, n_store),
        "format": fmt,
        "capacity_units": 0,  # calibrated after the simulation (see below)
        "open_date": [(start - timedelta(days=int(x))).isoformat() for x in r.integers(200, 3000, n_store)],
        "status": "ACTIVE",
    })

    # ------------------------------------------------------------------ SKUs
    r = rng_for(seed, "sku")
    cat_idx = r.integers(0, len(CATEGORIES), n_sku)
    perm = r.permutation(n_sku)
    n_planned = max(1, round(0.02 * n_sku))
    n_launch = max(3, round(0.12 * n_sku))
    n_day0 = max(1, round(0.01 * n_sku))
    n_disc = max(2, round(0.03 * n_sku))
    n_lapse = max(1, round(0.015 * n_sku))
    kind = np.array(["legacy"] * n_sku, dtype=object)
    pos = 0
    for name, n in (("planned", n_planned), ("launch", n_launch), ("day0", n_day0), ("disc", n_disc), ("lapse", n_lapse)):
        kind[perm[pos:pos + n]] = name
        pos += n
    launch_day = np.zeros(n_sku, dtype=np.int64)
    disc_day = np.full(n_sku, BIG, dtype=np.int64)
    lapse_day = np.full(n_sku, BIG, dtype=np.int64)
    switch_day = np.full(n_sku, BIG, dtype=np.int64)
    for i in range(n_sku):
        k = kind[i]
        if k in ("legacy", "disc", "lapse"):
            launch_day[i] = -int(r.integers(30, 1000))
        elif k == "launch":
            launch_day[i] = int(r.uniform(0.08, 0.75) * D)
        elif k == "day0":
            launch_day[i] = 0
        else:  # planned: launches after the as-of date
            launch_day[i] = D + int(r.integers(14, 150))
        if k == "disc":
            disc_day[i] = max(int(r.uniform(0.35, 0.85) * D), 10)
        if k == "lapse":
            lapse_day[i] = int(r.uniform(0.5, 0.8) * D)
    legacy_ok = np.nonzero(kind == "legacy")[0]
    n_switch = min(len(legacy_ok), max(2, round(0.08 * n_sku)))
    switch_set = r.choice(legacy_ok, n_switch, replace=False) if n_switch else np.array([], dtype=int)
    for i in switch_set:
        switch_day[i] = int(r.uniform(0.35, 0.65) * D)

    price = np.zeros(n_sku)
    cost = np.zeros(n_sku)
    vol = np.zeros(n_sku)
    for i in range(n_sku):
        _, lo, hi, margin, v, _, _, _, _ = CATEGORIES[cat_idx[i]]
        p = float(np.exp(r.uniform(np.log(lo), np.log(hi))))
        price[i] = round(p, 2)
        cost[i] = round(p * (1 - margin * r.uniform(0.7, 1.2)), 2)
        vol[i] = round(v * r.uniform(0.7, 1.3), 2)
    status = np.where(launch_day >= D, "PLANNED", np.where(disc_day < D, "DISCONTINUED", "ACTIVE"))
    sku = pd.DataFrame({
        "sku_id": sku_ids,
        "name": [f"{CATEGORY_NAMES[cat_idx[i]]} item {i + 1:06d}" for i in range(n_sku)],
        "category": [CATEGORY_NAMES[c] for c in cat_idx],
        "subcategory": [f"{CATEGORY_NAMES[cat_idx[i]]}-{int(x)}" for i, x in enumerate(r.integers(1, 6, n_sku))],
        "unit_cost": cost,
        "unit_price": price,
        "volume_per_unit": vol,
        "launch_date": [(start + timedelta(days=int(d))).isoformat() for d in launch_day],
        "discontinue_date": [(start + timedelta(days=int(d))).isoformat() if d < BIG else None for d in disc_day],
        "status": status,
    })

    # ------------------------------------------------------------------ SupplierSKU (bridge, effective dated)
    r = rng_for(seed, "supplier_sku")
    SUP = np.zeros((n_sku, 2), dtype=np.int64)
    PACK = np.zeros((n_sku, 2), dtype=np.int64)
    MOQ = np.zeros((n_sku, 2), dtype=np.int64)
    MEAN = np.zeros((n_sku, 2))
    SD = np.zeros((n_sku, 2))
    rows = []

    def make_terms(i, s):
        pack = int(r.choice(CATEGORIES[cat_idx[i]][5]))
        moq = pack * int(r.choice([1, 1, 2, 4], p=[0.4, 0.2, 0.25, 0.15]))
        m = round(float(base_lt[s] * r.uniform(0.85, 1.15)), 1)
        sd = round(max(0.3, m * float(lt_cv[s]) * r.uniform(0.8, 1.2)), 2)
        return pack, moq, m, sd

    for i in range(n_sku):
        p = int(r.integers(0, n_sup))
        pack, moq, m, sd = make_terms(i, p)
        eff_from = min(start, start + timedelta(days=int(launch_day[i]) - 14))
        eff_to = None
        if lapse_day[i] < BIG:
            eff_to = (start + timedelta(days=int(lapse_day[i]) - 1)).isoformat()
        if switch_day[i] < BIG:
            eff_to = (start + timedelta(days=int(switch_day[i]) - 1)).isoformat()
        c1 = round(float(cost[i]) * float(r.uniform(0.97, 1.03)), 2)
        rows.append((sup_ids[p], sku_ids[i], eff_from.isoformat(), eff_to, pack, moq, c1, m, sd, 1))
        SUP[i, :], PACK[i, :], MOQ[i, :], MEAN[i, :], SD[i, :] = p, pack, moq, m, sd
        if switch_day[i] < BIG:
            q = int(r.choice([x for x in range(n_sup) if x != p])) if n_sup > 1 else p
            pack2, moq2, m2, sd2 = make_terms(i, q)
            c2 = round(float(cost[i]) * float(r.uniform(0.95, 1.05)), 2)
            rows.append((sup_ids[q], sku_ids[i], (start + timedelta(days=int(switch_day[i]))).isoformat(), None, pack2, moq2, c2, m2, sd2, 1))
            SUP[i, 1], PACK[i, 1], MOQ[i, 1], MEAN[i, 1], SD[i, 1] = q, pack2, moq2, m2, sd2
        if r.random() < 0.15 and n_sup > 2:  # secondary (non-primary) supplier
            q = int(r.choice([x for x in range(n_sup) if x != p]))
            pack3, moq3, m3, sd3 = make_terms(i, q)
            rows.append((sup_ids[q], sku_ids[i], eff_from.isoformat(), None, pack3, moq3, round(float(cost[i]) * 1.05, 2), m3, sd3, 0))
    supplier_sku = pd.DataFrame(rows, columns=[
        "supplier_id", "sku_id", "effective_from", "effective_to", "pack_size", "moq", "unit_cost",
        "mean_lead_time_days", "lead_time_sd", "is_primary"])
    last_date = dates[-1].isoformat()
    supplier_sku["status"] = np.where(
        supplier_sku["effective_to"].notna() & (supplier_sku["effective_to"] < last_date), "CLOSED", "ACTIVE")
    supplier_sku = supplier_sku.sort_values(["sku_id", "effective_from", "supplier_id"]).reset_index(drop=True)

    # ------------------------------------------------------------------ assortment matrix (Store x SKU, N:M)
    r = rng_for(seed, "assortment")
    lo, hi = cfg["density"]
    chosen = []
    for s in range(n_store):
        frac = min(1.0, float(r.uniform(lo, hi)) * FORMAT_DENSITY[fmt[s]])
        n = min(n_sku, max(3, round(frac * n_sku)))
        chosen.append(set(int(x) for x in r.choice(n_sku, n, replace=False)))
    covered = set().union(*chosen)
    for k in range(n_sku):
        if k not in covered:
            chosen[int(r.integers(0, n_store))].add(k)
    pair_store, pair_sku = [], []
    for s in range(n_store):
        for k in sorted(chosen[s]):
            pair_store.append(s)
            pair_sku.append(k)
    pair_store = np.array(pair_store, dtype=np.int64)
    pair_sku = np.array(pair_sku, dtype=np.int64)
    P = len(pair_store)
    store_starts = np.searchsorted(pair_store, np.arange(n_store))
    start_day = np.maximum(launch_day[pair_sku], 0)
    ss_status = np.where(launch_day[pair_sku] >= D, "PLANNED", np.where(disc_day[pair_sku] < D, "DELISTED", "ACTIVE"))
    store_sku = pd.DataFrame({
        "store_id": _cat(pair_store, store_ids),
        "sku_id": _cat(pair_sku, sku_ids),
        "listed_from": [(start + timedelta(days=int(max(launch_day[k], 0)))).isoformat() if launch_day[k] >= 0 else start.isoformat()
                        for k in pair_sku],
        "listed_to": [(start + timedelta(days=int(disc_day[k]))).isoformat() if disc_day[k] < BIG else None for k in pair_sku],
        "status": ss_status,
    })

    # ------------------------------------------------------------------ latent demand
    r = rng_for(seed, "demand")
    cat_shift = np.array([c[8] for c in CATEGORIES])
    sku_pop = np.exp(r.normal(-0.95 + cat_shift[cat_idx], 1.0, n_sku))
    top = r.random(n_sku) < 0.04
    sku_pop[top] *= r.uniform(3, 6, int(top.sum()))  # long tail of blockbusters
    store_factor = np.array([FORMAT_SIZE[f] for f in fmt]) * r.lognormal(0, 0.3, n_store)
    pair_noise = r.lognormal(0, 0.25, P)
    base_rate = sku_pop[pair_sku] * store_factor[pair_store] * pair_noise  # expected units / day

    depth = np.zeros((n_sku, D), dtype=np.float32)  # promo calendar per SKU (chain-wide)
    n_windows = r.poisson(max(1.0, 3.5 * D / 365), n_sku)
    for i in range(n_sku):
        for _ in range(int(n_windows[i])):
            s0 = int(r.integers(0, D))
            ln = int(r.integers(5, 15))
            d0 = float(r.choice([0.10, 0.15, 0.20, 0.25, 0.30, 0.40]))
            depth[i, s0:s0 + ln] = np.maximum(depth[i, s0:s0 + ln], d0)
    elasticity = r.uniform(1.2, 2.5, n_sku).astype(np.float32)
    promo_mult = np.power(1.0 - depth, -elasticity[:, None]).astype(np.float32)

    amp = np.array([c[6] for c in CATEGORIES])[:, None]
    peak = np.array([c[7] for c in CATEGORIES])[:, None]
    season_cat = 1.0 + amp * np.cos(2 * np.pi * (doy[None, :] - peak) / 365.0)
    calendar_cat = (season_cat * WEEKLY[dow][None, :]).astype(np.float32)

    day = np.arange(D)
    lam = calendar_cat[cat_idx[pair_sku]] * base_rate.astype(np.float32)[:, None]
    lam *= promo_mult[pair_sku]
    is_launch = np.isin(kind[pair_sku], ["launch", "day0"])
    ds = day[None, :] - start_day[:, None]
    ramp = np.clip(0.35 + 0.65 * ds / 28.0, 0.35, 1.0).astype(np.float32)
    lam *= np.where(is_launch[:, None], ramp, np.float32(1.0))
    del ramp, ds
    k_over = 2.5  # gamma-Poisson over-dispersion
    lam *= (r.standard_gamma(k_over, size=lam.shape, dtype=np.float32) / np.float32(k_over))
    demand = r.poisson(lam).astype(np.int32)
    del lam
    active = (day[None, :] >= start_day[:, None]) & (day[None, :] < disc_day[pair_sku][:, None])
    demand *= active

    # ------------------------------------------------------------------ planner policy parameters (history generator)
    r = rng_for(seed, "planner")
    rate_est = base_rate * r.lognormal(0.2, 0.3, P)  # planner forecasts the *base* rate: misses seasonality/promos
    z = r.choice([1.0, 1.65, 2.05], P, p=[0.25, 0.45, 0.30])
    review = 7
    offset = np.arange(P) % review
    ROP = np.zeros((P, 2))
    SS = np.zeros((P, 2))
    for j in range(2):
        L = MEAN[pair_sku, j]
        sdl = SD[pair_sku, j]
        var_d = rate_est * (1 + rate_est / 2.5)
        ROP[:, j] = rate_est * L + z * np.sqrt(L * var_d + (rate_est * sdl) ** 2)
        SS[:, j] = ROP[:, j] + rate_est * review  # order-up-to level
    PACKp, MOQp, MEANp, SDp, SUPp = PACK[pair_sku], MOQ[pair_sku], MEAN[pair_sku], SD[pair_sku], SUP[pair_sku]
    seed_stock = np.ceil(base_rate * (MEANp[:, 0] + 7) * r.uniform(0.6, 1.8, P) / PACKp[:, 0]) * PACKp[:, 0]
    seed_stock = np.maximum(seed_stock, PACKp[:, 0]).astype(np.int64)

    # ------------------------------------------------------------------ inventory simulation
    rl = rng_for(seed, "leadtime")
    W = D + MAX_LT + 3
    sched_arr = np.zeros((P, W), dtype=np.int32)
    sched_ship = np.zeros((P, W), dtype=np.int32)
    onhand = np.zeros(P, dtype=np.int64)
    on_order = np.zeros(P, dtype=np.int64)
    in_transit = np.zeros(P, dtype=np.int64)
    A_start = np.zeros((P, D), dtype=np.int32)
    A_rec = np.zeros((P, D), dtype=np.int32)
    A_end = np.zeros((P, D), dtype=np.int32)
    A_oo = np.zeros((P, D), dtype=np.int32)
    A_it = np.zeros((P, D), dtype=np.int32)
    A_sold = np.zeros((P, D), dtype=np.int32)
    A_so = np.zeros((P, D), dtype=bool)
    allowed_until = np.minimum(lapse_day[pair_sku], disc_day[pair_sku] - (MAX_LT + 2))
    sw = switch_day[pair_sku]
    orders = []
    for t in range(D):
        starting = start_day == t
        onhand[starting] = seed_stock[starting]
        act = active[:, t]
        rec = sched_arr[:, t].astype(np.int64)
        shp = sched_ship[:, t].astype(np.int64)
        A_start[:, t] = onhand
        open_ = onhand + rec
        dem = demand[:, t].astype(np.int64)
        sold = np.minimum(dem, open_)
        A_so[:, t] = act & ((open_ == 0) | (dem > open_))
        onhand = open_ - sold
        on_order -= shp
        in_transit += shp - rec
        due = act & (((t + offset) % review) == 0) & (t < allowed_until)
        idx = np.nonzero(due)[0]
        if idx.size:
            j = (t >= sw[idx]).astype(np.int64)
            ip = onhand[idx] + on_order[idx] + in_transit[idx]
            m = ip <= ROP[idx, j]
            idx, j, ip = idx[m], j[m], ip[m]
            if idx.size:
                pk = PACKp[idx, j]
                qty = np.ceil((SS[idx, j] - ip) / pk) * pk
                qty = np.maximum(qty, MOQp[idx, j]).astype(np.int64)
                mean, sd = MEANp[idx, j], SDp[idx, j]
                base = rl.gamma((mean / sd) ** 2, sd ** 2 / mean)
                sup = SUPp[idx, j]
                delayed = rl.random(idx.size) < delay_prob[sup]
                extra = rl.integers(3, 13, idx.size) * delayed
                lt = np.minimum(np.clip(np.rint(base), 1, 38).astype(np.int64) + extra, MAX_LT)
                sched_arr[idx, t + lt] += qty.astype(np.int32)
                off = np.floor(SHIP_RATIO * lt).astype(np.int64)
                later = off > 0
                sched_ship[idx[later], t + off[later]] += qty[later].astype(np.int32)
                on_order[idx[later]] += qty[later]
                in_transit[idx[~later]] += qty[~later]
                orders.append((idx, np.full(idx.size, t), lt, qty, sup, mean, sd))
        A_rec[:, t] = rec
        A_sold[:, t] = sold
        A_end[:, t] = onhand
        A_oo[:, t] = on_order
        A_it[:, t] = in_transit
    del sched_arr, sched_ship

    # ------------------------------------------------------------------ store capacity (calibrated from simulated utilisation)
    r = rng_for(seed, "capacity")
    pos_vol = (A_end.astype(np.float32) + A_oo + A_it) * vol[pair_sku].astype(np.float32)[:, None]
    util = np.add.reduceat(pos_vol, store_starts, axis=0)
    p90 = np.percentile(util, 90, axis=1)
    store["capacity_units"] = np.ceil(p90 * r.uniform(1.08, 1.30, n_store)).astype(np.int64)
    del pos_vol, util

    # ------------------------------------------------------------------ event tables
    pi, di = np.nonzero(active)
    st_cat = _cat(pair_store[pi], store_ids)
    sk_cat = _cat(pair_sku[pi], sku_ids)
    dt_cat = _cat(di, date_str)
    dep = depth[pair_sku[pi], di].astype(np.float64)
    px = np.round(price[pair_sku[pi]] * (1.0 - dep), 2)
    units = A_sold[pi, di]
    so_flag = A_so[pi, di].astype(np.int8)
    sales = pd.DataFrame({
        "store_id": st_cat, "sku_id": sk_cat, "date": dt_cat,
        "units_sold": units, "on_promo": (dep > 0).astype(np.int8), "promo_depth": np.round(dep, 2),
        "price": px, "net_revenue": np.round(units * px, 2), "stockout_flag": so_flag,
    })
    inventory = pd.DataFrame({
        "store_id": st_cat, "sku_id": sk_cat, "date": dt_cat,
        "on_hand_start": A_start[pi, di], "receipts": A_rec[pi, di], "on_hand": A_end[pi, di],
        "on_order": A_oo[pi, di], "in_transit": A_it[pi, di], "stockout_flag": so_flag,
    })
    dem_pd = demand[pi, di]
    lost = dem_pd - units
    m = lost > 0
    censored = pd.DataFrame({
        "sale_id": ids.sale_ids(np.asarray(st_cat[m]), np.asarray(sk_cat[m]), np.asarray(dt_cat[m])),
        "store_id": st_cat[m], "sku_id": sk_cat[m], "date": dt_cat[m],
        "true_demand": dem_pd[m], "units_sold": units[m], "lost_units": lost[m],
    })

    # lead-time observations (one per delivered purchase order line)
    if orders:
        o_pair = np.concatenate([o[0] for o in orders])
        o_day = np.concatenate([o[1] for o in orders])
        o_lt = np.concatenate([o[2] for o in orders])
        o_qty = np.concatenate([o[3] for o in orders])
        o_sup = np.concatenate([o[4] for o in orders])
        o_mean = np.concatenate([o[5] for o in orders])
        o_sd = np.concatenate([o[6] for o in orders])
    else:
        o_pair = o_day = o_lt = o_qty = o_sup = np.zeros(0, dtype=np.int64)
        o_mean = o_sd = np.zeros(0)
    arrived = (o_day + o_lt) < D
    o_pair, o_day, o_lt, o_qty, o_sup, o_mean, o_sd = (a[arrived] for a in (o_pair, o_day, o_lt, o_qty, o_sup, o_mean, o_sd))
    n_lt = len(o_pair)
    lt_obs = pd.DataFrame({
        "lt_obs_id": [ids.lt_obs_id(i + 1) for i in range(n_lt)],
        "supplier_id": _cat(o_sup, sup_ids),
        "sku_id": _cat(pair_sku[o_pair], sku_ids),
        "store_id": _cat(pair_store[o_pair], store_ids),
        "order_date": _cat(o_day, date_str),
        "receipt_date": _cat(o_day + o_lt, date_str),
        "lead_time_days": o_lt.astype(np.int64),
        "units_received": o_qty.astype(np.int64),
        "delay_flag": (o_lt > np.ceil(o_mean + 2 * o_sd)).astype(np.int8),
        "source": "RECEIPT",
    })

    # lifecycle events (never overwrite history)
    ev = []
    for i in range(n_sku):
        ld = (start + timedelta(days=int(launch_day[i]))).isoformat()
        if launch_day[i] >= D:
            ev.append(("SKU", sku_ids[i], None, "PLANNED", start.isoformat(), "SKU_CREATED"))
        elif launch_day[i] > 0:
            ev.append(("SKU", sku_ids[i], None, "PLANNED", start.isoformat(), "SKU_CREATED"))
            ev.append(("SKU", sku_ids[i], "PLANNED", "ACTIVE", ld, "LAUNCH"))
        else:
            ev.append(("SKU", sku_ids[i], None, "ACTIVE", ld if launch_day[i] < 0 else start.isoformat(), "SKU_CREATED"))
        if disc_day[i] < D:
            ev.append(("SKU", sku_ids[i], "ACTIVE", "DISCONTINUED", (start + timedelta(days=int(disc_day[i]))).isoformat(), "DISCONTINUED"))
    status_event = pd.DataFrame(ev, columns=["entity_type", "entity_id", "old_status", "new_status", "event_date", "reason"])
    status_event.insert(0, "event_id", [ids.event_id(i + 1) for i in range(len(status_event))])

    tables = {
        "supplier": supplier, "store": store, "sku": sku, "supplier_sku": supplier_sku, "store_sku": store_sku,
        "sales_history": sales, "inventory_snapshot": inventory, "lead_time_observation": lt_obs,
        "status_event": status_event,
    }
    act_mask = active
    tot_dem = float(demand[act_mask].sum())
    tot_sold = float(A_sold[act_mask].sum())
    truth = {
        "fill_rate": tot_sold / tot_dem if tot_dem else 1.0,
        "stockout_day_rate": float(A_so[act_mask].mean()) if act_mask.any() else 0.0,
        "lost_units": tot_dem - tot_sold,
        "avg_on_hand_units": float(A_end[act_mask].mean()) if act_mask.any() else 0.0,
        "avg_on_hand_value": float((A_end.astype(np.float64) * cost[pair_sku][:, None])[act_mask].mean()) if act_mask.any() else 0.0,
        "n_pairs": int(P), "n_sales_rows": int(len(sales)),
    }
    aux = {
        "start": start.isoformat(), "end": last_date, "n_days": D, "dates": date_str,
        "store_ids": store_ids, "sku_ids": sku_ids, "supplier_ids": sup_ids,
        "sku_kind": kind, "categories": CATEGORY_NAMES,
    }
    return {"tables": tables, "censored_demand": censored, "truth": truth, "aux": aux}
