"""中国宏观数据源（央行社融等）。"""

import pandas as pd
import requests


def fetch_pboc_social_financing():
    """从央行官网抓取社会融资规模增量数据（XLSX 格式），并与 AKShare 历史数据合并"""
    try:
        from io import BytesIO
        import re
        import akshare as ak

        page_url = "http://www.pbc.gov.cn/diaochatongjisi/116219/116319/2026ntjsj/shrzgm/index.html"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(page_url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
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

        data_start = None
        for i in range(len(df_raw)):
            val = str(df_raw.iloc[i, 0])
            if re.match(r'\d{4}\.\d{2}$', val):
                data_start = i
                break
        if data_start is None:
            print("  央行社融数据起始行未找到")
            return None

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

        try:
            ak_df = ak.macro_china_shrzgm()
            if ak_df is not None and len(ak_df) > 0:
                if 'date' not in ak_df.columns:
                    ak_df['date'] = pd.to_datetime(ak_df['月份'].astype(str) + '01', format='%Y%m%d')
                ak_df = ak_df[ak_df['date'] < '2026-01-01']
                combined = pd.concat([ak_df, pboc_df], ignore_index=True)
                combined = combined.sort_values('date')
                combined.reset_index(drop=True, inplace=True)
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
