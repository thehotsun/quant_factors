"""Composite factor-chain execution service.

Keeps Flask route handlers thin by running configured sub-chains, collecting
per-chain results, and aggregating active signals in one reusable place.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
from typing import Any, Callable, Dict

from core.signal_aggregator import SignalAggregator

logger = logging.getLogger(__name__)


def run_composite_chain(
    chain_name: str,
    chains_config: Dict[str, Dict[str, Any]],
    run_factor_chain: Callable[[str], Dict[str, Any] | None],
    ensure_imported: Callable[[], None] | None = None,
) -> Dict[str, Any]:
    """Run a composite chain and return the JSON-serializable payload.

    The returned shape intentionally matches the previous ``server._run_composite_chain``
    response so existing API consumers and push formatting remain compatible.
    """
    if ensure_imported is not None:
        ensure_imported()

    cfg = chains_config.get(chain_name, {})
    sub_chains = cfg.get("sub_chains", [])
    description = cfg.get("description", "")
    results: Dict[str, Dict[str, Any]] = {}
    signals = []

    if sub_chains:
        with ThreadPoolExecutor(max_workers=min(8, len(sub_chains))) as executor:
            future_map = {executor.submit(run_factor_chain, name): name for name in sub_chains}
            for future in as_completed(future_map):
                chain_name_item = future_map[future]
                try:
                    result = future.result()
                    if result:
                        results[chain_name_item] = {
                            "description": chains_config.get(chain_name_item, {}).get("description", ""),
                            "factor_data": result["factor_data"],
                            "opportunity": result["opportunity"],
                            "signal_strength": result.get("signal_strength"),
                        }
                        if result.get("error"):
                            results[chain_name_item]["error"] = result["error"]
                            results[chain_name_item]["error_type"] = result.get("error_type")
                        if result["opportunity"]:
                            sig = dict(result["opportunity"])
                            sig["_chain"] = chain_name_item
                            signals.append(sig)
                    else:
                        logger.warning("综合链子链条 %s 返回None（因子实例化失败或chains.yaml配置错误）", chain_name_item)
                        results[chain_name_item] = {"error": "因子实例化失败", "error_type": "InstantiationError"}
                except Exception as e:
                    results[chain_name_item] = {"error": str(e), "error_type": type(e).__name__}

    aggregated = SignalAggregator.aggregate(signals, method="weighted") if signals else None
    all_failed = len(results) > 0 and all(r.get("error") for r in results.values())

    return {
        "chain": chain_name,
        "description": description,
        "active_signals": signals,
        "signal_count": len(signals),
        "aggregated_signal": aggregated,
        "all_results": results,
        "all_sub_chains_failed": all_failed,
        "error": "所有子链条均计算失败" if all_failed else None,
        "timestamp": datetime.now().isoformat(),
    }
