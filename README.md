# SKU-location demand forecasting & replenishment (YottaFlex.ai Round 2 - 72h challenge)

A fully **synthetic**, **seeded**, **reproducible** retail data generator plus a forecasting and replenishment decision engine.
It generates 10+ linked tables (2,000 SKUs x 100 stores x 365 days at full scale), forecasts demand on stockout-censored data with a
strict temporal holdout, and recommends purchase orders that respect lead time, safety stock, pack size, MOQ and store capacity -
with exceptions, lineage and labelled anomalies.

```
generate masters -> simulate demand + inventory + supplier deliveries -> forecast (temporal holdout)
   -> reorder policy (SS / ROP / order-up-to) -> purchase recommendations (pack / MOQ / capacity / exceptions)
   -> validate CLEAN baseline (0 violations) -> inject 5 labelled anomalies -> detect them -> export + checksums
```

## Quick start (fresh clone)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                          # numpy, pandas, pyyaml (pytest optional)
python -m src.pipeline --scale starter --seed 20261022 --out data/starter   # ~2 s
python tests/run_all.py                                  # or: pytest -q
python -m src.reproduce --scale starter                  # runs twice, compares row counts + SHA-256
```

Full volume (2,000 SKUs x 100 stores x 365 days, ~5.2M sales rows; needs ~3 GB RAM, a few minutes):

```bash
python -m src.pipeline --scale full --seed 20261022 --out data/full
python -m src.reproduce --scale full                     # reproducibility evidence at full scale
```

Presets live in `config/config.yaml` (`tiny`, `starter`, `small`, `full`) - **the same generator code** runs for all of them; only scale
parameters differ. Fixed seed: **20261022** (every stage draws from its own named, crc32-keyed RNG stream, so results do not depend on
process, ordering or hash randomisation).

Make targets: `make generate | generate-full | test | reproduce | zip`.

## What you get (`data/<scale>/`)

| path | content |
|---|---|
| `tables/*.csv`, `json/*.json` | all 13 tables (10 core entities + `store_sku` assortment bridge + `status_event` history + `exception_log`) |
| `sql/schema.sql`, `sql/seed.sql` | DDL with PK/FK; INSERT seed (large tables: `\copy` / `.import` hint against the CSV) |
| `ground_truth/ground_truth.csv/json` | the labelled injected anomalies (never joined into inputs) |
| `ground_truth/censored_demand.csv` | hidden latent demand on every stockout day (separate from inputs) |
| `metrics/*.json` | holdout accuracy, replenishment KPIs, data profile, edge-case coverage, detector precision/recall, all validation checks |
| `validation_summary.md` | baseline vs injected validation results |
| `reports/report.html` | self-contained run report |
| `run_manifest.json`, `source_manifest.json`, `checksums.json` | command, seed, parameters, row counts, provenance ("fully synthetic, no external data"), SHA-256 of every file |
| `../../docs/` | `data_dictionary.md` (type / required / allowed / unit / unique / rule for every field), `schema.sql`, `erd.md`, `source_manifest.json`, `reproducibility_<scale>.json` |

## Data model (see `docs/data_dictionary.md`, `docs/erd.md`)

Core entities: **SKU, Store, SalesHistory, InventorySnapshot, Supplier, SupplierSKU, LeadTimeObservation, Forecast, ReorderPolicy,
PurchaseRecommendation**. Additions: `store_sku` (assortment matrix = Store N:M SKU bridge), `status_event` (append-only history),
`exception_log` (operations worklist).

* PKs on every entity; composite FKs `(store_id, sku_id) -> store_sku`; `SupplierSKU` is the effective-dated N:M bridge.
* IDs: `SKU-000001`, `STORE-000001`, `SALE-<store-id>-<sku>-<date>`, `FC-<store-id>-<sku>-2026-01`, `PO-2026-000001` (all builders in `src/ids.py`,
  `PO` numbers assigned after sorting by store, sku). Supporting IDs: `SUP-`, `INV-`, `LT-`, `POL-`, `EVT-`, `EXC-`.
* History is never overwritten: SKU lifecycle, policy versions and recommendation approvals are rows in `status_event`; policies are
  effective-dated (v1 closed, v2 active). `purchase_recommendation.status` is the status **at creation**; later transitions are events.
* Derived values are computed from source rows: `on_hand = start + receipts - sold`, `receipts = sum(lead_time_observation.units)`,
  `lead_time = receipt - order`, `net_revenue = units x price`, forecast / policy / PO derive from tables only.

## Synthetic generation logic (`src/generate.py`)

1. Masters first: suppliers (reliability -> lead-time variability and delay probability), stores (format drives size / assortment breadth),
   SKUs (10 categories, long-tailed popularity, launches, discontinuations, planned future launches), `SupplierSKU` (pack size, MOQ,
   cost, lead-time mean / sd; mid-year supplier switches; secondary suppliers; supplier lapses), assortment matrix.
2. Latent demand per SKU-store-day = base rate x weekday x category seasonality x promo uplift (elasticity) x launch ramp, drawn
   gamma-Poisson (over-dispersed, strongly **intermittent**: most pair-days are zero).
3. A day-by-day inventory simulation under a deliberately imperfect planner (ignores seasonality / promos) with stochastic supplier lead times
   (gamma + delay events) produces receipts, on-order, in-transit and **stockouts**. Sales are *censored* by stock; latent demand is
   written only to `ground_truth/censored_demand.csv`. Stockouts (`stockout_flag`) are recorded separately from genuine zero-demand days.
4. Everything (sales, inventory, lead-time observations, store capacity) is derived from the simulation, not drawn independently.

Assumptions (also documented in code): history ends 2025-12-31, recommendations are created 2026-01-01 for forecast month 2026-01;
store capacity is calibrated from simulated peak utilisation (p90 x 1.08-1.30) so capacity sometimes binds; the full preset lists 5-12 % of SKUs
per store (breadth x format factor) to keep volume at ~5.2M rows instead of 73M.

## Forecasting (`src/forecasting.py`)

* **Censoring**: a day is censored when `stockout_flag=1` **or** (zero sales and nothing on the shelf). Censored days are excluded from training
  and from evaluation, so even mislabelled stockouts do not teach the model that demand is zero.
* Methods compared on the holdout: `naive_last28`, `seasonal_naive` (weekday means), `ses`, `sba` (Croston-SBA) and the segment-aware
  **hybrid** (SES for smooth/erratic, SBA for intermittent/lumpy, cohort blend for NEW SKUs) with promo-uplift, weekday and (when a full year
  is available) category-month seasonality - all estimated on training data only. The planned promo calendar is the only forward-looking input.
* **Temporal holdout**: train on days `[0, c)`, test on the last `holdout_days` (65 at full scale); metrics are reported on the holdout only:
  WAPE (daily and weekly), MAE, bias, MASE, overall and per segment (SMOOTH / ERRATIC / INTERMITTENT / LUMPY / NEW).
  `tests/test_holdout.py` proves no future leakage: overwriting every sale on/after the cutoff leaves the forecast unchanged.
* Honest result: demand is highly intermittent, so daily WAPE is dominated by noise; the hybrid beats the naive baseline by a few percent daily and
  more at weekly level (see `metrics/forecast_holdout_metrics.json`).

## Replenishment engine (`src/replenishment.py`)

```
SS  = z * sqrt(L * sigma_d^2 + d_hat^2 * sigma_L^2)      ROP = d_hat * L + SS       S = d_hat * (L + R) + SS
IP  = on_hand + on_order + in_transit                     order when IP <= ROP (boundary inclusive)
raw = max(0, S - IP) -> ceil to pack -> max(., MOQ) -> ceil to pack -> min(., capacity headroom floored to pack)
```
Lead time `L, sigma_L` come from valid observations (>= 5) else from the effective `SupplierSKU` planning values; negative/inconsistent
observations are excluded and logged. Service level by demand segment. Capacity is allocated per store to the most urgent SKUs first.

Exception paths with reason codes: `DISCONTINUED_SKU`, `NOT_YET_LAUNCHED`, `NO_VALID_SUPPLIER` (expired effective dates), `CAPACITY`,
`MOQ_CONFLICT`, `CAPACITY_REDUCED` (ordered but reduced), `INVALID_LEAD_TIME`, plus `LOW_CONFIDENCE` forecasts for new SKUs.
Each recommendation carries `forecast_id`, `policy_id`, `supplier_id`, raw vs recommended quantity - decisions are explainable and traceable.

## Labelled edge cases (`src/inject.py`, `src/validate.py`)

| issue_type | injected as | detector rule |
|---|---|---|
| `STOCKOUT_AS_ZERO_DEMAND` | censored zero-sales day relabelled `stockout_flag=0` | zero sales + empty shelf + flag 0 |
| `PACK_SIZE_VIOLATION` | quantity = valid qty - 1 | qty % pack_size != 0 |
| `DISCONTINUED_SKU_RECOMMENDED` | blocked recommendation flipped to DRAFT | SKU not ACTIVE at `created_at` and status != BLOCKED |
| `NEGATIVE_LEAD_TIME` | extra manual-entry delivery with receipt < order (0 units, no side effects) | receipt_date < order_date |
| `FORECAST_LEAKAGE` | `training_cutoff_date` inside the forecast period | cutoff >= period_start |

Flow: the **clean baseline is validated first (0 violations)**, then labelled rows are injected in place; the same validator then fires only
its five anomaly detectors, and `metrics/detector_scores.json` reports precision / recall per issue type against `ground_truth`
(1.0 / 1.0). Injections touch only their own rows (structural violations after injection: 0). No `is_anomaly` column exists in any input table.

## Validation (`src/validate.py`, 60+ checks)

PK uniqueness, FK integrity (incl. composite), required fields, enums, ID formats, date ordering, lifecycle (no sales before launch / after
discontinuation, legal status transitions, one active policy, no primary-supplier overlap), arithmetic reconciliation (inventory balance, opening =
previous closing, receipts = lead-time units, lead time = dates, revenue), duplicate checks, and business acceptance criteria
(MOQ, pack size, capacity per store, valid supplier, blocked qty = 0).

## Tests

`pytest -q` or `python tests/run_all.py`: ID conventions, integrity / reconciliation, SQL seed loads into SQLite with `PRAGMA foreign_key_check`,
pack / MOQ / capacity boundary cases (exact MOQ, negative headroom, MOQ not a pack multiple), censoring, ground-truth separation,
detector precision/recall, temporal holdout + no-leakage perturbation test, same-seed determinism and two-process checksum equality.

## Results at full scale (seed 20261022, evidence in `docs/full_scale_run/`)

| | |
|---|---|
| Volume | 2,000 SKUs, 100 stores, 365 days, 15,401 store-SKU pairs, **5,160,733** sales rows and inventory snapshots, 196,723 delivery observations |
| Holdout (last 65 days, in-stock days) | hybrid daily WAPE 0.957 vs naive-28 0.986 (**-2.9 %**); weekly WAPE 0.459 vs 0.484 (**-5.2 %**) |
| History service (simulated) | fill rate 90.6 %, stockout days 5.7 %, 318,960 lost units (latent demand kept in ground truth only) |
| Recommendations (2026-01-01) | 3,020 evaluated: 1,924 orders drafted, 1,096 blocked (DISCONTINUED_SKU 498, NOT_YET_LAUNCHED 315, NO_VALID_SUPPLIER 235, CAPACITY 47, MOQ_CONFLICT 1), 6 capacity-reduced, 648 orders exactly at MOQ |
| Validation | clean baseline: **0** violations; after injecting 500 labelled anomalies: 0 structural violations, every detector precision = recall = 1.00 |
| Reproducibility | two independent runs: identical row counts and SHA-256 for every file (`docs/reproducibility_*.json`) |

The full dataset (~1.1 GB) is not committed (`.gitignore`); regenerate it with the command above - `docs/full_scale_run/run_manifest.json` holds the parameters
and row counts, and `docs/reproducibility_full.json` the per-file checksums. A committed starter dataset lives in `data/starter/`.

## Repository layout

```
config/config.yaml   src/{ids,util,schema,generate,forecasting,replenishment,inject,validate,export,pipeline,reproduce}.py
tests/               docs/    scripts/package_zip.py    Makefile    requirements.txt
```

## Data provenance / lawful use

100 % synthetic. No external datasets, scraping or personal data (`source_manifest.json`).
# retail-replenishment-engine
## Limitations and next steps

**What works:** deterministic generator (seed 20261022, same code for all scales), 10 core entities + bridge/event tables,
temporal-holdout forecasting on stockout-censored data, reorder policy and purchase recommendations (pack size, MOQ, capacity),
five labelled anomalies with detectors, fail-closed validation gates, reproducibility checks.

**Known limitations**
- Daily demand is highly intermittent, so daily WAPE is dominated by noise; the hybrid beats naive baselines only modestly (see `metrics/forecast_holdout_metrics.json`).
- The starter preset covers 120 days (smaller than the 365-day full preset); full scale needs about 3 GB RAM and a few minutes.
- Capacity is calibrated from simulated peak utilisation, not real warehouse data. All data is synthetic.
- Single forecast month (2026-01) and one policy version change; no multi-period rolling re-planning.
- The full dataset (~1.1 GB) is not committed; regenerate it with the command above.
- `tests/run_all.py` cannot run pytest fixtures; use `python -m pytest -q`.

**Next steps:** rolling-origin evaluation, probabilistic forecasts, supplier-specific service levels, multi-echelon constraints.

## AI usage
See [`AI_USAGE.md`](AI_USAGE.md) and [`prompts/`](prompts/).

