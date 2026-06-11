"""现货数据源适配器。

目前支持：
- 生猪现货（pork_spot）：来自生意社 100ppi.com，通过 akshare futures_spot_price_daily 获取
- 鸡肉现货（chicken_spot）：暂无稳定公开接口，继续 known_missing
- 黄金现货（gold_spot）：上海金交所 Au99.99，spot_hist_sge 接口，实时无延迟
- 白银现货（silver_spot）：上海金交所 Ag99.99，spot_hist_sge 接口，实时无延迟
- 铂金现货（platinum_spot）：上海金交所 Pt99.95，spot_hist_sge 接口，实时无延迟
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

        # spot_price 列是现货价格
        result = df[["date", "spot_price"]].copy()
        result = result.rename(columns={"spot_price": "close"})
        result["date"] = pd.to_datetime(result["date"].astype(str), format="%Y%m%d", errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result["source"] = "akshare.futures_spot_price_daily:LH.spot_price"
        result = result.dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)

        print(f"  生猪现货: {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  生猪现货下载失败: {e}")
        return None


def fetch_gold_spot():
    """获取黄金现货价格（上海金交所 Au99.99）。

    数据来源：akshare spot_hist_sge
    使用 close 价作为日收盘价（实时更新，无延迟）。
    """
    import akshare as ak

    try:
        df = ak.spot_hist_sge(symbol='Au99.99')
        if df is None or df.empty:
            print("  黄金现货数据为空")
            return None

        result = df[["date", "close"]].copy()
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result["source"] = "akshare.spot_hist_sge:Au99.99.close"
        result = result.dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)

        print(f"  黄金现货(Au99.99): {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  黄金现货下载失败: {e}")
        return None


def fetch_silver_spot():
    """获取白银现货价格（上海金交所 Ag99.99）。

    数据来源：akshare spot_hist_sge
    使用 close 价作为日收盘价（实时更新，无延迟）。
    """
    import akshare as ak

    try:
        df = ak.spot_hist_sge(symbol='Ag99.99')
        if df is None or df.empty:
            print("  白银现货数据为空")
            return None

        result = df[["date", "close"]].copy()
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result["source"] = "akshare.spot_hist_sge:Ag99.99.close"
        result = result.dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)

        print(f"  白银现货(Ag99.99): {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  白银现货下载失败: {e}")
        return None


def fetch_platinum_spot():
    """获取铂金现货价格（上海金交所 Pt99.95）。

    数据来源：akshare spot_hist_sge
    使用 close 价作为日收盘价（实时更新，无延迟）。
    """
    import akshare as ak

    try:
        df = ak.spot_hist_sge(symbol='Pt99.95')
        if df is None or df.empty:
            print("  铂金现货数据为空")
            return None

        result = df[["date", "close"]].copy()
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result["source"] = "akshare.spot_hist_sge:Pt99.95.close"
        result = result.dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)

        print(f"  铂金现货(Pt99.95): {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  铂金现货下载失败: {e}")
        return None


def _fetch_spot_from_bizhi(vars_list: list, name: str, start_day: str = "20200101"):
    """通用现货数据下载（生意社 futures_spot_price_daily）。

    数据来源：akshare futures_spot_price_daily
    取 spot_price 作为现货价格。
    注意：该接口逐日请求，速度较慢，但只是一次性下载。
    """
    import akshare as ak
    import warnings
    warnings.filterwarnings("ignore")

    try:
        end_day = pd.Timestamp.today().strftime("%Y%m%d")
        df = ak.futures_spot_price_daily(start_day=start_day, end_day=end_day, vars_list=vars_list)
        if df is None or df.empty:
            print(f"  {name}现货数据为空")
            return None

        result = df[["date", "spot_price"]].copy()
        result = result.rename(columns={"spot_price": "close"})
        result["date"] = pd.to_datetime(result["date"].astype(str), format="%Y%m%d", errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result["source"] = f"akshare.futures_spot_price_daily:{vars_list[0]}.spot_price"
        result = result.dropna(subset=["date", "close"]).sort_values("date")
        result.reset_index(drop=True, inplace=True)

        print(f"  {name}现货: {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  {name}现货下载失败: {e}")
        return None


def fetch_copper_spot(start_day: str = "20200101"):
    """获取铜现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["CU"], "铜", start_day)


def fetch_corn_spot(start_day: str = "20200101"):
    """获取玉米现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["C"], "玉米", start_day)


def fetch_soybean_meal_spot(start_day: str = "20200101"):
    """获取豆粕现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["M"], "豆粕", start_day)


def fetch_egg_spot(start_day: str = "20200101"):
    """获取鸡蛋现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["JD"], "鸡蛋", start_day)


def fetch_soybean_oil_spot(start_day: str = "20200101"):
    """获取豆油现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["Y"], "豆油", start_day)


def fetch_rapeseed_meal_spot(start_day: str = "20200101"):
    """获取菜粕现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["RM"], "菜粕", start_day)


def fetch_rebar_spot(start_day: str = "20200101"):
    """获取螺纹钢现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["RB"], "螺纹钢", start_day)


def fetch_iron_ore_spot(start_day: str = "20200101"):
    """获取铁矿石现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["I"], "铁矿石", start_day)


def fetch_aluminum_spot(start_day: str = "20200101"):
    """获取铝现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["AL"], "铝", start_day)


def fetch_soybean_domestic_spot(start_day: str = "20200101"):
    """获取国产大豆现货价格（生意社）。"""
    return _fetch_spot_from_bizhi(["A"], "国产大豆", start_day)
