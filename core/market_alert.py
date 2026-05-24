"""盘中异动告警：监控期货品种实时价格，涨跌幅超阈值时推送告警。

- 使用 akshare futures_zh_spot 获取实时行情（轻量，0.06s/品种）
- 对比前一日收盘价，计算日内涨跌幅
- 超过阈值（默认 ±5%）触发告警
- 同品种同一天不重复告警
- 只在交易时段运行（日盘 9:00-15:00 + 夜盘 21:00-23:00）
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from core.settings import DATA_DIR

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────

# 监控品种：akshare 新浪代码 → 显示名
MONITORED_SYMBOLS: Dict[str, str] = {
    'LH0': '生猪',    'JD0': '鸡蛋',    'M0': '豆粕',
    'C0': '玉米',     'CU0': '铜',      'AL0': '铝',
    'RB0': '螺纹钢',  'AU0': '黄金',    'AG0': '白银',
    'I0': '铁矿石',   'SC0': '原油',    'A0': '国产大豆',
    'B0': '进口大豆',  'RM0': '菜粕',    'Y0': '豆油',
}

# 品种 → 前一日收盘价 parquet 文件名
_SYMBOL_TO_PARQUET: Dict[str, str] = {
    'LH0': 'pork_futures',       'JD0': 'egg_futures',
    'M0': 'soybean_meal_futures', 'C0': 'corn_futures',
    'CU0': 'copper_futures',     'AL0': 'aluminum_futures',
    'RB0': 'rebar_futures',      'AU0': 'gold_futures',
    'AG0': 'silver_futures',     'I0': 'iron_ore_futures',
    'SC0': 'crude_oil_futures',  'A0': 'soybean_domestic_futures',
    'B0': 'soybean_import_futures', 'RM0': 'rapeseed_meal_futures',
    'Y0': 'soybean_oil_futures',
}

def _load_alert_config() -> dict:
    """加载告警配置（alert.yaml）。"""
    try:
        from pathlib import Path
        import yaml
        cfg_path = Path(__file__).parent.parent / "config" / "alert.yaml"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


_alert_cfg = _load_alert_config()
DEFAULT_THRESHOLD = _alert_cfg.get("threshold", 5.0)  # 百分比

# 告警状态文件（记录今天已告警的品种）
_ALERT_STATE_PATH = Path(DATA_DIR) / "alert_state.json"

# ── 交易时段判断 ──────────────────────────────────────────

def _is_trading_session() -> bool:
    """判断当前是否在交易时段内（日盘 + 夜盘）。"""
    now = datetime.now()
    t = now.time()

    # 日盘：9:00 - 11:30, 13:30 - 15:00
    if dt_time(9, 0) <= t <= dt_time(11, 30):
        return True
    if dt_time(13, 30) <= t <= dt_time(15, 0):
        return True
    # 夜盘：21:00 - 23:00
    if dt_time(21, 0) <= t <= dt_time(23, 0):
        return True

    return False


# ── 告警状态管理 ──────────────────────────────────────────

def _load_alerted() -> Set[str]:
    """加载今天已告警的品种集合。"""
    try:
        if _ALERT_STATE_PATH.exists():
            data = json.loads(_ALERT_STATE_PATH.read_text())
            if data.get("date") == date.today().isoformat():
                return set(data.get("alerted", []))
    except Exception:
        pass
    return set()


def _save_alerted(alerted: Set[str]):
    """保存今天已告警的品种集合。"""
    try:
        data = {
            "date": date.today().isoformat(),
            "alerted": sorted(alerted),
        }
        _ALERT_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.warning("保存告警状态失败: %s", e)


# ── 前一日收盘价 ──────────────────────────────────────────

def _get_prev_close() -> Dict[str, float]:
    """从 parquet 文件获取所有品种的前一日收盘价。"""
    result = {}
    data_dir = str(DATA_DIR)
    for symbol, parquet_name in _SYMBOL_TO_PARQUET.items():
        path = os.path.join(data_dir, f"{parquet_name}.parquet")
        try:
            df = pd.read_parquet(path)
            if 'close' in df.columns and not df.empty:
                result[symbol] = float(df['close'].iloc[-1])
        except Exception:
            pass
    return result


# ── 实时行情获取 ──────────────────────────────────────────

def _fetch_realtime_prices() -> Dict[str, Dict[str, float]]:
    """获取所有监控品种的实时行情。

    返回 {symbol: {"price": float, "prev_close": float}}
    """
    import akshare as ak

    result = {}
    for symbol in MONITORED_SYMBOLS:
        try:
            df = ak.futures_zh_spot(symbol=symbol, market='CF', adjust='0')
            if df is not None and not df.empty:
                price = float(df['current_price'].iloc[0])
                # akshare 返回的 last_close 有时为 0，用本地 parquet 兜底
                prev = float(df['last_close'].iloc[0]) if 'last_close' in df.columns else 0
                result[symbol] = {"price": price, "prev_close_api": prev}
        except Exception as e:
            logger.debug("获取 %s 实时行情失败: %s", symbol, e)
    return result


# ── 告警检查 ──────────────────────────────────────────────

def check_market_alerts(threshold: float = DEFAULT_THRESHOLD,
                        push_fn=None) -> List[Dict[str, Any]]:
    """检查市场异动，返回触发告警列表。

    Args:
        threshold: 涨跌幅阈值（百分比），默认 ±5%
        push_fn: 推送函数 push_fn(title, content) -> bool

    Returns:
        触发的告警列表 [{symbol, name, price, prev_close, pct_change, direction}]
    """
    if not _is_trading_session():
        logger.debug("非交易时段，跳过异动检查")
        return []

    from core.trading_calendar import is_trading_day
    if not is_trading_day():
        logger.debug("非交易日，跳过异动检查")
        return []

    # 获取前一日收盘价（本地 parquet 优先）
    prev_closes = _get_prev_close()
    if not prev_closes:
        logger.warning("无法获取前一日收盘价，跳过异动检查")
        return []

    # 获取实时行情
    realtime = _fetch_realtime_prices()
    if not realtime:
        logger.warning("无法获取实时行情，跳过异动检查")
        return []

    # 加载已告警品种
    alerted = _load_alerted()

    # 检查涨跌幅
    alerts = []
    for symbol, info in realtime.items():
        if symbol in alerted:
            continue

        price = info["price"]
        # 优先用本地 parquet 的前收，api 的 last_close 作兜底
        prev = prev_closes.get(symbol, info.get("prev_close_api", 0))
        if not prev or prev <= 0:
            continue

        pct = (price - prev) / prev * 100
        if abs(pct) >= threshold:
            name = MONITORED_SYMBOLS.get(symbol, symbol)
            direction = "暴涨" if pct > 0 else "暴跌"
            alert = {
                "symbol": symbol,
                "name": name,
                "price": price,
                "prev_close": prev,
                "pct_change": round(pct, 2),
                "direction": direction,
            }
            alerts.append(alert)

    # 推送告警
    if alerts and push_fn:
        for alert in alerts:
            title = f"⚠️ {alert['name']}{alert['direction']}告警"
            content = (
                f"**{alert['name']}** {alert['direction']} {alert['pct_change']:+.2f}%\n"
                f"当前价: {alert['price']:.0f} | 前收: {alert['prev_close']:.0f}\n"
                f"时间: {datetime.now().strftime('%H:%M')}"
            )
            try:
                push_fn(title, content)
            except Exception as e:
                logger.error("推送告警失败: %s", e)

        # 记录已告警品种
        alerted.update(a["symbol"] for a in alerts)
        _save_alerted(alerted)

    if alerts:
        names = [a["name"] for a in alerts]
        logger.info("异动告警触发: %s", ", ".join(names))

    return alerts


# ── 定时任务入口 ──────────────────────────────────────────

def run_market_alert_check():
    """定时任务入口：检查市场异动并推送告警。"""
    from core.push import get_push_manager

    def _push(title, content):
        mgr = get_push_manager()
        results = mgr.send(title, content)
        return any(results.values())

    alerts = check_market_alerts(push_fn=_push)
    if not alerts:
        logger.debug("本轮异动检查：无告警")
