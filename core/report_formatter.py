"""Shared report formatting for quant_factors.

Provides a unified view of chain results used by both push messages and API
responses.  The ``format_chain_report`` function returns a structured dict
that can be serialized to JSON (API) or rendered to markdown (push).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


DIRECTION_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}

REC_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}
REC_VERB = {"BUY": "建议买入", "SELL": "建议卖出", "HOLD": "建议观望"}


def direction_emoji(direction: str) -> str:
    return DIRECTION_EMOJI.get(direction, "⚪")


def recommendation_emoji(rec: str) -> str:
    return REC_EMOJI.get(rec, "⚪")


def position_label(percentile: float) -> str:
    """Human-readable position label from 0–100 percentile."""
    if percentile <= 20:
        return "★接近底部区间★"
    if percentile <= 40:
        return "偏低区间"
    if percentile <= 60:
        return "中等水平"
    if percentile <= 80:
        return "偏高区间"
    return "★接近顶部区间★"


def period_label(days: int) -> str:
    if days >= 200:
        return "近1年"
    if days >= 100:
        return "近半年"
    if days >= 40:
        return "近2个月"
    return f"近{days}天"


def format_trend(prices: List[float], key: str = None) -> str:
    """Format a price list as a trend string with arrow and pct change.

    Args:
        prices: list of raw prices
        key: optional data_dep or symbol for display unit conversion
    """
    if not prices or len(prices) < 2:
        return ""
    from core.display_units import get_display_rule
    divisor = 1
    unit_suffix = ""
    if key:
        rule = get_display_rule(key)
        if rule:
            divisor, unit_suffix = rule
            unit_suffix = f" {unit_suffix}"
    display_prices = [p / divisor for p in prices]
    arrow = "↑" if display_prices[-1] > display_prices[0] else ("↓" if display_prices[-1] < display_prices[0] else "→")
    pct = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0
    fmt = lambda p: f"{p:,.0f}" if abs(p) >= 100 else (f"{p:.1f}" if abs(p) >= 10 else f"{p:.2f}")
    price_str = " → ".join(fmt(p) for p in display_prices)
    
    # 涨跌幅超过阈值时添加标记
    abs_pct = abs(pct)
    if abs_pct >= 8:
        # 严重涨跌：🔴 暴涨/暴跌
        tag = "🔴"
    elif abs_pct >= 5:
        # 大幅涨跌：🔶 大涨/大跌
        tag = "🔶"
    elif abs_pct >= 3:
        # 明显涨跌：⚠️
        tag = "⚠️"
    else:
        tag = ""
    
    result = f"{price_str}{unit_suffix} {arrow} ({pct:+.1f}%)"
    if tag:
        result = f"{tag} {result}"
    return result


def format_chain_report(composite_results: Dict[str, Any]) -> Dict[str, Any]:
    """Return a structured report dict from composite chain results.

    This is the canonical formatting layer.  Both API responses and push
    messages should consume this output.
    """
    chain_name = composite_results.get("chain", "未知")
    description = composite_results.get("description", "")
    aggregated = composite_results.get("aggregated_signal")
    signals = composite_results.get("active_signals", [])
    all_results = composite_results.get("all_results", {})

    # Build aggregated summary
    agg_summary = None
    if aggregated:
        agg_summary = {
            "direction": aggregated.get("direction", "HOLD"),
            "strength": aggregated.get("strength", 0),
            "confidence": aggregated.get("confidence", 0),
            "signal_count": aggregated.get("signal_count", 0),
            "buy_count": aggregated.get("buy_count", 0),
            "sell_count": aggregated.get("sell_count", 0),
            "raw_signal_count": aggregated.get("raw_signal_count"),
            "effective_signal_count": aggregated.get("effective_signal_count"),
            "dedup_applied": aggregated.get("dedup_applied"),
            "conflict_score": aggregated.get("conflict_score"),
            "driver_groups": aggregated.get("driver_groups"),
        }

    # Build signal list
    signal_list = []
    for s in signals[:10]:
        entry = {
            "trigger": s.get("trigger", s.get("_chain", "")),
            "direction": s.get("direction", ""),
            "strength": s.get("strength", 0),
            "confidence": s.get("confidence", 0),
            "reason": s.get("reason", "")[:120],
            "asset": s.get("asset", ""),
            "holding_days": s.get("holding_days"),
            "stop_loss": s.get("stop_loss"),
        }
        # Mixed chain fields
        if s.get("drivers_used"):
            entry["drivers_used"] = s["drivers_used"]
        if s.get("missing_drivers"):
            entry["missing_drivers"] = s["missing_drivers"]
        if s.get("trade_asset"):
            entry["trade_asset"] = s["trade_asset"]
        signal_list.append(entry)

    # Build error list
    errors = []
    for name, result in all_results.items():
        if isinstance(result, dict) and result.get("error"):
            errors.append({"chain": name, "error": result["error"], "error_type": result.get("error_type", "")})

    return {
        "chain": chain_name,
        "description": description,
        "aggregated": agg_summary,
        "signals": signal_list,
        "errors": errors,
        "timestamp": datetime.now().isoformat(),
    }


def format_chain_report_markdown(report: Dict[str, Any], price_context: List[Dict[str, Any]] = None) -> str:
    """Render a structured report dict to markdown for push messages."""
    lines = []
    chain = report.get("chain", "未知")
    desc = report.get("description", "")
    agg = report.get("aggregated")

    lines.append(f"**{chain}** - {desc}")
    lines.append("")

    if agg:
        emoji = direction_emoji(agg["direction"])
        lines.append(f"{emoji} **综合信号: {agg['direction']}** | 强度: {agg['strength']:.2f} | 置信度: {agg['confidence']:.2f}")
        line2 = f"信号数: {agg['signal_count']} (BUY:{agg['buy_count']} SELL:{agg['sell_count']})"
        if agg.get("conflict_score") is not None:
            line2 += f" | 冲突度: {agg['conflict_score']:.2f}"
        if agg.get("dedup_applied"):
            line2 += " | 已去重"
        lines.append(line2)
    else:
        lines.append("⚪ 综合信号: HOLD（无有效信号）")

    if price_context:
        lines.append("")
        lines.append("📊 **近5日价格:**")
        for item in price_context:
            label = item.get("label", "")
            trend = item.get("trend", "")
            position = item.get("position", "")
            line = f"- {label}: {trend}"
            if position:
                line += f"\n  {position}"
            lines.append(line)

    signals = report.get("signals", [])
    if signals:
        lines.append("")
        lines.append("**活跃信号:**")
        for s in signals:
            emoji = direction_emoji(s["direction"])
            line = f"- {emoji} **{s['trigger']}** ({s['direction']}): {s['reason']}"
            # Mixed chain: show drivers
            drivers_used = s.get("drivers_used", [])
            missing = s.get("missing_drivers", [])
            if drivers_used:
                line += f"\n  📎 驱动: {', '.join(drivers_used)}"
            if missing:
                line += f"\n  ⚠️ 缺失: {', '.join(missing)}"
            lines.append(line)

    errors = report.get("errors", [])
    if errors:
        lines.append("")
        lines.append("**⚠️ 异常:**")
        for e in errors:
            lines.append(f"- {e['chain']}: {e['error']}")

    return "\n".join(lines)


def format_recommendation_report(recommendation: Dict[str, Any], chain_name: str = "",
                                  description: str = "", price_context: List[Dict[str, Any]] = None) -> str:
    """Render a RecommendationV1 to markdown for push messages.

    Uses '建议口径': 建议买入/卖出/观望, no trading actions or positions.
    """
    lines = []

    rec = recommendation.get("recommendation", "HOLD")
    label = recommendation.get("label", "建议观望")
    emoji = recommendation_emoji(rec)
    strength = recommendation.get("strength", 0)
    confidence = recommendation.get("confidence", 0)
    reason = recommendation.get("reason", "")

    if chain_name:
        lines.append(f"**{chain_name}**")
    if description:
        lines.append(f"_{description}_")
    lines.append("")

    # Main recommendation
    lines.append(f"{emoji} **{label}** | 强度: {strength:.2f} | 置信度: {confidence:.2f}")
    if reason:
        lines.append(f"📌 原因: {reason}")
    lines.append("")

    # Price context
    if price_context:
        lines.append("📊 **近5日价格:**")
        for item in price_context:
            p_label = item.get("label", "")
            trend = item.get("trend", "")
            position = item.get("position", "")
            line = f"- {p_label}: {trend}"
            if position:
                line += f"\n  {position}"
            lines.append(line)
        lines.append("")

    # Components (top signals)
    components = recommendation.get("components", [])
    if components:
        lines.append("📎 **信号组成:**")
        for comp in components[:8]:
            trigger = comp.get("trigger", comp.get("name", ""))
            comp_dir = comp.get("direction", "")
            comp_str = comp.get("strength", 0)
            if trigger and comp_dir:
                comp_emoji = direction_emoji(comp_dir)
                lines.append(f"- {comp_emoji} {trigger} ({comp_dir}, 强度{comp_str:.2f})")
            elif trigger:
                lines.append(f"- {trigger}: {comp.get('value', '')}")
        lines.append("")

    # Drivers
    drivers_used = recommendation.get("drivers_used", [])
    missing = recommendation.get("missing_drivers", [])
    if drivers_used:
        lines.append(f"📎 驱动: {', '.join(drivers_used)}")
    if missing:
        lines.append(f"⚠️ 缺失驱动: {', '.join(missing)}")

    # Data notes
    data_notes = recommendation.get("data_notes", [])
    if data_notes:
        lines.append("")
        lines.append("📋 **数据说明:**")
        for note in data_notes:
            lines.append(f"- {note}")

    # Conflict notes
    conflict_notes = recommendation.get("conflict_notes", [])
    if conflict_notes:
        lines.append("")
        lines.append("⚡ **信号冲突:**")
        for note in conflict_notes:
            lines.append(f"- {note}")

    # Risk notes
    risk_notes = recommendation.get("risk_notes", [])
    if risk_notes:
        lines.append("")
        lines.append("⚠️ **风险提示:**")
        for note in risk_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)
