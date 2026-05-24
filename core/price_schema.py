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
    "vix", "chicken_spot", "pork_spot", "gold_spot", "silver_spot",
    "copper_spot", "corn_spot", "soybean_meal_spot",
    "egg_spot", "soybean_oil_spot", "rapeseed_meal_spot", "rebar_spot", "iron_ore_spot",
    "aluminum_spot", "soybean_domestic_spot",
    "breeding_etf", "gold_etf", "petrochina_stock",
}
KNOWN_MISSING_PRICE_DATA = {"chicken_spot"}

# Dataset kind is intentionally separate from price schema:
# - futures: tradeable futures/continuous contracts; Chinese futures may receive roll-gap adjustment.
# - spot: cash/physical spot prices; no roll-gap adjustment, close_raw == close_adj.
# - equity: stocks/ETFs/index-like trade assets; no futures roll adjustment.
# - macro: non-tradeable macro observations, usually not OHLC price data.
DATASET_KINDS = {
    "pork_futures": "futures", "pork_futures_far": "futures", "egg_futures": "futures",
    "soybean_meal_futures": "futures", "corn_futures": "futures",
    "soybean_domestic_futures": "futures", "soybean_import_futures": "futures",
    "rapeseed_meal_futures": "futures", "soybean_oil_futures": "futures",
    "crude_oil_futures": "futures", "thermal_coal_futures": "futures",
    "copper_futures": "futures", "aluminum_futures": "futures", "rebar_futures": "futures",
    "gold_futures": "futures", "silver_futures": "futures", "iron_ore_futures": "futures",
    "natural_gas_futures": "futures", "brent_oil": "futures", "cbot_soybean": "futures",
    "chicken_spot": "spot", "pork_spot": "spot", "gold_spot": "spot", "silver_spot": "spot",
    "copper_spot": "spot", "corn_spot": "spot", "soybean_meal_spot": "spot",
    "egg_spot": "spot", "soybean_oil_spot": "spot", "rapeseed_meal_spot": "spot",
    "rebar_spot": "spot", "iron_ore_spot": "spot",
    "aluminum_spot": "spot", "soybean_domestic_spot": "spot",
    "vix": "macro",
    "breeding_etf": "equity", "gold_etf": "equity", "petrochina_stock": "equity",
}


def get_data_kind(dataset_name: str) -> str:
    if dataset_name in DATASET_KINDS:
        return DATASET_KINDS[dataset_name]
    if dataset_name.endswith("_spot"):
        return "spot"
    if dataset_name.endswith("_futures") or dataset_name.endswith("_futures_far"):
        return "futures"
    if dataset_name.endswith("_etf") or dataset_name.endswith("_stock") or dataset_name.endswith("_equity"):
        return "equity"
    return "unknown"


def flatten_driver_dependencies(drivers: Dict[str, Any]) -> List[str]:
    deps: List[str] = []
    if not isinstance(drivers, dict):
        return deps
    for group in drivers.values():
        if isinstance(group, list):
            deps.extend(str(item) for item in group)
        elif isinstance(group, dict):
            for value in group.values():
                if isinstance(value, list):
                    deps.extend(str(item) for item in value)
                elif value:
                    deps.append(str(value))
        elif group:
            deps.append(str(group))
    return deps
REQUIRED_PRICE_COLUMNS = {"date", "close"}
EXPLICIT_PRICE_COLUMNS = {"close_raw", "close_adj", "return_raw", "return_adj"}

# Price column semantics:
#   close_raw  — Original unadjusted close from the data source.
#   close_adj  — Close after roll-gap adjustment (futures only; = close_raw for non-futures).
#   return_raw — Daily return from close_raw (use for P&L / backtest).
#   return_adj — Daily return from close_adj (use for z-score / valuation positioning).
#   close      — Backward-compatible alias; equals close_adj after DataBus processing.


def normalize_price_frame(df: "pd.DataFrame", dataset_name: str, is_futures: bool = False) -> "pd.DataFrame":
    """Add explicit price columns (close_raw/close_adj/return_raw/return_adj) to a price DataFrame.

    Call this BEFORE writing parquet so that downstream readers get explicit
    price semantics without relying on DataBus runtime injection.

    - For futures data with roll-gap adjustment: close_adj differs from close_raw.
    - For non-futures data: close_raw == close_adj (no adjustment).
    - Returns are computed from the respective close series.
    """
    import pandas as pd

    if df is None or df.empty or 'close' not in df.columns:
        return df

    result = df.copy()
    close = result['close'].astype(float)

    if 'close_raw' not in result.columns:
        result['close_raw'] = close
    if 'close_adj' not in result.columns:
        result['close_adj'] = close  # Will be overwritten by roll-gap adjustment if applicable
    if 'return_raw' not in result.columns:
        result['return_raw'] = result['close_raw'].pct_change()
    if 'return_adj' not in result.columns:
        result['return_adj'] = result['close_adj'].pct_change()

    return result


def is_price_like(dep_name: str) -> bool:
    return dep_name in PRICE_DATA_NAMES


def inspect_price_file(data_dir: Path, dep_name: str) -> Dict[str, Any]:
    path = Path(data_dir) / f"{dep_name}.parquet"
    item: Dict[str, Any] = {
        "name": dep_name,
        "path": str(path),
        "known_missing": dep_name in KNOWN_MISSING_PRICE_DATA,
        "data_kind": get_data_kind(dep_name),
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
        all_deps = list(cfg.get("data_deps", []) or []) + flatten_driver_dependencies(cfg.get("drivers", {}))
        for dep in all_deps:
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
