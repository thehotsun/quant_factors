"""国内期货数据源（Tushare）。"""

import pandas as pd
from core.config import get_tushare_pro


def _pro():
    return get_tushare_pro()


def fetch_tushare_futures(ts_code, name, start_date="20200101"):
    """从 Tushare 获取期货主力合约日线数据"""
    try:
        df = _pro().fut_daily(ts_code=ts_code, start_date=start_date)
        if df is not None and not df.empty:
            df = df.rename(columns={
                'trade_date': 'date',
                'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close',
                'vol': 'volume', 'amount': 'amount', 'oi': 'open_interest'
            })
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        return df
    except Exception as e:
        print(f"  {name} 下载失败: {e}")
        return None


def fetch_pork_futures_far(start_day="20240101", end_day=None):
    """Fetch pork futures far/dominant contract proxy from basis data."""
    import akshare as ak
    try:
        if end_day is None:
            end_day = pd.Timestamp.today().strftime("%Y%m%d")
        df = ak.futures_spot_price_daily(start_day=start_day, end_day=end_day, vars_list=["LH"])
        if df is None or df.empty:
            print("  生猪远月/主力期货基差数据为空")
            return None
        result = df.copy()
        result["date"] = pd.to_datetime(result["date"].astype(str), format="%Y%m%d", errors="coerce")
        result["close"] = pd.to_numeric(result["dominant_contract_price"], errors="coerce")
        result["spot_price"] = pd.to_numeric(result.get("spot_price"), errors="coerce")
        result["basis"] = pd.to_numeric(result.get("dom_basis"), errors="coerce")
        result["basis_rate"] = pd.to_numeric(result.get("dom_basis_rate"), errors="coerce")
        result["contract"] = result.get("dominant_contract")
        result["source"] = "akshare.futures_spot_price_daily:LH.dominant_contract_price"
        keep = ["date", "close", "contract", "spot_price", "basis", "basis_rate", "source"]
        result = result[keep].dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)
        print(f"  生猪远月/主力期货代理: {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  生猪远月/主力期货代理下载失败: {e}")
        return None
