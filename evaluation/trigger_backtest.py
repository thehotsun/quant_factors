"""Trigger-level backtest: evaluate whether each trigger actually predicts returns.

Queries historical signals from the signal logger, maps each signal's asset to
a price series, computes forward returns at 1/5/10/20 day horizons, and
aggregates per-trigger statistics.

Usage:
    from evaluation.trigger_backtest import trigger_backtest
    report = trigger_backtest(chains_config, data_bus, signal_logger)
"""
from __future__ import annotations

import sqlite3
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FORWARD_DAYS = [1, 5, 10, 20]


def _build_asset_to_dep(chains_config: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Build reverse mapping from asset label → price data dep.

    For mixed chains, prefer execution_asset (code) if it appears in data_deps,
    then check drivers for the trade_asset_type group, then fall back to data_deps[0].
    """
    # Map trade_asset_type to driver group key
    _TYPE_TO_DRIVER = {"etf": "equity", "stock": "equity", "basket": "equity"}

    mapping: Dict[str, str] = {}
    for cfg in chains_config.values():
        asset = cfg.get("asset", "")
        trade_asset = cfg.get("trade_asset", "") or asset
        execution_asset = cfg.get("execution_asset", "")
        trade_asset_type = cfg.get("trade_asset_type", "")
        deps = cfg.get("data_deps", [])
        drivers = cfg.get("drivers", {})
        if not asset or not deps:
            continue
        if asset in mapping:
            continue
        preferred = None
        # 1. Check if execution_asset appears in any dep name
        if execution_asset:
            for dep in deps:
                if execution_asset in dep or dep.endswith(f"_{execution_asset}"):
                    preferred = dep
                    break
        # 2. Check drivers: for mixed chains, the trade_asset_type group
        #    (e.g., "equity") contains the trade asset's price dep
        if not preferred and drivers and trade_asset_type:
            driver_key = _TYPE_TO_DRIVER.get(trade_asset_type, trade_asset_type)
            type_deps = drivers.get(driver_key, [])
            if type_deps and type_deps[0] in deps:
                preferred = type_deps[0]
        # 3. Check if any dep name matches the trade asset label
        if not preferred and trade_asset:
            for dep in deps:
                if dep in trade_asset or trade_asset in dep:
                    preferred = dep
                    break
        mapping[asset] = preferred or deps[0]
    return mapping


def _get_forward_returns(price_df: pd.DataFrame, signal_date: str,
                         horizons: List[int] = None) -> Dict[str, Optional[float]]:
    """Calculate forward returns from signal_date for each horizon.

    Returns a dict like {"fwd_1d": 0.01, "fwd_5d": 0.03, ...}.
    """
    if horizons is None:
        horizons = FORWARD_DAYS

    if price_df is None or price_df.empty or "close" not in price_df.columns:
        return {f"fwd_{h}d": None for h in horizons}

    close = price_df["close"].astype(float)
    dates = pd.to_datetime(price_df["date"])
    signal_ts = pd.to_datetime(signal_date)

    # Find the index of the signal date or the nearest prior date
    mask = dates <= signal_ts
    if not mask.any():
        return {f"fwd_{h}d": None for h in horizons}

    # Get the last date <= signal_ts (not the first)
    signal_idx = mask[::-1].idxmax()
    signal_price = close.iloc[signal_idx]

    if signal_price == 0 or np.isnan(signal_price):
        return {f"fwd_{h}d": None for h in horizons}

    result = {}
    for h in horizons:
        fwd_idx = signal_idx + h
        if fwd_idx < len(close):
            fwd_price = close.iloc[fwd_idx]
            if not np.isnan(fwd_price):
                result[f"fwd_{h}d"] = round(float((fwd_price - signal_price) / signal_price), 6)
            else:
                result[f"fwd_{h}d"] = None
        else:
            result[f"fwd_{h}d"] = None
    return result


def _aggregate_trigger_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate forward-return statistics for a single trigger."""
    if not records:
        return {"count": 0}

    stats: Dict[str, Any] = {"count": len(records)}

    # Direction breakdown
    buy_count = sum(1 for r in records if r.get("direction") == "BUY")
    sell_count = sum(1 for r in records if r.get("direction") == "SELL")
    stats["buy_count"] = buy_count
    stats["sell_count"] = sell_count

    for h in FORWARD_DAYS:
        key = f"fwd_{h}d"
        returns = [r[key] for r in records if r.get(key) is not None]
        if not returns:
            stats[f"avg_{key}"] = None
            stats[f"median_{key}"] = None
            stats[f"win_rate_{key}"] = None
            stats[f"max_loss_{key}"] = None
            continue

        arr = np.array(returns)

        # For BUY signals, positive return = win; for SELL, negative return = win
        # Use direction-adjusted return for win rate
        adjusted = []
        for r in records:
            if r.get(key) is not None:
                ret = r[key]
                if r.get("direction") == "SELL":
                    adjusted.append(-ret)
                else:
                    adjusted.append(ret)
        adj_arr = np.array(adjusted)

        stats[f"avg_{key}"] = round(float(arr.mean()), 6)
        stats[f"median_{key}"] = round(float(np.median(arr)), 6)
        stats[f"win_rate_{key}"] = round(float((adj_arr > 0).mean()), 4)
        stats[f"max_loss_{key}"] = round(float(arr.min()), 6)

    # Per-year breakdown
    yearly = defaultdict(list)
    for r in records:
        year = r.get("year")
        if year:
            for h in FORWARD_DAYS:
                key = f"fwd_{h}d"
                if r.get(key) is not None:
                    yearly[year].append(r[key])

    if yearly:
        year_stats = {}
        for year, rets in sorted(yearly.items()):
            arr = np.array(rets)
            year_stats[str(year)] = {
                "count": len(rets),
                "avg_return": round(float(arr.mean()), 6),
                "win_rate": round(float((arr > 0).mean()), 4),
            }
        stats["by_year"] = year_stats

    return stats


def trigger_backtest(
    chains_config: Dict[str, Dict[str, Any]],
    data_bus,
    signal_logger,
    days: int = 365,
    min_samples: int = 3,
) -> Dict[str, Any]:
    """Run trigger-level backtest across all recorded signals.

    Returns a dict with:
    - summary: total triggers, total signals, evaluated triggers
    - triggers: per-trigger statistics
    """
    asset_to_dep = _build_asset_to_dep(chains_config)

    # Query all signals from the past N days
    signals = signal_logger.query(days=days, limit=10000)
    if not signals:
        return {
            "summary": {"total_signals": 0, "triggers_evaluated": 0},
            "triggers": {},
        }

    # Group by trigger
    by_trigger: Dict[str, List[Dict]] = defaultdict(list)
    for sig in signals:
        trigger = sig.get("trigger")
        if not trigger:
            continue
        by_trigger[trigger].append(sig)

    # Evaluate each trigger
    trigger_results = {}
    evaluated = 0

    for trigger, sigs in by_trigger.items():
        if len(sigs) < min_samples:
            trigger_results[trigger] = {
                "count": len(sigs),
                "insufficient_samples": True,
                "min_required": min_samples,
            }
            continue

        records = []
        for sig in sigs:
            asset = sig.get("asset", "")
            as_of = sig.get("as_of") or sig.get("created_at", "")[:10]
            direction = sig.get("direction", "")

            dep_name = asset_to_dep.get(asset)
            if not dep_name:
                continue

            price_df = data_bus.get(dep_name)
            if price_df is None:
                continue

            fwd = _get_forward_returns(price_df, as_of)
            record = {
                "direction": direction,
                "strength": sig.get("strength"),
                "confidence": sig.get("confidence"),
                "as_of": as_of,
                "year": pd.to_datetime(as_of).year if as_of else None,
                **fwd,
            }
            records.append(record)

        if records:
            stats = _aggregate_trigger_stats(records)
            stats["description"] = sigs[0].get("reason", "")[:80]
            stats["asset"] = sigs[0].get("asset", "")
            trigger_results[trigger] = stats
            evaluated += 1

    # Sort by count descending
    sorted_triggers = dict(
        sorted(trigger_results.items(), key=lambda x: x[1].get("count", 0), reverse=True)
    )

    return {
        "summary": {
            "total_signals": len(signals),
            "unique_triggers": len(by_trigger),
            "triggers_evaluated": evaluated,
            "triggers_insufficient": len(by_trigger) - evaluated,
            "lookback_days": days,
            "min_samples": min_samples,
        },
        "triggers": sorted_triggers,
    }


def format_trigger_report(report: Dict[str, Any]) -> str:
    """Format trigger backtest report as human-readable markdown."""
    lines = []
    summary = report["summary"]
    lines.append(f"**Trigger 级回测报告** (回看 {summary['lookback_days']} 天)")
    lines.append(f"总信号数: {summary['total_signals']} | 触发器: {summary['unique_triggers']} | 评估: {summary['triggers_evaluated']} | 样本不足: {summary['triggers_insufficient']}")
    lines.append("")

    triggers = report.get("triggers", {})
    for name, stats in triggers.items():
        if stats.get("insufficient_samples"):
            lines.append(f"**{name}**: {stats['count']}次 (需{stats['min_required']}+)")
            continue

        count = stats["count"]
        asset = stats.get("asset", "")
        desc = stats.get("description", "")

        # Use 5d return as primary indicator
        avg_5d = stats.get("avg_fwd_5d")
        wr_5d = stats.get("win_rate_fwd_5d")
        avg_20d = stats.get("avg_fwd_20d")

        emoji = "🟢" if avg_5d and avg_5d > 0 else ("🔴" if avg_5d and avg_5d < 0 else "⚪")

        line = f"{emoji} **{name}** ({count}次, {asset})"
        if avg_5d is not None:
            line += f"\n  5日: 均{avg_5d*100:+.1f}% 胜率{wr_5d*100:.0f}%" if wr_5d else ""
        if avg_20d is not None:
            wr_20d = stats.get("win_rate_fwd_20d")
            line += f" | 20日: 均{avg_20d*100:+.1f}% 胜率{wr_20d*100:.0f}%" if wr_20d else ""
        ml = stats.get("max_loss_fwd_5d")
        if ml is not None:
            line += f" | 最大亏损{ml*100:.1f}%"
        lines.append(line)

    return "\n".join(lines)
