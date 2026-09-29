"""Tests for network guards (default request timeouts + job watchdog)."""
import time

import pytest
import requests


class TestRunWithTimeout:
    def test_returns_value_when_fast(self):
        from core.net_guard import run_with_timeout
        assert run_with_timeout(lambda: 42, 5, "fast") == 42

    def test_gives_up_after_timeout(self):
        from core.net_guard import run_with_timeout

        def hang():
            time.sleep(3)

        started = time.monotonic()
        result = run_with_timeout(hang, 0.2, "hang")
        elapsed = time.monotonic() - started
        assert result is None
        assert elapsed < 1.5  # returned promptly, did not wait for full sleep

    def test_propagates_exception(self):
        from core.net_guard import run_with_timeout

        def boom():
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            run_with_timeout(boom, 5, "boom")


class TestInstallRequestsTimeout:
    def test_send_injects_default_timeout(self, monkeypatch):
        import core.net_guard as ng
        from requests.adapters import HTTPAdapter

        captured = {}

        def fake_orig(self, request, **kwargs):
            captured.update(kwargs)
            return "sent"

        monkeypatch.setattr(HTTPAdapter, "send", fake_orig)
        monkeypatch.setattr(ng, "_PATCHED", False)
        ng.install_requests_timeout(17)

        adapter = HTTPAdapter()
        assert adapter.send(object()) == "sent"
        assert captured.get("timeout") == 17

    def test_explicit_timeout_preserved(self, monkeypatch):
        import core.net_guard as ng
        from requests.adapters import HTTPAdapter

        captured = {}

        def fake_orig(self, request, **kwargs):
            captured.update(kwargs)
            return "sent"

        monkeypatch.setattr(HTTPAdapter, "send", fake_orig)
        monkeypatch.setattr(ng, "_PATCHED", False)
        ng.install_requests_timeout(17)

        adapter = HTTPAdapter()
        adapter.send(object(), timeout=3)
        assert captured.get("timeout") == 3


class TestFredTimeout:
    def test_data_sources_fred_passes_timeout(self, monkeypatch):
        import data_sources.fred as fred

        captured = {}

        def fake_get(url, timeout=None):
            captured["url"] = url
            captured["timeout"] = timeout
            raise requests.Timeout("stalled")

        monkeypatch.setattr(fred.requests, "get", fake_get)
        assert fred.fetch_fred_csv("DEXCHUS", "USD/CNY汇率") is None
        assert captured["timeout"] == fred._TIMEOUT

    def test_core_data_refresh_fred_passes_timeout(self, monkeypatch):
        import core.data_refresh as dr

        captured = {}

        def fake_get(url, timeout=None):
            captured["timeout"] = timeout
            raise requests.Timeout("stalled")

        monkeypatch.setattr(dr.requests, "get", fake_get)
        assert dr.fetch_fred_csv("DEXCHUS", "USD/CNY汇率") is None
        assert captured["timeout"] == dr.FRED_TIMEOUT


if __name__ == "__main__":
    import unittest

    unittest.main()
