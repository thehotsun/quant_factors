"""Base class for mixed signal factors.

MixedDriverFactor extends BaseFactor with driver bundle loading,
missing driver handling, and standardized signal output for
spot + futures + equity + macro mixed chains.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from factors.base import BaseFactor


class MixedDriverFactor(BaseFactor):
    """Base class for factors that consume multiple driver types.

    Subclasses should implement ``calculate()`` using ``self.load_drivers()``
    to get grouped data, and ``signal()`` using ``self._get_or_calculate()``.

    Example::

        class MyFactor(MixedDriverFactor):
            def calculate(self):
                bundle = self.load_drivers()
                futures = bundle.get("futures", {})
                spot = bundle.get("spot", {})
                # ... compute with futures and spot data
        """
    def __init__(self, chain_def=None, **kwargs):
        super().__init__(**kwargs)
        self._chain_def = chain_def
        self._driver_bundle = None
        self._driver_status = None

    @property
    def chain_def(self):
        return self._chain_def

    @property
    def trade_asset(self) -> str:
        if self._chain_def:
            return getattr(self._chain_def, "trade_asset", "") or getattr(self._chain_def, "asset", "")
        return ""

    @property
    def trade_asset_type(self) -> str:
        if self._chain_def:
            return getattr(self._chain_def, "trade_asset_type", "")
        return ""

    @property
    def execution_asset(self) -> str:
        if self._chain_def:
            return getattr(self._chain_def, "execution_asset", "")
        return ""

    def load_drivers(self) -> Dict[str, Dict[str, Optional[pd.DataFrame]]]:
        """Load all driver datasets grouped by type.

        Returns:
            {"futures": {"pork_futures": df, ...}, "spot": {...}, ...}
        Missing datasets are None.
        """
        if self._driver_bundle is not None:
            return self._driver_bundle
        self._driver_bundle = self._bus.get_driver_bundle(self._chain_def)
        return self._driver_bundle

    def get_driver_status(self) -> Dict[str, Dict[str, str]]:
        """Check driver availability without loading full DataFrames."""
        if self._driver_status is not None:
            return self._driver_status
        self._driver_status = self._bus.get_driver_status(self._chain_def)
        return self._driver_status

    def get_missing_drivers(self) -> List[str]:
        """Return list of missing driver names."""
        status = self.get_driver_status()
        missing = []
        for group_status in status.values():
            for name, state in group_status.items():
                if state != "ok":
                    missing.append(name)
        return missing

    def get_critical_missing(self) -> List[str]:
        """Return list of unexpected missing drivers (not known_missing)."""
        status = self.get_driver_status()
        missing = []
        for group_status in status.values():
            for name, state in group_status.items():
                if state == "missing_unexpected":
                    missing.append(name)
        return missing

    def load(self, name: str, date_col: str = 'date') -> Optional[pd.DataFrame]:
        """Override BaseFactor.load to also work with driver bundle.

        Falls back to DataBus.get() for non-driver data.
        """
        return self._bus.get(name, date_col)

    def _make_signal(self, asset: str = None, direction: str = "HOLD",
                     reason: str = "", holding_days: int = 10,
                     stop_loss: float = -0.05, confidence: float = 0.5,
                     strength: float = 0.0, trigger: str = "",
                     **extra) -> Dict[str, Any]:
        """Build a standardized signal dict with mixed chain metadata.

        Calls base class _make_signal to ensure trade_signal_strength,
        factor_value, vol_stop, etc. are included.
        """
        # Call base class to get trade_signal_strength, factor_value, etc.
        signal = super()._make_signal(
            asset=asset or self.trade_asset,
            direction=direction,
            reason=reason,
            holding_days=holding_days,
            stop_loss=stop_loss,
            confidence=confidence,
            strength=strength,
            trigger=trigger,
        )
        # Add mixed-chain specific fields
        signal["trade_asset"] = asset or self.trade_asset
        signal["execution_asset"] = self.execution_asset
        signal["drivers_used"] = self._list_used_drivers()
        signal["missing_drivers"] = self.get_missing_drivers()
        signal.update(extra)
        return signal

    def _list_used_drivers(self) -> List[str]:
        """Return list of driver names that were actually loaded (non-None)."""
        bundle = self.load_drivers()
        used = []
        for group_data in bundle.values():
            for name, df in group_data.items():
                if df is not None:
                    used.append(name)
        return used
