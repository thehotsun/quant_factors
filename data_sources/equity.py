"""股票/ETF 数据源适配器（腾讯行情 via akshare）。

支持：
- ETF 历史行情：stock_zh_a_hist_tx（腾讯行情）
- A 股历史行情：stock_zh_a_hist_tx（腾讯行情）

返回标准化 DataFrame：date, open, high, low, close, amount, source
注：腾讯接口不返回 volume，仅有 amount
"""

import pandas as pd


def _tx_symbol(code: str) -> str:
    """将纯代码转换为腾讯格式（sh/sz 前缀）。"""
    if code.startswith(("sh", "sz")):
        return code
    # 上海：6 开头（股票）、518/510 开头（ETF）
    if code.startswith(("6", "518", "510", "513", "515", "516")):
        return f"sh{code}"
    # 深圳：0/3 开头（股票）、159 开头（ETF）
    return f"sz{code}"


def _normalize_tx_df(df, label, symbol, start_date):
    """规范化腾讯接口返回的 DataFrame。"""
    df["date"] = pd.to_datetime(df["date"])
    df["source"] = f"akshare.stock_zh_a_hist_tx:{symbol}"
    # 腾讯接口列：date, open, close, high, low, amount
    keep = ["date", "open", "high", "low", "close", "amount", "source"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    df.reset_index(drop=True, inplace=True)
    print(f"  {label}: {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def fetch_etf_hist(symbol, name=None, start_date="20200101", adjust="qfq"):
    """获取 ETF 历史行情数据。

    Args:
        symbol: ETF 代码，如 "159865"（养殖ETF）、"518880"（黄金ETF）
        name: 显示名称（仅用于日志）
        start_date: 起始日期
        adjust: 复权方式（腾讯接口不支持，忽略）

    Returns:
        DataFrame with date, open, high, low, close, amount, source
    """
    import akshare as ak

    label = name or symbol
    tx_sym = _tx_symbol(symbol)
    try:
        df = ak.stock_zh_a_hist_tx(symbol=tx_sym, start_date=start_date)
        if df is None or df.empty:
            print(f"  {label} ETF 数据为空")
            return None
        return _normalize_tx_df(df, label, tx_sym, start_date=None)
    except Exception as e:
        print(f"  {label} ETF 下载失败: {e}")
        return None


def fetch_stock_hist(symbol, name=None, start_date="20200101", adjust="qfq"):
    """获取 A 股历史行情数据。

    Args:
        symbol: 股票代码，如 "601857"（中国石油）
        name: 显示名称（仅用于日志）
        start_date: 起始日期
        adjust: 复权方式（腾讯接口不支持，忽略）

    Returns:
        DataFrame with date, open, high, low, close, amount, source
    """
    import akshare as ak

    label = name or symbol
    tx_sym = _tx_symbol(symbol)
    try:
        df = ak.stock_zh_a_hist_tx(symbol=tx_sym, start_date=start_date)
        if df is None or df.empty:
            print(f"  {label} 股票数据为空")
            return None
        return _normalize_tx_df(df, label, tx_sym, start_date=None)
    except Exception as e:
        print(f"  {label} 股票下载失败: {e}")
        return None
