"""国内期货数据源（akshare + Tushare 兼容）。"""

import pandas as pd

# tushare ts_code → akshare 新浪主力合约代码
_TS_TO_SINA = {
    'LH.DCE': 'LH0',   # 生猪
    'JD.DCE': 'JD0',   # 鸡蛋
    'M.DCE': 'M0',     # 豆粕
    'C.DCE': 'C0',     # 玉米
    'A.DCE': 'A0',     # 国产大豆
    'B.DCE': 'B0',     # 进口大豆
    'RM.ZCE': 'RM0',   # 菜粕
    'Y.DCE': 'Y0',     # 豆油
    'SC.INE': 'SC0',   # 原油
    'CU.SHF': 'CU0',   # 铜
    'AL.SHF': 'AL0',   # 铝
    'RB.SHF': 'RB0',   # 螺纹钢
    'AU.SHF': 'AU0',   # 黄金
    'AG.SHF': 'AG0',   # 白银
    'I.DCE': 'I0',     # 铁矿石
}


def fetch_akshare_futures(ts_code, name, start_date="20200101"):
    """从 akshare（新浪期货）获取主力合约日线数据。

    返回与旧 tushare 格式兼容的 DataFrame，包含:
    date, open, high, low, close, settle, volume, open_interest 列。
    """
    import akshare as ak

    sina_sym = _TS_TO_SINA.get(ts_code)
    if not sina_sym:
        print(f"  {name} 无 akshare 映射: {ts_code}")
        return None

    try:
        df = ak.futures_zh_daily_sina(symbol=sina_sym)
        if df is None or df.empty:
            print(f"  {name} akshare 数据为空")
            return None

        df = df.rename(columns={
            'hold': 'open_interest',
        })
        df['date'] = pd.to_datetime(df['date'])
        # 过滤起始日期
        df = df[df['date'] >= pd.Timestamp(start_date)]
        df = df.sort_values('date').reset_index(drop=True)
        # 确保数值列
        for col in ['open', 'high', 'low', 'close', 'settle', 'volume', 'open_interest']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception as e:
        print(f"  {name} akshare下载失败: {e}")
        return None


# 向后兼容：保留旧函数名，默认走 akshare
def fetch_tushare_futures(ts_code, name, start_date="20200101"):
    """获取期货主力合约日线数据（优先 akshare，回退 tushare）。"""
    df = fetch_akshare_futures(ts_code, name, start_date)
    if df is not None and not df.empty:
        return df

    # 回退 tushare
    try:
        from core.config import get_tushare_pro
        pro = get_tushare_pro()
        df = pro.fut_daily(ts_code=ts_code, start_date=start_date)
        if df is not None and not df.empty:
            df = df.rename(columns={
                'trade_date': 'date', 'vol': 'volume', 'oi': 'open_interest'
            })
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        return df
    except Exception as e:
        print(f"  {name} tushare回退也失败: {e}")
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
