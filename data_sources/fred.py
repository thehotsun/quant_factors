"""FRED 数据源（美联储经济数据）。"""

import pandas as pd


def fetch_fred_csv(series_id, name, start_date="2020-01-01"):
    """从 FRED 直接下载 CSV 数据"""
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
        df = pd.read_csv(url)
        df = df.rename(columns={'observation_date': 'date'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        return df
    except Exception as e:
        print(f"  {name} 下载失败: {e}")
        return None


def fetch_brent_oil():
    """从 FRED 下载布伦特原油价格（日度）"""
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU&cosd=2020-01-01'
        df = pd.read_csv(url)
        df = df.rename(columns={'observation_date': 'date', 'DCOILBRENTEU': 'close'})
        df['date'] = pd.to_datetime(df['date'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        df = df.sort_values('date')
        df.reset_index(drop=True, inplace=True)
        print(f"  布伦特原油(FRED): {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}")
        return df
    except Exception as e:
        print(f"  布伦特原油下载失败: {e}")
        return None
