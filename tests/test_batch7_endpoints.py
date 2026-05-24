"""Tests for /recommendations/daily and /recommendation_backtest endpoints."""
import pytest
import json
import os
from pathlib import Path

_TEST_DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(autouse=True)
def _reset_databus():
    from core.data_bus import DataBus
    DataBus.reset()
    yield
    DataBus.reset()


@pytest.fixture
def app():
    from core.data_bus import DataBus
    DataBus.reset()
    from server import create_app
    settings = {"data_dir": str(_TEST_DATA_DIR), "skip_scheduler": True}
    app = create_app(settings)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestDailyOverview:
    def test_daily_overview_structure(self, client):
        resp = client.get("/recommendations/daily")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "date" in data
        assert "buy" in data
        assert "sell" in data
        assert "hold" in data
        assert "data_issues" in data
        assert "summary" in data
        assert "timestamp" in data

    def test_daily_overview_summary(self, client):
        resp = client.get("/recommendations/daily")
        data = json.loads(resp.data)
        summary = data["summary"]
        assert "total" in summary
        assert "buy_count" in summary
        assert "sell_count" in summary
        assert "hold_count" in summary
        assert "data_issue_count" in summary
        assert summary["total"] == summary["buy_count"] + summary["sell_count"] + summary["hold_count"]

    def test_daily_overview_entry_fields(self, client):
        resp = client.get("/recommendations/daily")
        data = json.loads(resp.data)
        for lst in (data["buy"], data["sell"], data["hold"]):
            for entry in lst:
                assert "chain" in entry
                assert "recommendation" in entry
                assert "label" in entry
                assert "strength" in entry
                assert "confidence" in entry
                assert "reason" in entry


class TestRecommendationBacktest:
    def test_backtest_structure(self, client):
        resp = client.get("/recommendation_backtest")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "summary" in data
        assert "buy_recommendations" in data
        assert "sell_recommendations" in data
        assert "note" in data
        assert "建议有效性" in data["note"]

    def test_backtest_entry_fields(self, client):
        resp = client.get("/recommendation_backtest")
        data = json.loads(resp.data)
        for lst in (data["buy_recommendations"], data["sell_recommendations"]):
            for entry in lst:
                assert "trigger" in entry
                assert "count" in entry
                assert "returns" in entry
