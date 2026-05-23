"""外盘数据源（AKShare 外盘期货）。"""

import pandas as pd
import akshare as ak


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
