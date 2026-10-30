# Validation summary

Scale: `full` | seed: `20261022` | history: 2025-01-01 to 2025-12-31 (365 days)

## 1. Clean baseline (before anomaly injection)

- Structural checks: **225**, violations: **0**
- Anomaly detectors on the clean baseline (expected 0): {'detect.stockout_flagged_as_zero_demand': 0, 'detect.order_qty_not_multiple_of_pack_size': 0, 'detect.discontinued_sku_recommended': 0, 'detect.negative_lead_time': 0, 'detect.forecast_uses_future_sales': 0}

| category | checks | rows checked | violations | failed checks |
|---|---|---|---|---|
| business_rule | 4 | 5044 | 0 | 0 |
| date_order | 4 | 60797 | 0 | 0 |
| duplicate | 2 | 17608 | 0 | 0 |
| enum | 24 | 16084307 | 0 | 0 |
| foreign_key | 16 | 11028299 | 0 | 0 |
| id_format | 10 | 299217 | 0 | 0 |
| lifecycle | 6 | 10401331 | 0 | 0 |
| primary_key | 13 | 10632638 | 0 | 0 |
| range | 1 | 5160733 | 0 | 0 |
| reconciliation | 10 | 36517550 | 0 | 0 |
| required | 122 | 96068010 | 0 | 0 |
| schema | 13 | 10632638 | 0 | 0 |

## 2. After labelled anomaly injection

- Structural violations after injection (expected 0 - injections touch only their own rows): **0**
- Failed structural checks: none

| issue type | injected | detected | true pos. | false pos. | false neg. | precision | recall |
|---|---|---|---|---|---|---|---|
| STOCKOUT_AS_ZERO_DEMAND | 100 | 100 | 100 | 0 | 0 | 1.000 | 1.000 |
| PACK_SIZE_VIOLATION | 100 | 100 | 100 | 0 | 0 | 1.000 | 1.000 |
| DISCONTINUED_SKU_RECOMMENDED | 100 | 100 | 100 | 0 | 0 | 1.000 | 1.000 |
| NEGATIVE_LEAD_TIME | 100 | 100 | 100 | 0 | 0 | 1.000 | 1.000 |
| FORECAST_LEAKAGE | 100 | 100 | 100 | 0 | 0 | 1.000 | 1.000 |

Ground-truth rows: 500 ({'DISCONTINUED_SKU_RECOMMENDED': 100, 'FORECAST_LEAKAGE': 100, 'NEGATIVE_LEAD_TIME': 100, 'PACK_SIZE_VIOLATION': 100, 'STOCKOUT_AS_ZERO_DEMAND': 100}). Detectors use only input tables and rules; the labels live in `ground_truth/`.

## 3. Reproducibility

Run `python -m src.reproduce --scale full` (or `make reproduce`) - it executes this pipeline twice in separate processes and compares row counts and SHA-256 checksums of every output file. Evidence: `reproducibility.json`.

## 4. All checks (baseline)

| check | category | rows checked | violations |
|---|---|---|---|
| `schema.columns_present:supplier` | schema | 40 | 0 |
| `required:supplier.supplier_id` | required | 40 | 0 |
| `required:supplier.name` | required | 40 | 0 |
| `required:supplier.country` | required | 40 | 0 |
| `required:supplier.reliability_score` | required | 40 | 0 |
| `required:supplier.delay_probability` | required | 40 | 0 |
| `required:supplier.status` | required | 40 | 0 |
| `enum:supplier.status` | enum | 40 | 0 |
| `required:supplier.onboarded_date` | required | 40 | 0 |
| `pk_unique:supplier` | primary_key | 40 | 0 |
| `id_format:supplier.supplier_id` | id_format | 40 | 0 |
| `schema.columns_present:store` | schema | 100 | 0 |
| `required:store.store_id` | required | 100 | 0 |
| `required:store.name` | required | 100 | 0 |
| `required:store.region` | required | 100 | 0 |
| `enum:store.region` | enum | 100 | 0 |
| `required:store.format` | required | 100 | 0 |
| `enum:store.format` | enum | 100 | 0 |
| `required:store.capacity_units` | required | 100 | 0 |
| `required:store.open_date` | required | 100 | 0 |
| `required:store.status` | required | 100 | 0 |
| `enum:store.status` | enum | 100 | 0 |
| `pk_unique:store` | primary_key | 100 | 0 |
| `id_format:store.store_id` | id_format | 100 | 0 |
| `schema.columns_present:sku` | schema | 2000 | 0 |
| `required:sku.sku_id` | required | 2000 | 0 |
| `required:sku.name` | required | 2000 | 0 |
| `required:sku.category` | required | 2000 | 0 |
| `required:sku.subcategory` | required | 2000 | 0 |
| `required:sku.unit_cost` | required | 2000 | 0 |
| `required:sku.unit_price` | required | 2000 | 0 |
| `required:sku.volume_per_unit` | required | 2000 | 0 |
| `required:sku.launch_date` | required | 2000 | 0 |
| `required:sku.status` | required | 2000 | 0 |
| `enum:sku.status` | enum | 2000 | 0 |
| `pk_unique:sku` | primary_key | 2000 | 0 |
| `id_format:sku.sku_id` | id_format | 2000 | 0 |
| `schema.columns_present:supplier_sku` | schema | 2493 | 0 |
| `required:supplier_sku.supplier_id` | required | 2493 | 0 |
| `required:supplier_sku.sku_id` | required | 2493 | 0 |
| `required:supplier_sku.effective_from` | required | 2493 | 0 |
| `required:supplier_sku.pack_size` | required | 2493 | 0 |
| `required:supplier_sku.moq` | required | 2493 | 0 |
| `required:supplier_sku.unit_cost` | required | 2493 | 0 |
| `required:supplier_sku.mean_lead_time_days` | required | 2493 | 0 |
| `required:supplier_sku.lead_time_sd` | required | 2493 | 0 |
| `required:supplier_sku.is_primary` | required | 2493 | 0 |
| `enum:supplier_sku.is_primary` | enum | 2493 | 0 |
| `required:supplier_sku.status` | required | 2493 | 0 |
| `enum:supplier_sku.status` | enum | 2493 | 0 |
| `pk_unique:supplier_sku` | primary_key | 2493 | 0 |
| `fk:supplier_sku(supplier_id)->supplier` | foreign_key | 2493 | 0 |
| `fk:supplier_sku(sku_id)->sku` | foreign_key | 2493 | 0 |
| `schema.columns_present:store_sku` | schema | 15401 | 0 |
| `required:store_sku.store_id` | required | 15401 | 0 |
| `required:store_sku.sku_id` | required | 15401 | 0 |
| `required:store_sku.listed_from` | required | 15401 | 0 |
| `required:store_sku.status` | required | 15401 | 0 |
| `enum:store_sku.status` | enum | 15401 | 0 |
| `pk_unique:store_sku` | primary_key | 15401 | 0 |
| `fk:store_sku(store_id)->store` | foreign_key | 15401 | 0 |
| `fk:store_sku(sku_id)->sku` | foreign_key | 15401 | 0 |
| `schema.columns_present:sales_history` | schema | 5160733 | 0 |
| `required:sales_history.store_id` | required | 5160733 | 0 |
| `required:sales_history.sku_id` | required | 5160733 | 0 |
| `required:sales_history.date` | required | 5160733 | 0 |
| `required:sales_history.units_sold` | required | 5160733 | 0 |
| `required:sales_history.on_promo` | required | 5160733 | 0 |
| `enum:sales_history.on_promo` | enum | 5160733 | 0 |
| `required:sales_history.promo_depth` | required | 5160733 | 0 |
| `required:sales_history.price` | required | 5160733 | 0 |
| `required:sales_history.net_revenue` | required | 5160733 | 0 |
| `required:sales_history.stockout_flag` | required | 5160733 | 0 |
| `enum:sales_history.stockout_flag` | enum | 5160733 | 0 |
| `pk_unique:sales_history` | primary_key | 5160733 | 0 |
| `id_format:sales_history.sale_id` | id_format | 20003 | 0 |
| `fk:sales_history(store_id,sku_id)->store_sku` | foreign_key | 5160733 | 0 |
| `schema.columns_present:inventory_snapshot` | schema | 5160733 | 0 |
| `required:inventory_snapshot.store_id` | required | 5160733 | 0 |
| `required:inventory_snapshot.sku_id` | required | 5160733 | 0 |
| `required:inventory_snapshot.date` | required | 5160733 | 0 |
| `required:inventory_snapshot.on_hand_start` | required | 5160733 | 0 |
| `required:inventory_snapshot.receipts` | required | 5160733 | 0 |
| `required:inventory_snapshot.on_hand` | required | 5160733 | 0 |
| `required:inventory_snapshot.on_order` | required | 5160733 | 0 |
| `required:inventory_snapshot.in_transit` | required | 5160733 | 0 |
| `required:inventory_snapshot.stockout_flag` | required | 5160733 | 0 |
| `enum:inventory_snapshot.stockout_flag` | enum | 5160733 | 0 |
| `pk_unique:inventory_snapshot` | primary_key | 5160733 | 0 |
| `id_format:inventory_snapshot.snapshot_id` | id_format | 20003 | 0 |
| `fk:inventory_snapshot(store_id,sku_id)->store_sku` | foreign_key | 5160733 | 0 |
| `schema.columns_present:lead_time_observation` | schema | 196723 | 0 |
| `required:lead_time_observation.lt_obs_id` | required | 196723 | 0 |
| `required:lead_time_observation.supplier_id` | required | 196723 | 0 |
| `required:lead_time_observation.sku_id` | required | 196723 | 0 |
| `required:lead_time_observation.store_id` | required | 196723 | 0 |
| `required:lead_time_observation.order_date` | required | 196723 | 0 |
| `required:lead_time_observation.receipt_date` | required | 196723 | 0 |
| `required:lead_time_observation.lead_time_days` | required | 196723 | 0 |
| `required:lead_time_observation.units_received` | required | 196723 | 0 |
| `required:lead_time_observation.delay_flag` | required | 196723 | 0 |
| `enum:lead_time_observation.delay_flag` | enum | 196723 | 0 |
| `required:lead_time_observation.source` | required | 196723 | 0 |
| `enum:lead_time_observation.source` | enum | 196723 | 0 |
| `pk_unique:lead_time_observation` | primary_key | 196723 | 0 |
| `id_format:lead_time_observation.lt_obs_id` | id_format | 196723 | 0 |
| `fk:lead_time_observation(supplier_id)->supplier` | foreign_key | 196723 | 0 |
| `fk:lead_time_observation(sku_id)->sku` | foreign_key | 196723 | 0 |
| `fk:lead_time_observation(store_id,sku_id)->store_sku` | foreign_key | 196723 | 0 |
| `schema.columns_present:status_event` | schema | 47553 | 0 |
| `required:status_event.event_id` | required | 47553 | 0 |
| `required:status_event.entity_type` | required | 47553 | 0 |
| `enum:status_event.entity_type` | enum | 47553 | 0 |
| `required:status_event.entity_id` | required | 47553 | 0 |
| `required:status_event.new_status` | required | 47553 | 0 |
| `required:status_event.event_date` | required | 47553 | 0 |
| `required:status_event.reason` | required | 47553 | 0 |
| `pk_unique:status_event` | primary_key | 47553 | 0 |
| `schema.columns_present:forecast` | schema | 14588 | 0 |
| `required:forecast.forecast_id` | required | 14588 | 0 |
| `required:forecast.store_id` | required | 14588 | 0 |
| `required:forecast.sku_id` | required | 14588 | 0 |
| `required:forecast.forecast_month` | required | 14588 | 0 |
| `required:forecast.period_start` | required | 14588 | 0 |
| `required:forecast.period_end` | required | 14588 | 0 |
| `required:forecast.method` | required | 14588 | 0 |
| `enum:forecast.method` | enum | 14588 | 0 |
| `required:forecast.segment` | required | 14588 | 0 |
| `enum:forecast.segment` | enum | 14588 | 0 |
| `required:forecast.horizon_days` | required | 14588 | 0 |
| `required:forecast.forecast_units` | required | 14588 | 0 |
| `required:forecast.daily_rate` | required | 14588 | 0 |
| `required:forecast.lower` | required | 14588 | 0 |
| `required:forecast.upper` | required | 14588 | 0 |
| `required:forecast.training_cutoff_date` | required | 14588 | 0 |
| `required:forecast.confidence` | required | 14588 | 0 |
| `enum:forecast.confidence` | enum | 14588 | 0 |
| `pk_unique:forecast` | primary_key | 14588 | 0 |
| `id_format:forecast.forecast_id` | id_format | 14588 | 0 |
| `fk:forecast(store_id,sku_id)->store_sku` | foreign_key | 14588 | 0 |
| `schema.columns_present:reorder_policy` | schema | 28152 | 0 |
| `required:reorder_policy.policy_id` | required | 28152 | 0 |
| `required:reorder_policy.store_id` | required | 28152 | 0 |
| `required:reorder_policy.sku_id` | required | 28152 | 0 |
| `required:reorder_policy.supplier_id` | required | 28152 | 0 |
| `required:reorder_policy.version` | required | 28152 | 0 |
| `required:reorder_policy.service_level` | required | 28152 | 0 |
| `required:reorder_policy.z` | required | 28152 | 0 |
| `required:reorder_policy.review_period_days` | required | 28152 | 0 |
| `required:reorder_policy.mean_lead_time_days` | required | 28152 | 0 |
| `required:reorder_policy.lead_time_sd` | required | 28152 | 0 |
| `required:reorder_policy.lead_time_source` | required | 28152 | 0 |
| `enum:reorder_policy.lead_time_source` | enum | 28152 | 0 |
| `required:reorder_policy.daily_demand_est` | required | 28152 | 0 |
| `required:reorder_policy.demand_sd` | required | 28152 | 0 |
| `required:reorder_policy.safety_stock` | required | 28152 | 0 |
| `required:reorder_policy.reorder_point` | required | 28152 | 0 |
| `required:reorder_policy.order_up_to` | required | 28152 | 0 |
| `required:reorder_policy.segment` | required | 28152 | 0 |
| `enum:reorder_policy.segment` | enum | 28152 | 0 |
| `required:reorder_policy.effective_from` | required | 28152 | 0 |
| `required:reorder_policy.computed_from_cutoff` | required | 28152 | 0 |
| `required:reorder_policy.status` | required | 28152 | 0 |
| `enum:reorder_policy.status` | enum | 28152 | 0 |
| `pk_unique:reorder_policy` | primary_key | 28152 | 0 |
| `id_format:reorder_policy.policy_id` | id_format | 28152 | 0 |
| `fk:reorder_policy(store_id,sku_id)->store_sku` | foreign_key | 28152 | 0 |
| `fk:reorder_policy(supplier_id)->supplier` | foreign_key | 28152 | 0 |
| `schema.columns_present:purchase_recommendation` | schema | 3020 | 0 |
| `required:purchase_recommendation.po_id` | required | 3020 | 0 |
| `required:purchase_recommendation.store_id` | required | 3020 | 0 |
| `required:purchase_recommendation.sku_id` | required | 3020 | 0 |
| `required:purchase_recommendation.raw_qty` | required | 3020 | 0 |
| `required:purchase_recommendation.recommended_qty` | required | 3020 | 0 |
| `required:purchase_recommendation.order_value` | required | 3020 | 0 |
| `required:purchase_recommendation.reason_code` | required | 3020 | 0 |
| `enum:purchase_recommendation.reason_code` | enum | 3020 | 0 |
| `required:purchase_recommendation.status` | required | 3020 | 0 |
| `enum:purchase_recommendation.status` | enum | 3020 | 0 |
| `enum:purchase_recommendation.confidence` | enum | 3020 | 0 |
| `required:purchase_recommendation.created_at` | required | 3020 | 0 |
| `pk_unique:purchase_recommendation` | primary_key | 3020 | 0 |
| `id_format:purchase_recommendation.po_id` | id_format | 3020 | 0 |
| `fk:purchase_recommendation(store_id,sku_id)->store_sku` | foreign_key | 3020 | 0 |
| `fk:purchase_recommendation(supplier_id)->supplier` | foreign_key | 3020 | 0 |
| `fk:purchase_recommendation(forecast_id)->forecast` | foreign_key | 1972 | 0 |
| `fk:purchase_recommendation(policy_id)->reorder_policy` | foreign_key | 1972 | 0 |
| `schema.columns_present:exception_log` | schema | 1102 | 0 |
| `required:exception_log.exception_id` | required | 1102 | 0 |
| `required:exception_log.exception_code` | required | 1102 | 0 |
| `required:exception_log.entity_type` | required | 1102 | 0 |
| `required:exception_log.entity_id` | required | 1102 | 0 |
| `required:exception_log.reason_code` | required | 1102 | 0 |
| `required:exception_log.detail` | required | 1102 | 0 |
| `required:exception_log.severity` | required | 1102 | 0 |
| `enum:exception_log.severity` | enum | 1102 | 0 |
| `pk_unique:exception_log` | primary_key | 1102 | 0 |
| `lifecycle.no_sales_before_launch` | lifecycle | 5160733 | 0 |
| `lifecycle.no_sales_on_or_after_discontinue` | lifecycle | 5160733 | 0 |
| `date_order:sku.launch<discontinue` | date_order | 2000 | 0 |
| `date_order:supplier_sku.effective_from<effective_to` | date_order | 2493 | 0 |
| `date_order:reorder_policy.effective_from<effective_to` | date_order | 28152 | 0 |
| `date_order:reorder_policy.cutoff<effective_from` | date_order | 28152 | 0 |
| `lifecycle.one_active_policy_per_store_sku` | lifecycle | 28152 | 0 |
| `lifecycle.primary_supplier_no_overlap` | lifecycle | 2160 | 0 |
| `lifecycle.status_event_transitions_legal` | lifecycle | 47553 | 0 |
| `lifecycle.sku_status_matches_last_event` | lifecycle | 2000 | 0 |
| `reconcile.sales_and_inventory_same_grain` | reconciliation | 5160733 | 0 |
| `reconcile.on_hand=start+receipts-sold` | reconciliation | 5160733 | 0 |
| `reconcile.units_sold<=available_stock` | reconciliation | 5160733 | 0 |
| `reconcile.opening_balance=previous_closing` | reconciliation | 5145647 | 0 |
| `reconcile.stockout_flag_sales=inventory` | reconciliation | 5160733 | 0 |
| `reconcile.receipts=sum(lead_time_observation.units)` | reconciliation | 196194 | 0 |
| `reconcile.net_revenue=units*price` | reconciliation | 5160733 | 0 |
| `reconcile.on_promo<=>promo_depth>0` | reconciliation | 5160733 | 0 |
| `range.inventory_non_negative` | range | 5160733 | 0 |
| `reconcile.lead_time_days=receipt-order` | reconciliation | 196723 | 0 |
| `reconcile.forecast_bounds` | reconciliation | 14588 | 0 |
| `reconcile.forecast_id_matches_keys` | id_format | 14588 | 0 |
| `duplicate.purchase_recommendation_per_store_sku_period` | duplicate | 3020 | 0 |
| `duplicate.forecast_per_store_sku_month` | duplicate | 14588 | 0 |
| `business.moq_respected` | business_rule | 1924 | 0 |
| `business.recommendation_has_valid_supplier` | business_rule | 1924 | 0 |
| `business.capacity_respected_per_store` | business_rule | 100 | 0 |
| `business.blocked_has_zero_qty` | business_rule | 1096 | 0 |
| `detect.stockout_flagged_as_zero_demand` | anomaly_detector | 5160733 | 0 |
| `detect.order_qty_not_multiple_of_pack_size` | anomaly_detector | 1924 | 0 |
| `detect.discontinued_sku_recommended` | anomaly_detector | 3020 | 0 |
| `detect.negative_lead_time` | anomaly_detector | 196723 | 0 |
| `detect.forecast_uses_future_sales` | anomaly_detector | 14588 | 0 |
