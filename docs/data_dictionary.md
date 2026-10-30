# Data dictionary

Generated from `src/schema.py` (the same spec drives validation and the SQL DDL).
Types: text, int, real, date (ISO-8601), bool (0/1). IDs follow the conventions in `src/ids.py`.

## supplier

Supplier master. Reliability drives lead-time variability and delay probability.

- **Primary key:** `supplier_id`
- **Cardinality:** Supplier 1:N SupplierSKU
- **Lifecycle:** ACTIVE -> SUSPENDED (never deleted)

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `supplier_id` | text | Y | SUP-NNNNNN | - | Y | format ^SUP-\d{6}$ |
| `name` | text | Y | - | - | N | non-empty |
| `country` | text | Y | ISO-like code | - | N | non-empty |
| `reliability_score` | real | Y | 0.5-1.0 | ratio | N | 0.5<=x<=1 |
| `delay_probability` | real | Y | 0-0.5 | probability | N | derived: (1-reliability)*0.5 |
| `status` | text | Y | ACTIVE,SUSPENDED | - | N | enum |
| `onboarded_date` | date | Y | ISO date | - | N | <= first sale date |

## store

Store / warehouse master with a storage capacity constraint.

- **Primary key:** `store_id`
- **Cardinality:** Store N:M SKU via store_sku
- **Lifecycle:** ACTIVE -> CLOSED

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `store_id` | text | Y | STORE-NNNNNN | - | Y | format ^STORE-\d{6}$ |
| `name` | text | Y | - | - | N | non-empty |
| `region` | text | Y | NORTH,SOUTH,EAST,WEST,CENTRAL | - | N | enum |
| `format` | text | Y | HYPER,SUPER,EXPRESS | - | N | enum; drives size and assortment breadth |
| `capacity_units` | int | Y | >0 | volume units (same unit as sku.volume_per_unit) | N | calibrated from simulated peak utilisation |
| `open_date` | date | Y | ISO date | - | N | <= first sale date |
| `status` | text | Y | ACTIVE,CLOSED | - | N | enum |

## sku

Product master. Launch / discontinue dates create cold starts and lifecycle rules.

- **Primary key:** `sku_id`
- **Cardinality:** SKU N:M Store (store_sku), SKU N:M Supplier (supplier_sku)
- **Lifecycle:** PLANNED -> ACTIVE -> DISCONTINUED (terminal)

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `sku_id` | text | Y | SKU-NNNNNN | - | Y | format ^SKU-\d{6}$ |
| `name` | text | Y | - | - | N | non-empty |
| `category` | text | Y | 10 categories | - | N | enum |
| `subcategory` | text | Y | - | - | N | non-empty |
| `unit_cost` | real | Y | >0 | currency | N | unit_cost < unit_price |
| `unit_price` | real | Y | >0 | currency | N | list price |
| `volume_per_unit` | real | Y | >0 | volume units | N | >0 |
| `launch_date` | date | Y | ISO date | - | N | no sales before this date |
| `discontinue_date` | date | N | ISO date | - | N | > launch_date; no sales / recommendations on or after it |
| `status` | text | Y | PLANNED,ACTIVE,DISCONTINUED | - | N | status as of end of history; consistent with dates & status_event |

## supplier_sku

Bridge Supplier<->SKU (N:M), effective dated: pack size, MOQ, cost and lead-time distribution.

- **Primary key:** `supplier_id, sku_id, effective_from`
- **Foreign keys:** `(supplier_id)` -> `supplier(supplier_id)`; `(sku_id)` -> `sku(sku_id)`
- **Cardinality:** 1:N LeadTimeObservation (by supplier+sku)
- **Lifecycle:** versioned by effective dates; rows are closed, never edited

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `supplier_id` | text | Y | FK supplier | - | N | exists in supplier |
| `sku_id` | text | Y | FK sku | - | N | exists in sku |
| `effective_from` | date | Y | ISO date | - | N | PK part |
| `effective_to` | date | N | ISO date | - | N | NULL=open ended; effective_from < effective_to |
| `pack_size` | int | Y | >=1 | units/case | N | orders must be multiples |
| `moq` | int | Y | >=pack_size | units | N | minimum order quantity (multiple of pack_size) |
| `unit_cost` | real | Y | >0 | currency | N | >0 |
| `mean_lead_time_days` | real | Y | >0 | days | N | planning mean |
| `lead_time_sd` | real | Y | >0 | days | N | planning std-dev |
| `is_primary` | bool | Y | 0,1 | - | N | exactly one primary per SKU at any date |
| `status` | text | Y | ACTIVE,CLOSED | - | N | CLOSED when effective_to < end of history |

## store_sku

Assortment matrix: which SKU each store lists (Store N:M SKU bridge).

- **Primary key:** `store_id, sku_id`
- **Foreign keys:** `(store_id)` -> `store(store_id)`; `(sku_id)` -> `sku(sku_id)`
- **Cardinality:** parent of SalesHistory, InventorySnapshot, Forecast, ReorderPolicy, PurchaseRecommendation (1:N each)

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `store_id` | text | Y | FK store | - | N | exists in store |
| `sku_id` | text | Y | FK sku | - | N | exists in sku |
| `listed_from` | date | Y | ISO date | - | N | <= first sale |
| `listed_to` | date | N | ISO date | - | N | NULL=still listed |
| `status` | text | Y | PLANNED,ACTIVE,DELISTED | - | N | enum |

## sales_history

Daily sales per SKU-store (grain: store, sku, date). Stockouts are flagged separately from zero demand; latent demand is NOT in this table (see ground_truth/censored_demand.csv).

- **Primary key:** `sale_id`
- **Foreign keys:** `(store_id, sku_id)` -> `store_sku(store_id, sku_id)`
- **Grain:** one row per store-sku-day; row exists only while the SKU is alive in that store
- **Cardinality:** StoreSKU 1:N SalesHistory

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `sale_id` | text | Y | SALE-<store-id>-<sku>-<date> | - | Y | format ^SALE-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}-\d{2}$; = f(store,sku,date) |
| `store_id` | text | Y | FK store_sku | - | N | exists in store_sku |
| `sku_id` | text | Y | FK store_sku | - | N | exists in store_sku |
| `date` | date | Y | ISO date | - | N | launch<=date<discontinue |
| `units_sold` | int | Y | >=0 | units | N | <= on_hand_start+receipts |
| `on_promo` | bool | Y | 0,1 | - | N | 1 iff promo_depth>0 |
| `promo_depth` | real | Y | 0-0.5 | fraction | N | price cut |
| `price` | real | Y | >0 | currency | N | unit_price*(1-promo_depth) |
| `net_revenue` | real | Y | >=0 | currency | N | derived: units_sold*price |
| `stockout_flag` | bool | Y | 0,1 | - | N | 1 = shelf empty / demand exceeded stock (units_sold is CENSORED) |

## inventory_snapshot

Daily closing inventory balance per SKU-store; reconciles with sales and receipts.

- **Primary key:** `snapshot_id`
- **Foreign keys:** `(store_id, sku_id)` -> `store_sku(store_id, sku_id)`
- **Cardinality:** StoreSKU 1:N InventorySnapshot

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `snapshot_id` | text | Y | INV-<store-id>-<sku>-<date> | - | Y | format ^INV-...; = f(store,sku,date) |
| `store_id` | text | Y | FK store_sku | - | N | exists in store_sku |
| `sku_id` | text | Y | FK store_sku | - | N | exists in store_sku |
| `date` | date | Y | ISO date | - | N | same grain as sales_history |
| `on_hand_start` | int | Y | >=0 | units | N | = previous day's on_hand (opening stock on first day) |
| `receipts` | int | Y | >=0 | units | N | = sum(units_received) of lead_time_observation by receipt_date |
| `on_hand` | int | Y | >=0 | units | N | = on_hand_start + receipts - units_sold |
| `on_order` | int | Y | >=0 | units | N | ordered, not yet shipped |
| `in_transit` | int | Y | >=0 | units | N | shipped, not yet received |
| `stockout_flag` | bool | Y | 0,1 | - | N | identical to sales_history.stockout_flag |

## lead_time_observation

Observed deliveries (one per received order line). lead_time_days = receipt_date - order_date.

- **Primary key:** `lt_obs_id`
- **Foreign keys:** `(supplier_id)` -> `supplier(supplier_id)`; `(sku_id)` -> `sku(sku_id)`; `(store_id, sku_id)` -> `store_sku(store_id, sku_id)`
- **Cardinality:** SupplierSKU 1:N LeadTimeObservation

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `lt_obs_id` | text | Y | LT-NNNNNNN | - | Y | format ^LT-\d{7}$ |
| `supplier_id` | text | Y | FK supplier | - | N | exists |
| `sku_id` | text | Y | FK sku | - | N | exists |
| `store_id` | text | Y | FK store_sku | - | N | exists |
| `order_date` | date | Y | ISO date | - | N | <= receipt_date |
| `receipt_date` | date | Y | ISO date | - | N | >= order_date |
| `lead_time_days` | int | Y | >=0 | days | N | derived = receipt_date - order_date |
| `units_received` | int | Y | >=0 | units | N | reconciles with inventory receipts |
| `delay_flag` | bool | Y | 0,1 | - | N | 1 iff lead_time_days > ceil(mean+2*sd) of the supplier_sku terms |
| `source` | text | Y | RECEIPT,MANUAL_ENTRY | - | N | enum |

## status_event

Append-only lifecycle history for SKU, ReorderPolicy and PurchaseRecommendation (nothing is overwritten).

- **Primary key:** `event_id`
- **Cardinality:** polymorphic 1:N from SKU / ReorderPolicy / PurchaseRecommendation

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `event_id` | text | Y | EVT-NNNNNNN | - | Y | format ^EVT-\d{7}$ |
| `entity_type` | text | Y | SKU,REORDER_POLICY,PURCHASE_RECOMMENDATION | - | N | enum |
| `entity_id` | text | Y | - | - | N | id of the entity in its own table |
| `old_status` | text | N | - | - | N | NULL on creation |
| `new_status` | text | Y | - | - | N | legal transition from old_status |
| `event_date` | date | Y | ISO date | - | N | non-decreasing per entity |
| `reason` | text | Y | - | - | N | business reason |

## forecast

Month-ahead demand forecast per SKU-store (ID suffix = forecast month).

- **Primary key:** `forecast_id`
- **Foreign keys:** `(store_id, sku_id)` -> `store_sku(store_id, sku_id)`
- **Cardinality:** StoreSKU 1:N Forecast (one per month)

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `forecast_id` | text | Y | FC-<store-id>-<sku>-YYYY-MM | - | Y | format ^FC-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}$ |
| `store_id` | text | Y | FK store_sku | - | N | exists |
| `sku_id` | text | Y | FK store_sku | - | N | exists |
| `forecast_month` | text | Y | YYYY-MM | - | N | matches id suffix |
| `period_start` | date | Y | ISO date | - | N | first day of forecast_month |
| `period_end` | date | Y | ISO date | - | N | last day of forecast_month |
| `method` | text | Y | HYBRID_SES,HYBRID_SBA,COHORT_BLEND,COHORT_FALLBACK | - | N | enum |
| `segment` | text | Y | SMOOTH,ERRATIC,INTERMITTENT,LUMPY,NEW | - | N | Syntetos-Boylan class |
| `horizon_days` | int | Y | >0 | days | N | period_end-period_start+1 |
| `forecast_units` | real | Y | >=0 | units | N | sum over period |
| `daily_rate` | real | Y | >=0 | units/day | N | forecast_units/horizon_days |
| `lower` | real | Y | >=0 | units | N | <= forecast_units |
| `upper` | real | Y | >=0 | units | N | >= forecast_units |
| `training_cutoff_date` | date | Y | ISO date | - | N | MUST be < period_start (leakage guard) |
| `confidence` | text | Y | NORMAL,LOW_CONFIDENCE | - | N | enum |

## reorder_policy

Effective-dated reorder policy versions (old versions are closed, never overwritten).

- **Primary key:** `policy_id`
- **Foreign keys:** `(store_id, sku_id)` -> `store_sku(store_id, sku_id)`; `(supplier_id)` -> `supplier(supplier_id)`
- **Cardinality:** StoreSKU 1:N ReorderPolicy over time, exactly 1 active at a time
- **Lifecycle:** ACTIVE -> SUPERSEDED (status_event)

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `policy_id` | text | Y | POL-NNNNNNN | - | Y | format ^POL-\d{7}$ |
| `store_id` | text | Y | FK store_sku | - | N | exists |
| `sku_id` | text | Y | FK store_sku | - | N | exists |
| `supplier_id` | text | Y | FK supplier | - | N | exists |
| `version` | int | Y | >=1 | - | N | increments per store-sku |
| `service_level` | real | Y | 0.5-0.999 | probability | N | by demand segment |
| `z` | real | Y | >0 | - | N | inverse normal CDF of service_level |
| `review_period_days` | int | Y | >0 | days | N | R |
| `mean_lead_time_days` | real | Y | >0 | days | N | L (observed if >=5 valid obs, else planning) |
| `lead_time_sd` | real | Y | >=0 | days | N | sigma_L |
| `lead_time_source` | text | Y | OBSERVED,PLANNING | - | N | provenance of L |
| `daily_demand_est` | real | Y | >=0 | units/day | N | d_hat from forecast |
| `demand_sd` | real | Y | >=0 | units/day | N | sigma_d (in-stock days) |
| `safety_stock` | real | Y | >=0 | units | N | z*sqrt(L*sd^2+d^2*sdL^2) |
| `reorder_point` | real | Y | >=0 | units | N | d*L+SS |
| `order_up_to` | real | Y | >=0 | units | N | d*(L+R)+SS |
| `segment` | text | Y | SMOOTH,ERRATIC,INTERMITTENT,LUMPY,NEW | - | N | enum |
| `effective_from` | date | Y | ISO date | - | N | <effective_to |
| `effective_to` | date | N | ISO date | - | N | NULL = current |
| `computed_from_cutoff` | date | Y | ISO date | - | N | data cutoff used (< effective_from) |
| `status` | text | Y | ACTIVE,SUPERSEDED | - | N | one ACTIVE per store-sku |

## purchase_recommendation

Recommended purchase order with full lineage (forecast, policy, supplier) and reason code.

- **Primary key:** `po_id`
- **Foreign keys:** `(store_id, sku_id)` -> `store_sku(store_id, sku_id)`; `(supplier_id)` -> `supplier(supplier_id)`; `(forecast_id)` -> `forecast(forecast_id)`; `(policy_id)` -> `reorder_policy(policy_id)`
- **Cardinality:** Forecast 1:N PurchaseRecommendation (optional), ReorderPolicy 1:N PurchaseRecommendation (optional)
- **Lifecycle:** DRAFT -> APPROVED | CANCELLED (events); BLOCKED is terminal

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `po_id` | text | Y | PO-YYYY-NNNNNN | - | Y | format ^PO-\d{4}-\d{6}$; numbered after sorting by store,sku |
| `store_id` | text | Y | FK store_sku | - | N | exists |
| `sku_id` | text | Y | FK store_sku | - | N | exists |
| `supplier_id` | text | N | FK supplier | - | N | NULL only if SKU never had a supplier |
| `forecast_id` | text | N | FK forecast | - | N | NULL when blocked before forecasting |
| `policy_id` | text | N | FK reorder_policy | - | N | NULL when blocked before policy |
| `raw_qty` | real | Y | >=0 | units | N | max(0, order_up_to - inventory_position) |
| `recommended_qty` | int | Y | >=0 | units | N | multiple of pack_size, >= moq, within capacity (0 when BLOCKED) |
| `pack_size` | int | N | >=1 | units | N | from supplier_sku effective at created_at |
| `moq` | int | N | >=1 | units | N | from supplier_sku effective at created_at |
| `inventory_position` | int | N | >=0 | units | N | on_hand+on_order+in_transit at cutoff |
| `reorder_point` | real | N | >=0 | units | N | from policy |
| `order_up_to` | real | N | >=0 | units | N | from policy |
| `unit_cost` | real | N | >0 | currency | N | from supplier_sku |
| `order_value` | real | Y | >=0 | currency | N | recommended_qty*unit_cost |
| `expected_lead_time_days` | real | N | >0 | days | N | from policy |
| `reason_code` | text | Y | REORDER_POINT,CAPACITY_REDUCED,CAPACITY,MOQ_CONFLICT,DISCONTINUED_SKU,NOT_YET_LAUNCHED,NO_VALID_SUPPLIER,INVALID_LEAD_TIME | - | N | enum |
| `status` | text | Y | DRAFT,APPROVED,BLOCKED,CANCELLED | - | N | status AT CREATION; later transitions live in status_event |
| `confidence` | text | N | NORMAL,LOW_CONFIDENCE | - | N | from forecast |
| `created_at` | text | Y | ISO timestamp | - | N | date part is the as-of date |

## exception_log

Operations exception list derived from the recommendation run (blocked / reduced / low-confidence / invalid lead time).

- **Primary key:** `exception_id`
- **Cardinality:** derived output

| field | type | required | allowed values / format | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `exception_id` | text | Y | EXC-NNNNNN | - | Y | format |
| `exception_code` | text | Y | - | - | N | BLOCKED_RECOMMENDATION, REDUCED_RECOMMENDATION, LOW_CONFIDENCE_FORECAST, INVALID_LEAD_TIME_EXCLUDED |
| `entity_type` | text | Y | - | - | N | polymorphic |
| `entity_id` | text | Y | - | - | N | id of the entity |
| `store_id` | text | N | - | - | N | context |
| `sku_id` | text | N | - | - | N | context |
| `reason_code` | text | Y | - | - | N | reason |
| `detail` | text | Y | - | - | N | human readable |
| `severity` | text | Y | HIGH,MEDIUM,LOW | - | N | enum |
