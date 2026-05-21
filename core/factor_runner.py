"""Factor execution service.

This module keeps the API layer thin: importing factor modules, building factor
instances, normalizing outputs, logging signals, and recording IC snapshots live
here instead of in server.py.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


FACTOR_VALUE_KEYS = [
    "factor_value", "zscore", "zscore_20d", "ratio", "pig_grain_ratio", "egg_feed_ratio",
    "pig_chicken_ratio", "copper_gold_ratio", "oil_gas_ratio", "iron_rebar_ratio",
    "score", "momentum_score", "value", "change", "spread", "margin", "crush_margin",
    "diff", "divergence", "current_price", "current", "current_cpi", "current_pmi",
    "latest", "cpi_actual", "cbot_soybean", "vix_current", "usd_cny",
    "domestic_soybean", "iron_ore_price", "feed_cost_index", "m2_yoy", "sf_growth",
    "pmi", "cost_per_jin", "vol_ratio", "seasonal_avg_return", "seasonal_win_rate",
]

FACTOR_IMPORTS = [
    "factors.meat.pork",
    "factors.feed.soybean_meal",
    "factors.feed.corn",
    "factors.feed.soybean",
    "factors.feed.rapeseed_meal",
    "factors.cross.pig_grain_ratio",
    "factors.cross.feed_cost",
    "factors.cross.crush_margin",
    "factors.cross.pig_chicken_spread",
    "factors.cross.egg_feed_ratio",
    "factors.cross.copper_gold_ratio",
    "factors.cross.oil_gold_link",
    "factors.cross.forex_commodity",
    "factors.cross.pmi_metals",
    "factors.macro.cpi",
    "factors.macro.cpi_gold",
    "factors.macro.pmi",
    "factors.macro.forex",
    "factors.macro.money_supply",
    "factors.macro.cbot",
    "factors.macro.social_financing",
    "factors.macro.vix",
    "factors.energy.energy",
    "factors.energy.oil_assets",
    "factors.metals.metals",
    "factors.metals.silver",
    "factors.metals.iron_ore",
    "factors.cross.iron_rebar_cost",
    "factors.technical.momentum",
    "factors.technical.volatility",
    "factors.technical.term_structure",
    "factors.technical.seasonality",
]


def extract_factor_value(data: Any, factor_name: str = "unknown") -> Optional[float]:
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if not isinstance(data, dict):
        return None

    for key in FACTOR_VALUE_KEYS:
        if key in data and data[key] is not None:
            try:
                if key != "factor_value":
                    logger.debug(
                        "因子 %s 未使用 'factor_value' 字段，通过 fallback key '%s' 提取因子值。",
                        factor_name, key,
                    )
                return float(data[key])
            except (ValueError, TypeError):
                continue
    return None


def normalize_factor_data(data: Any, factor_name: str = "unknown") -> Any:
    """Attach a stable factor_value field without discarding legacy fields."""
    if not isinstance(data, dict):
        return data
    result = dict(data)
    if result.get("factor_value") is None:
        result["factor_value"] = extract_factor_value(result, factor_name)
    return result


class FactorRunner:
    def __init__(self, chains_config: Dict[str, Dict[str, Any]], factor_params: Dict[str, Any],
                 data_dir, signal_logger, ic_monitor):
        self.chains_config = chains_config
        self.factor_params = factor_params or {}
        self.data_dir = data_dir
        self.signal_logger = signal_logger
        self.ic_monitor = ic_monitor
        self._imported = False

    def ensure_imported(self):
        if self._imported:
            return
        for module_name in FACTOR_IMPORTS:
            importlib.import_module(module_name)
        self._imported = True

    def instantiate(self, chain_name: str):
        cfg = self.chains_config.get(chain_name)
        if not cfg:
            return None
        module_path = cfg.get("factor_module")
        class_name = cfg.get("factor_class")
        if not module_path or not class_name:
            return None
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            factor_cfg = self.factor_params.get(chain_name, {})
            kwargs = {
                "data_dir": str(self.data_dir),
                "adaptive": factor_cfg.get("adaptive", True),
                "params": factor_cfg.get("params", {}),
            }
            for key in ("symbol", "far_symbol"):
                if key in cfg:
                    kwargs[key] = cfg[key]
            return cls(**kwargs)
        except Exception as e:
            logger.warning("实例化因子 %s 失败: %s", chain_name, e)
            return None

    def run_chain(self, chain_name: str) -> Optional[Dict[str, Any]]:
        factor = self.instantiate(chain_name)
        if factor is None:
            return None
        try:
            data = normalize_factor_data(factor.calculate(), chain_name)
        except Exception as e:
            logger.error("因子 %s calculate 失败: %s", chain_name, e)
            return {
                "factor_data": None,
                "opportunity": None,
                "signal_strength": None,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        factor._cached_data = data
        try:
            signal = factor.signal()
        except Exception as e:
            logger.error("因子 %s signal 失败: %s", chain_name, e)
            signal = None

        strength = None
        if hasattr(factor, "signal_strength"):
            try:
                strength = factor.signal_strength()
            except Exception as e:
                logger.warning("因子 %s signal_strength 计算失败: %s", chain_name, e)

        self.signal_logger.log(chain_name, signal, strength, data)

        if data is not None:
            try:
                fv = extract_factor_value(data, chain_name)
                if fv is not None:
                    self.ic_monitor.snapshot(chain_name, fv, strength)
                else:
                    logger.debug("因子 %s 无有效因子值，跳过 IC 快照", chain_name)
            except Exception as e:
                logger.warning("因子 %s IC快照失败: %s", chain_name, e)

        return {
            "factor_data": data,
            "opportunity": signal,
            "signal_strength": strength,
        }
