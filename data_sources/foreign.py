"""外盘数据源（新浪外盘期货 / 外汇 / AKShare 外盘）。

约定：本模块只依赖 stdlib / requests / akshare / pandas，**不导入 core**，
以避免与 core.data_refresh 形成循环依赖。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# 出站超时（秒）——避免源站挂起导致刷新任务永久阻塞
_TIMEOUT = 20
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 新浪外盘期货 日线（JSONP）
_SINA_HIST_URL = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
    "var%20_S{today}=/GlobalFuturesService.getGlobalFuturesDailyKLine"
)
# 新浪外盘期货 实时快照（hf_）
_SINA_HF_URL = "https://hq.sinajs.cn/list={codes}"


def fetch_sina_foreign_hist(symbol: str = "OIL") -> Optional[pd.DataFrame]:
    """新浪外盘期货日线（带超时）。

    symbol 例：OIL 布伦特原油, CL 纽约原油(WTI), NG 天然气, S 美豆, CAD 伦铜。
    """
    today = f"{datetime.today().year}_{datetime.today().month}_{datetime.today().day}"
    url = _SINA_HIST_URL.format(today=today)
    params = {"symbol": symbol, "_": today, "source": "web"}
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT,
                         headers={"Referer": "https://finance.sina.com.cn", "User-Agent": _UA})
        r.raise_for_status()
        text = r.text
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end < 0:
            logger.warning("新浪外盘 %s 响应异常", symbol)
            return None
        df = pd.DataFrame(json.loads(text[start:end + 1]))
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for col in ("open", "high", "low", "close", "volume", "position", "settlement"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        logger.info("新浪外盘 %s: %d 条, %s ~ %s", symbol, len(df),
                    df["date"].min().date(), df["date"].max().date())
        return df
    except Exception as e:  # noqa: BLE001
        logger.warning("新浪外盘 %s 下载失败: %s", symbol, e)
        return None


def fetch_sina_foreign_spot(symbol: str = "OIL") -> Optional[dict]:
    """新浪外盘期货实时快照（单点，非历史）。symbol 同上。"""
    try:
        r = requests.get(_SINA_HF_URL.format(codes=f"hf_{symbol}"), timeout=_TIMEOUT,
                         headers={"Referer": "https://finance.sina.com.cn", "User-Agent": _UA})
        r.encoding = "gbk"
        text = r.text
        if '="' not in text:
            return None
        fields = text.split('="', 1)[1].rstrip('";\n').split(",")
        if len(fields) < 14 or not fields[0]:
            return None
        return {
            "name": fields[13] or fields[0],
            "price": float(fields[0]),
            "date": f"{fields[12]} {fields[6]}",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("新浪外盘快照 %s 失败: %s", symbol, e)
        return None


def fetch_boc_usd_cny(start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
    """中行美元/人民币牌价日频（akshare 包装），取「中行折算价」/100 作为 close。

    与 FRED DEXCHUS 同量级（≈6.7），可作备用源。
    """
    end = end_date or datetime.today().strftime("%Y%m%d")
    start = start_date or (datetime.today() - timedelta(days=365 * 5)).strftime("%Y%m%d")
    try:
        df = ak.currency_boc_sina(symbol="美元", start_date=start, end_date=end)
        if df is None or df.empty:
            return None
        df = df.rename(columns={"日期": "date", "中行折算价": "close"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce") / 100.0
        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        logger.info("中行美元人民币: %d 条, %s ~ %s", len(df),
                    df["date"].min().date(), df["date"].max().date())
        return df[["date", "close"]]
    except Exception as e:  # noqa: BLE001
        logger.warning("中行美元人民币下载失败: %s", e)
        return None


def fetch_cbot_soybean():
    """下载 CBOT 大豆连续合约历史数据。"""
    try:
        df = ak.futures_foreign_hist(symbol="S")
        if df is None or df.empty:
            print("  CBOT大豆下载为空")
            return None
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume", "position", "settlement"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        print(f"  CBOT大豆下载失败: {e}")
        return None
