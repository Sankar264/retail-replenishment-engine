-- Generated from src/schema.py. SQLite/PostgreSQL compatible. Dates are ISO-8601 text.
-- NOTE: value CHECK constraints are intentionally omitted so labelled anomaly rows can load;
-- they are detected by the validation suite (src/validate.py) instead.
PRAGMA foreign_keys = ON;

CREATE TABLE supplier (
  supplier_id TEXT NOT NULL,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  reliability_score REAL NOT NULL,
  delay_probability REAL NOT NULL,
  status TEXT NOT NULL,
  onboarded_date TEXT NOT NULL,
  PRIMARY KEY (supplier_id)
);

CREATE TABLE store (
  store_id TEXT NOT NULL,
  name TEXT NOT NULL,
  region TEXT NOT NULL,
  format TEXT NOT NULL,
  capacity_units INTEGER NOT NULL,
  open_date TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (store_id)
);

CREATE TABLE sku (
  sku_id TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  subcategory TEXT NOT NULL,
  unit_cost REAL NOT NULL,
  unit_price REAL NOT NULL,
  volume_per_unit REAL NOT NULL,
  launch_date TEXT NOT NULL,
  discontinue_date TEXT,
  status TEXT NOT NULL,
  PRIMARY KEY (sku_id)
);

CREATE TABLE supplier_sku (
  supplier_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  pack_size INTEGER NOT NULL,
  moq INTEGER NOT NULL,
  unit_cost REAL NOT NULL,
  mean_lead_time_days REAL NOT NULL,
  lead_time_sd REAL NOT NULL,
  is_primary INTEGER NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (supplier_id, sku_id, effective_from),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id)
);

CREATE TABLE store_sku (
  store_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  listed_from TEXT NOT NULL,
  listed_to TEXT,
  status TEXT NOT NULL,
  PRIMARY KEY (store_id, sku_id),
  FOREIGN KEY (store_id) REFERENCES store (store_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id)
);

CREATE TABLE sales_history (
  sale_id TEXT NOT NULL,
  store_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  date TEXT NOT NULL,
  units_sold INTEGER NOT NULL,
  on_promo INTEGER NOT NULL,
  promo_depth REAL NOT NULL,
  price REAL NOT NULL,
  net_revenue REAL NOT NULL,
  stockout_flag INTEGER NOT NULL,
  PRIMARY KEY (sale_id),
  FOREIGN KEY (store_id, sku_id) REFERENCES store_sku (store_id, sku_id)
);

CREATE TABLE inventory_snapshot (
  snapshot_id TEXT NOT NULL,
  store_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  date TEXT NOT NULL,
  on_hand_start INTEGER NOT NULL,
  receipts INTEGER NOT NULL,
  on_hand INTEGER NOT NULL,
  on_order INTEGER NOT NULL,
  in_transit INTEGER NOT NULL,
  stockout_flag INTEGER NOT NULL,
  PRIMARY KEY (snapshot_id),
  FOREIGN KEY (store_id, sku_id) REFERENCES store_sku (store_id, sku_id)
);

CREATE TABLE lead_time_observation (
  lt_obs_id TEXT NOT NULL,
  supplier_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  store_id TEXT NOT NULL,
  order_date TEXT NOT NULL,
  receipt_date TEXT NOT NULL,
  lead_time_days INTEGER NOT NULL,
  units_received INTEGER NOT NULL,
  delay_flag INTEGER NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY (lt_obs_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (store_id, sku_id) REFERENCES store_sku (store_id, sku_id)
);

CREATE TABLE status_event (
  event_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  old_status TEXT,
  new_status TEXT NOT NULL,
  event_date TEXT NOT NULL,
  reason TEXT NOT NULL,
  PRIMARY KEY (event_id)
);

CREATE TABLE forecast (
  forecast_id TEXT NOT NULL,
  store_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  forecast_month TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  method TEXT NOT NULL,
  segment TEXT NOT NULL,
  horizon_days INTEGER NOT NULL,
  forecast_units REAL NOT NULL,
  daily_rate REAL NOT NULL,
  lower REAL NOT NULL,
  upper REAL NOT NULL,
  training_cutoff_date TEXT NOT NULL,
  confidence TEXT NOT NULL,
  PRIMARY KEY (forecast_id),
  FOREIGN KEY (store_id, sku_id) REFERENCES store_sku (store_id, sku_id)
);

CREATE TABLE reorder_policy (
  policy_id TEXT NOT NULL,
  store_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  supplier_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  service_level REAL NOT NULL,
  z REAL NOT NULL,
  review_period_days INTEGER NOT NULL,
  mean_lead_time_days REAL NOT NULL,
  lead_time_sd REAL NOT NULL,
  lead_time_source TEXT NOT NULL,
  daily_demand_est REAL NOT NULL,
  demand_sd REAL NOT NULL,
  safety_stock REAL NOT NULL,
  reorder_point REAL NOT NULL,
  order_up_to REAL NOT NULL,
  segment TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  computed_from_cutoff TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (policy_id),
  FOREIGN KEY (store_id, sku_id) REFERENCES store_sku (store_id, sku_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id)
);

CREATE TABLE purchase_recommendation (
  po_id TEXT NOT NULL,
  store_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  supplier_id TEXT,
  forecast_id TEXT,
  policy_id TEXT,
  raw_qty REAL NOT NULL,
  recommended_qty INTEGER NOT NULL,
  pack_size INTEGER,
  moq INTEGER,
  inventory_position INTEGER,
  reorder_point REAL,
  order_up_to REAL,
  unit_cost REAL,
  order_value REAL NOT NULL,
  expected_lead_time_days REAL,
  reason_code TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (po_id),
  FOREIGN KEY (store_id, sku_id) REFERENCES store_sku (store_id, sku_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id),
  FOREIGN KEY (forecast_id) REFERENCES forecast (forecast_id),
  FOREIGN KEY (policy_id) REFERENCES reorder_policy (policy_id)
);

CREATE TABLE exception_log (
  exception_id TEXT NOT NULL,
  exception_code TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  store_id TEXT,
  sku_id TEXT,
  reason_code TEXT NOT NULL,
  detail TEXT NOT NULL,
  severity TEXT NOT NULL,
  PRIMARY KEY (exception_id)
);
