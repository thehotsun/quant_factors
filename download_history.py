import akshare as ak
import pandas as pd
import requests
from pathlib import Path
import os
import tempfile
import time
from core.config import get_tushare_pro

DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)


def _pro():
    return get_tushare_pro()


def _normalize_history_frame(df):
    df = df.copy()
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
        # Read back before replacing so a broken write cannot clobber existing data.
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
    file_path = DATA_DIR / f"{name}.parquet"
    _atomic_write_parquet(df, file_path)
    print(f"  {name}: {len(df)} 条记录 -> {file_path}")
    return True


def fetch_brent_oil():
    """从 FRED 下载布伦特原油价格（日度）"""
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU&cosd=2020-01-01'
        df = pd.read_csv(url)
        df = df.rename(columns={'observation_date': 'date', 'DCOILBRENTEU': 'close'})
        df['date'] = pd.to_datetime(df['date'])
        # 替换 "." 为 NaN（FRED 用 "." 表示缺失）
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])
        df = df.sort_values('date')
        df.reset_index(drop=True, inplace=True)
        print(f"  布伦特原油(FRED): {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}")
        return df
    except Exception as e:
        print(f"  布伦特原油下载失败: {e}")
        return None


def fetch_eia_crude_stock():
    """从 EIA 官网下载美国原油库存周度数据（XLS 格式）"""
    try:
        from io import BytesIO
        url = 'https://ir.eia.gov/wpsr/psw04.xls'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        df = pd.read_excel(BytesIO(r.content), sheet_name='Data 1', header=None)
        # Row 1 = sourcekey, Row 2 = description, Data starts from Row 3
        # Column 0 = Date, Column 1 = WCESTUS1 (Weekly U.S. Ending Stocks of Crude Oil)
        # Column 2 = WCESTP11 (Ending Stocks excluding SPR)
        records = []
        for i in range(3, len(df)):
            date_val = df.iloc[i, 0]
            total_stocks = df.iloc[i, 1]  # Total including SPR
            commercial = df.iloc[i, 2]    # Excluding SPR
            if pd.isna(date_val) or pd.isna(total_stocks):
                continue
            records.append({
                'date': pd.to_datetime(date_val),
                'total_stocks_kb': float(total_stocks),
                'commercial_stocks_kb': float(commercial) if pd.notna(commercial) else None,
            })

        result = pd.DataFrame(records)
        result = result.sort_values('date')
        result.reset_index(drop=True, inplace=True)
        # 计算变化率（周环比）
        result['weekly_change'] = result['commercial_stocks_kb'].diff()
        print(f"  EIA原油库存: {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  EIA原油库存下载失败: {e}")
        return None


def fetch_fred_csv(series_id, name, start_date="2020-01-01"):
    """从 FRED 直接下载 CSV 数据"""
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
        df = pd.read_csv(url)
        df = df.rename(columns={'observation_date': 'date'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        return df
    except Exception as e:
        print(f"  {name} 下载失败: {e}")
        return None


def fetch_cbot_soybean():
    """下载 CBOT 大豆连续合约历史数据。

    AKShare 的外盘期货接口中，CBOT Soybean 对应 symbol="S"。
    返回字段已包含 date/open/high/low/close，可直接供 CbotSoybeanFactor 使用。
    """
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


def fetch_pboc_social_financing():
    """从央行官网抓取社会融资规模增量数据（XLSX 格式），并与 AKShare 历史数据合并"""
    try:
        from io import BytesIO
        import re
        # 央行社融数据页面
        page_url = "http://www.pbc.gov.cn/diaochatongjisi/116219/116319/2026ntjsj/shrzgm/index.html"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(page_url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        # 解析 XLS 链接
        xlsx_match = re.search(r'(http://[^"\s]+\.xlsx)', r.text)
        if not xlsx_match:
            match = re.search(r'href="([^"]+\.xlsx)"', r.text)
            if match:
                xlsx_url = f"http://www.pbc.gov.cn{match.group(1)}"
            else:
                print("  央行社融 XLS 链接未找到")
                return None
        else:
            xlsx_url = xlsx_match.group(1)

        r2 = requests.get(xlsx_url, headers=headers, timeout=15)
        df_raw = pd.read_excel(BytesIO(r2.content), header=None)

        # 找到数据起始行（包含 "2026.01" 或类似格式的行）
        data_start = None
        for i in range(len(df_raw)):
            val = str(df_raw.iloc[i, 0])
            if re.match(r'\d{4}\.\d{2}$', val):
                data_start = i
                break
        if data_start is None:
            print("  央行社融数据起始行未找到")
            return None

        # 解析数据
        rows = []
        for i in range(data_start, len(df_raw)):
            month_str = str(df_raw.iloc[i, 0]).strip()
            if not re.match(r'\d{4}\.\d{2}$', month_str):
                break
            total = df_raw.iloc[i, 1]
            if pd.isna(total) or str(total).strip() == '':
                continue
            row = {
                '月份': month_str,
                '社会融资规模增量': float(total),
            }
            col_map = {
                '其中-人民币贷款': 2,
                '其中-委托贷款外币贷款': 3,
                '其中-委托贷款': 4,
                '其中-信托贷款': 5,
                '其中-未贴现银行承兑汇票': 6,
                '其中-企业债券': 7,
                '其中-非金融企业境内股票融资': 9,
            }
            for col_name, col_idx in col_map.items():
                val = df_raw.iloc[i, col_idx]
                row[col_name] = float(val) if pd.notna(val) and str(val).strip() != '' else 0
            rows.append(row)

        if not rows:
            print("  央行社融数据为空")
            return None

        pboc_df = pd.DataFrame(rows)
        pboc_df['月份'] = pboc_df['月份'].str.replace('.', '')
        pboc_df['date'] = pd.to_datetime(pboc_df['月份'] + '01', format='%Y%m%d')
        print(f"  央行社融 2026 数据: {len(pboc_df)} 条")

        # 获取 AKShare 历史数据（2015-2025）
        try:
            ak_df = ak.macro_china_shrzgm()
            if ak_df is not None and len(ak_df) > 0:
                if 'date' not in ak_df.columns:
                    ak_df['date'] = pd.to_datetime(ak_df['月份'].astype(str) + '01', format='%Y%m%d')
                # 合并，央行数据优先（覆盖 AKShare 可能缺失的 2026 数据）
                ak_df = ak_df[ak_df['date'] < '2026-01-01']
                combined = pd.concat([ak_df, pboc_df], ignore_index=True)
                combined = combined.sort_values('date')
                combined.reset_index(drop=True, inplace=True)
                # 删除多余的 '月份' 列，避免 save_parquet 冲突
                if '月份' in combined.columns:
                    combined.drop(columns=['月份'], inplace=True)
                print(f"  合并后社融数据: {len(combined)} 条 (历史 {len(ak_df)} + 央行 {len(pboc_df)})")
                return combined
        except Exception as e:
            print(f"  AKShare 历史数据获取失败: {e}")

        if '月份' in pboc_df.columns:
            pboc_df.drop(columns=['月份'], inplace=True)
        return pboc_df
    except Exception as e:
        print(f"  央行社融抓取失败: {e}")
        return None


def fetch_tushare_futures(ts_code, name, start_date="20200101"):
    """从 Tushare 获取期货主力合约日线数据"""
    try:
        df = _pro().fut_daily(ts_code=ts_code, start_date=start_date)
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
        forex = fetch_fred_csv("DEXCHUS", "USD/CNY汇率")
        if forex is not None:
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
        sf = fetch_pboc_social_financing()
        if sf is not None:
            save_parquet(sf, "social_financing")
        else:
            # 回退到 AKShare
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
            # 回退到 AKShare
            eia = ak.macro_usa_eia_crude_rate()
            save_parquet(eia, "eia_crude_stock")
    except Exception as e:
        print(f"  EIA库存下载失败: {e}")

    print("27. QVIX波动率")
    try:
        vix = ak.index_option_300etf_qvix()
        # QVIX 2019-12 才上线，过滤掉上线前的空行
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

    # ==================== 暂不支持的数据 ====================
    print("\n--- 暂不支持的数据 ---")
    print("  鸡肉现货 - 接口已变更，尚未找到稳定历史源")
    print("  生猪远月期货 - 需要合约链/远月连续口径，尚未接入")

    print("\n历史数据下载完成！")


if __name__ == "__main__":
    main()
