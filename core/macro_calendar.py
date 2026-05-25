"""Common helpers for macro-economic data alignment.

Macro series are monthly/weekly and should not be treated as tradable on the
statistical period date.  These helpers add conservative publication dates so
signals and backtests use information only after it is plausibly public.

Point-in-time (PIT) approach:
- Primary: use estimated release_date based on known publication schedules
- Fallback: use actual data fetch timestamp from refresh_manifest.json
- The effective availability date = max(release_date, fetch_timestamp)
- This ensures backtests never use data before it was actually available
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

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

# Cache for fetch timestamps from refresh_manifest.json
_FETCH_TIMESTAMPS: Dict[str, str] = {}


def _load_fetch_timestamps(manifest_path: str = None) -> Dict[str, str]:
    """Load actual fetch timestamps from refresh_manifest.json.

    Returns dict mapping series_name -> ISO timestamp of last successful fetch.
    """
    global _FETCH_TIMESTAMPS
    if _FETCH_TIMESTAMPS:
        return _FETCH_TIMESTAMPS

    if manifest_path is None:
        manifest_path = str(Path(__file__).parent.parent / "data" / "refresh_manifest.json")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        for record in manifest.get("records", []):
            if record.get("status") == "success" and record.get("name"):
                # Use the manifest's ended_at as conservative fetch time
                fetch_time = manifest.get("ended_at")
                if fetch_time:
                    _FETCH_TIMESTAMPS[record["name"]] = fetch_time
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    return _FETCH_TIMESTAMPS


def get_fetch_timestamp(series_name: str) -> Optional[pd.Timestamp]:
    """Get the actual fetch timestamp for a series from refresh_manifest.json.

    This is used as a fallback when release_date is estimated.
    """
    timestamps = _load_fetch_timestamps()
    ts_str = timestamps.get(series_name)
    if ts_str:
        try:
            return pd.to_datetime(ts_str)
        except Exception:
            pass
    return None


def infer_release_date(period_date, series_name: str) -> Optional[pd.Timestamp]:
    if pd.isna(period_date):
        return None
    period = pd.to_datetime(period_date)
    lag = RELEASE_LAG_DAYS.get(series_name, 10)
    return (period + MonthEnd(0) + BDay(lag)).normalize()


def add_release_date(df: pd.DataFrame, series_name: str, date_col: str = "date") -> pd.DataFrame:
    """Add release_date column using estimated publication schedule.

    If fetch_timestamp is available from refresh_manifest.json, use it as
    a conservative floor (data can't be available before it was fetched).
    """
    if df is None or df.empty or date_col not in df.columns:
        return df
    result = df.copy()
    if "release_date" not in result.columns:
        result["release_date"] = result[date_col].apply(lambda d: infer_release_date(d, series_name))
    result["release_date"] = pd.to_datetime(result["release_date"], errors="coerce")

    # Apply fetch timestamp as conservative floor
    fetch_ts = get_fetch_timestamp(series_name)
    if fetch_ts is not None:
        # release_date can't be before the data was actually fetched
        result["release_date"] = result["release_date"].apply(
            lambda rd: max(rd, fetch_ts) if pd.notna(rd) and pd.notna(fetch_ts) else rd
        )
        result["fetch_timestamp"] = fetch_ts

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


def save_pit_snapshot(df: pd.DataFrame, series_name: str, pit_dir: str = None) -> Optional[str]:
    """Save a point-in-time snapshot of macro data.

    This creates a timestamped copy of the data that can be used for
    backtesting without forward-looking bias from revisions.

    Args:
        df: DataFrame to snapshot
        series_name: Name of the series (e.g., "cpi", "pmi")
        pit_dir: Directory to save snapshots (default: data/pit_snapshots)

    Returns:
        Path to saved snapshot, or None if failed
    """
    if df is None or df.empty:
        return None

    try:
        if pit_dir is None:
            pit_dir = str(Path(__file__).parent.parent / "data" / "pit_snapshots")

        pit_path = Path(pit_dir)
        pit_path.mkdir(parents=True, exist_ok=True)

        # Use date-based filename for easy lookup
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{series_name}_{today}.parquet"
        filepath = pit_path / filename

        # Save with metadata
        snapshot = df.copy()
        snapshot["_snapshot_date"] = datetime.now().isoformat()
        snapshot["_series_name"] = series_name

        # Use parquet for efficient storage
        snapshot.to_parquet(filepath, index=False, engine="pyarrow")
        return str(filepath)
    except Exception:
        return None


def load_pit_snapshot(series_name: str, as_of: str = None, pit_dir: str = None) -> Optional[pd.DataFrame]:
    """Load a point-in-time snapshot of macro data.

    Args:
        series_name: Name of the series
        as_of: Load the snapshot closest to (but not after) this date
        pit_dir: Directory containing snapshots

    Returns:
        DataFrame from the closest snapshot, or None if not found
    """
    try:
        if pit_dir is None:
            pit_dir = str(Path(__file__).parent.parent / "data" / "pit_snapshots")

        pit_path = Path(pit_dir)
        if not pit_path.exists():
            return None

        # Find all snapshots for this series
        snapshots = sorted(pit_path.glob(f"{series_name}_*.parquet"))
        if not snapshots:
            return None

        if as_of is None:
            # Return the latest snapshot
            return pd.read_parquet(snapshots[-1])

        # Find the closest snapshot before as_of
        as_of_ts = pd.to_datetime(as_of)
        best = None
        for snap in snapshots:
            # Extract date from filename: series_name_YYYY-MM-DD.parquet
            date_str = snap.stem.replace(f"{series_name}_", "")
            try:
                snap_date = pd.to_datetime(date_str)
                if snap_date <= as_of_ts:
                    best = snap
            except Exception:
                continue

        if best is not None:
            return pd.read_parquet(best)
        return None
    except Exception:
        return None


def invalidate_fetch_timestamp_cache():
    """Clear the fetch timestamp cache (e.g., after a new data refresh)."""
    global _FETCH_TIMESTAMPS
    _FETCH_TIMESTAMPS = {}
