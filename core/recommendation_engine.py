"""Recommendation engine: converts signal output into clean BUY/SELL/HOLD recommendations.

This is a pure presentation layer — it does NOT read, maintain, or infer
any user positions, portfolio, or trading account.  It translates raw
signal data into human-readable recommendations with confidence, risk
notes, and data health context.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── RecommendationV1 标准输出结构 ──────────────────────────────

RECOMMENDATION_LABELS = {
    "BUY": "建议买入",
    "SELL": "建议卖出",
    "HOLD": "建议观望",
}


def make_recommendation(
    recommendation: str,
    strength: float = 0.0,
    confidence: float = 0.0,
    reason: str = "",
    risk_notes: Optional[List[str]] = None,
    data_notes: Optional[List[str]] = None,
    conflict_notes: Optional[List[str]] = None,
    drivers_used: Optional[List[str]] = None,
    missing_drivers: Optional[List[str]] = None,
    components: Optional[List[Dict[str, Any]]] = None,
    chain_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a RecommendationV1 dict with validated fields.

    Args:
        recommendation: BUY / SELL / HOLD
        strength: signal strength (-1.0 to 1.0)
        confidence: signal confidence (0.0 to 1.0)
        reason: human-readable reason for the recommendation
        risk_notes: list of risk warnings
        data_notes: list of data quality notes
        conflict_notes: list of conflict descriptions
        drivers_used: driver groups that contributed to the signal
        missing_drivers: driver groups with missing/unavailable data
        components: individual signal components for transparency
        chain_meta: chain-level metadata (trade_asset, etc.)

    Returns:
        RecommendationV1 dict
    """
    recommendation = recommendation.upper()
    if recommendation not in ("BUY", "SELL", "HOLD"):
        logger.warning("Invalid recommendation '%s', defaulting to HOLD", recommendation)
        recommendation = "HOLD"

    return {
        "recommendation": recommendation,
        "label": RECOMMENDATION_LABELS.get(recommendation, "建议观望"),
        "strength": round(strength, 4),
        "confidence": round(confidence, 4),
        "reason": reason,
        "risk_notes": risk_notes or [],
        "data_notes": data_notes or [],
        "conflict_notes": conflict_notes or [],
        "drivers_used": drivers_used or [],
        "missing_drivers": missing_drivers or [],
        "components": components or [],
        "chain_meta": chain_meta or {},
        "generated_at": datetime.now().isoformat(),
    }


# ── RecommendationEngine ──────────────────────────────────────

class RecommendationEngine:
    """Converts signal output into RecommendationV1.

    Stateless — does not track positions or portfolio.
    """

    @staticmethod
    def _adjust_for_data_health(rec: Dict[str, Any], missing_deps: List[str],
                                stale_deps: List[tuple]) -> Dict[str, Any]:
        """Adjust recommendation based on data health.

        - Missing critical data: lower confidence
        - Stale data: lower confidence
        - Severe missing (>=2 critical deps): force HOLD
        """
        severity = len(missing_deps) + len(stale_deps) * 0.5

        if severity >= 2.0:
            # Severe: force HOLD
            rec["recommendation"] = "HOLD"
            rec["label"] = "建议观望"
            rec["confidence"] = round(max(0.1, rec["confidence"] * 0.3), 4)
            rec["risk_notes"].append("关键驱动数据严重缺失或过期，强制观望")
        elif severity >= 1.0:
            # Moderate: lower confidence
            rec["confidence"] = round(max(0.1, rec["confidence"] * 0.5), 4)
        elif severity > 0:
            # Mild: slight confidence reduction
            rec["confidence"] = round(max(0.1, rec["confidence"] * 0.8), 4)

        return rec

    @staticmethod
    def from_signal(signal_result: Dict[str, Any]) -> Dict[str, Any]:
        """Build a RecommendationV1 from a single-chain signal result.

        Args:
            signal_result: output of FactorRunner.run_chain() or similar,
                expected keys: opportunity, signal, signal_strength, factor_data, chain_meta

        Returns:
            RecommendationV1 dict
        """
        if signal_result is None:
            return make_recommendation("HOLD", reason="无信号数据")

        # Extract signal info
        signal = signal_result.get("signal") or signal_result.get("opportunity") or {}
        if isinstance(signal, str):
            # Old-format: signal is just a direction string
            direction = signal
            strength = signal_result.get("signal_strength", 0.0) or 0.0
            reason = ""
        else:
            direction = signal.get("direction", "HOLD")
            strength = signal.get("strength", 0.0) or 0.0
            reason = signal.get("reason", "")

        confidence = signal.get("confidence", 0.0) if isinstance(signal, dict) else 0.0

        # Build notes from signal metadata
        risk_notes = []
        data_notes = []
        conflict_notes = []

        if isinstance(signal, dict):
            # Missing drivers
            missing = signal.get("missing_drivers", [])
            if missing:
                data_notes.append(f"缺失驱动数据: {', '.join(missing)}")
                risk_notes.append("部分驱动数据不可用，建议置信度已降低")

            # Driver conflicts
            conflicts = signal.get("driver_conflicts", [])
            if conflicts:
                for c in conflicts:
                    if isinstance(c, dict):
                        driver = c.get("driver", "unknown")
                        buy_t = c.get("buy_triggers", [])
                        sell_t = c.get("sell_triggers", [])
                        severity = c.get("severity", 0)
                        conflict_notes.append(
                            f"{driver}方向冲突: BUY({', '.join(buy_t)}) vs SELL({', '.join(sell_t)}) 严重度{severity:.2f}"
                        )
                    else:
                        conflict_notes.append(str(c))

            # Conflict score
            conflict_score = signal.get("conflict_score", 0)
            if conflict_score and conflict_score > 0.5:
                risk_notes.append(f"信号冲突度较高({conflict_score:.2f})，建议谨慎")

        # Drivers used / missing from chain_meta
        chain_meta = signal_result.get("chain_meta") or {}
        drivers_used = []
        missing_drivers = []
        stale_deps = []
        if chain_meta:
            drivers_used = list(chain_meta.get("drivers", {}).keys()) if isinstance(chain_meta.get("drivers"), dict) else []
            driver_health = chain_meta.get("driver_health", {})
            if isinstance(driver_health, dict):
                stale_deps = []
                for group, statuses in driver_health.items():
                    if isinstance(statuses, dict):
                        for dep, info in statuses.items():
                            # Handle both old format (string) and new format (dict)
                            if isinstance(info, str):
                                st = info
                                lag = None
                            else:
                                st = info.get("status", "ok") if isinstance(info, dict) else "ok"
                                lag = info.get("lag_days") if isinstance(info, dict) else None

                            if st == "ok":
                                if dep not in drivers_used:
                                    drivers_used.append(dep)
                                # Check freshness even for "ok" if lag is significant
                                if lag is not None and lag > 5:
                                    stale_deps.append((dep, lag))
                            elif st == "stale":
                                stale_deps.append((dep, lag))
                                if dep not in drivers_used:
                                    drivers_used.append(dep)
                            elif st.startswith("missing"):
                                missing_drivers.append(dep)
                                reason = info.get("reason", st) if isinstance(info, dict) else st

                # Stale data notes
                for dep, lag in stale_deps:
                    data_notes.append(f"数据过期: {dep} 已过期 {lag} 天")
                    risk_notes.append(f"{dep} 数据过期({lag}天)，建议置信度已降低")

                # Missing data notes
                for dep in missing_drivers:
                    data_notes.append(f"数据缺失: {dep}")

                # Severe missing: lower confidence
                if missing_drivers:
                    risk_notes.append(f"缺失关键驱动数据({', '.join(missing_drivers)})，建议置信度已降低")

        # Factor data components for transparency
        components = []
        factor_data = signal_result.get("factor_data")
        if isinstance(factor_data, dict):
            fv = factor_data.get("factor_value")
            fv_type = factor_data.get("factor_value_type")
            if fv is not None:
                components.append({
                    "name": "factor_value",
                    "value": fv,
                    "type": fv_type,
                })
            # Include zscore, ratio, etc. if present
            for key in ("zscore", "zscore_20d", "ratio", "momentum_score", "score"):
                if key in factor_data and factor_data[key] is not None:
                    try:
                        components.append({
                            "name": key,
                            "value": float(factor_data[key]),
                            "type": key,
                        })
                    except (TypeError, ValueError):
                        pass

        rec = make_recommendation(
            recommendation=direction,
            strength=strength,
            confidence=confidence,
            reason=reason,
            risk_notes=risk_notes,
            data_notes=data_notes,
            conflict_notes=conflict_notes,
            drivers_used=drivers_used,
            missing_drivers=missing_drivers,
            components=components,
            chain_meta=chain_meta,
        )

        # Adjust recommendation based on data health
        rec = RecommendationEngine._adjust_for_data_health(rec, missing_drivers, stale_deps)
        return rec

    @staticmethod
    def from_aggregated(aggregated: Dict[str, Any], chain_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build a RecommendationV1 from an aggregated signal (composite chains).

        Args:
            aggregated: output of SignalAggregator.aggregate()
            chain_meta: optional chain metadata

        Returns:
            RecommendationV1 dict
        """
        if aggregated is None:
            return make_recommendation("HOLD", reason="无聚合信号")

        direction = aggregated.get("direction", "HOLD")
        strength = aggregated.get("strength", 0.0)
        confidence = aggregated.get("confidence", 0.0)

        # Build reason from components
        components_data = aggregated.get("components", [])
        reason_parts = []
        for comp in components_data[:5]:
            trigger = comp.get("trigger", "")
            comp_dir = comp.get("direction", "")
            if trigger and comp_dir:
                reason_parts.append(f"{trigger}→{comp_dir}")
        reason = "; ".join(reason_parts) if reason_parts else ""

        # Notes
        risk_notes = []
        data_notes = []
        conflict_notes = []

        conflict_score = aggregated.get("conflict_score", 0)
        if conflict_score and conflict_score > 0.5:
            risk_notes.append(f"信号冲突度较高({conflict_score:.2f})，建议谨慎")

        driver_conflicts = aggregated.get("driver_conflicts", [])
        for c in driver_conflicts:
            if isinstance(c, dict):
                driver = c.get("driver", "unknown")
                buy_t = c.get("buy_triggers", [])
                sell_t = c.get("sell_triggers", [])
                severity = c.get("severity", 0)
                conflict_notes.append(
                    f"{driver}方向冲突: BUY({', '.join(buy_t)}) vs SELL({', '.join(sell_t)}) 严重度{severity:.2f}"
                )

        dedup_applied = aggregated.get("dedup_applied", False)
        if dedup_applied:
            data_notes.append("信号已去重处理")

        # Drivers
        driver_groups = aggregated.get("driver_groups", {})
        drivers_used = list(driver_groups.keys()) if driver_groups else []

        # Components
        components = []
        for comp in components_data:
            components.append({
                "trigger": comp.get("trigger", ""),
                "direction": comp.get("direction", ""),
                "strength": comp.get("strength", 0),
                "confidence": comp.get("confidence", 0),
            })

        return make_recommendation(
            recommendation=direction,
            strength=strength,
            confidence=confidence,
            reason=reason,
            risk_notes=risk_notes,
            data_notes=data_notes,
            conflict_notes=conflict_notes,
            drivers_used=drivers_used,
            missing_drivers=[],
            components=components,
            chain_meta=chain_meta or {},
        )
