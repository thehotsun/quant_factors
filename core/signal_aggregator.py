from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _load_yaml_config() -> Dict[str, Any]:
    """Load factor_params.yaml once and cache."""
    try:
        params_path = Path(__file__).parent.parent / "config" / "factor_params.yaml"
        if params_path.exists():
            with open(params_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


_YAML_CACHE: Dict[str, Any] = None  # type: ignore[assignment]


def _get_config() -> Dict[str, Any]:
    global _YAML_CACHE
    if _YAML_CACHE is None:
        _YAML_CACHE = _load_yaml_config()
    return _YAML_CACHE


def _load_correlation_groups() -> Dict[str, Any]:
    return _get_config().get("correlation_groups", {})


def _load_driver_patterns() -> Dict[str, List[str]]:
    return _get_config().get("driver_patterns", {})


class SignalAggregator:
    """信号聚合器：多因子信号融合 + 冲突消解 + 仓位计算 + 相关性去重"""

    CORRELATION_GROUPS = _load_correlation_groups()
    # 从 config/factor_params.yaml 加载，支持热更新
    DRIVER_PATTERNS: Dict[str, List[str]] = _load_driver_patterns()

    @classmethod
    def reload_config(cls):
        """热更新：重新加载 factor_params.yaml 中的 driver_patterns 和 correlation_groups。"""
        global _YAML_CACHE
        _YAML_CACHE = None
        cls.DRIVER_PATTERNS = _load_driver_patterns()
        cls.CORRELATION_GROUPS = _load_correlation_groups()
        logger.info("SignalAggregator 配置已重载: driver_patterns=%d groups, correlation_groups=%d groups",
                     len(cls.DRIVER_PATTERNS), len(cls.CORRELATION_GROUPS))

    @classmethod
    def _classify_driver(cls, trigger: str) -> str:
        """Classify a trigger into a macro driver category."""
        if not trigger:
            return "other"
        t = trigger.lower()
        for driver, patterns in cls.DRIVER_PATTERNS.items():
            if any(p in t for p in patterns):
                return driver
        return "other"

    @classmethod
    def _dedup_drivers(cls, signals: List[Dict]) -> List[Dict]:
        """Discount signals that share the same macro driver.

        When multiple signals are driven by the same macro factor (e.g., two
        growth-linked signals), they are not independent evidence.  Apply a
        decay factor of 1/sqrt(n) per driver group, similar to trigger-based
        dedup but at a higher conceptual level.
        """
        if len(signals) <= 1:
            return signals

        # Group by driver
        driver_indices: Dict[str, List[int]] = {}
        for i, s in enumerate(signals):
            trigger = s.get("trigger", "")
            driver = s.get("driver") or cls._classify_driver(trigger)
            driver_indices.setdefault(driver, []).append(i)

        # Only apply dedup where a driver has 2+ signals
        affected = {d: idxs for d, idxs in driver_indices.items() if len(idxs) >= 2}
        if not affected:
            return signals

        result = [dict(s) for s in signals]
        for driver, indices in affected.items():
            n = len(indices)
            decay = 1.0 / np.sqrt(n)
            for idx in indices:
                orig_strength = result[idx].get("strength", 0.0)
                orig_confidence = result[idx].get("confidence", 0.5)
                result[idx]["strength"] = round(orig_strength * decay, 4)
                result[idx]["confidence"] = round(orig_confidence * decay, 4)
                result[idx]["driver_dedup_group"] = driver
                result[idx]["driver_dedup_factor"] = round(decay, 4)
                # Also set driver for downstream grouping
                if "driver" not in result[idx]:
                    result[idx]["driver"] = driver

        return result

    @staticmethod
    def compute_signal_correlation_discount(signals: List[Dict], history: Any = None) -> Dict[str, float]:
        """基于历史相关性计算信号折扣系数。

        对高相关 pair (|ρ| > 0.7) 中较弱信号施加折扣：
            1. 收集各信号 trigger 对应品种的历史收益率序列
            2. 计算 pairwise correlation matrix
            3. 对高相关 pair 中较弱信号施加折扣 (1/√n)
            4. 返回 {trigger: discount_factor} 映射

        Args:
            signals: 待评估信号列表
            history: 历史价格数据 dict {dep_name: DataFrame}，可选

        Returns:
            {trigger_name: discount_factor}，1.0 = 不折扣，<1.0 = 降权
        """
        if not history or len(signals) < 2:
            return {}

        # Collect price series for each signal's trigger
        trigger_returns = {}
        for sig in signals:
            trigger = sig.get("trigger", "")
            if not trigger:
                continue
            # Try to find matching price data in history
            for dep_name, df in history.items():
                if df is not None and hasattr(df, "columns") and "close" in df.columns:
                    try:
                        returns = df["close"].pct_change().dropna().tail(60)
                        if len(returns) >= 20:
                            trigger_returns[trigger] = returns.values
                            break
                    except Exception:
                        continue

        if len(trigger_returns) < 2:
            return {}

        # Compute pairwise correlation and find highly correlated pairs
        triggers = list(trigger_returns.keys())
        n = len(triggers)
        discount = {t: 1.0 for t in triggers}

        for i in range(n):
            for j in range(i + 1, n):
                try:
                    min_len = min(len(trigger_returns[triggers[i]]), len(trigger_returns[triggers[j]]))
                    if min_len < 20:
                        continue
                    a = trigger_returns[triggers[i]][-min_len:]
                    b = trigger_returns[triggers[j]][-min_len:]
                    corr = abs(float(np.corrcoef(a, b)[0, 1]))
                    if corr > 0.7 and not np.isnan(corr):
                        # Apply 1/sqrt(2) discount to both
                        discount[triggers[i]] = min(discount[triggers[i]], 1.0 / np.sqrt(2))
                        discount[triggers[j]] = min(discount[triggers[j]], 1.0 / np.sqrt(2))
                except Exception:
                    continue

        return discount

    @classmethod
    def _dedup_correlated(cls, signals: List[Dict]) -> List[Dict]:
        """对高度相关的信号进行降权去重"""
        if len(signals) <= 1:
            return signals

        if not cls.CORRELATION_GROUPS:
            logger.debug("correlation_groups 未配置，相关性去重未生效")
            return signals

        trigger_to_idx = {}
        for i, s in enumerate(signals):
            trigger = s.get("trigger", "")
            if trigger:
                trigger_to_idx[trigger] = i

        group_hits = {}
        for group_name, group_info in cls.CORRELATION_GROUPS.items():
            members = group_info["members"]
            hit_indices = []
            for member in members:
                if member in trigger_to_idx:
                    hit_indices.append(trigger_to_idx[member])
            if len(hit_indices) >= 2:
                group_hits[group_name] = hit_indices

        if not group_hits:
            return signals

        result = [dict(s) for s in signals]
        for group_name, indices in group_hits.items():
            n = len(indices)
            decay = 1.0 / np.sqrt(n)
            for idx in indices:
                orig_strength = result[idx].get("strength", 0.0)
                orig_confidence = result[idx].get("confidence", 0.5)
                result[idx]["strength"] = round(orig_strength * decay, 4)
                result[idx]["confidence"] = round(orig_confidence * decay, 4)
                result[idx]["dedup_group"] = group_name
                result[idx]["dedup_factor"] = round(decay, 4)

        return result

    @staticmethod
    def aggregate(signals: List[Dict[str, Any]], method: str = "weighted",
                  dedup: bool = True) -> Optional[Dict[str, Any]]:
        valid = [s for s in signals if s is not None]
        if not valid:
            return None

        raw_count = len(valid)
        dedup_applied = False

        if dedup:
            valid = SignalAggregator._dedup_correlated(valid)
            valid = SignalAggregator._dedup_drivers(valid)
            dedup_applied = len(valid) != raw_count or any(s.get("dedup_group") or s.get("driver_dedup_group") for s in valid)

        if method == "weighted":
            result = SignalAggregator._weighted_aggregate(valid)
        elif method == "voting":
            result = SignalAggregator._voting_aggregate(valid)
        elif method == "strongest":
            result = SignalAggregator._strongest_aggregate(valid)
        else:
            result = SignalAggregator._weighted_aggregate(valid)

        # Attach transparency metadata
        result["raw_signal_count"] = raw_count
        result["effective_signal_count"] = len(valid)
        result["dedup_applied"] = dedup_applied
        result["driver_groups"] = SignalAggregator._extract_driver_groups(valid)
        result["conflict_score"] = SignalAggregator._compute_conflict_score(valid)
        result["driver_conflicts"] = SignalAggregator._detect_driver_conflicts(valid)
        return result

    @staticmethod
    def _weighted_aggregate(signals: List[Dict]) -> Dict[str, Any]:
        total_weight = 0.0
        weighted_strength = 0.0
        buy_signals = []
        sell_signals = []

        for s in signals:
            direction = s.get("direction", "HOLD")
            # Prefer trade_signal_strength (direction-aligned) over raw strength
            trade_str = s.get("trade_signal_strength")
            if trade_str is not None:
                strength = trade_str
            else:
                strength = s.get("strength", 0.0)
            confidence = s.get("confidence", 0.5)
            weight = abs(strength) * confidence
            total_weight += weight

            if direction == "BUY":
                weighted_strength += weight
                buy_signals.append(s)
            elif direction == "SELL":
                weighted_strength -= weight
                sell_signals.append(s)

        if total_weight == 0:
            return {"direction": "HOLD", "strength": 0.0, "confidence": 0.0}

        net_strength = weighted_strength / total_weight
        net_strength = max(-1.0, min(1.0, net_strength))

        if net_strength > 0.15:
            direction = "BUY"
        elif net_strength < -0.15:
            direction = "SELL"
        else:
            direction = "HOLD"

        confidence = min(0.95, total_weight / len(signals))

        return {
            "direction": direction,
            "strength": round(net_strength, 4),
            "confidence": round(confidence, 4),
            "signal_count": len(signals),
            "buy_count": len(buy_signals),
            "sell_count": len(sell_signals),
            "components": [
                {"trigger": s.get("trigger", ""), "direction": s.get("direction", ""),
                 "strength": s.get("strength", 0), "trade_signal_strength": s.get("trade_signal_strength"),
                 "confidence": s.get("confidence", 0)}
                for s in signals
            ]
        }

    @staticmethod
    def _voting_aggregate(signals: List[Dict]) -> Dict[str, Any]:
        buy_votes = sum(1 for s in signals if s.get("direction") == "BUY")
        sell_votes = sum(1 for s in signals if s.get("direction") == "SELL")
        total = len(signals)

        if buy_votes > sell_votes and buy_votes > total * 0.5:
            direction = "BUY"
        elif sell_votes > buy_votes and sell_votes > total * 0.5:
            direction = "SELL"
        else:
            direction = "HOLD"

        return {
            "direction": direction,
            "strength": round((buy_votes - sell_votes) / total, 4),
            "confidence": round(max(buy_votes, sell_votes) / total, 4),
            "signal_count": total,
            "buy_count": buy_votes,
            "sell_count": sell_votes,
        }

    @staticmethod
    def _strongest_aggregate(signals: List[Dict]) -> Dict[str, Any]:
        best = max(signals, key=lambda s: abs(s.get("strength", 0)) * s.get("confidence", 0))
        return {
            "direction": best.get("direction", "HOLD"),
            "strength": best.get("strength", 0),
            "confidence": best.get("confidence", 0),
            "signal_count": len(signals),
            "best_trigger": best.get("trigger", ""),
        }

    @staticmethod
    def resolve_conflict(buy_signal: Dict, sell_signal: Dict) -> Dict[str, Any]:
        buy_score = abs(buy_signal.get("strength", 0)) * buy_signal.get("confidence", 0.5)
        sell_score = abs(sell_signal.get("strength", 0)) * sell_signal.get("confidence", 0.5)

        if buy_score > sell_score * 1.5:
            return {**buy_signal, "conflict_resolved": True, "overridden": sell_signal.get("trigger")}
        elif sell_score > buy_score * 1.5:
            return {**sell_signal, "conflict_resolved": True, "overridden": buy_signal.get("trigger")}
        else:
            return {
                "direction": "HOLD",
                "strength": 0.0,
                "confidence": 0.0,
                "reason": f"信号冲突: BUY({buy_signal.get('trigger')}) vs SELL({sell_signal.get('trigger')})",
                "conflict_resolved": False,
            }

    @staticmethod
    def _extract_driver_groups(signals: List[Dict]) -> Dict[str, List[str]]:
        """Group signals by their macro driver (from dedup or classification)."""
        groups: Dict[str, List[str]] = {}
        for s in signals:
            driver = (s.get("driver") or s.get("driver_dedup_group")
                      or s.get("dedup_group"))
            if not driver:
                # Classify from trigger even when dedup is off
                driver = SignalAggregator._classify_driver(s.get("trigger", ""))
            trigger = s.get("trigger", "unknown")
            groups.setdefault(driver, []).append(trigger)
        return groups

    @staticmethod
    def _compute_conflict_score(signals: List[Dict]) -> float:
        """Compute a 0.0–1.0 conflict score.

        0.0 = all signals agree on direction; 1.0 = maximum disagreement.
        Based on the ratio of opposing weight to total weight.
        """
        if len(signals) <= 1:
            return 0.0

        buy_weight = 0.0
        sell_weight = 0.0
        for s in signals:
            w = abs(s.get("strength", 0)) * s.get("confidence", 0.5)
            if s.get("direction") == "BUY":
                buy_weight += w
            elif s.get("direction") == "SELL":
                sell_weight += w

        total = buy_weight + sell_weight
        if total == 0:
            return 0.0
        # Conflict = minority weight / total weight (0 if unanimous, max 0.5 if split)
        minority = min(buy_weight, sell_weight)
        return round(min(1.0, 2.0 * minority / total), 4)

    @staticmethod
    def _detect_driver_conflicts(signals: List[Dict]) -> List[Dict[str, Any]]:
        """Detect driver groups with opposing signals.

        Returns list of conflicts: [{driver, buy_triggers, sell_triggers, severity}]
        """
        if len(signals) <= 1:
            return []

        # Group signals by driver
        driver_signals: Dict[str, List[Dict]] = {}
        for s in signals:
            driver = (s.get("driver") or s.get("driver_dedup_group")
                      or s.get("dedup_group")
                      or SignalAggregator._classify_driver(s.get("trigger", "")))
            driver_signals.setdefault(driver, []).append(s)

        conflicts = []
        for driver, sigs in driver_signals.items():
            buy_triggers = [s.get("trigger", "") for s in sigs if s.get("direction") == "BUY"]
            sell_triggers = [s.get("trigger", "") for s in sigs if s.get("direction") == "SELL"]
            if buy_triggers and sell_triggers:
                total_weight = sum(abs(s.get("strength", 0)) * s.get("confidence", 0.5) for s in sigs)
                minority_weight = min(
                    sum(abs(s.get("strength", 0)) * s.get("confidence", 0.5) for s in sigs if s.get("direction") == "BUY"),
                    sum(abs(s.get("strength", 0)) * s.get("confidence", 0.5) for s in sigs if s.get("direction") == "SELL"),
                )
                severity = round(2.0 * minority_weight / total_weight, 4) if total_weight > 0 else 0.0
                conflicts.append({
                    "driver": driver,
                    "buy_triggers": buy_triggers,
                    "sell_triggers": sell_triggers,
                    "severity": severity,
                })
        return conflicts