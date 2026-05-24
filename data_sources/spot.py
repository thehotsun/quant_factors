"""现货数据源适配器。

目前支持：
- 生猪现货（pork_spot）：来自生意社 100ppi.com，通过 akshare futures_spot_price_daily 获取
- 鸡肉现货（chicken_spot）：暂无稳定公开接口，继续 known_missing
"""

import pandas as pd


def fetch_pork_spot(start_day="20200101", end_day=None):
    """获取生猪现货价格数据。

    数据来源：生意社(100ppi.com)，通过 akshare futures_spot_price_daily 接口。
    返回 DataFrame 包含 date, close, source 列。
    """
    import akshare as ak

    if end_day is None:
        end_day = pd.Timestamp.today().strftime("%Y%m%d")

    try:
        df = ak.futures_spot_price_daily(start_day=start_day, end_day=end_day, vars_list=["LH"])
        if df is None or df.empty:
            print("  生猪现货数据为空")
            return None

        # sp 列是现货价格
        result = df[["date", "sp"]].copy()
        result = result.rename(columns={"sp": "close"})
        result["date"] = pd.to_datetime(result["date"].astype(str), format="%Y%m%d", errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result["source"] = "akshare.futures_spot_price_daily:LH.sp"
        result = result.dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)

        print(f"  生猪现货: {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  生猪现货下载失败: {e}")
        return None
