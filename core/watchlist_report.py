"""关注标的看板：读取 watchlist.yaml，汇总现货/期货/基金/股票，输出文字报告。

与链条信号无关，纯粹展示你关注的标的行情。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from core.settings import CONFIG_DIR

logger = logging.getLogger(__name__)

WATCHLIST_PATH = CONFIG_DIR / "watchlist.yaml"


def load_watchlist(path: Path = WATCHLIST_PATH) -> Dict[str, Any]:
    """加载 watchlist.yaml 配置。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _fetch_fund_nav(code: str) -> Optional[Dict[str, Any]]:
    """获取场外基金净值（akshare）。"""
    import akshare as ak
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is None or df.empty:
            return None
        df["单位净值"] = df["单位净值"].astype(float)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        chg = float(latest["日增长率"]) if "日增长率" in latest.index else 0
        # 百分位位置
        all_prices = df["单位净值"].tolist()
        current = all_prices[-1]
        percentile = sum(1 for p in all_prices if p < current) / len(all_prices) * 100
        start_date = str(df.iloc[0]["净值日期"])
        end_date = str(latest["净值日期"])
        # 最近5天价格序列
        recent5 = df["单位净值"].tail(5).tolist()
        return {
            "price": float(latest["单位净值"]),
            "chg_pct": round(chg, 2),
            "date": str(latest["净值日期"]),
            "percentile": round(percentile, 1),
            "data_days": len(all_prices),
            "start_date": start_date,
            "recent5": recent5,
        }
    except Exception as e:
        logger.warning("获取基金 %s 失败: %s", code, e)
        return None


def _fetch_tx_quote(code: str) -> Optional[Dict[str, Any]]:
    """获取 ETF/股票行情（腾讯行情 via akshare）。"""
    import akshare as ak
    try:
        sym = f"sz{code}" if code.startswith(("0", "1", "3")) else f"sh{code}"
        df = ak.stock_zh_a_hist_tx(symbol=sym, start_date="20200101")
        if df is None or df.empty:
            return None
        df["close"] = df["close"].astype(float)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        chg = (latest["close"] - prev["close"]) / prev["close"] * 100
        # 百分位位置
        all_prices = df["close"].tolist()
        current = all_prices[-1]
        percentile = sum(1 for p in all_prices if p < current) / len(all_prices) * 100
        # 最近5天价格序列
        recent5 = df["close"].tail(5).tolist()
        return {
            "price": float(latest["close"]),
            "chg_pct": round(chg, 2),
            "date": str(latest["date"])[:10],
            "percentile": round(percentile, 1),
            "data_days": len(all_prices),
            "start_date": str(df.iloc[0]["date"])[:10],
            "recent5": recent5,
        }
    except Exception as e:
        logger.warning("获取行情 %s 失败: %s", code, e)
        return None


def _fetch_target(code: str, kind: str) -> Optional[Dict[str, Any]]:
    """根据类型分发获取。"""
    if kind == "fund":
        return _fetch_fund_nav(code)
    elif kind in ("etf", "stock"):
        return _fetch_tx_quote(code)
    return None


def _get_spot_avg(data_bus, spot_key: str) -> Optional[float]:
    """从 DataBus 获取现货最新均价。"""
    try:
        df = data_bus.get(spot_key)
        if df is None or df.empty or "close" not in df.columns:
            return None
        return float(df["close"].dropna().iloc[-1])
    except Exception:
        return None


def _get_futures_latest(data_bus, futures_key: str) -> Optional[Dict[str, Any]]:
    """从 DataBus 获取期货最新价格和涨跌幅。"""
    try:
        df = data_bus.get(futures_key)
        if df is None or df.empty or "close" not in df.columns:
            return None
        closes = df["close"].dropna()
        if len(closes) < 2:
            return None
        latest = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        chg = (latest - prev) / prev * 100
        return {"price": latest, "chg_pct": round(chg, 2)}
    except Exception:
        return None


def generate_watchlist_report(data_bus) -> str:
    """生成关注标的看板文字报告（独立使用，不含链条）。"""
    config = load_watchlist()
    groups = config.get("groups", [])
    if not groups:
        return ""

    lines = []
    lines.append(f"📊 每日看板 ({datetime.now().strftime('%Y-%m-%d')})")

    for group in groups:
        name = group.get("name", "")
        spot_keys = group.get("spot", [])
        futures_keys = group.get("futures", [])
        targets = group.get("targets", [])

        lines.append("")
        lines.append(f"{'🐷' if '猪' in name else '📈'} {name}")

        for key in spot_keys:
            price = _get_spot_avg(data_bus, key)
            if price is not None:
                lines.append(f"  现货均价: {price:.2f}")

        for key in futures_keys:
            data = _get_futures_latest(data_bus, key)
            if data is not None:
                lines.append(f"  期货主力: {data['price']:.0f}  {data['chg_pct']:+.2f}%")

        for t in targets:
            code = t.get("code", "")
            tname = t.get("name", code)
            kind = t.get("type", "stock")
            data = _fetch_target(code, kind)
            if data is not None:
                lines.append(f"  {tname}({code}): {data['price']:.4f}  {data['chg_pct']:+.2f}%")
            else:
                lines.append(f"  {tname}({code}): 获取失败")

    return "\n".join(lines)


def get_watchlist_targets_for_chain(chain_name: str) -> List[Dict[str, str]]:
    """获取指定链条关联的看板标的列表（按 chain 匹配）。"""
    try:
        config = load_watchlist()
    except Exception:
        return []
    for group in config.get("groups", []):
        if group.get("chain") == chain_name:
            return group.get("targets", [])
    return []


def get_watchlist_targets_for_label(label: str) -> List[Dict[str, str]]:
    """获取指定资产标签关联的看板标的列表（按 match_label 匹配）。"""
    try:
        config = load_watchlist()
    except Exception:
        return []
    for group in config.get("groups", []):
        if group.get("match_label") == label:
            return group.get("targets", [])
    return []


def fetch_watchlist_targets_for_chain(chain_name: str) -> List[Dict[str, Any]]:
    """获取指定链条关联的标的行情数据。

    Returns:
        [{"code", "name", "kind", "price", "chg_pct"}, ...]
    """
    targets = get_watchlist_targets_for_chain(chain_name)
    if not targets:
        return []
    results = []
    for t in targets:
        code = t.get("code", "")
        tname = t.get("name", code)
        kind = t.get("type", "stock")
        data = _fetch_target(code, kind)
        if data:
            results.append({"code": code, "name": tname, "kind": kind, **data})
        else:
            results.append({"code": code, "name": tname, "kind": kind, "price": None, "chg_pct": None})
    return results
