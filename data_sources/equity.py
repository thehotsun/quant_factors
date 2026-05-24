"""股票/ETF 数据源适配器（东方财富 via akshare）。

支持：
- ETF 历史行情：fund_etf_hist_em（东方财富 ETF）
- A 股历史行情：stock_zh_a_hist（东方财富 A 股）

返回标准化 DataFrame：date, open, high, low, close, volume, amount, source
"""

import pandas as pd


def fetch_etf_hist(symbol, name=None, start_date="20200101", adjust="qfq"):
    """获取 ETF 历史行情数据。

    Args:
        symbol: ETF 代码，如 "159865"（养殖ETF）、"518880"（黄金ETF）
        name: 显示名称（仅用于日志）
        start_date: 起始日期
        adjust: 复权方式 "qfq" 前复权 / "hfq" 后复权 / "" 不复权

    Returns:
        DataFrame with date, open, high, low, close, volume, amount, source
    """
    import akshare as ak

    label = name or symbol
    try:
        df = ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            adjust=adjust,
        )
        if df is None or df.empty:
            print(f"  {label} ETF 数据为空")
            return None

        # akshare fund_etf_hist_em 返回中文列名
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"])
        df["source"] = f"akshare.fund_etf_hist_em:{symbol}"

        keep = ["date", "open", "high", "low", "close", "volume", "amount", "source"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        df.reset_index(drop=True, inplace=True)

        print(f"  {label}: {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}")
        return df
    except Exception as e:
        print(f"  {label} ETF 下载失败: {e}")
        return None


def fetch_stock_hist(symbol, name=None, start_date="20200101", adjust="qfq"):
    """获取 A 股历史行情数据。

    Args:
        symbol: 股票代码，如 "601857"（中国石油）
        name: 显示名称（仅用于日志）
        start_date: 起始日期
        adjust: 复权方式

    Returns:
        DataFrame with date, open, high, low, close, volume, amount, source
    """
    import akshare as ak

    label = name or symbol
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            adjust=adjust,
        )
        if df is None or df.empty:
            print(f"  {label} 股票数据为空")
            return None

        # akshare stock_zh_a_hist 返回中文列名
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"])
        df["source"] = f"akshare.stock_zh_a_hist:{symbol}"

        keep = ["date", "open", "high", "low", "close", "volume", "amount", "source"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        df.reset_index(drop=True, inplace=True)

        print(f"  {label}: {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}")
        return df
    except Exception as e:
        print(f"  {label} 股票下载失败: {e}")
        return None
