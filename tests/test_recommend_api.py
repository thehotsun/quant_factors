"""Tests for /recommend API endpoint and recommendation field in /signal."""
import pytest
import json
import os
import tempfile
from pathlib import Path

# Ensure we have a test-friendly data_dir
_TEST_DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(autouse=True)
def _reset_databus():
    """Reset DataBus singleton before each test to avoid cross-test pollution."""
    from core.data_bus import DataBus
    DataBus.reset()
    yield
    DataBus.reset()


@pytest.fixture
def app():
    """Create test app with real config."""
    from core.data_bus import DataBus
    DataBus.reset()
    from server import create_app
    settings = {
        "data_dir": str(_TEST_DATA_DIR),
        "skip_scheduler": True,
    }
    app = create_app(settings)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestRecommendEndpoint:
    def test_recommend_unknown_chain(self, client):
        resp = client.get("/recommend/nonexistent_chain_xyz")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_recommend_returns_recommendation_structure(self, client):
        """Test that /recommend returns RecommendationV1 structure."""
        # Use a known chain from chains.yaml
        from core.settings import load_chains_config
        chains = load_chains_config()
        # Pick first non-composite chain
        chain_name = None
        for name, cfg in chains.items():
            if cfg.get("category") != "composite":
                chain_name = name
                break
        if chain_name is None:
            pytest.skip("No non-composite chains found")

        resp = client.get(f"/recommend/{chain_name}")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "recommendation" in data
        rec = data["recommendation"]
        assert "recommendation" in rec
        assert "label" in rec
        assert "strength" in rec
        assert "confidence" in rec
        assert "reason" in rec
        assert "risk_notes" in rec
        assert "data_notes" in rec
        assert "conflict_notes" in rec
        assert "drivers_used" in rec
        assert "missing_drivers" in rec
        assert "generated_at" in rec
        assert rec["recommendation"] in ("BUY", "SELL", "HOLD")


class TestSignalRecommendationField:
    def test_signal_has_recommendation(self, client):
        """Test that /signal/<chain> now includes recommendation field."""
        from core.settings import load_chains_config
        chains = load_chains_config()
        chain_name = None
        for name, cfg in chains.items():
            if cfg.get("category") != "composite":
                chain_name = name
                break
        if chain_name is None:
            pytest.skip("No non-composite chains found")

        resp = client.get(f"/signal/{chain_name}")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # Backward compat: signal and signal_strength still present
        assert "signal" in data
        assert "signal_strength" in data
        # New field
        assert "recommendation" in data
        rec = data["recommendation"]
        assert rec["recommendation"] in ("BUY", "SELL", "HOLD")
