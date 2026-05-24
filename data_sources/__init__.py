"""数据源适配器。

每个模块负责一种数据来源的 fetch 逻辑，返回标准化的 DataFrame。
download_history.py 只做编排（调用 fetch → save_parquet）。
"""

from data_sources.domestic_futures import fetch_tushare_futures, fetch_pork_futures_far
from data_sources.fred import fetch_fred_csv, fetch_brent_oil
from data_sources.eia import fetch_eia_crude_stock
from data_sources.macro_china import fetch_pboc_social_financing
from data_sources.foreign import fetch_cbot_soybean
from data_sources.spot import fetch_pork_spot
from data_sources.equity import fetch_etf_hist, fetch_stock_hist

__all__ = [
    "fetch_tushare_futures",
    "fetch_pork_futures_far",
    "fetch_fred_csv",
    "fetch_brent_oil",
    "fetch_eia_crude_stock",
    "fetch_pboc_social_financing",
    "fetch_cbot_soybean",
    "fetch_pork_spot",
    "fetch_etf_hist",
    "fetch_stock_hist",
]
