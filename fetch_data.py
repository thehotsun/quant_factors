# fetch_data.py
import akshare as ak
import json
from datetime import datetime

def get_latest_pork():
    # 生猪期货主连
    df = ak.futures_main_sina(symbol='LH0')
    latest = df.iloc[-1]
    return {"current": float(latest['收盘价']), "yesterday": float(df.iloc[-2]['收盘价'])}

def get_latest_cpi():
    # 美国CPI月率
    df = ak.macro_usa_cpi_monthly()
    # 过滤掉今值为空的行
    valid = df.dropna(subset=['今值'])
    if valid.empty:
        return {"expected": 0.3, "actual": 0.3}
    latest = valid.iloc[-1]
    return {"expected": float(latest['预测值']), "actual": float(latest['今值'])}

if __name__ == '__main__':
    # 测试打印
    print(json.dumps(get_latest_pork(), indent=2))
