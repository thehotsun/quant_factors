"""EIA 数据源（美国能源信息署）。"""

import pandas as pd
import requests


def fetch_eia_crude_stock():
    """从 EIA 官网下载美国原油库存周度数据（XLS 格式）"""
    try:
        from io import BytesIO
        url = 'https://ir.eia.gov/wpsr/psw04.xls'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        df = pd.read_excel(BytesIO(r.content), sheet_name='Data 1', header=None)
        records = []
        for i in range(3, len(df)):
            date_val = df.iloc[i, 0]
            total_stocks = df.iloc[i, 1]
            commercial = df.iloc[i, 2]
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
        result['weekly_change'] = result['commercial_stocks_kb'].diff()
        print(f"  EIA原油库存: {len(result)} 条, {result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:
        print(f"  EIA原油库存下载失败: {e}")
        return None
