"""盘中异动告警：监控期货 + 现货品种实时价格，涨跌幅超阈值时推送告警。

功能：
- 分级告警：初始/升级/严重，每档只推一次
- 恢复通知：涨跌幅回到阈值一半以内时推送告警解除
- 期货和现货独立配置阈值

期货：使用 akshare futures_zh_spot 获取实时行情（轻量，0.06s/品种）
现货：使用 akshare soozhu 系列接口获取实时行情
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.settings import DATA_DIR

logger = logging.getLogger(__name__)

# ── 期货配置 ──────────────────────────────────────────────

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

# ── 现货配置 ──────────────────────────────────────────────

# 异常涨跌幅上限：超过此值大概率是数据错误，跳过告警
_MAX_PCT_THRESHOLD = 30.0

_SPOT_SOURCES: Dict[str, Dict[str, Any]] = {
    "pork": {
        "name": "生猪现货",
        "fetch": "hog",
        "unit_factor": 1000,
    },
    "corn": {
        "name": "玉米现货",
        "fetch": "corn",
        "unit_factor": 2000,
    },
    "soybean_domestic": {
        "name": "国产大豆现货",
        "fetch": "soybean",
        "unit_factor": 2000,
    },
}

# ── 加载配置 ──────────────────────────────────────────────

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

# ── 分级告警配置 ──────────────────────────────────────────

# 期货告警档位：(阈值%, emoji标签)
FUTURES_TIERS: List[Tuple[float, str]] = [
    (5.0,  "⚠️"),   # 初始告警
    (8.0,  "🔶"),   # 升级告警
    (12.0, "🔴"),   # 严重告警
]

# 现货告警档位
SPOT_TIERS: List[Tuple[float, str]] = [
    (3.0,  "⚠️"),
    (5.0,  "🔶"),
    (8.0,  "🔴"),
]

# 恢复阈值：涨跌幅回到初始阈值的多少比例以内算恢复
RECOVERY_RATIO = 0.5  # 即回到初始阈值的50%以内

# 告警状态文件
_ALERT_STATE_PATH = Path(DATA_DIR) / "alert_state.json"
# 现货前收盘价文件
_SPOT_PREV_CLOSE_PATH = Path(DATA_DIR) / "spot_prev_close.json"

# ── 交易时段判断 ──────────────────────────────────────────

# 期货夜盘收盘时间：贵金属 02:30，有色金属 01:00，其余 23:00
# 统一取最晚的 02:30，避免品种判断复杂化
_FUTURES_SESSIONS = [
    (dt_time(9, 0),  dt_time(11, 30)),   # 日盘
    (dt_time(13, 30), dt_time(15, 0)),    # 日盘
    (dt_time(21, 0), dt_time(2, 30)),     # 夜盘（跨日，覆盖所有品种）
]

# 现货：排除 9:00-9:30 开盘缓冲期，等 soozhu 数据刷新
_SPOT_SESSIONS = [
    (dt_time(9, 30), dt_time(11, 30)),    # 日盘（9:30 起）
    (dt_time(13, 30), dt_time(15, 0)),    # 日盘
    (dt_time(21, 0), dt_time(23, 0)),     # 夜盘
]


def _in_sessions(sessions: list) -> bool:
    """判断当前时间是否在给定时段列表内（支持跨日）。"""
    now = datetime.now().time()
    for start, end in sessions:
        if start <= end:
            if start <= now <= end:
                return True
        else:  # 跨日（如 21:00-02:30）
            if now >= start or now <= end:
                return True
    return False


def _is_trading_session() -> bool:
    return _in_sessions(_FUTURES_SESSIONS)


def _is_spot_trading_session() -> bool:
    return _in_sessions(_SPOT_SESSIONS)


# ── 告警状态管理（分级版）──────────────────────────────────

def _load_alert_state() -> Dict[str, Any]:
    """加载今日告警状态。

    格式：
    {
        "date": "2026-05-25",
        "alerts": {
            "LH0": {"tier": 1, "direction": "up", "pct": 5.2, "time": "10:00"},
            "spot_corn": {"tier": 2, "direction": "down", "pct": -8.5, "time": "10:30"}
        }
    }
    """
    try:
        if _ALERT_STATE_PATH.exists():
            data = json.loads(_ALERT_STATE_PATH.read_text())
            if data.get("date") == date.today().isoformat():
                return data
    except Exception:
        pass
    return {"date": date.today().isoformat(), "alerts": {}}


def _save_alert_state(state: Dict[str, Any]):
    try:
        _ALERT_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning("保存告警状态失败: %s", e)


def _get_triggered_tier(pct: float, tiers: List[Tuple[float, str]]) -> int:
    """判断当前涨跌幅触发了哪个档位（返回1-based索引，0=未触发）。"""
    abs_pct = abs(pct)
    triggered = 0
    for i, (threshold, _) in enumerate(tiers, 1):
        if abs_pct >= threshold:
            triggered = i
    return triggered


def _is_recovery(pct: float, tiers: List[Tuple[float, str]]) -> bool:
    """判断是否已恢复到安全区间（涨跌幅 < 初始阈值 × 恢复比例）。"""
    if not tiers:
        return True
    initial_threshold = tiers[0][0]
    return abs(pct) < initial_threshold * RECOVERY_RATIO


# ── 期货前一日收盘价 ──────────────────────────────────────

def _get_prev_close() -> Dict[str, float]:
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


# ── 现货前一日收盘价 ──────────────────────────────────────

def _get_spot_prev_close() -> Dict[str, Dict[str, Any]]:
    try:
        if _SPOT_PREV_CLOSE_PATH.exists():
            return json.loads(_SPOT_PREV_CLOSE_PATH.read_text())
    except Exception:
        pass
    return {}


# ── 期货实时行情获取 ──────────────────────────────────────

def _fetch_realtime_prices() -> Dict[str, Dict[str, float]]:
    import akshare as ak
    result = {}
    for symbol in MONITORED_SYMBOLS:
        try:
            df = ak.futures_zh_spot(symbol=symbol, market='CF', adjust='0')
            if df is not None and not df.empty:
                price = float(df['current_price'].iloc[0])
                # 优先用昨结算价（更准确），其次昨收盘价，最后 0（由上游 fallback parquet）
                settle = float(df['last_settle_price'].iloc[0]) if 'last_settle_price' in df.columns and df['last_settle_price'].iloc[0] else 0
                last_close = float(df['last_close'].iloc[0]) if 'last_close' in df.columns and df['last_close'].iloc[0] else 0
                prev = settle if settle > 0 else last_close
                result[symbol] = {"price": price, "prev_close_api": prev}
        except Exception as e:
            logger.debug("获取 %s 实时行情失败: %s", symbol, e)
    return result


# ── 现货实时行情获取 ──────────────────────────────────────

def _fetch_realtime_spot_prices() -> Dict[str, Dict[str, float]]:
    import akshare as ak
    result = {}

    # 生猪现货：取全国均价，前一日从 parquet 获取
    try:
        df = ak.spot_hog_soozhu()
        if df is not None and not df.empty and '价格' in df.columns:
            avg_price = float(df['价格'].mean())
            # 生猪用前几日均价做基准（排除今天），避免 prev_close=0 导致 fallback 旧数据
            prev_prices = df['价格'].iloc[:-1] if len(df) > 1 else df['价格']
            prev_avg = float(prev_prices.mean()) if len(prev_prices) > 0 else 0
            result["pork"] = {
                "price": avg_price * _SPOT_SOURCES["pork"]["unit_factor"],
                "prev_close": prev_avg * _SPOT_SOURCES["pork"]["unit_factor"] if prev_avg > 0 else 0,
            }
    except Exception as e:
        logger.debug("获取生猪现货失败: %s", e)

    # 玉米现货：soozhu 有历史序列，自对比
    try:
        df = ak.spot_corn_price_soozhu()
        if df is not None and len(df) >= 2 and '价格' in df.columns:
            factor = _SPOT_SOURCES["corn"]["unit_factor"]
            result["corn"] = {
                "price": float(df['价格'].iloc[-1]) * factor,
                "prev_close": float(df['价格'].iloc[-2]) * factor,
            }
    except Exception as e:
        logger.debug("获取玉米现货失败: %s", e)

    # 国产大豆现货：soozhu 有历史序列，自对比
    try:
        df = ak.spot_soybean_price_soozhu()
        if df is not None and len(df) >= 2 and '价格' in df.columns:
            factor = _SPOT_SOURCES["soybean_domestic"]["unit_factor"]
            result["soybean_domestic"] = {
                "price": float(df['价格'].iloc[-1]) * factor,
                "prev_close": float(df['价格'].iloc[-2]) * factor,
            }
    except Exception as e:
        logger.debug("获取国产大豆现货失败: %s", e)

    return result


# ── 价格格式化 ──────────────────────────────────────────

def _format_price(price: float) -> str:
    if price >= 10000:
        return f"{price:,.0f}"
    elif price >= 100:
        return f"{price:.0f}"
    else:
        return f"{price:.2f}"


# ── 告警推送 ──────────────────────────────────────────────

def _push_alert(push_fn, alert: Dict[str, Any], tier: int, tiers: List[Tuple[float, str]]):
    """推送一条分级告警。"""
    _, emoji = tiers[tier - 1]
    title = f"{emoji} {alert['name']}{alert['direction']}告警（{['','初告警','升级','严重'][tier]}）"

    price_str = _format_price(alert['price'])
    prev_str = _format_price(alert['prev_close'])
    lines = [
        f"**{alert['name']}** {alert['direction']} {alert['pct_change']:+.2f}%",
        f"当前价: {price_str} | 前收: {prev_str}",
    ]
    if alert.get("prev_date"):
        lines.append(f"前收日期: {alert['prev_date']}")
    lines.append(f"档位: 第{tier}档 ({tiers[tier-1][0]}%)")
    lines.append(f"时间: {datetime.now().strftime('%H:%M')}")
    content = "\n".join(lines)

    try:
        push_fn(title, content)
    except Exception as e:
        logger.error("推送告警失败: %s", e)


def _push_recovery(push_fn, symbol: str, name: str, pct: float, asset_type: str):
    """推送一条恢复通知。"""
    direction = "上涨" if pct > 0 else "下跌"
    title = f"✅ {name}告警解除"
    content = (
        f"**{name}** 已回落至 {pct:+.2f}%，{direction}幅度收窄\n"
        f"时间: {datetime.now().strftime('%H:%M')}"
    )
    try:
        push_fn(title, content)
    except Exception as e:
        logger.error("推送恢复通知失败: %s", e)


# ── 告警检查 ──────────────────────────────────────────────

def check_market_alerts(push_fn=None) -> List[Dict[str, Any]]:
    """检查市场异动（期货 + 现货），支持分级告警 + 恢复通知。

    返回触发的告警/恢复列表。
    """
    if not _is_trading_session():
        logger.debug("非交易时段，跳过异动检查")
        return []

    from core.trading_calendar import is_trading_day
    if not is_trading_day():
        logger.debug("非交易日，跳过异动检查")
        return []

    state = _load_alert_state()
    alerts_log = state.get("alerts", {})
    triggered = []  # 本轮触发的告警/恢复

    # ── 期货异动检查 ──────────────────────────────────────

    prev_closes = _get_prev_close()
    realtime = _fetch_realtime_prices()

    if prev_closes and realtime:
        for symbol, info in realtime.items():
            price = info["price"]
            prev = prev_closes.get(symbol, info.get("prev_close_api", 0))
            if not prev or prev <= 0:
                continue

            pct = (price - prev) / prev * 100
            name = MONITORED_SYMBOLS.get(symbol, symbol)

            _process_alert(
                symbol=symbol, name=name, price=price, prev=prev,
                pct=pct, asset_type="期货", tiers=FUTURES_TIERS,
                alerts_log=alerts_log, push_fn=push_fn, triggered=triggered,
            )

    # ── 现货异动检查 ──────────────────────────────────────

    spot_prev = _get_spot_prev_close()
    # 现货只在现货交易时段检查（9:30 之后，避开开盘缓冲期）
    spot_realtime = _fetch_realtime_spot_prices() if _is_spot_trading_session() else {}

    if spot_realtime:
        for key, spot_info in spot_realtime.items():
            spot_key = f"spot_{key}"
            src = _SPOT_SOURCES.get(key, {})
            name = src.get("name", key)
            current_price = spot_info["price"]

            # 优先用 soozhu 自对比的 prev_close，其次用 spot_prev_close.json
            prev_price = spot_info.get("prev_close", 0)
            prev_date = ""
            if not prev_price or prev_price <= 0:
                prev_info = spot_prev.get(key, {})
                prev_price = prev_info.get("price", 0)
                prev_date = prev_info.get("date", "")

            if not prev_price or prev_price <= 0:
                continue

            pct = (current_price - prev_price) / prev_price * 100

            # 异常值过滤：涨跌幅超过 ±30% 大概率是数据错误
            if abs(pct) > _MAX_PCT_THRESHOLD:
                logger.warning("%s 涨跌幅异常 %.2f%%，跳过告警（当前价: %s, 前收: %s）",
                               name, pct, current_price, prev_price)
                continue

            alert_extra = {}
            if prev_date:
                alert_extra["prev_date"] = prev_date

            _process_alert(
                symbol=spot_key, name=name, price=current_price, prev=prev_price,
                pct=pct, asset_type="现货", tiers=SPOT_TIERS,
                alerts_log=alerts_log, push_fn=push_fn, triggered=triggered,
                extra=alert_extra,
            )

    # ── 保存状态 ──────────────────────────────────────────

    state["alerts"] = alerts_log
    _save_alert_state(state)

    if triggered:
        names = [f"{a['name']}({a.get('asset_type','')})" for a in triggered]
        logger.info("异动事件: %s", ", ".join(names))

    return triggered


def _process_alert(symbol: str, name: str, price: float, prev: float,
                   pct: float, asset_type: str, tiers: List[Tuple[float, str]],
                   alerts_log: Dict, push_fn, triggered: list,
                   extra: Dict = None):
    """处理单个品种的告警逻辑（分级 + 恢复）。"""
    current_tier = _get_triggered_tier(pct, tiers)
    prev_state = alerts_log.get(symbol)
    prev_tier = prev_state.get("tier", 0) if prev_state else 0

    alert_entry = {
        "symbol": symbol,
        "name": name,
        "price": price,
        "prev_close": prev,
        "pct_change": round(pct, 2),
        "direction": "暴涨" if pct > 0 else "暴跌",
        "asset_type": asset_type,
    }
    if extra:
        alert_entry.update(extra)

    # 情况1：触发了更高档位 → 升级告警
    if current_tier > 0 and current_tier > prev_tier:
        if push_fn:
            _push_alert(push_fn, alert_entry, current_tier, tiers)
        alerts_log[symbol] = {
            "tier": current_tier,
            "direction": "up" if pct > 0 else "down",
            "pct": round(pct, 2),
            "time": datetime.now().strftime("%H:%M"),
        }
        triggered.append(alert_entry)

    # 情况2：之前告警过，现已恢复到安全区间 → 恢复通知
    elif prev_tier > 0 and current_tier == 0 and _is_recovery(pct, tiers):
        if push_fn:
            _push_recovery(push_fn, symbol, name, pct, asset_type)
        # 移除告警状态
        alerts_log.pop(symbol, None)
        triggered.append({**alert_entry, "event": "recovery"})

    # 情况3：同档位或更高但未升级 → 不重复推送
    # 情况4：未触发且无历史告警 → 跳过


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
