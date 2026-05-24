"""交易日历工具：判断是否为交易日，非交易日跳过数据刷新和推送。

使用 akshare 的新浪交易日历作为数据源，本地缓存避免重复请求。
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)

_cached_trade_dates: Optional[Set[date]] = None
_cache_date: Optional[date] = None


def _load_trade_dates() -> Set[date]:
    """加载交易日历（每日只加载一次）。"""
    global _cached_trade_dates, _cache_date

    today = date.today()
    if _cached_trade_dates is not None and _cache_date == today:
        return _cached_trade_dates

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = set(pd.to_datetime(df['trade_date']).dt.date)
        _cached_trade_dates = dates
        _cache_date = today
        logger.info("交易日历加载成功: %d 个交易日", len(dates))
        return dates
    except Exception as e:
        logger.warning("交易日历加载失败: %s, 回退到工作日判断", e)
        return set()


def is_trading_day(d: Optional[date] = None) -> bool:
    """判断指定日期是否为交易日。

    优先使用 akshare 交易日历，失败时回退到周一~周五判断。
    """
    if d is None:
        d = date.today()

    trade_dates = _load_trade_dates()
    if trade_dates:
        return d in trade_dates

    # 回退：周一~周五
    return d.weekday() < 5


def skip_if_not_trading_day(func):
    """装饰器：非交易日跳过执行并记录日志。"""
    def wrapper(*args, **kwargs):
        if not is_trading_day():
            logger.info("今天 (%s) 非交易日，跳过 %s", date.today(), func.__name__)
            return None
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper
