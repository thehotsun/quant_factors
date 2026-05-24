"""Tests for components extraction from mixed factors."""
import pytest
from core.recommendation_engine import RecommendationEngine


class TestComponentsExtraction:
    def test_mixed_factor_components(self):
        """Test that mixed factor sub-fields are extracted as components."""
        signal_result = {
            "signal": {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "reason": "test"},
            "factor_data": {
                "factor_value": 0.45,
                "factor_value_type": "score",
                "pork_zscore": -1.5,
                "feed_cost_change_20d": -0.03,
                "spot_change_5d": 0.02,
                "equity_momentum_20d": 0.06,
                "pork_momentum_20d": -0.01,
                "current_price": 15000.0,
                "spot_price": 14500.0,
                "feed_cost_index": 2800.0,
            },
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        comp_names = [c["name"] for c in rec["components"]]
        assert "factor_value" in comp_names
        assert "pork_zscore" in comp_names
        assert "feed_cost_change_20d" in comp_names
        assert "spot_change_5d" in comp_names
        assert "equity_momentum_20d" in comp_names
        assert "current_price" in comp_names
        assert "spot_price" in comp_names
        assert "feed_cost_index" in comp_names

    def test_commodity_to_equity_components(self):
        """Test that commodity_to_equity factor fields are extracted."""
        signal_result = {
            "signal": {"direction": "BUY", "strength": 0.4, "confidence": 0.5, "reason": "test"},
            "factor_data": {
                "factor_value": 0.4,
                "factor_value_type": "score",
                "commodity_signal": -1.8,
                "cost_signal": -0.06,
                "equity_signal": 0.08,
            },
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        comp_names = [c["name"] for c in rec["components"]]
        assert "commodity_signal" in comp_names
        assert "cost_signal" in comp_names
        assert "equity_signal" in comp_names

    def test_none_factor_data(self):
        """Test that None factor_data produces empty components."""
        signal_result = {
            "signal": {"direction": "HOLD", "strength": 0, "confidence": 0.3, "reason": "test"},
            "factor_data": None,
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        assert rec["components"] == []
