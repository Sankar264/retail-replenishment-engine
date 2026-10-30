"""Single-source schema: drives the data dictionary, SQL DDL, ERD and the validation suite.

Field spec: name | type | required(Y/N) | allowed values / range | unit | unique | validation rule
(types: text, int, real, date, bool).  `unique` = Y means unique across the table (PK columns are unique as a set).
"""
from __future__ import annotations

T = {}


def table(name, desc, pk, fks, fields, cardinality="", lifecycle="", grain=""):
    cols = []
    for line in fields.strip().splitlines():
        n, ty, req, allowed, unit, uniq, rule = [x.strip() for x in line.split("|")]
        cols.append(dict(name=n, type=ty, required=req == "Y", allowed=allowed, unit=unit, unique=uniq == "Y", rule=rule))
    T[name] = dict(name=name, desc=desc, pk=pk, fks=fks, cols=cols, cardinality=cardinality, lifecycle=lifecycle, grain=grain)


table("supplier", "Supplier master. Reliability drives lead-time variability and delay probability.", ["supplier_id"], [], """
supplier_id|text|Y|SUP-NNNNNN||Y|format ^SUP-\\d{6}$
name|text|Y|||N|non-empty
country|text|Y|ISO-like code||N|non-empty
reliability_score|real|Y|0.5-1.0|ratio|N|0.5<=x<=1
delay_probability|real|Y|0-0.5|probability|N|derived: (1-reliability)*0.5
status|text|Y|ACTIVE,SUSPENDED||N|enum
onboarded_date|date|Y|ISO date||N|<= first sale date
""", cardinality="Supplier 1:N SupplierSKU", lifecycle="ACTIVE -> SUSPENDED (never deleted)")

table("store", "Store / warehouse master with a storage capacity constraint.", ["store_id"], [], """
store_id|text|Y|STORE-NNNNNN||Y|format ^STORE-\\d{6}$
name|text|Y|||N|non-empty
region|text|Y|NORTH,SOUTH,EAST,WEST,CENTRAL||N|enum
format|text|Y|HYPER,SUPER,EXPRESS||N|enum; drives size and assortment breadth
capacity_units|int|Y|>0|volume units (same unit as sku.volume_per_unit)|N|calibrated from simulated peak utilisation
open_date|date|Y|ISO date||N|<= first sale date
status|text|Y|ACTIVE,CLOSED||N|enum
""", cardinality="Store N:M SKU via store_sku", lifecycle="ACTIVE -> CLOSED")

table("sku", "Product master. Launch / discontinue dates create cold starts and lifecycle rules.", ["sku_id"], [], """
sku_id|text|Y|SKU-NNNNNN||Y|format ^SKU-\\d{6}$
name|text|Y|||N|non-empty
category|text|Y|10 categories||N|enum
subcategory|text|Y|||N|non-empty
unit_cost|real|Y|>0|currency|N|unit_cost < unit_price
unit_price|real|Y|>0|currency|N|list price
volume_per_unit|real|Y|>0|volume units|N|>0
launch_date|date|Y|ISO date||N|no sales before this date
discontinue_date|date|N|ISO date||N|> launch_date; no sales / recommendations on or after it
status|text|Y|PLANNED,ACTIVE,DISCONTINUED||N|status as of end of history; consistent with dates & status_event
""", cardinality="SKU N:M Store (store_sku), SKU N:M Supplier (supplier_sku)", lifecycle="PLANNED -> ACTIVE -> DISCONTINUED (terminal)")

table("supplier_sku", "Bridge Supplier<->SKU (N:M), effective dated: pack size, MOQ, cost and lead-time distribution.",
      ["supplier_id", "sku_id", "effective_from"], [(["supplier_id"], "supplier", ["supplier_id"]), (["sku_id"], "sku", ["sku_id"])], """
supplier_id|text|Y|FK supplier||N|exists in supplier
sku_id|text|Y|FK sku||N|exists in sku
effective_from|date|Y|ISO date||N|PK part
effective_to|date|N|ISO date||N|NULL=open ended; effective_from < effective_to
pack_size|int|Y|>=1|units/case|N|orders must be multiples
moq|int|Y|>=pack_size|units|N|minimum order quantity (multiple of pack_size)
unit_cost|real|Y|>0|currency|N|>0
mean_lead_time_days|real|Y|>0|days|N|planning mean
lead_time_sd|real|Y|>0|days|N|planning std-dev
is_primary|bool|Y|0,1||N|exactly one primary per SKU at any date
status|text|Y|ACTIVE,CLOSED||N|CLOSED when effective_to < end of history
""", cardinality="1:N LeadTimeObservation (by supplier+sku)", lifecycle="versioned by effective dates; rows are closed, never edited")

table("store_sku", "Assortment matrix: which SKU each store lists (Store N:M SKU bridge).", ["store_id", "sku_id"],
      [(["store_id"], "store", ["store_id"]), (["sku_id"], "sku", ["sku_id"])], """
store_id|text|Y|FK store||N|exists in store
sku_id|text|Y|FK sku||N|exists in sku
listed_from|date|Y|ISO date||N|<= first sale
listed_to|date|N|ISO date||N|NULL=still listed
status|text|Y|PLANNED,ACTIVE,DELISTED||N|enum
""", cardinality="parent of SalesHistory, InventorySnapshot, Forecast, ReorderPolicy, PurchaseRecommendation (1:N each)")

table("sales_history", "Daily sales per SKU-store (grain: store, sku, date). Stockouts are flagged separately from zero demand; "
      "latent demand is NOT in this table (see ground_truth/censored_demand.csv).", ["sale_id"],
      [(["store_id", "sku_id"], "store_sku", ["store_id", "sku_id"])], """
sale_id|text|Y|SALE-<store-id>-<sku>-<date>||Y|format ^SALE-STORE-\\d{6}-SKU-\\d{6}-\\d{4}-\\d{2}-\\d{2}$; = f(store,sku,date)
store_id|text|Y|FK store_sku||N|exists in store_sku
sku_id|text|Y|FK store_sku||N|exists in store_sku
date|date|Y|ISO date||N|launch<=date<discontinue
units_sold|int|Y|>=0|units|N|<= on_hand_start+receipts
on_promo|bool|Y|0,1||N|1 iff promo_depth>0
promo_depth|real|Y|0-0.5|fraction|N|price cut
price|real|Y|>0|currency|N|unit_price*(1-promo_depth)
net_revenue|real|Y|>=0|currency|N|derived: units_sold*price
stockout_flag|bool|Y|0,1||N|1 = shelf empty / demand exceeded stock (units_sold is CENSORED)
""", cardinality="StoreSKU 1:N SalesHistory", grain="one row per store-sku-day; row exists only while the SKU is alive in that store")

table("inventory_snapshot", "Daily closing inventory balance per SKU-store; reconciles with sales and receipts.", ["snapshot_id"],
      [(["store_id", "sku_id"], "store_sku", ["store_id", "sku_id"])], """
snapshot_id|text|Y|INV-<store-id>-<sku>-<date>||Y|format ^INV-...; = f(store,sku,date)
store_id|text|Y|FK store_sku||N|exists in store_sku
sku_id|text|Y|FK store_sku||N|exists in store_sku
date|date|Y|ISO date||N|same grain as sales_history
on_hand_start|int|Y|>=0|units|N|= previous day's on_hand (opening stock on first day)
receipts|int|Y|>=0|units|N|= sum(units_received) of lead_time_observation by receipt_date
on_hand|int|Y|>=0|units|N|= on_hand_start + receipts - units_sold
on_order|int|Y|>=0|units|N|ordered, not yet shipped
in_transit|int|Y|>=0|units|N|shipped, not yet received
stockout_flag|bool|Y|0,1||N|identical to sales_history.stockout_flag
""", cardinality="StoreSKU 1:N InventorySnapshot")

table("lead_time_observation", "Observed deliveries (one per received order line). lead_time_days = receipt_date - order_date.", ["lt_obs_id"],
      [(["supplier_id"], "supplier", ["supplier_id"]), (["sku_id"], "sku", ["sku_id"]), (["store_id", "sku_id"], "store_sku", ["store_id", "sku_id"])], """
lt_obs_id|text|Y|LT-NNNNNNN||Y|format ^LT-\\d{7}$
supplier_id|text|Y|FK supplier||N|exists
sku_id|text|Y|FK sku||N|exists
store_id|text|Y|FK store_sku||N|exists
order_date|date|Y|ISO date||N|<= receipt_date
receipt_date|date|Y|ISO date||N|>= order_date
lead_time_days|int|Y|>=0|days|N|derived = receipt_date - order_date
units_received|int|Y|>=0|units|N|reconciles with inventory receipts
delay_flag|bool|Y|0,1||N|1 iff lead_time_days > ceil(mean+2*sd) of the supplier_sku terms
source|text|Y|RECEIPT,MANUAL_ENTRY||N|enum
""", cardinality="SupplierSKU 1:N LeadTimeObservation")

table("forecast", "Month-ahead demand forecast per SKU-store (ID suffix = forecast month).", ["forecast_id"],
      [(["store_id", "sku_id"], "store_sku", ["store_id", "sku_id"])], """
forecast_id|text|Y|FC-<store-id>-<sku>-YYYY-MM||Y|format ^FC-STORE-\\d{6}-SKU-\\d{6}-\\d{4}-\\d{2}$
store_id|text|Y|FK store_sku||N|exists
sku_id|text|Y|FK store_sku||N|exists
forecast_month|text|Y|YYYY-MM||N|matches id suffix
period_start|date|Y|ISO date||N|first day of forecast_month
period_end|date|Y|ISO date||N|last day of forecast_month
method|text|Y|HYBRID_SES,HYBRID_SBA,COHORT_BLEND,COHORT_FALLBACK||N|enum
segment|text|Y|SMOOTH,ERRATIC,INTERMITTENT,LUMPY,NEW||N|Syntetos-Boylan class
horizon_days|int|Y|>0|days|N|period_end-period_start+1
forecast_units|real|Y|>=0|units|N|sum over period
daily_rate|real|Y|>=0|units/day|N|forecast_units/horizon_days
lower|real|Y|>=0|units|N|<= forecast_units
upper|real|Y|>=0|units|N|>= forecast_units
training_cutoff_date|date|Y|ISO date||N|MUST be < period_start (leakage guard)
confidence|text|Y|NORMAL,LOW_CONFIDENCE||N|enum
""", cardinality="StoreSKU 1:N Forecast (one per month)")

table("reorder_policy", "Effective-dated reorder policy versions (old versions are closed, never overwritten).", ["policy_id"],
      [(["store_id", "sku_id"], "store_sku", ["store_id", "sku_id"]), (["supplier_id"], "supplier", ["supplier_id"])], """
policy_id|text|Y|POL-NNNNNNN||Y|format ^POL-\\d{7}$
store_id|text|Y|FK store_sku||N|exists
sku_id|text|Y|FK store_sku||N|exists
supplier_id|text|Y|FK supplier||N|exists
version|int|Y|>=1||N|increments per store-sku
service_level|real|Y|0.5-0.999|probability|N|by demand segment
z|real|Y|>0||N|inverse normal CDF of service_level
review_period_days|int|Y|>0|days|N|R
mean_lead_time_days|real|Y|>0|days|N|L (observed if >=5 valid obs, else planning)
lead_time_sd|real|Y|>=0|days|N|sigma_L
lead_time_source|text|Y|OBSERVED,PLANNING||N|provenance of L
daily_demand_est|real|Y|>=0|units/day|N|d_hat from forecast
demand_sd|real|Y|>=0|units/day|N|sigma_d (in-stock days)
safety_stock|real|Y|>=0|units|N|z*sqrt(L*sd^2+d^2*sdL^2)
reorder_point|real|Y|>=0|units|N|d*L+SS
order_up_to|real|Y|>=0|units|N|d*(L+R)+SS
segment|text|Y|SMOOTH,ERRATIC,INTERMITTENT,LUMPY,NEW||N|enum
effective_from|date|Y|ISO date||N|<effective_to
effective_to|date|N|ISO date||N|NULL = current
computed_from_cutoff|date|Y|ISO date||N|data cutoff used (< effective_from)
status|text|Y|ACTIVE,SUPERSEDED||N|one ACTIVE per store-sku
""", cardinality="StoreSKU 1:N ReorderPolicy over time, exactly 1 active at a time", lifecycle="ACTIVE -> SUPERSEDED (status_event)")

table("purchase_recommendation", "Recommended purchase order with full lineage (forecast, policy, supplier) and reason code.", ["po_id"],
      [(["store_id", "sku_id"], "store_sku", ["store_id", "sku_id"]), (["supplier_id"], "supplier", ["supplier_id"]),
       (["forecast_id"], "forecast", ["forecast_id"]), (["policy_id"], "reorder_policy", ["policy_id"])], """
po_id|text|Y|PO-YYYY-NNNNNN||Y|format ^PO-\\d{4}-\\d{6}$; numbered after sorting by store,sku
store_id|text|Y|FK store_sku||N|exists
sku_id|text|Y|FK store_sku||N|exists
supplier_id|text|N|FK supplier||N|NULL only if SKU never had a supplier
forecast_id|text|N|FK forecast||N|NULL when blocked before forecasting
policy_id|text|N|FK reorder_policy||N|NULL when blocked before policy
raw_qty|real|Y|>=0|units|N|max(0, order_up_to - inventory_position)
recommended_qty|int|Y|>=0|units|N|multiple of pack_size, >= moq, within capacity (0 when BLOCKED)
pack_size|int|N|>=1|units|N|from supplier_sku effective at created_at
moq|int|N|>=1|units|N|from supplier_sku effective at created_at
inventory_position|int|N|>=0|units|N|on_hand+on_order+in_transit at cutoff
reorder_point|real|N|>=0|units|N|from policy
order_up_to|real|N|>=0|units|N|from policy
unit_cost|real|N|>0|currency|N|from supplier_sku
order_value|real|Y|>=0|currency|N|recommended_qty*unit_cost
expected_lead_time_days|real|N|>0|days|N|from policy
reason_code|text|Y|REORDER_POINT,CAPACITY_REDUCED,CAPACITY,MOQ_CONFLICT,DISCONTINUED_SKU,NOT_YET_LAUNCHED,NO_VALID_SUPPLIER,INVALID_LEAD_TIME||N|enum
status|text|Y|DRAFT,APPROVED,BLOCKED,CANCELLED||N|status AT CREATION; later transitions live in status_event
confidence|text|N|NORMAL,LOW_CONFIDENCE||N|from forecast
created_at|text|Y|ISO timestamp||N|date part is the as-of date
""", cardinality="Forecast 1:N PurchaseRecommendation (optional), ReorderPolicy 1:N PurchaseRecommendation (optional)",
      lifecycle="DRAFT -> APPROVED | CANCELLED (events); BLOCKED is terminal")

table("status_event", "Append-only lifecycle history for SKU, ReorderPolicy and PurchaseRecommendation (nothing is overwritten).", ["event_id"], [], """
event_id|text|Y|EVT-NNNNNNN||Y|format ^EVT-\\d{7}$
entity_type|text|Y|SKU,REORDER_POLICY,PURCHASE_RECOMMENDATION||N|enum
entity_id|text|Y|||N|id of the entity in its own table
old_status|text|N|||N|NULL on creation
new_status|text|Y|||N|legal transition from old_status
event_date|date|Y|ISO date||N|non-decreasing per entity
reason|text|Y|||N|business reason
""", cardinality="polymorphic 1:N from SKU / ReorderPolicy / PurchaseRecommendation")

table("exception_log", "Operations exception list derived from the recommendation run (blocked / reduced / low-confidence / invalid lead time).", ["exception_id"], [], """
exception_id|text|Y|EXC-NNNNNN||Y|format
exception_code|text|Y|||N|BLOCKED_RECOMMENDATION, REDUCED_RECOMMENDATION, LOW_CONFIDENCE_FORECAST, INVALID_LEAD_TIME_EXCLUDED
entity_type|text|Y|||N|polymorphic
entity_id|text|Y|||N|id of the entity
store_id|text|N|||N|context
sku_id|text|N|||N|context
reason_code|text|Y|||N|reason
detail|text|Y|||N|human readable
severity|text|Y|HIGH,MEDIUM,LOW||N|enum
""", cardinality="derived output")

ORDER = ["supplier", "store", "sku", "supplier_sku", "store_sku", "sales_history", "inventory_snapshot", "lead_time_observation",
         "status_event", "forecast", "reorder_policy", "purchase_recommendation", "exception_log"]
SQL_TYPE = {"text": "TEXT", "int": "INTEGER", "real": "REAL", "date": "TEXT", "bool": "INTEGER"}


def columns(name):
    return [c["name"] for c in T[name]["cols"]]


def enum_values(col):
    a = col["allowed"]
    if "," in a and not any(ch in a for ch in "<>=") and " " not in a.replace(", ", ",").strip().split(",")[0]:
        vals = [x.strip() for x in a.split(",")]
        if all(v.replace("_", "").isalnum() and v.upper() == v for v in vals):
            return vals
    return None


def ddl() -> str:
    out = ["-- Generated from src/schema.py. SQLite/PostgreSQL compatible. Dates are ISO-8601 text.",
           "-- NOTE: value CHECK constraints are intentionally omitted so labelled anomaly rows can load;",
           "-- they are detected by the validation suite (src/validate.py) instead.", "PRAGMA foreign_keys = ON;", ""]
    for name in ORDER:
        t = T[name]
        lines = []
        for c in t["cols"]:
            lines.append(f"  {c['name']} {SQL_TYPE[c['type']]}{' NOT NULL' if c['required'] else ''}")
        lines.append(f"  PRIMARY KEY ({', '.join(t['pk'])})")
        for cols, parent, pcols in t["fks"]:
            lines.append(f"  FOREIGN KEY ({', '.join(cols)}) REFERENCES {parent} ({', '.join(pcols)})")
        out.append(f"CREATE TABLE {name} (\n" + ",\n".join(lines) + "\n);\n")
    return "\n".join(out)


def data_dictionary_md() -> str:
    md = ["# Data dictionary", "", "Generated from `src/schema.py` (the same spec drives validation and the SQL DDL).",
          "Types: text, int, real, date (ISO-8601), bool (0/1). IDs follow the conventions in `src/ids.py`.", ""]
    for name in ORDER:
        t = T[name]
        md += [f"## {name}", "", t["desc"], "", f"- **Primary key:** `{', '.join(t['pk'])}`"]
        if t["fks"]:
            md.append("- **Foreign keys:** " + "; ".join(f"`({', '.join(c)})` -> `{p}({', '.join(pc)})`" for c, p, pc in t["fks"]))
        if t["grain"]:
            md.append(f"- **Grain:** {t['grain']}")
        if t["cardinality"]:
            md.append(f"- **Cardinality:** {t['cardinality']}")
        if t["lifecycle"]:
            md.append(f"- **Lifecycle:** {t['lifecycle']}")
        md += ["", "| field | type | required | allowed values / format | unit | unique | validation rule |", "|---|---|---|---|---|---|---|"]
        for c in t["cols"]:
            md.append(f"| `{c['name']}` | {c['type']} | {'Y' if c['required'] else 'N'} | {c['allowed'] or '-'} | {c['unit'] or '-'} | "
                      f"{'Y' if (c['unique'] or t['pk'] == [c['name']]) else 'N'} | {c['rule'] or '-'} |")
        md.append("")
    return "\n".join(md)


def erd_mermaid() -> str:
    lines = ["```mermaid", "erDiagram"]
    rel = [("supplier", "supplier_sku", "||--o{"), ("sku", "supplier_sku", "||--o{"), ("store", "store_sku", "||--o{"),
           ("sku", "store_sku", "||--o{"), ("store_sku", "sales_history", "||--o{"), ("store_sku", "inventory_snapshot", "||--o{"),
           ("supplier", "lead_time_observation", "||--o{"), ("store_sku", "lead_time_observation", "||--o{"),
           ("store_sku", "forecast", "||--o{"), ("store_sku", "reorder_policy", "||--o{"), ("supplier", "reorder_policy", "||--o{"),
           ("forecast", "purchase_recommendation", "|o--o{"), ("reorder_policy", "purchase_recommendation", "|o--o{"),
           ("supplier", "purchase_recommendation", "|o--o{"), ("store_sku", "purchase_recommendation", "||--o{")]
    for a, b, r in rel:
        lines.append(f"  {a} {r} {b} : has")
    for name in ORDER:
        lines.append(f"  {name} {{")
        for c in T[name]["cols"][:6]:
            lines.append(f"    {c['type']} {c['name']}")
        lines.append("  }")
    lines.append("```")
    return "\n".join(lines)
