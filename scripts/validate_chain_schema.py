#!/usr/bin/env python3
"""Validate chains.yaml against the mixed signal chain schema.

Exit code 0 = all OK; exit code 1 = errors found.
Warnings are printed but do not cause failure.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHAINS_PATH = ROOT / "config" / "chains.yaml"

VALID_DRIVER_GROUPS = {"spot", "futures", "macro", "equity", "technical"}
VALID_TRADE_ASSET_TYPES = {"etf", "stock", "futures", "basket", "index", ""}
VALID_CATEGORIES_NON_COMPOSITE = {
    "meat", "feed", "cross", "cross/system", "macro",
    "energy", "metals", "technical", "mixed", "uncategorized",
}


def validate_chain(name: str, cfg: Dict[str, Any]) -> tuple[List[str], List[str]]:
    """Return (errors, warnings) for a single chain."""
    errors: List[str] = []
    warnings: List[str] = []

    if cfg.get("category") == "composite":
        # Composite: only need sub_chains
        if not cfg.get("sub_chains"):
            errors.append(f"{name}: composite chain has no sub_chains")
        return errors, warnings

    # Non-composite must have factor module + class
    if not cfg.get("factor_module"):
        errors.append(f"{name}: missing factor_module")
    if not cfg.get("factor_class"):
        errors.append(f"{name}: missing factor_class")

    # Must have either data_deps or drivers
    has_data_deps = bool(cfg.get("data_deps"))
    has_drivers = bool(cfg.get("drivers"))
    if not has_data_deps and not has_drivers:
        errors.append(f"{name}: must have either data_deps or drivers")

    # Validate drivers structure
    drivers = cfg.get("drivers", {})
    if drivers:
        if not isinstance(drivers, dict):
            errors.append(f"{name}: drivers must be a dict")
        else:
            for group_name, group_deps in drivers.items():
                if group_name not in VALID_DRIVER_GROUPS:
                    errors.append(f"{name}: invalid driver group '{group_name}' (allowed: {VALID_DRIVER_GROUPS})")
                if not isinstance(group_deps, list):
                    errors.append(f"{name}: drivers.{group_name} must be a list")

    # Validate trade_asset_type
    trade_asset_type = cfg.get("trade_asset_type", "")
    if trade_asset_type not in VALID_TRADE_ASSET_TYPES:
        errors.append(f"{name}: invalid trade_asset_type '{trade_asset_type}' (allowed: {VALID_TRADE_ASSET_TYPES})")

    # Warn if drivers and data_deps are inconsistent
    if drivers and has_data_deps:
        driver_deps = set()
        for group_deps in drivers.values():
            if isinstance(group_deps, list):
                driver_deps.update(group_deps)
        yaml_deps = set(cfg.get("data_deps", []))
        missing_in_data_deps = driver_deps - yaml_deps
        missing_in_drivers = yaml_deps - driver_deps
        if missing_in_data_deps:
            warnings.append(f"{name}: deps in drivers but not in data_deps: {missing_in_data_deps}")
        if missing_in_drivers:
            warnings.append(f"{name}: deps in data_deps but not in drivers: {missing_in_drivers}")

    # Warn if trade_asset is missing
    if not cfg.get("trade_asset") and not cfg.get("asset"):
        warnings.append(f"{name}: no trade_asset or asset defined")

    return errors, warnings


def validate_all() -> tuple[int, int, int]:
    """Return (total_chains, error_count, warning_count)."""
    with open(CHAINS_PATH, "r", encoding="utf-8") as f:
        chains = yaml.safe_load(f)["chains"]

    total = len(chains)
    total_errors = 0
    total_warnings = 0

    for name, cfg in chains.items():
        errors, warnings = validate_chain(name, cfg or {})
        for e in errors:
            print(f"  ERROR: {e}")
            total_errors += 1
        for w in warnings:
            print(f"  WARN:  {w}")
            total_warnings += 1

    return total, total_errors, total_warnings


def main():
    print(f"Validating {CHAINS_PATH} ...")
    total, errors, warnings = validate_all()
    print(f"\n  chains: {total}, errors: {errors}, warnings: {warnings}")
    if errors > 0:
        print("  RESULT: FAIL")
        sys.exit(1)
    else:
        print("  RESULT: OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
