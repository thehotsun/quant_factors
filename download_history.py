import akshare as ak
import pandas as pd
from pathlib import Path

DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)

def save_parquet(df, name):
    if df is None or df.empty:
        print(f"  {name} 无数据")
        return
    if '日期' in df.columns:
        df.rename(columns={'日期': 'date'}, inplace=True)
    if '月份' in df.columns:
        df.rename(columns={'月份': 'date'}, inplace=True)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
    file_path = DATA_DIR / f"{name}.parquet"
    df.to_parquet(file_path, index=False)
    print(f"  {name}: {len(df)} 条记录 -> {file_path}")


def main():
    print(" 开始下载历史数据...")

    # ==================== 原有数据 ====================
    print("\n--- 原有数据 ---")
    print("1. 生猪期货(主力)")
    save_parquet(ak.futures_main_sina(symbol="LH"), "pork_futures")

    print("1b. 生猪期货(远月)")
    try:
        save_parquet(ak.futures_zh_daily_sina(symbol="LH2701"), "pork_futures_far")
    except Exception as e:
        print(f"  生猪远月下载失败: {e}")

    print("2. 布伦特原油")
    oil = ak.energy_oil_hist()
    if '日期' in oil.columns:
        oil.rename(columns={'日期': 'date', '收盘': 'close'}, inplace=True)
    save_parquet(oil, "brent_oil")

    save_parquet(ak.macro_usa_cpi(), "us_cpi")

    print("5. 中国PMI")
    save_parquet(ak.macro_china_pmi(), "pmi")

    # ==================== 肉类数据 ====================
    print("\n--- 肉类数据 ---")
    print("7. 鸡蛋期货")
    save_parquet(ak.futures_main_sina(symbol="JD"), "egg_futures")

    print("8. 鸡肉现货(白羽肉鸡)")
    try:
        chicken = ak.futures_spot_price(symbol="白羽肉鸡")
        save_parquet(chicken, "chicken_spot")
    except Exception as e:
        print(f"  鸡肉现货下载失败: {e}")

    # ==================== 饲料数据 ====================
    print("\n--- 饲料数据 ---")
    print("11. 豆粕期货")
    save_parquet(ak.futures_main_sina(symbol="M"), "soybean_meal_futures")

    print("12. 玉米期货")
    save_parquet(ak.futures_main_sina(symbol="C"), "corn_futures")

    print("13. 国产大豆期货(A)")
    save_parquet(ak.futures_main_sina(symbol="A"), "soybean_domestic_futures")

    print("14. 进口大豆期货(B)")
    save_parquet(ak.futures_main_sina(symbol="B"), "soybean_import_futures")

    print("15. 菜粕期货")
    save_parquet(ak.futures_main_sina(symbol="RM"), "rapeseed_meal_futures")

    print("16. 豆油期货")
    save_parquet(ak.futures_main_sina(symbol="Y"), "soybean_oil_futures")

    # ==================== 宏观数据 ====================
    print("\n--- 宏观数据 ---")
    print("17. USD/CNY汇率")
    try:
        forex = ak.currency_boc_sina(symbol="美元")
        save_parquet(forex, "usd_cny")
    except Exception as e:
        print(f"  汇率下载失败: {e}")

    print("18. CBOT大豆")
    try:
        cbot = ak.futures_foreign_hist(symbol="ZS")
        save_parquet(cbot, "cbot_soybean")
    except Exception as e:
        print(f"  CBOT大豆下载失败: {e}")

    print("19. 中国CPI")
    try:
        cpi = ak.macro_china_cpi()
        save_parquet(cpi, "cpi")
    except Exception as e:
        print(f"  CPI下载失败: {e}")

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

    # ==================== 能源数据 ====================
    print("\n--- 能源数据 ---")
    print("22. 原油期货(SC)")
    save_parquet(ak.futures_main_sina(symbol="SC"), "crude_oil_futures")

    print("23. 天然气期货(NG)")
    try:
        ng = ak.futures_foreign_hist(symbol="NG")
        save_parquet(ng, "natural_gas_futures")
    except Exception as e:
        print(f"  天然气下载失败: {e}")

    # ==================== 金属数据 ====================
    print("\n--- 金属数据 ---")
    print("24. 铜期货(CU)")
    save_parquet(ak.futures_main_sina(symbol="CU"), "copper_futures")

    print("25. 铝期货(AL)")
    save_parquet(ak.futures_main_sina(symbol="AL"), "aluminum_futures")

    print("26. 螺纹钢期货(RB)")
    save_parquet(ak.futures_main_sina(symbol="RB"), "rebar_futures")

    print("27. 黄金期货(AU)")
    save_parquet(ak.futures_main_sina(symbol="AU"), "gold_futures")
    print("28. 白银期货(AG)")
    save_parquet(ak.futures_main_sina(symbol="AG"), "silver_futures")

    print("29. 动力煤期货(ZC)")
    try:
        save_parquet(ak.futures_main_sina(symbol="ZC"), "thermal_coal_futures")
    except Exception as e:
        print(f"  动力煤下载失败: {e}")

    print("30. 铁矿石期货(I)")
    try:
        save_parquet(ak.futures_main_sina(symbol="I"), "iron_ore_futures")
    except Exception as e:
        print(f"  铁矿石下载失败: {e}")

    # ==================== 海外数据 ====================
    print("\n--- 海外数据 ---")
    print("31. EIA原油库存")
    try:
        eia = ak.energy_eia_crude()
        save_parquet(eia, "eia_crude_stock")
    except Exception as e:
        print(f"  EIA库存下载失败: {e}（AKShare可能暂不支持此接口）")

    print("32. 美国TIPS收益率(实际利率)")
    try:
        tips = ak.macro_usa_tips_yield()
        save_parquet(tips, "tips_yield")
    except Exception as e:
        print(f"  TIPS下载失败: {e}")

    print("33. VIX恐慌指数")
    try:
        vix = ak.index_vix()
        save_parquet(vix, "vix")
    except Exception as e:
        print(f"  VIX下载失败: {e}")

    print("\n 历史数据下载完成！")


if __name__ == "__main__":
    main()