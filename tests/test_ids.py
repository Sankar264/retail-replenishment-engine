import csv
from src import ids
from tests.helpers import result


def test_id_builders():
    assert ids.sku_id(1) == "SKU-000001"
    assert ids.store_id(42) == "STORE-000042"
    assert ids.sale_id("STORE-000042", "SKU-000007", "2026-03-15") == "SALE-STORE-000042-SKU-000007-2026-03-15"
    assert ids.forecast_id("STORE-000042", "SKU-000007", "2026-01") == "FC-STORE-000042-SKU-000007-2026-01"
    assert ids.po_id(1) == "PO-2026-000001"


def test_exported_ids_match_conventions():
    out = result().get("out_dir")
    checks = {"sku": ("sku_id", ids.SKU_RE), "store": ("store_id", ids.STORE_RE), "sales_history": ("sale_id", ids.SALE_RE),
              "inventory_snapshot": ("snapshot_id", ids.INV_RE), "forecast": ("forecast_id", ids.FC_RE),
              "purchase_recommendation": ("po_id", ids.PO_RE), "lead_time_observation": ("lt_obs_id", ids.LT_RE)}
    for table, (col, pat) in checks.items():
        with open(out / "tables" / f"{table}.csv", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                assert pat.match(row[col]), (table, row[col])


def test_po_numbering_is_sorted_and_sequential():
    po = result()["tables"]["purchase_recommendation"]
    assert list(po["po_id"]) == [ids.po_id(i + 1) for i in range(len(po))]
    keys = list(zip(po["store_id"], po["sku_id"]))
    assert keys == sorted(keys)
