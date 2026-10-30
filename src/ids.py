"""Deterministic ID builders - the ONLY place where ID formats are defined.

SKU-000001 | STORE-000001 | SALE-<store-id>-<sku>-<date> | FC-<store-id>-<sku>-2026-01 | PO-2026-000001
Counters are zero-padded and IDs are immutable. (Supporting entities follow the same style.)
"""
from __future__ import annotations

import re

import numpy as np

SKU_RE = re.compile(r"^SKU-\d{6}$")
STORE_RE = re.compile(r"^STORE-\d{6}$")
SUPPLIER_RE = re.compile(r"^SUP-\d{6}$")
SALE_RE = re.compile(r"^SALE-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}-\d{2}$")
INV_RE = re.compile(r"^INV-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}-\d{2}$")
FC_RE = re.compile(r"^FC-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}$")
PO_RE = re.compile(r"^PO-\d{4}-\d{6}$")
LT_RE = re.compile(r"^LT-\d{7}$")
POLICY_RE = re.compile(r"^POL-\d{7}$")


def sku_id(n: int) -> str:
    return f"SKU-{int(n):06d}"


def store_id(n: int) -> str:
    return f"STORE-{int(n):06d}"


def supplier_id(n: int) -> str:
    return f"SUP-{int(n):06d}"


def sale_id(store: str, sku: str, iso_date: str) -> str:
    return f"SALE-{store}-{sku}-{iso_date}"


def inventory_id(store: str, sku: str, iso_date: str) -> str:
    return f"INV-{store}-{sku}-{iso_date}"


def forecast_id(store: str, sku: str, year_month: str) -> str:
    return f"FC-{store}-{sku}-{year_month}"


def po_id(n: int, year: int = 2026) -> str:
    return f"PO-{year}-{int(n):06d}"


def lt_obs_id(n: int) -> str:
    return f"LT-{int(n):07d}"


def policy_id(n: int) -> str:
    return f"POL-{int(n):07d}"


def event_id(n: int) -> str:
    return f"EVT-{int(n):07d}"


def exception_id(n: int) -> str:
    return f"EXC-{int(n):06d}"


def _obj(a) -> np.ndarray:
    return np.asarray(a, dtype=object)


def sale_ids(stores, skus, dates) -> np.ndarray:
    return "SALE-" + _obj(stores) + "-" + _obj(skus) + "-" + _obj(dates)


def inventory_ids(stores, skus, dates) -> np.ndarray:
    return "INV-" + _obj(stores) + "-" + _obj(skus) + "-" + _obj(dates)


def forecast_ids(stores, skus, year_month: str) -> np.ndarray:
    return "FC-" + _obj(stores) + "-" + _obj(skus) + "-" + year_month
