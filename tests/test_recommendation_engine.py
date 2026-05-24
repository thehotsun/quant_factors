"""Tests for RecommendationV1 and RecommendationEngine."""
import pytest
from core.recommendation_engine import make_recommendation, RecommendationEngine, RECOMMENDATION_LABELS


class TestMakeRecommendation:
    def test_basic_buy(self):
        rec = make_recommendation("BUY", strength=0.8, confidence=0.7, reason="test buy")
        assert rec["recommendation"] == "BUY"
        assert rec["label"] == "建议买入"
        assert rec["strength"] == 0.8
        assert rec["confidence"] == 0.7
        assert rec["reason"] == "test buy"
        assert rec["generated_at"]  # should be non-empty

    def test_basic_sell(self):
        rec = make_recommendation("SELL")
        assert rec["recommendation"] == "SELL"
        assert rec["label"] == "建议卖出"

    def test_basic_hold(self):
        rec = make_recommendation("HOLD")
        assert rec["recommendation"] == "HOLD"
        assert rec["label"] == "建议观望"

    def test_invalid_defaults_to_hold(self):
        rec = make_recommendation("INVALID")
        assert rec["recommendation"] == "HOLD"

    def test_case_insensitive(self):
        rec = make_recommendation("buy")
        assert rec["recommendation"] == "BUY"

    def test_notes_lists(self):
        rec = make_recommendation(
            "BUY",
            risk_notes=["risk1"],
            data_notes=["data1"],
            conflict_notes=["conflict1"],
        )
        assert rec["risk_notes"] == ["risk1"]
        assert rec["data_notes"] == ["data1"]
        assert rec["conflict_notes"] == ["conflict1"]

    def test_empty_notes_default(self):
        rec = make_recommendation("HOLD")
        assert rec["risk_notes"] == []
        assert rec["data_notes"] == []
        assert rec["conflict_notes"] == []

    def test_all_labels(self):
        for direction, label in RECOMMENDATION_LABELS.items():
            rec = make_recommendation(direction)
            assert rec["label"] == label


class TestRecommendationEngineFromSignal:
    def test_none_signal(self):
        rec = RecommendationEngine.from_signal(None)
        assert rec["recommendation"] == "HOLD"
        assert "无信号数据" in rec["reason"]

    def test_basic_signal(self):
        signal_result = {
            "signal": {"direction": "BUY", "strength": 0.6, "confidence": 0.8, "reason": "bullish"},
            "signal_strength": 0.6,
            "factor_data": {"factor_value": 1.5, "zscore": 2.0},
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        assert rec["recommendation"] == "BUY"
        assert rec["strength"] == 0.6
        assert rec["confidence"] == 0.8
        assert rec["reason"] == "bullish"

    def test_old_format_string_signal(self):
        signal_result = {
            "signal": "SELL",
            "signal_strength": -0.5,
            "factor_data": {},
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        assert rec["recommendation"] == "SELL"
        assert rec["strength"] == -0.5

    def test_missing_drivers_in_signal(self):
        signal_result = {
            "signal": {"direction": "BUY", "strength": 0.5, "confidence": 0.5,
                       "missing_drivers": ["pork_spot"]},
            "factor_data": {},
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        assert any("pork_spot" in n for n in rec["data_notes"])

    def test_driver_conflicts_in_signal(self):
        signal_result = {
            "signal": {"direction": "HOLD", "strength": 0.0, "confidence": 0.3,
                       "driver_conflicts": [
                           {"driver": "meat", "buy_triggers": ["pork"], "sell_triggers": ["chicken"], "severity": 0.8}
                       ],
                       "conflict_score": 0.7},
            "factor_data": {},
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        assert len(rec["conflict_notes"]) > 0
        assert any("meat" in n for n in rec["conflict_notes"])
        assert len(rec["risk_notes"]) > 0

    def test_components_from_factor_data(self):
        signal_result = {
            "signal": {"direction": "BUY", "strength": 0.5, "confidence": 0.5},
            "factor_data": {"factor_value": 2.5, "zscore": 1.8, "ratio": 0.95},
            "chain_meta": {},
        }
        rec = RecommendationEngine.from_signal(signal_result)
        comp_names = [c["name"] for c in rec["components"]]
        assert "factor_value" in comp_names
        assert "zscore" in comp_names
        assert "ratio" in comp_names


class TestRecommendationEngineFromAggregated:
    def test_none_aggregated(self):
        rec = RecommendationEngine.from_aggregated(None)
        assert rec["recommendation"] == "HOLD"

    def test_basic_aggregated(self):
        agg = {
            "direction": "BUY",
            "strength": 0.4,
            "confidence": 0.7,
            "components": [
                {"trigger": "pork_zscore", "direction": "BUY", "strength": 0.6, "confidence": 0.8},
                {"trigger": "feed_cost", "direction": "BUY", "strength": 0.3, "confidence": 0.6},
            ],
            "conflict_score": 0.1,
            "driver_conflicts": [],
            "dedup_applied": False,
            "driver_groups": {"meat": ["pork_zscore"], "feed": ["feed_cost"]},
        }
        rec = RecommendationEngine.from_aggregated(agg)
        assert rec["recommendation"] == "BUY"
        assert "pork_zscore" in rec["reason"]
        assert len(rec["components"]) == 2
        assert "meat" in rec["drivers_used"]

    def test_aggregated_with_conflicts(self):
        agg = {
            "direction": "HOLD",
            "strength": 0.0,
            "confidence": 0.3,
            "components": [],
            "conflict_score": 0.8,
            "driver_conflicts": [
                {"driver": "energy", "buy_triggers": ["oil"], "sell_triggers": ["gas"], "severity": 0.9}
            ],
            "dedup_applied": True,
            "driver_groups": {},
        }
        rec = RecommendationEngine.from_aggregated(agg)
        assert len(rec["conflict_notes"]) > 0
        assert any("energy" in n for n in rec["conflict_notes"])
        assert any("去重" in n for n in rec["data_notes"])
