"""Factor execution service.

This module keeps the API layer thin: importing factor modules, building factor
instances, normalizing outputs, logging signals, and recording IC snapshots live
here instead of in server.py.
"""
from __future__ import annotations

import importlib
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

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

# Maps fallback key → factor_value_type for semantic clarity
_VALUE_TYPE_MAP = {
    "factor_value": None,  # already explicit
    "zscore": "zscore", "zscore_20d": "zscore",
    "ratio": "ratio", "pig_grain_ratio": "ratio", "egg_feed_ratio": "ratio",
    "pig_chicken_ratio": "ratio", "copper_gold_ratio": "ratio", "oil_gas_ratio": "ratio",
    "iron_rebar_ratio": "ratio",
    "score": "score", "momentum_score": "score",
    "value": "raw_value", "current_price": "raw_value", "current": "raw_value",
    "current_cpi": "raw_value", "current_pmi": "raw_value", "latest": "raw_value",
    "cpi_actual": "raw_value", "cbot_soybean": "raw_value", "vix_current": "raw_value",
    "usd_cny": "raw_value", "domestic_soybean": "raw_value", "iron_ore_price": "raw_value",
    "pmi": "raw_value",
    "change": "return", "diff": "spread", "spread": "spread", "margin": "spread",
    "crush_margin": "spread", "divergence": "spread",
    "m2_yoy": "yoy", "sf_growth": "yoy",
    "feed_cost_index": "index", "cost_per_jin": "cost",
    "vol_ratio": "ratio", "seasonal_avg_return": "return", "seasonal_win_rate": "percentile",
}

# Group keys by type for safe fallback (P0-1: prevent cross-dimension fallback)
_TYPE_KEY_GROUPS = {
    "zscore": ["zscore", "zscore_20d"],
    "ratio": ["ratio", "pig_grain_ratio", "egg_feed_ratio", "pig_chicken_ratio",
               "copper_gold_ratio", "oil_gas_ratio", "iron_rebar_ratio", "vol_ratio"],
    "score": ["score", "momentum_score"],
    "raw_value": ["value", "current_price", "current", "current_cpi", "current_pmi",
                    "latest", "cpi_actual", "cbot_soybean", "vix_current", "usd_cny",
                    "domestic_soybean", "iron_ore_price", "pmi"],
    "spread": ["diff", "spread", "margin", "crush_margin", "divergence"],
    "return": ["change", "seasonal_avg_return"],
    "yoy": ["m2_yoy", "sf_growth"],
    "index": ["feed_cost_index"],
    "cost": ["cost_per_jin"],
    "percentile": ["seasonal_win_rate"],
}


def collect_factor_modules(chains_config: Dict[str, Dict[str, Any]]) -> List[str]:
    """Return unique factor modules declared by chains.yaml in deterministic order.

    Composite chains do not have ``factor_module`` and are skipped.  This keeps
    module discovery tied to the runtime chain configuration instead of a second
    hard-coded import list.
    """
    modules: List[str] = []
    seen = set()
    for cfg in chains_config.values():
        module_name = cfg.get("factor_module")
        if not module_name or module_name in seen:
            continue
        seen.add(module_name)
        modules.append(module_name)
    return modules


def _find_fallback_key(data: dict, factor_name: str = "unknown") -> Optional[str]:
    """Find the first matching fallback key in data, preferring explicit factor_value."""
    if "factor_value" in data and data["factor_value"] is not None:
        return "factor_value"
    for key in FACTOR_VALUE_KEYS:
        if key in data and data[key] is not None:
            return key
    return None


def _find_same_type_fallback(data: dict, primary_key: str, factor_name: str = "unknown") -> Optional[str]:
    """Find a fallback key within the same type group as primary_key.

    P0-1 fix: prevent cross-dimension fallback (e.g. zscore -> current_price).
    """
    primary_type = _VALUE_TYPE_MAP.get(primary_key)
    if primary_type is None:
        # primary_key is "factor_value" (explicit), no fallback needed
        return primary_key
    group = _TYPE_KEY_GROUPS.get(primary_type, [])
    for key in group:
        if key in data and data[key] is not None:
            return key
    return None


def extract_factor_value(data: Any, factor_name: str = "unknown") -> Optional[float]:
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if not isinstance(data, dict):
        return None

    # Find the first available key
    primary_key = _find_fallback_key(data, factor_name)
    if primary_key is None:
        return None

    # If it's factor_value or we can get the type, try same-type fallback first
    primary_type = _VALUE_TYPE_MAP.get(primary_key)
    if primary_type is not None:
        # Try same-type fallback
        fallback_key = _find_same_type_fallback(data, primary_key, factor_name)
        if fallback_key is not None:
            try:
                if fallback_key != "factor_value":
                    logger.debug(
                        "因子 %s 通过同类型 fallback key '%s' (type=%s) 提取因子值。",
                        factor_name, fallback_key, primary_type,
                    )
                return float(data[fallback_key])
            except (ValueError, TypeError):
                pass

    # Last resort: use primary_key directly (may be cross-type)
    try:
        if primary_key != "factor_value":
            logger.warning(
                "因子 %s 跨量纲 fallback 到 key '%s'，建议显式声明 factor_value。",
                factor_name, primary_key,
            )
        return float(data[primary_key])
    except (ValueError, TypeError):
        return None


def normalize_factor_data(data: Any, factor_name: str = "unknown") -> Any:
    """Attach stable factor_value / factor_value_type fields without discarding legacy fields."""
    if not isinstance(data, dict):
        return data
    result = dict(data)
    if result.get("factor_value") is not None:
        # 显式声明 factor_value
        result.setdefault("factor_value_source", "explicit")
    else:
        result["factor_value"] = extract_factor_value(result, factor_name)
        # 标记 fallback 来源
        for key in FACTOR_VALUE_KEYS:
            if key != "factor_value" and key in data and data[key] is not None:
                result.setdefault("factor_value_source", f"fallback:{key}")
                break
        else:
            result.setdefault("factor_value_source", "none")
    # Infer factor_value_type from the key that was used
    if result.get("factor_value_type") is None:
        for key in FACTOR_VALUE_KEYS:
            if key in data and data[key] is not None:
                result["factor_value_type"] = _VALUE_TYPE_MAP.get(key, "unknown")
                break
    return result


class FactorRunner:
    def __init__(self, chains_config: Dict[str, Dict[str, Any]], factor_params: Dict[str, Any],
                 data_dir, signal_logger, ic_monitor, chain_defs: Dict[str, Any] = None,
                 data_bus: "DataBus" = None):
        self.chains_config = chains_config
        self.factor_params = factor_params or {}
        self.data_dir = data_dir
        self.signal_logger = signal_logger
        self.ic_monitor = ic_monitor
        self.chain_defs = chain_defs or {}
        self._imported = False
        # 持有共享 DataBus 实例，注入给因子避免全局单例
        from core.data_bus import DataBus
        self._data_bus = data_bus or DataBus(data_dir)

    def ensure_imported(self):
        if self._imported:
            return
        for module_name in collect_factor_modules(self.chains_config):
            importlib.import_module(module_name)
        from core.factor_registry import FactorRegistry
        FactorRegistry.sync_from_chains(self.chains_config)
        self._imported = True

    def instantiate(self, chain_name: str):
        # Prefer ChainDefinition for metadata; fall back to raw config
        chain_def = self.chain_defs.get(chain_name)
        cfg = self.chains_config.get(chain_name)
        if chain_def is not None:
            if chain_def.is_composite or not chain_def.has_factor:
                return None
            module_path = chain_def.factor_module
            class_name = chain_def.factor_class
            symbol = chain_def.symbol
            far_symbol = chain_def.far_symbol
        elif cfg:
            module_path = cfg.get("factor_module")
            class_name = cfg.get("factor_class")
            if not module_path or not class_name:
                return None
            symbol = cfg.get("symbol")
            far_symbol = cfg.get("far_symbol")
        else:
            return None
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            factor_cfg = self.factor_params.get(chain_name, {})
            # Merge: chain-level params as default, factor_params.yaml overrides
            chain_params = {}
            if cfg:
                chain_params = dict(cfg.get("params", {}) or {})
            merged_params = {**chain_params, **factor_cfg.get("params", {})}
            kwargs = {
                "data_dir": str(self.data_dir),
                "adaptive": factor_cfg.get("adaptive", True),
                "params": merged_params,
                "data_bus": self._data_bus,
            }
            if symbol:
                kwargs["symbol"] = symbol
            if far_symbol:
                kwargs["far_symbol"] = far_symbol
            # Inject chain_def for mixed factors that accept it
            import inspect
            sig = inspect.signature(cls.__init__)
            if "chain_def" in sig.parameters:
                kwargs["chain_def"] = chain_def
            return cls(**kwargs)
        except Exception as e:
            logger.warning("实例化因子 %s 失败: %s", chain_name, e)
            return None

    def calculate_only(self, chain_name: str) -> Optional[Dict[str, Any]]:
        """标准化计算：instantiate → calculate → normalize，不做 signal/日志/IC。"""
        factor = self.instantiate(chain_name)
        if factor is None:
            return None
        try:
            data = normalize_factor_data(factor.calculate(), chain_name)
        except Exception as e:
            logger.error("因子 %s calculate 失败: %s", chain_name, e)
            return {
                "factor_data": None,
                "signal_strength": None,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        strength = None
        if hasattr(factor, "signal_strength"):
            try:
                strength = factor.signal_strength()
            except Exception:
                pass

        return {
            "factor_data": data,
            "signal_strength": strength,
        }

    def signal_only(self, chain_name: str) -> Optional[Dict[str, Any]]:
        """标准化信号：calculate_only → signal → 日志记录。"""
        calc_result = self.calculate_only(chain_name)
        if calc_result is None:
            return None
        if calc_result.get("error"):
            return calc_result

        data = calc_result["factor_data"]
        strength = calc_result["signal_strength"]

        factor = self.instantiate(chain_name)
        if factor is None:
            return None
        # P0-5: let factor manage its own cache via _get_or_calculate
        data = normalize_factor_data(factor._get_or_calculate(), chain_name)

        signal_error = None
        try:
            signal = factor.signal()
        except Exception as e:
            logger.error("因子 %s signal 失败: %s", chain_name, e)
            signal = None
            signal_error = str(e)

        today = datetime.now().strftime("%Y-%m-%d")
        self.signal_logger.log(chain_name, signal, strength, data, as_of=today, run_id=f"{chain_name}:{today}")

        result = {
            "factor_data": data,
            "signal": signal,
            "signal_strength": strength,
        }
        if signal_error:
            result["error"] = signal_error
            result["error_type"] = "SignalError"
        return result

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

        signal_error = None
        try:
            signal = factor.signal()
        except Exception as e:
            logger.error("因子 %s signal 失败: %s", chain_name, e)
            signal = None
            signal_error = str(e)

        strength = None
        if hasattr(factor, "signal_strength"):
            try:
                strength = factor.signal_strength()
            except Exception as e:
                logger.warning("因子 %s signal_strength 计算失败: %s", chain_name, e)

        today = datetime.now().strftime("%Y-%m-%d")
        self.signal_logger.log(chain_name, signal, strength, data, as_of=today, run_id=f"{chain_name}:{today}")

        ic_error = None
        if data is not None:
            try:
                fv = extract_factor_value(data, chain_name)
                if fv is not None:
                    self.ic_monitor.snapshot(chain_name, fv, strength, snapshot_date=today)
                else:
                    logger.debug("因子 %s 无有效因子值，跳过 IC 快照", chain_name)
            except Exception as e:
                logger.warning("因子 %s IC快照失败: %s", chain_name, e)
                ic_error = str(e)

        result = {
            "factor_data": data,
            "opportunity": signal,
            "signal_strength": strength,
            "chain_meta": self._chain_meta(chain_name),
        }
        if signal_error:
            result["error"] = signal_error
            result["error_type"] = "SignalError"
        if ic_error:
            result.setdefault("warnings", []).append(f"IC快照失败: {ic_error}")
        return result

    def _chain_meta(self, chain_name: str) -> Optional[Dict[str, Any]]:
        """Return chain-level metadata for mixed chains (trade_asset, drivers, etc.)."""
        chain_def = self.chain_defs.get(chain_name)
        if chain_def is None:
            return None
        meta = {}
        for attr in ("trade_asset", "trade_asset_type", "execution_asset",
                     "signal_target", "category"):
            val = getattr(chain_def, attr, None)
            if val:
                meta[attr] = val
        drivers = getattr(chain_def, "drivers", None)
        if drivers:
            meta["drivers"] = drivers
        # Driver health: check data availability
        if drivers:
            try:
                meta["driver_health"] = self._data_bus.get_driver_status(chain_def)
            except Exception:
                pass
        return meta if meta else None
