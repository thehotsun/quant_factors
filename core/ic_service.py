"""IC computation service helpers."""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

MONTHLY_SOURCES = {"cpi", "pmi", "m2", "social_financing", "us_cpi"}


def _resolve_ic_price_dep(cfg: Dict[str, Any]) -> str:
    """Resolve the price dep for IC computation.

    For mixed chains, prefer execution_asset matching dep.
    For regular chains, use data_deps[0].
    """
    deps = cfg.get("data_deps", [])
    if not deps:
        return ""
    execution_asset = cfg.get("execution_asset", "")
    if execution_asset:
        for dep in deps:
            if execution_asset in dep or dep.endswith(f"_{execution_asset}"):
                return dep
    trade_asset = cfg.get("trade_asset", "")
    if trade_asset:
        for dep in deps:
            if dep in trade_asset or trade_asset in dep:
                return dep
    return deps[0]


def compute_daily_ic(
    chains_config: Dict[str, Dict[str, Any]],
    data_bus,
    ic_monitor,
    ensure_imported,
) -> int:
    """Compute daily IC records for non-composite, price-backed chains.

    Monthly macro sources are skipped here because their availability date needs a
    different calendar-aware evaluation path.
    """
    logger.info("开始每日 IC 计算...")
    ensure_imported()

    computed = 0
    for chain_name, cfg in chains_config.items():
        if cfg.get("category") == "composite":
            continue
        data_deps = cfg.get("data_deps", [])
        if not data_deps:
            continue
        dep_name = _resolve_ic_price_dep(cfg)
        if dep_name in MONTHLY_SOURCES:
            continue
        price_df = data_bus.get(dep_name)
        if price_df is None or len(price_df) < 20:
            continue
        try:
            result = ic_monitor.compute_ic(chain_name, price_df)
            if result:
                computed += 1
        except Exception as e:
            logger.warning("  %s IC 计算失败: %s", chain_name, e)

    logger.info("每日 IC 计算完成，共计算 %d 个因子", computed)
    return computed
