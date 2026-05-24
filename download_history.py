"""历史数据下载编排。

数据源适配器已拆分到 data_sources/ 目录。本文件只负责：
- save_parquet（规范化 + 原子写入）
- main（下载编排入口）
"""
from pathlib import Path
import os
import tempfile
import time

import akshare as ak
import pandas as pd

from core.price_schema import is_price_like, normalize_price_frame

DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)


# ── 写入工具 ──────────────────────────────────────────────────

def _normalize_history_frame(df):
    df = df.copy()
    if '日期' in df.columns:
        df.rename(columns={'日期': 'date'}, inplace=True)
    if '收盘' in df.columns:
        df.rename(columns={'收盘': 'close'}, inplace=True)
    if 'date' in df.columns:
        date_str = df['date'].astype(str)
        if date_str.str.contains('年').any():
            df['date'] = date_str.str.replace(r'年|月份?', '-', regex=True).str.rstrip('-')
        elif date_str.str.match(r'^\d{6}$').all():
            df['date'] = date_str + '01'
        df['date'] = pd.to_datetime(df['date'], format='mixed')
        df = df.dropna(subset=['date']).sort_values('date')
    return df


def _atomic_write_parquet(df, file_path: Path):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            dir=file_path.parent,
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        df.to_parquet(tmp_path, index=False)
        check = pd.read_parquet(tmp_path)
        if check.empty:
            raise ValueError("written parquet readback is empty")
        os.replace(tmp_path, file_path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def save_parquet(df, name):
    if df is None or df.empty:
        print(f"  {name} 无数据，保留已有文件")
        return False
    df = _normalize_history_frame(df)
    if df.empty:
        print(f"  {name} 规范化后无数据，保留已有文件")
        return False
    if is_price_like(name):
        df = normalize_price_frame(df, name)
    file_path = DATA_DIR / f"{name}.parquet"
    _atomic_write_parquet(df, file_path)
    print(f"  {name}: {len(df)} 条记录 -> {file_path}")
    return True


# ── 数据源导入 ────────────────────────────────────────────────
from data_sources.domestic_futures import fetch_tushare_futures, fetch_pork_futures_far  # noqa: E402
from data_sources.fred import fetch_fred_csv, fetch_brent_oil  # noqa: E402
from data_sources.eia import fetch_eia_crude_stock  # noqa: E402
from data_sources.macro_china import fetch_pboc_social_financing  # noqa: E402
from data_sources.foreign import fetch_cbot_soybean  # noqa: E402
from data_sources.spot import fetch_pork_spot  # noqa: E402
from data_sources.equity import fetch_etf_hist, fetch_stock_hist  # noqa: E402


# ── 下载编排 ──────────────────────────────────────────────────

def main():
    print("开始下载历史数据...")

    # ==================== 国内期货（Tushare）====================
    print("\n--- 国内期货（Tushare）---")

    futures_map = [
        ("生猪期货", "LH.DCE", "pork_futures"),
        ("鸡蛋期货", "JD.DCE", "egg_futures"),
        ("豆粕期货", "M.DCE", "soybean_meal_futures"),
        ("玉米期货", "C.DCE", "corn_futures"),
        ("国产大豆", "A.DCE", "soybean_domestic_futures"),
        ("进口大豆", "B.DCE", "soybean_import_futures"),
        ("菜粕期货", "RM.ZCE", "rapeseed_meal_futures"),
        ("豆油期货", "Y.DCE", "soybean_oil_futures"),
        ("原油期货", "SC.INE", "crude_oil_futures"),
        ("铜期货", "CU.SHF", "copper_futures"),
        ("铝期货", "AL.SHF", "aluminum_futures"),
        ("螺纹钢", "RB.SHF", "rebar_futures"),
        ("黄金期货", "AU.SHF", "gold_futures"),
        ("白银期货", "AG.SHF", "silver_futures"),
        ("动力煤", "ZC.ZCE", "thermal_coal_futures"),
        ("铁矿石", "I.DCE", "iron_ore_futures"),
    ]

    for i, (name, code, filename) in enumerate(futures_map, 1):
        print(f"{i}. {name}")
        df = fetch_tushare_futures(code, name)
        if df is not None:
            save_parquet(df, filename)
        time.sleep(0.5)

    print("17. 生猪远月/主力期货代理")
    try:
        far = fetch_pork_futures_far()
        if far is not None:
            save_parquet(far, "pork_futures_far")
    except Exception as e:
        print(f"  生猪远月/主力期货代理下载失败: {e}")

    # ==================== 宏观数据（AKShare）====================
    print("\n--- 宏观数据（AKShare）---")

    print("18. USD/CNY汇率")
    try:
        forex = fetch_fred_csv("DEXCHUS", "USD/CNY汇率")
        if forex is not None:
            save_parquet(forex, "usd_cny")
    except Exception as e:
        print(f"  汇率下载失败: {e}")

    print("19. 中国CPI")
    try:
        cpi = ak.macro_china_cpi()
        save_parquet(cpi, "cpi")
    except Exception as e:
        print(f"  CPI下载失败: {e}")

    print("20. 中国PMI")
    try:
        pmi = ak.macro_china_pmi()
        save_parquet(pmi, "pmi")
    except Exception as e:
        print(f"  PMI下载失败: {e}")

    print("21. M2货币供应量")
    try:
        m2 = ak.macro_china_money_supply()
        save_parquet(m2, "m2")
    except Exception as e:
        print(f"  M2下载失败: {e}")

    print("22. 社融规模增量")
    try:
        sf = fetch_pboc_social_financing()
        if sf is not None:
            save_parquet(sf, "social_financing")
        else:
            sf = ak.macro_china_shrzgm()
            save_parquet(sf, "social_financing")
    except Exception as e:
        print(f"  社融下载失败: {e}")

    # ==================== 外盘数据（AKShare）====================
    print("\n--- 外盘数据（AKShare）---")

    print("22. 布伦特原油")
    try:
        brent = fetch_brent_oil()
        if brent is not None:
            save_parquet(brent, "brent_oil")
        else:
            brent = ak.energy_oil_hist()
            save_parquet(brent, "brent_oil")
    except Exception as e:
        print(f"  布伦特原油下载失败: {e}")

    print("23. 天然气期货(NG)")
    try:
        ng = ak.futures_foreign_hist(symbol="NG")
        save_parquet(ng, "natural_gas_futures")
    except Exception as e:
        print(f"  天然气下载失败: {e}")

    print("24. CBOT大豆")
    try:
        cbot = fetch_cbot_soybean()
        if cbot is not None:
            save_parquet(cbot, "cbot_soybean")
    except Exception as e:
        print(f"  CBOT大豆下载失败: {e}")

    print("25. 美国CPI")
    try:
        us_cpi = fetch_fred_csv("CPIAUCSL", "美国CPI")
        if us_cpi is not None:
            save_parquet(us_cpi, "us_cpi")
    except Exception as e:
        print(f"  美国CPI下载失败: {e}")

    print("26. EIA原油库存")
    try:
        eia = fetch_eia_crude_stock()
        if eia is not None:
            save_parquet(eia, "eia_crude_stock")
        else:
            eia = ak.macro_usa_eia_crude_rate()
            save_parquet(eia, "eia_crude_stock")
    except Exception as e:
        print(f"  EIA库存下载失败: {e}")

    print("27. QVIX波动率")
    try:
        vix = ak.index_option_300etf_qvix()
        if vix is not None and 'open' in vix.columns:
            vix = vix.dropna(subset=['open', 'high', 'low', 'close'])
        save_parquet(vix, "vix")
    except Exception as e:
        print(f"  QVIX下载失败: {e}")

    print("28. TIPS收益率")
    try:
        tips = fetch_fred_csv("DFII10", "TIPS收益率")
        if tips is not None:
            save_parquet(tips, "tips_yield")
    except Exception as e:
        print(f"  TIPS下载失败: {e}")

    print("\n--- 现货数据 ---")

    print("29. 生猪现货")
    try:
        pork_spot = fetch_pork_spot()
        if pork_spot is not None:
            save_parquet(pork_spot, "pork_spot")
    except Exception as e:
        print(f"  生猪现货下载失败: {e}")

    print("\n--- 股票/ETF 数据 ---")

    print("30. 养殖ETF(159865)")
    try:
        breeding_etf = fetch_etf_hist("159865", "养殖ETF")
        if breeding_etf is not None:
            save_parquet(breeding_etf, "breeding_etf")
    except Exception as e:
        print(f"  养殖ETF下载失败: {e}")

    print("31. 黄金ETF(518880)")
    try:
        gold_etf = fetch_etf_hist("518880", "黄金ETF")
        if gold_etf is not None:
            save_parquet(gold_etf, "gold_etf")
    except Exception as e:
        print(f"  黄金ETF下载失败: {e}")

    print("32. 中国石油(601857)")
    try:
        petrochina = fetch_stock_hist("601857", "中国石油")
        if petrochina is not None:
            save_parquet(petrochina, "petrochina_stock")
    except Exception as e:
        print(f"  中国石油下载失败: {e}")

    print("\n--- 暂不支持的数据 ---")
    print("  鸡肉现货(chicken_spot) - 未接入：尚未找到稳定公开历史接口；不使用网页 HTML 解析，不以白条鸡批发价冒充白羽肉鸡棚前价")

    print("\n历史数据下载完成！")


if __name__ == "__main__":
    main()
