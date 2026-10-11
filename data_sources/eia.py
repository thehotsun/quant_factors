"""EIA 数据源（美国能源信息署）。

背景：原主源 WPSR 直链 https://ir.eia.gov/wpsr/psw04.xls 自 2026-10 起被
CloudFront 签名 URL 门禁拦截（间歇 302/403 Access Restricted），导致
「EIA原油库存」源链全部失败、数据停更并触发新鲜度告警。

改用 EIA dnav 免费 XLS 直链（www.eia.gov/dnav/pet/hist_xls/*.xls，无需 API key）：
  - WCRSTUS1w.xls → 美国原油总库存（含战略储备）
  - WCESTUS1w.xls → 美国原油商业库存（不含战略储备）
两条序列均为周度、单位千桶（Thousand Barrels），每周三更新。
"""

from io import BytesIO

import pandas as pd
import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# 序列 → dnav XLS 直链
_DNAV_TOTAL_URL = "https://www.eia.gov/dnav/pet/hist_xls/WCRSTUS1w.xls"
_DNAV_COMMERCIAL_URL = "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls"


def _fetch_dnav_series(url: str) -> pd.Series:
    """下载 EIA dnav 周度 XLS，返回以日期为索引的单值序列。

    dnav XLS 的 ``Data 1`` 表结构：前 3 行为标题/序列名/表头，数据自第 4 行起，
    列 0 = 日期，列 1 = 数值。
    """
    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_excel(BytesIO(r.content), sheet_name="Data 1", header=None)
    df = df.iloc[3:, :2].copy()
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return df.set_index("date")["value"]


def fetch_eia_crude_stock():
    """从 EIA dnav 下载美国原油库存周度数据（XLS）。

    返回列：``date`` / ``total_stocks_kb`` / ``commercial_stocks_kb`` / ``weekly_change``
    （total=含战略储备；commercial=不含战略储备；weekly_change 为商业库存周环比）。
    """
    try:
        total = _fetch_dnav_series(_DNAV_TOTAL_URL)
        commercial = _fetch_dnav_series(_DNAV_COMMERCIAL_URL)

        merged = pd.DataFrame({
            "total_stocks_kb": total,
            "commercial_stocks_kb": commercial,
        })
        result = merged.reset_index().sort_values("date").reset_index(drop=True)
        result["weekly_change"] = result["commercial_stocks_kb"].diff()

        print(f"  EIA原油库存: {len(result)} 条, "
              f"{result['date'].min().date()} ~ {result['date'].max().date()}")
        return result
    except Exception as e:  # noqa: BLE001
        print(f"  EIA原油库存下载失败: {e}")
        return None
