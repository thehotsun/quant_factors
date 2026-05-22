"""Price data schema inspection helpers.

This module is deliberately observational: it reports current price schema and
legacy close usage without changing how factors read data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd


PRICE_DATA_NAMES = {
    "pork_futures", "pork_futures_far", "egg_futures",
    "soybean_meal_futures", "corn_futures", "soybean_domestic_futures",
    "soybean_import_futures", "rapeseed_meal_futures", "soybean_oil_futures",
    "crude_oil_futures", "thermal_coal_futures", "copper_futures",
    "aluminum_futures", "rebar_futures", "gold_futures", "silver_futures",
    "iron_ore_futures", "natural_gas_futures", "brent_oil", "cbot_soybean",
    "vix", "chicken_spot",
}
KNOWN_MISSING_PRICE_DATA = {"chicken_spot"}
REQUIRED_PRICE_COLUMNS = {"date", "close"}
EXPLICIT_PRICE_COLUMNS = {"close_raw", "close_adj", "return_raw", "return_adj"}


def is_price_like(dep_name: str) -> bool:
    return dep_name in PRICE_DATA_NAMES


def inspect_price_file(data_dir: Path, dep_name: str) -> Dict[str, Any]:
    path = Path(data_dir) / f"{dep_name}.parquet"
    item: Dict[str, Any] = {
        "name": dep_name,
        "path": str(path),
        "known_missing": dep_name in KNOWN_MISSING_PRICE_DATA,
        "exists": path.exists(),
        "ok": True,
        "schema": "missing",
        "warnings": [],
        "errors": [],
        "columns": [],
        "rows": 0,
    }
    if not path.exists():
        item["ok"] = not item["known_missing"]
        item["schema"] = "known_missing" if item["known_missing"] else "missing"
        if item["known_missing"]:
            item["warnings"].append("known missing parquet file")
        else:
            item["errors"].append("missing parquet file")
        return item

    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        item["ok"] = False
        item["errors"].append(f"read failed: {type(exc).__name__}: {exc}")
        return item

    item["columns"] = list(df.columns)
    item["rows"] = int(len(df))
    missing = sorted(REQUIRED_PRICE_COLUMNS - set(df.columns))
    if missing:
        item["ok"] = False
        item["errors"].append(f"missing required price columns: {missing}")
        item["schema"] = "invalid"
        return item

    explicit = sorted(EXPLICIT_PRICE_COLUMNS & set(df.columns))
    if explicit:
        item["schema"] = "explicit_price_columns"
        item["explicit_columns"] = explicit
    else:
        item["schema"] = "legacy_close"
        item["warnings"].append("price data uses legacy date/close schema without explicit price_mode")

    return item


def collect_price_dependencies(chains_config: Dict[str, Dict[str, Any]]) -> List[str]:
    deps = set()
    for cfg in chains_config.values():
        for dep in cfg.get("data_deps", []) or []:
            if is_price_like(dep):
                deps.add(dep)
    return sorted(deps)


def inspect_price_dependencies(data_dir: Path, deps: Iterable[str]) -> Dict[str, Any]:
    items = [inspect_price_file(data_dir, dep) for dep in sorted(set(deps))]
    return {
        "summary": {
            "price_dependencies": len(items),
            "missing": sum(1 for item in items if not item["exists"]),
            "known_missing": sum(1 for item in items if item.get("known_missing") and not item["exists"]),
            "unexpected_missing": sum(1 for item in items if not item.get("known_missing") and not item["exists"]),
            "invalid": sum(1 for item in items if item["exists"] and not item["ok"]),
            "legacy_close": sum(1 for item in items if item.get("schema") == "legacy_close"),
            "explicit_price_columns": sum(1 for item in items if item.get("schema") == "explicit_price_columns"),
        },
        "items": items,
    }
