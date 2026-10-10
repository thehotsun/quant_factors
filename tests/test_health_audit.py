"""Tests for 交易数据健康巡检 core/health_audit.py（离线，注入假结果）。

另含 VIX 源切换（FRED VIXCLS）与「外盘刷新去 A 股日历门」的配置/接线断言。
"""
import json
from pathlib import Path

import pandas as pd

import core.health_audit as ha
import core.push as push_mod


class _FakePush:
    def __init__(self):
        self.sent = []

    def send(self, title, content):
        self.sent.append((title, content))
        return {"fake": True}


def _patch(monkeypatch, tmp_path, freshness=None, sources=None, manifest=None):
    monkeypatch.setattr(ha, "AUDIT_PATH", Path(tmp_path) / "health_audit.json")
    monkeypatch.setattr(ha, "_audit_freshness", lambda: list(freshness or []))
    monkeypatch.setattr(ha, "_audit_sources", lambda probe: dict(sources or {}))
    monkeypatch.setattr(ha, "_audit_manifest", lambda: dict(
        manifest or {"present": True, "lag_hours": 1.0, "failed_items": []}))
    fake = _FakePush()
    monkeypatch.setattr(push_mod, "get_push_manager", lambda: fake)
    return fake


class TestHealthAudit:
    def test_all_clean_silent(self, monkeypatch, tmp_path):
        fake = _patch(monkeypatch, tmp_path)
        report = ha.run_health_audit()
        assert report["ok"] is True
        assert report["problems"] == []
        assert fake.sent == []  # 正常不推送
        # 已落盘
        saved = json.loads((Path(tmp_path) / "health_audit.json").read_text(encoding="utf-8"))
        assert saved["ok"] is True

    def test_freshness_problem_pushes(self, monkeypatch, tmp_path):
        fake = _patch(monkeypatch, tmp_path, freshness=["布伦特原油: 最新 2026-09-30（滞后 10 天）"])
        report = ha.run_health_audit()
        assert report["ok"] is False
        assert any("布伦特原油" in p for p in report["problems"])
        assert len(fake.sent) == 1 and "健康巡检" in fake.sent[0][0]

    def test_source_all_failed(self, monkeypatch, tmp_path):
        _patch(monkeypatch, tmp_path, sources={
            "vix": {"label": "VIX恐慌指数", "ok": False,
                    "sources": [{"source": "fred_close", "ok": False}]}})
        report = ha.run_health_audit(push=False)
        assert any("VIX恐慌指数" in p and "均不可用" in p for p in report["problems"])

    def test_manifest_missing(self, monkeypatch, tmp_path):
        _patch(monkeypatch, tmp_path, manifest={"present": False})
        report = ha.run_health_audit(push=False)
        assert any("刷新清单缺失" in p for p in report["problems"])

    def test_manifest_failed_items(self, monkeypatch, tmp_path):
        _patch(monkeypatch, tmp_path, manifest={"present": True, "lag_hours": 1.0,
                                                "failed_items": ["CBOT大豆"]})
        report = ha.run_health_audit(push=False)
        assert any("CBOT大豆" in p for p in report["problems"])

    def test_manifest_stale(self, monkeypatch, tmp_path):
        _patch(monkeypatch, tmp_path, manifest={"present": True, "lag_hours": 100.0,
                                                "ended_at": "2026-10-05T18:00:00",
                                                "failed_items": []})
        report = ha.run_health_audit(push=False)
        assert any("上次结束" in p for p in report["problems"])


class TestVixSourceConfig:
    def test_vix_dataset_uses_fred_close_first(self):
        from core.source_chain import load_source_config
        cfg = load_source_config()
        vix = cfg["datasets"]["vix"]
        assert vix["sources"][0]["name"] == "fred_close"
        assert vix["sources"][0]["args"]["series_id"] == "VIXCLS"
        # 兜底源保留
        assert vix["sources"][1]["name"] == "akshare_qvix"

    def test_vix_is_chained_not_single(self):
        import core.data_refresh as dr
        assert "vix" in dr._CHAINED_FOREIGN

    def test_fred_close_normalizes_to_close(self, monkeypatch):
        from core import data_refresh as dr
        from core.source_chain import _f_fred_close
        monkeypatch.setattr(dr, "fetch_fred_csv", lambda *a, **k: pd.DataFrame({
            "date": pd.to_datetime(["2026-10-07", "2026-10-08"]),
            "VIXCLS": [16.0, 15.41]}))
        df = _f_fred_close("VIXCLS", "VIX(CBOE)")
        assert list(df.columns) == ["date", "close"]
        assert df["close"].iloc[-1] == 15.41


class TestForeignRefreshUngated:
    def test_foreign_refresh_not_gated_by_calendar(self):
        """外盘刷新任务不应再引用 is_trading_day 跳过。"""
        src = Path("server.py").read_text(encoding="utf-8")
        block = src.split("def _daily_data_refresh_foreign", 1)[1].split("def ", 1)[0]
        assert "is_trading_day" not in block
