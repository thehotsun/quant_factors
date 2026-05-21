"""Common helpers for macro-economic data alignment.

Macro series are monthly/weekly and should not be treated as tradable on the
statistical period date.  These helpers add conservative publication dates so
signals and backtests use information only after it is plausibly public.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
from pandas.tseries.offsets import BDay, MonthEnd


RELEASE_LAG_DAYS = {
    # China CPI is usually published around the 9th-12th of next month.
    "cpi": 10,
    # China PMI is usually available at month-end / start of next month.
    "pmi": 1,
    # PBoC M2 and social-financing data are usually published mid next month.
    "m2": 12,
    "social_financing": 12,
    # US CPI is mid next month; use conservative default when reused.
    "us_cpi": 14,
}


def infer_release_date(period_date, series_name: str) -> Optional[pd.Timestamp]:
    if pd.isna(period_date):
        return None
    period = pd.to_datetime(period_date)
    lag = RELEASE_LAG_DAYS.get(series_name, 10)
    return (period + MonthEnd(0) + BDay(lag)).normalize()


def add_release_date(df: pd.DataFrame, series_name: str, date_col: str = "date") -> pd.DataFrame:
    if df is None or df.empty or date_col not in df.columns:
        return df
    result = df.copy()
    if "release_date" not in result.columns:
        result["release_date"] = result[date_col].apply(lambda d: infer_release_date(d, series_name))
    result["release_date"] = pd.to_datetime(result["release_date"], errors="coerce")
    return result


def available_asof(df: pd.DataFrame, series_name: str, as_of=None, date_col: str = "date") -> pd.DataFrame:
    """Return rows available at *as_of* using conservative release dates.

    If as_of is None, no row is dropped for live analysis, but release_date is
    still attached so downstream consumers can audit the information timestamp.
    """
    if df is None or df.empty:
        return df
    result = add_release_date(df, series_name, date_col=date_col)
    if as_of is None:
        return result
    ts = pd.to_datetime(as_of)
    return result[result["release_date"] <= ts]


def latest_release_date(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty or "release_date" not in df.columns:
        return None
    value = df["release_date"].dropna().max()
    if pd.isna(value):
        return None
    return pd.to_datetime(value).date().isoformat()


def latest_period_date(df: pd.DataFrame, date_col: str = "date") -> Optional[str]:
    if df is None or df.empty or date_col not in df.columns:
        return None
    value = pd.to_datetime(df[date_col], errors="coerce").dropna().max()
    if pd.isna(value):
        return None
    return pd.to_datetime(value).date().isoformat()
