#!/usr/bin/env python3
"""Audit chain configuration, importability, data dependencies, and schema gaps."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.factor_runner import collect_factor_modules, normalize_factor_data  # noqa: E402
from core.data_bus import DataBus  # noqa: E402
from core.factor_registry import FactorRegistry  # noqa: E402
from core.price_schema import collect_price_dependencies, inspect_price_dependencies  # noqa: E402
from core.settings import load_chains_config  # noqa: E402
from core.chain_config import build_chain_definitions, check_metadata_consistency  # noqa: E402


REQUIRED_SIGNAL_KEYS = {"asset", "direction", "strength", "signal_strength", "reason", "confidence", "trigger", "meta"}
KNOWN_MISSING_DATA_DEPS = {
    "pig_chicken_spread": {"chicken_spot"},
}


def load_chains() -> Dict[str, Dict[str, Any]]:
    return load_chains_config()


def _compare_registry_metadata(chain_name: str, cfg: Dict[str, Any], item: Dict[str, Any]) -> int:
    """Record non-fatal metadata drift between registry and chains.yaml."""
    diffs = check_metadata_consistency({chain_name: cfg}, FactorRegistry.info)
    if diffs:
        item.setdefault("metadata_diffs", []).extend([
            {"field": d.field, "chains_yaml": d.yaml_value, "registry": d.registry_value}
            for d in diffs
        ])
    return len(diffs)


def audit_chains(run_calculate: bool = False) -> Dict[str, Any]:
    chains = load_chains()
    modules = collect_factor_modules(chains)
    report: Dict[str, Any] = {
        "summary": {
            "chains": len(chains),
            "factor_modules": len(modules),
            "errors": 0,
            "warnings": 0,
            "metadata_diffs": 0,
            "known_missing_deps": 0,
            "unexpected_missing_deps": 0,
            "fallback_factors": 0,
        },
        "modules": [],
        "price_schema": {
            "summary": {
                "price_dependencies": 0,
                "missing": 0,
                "invalid": 0,
                "legacy_close": 0,
                "explicit_price_columns": 0,
            },
            "items": [],
        },
        "chains": [],
    }

    price_deps = collect_price_dependencies(chains)
    report["price_schema"] = inspect_price_dependencies(ROOT / "data", price_deps)

    for module_name in modules:
        item = {"module": module_name, "ok": True, "error": None}
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - script diagnostics
            item["ok"] = False
            item["error"] = f"{type(exc).__name__}: {exc}"
            report["summary"]["errors"] += 1
        report["modules"].append(item)

    FactorRegistry.sync_from_chains(chains)

    DataBus.reset()
    for name, cfg in chains.items():
        item: Dict[str, Any] = {
            "chain": name,
            "category": cfg.get("category"),
            "ok": True,
            "warnings": [],
            "errors": [],
        }

        if cfg.get("category") == "composite":
            missing = [c for c in cfg.get("sub_chains", []) if c not in chains]
            if missing:
                item["ok"] = False
                item["errors"].append(f"missing sub_chains: {missing}")
            report["chains"].append(item)
            continue

        module_name = cfg.get("factor_module")
        class_name = cfg.get("factor_class")
        known_missing_deps = []
        unexpected_missing_deps = []
        for dep in cfg.get("data_deps", []):
            if not (ROOT / "data" / f"{dep}.parquet").exists():
                if dep in KNOWN_MISSING_DATA_DEPS.get(name, set()):
                    known_missing_deps.append(dep)
                else:
                    unexpected_missing_deps.append(dep)
        missing_deps = known_missing_deps + unexpected_missing_deps
        if known_missing_deps:
            item["known_missing_deps"] = known_missing_deps
        if unexpected_missing_deps:
            item["unexpected_missing_deps"] = unexpected_missing_deps

        if not module_name or not class_name:
            item["ok"] = False
            item["errors"].append("missing factor_module/factor_class")
        else:
            try:
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                kwargs = {"data_dir": str(ROOT / "data")}
                for key in ("symbol", "far_symbol"):
                    if key in cfg:
                        kwargs[key] = cfg[key]
                factor = cls(**kwargs)
                report["summary"]["metadata_diffs"] += _compare_registry_metadata(name, cfg, item)
            except Exception as exc:
                item["ok"] = False
                item["errors"].append(f"instantiate failed: {type(exc).__name__}: {exc}")
                factor = None

            if factor is not None and run_calculate:
                try:
                    data = normalize_factor_data(factor.calculate(), name)
                    if not isinstance(data, dict):
                        item["warnings"].append("calculate did not return dict")
                    elif data.get("factor_value") is None and not missing_deps:
                        item["warnings"].append("factor_value is missing or None")
                    # 检测 fallback 来源
                    fv_source = data.get("factor_value_source", "none") if isinstance(data, dict) else "none"
                    if fv_source.startswith("fallback:"):
                        item["warnings"].append(f"factor_value via {fv_source}")
                        report["summary"]["fallback_factors"] += 1
                    factor._cached_data = data
                    signal = factor.signal()
                    if signal is not None:
                        missing_keys = sorted(REQUIRED_SIGNAL_KEYS - set(signal.keys()))
                        if missing_keys:
                            item["warnings"].append(f"signal missing keys: {missing_keys}")
                except Exception as exc:
                    item["ok"] = False
                    item["errors"].append(f"calculate/signal failed: {type(exc).__name__}: {exc}")

        if known_missing_deps:
            item["warnings"].append(f"known missing data_deps files: {known_missing_deps}")
            report["summary"]["known_missing_deps"] += len(known_missing_deps)
        if unexpected_missing_deps:
            item["warnings"].append(f"unexpected missing data_deps files: {unexpected_missing_deps}")
            report["summary"]["unexpected_missing_deps"] += len(unexpected_missing_deps)

        if item["errors"]:
            report["summary"]["errors"] += len(item["errors"])
        if item["warnings"]:
            report["summary"]["warnings"] += len(item["warnings"])
        report["chains"].append(item)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit quant factor chain wiring and schemas.")
    parser.add_argument("--run-calculate", action="store_true", help="also run calculate()/signal() for each factor")
    parser.add_argument("--json", action="store_true", help="emit full JSON report")
    args = parser.parse_args()

    report = audit_chains(run_calculate=args.run_calculate)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print(
            f"chains={summary['chains']} factor_modules={summary['factor_modules']} "
            f"errors={summary['errors']} warnings={summary['warnings']} "
            f"metadata_diffs={summary.get('metadata_diffs', 0)} "
            f"known_missing_deps={summary.get('known_missing_deps', 0)} "
            f"unexpected_missing_deps={summary.get('unexpected_missing_deps', 0)} "
            f"fallback_factors={summary.get('fallback_factors', 0)}"
        )
        price_summary = report.get("price_schema", {}).get("summary", {})
        print(
            f"price_schema price_dependencies={price_summary.get('price_dependencies', 0)} "
            f"missing={price_summary.get('missing', 0)} invalid={price_summary.get('invalid', 0)} "
            f"legacy_close={price_summary.get('legacy_close', 0)} "
            f"explicit_price_columns={price_summary.get('explicit_price_columns', 0)}"
        )
        for item in report.get("price_schema", {}).get("items", []):
            if item.get("errors"):
                print(f"- PRICE {item['name']}")
                for msg in item.get("errors", []):
                    print(f"  ERROR: {msg}")
        for item in report["chains"]:
            if item.get("errors") or item.get("warnings") or item.get("metadata_diffs"):
                print(f"- {item['chain']} [{item.get('category')}]")
                for msg in item.get("errors", []):
                    print(f"  ERROR: {msg}")
                for msg in item.get("warnings", []):
                    print(f"  WARN: {msg}")
                for diff in item.get("metadata_diffs", []):
                    print(f"  META: {diff['field']} differs between chains.yaml and registry")
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
