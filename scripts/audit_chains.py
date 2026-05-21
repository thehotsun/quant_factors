#!/usr/bin/env python3
"""Audit chain configuration, importability, data dependencies, and schema gaps."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.factor_runner import collect_factor_modules, normalize_factor_data  # noqa: E402
from core.data_bus import DataBus  # noqa: E402


REQUIRED_SIGNAL_KEYS = {"asset", "direction", "strength", "signal_strength", "reason", "confidence", "trigger", "meta"}


def load_chains() -> Dict[str, Dict[str, Any]]:
    with open(ROOT / "config" / "chains.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["chains"]


def audit_chains(run_calculate: bool = False) -> Dict[str, Any]:
    chains = load_chains()
    modules = collect_factor_modules(chains)
    report: Dict[str, Any] = {
        "summary": {
            "chains": len(chains),
            "factor_modules": len(modules),
            "errors": 0,
            "warnings": 0,
        },
        "modules": [],
        "chains": [],
    }

    for module_name in modules:
        item = {"module": module_name, "ok": True, "error": None}
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - script diagnostics
            item["ok"] = False
            item["error"] = f"{type(exc).__name__}: {exc}"
            report["summary"]["errors"] += 1
        report["modules"].append(item)

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
            except Exception as exc:
                item["ok"] = False
                item["errors"].append(f"instantiate failed: {type(exc).__name__}: {exc}")
                factor = None

            if factor is not None and run_calculate:
                try:
                    data = normalize_factor_data(factor.calculate(), name)
                    if not isinstance(data, dict):
                        item["warnings"].append("calculate did not return dict")
                    elif data.get("factor_value") is None:
                        item["warnings"].append("factor_value is missing or None")
                    factor._cached_data = data
                    signal = factor.signal()
                    if signal is not None:
                        missing_keys = sorted(REQUIRED_SIGNAL_KEYS - set(signal.keys()))
                        if missing_keys:
                            item["warnings"].append(f"signal missing keys: {missing_keys}")
                except Exception as exc:
                    item["ok"] = False
                    item["errors"].append(f"calculate/signal failed: {type(exc).__name__}: {exc}")

        missing_deps = []
        for dep in cfg.get("data_deps", []):
            if not (ROOT / "data" / f"{dep}.parquet").exists():
                missing_deps.append(dep)
        if missing_deps:
            item["warnings"].append(f"missing data_deps files: {missing_deps}")

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
        print(f"chains={summary['chains']} factor_modules={summary['factor_modules']} errors={summary['errors']} warnings={summary['warnings']}")
        for item in report["chains"]:
            if item.get("errors") or item.get("warnings"):
                print(f"- {item['chain']} [{item.get('category')}]")
                for msg in item.get("errors", []):
                    print(f"  ERROR: {msg}")
                for msg in item.get("warnings", []):
                    print(f"  WARN: {msg}")
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
