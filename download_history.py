import akshare as ak
import tushare as ts
import pandas as pd
from pathlib import Path
import os
import time

DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)

# Tushare 配置
TUSHARE_TOKEN = "165fb826f4b6e41aeb37ef84b7f4c99df784cbfec771ee139dfae048"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


def save_parquet(df, name):
    if df is None or df.empty:
        print(f"  {name} 无数据")
        return
    if '日期' in df.columns:
        df.rename(columns={'日期': 'date'}, inplace=True)
    if '月份' in df.columns:
        df.rename(columns={'月份': 'date'}, inplace=True)
    if '收盘' in df.columns:
        df.rename(columns={'收盘': 'close'}, inplace=True)
    if 'date' in df.columns:
        # 处理各种日期格式
        date_str = df['date'].astype(str)
        if date_str.str.contains('年').any():
            # 中文格式: "2026年04月份"
            df['date'] = date_str.str.replace(r'年|月份?', '-', regex=True).str.rstrip('-')
        elif date_str.str.match(r'^\d{6}$').all():
            # YYYYMM格式: "201501"
            df['date'] = date_str + '01'  # 补充日期为01
        df['date'] = pd.to_datetime(df['date'], format='mixed')
        df = df.sort_values('date')
    file_path = DATA_DIR / f"{name}.parquet"
    tmp_path = DATA_DIR / f"{name}.parquet.tmp"
    df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, file_path)
    print(f"  {name}: {len(df)} 条记录 -> {file_path}")


def fetch_tushare_futures(ts_code, name, start_date="20200101"):
    """从 Tushare 获取期货主力合约日线数据"""
    try:
        df = pro.fut_daily(ts_code=ts_code, start_date=start_date)
        if df is not None and not df.empty:
            # 重命名列以匹配原有格式
            df = df.rename(columns={
                'trade_date': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'vol': 'volume',
                'amount': 'amount',
                'oi': 'open_interest'
            })
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        return df
    except Exception as e:
        print(f"  {name} 下载失败: {e}")
        return None


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
        time.sleep(0.5)  # 避免频率限制

    # ==================== 宏观数据（AKShare）====================
    print("\n--- 宏观数据（AKShare）---")

    print("17. USD/CNY汇率")
    try:
        forex = ak.currency_boc_sina(symbol="美元")
        save_parquet(forex, "usd_cny")
    except Exception as e:
        print(f"  汇率下载失败: {e}")

    print("18. 中国CPI")
    try:
        cpi = ak.macro_china_cpi()
        save_parquet(cpi, "cpi")
    except Exception as e:
        print(f"  CPI下载失败: {e}")

    print("19. 中国PMI")
    try:
        pmi = ak.macro_china_pmi()
        save_parquet(pmi, "pmi")
    except Exception as e:
        print(f"  PMI下载失败: {e}")

    print("20. M2货币供应量")
    try:
        m2 = ak.macro_china_money_supply()
        save_parquet(m2, "m2")
    except Exception as e:
        print(f"  M2下载失败: {e}")

    print("21. 社融规模增量")
    try:
        sf = ak.macro_china_shrzgm()
        save_parquet(sf, "social_financing")
    except Exception as e:
        print(f"  社融下载失败: {e}")

    # ==================== 外盘数据（AKShare）====================
    print("\n--- 外盘数据（AKShare）---")

    print("22. 布伦特原油")
    try:
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

    print("24. 美国CPI")
    try:
        us_cpi = ak.macro_usa_cpi_monthly()
        save_parquet(us_cpi, "us_cpi")
    except Exception as e:
        print(f"  美国CPI下载失败: {e}")

    print("25. EIA原油库存")
    try:
        eia = ak.macro_usa_eia_crude_rate()
        save_parquet(eia, "eia_crude_stock")
    except Exception as e:
        print(f"  EIA库存下载失败: {e}")

    print("26. QVIX波动率")
    try:
        vix = ak.index_option_300etf_qvix()
        save_parquet(vix, "vix")
    except Exception as e:
        print(f"  QVIX下载失败: {e}")

    # ==================== 暂不支持的数据 ====================
    print("\n--- 暂不支持的数据 ---")
    print("  CBOT大豆 - 无可用接口")
    print("  TIPS收益率 - 无可用接口")
    print("  鸡肉现货 - 接口已变更")

    print("\n历史数据下载完成！")


if __name__ == "__main__":
    main()
