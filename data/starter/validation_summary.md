# Validation summary

Scale: `starter` | seed: `20261022` | history: 2025-09-03 to 2025-12-31 (120 days)

## 1. Clean baseline (before anomaly injection)

- Structural checks: **248**, violations: **0**
- Anomaly detectors on the clean baseline (expected 0): {'detect.stockout_flagged_as_zero_demand': 0, 'detect.order_qty_not_multiple_of_pack_size': 0, 'detect.discontinued_sku_recommended': 0, 'detect.negative_lead_time': 0, 'detect.forecast_uses_future_sales': 0}

| category | checks | rows checked | violations | failed checks |
|---|---|---|---|---|
| business_rule | 5 | 67 | 0 | 0 |
| date_order | 4 | 581 | 0 | 0 |
| duplicate | 2 | 157 | 0 | 0 |
| enum | 24 | 46254 | 0 | 0 |
| foreign_key | 16 | 31419 | 0 | 0 |
| id_format | 10 | 29946 | 0 | 0 |
| lifecycle | 6 | 29666 | 0 | 0 |
| primary_key | 13 | 30474 | 0 | 0 |
| range | 16 | 58623 | 0 | 0 |
| reconciliation | 17 | 102648 | 0 | 0 |
| required | 122 | 276097 | 0 | 0 |
| schema | 13 | 30474 | 0 | 0 |

## 2. After labelled anomaly injection

- Structural violations after injection (expected 0 - injections touch only their own rows): **0**
- Failed structural checks: none

| issue type | injected | detected | true pos. | false pos. | false neg. | precision | recall |
|---|---|---|---|---|---|---|---|
| STOCKOUT_AS_ZERO_DEMAND | 5 | 5 | 5 | 0 | 0 | 1.000 | 1.000 |
| PACK_SIZE_VIOLATION | 5 | 5 | 5 | 0 | 0 | 1.000 | 1.000 |
| DISCONTINUED_SKU_RECOMMENDED | 5 | 5 | 5 | 0 | 0 | 1.000 | 1.000 |
| NEGATIVE_LEAD_TIME | 5 | 5 | 5 | 0 | 0 | 1.000 | 1.000 |
| FORECAST_LEAKAGE | 5 | 5 | 5 | 0 | 0 | 1.000 | 1.000 |

Ground-truth rows: 25 ({'DISCONTINUED_SKU_RECOMMENDED': 5, 'FORECAST_LEAKAGE': 5, 'NEGATIVE_LEAD_TIME': 5, 'PACK_SIZE_VIOLATION': 5, 'STOCKOUT_AS_ZERO_DEMAND': 5}). Detectors use only input tables and rules; the labels live in `ground_truth/`.

## 3. Reproducibility

Run `python -m src.reproduce --scale starter` (or `make reproduce`) - it executes this pipeline twice in separate processes and compares row counts and SHA-256 checksums of every output file. Evidence: `reproducibility.json`.

## 4. All checks (baseline)

| check | category | rows checked | violations |
|---|---|---|---|
| `schema.columns_present:supplier` | schema | 5 | 0 |
| `required:supplier.supplier_id` | required | 5 | 0 |
| `required:supplier.name` | required | 5 | 0 |
| `required:supplier.country` | required | 5 | 0 |
| `required:supplier.reliability_score` | required | 5 | 0 |
| `required:supplier.delay_probability` | required | 5 | 0 |
| `required:supplier.status` | required | 5 | 0 |
| `enum:supplier.status` | enum | 5 | 0 |
| `required:supplier.onboarded_date` | required | 5 | 0 |
| `pk_unique:supplier` | primary_key | 5 | 0 |
| `id_format:supplier.supplier_id` | id_format | 5 | 0 |
| `schema.columns_present:store` | schema | 5 | 0 |
| `required:store.store_id` | required | 5 | 0 |
| `required:store.name` | required | 5 | 0 |
| `required:store.region` | required | 5 | 0 |
| `enum:store.region` | enum | 5 | 0 |
| `required:store.format` | required | 5 | 0 |
| `enum:store.format` | enum | 5 | 0 |
| `required:store.capacity_units` | required | 5 | 0 |
| `required:store.open_date` | required | 5 | 0 |
| `required:store.status` | required | 5 | 0 |
| `enum:store.status` | enum | 5 | 0 |
| `pk_unique:store` | primary_key | 5 | 0 |
| `id_format:store.store_id` | id_format | 5 | 0 |
| `schema.columns_present:sku` | schema | 50 | 0 |
| `required:sku.sku_id` | required | 50 | 0 |
| `required:sku.name` | required | 50 | 0 |
| `required:sku.category` | required | 50 | 0 |
| `required:sku.subcategory` | required | 50 | 0 |
| `required:sku.unit_cost` | required | 50 | 0 |
| `required:sku.unit_price` | required | 50 | 0 |
| `required:sku.volume_per_unit` | required | 50 | 0 |
| `required:sku.launch_date` | required | 50 | 0 |
| `required:sku.status` | required | 50 | 0 |
| `enum:sku.status` | enum | 50 | 0 |
| `pk_unique:sku` | primary_key | 50 | 0 |
| `id_format:sku.sku_id` | id_format | 50 | 0 |
| `schema.columns_present:supplier_sku` | schema | 59 | 0 |
| `required:supplier_sku.supplier_id` | required | 59 | 0 |
| `required:supplier_sku.sku_id` | required | 59 | 0 |
| `required:supplier_sku.effective_from` | required | 59 | 0 |
| `required:supplier_sku.pack_size` | required | 59 | 0 |
| `required:supplier_sku.moq` | required | 59 | 0 |
| `required:supplier_sku.unit_cost` | required | 59 | 0 |
| `required:supplier_sku.mean_lead_time_days` | required | 59 | 0 |
| `required:supplier_sku.lead_time_sd` | required | 59 | 0 |
| `required:supplier_sku.is_primary` | required | 59 | 0 |
| `enum:supplier_sku.is_primary` | enum | 59 | 0 |
| `required:supplier_sku.status` | required | 59 | 0 |
| `enum:supplier_sku.status` | enum | 59 | 0 |
| `pk_unique:supplier_sku` | primary_key | 59 | 0 |
| `fk:supplier_sku(supplier_id)->supplier` | foreign_key | 59 | 0 |
| `fk:supplier_sku(sku_id)->sku` | foreign_key | 59 | 0 |
| `schema.columns_present:store_sku` | schema | 134 | 0 |
| `required:store_sku.store_id` | required | 134 | 0 |
| `required:store_sku.sku_id` | required | 134 | 0 |
| `required:store_sku.listed_from` | required | 134 | 0 |
| `required:store_sku.status` | required | 134 | 0 |
| `enum:store_sku.status` | enum | 134 | 0 |
| `pk_unique:store_sku` | primary_key | 134 | 0 |
| `fk:store_sku(store_id)->store` | foreign_key | 134 | 0 |
| `fk:store_sku(sku_id)->sku` | foreign_key | 134 | 0 |
| `schema.columns_present:sales_history` | schema | 14445 | 0 |
| `required:sales_history.store_id` | required | 14445 | 0 |
| `required:sales_history.sku_id` | required | 14445 | 0 |
| `required:sales_history.date` | required | 14445 | 0 |
| `required:sales_history.units_sold` | required | 14445 | 0 |
| `required:sales_history.on_promo` | required | 14445 | 0 |
| `enum:sales_history.on_promo` | enum | 14445 | 0 |
| `required:sales_history.promo_depth` | required | 14445 | 0 |
| `required:sales_history.price` | required | 14445 | 0 |
| `required:sales_history.net_revenue` | required | 14445 | 0 |
| `required:sales_history.stockout_flag` | required | 14445 | 0 |
| `enum:sales_history.stockout_flag` | enum | 14445 | 0 |
| `pk_unique:sales_history` | primary_key | 14445 | 0 |
| `id_format:sales_history.sale_id` | id_format | 14445 | 0 |
| `fk:sales_history(store_id,sku_id)->store_sku` | foreign_key | 14445 | 0 |
| `schema.columns_present:inventory_snapshot` | schema | 14445 | 0 |
| `required:inventory_snapshot.store_id` | required | 14445 | 0 |
| `required:inventory_snapshot.sku_id` | required | 14445 | 0 |
| `required:inventory_snapshot.date` | required | 14445 | 0 |
| `required:inventory_snapshot.on_hand_start` | required | 14445 | 0 |
| `required:inventory_snapshot.receipts` | required | 14445 | 0 |
| `required:inventory_snapshot.on_hand` | required | 14445 | 0 |
| `required:inventory_snapshot.on_order` | required | 14445 | 0 |
| `required:inventory_snapshot.in_transit` | required | 14445 | 0 |
| `required:inventory_snapshot.stockout_flag` | required | 14445 | 0 |
| `enum:inventory_snapshot.stockout_flag` | enum | 14445 | 0 |
| `pk_unique:inventory_snapshot` | primary_key | 14445 | 0 |
| `id_format:inventory_snapshot.snapshot_id` | id_format | 14445 | 0 |
| `fk:inventory_snapshot(store_id,sku_id)->store_sku` | foreign_key | 14445 | 0 |
| `schema.columns_present:lead_time_observation` | schema | 480 | 0 |
| `required:lead_time_observation.lt_obs_id` | required | 480 | 0 |
| `required:lead_time_observation.supplier_id` | required | 480 | 0 |
| `required:lead_time_observation.sku_id` | required | 480 | 0 |
| `required:lead_time_observation.store_id` | required | 480 | 0 |
| `required:lead_time_observation.order_date` | required | 480 | 0 |
| `required:lead_time_observation.receipt_date` | required | 480 | 0 |
| `required:lead_time_observation.lead_time_days` | required | 480 | 0 |
| `required:lead_time_observation.units_received` | required | 480 | 0 |
| `required:lead_time_observation.delay_flag` | required | 480 | 0 |
| `enum:lead_time_observation.delay_flag` | enum | 480 | 0 |
| `required:lead_time_observation.source` | required | 480 | 0 |
| `enum:lead_time_observation.source` | enum | 480 | 0 |
| `pk_unique:lead_time_observation` | primary_key | 480 | 0 |
| `id_format:lead_time_observation.lt_obs_id` | id_format | 480 | 0 |
| `fk:lead_time_observation(supplier_id)->supplier` | foreign_key | 480 | 0 |
| `fk:lead_time_observation(sku_id)->sku` | foreign_key | 480 | 0 |
| `fk:lead_time_observation(store_id,sku_id)->store_sku` | foreign_key | 480 | 0 |
| `schema.columns_present:status_event` | schema | 436 | 0 |
| `required:status_event.event_id` | required | 436 | 0 |
| `required:status_event.entity_type` | required | 436 | 0 |
| `enum:status_event.entity_type` | enum | 436 | 0 |
| `required:status_event.entity_id` | required | 436 | 0 |
| `required:status_event.new_status` | required | 436 | 0 |
| `required:status_event.event_date` | required | 436 | 0 |
| `required:status_event.reason` | required | 436 | 0 |
| `pk_unique:status_event` | primary_key | 436 | 0 |
| `schema.columns_present:forecast` | schema | 123 | 0 |
| `required:forecast.forecast_id` | required | 123 | 0 |
| `required:forecast.store_id` | required | 123 | 0 |
| `required:forecast.sku_id` | required | 123 | 0 |
| `required:forecast.forecast_month` | required | 123 | 0 |
| `required:forecast.period_start` | required | 123 | 0 |
| `required:forecast.period_end` | required | 123 | 0 |
| `required:forecast.method` | required | 123 | 0 |
| `enum:forecast.method` | enum | 123 | 0 |
| `required:forecast.segment` | required | 123 | 0 |
| `enum:forecast.segment` | enum | 123 | 0 |
| `required:forecast.horizon_days` | required | 123 | 0 |
| `required:forecast.forecast_units` | required | 123 | 0 |
| `required:forecast.daily_rate` | required | 123 | 0 |
| `required:forecast.lower` | required | 123 | 0 |
| `required:forecast.upper` | required | 123 | 0 |
| `required:forecast.training_cutoff_date` | required | 123 | 0 |
| `required:forecast.confidence` | required | 123 | 0 |
| `enum:forecast.confidence` | enum | 123 | 0 |
| `pk_unique:forecast` | primary_key | 123 | 0 |
| `id_format:forecast.forecast_id` | id_format | 123 | 0 |
| `fk:forecast(store_id,sku_id)->store_sku` | foreign_key | 123 | 0 |
| `schema.columns_present:reorder_policy` | schema | 236 | 0 |
| `required:reorder_policy.policy_id` | required | 236 | 0 |
| `required:reorder_policy.store_id` | required | 236 | 0 |
| `required:reorder_policy.sku_id` | required | 236 | 0 |
| `required:reorder_policy.supplier_id` | required | 236 | 0 |
| `required:reorder_policy.version` | required | 236 | 0 |
| `required:reorder_policy.service_level` | required | 236 | 0 |
| `required:reorder_policy.z` | required | 236 | 0 |
| `required:reorder_policy.review_period_days` | required | 236 | 0 |
| `required:reorder_policy.mean_lead_time_days` | required | 236 | 0 |
| `required:reorder_policy.lead_time_sd` | required | 236 | 0 |
| `required:reorder_policy.lead_time_source` | required | 236 | 0 |
| `enum:reorder_policy.lead_time_source` | enum | 236 | 0 |
| `required:reorder_policy.daily_demand_est` | required | 236 | 0 |
| `required:reorder_policy.demand_sd` | required | 236 | 0 |
| `required:reorder_policy.safety_stock` | required | 236 | 0 |
| `required:reorder_policy.reorder_point` | required | 236 | 0 |
| `required:reorder_policy.order_up_to` | required | 236 | 0 |
| `required:reorder_policy.segment` | required | 236 | 0 |
| `enum:reorder_policy.segment` | enum | 236 | 0 |
| `required:reorder_policy.effective_from` | required | 236 | 0 |
| `required:reorder_policy.computed_from_cutoff` | required | 236 | 0 |
| `required:reorder_policy.status` | required | 236 | 0 |
| `enum:reorder_policy.status` | enum | 236 | 0 |
| `pk_unique:reorder_policy` | primary_key | 236 | 0 |
| `id_format:reorder_policy.policy_id` | id_format | 236 | 0 |
| `fk:reorder_policy(store_id,sku_id)->store_sku` | foreign_key | 236 | 0 |
| `fk:reorder_policy(supplier_id)->supplier` | foreign_key | 236 | 0 |
| `schema.columns_present:purchase_recommendation` | schema | 34 | 0 |
| `required:purchase_recommendation.po_id` | required | 34 | 0 |
| `required:purchase_recommendation.store_id` | required | 34 | 0 |
| `required:purchase_recommendation.sku_id` | required | 34 | 0 |
| `required:purchase_recommendation.raw_qty` | required | 34 | 0 |
| `required:purchase_recommendation.recommended_qty` | required | 34 | 0 |
| `required:purchase_recommendation.order_value` | required | 34 | 0 |
| `required:purchase_recommendation.reason_code` | required | 34 | 0 |
| `enum:purchase_recommendation.reason_code` | enum | 34 | 0 |
| `required:purchase_recommendation.status` | required | 34 | 0 |
| `enum:purchase_recommendation.status` | enum | 34 | 0 |
| `enum:purchase_recommendation.confidence` | enum | 34 | 0 |
| `required:purchase_recommendation.created_at` | required | 34 | 0 |
| `pk_unique:purchase_recommendation` | primary_key | 34 | 0 |
| `id_format:purchase_recommendation.po_id` | id_format | 34 | 0 |
| `fk:purchase_recommendation(store_id,sku_id)->store_sku` | foreign_key | 34 | 0 |
| `fk:purchase_recommendation(supplier_id)->supplier` | foreign_key | 34 | 0 |
| `fk:purchase_recommendation(forecast_id)->forecast` | foreign_key | 20 | 0 |
| `fk:purchase_recommendation(policy_id)->reorder_policy` | foreign_key | 20 | 0 |
| `schema.columns_present:exception_log` | schema | 22 | 0 |
| `required:exception_log.exception_id` | required | 22 | 0 |
| `required:exception_log.exception_code` | required | 22 | 0 |
| `required:exception_log.entity_type` | required | 22 | 0 |
| `required:exception_log.entity_id` | required | 22 | 0 |
| `required:exception_log.reason_code` | required | 22 | 0 |
| `required:exception_log.detail` | required | 22 | 0 |
| `required:exception_log.severity` | required | 22 | 0 |
| `enum:exception_log.severity` | enum | 22 | 0 |
| `pk_unique:exception_log` | primary_key | 22 | 0 |
| `lifecycle.no_sales_before_launch` | lifecycle | 14445 | 0 |
| `lifecycle.no_sales_on_or_after_discontinue` | lifecycle | 14445 | 0 |
| `date_order:sku.launch<discontinue` | date_order | 50 | 0 |
| `date_order:supplier_sku.effective_from<effective_to` | date_order | 59 | 0 |
| `date_order:reorder_policy.effective_from<effective_to` | date_order | 236 | 0 |
| `date_order:reorder_policy.cutoff<effective_from` | date_order | 236 | 0 |
| `lifecycle.one_active_policy_per_store_sku` | lifecycle | 236 | 0 |
| `lifecycle.primary_supplier_no_overlap` | lifecycle | 54 | 0 |
| `lifecycle.status_event_transitions_legal` | lifecycle | 436 | 0 |
| `lifecycle.sku_status_matches_last_event` | lifecycle | 50 | 0 |
| `reconcile.sales_and_inventory_same_grain` | reconciliation | 14445 | 0 |
| `reconcile.on_hand=start+receipts-sold` | reconciliation | 14445 | 0 |
| `reconcile.units_sold<=available_stock` | reconciliation | 14445 | 0 |
| `reconcile.opening_balance=previous_closing` | reconciliation | 14316 | 0 |
| `reconcile.stockout_flag_sales=inventory` | reconciliation | 14445 | 0 |
| `reconcile.receipts=sum(lead_time_observation.units)` | reconciliation | 479 | 0 |
| `reconcile.net_revenue=units*price` | reconciliation | 14445 | 0 |
| `reconcile.on_promo<=>promo_depth>0` | reconciliation | 14445 | 0 |
| `range.inventory_non_negative` | range | 14445 | 0 |
| `reconcile.lead_time_days=receipt-order` | reconciliation | 480 | 0 |
| `reconcile.forecast_bounds` | reconciliation | 123 | 0 |
| `reconcile.forecast_id_matches_keys` | id_format | 123 | 0 |
| `reconcile.order_value=qty*unit_cost` | reconciliation | 34 | 0 |
| `range.recommendation_non_negative` | range | 34 | 0 |
| `reconcile.policy_id_points_to_same_store_sku` | reconciliation | 20 | 0 |
| `reconcile.forecast_id_points_to_same_store_sku` | reconciliation | 20 | 0 |
| `reconcile.inventory_position=last_snapshot` | reconciliation | 20 | 0 |
| `business.reorder_trigger_ip<=rop` | business_rule | 14 | 0 |
| `reconcile.raw_qty=max(0,order_up_to-ip)` | reconciliation | 14 | 0 |
| `reconcile.policy_rop=d*L+ss` | reconciliation | 236 | 0 |
| `reconcile.policy_order_up_to=d*(L+R)+ss` | reconciliation | 236 | 0 |
| `range:sku.unit_cost` | range | 50 | 0 |
| `range:sku.unit_price` | range | 50 | 0 |
| `range:sku.volume_per_unit` | range | 50 | 0 |
| `range:store.capacity_units` | range | 5 | 0 |
| `range:supplier_sku.pack_size` | range | 59 | 0 |
| `range:supplier_sku.moq` | range | 59 | 0 |
| `range:supplier_sku.unit_cost` | range | 59 | 0 |
| `range:supplier_sku.mean_lead_time_days` | range | 59 | 0 |
| `range:sales_history.units_sold` | range | 14445 | 0 |
| `range:sales_history.promo_depth` | range | 14445 | 0 |
| `range:sales_history.price` | range | 14445 | 0 |
| `range:reorder_policy.service_level` | range | 236 | 0 |
| `range:forecast.forecast_units` | range | 123 | 0 |
| `range:supplier_sku.moq_multiple_of_pack_after_rounding` | range | 59 | 0 |
| `duplicate.purchase_recommendation_per_store_sku_period` | duplicate | 34 | 0 |
| `duplicate.forecast_per_store_sku_month` | duplicate | 123 | 0 |
| `business.moq_respected` | business_rule | 14 | 0 |
| `business.recommendation_has_valid_supplier` | business_rule | 14 | 0 |
| `business.capacity_respected_per_store` | business_rule | 5 | 0 |
| `business.blocked_has_zero_qty` | business_rule | 20 | 0 |
| `detect.stockout_flagged_as_zero_demand` | anomaly_detector | 14445 | 0 |
| `detect.order_qty_not_multiple_of_pack_size` | anomaly_detector | 14 | 0 |
| `detect.discontinued_sku_recommended` | anomaly_detector | 34 | 0 |
| `detect.negative_lead_time` | anomaly_detector | 480 | 0 |
| `detect.forecast_uses_future_sales` | anomaly_detector | 123 | 0 |
