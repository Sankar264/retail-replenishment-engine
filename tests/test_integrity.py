from src import schema
from tests.helpers import result


def test_baseline_has_zero_structural_violations():
    r = result()
    assert r["base"]["summary"]["structural_violations"] == 0, r["base"]["summary"]["failed_structural_checks"]
    assert sum(r["base"]["summary"]["anomaly_detector_violations"].values()) == 0


def test_injection_does_not_corrupt_unrelated_rows():
    r = result()
    assert r["inj"]["summary"]["structural_violations"] == 0, r["inj"]["summary"]["failed_structural_checks"]


def test_all_pk_and_fk_checks_present_for_every_entity():
    names = {c["check"] for c in result()["base"]["checks"]}
    for t in schema.ORDER:
        assert f"pk_unique:{t}" in names
        for cols, parent, _ in schema.T[t]["fks"]:
            assert f"fk:{t}({','.join(cols)})->{parent}" in names


def test_reconciliation_checks_ran_and_pass():
    checks = {c["check"]: c for c in result()["base"]["checks"]}
    for k in ["reconcile.on_hand=start+receipts-sold", "reconcile.receipts=sum(lead_time_observation.units)",
              "reconcile.lead_time_days=receipt-order", "reconcile.opening_balance=previous_closing"]:
        assert checks[k]["rows_checked"] > 0 and checks[k]["violations"] == 0, k


def test_sql_seed_loads_with_foreign_keys():
    import sqlite3
    out = result()["out_dir"]
    con = sqlite3.connect(":memory:")
    con.executescript((out / "sql" / "seed.sql").read_text(encoding="utf-8"))
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    n = con.execute("select count(*) from sales_history").fetchone()[0]
    assert n == len(result()["tables"]["sales_history"])
