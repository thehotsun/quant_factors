"""Tests for data freshness in DataBus.get_driver_status() and RecommendationEngine adjustment."""
import pytest
import tempfile
from pathlib import Path
import pandas as pd
from core.data_bus import DataBus
from core.chain_config import build_chain_definitions
from core.recommendation_engine import RecommendationEngine


@pytest.fixture(autouse=True)
def _reset_databus():
    """Reset DataBus singleton before each test."""
    DataBus.reset()
    yield
    DataBus.reset()


class TestGetDriverStatusFreshness:
    def test_status_ok_with_freshness(self):
        """Test that ok status includes freshness details."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = DataBus(tmp)
            # Create a fresh parquet
            df = pd.DataFrame({"date": [pd.Timestamp.now().normalize()], "close": [100.0]})
            df.to_parquet(Path(tmp) / "pork_futures.parquet")

            chain_def = build_chain_definitions({
                "test": {"drivers": {"futures": ["pork_futures"]}, "data_deps": ["pork_futures"]}
            })["test"]
            status = bus.get_driver_status(chain_def)
            info = status["futures"]["pork_futures"]
            assert info["status"] == "ok"
            assert info["last_date"] is not None
            assert info["lag_days"] is not None
            assert info["lag_days"] <= 1
            assert info["expected_frequency"] == "daily"
            assert info["max_allowed_lag"] == 5

    def test_status_stale(self):
        """Test stale status when data is too old."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = DataBus(tmp)
            # Create stale parquet (30 days old)
            old_date = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
            df = pd.DataFrame({"date": [old_date], "close": [100.0]})
            df.to_parquet(Path(tmp) / "pork_futures.parquet")

            chain_def = build_chain_definitions({
                "test": {"drivers": {"futures": ["pork_futures"]}, "data_deps": ["pork_futures"]}
            })["test"]
            status = bus.get_driver_status(chain_def)
            info = status["futures"]["pork_futures"]
            assert info["status"] == "stale"
            assert info["lag_days"] == 30
            assert "过期" in info["reason"]

    def test_status_missing_known(self):
        """Test missing_known for known missing datasets."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = DataBus(tmp)
            chain_def = build_chain_definitions({
                "test": {"drivers": {"spot": ["chicken_spot"]}, "data_deps": ["chicken_spot"]}
            })["test"]
            status = bus.get_driver_status(chain_def)
            info = status["spot"]["chicken_spot"]
            assert info["status"] == "missing_known"
            assert info["last_date"] is None
            assert info["lag_days"] is None

    def test_status_missing_unexpected(self):
        """Test missing_unexpected for unknown missing datasets."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = DataBus(tmp)
            chain_def = build_chain_definitions({
                "test": {"drivers": {"futures": ["some_unknown_futures"]}, "data_deps": ["some_unknown_futures"]}
            })["test"]
            status = bus.get_driver_status(chain_def)
            info = status["futures"]["some_unknown_futures"]
            assert info["status"] == "missing_unexpected"


class TestRecommendationDataHealthAdjustment:
    def test_adjust_no_issues(self):
        rec = {"recommendation": "BUY", "confidence": 0.8, "risk_notes": []}
        result = RecommendationEngine._adjust_for_data_health(rec, [], [])
        assert result["recommendation"] == "BUY"
        assert result["confidence"] == 0.8

    def test_adjust_mild_stale(self):
        rec = {"recommendation": "BUY", "confidence": 0.8, "risk_notes": []}
        result = RecommendationEngine._adjust_for_data_health(rec, [], [("dep1", 7)])
        assert result["recommendation"] == "BUY"
        assert result["confidence"] < 0.8  # lowered

    def test_adjust_moderate_missing(self):
        rec = {"recommendation": "BUY", "confidence": 0.8, "risk_notes": []}
        result = RecommendationEngine._adjust_for_data_health(rec, ["dep1"], [])
        assert result["recommendation"] == "BUY"
        assert result["confidence"] <= 0.4  # significantly lowered

    def test_adjust_severe_forces_hold(self):
        rec = {"recommendation": "BUY", "confidence": 0.8, "risk_notes": []}
        result = RecommendationEngine._adjust_for_data_health(rec, ["dep1", "dep2"], [])
        assert result["recommendation"] == "HOLD"
        assert result["label"] == "建议观望"
        assert result["confidence"] < 0.3
        assert any("严重缺失" in n for n in result["risk_notes"])

    def test_adjust_severe_mixed(self):
        """2 stale = 1.0 severity, plus 1 missing = 2.0 total → force HOLD."""
        rec = {"recommendation": "SELL", "confidence": 0.7, "risk_notes": []}
        result = RecommendationEngine._adjust_for_data_health(
            rec, ["dep1"], [("dep2", 10), ("dep3", 15)]
        )
        assert result["recommendation"] == "HOLD"
