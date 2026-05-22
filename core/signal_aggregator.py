from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _load_correlation_groups() -> Dict[str, Any]:
    try:
        params_path = Path(__file__).parent.parent / "config" / "factor_params.yaml"
        if params_path.exists():
            with open(params_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config.get("correlation_groups", {})
    except Exception:
        pass
    return {}


class SignalAggregator:
    """信号聚合器：多因子信号融合 + 冲突消解 + 仓位计算 + 相关性去重"""

    CORRELATION_GROUPS = _load_correlation_groups()

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
            dedup_applied = len(valid) != raw_count or any(s.get("dedup_group") for s in valid)

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
        """Group signals by their dedup_group (trigger correlation group)."""
        groups: Dict[str, List[str]] = {}
        for s in signals:
            group = s.get("dedup_group", "ungrouped")
            trigger = s.get("trigger", "unknown")
            groups.setdefault(group, []).append(trigger)
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