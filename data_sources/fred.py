"""FRED 数据源（美联储经济数据）。"""
from io import StringIO

import pandas as pd
import requests

# 出站请求超时（秒）。FRED 曾出现过连接挂起导致整个刷新任务永久阻塞。
_TIMEOUT = 30


def _download_fred_csv(series_id, start_date):
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
           f"?id={series_id}&cosd={start_date}")
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return pd.read_csv(StringIO(resp.text))


def fetch_fred_csv(series_id, name, start_date="2020-01-01"):
    """从 FRED 直接下载 CSV 数据（带超时）。"""
    try:
        df = _download_fred_csv(series_id, start_date)
        df = df.rename(columns={'observation_date': 'date'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        return df
    except Exception as e:
        print(f"  {name} 下载失败: {e}")
        return None


def fetch_brent_oil():
    """从 FRED 下载布伦特原油价格（日度，带超时）。"""
    try:
        df = _download_fred_csv("DCOILBRENTEU", "2020-01-01")
        df = df.rename(columns={'observation_date': 'date', 'DCOILBRENTEU': 'close'})
        df['date'] = pd.to_datetime(df['date'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        df = df.sort_values('date')
        df.reset_index(drop=True, inplace=True)
        print(f"  布伦特原油(FRED): {len(df)} 条, "
              f"{df['date'].min().date()} ~ {df['date'].max().date()}")
        return df
    except Exception as e:
        print(f"  布伦特原油下载失败: {e}")
        return None
