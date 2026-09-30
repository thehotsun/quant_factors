"""Tests for 数据源容灾引擎 core/source_chain.py（离线，注入假抓取器）。"""
from datetime import date, datetime
import json

import pandas as pd

import core.source_chain as sc


TODAY = date(2026, 9, 30)


def _df(*dates):
    return pd.DataFrame({"date": pd.to_datetime(list(dates)), "close": [1.0] * len(dates)})


def _cfg(sources, max_lag=6):
    return {
        "defaults": {"max_lag_days": max_lag},
        "datasets": {"demo": {"label": "演示", "max_lag_days": max_lag, "sources": sources}},
    }


class TestIsFresh:
    def test_fresh(self):
        ok, reason = sc.is_fresh(_df("2026-09-30"), 6, today=TODAY)
        assert ok and "2026-09-30" in reason

    def test_within_tolerance(self):
        ok, _ = sc.is_fresh(_df("2026-09-24"), 6, today=TODAY)
        assert ok

    def test_stale(self):
        ok, reason = sc.is_fresh(_df("2026-09-22"), 6, today=TODAY)
        assert not ok and "滞后 8 天" in reason

    def test_empty(self):
        assert sc.is_fresh(None, 6, today=TODAY)[0] is False
        assert sc.is_fresh(pd.DataFrame(), 6, today=TODAY)[0] is False

    def test_no_date_col(self):
        ok, reason = sc.is_fresh(pd.DataFrame({"x": [1]}), 6, today=TODAY)
        assert not ok and "无日期" in reason

    def test_chinese_date_col(self):
        df = pd.DataFrame({"日期": ["2026-09-30"], "close": [1.0]})
        assert sc.is_fresh(df, 6, today=TODAY)[0]


class TestResolve:
    def _run(self, fetchers, tmp_path, max_lag=6):
        return sc.resolve_dataset("demo", cfg=_cfg(
            [{"name": "s1"}, {"name": "s2"}], max_lag),
            today=TODAY, fetchers=fetchers, status_path=tmp_path / "status.json")

    def test_primary_wins(self, tmp_path):
        calls = []
        f = {"s1": lambda: calls.append("s1") or _df("2026-09-30"),
             "s2": lambda: calls.append("s2") or _df("2026-09-30")}
        df = self._run(f, tmp_path)
        assert df is not None and calls == ["s1"]  # 命中即停，不试备用

    def test_failover_on_error(self, tmp_path):
        f = {"s1": lambda: None, "s2": lambda: _df("2026-09-30")}
        df = self._run(f, tmp_path)
        assert df is not None
        st = json.loads((tmp_path / "status.json").read_text())["datasets"]["demo"]
        assert st["chosen"] == "s2" and st["ok"] is True
        # s1 尝试过且失败
        assert st["sources"][0]["source"] == "s1" and st["sources"][0]["ok"] is False

    def test_failover_on_stale_data(self, tmp_path):
        # 主源「成功但陈旧」→ 应被新鲜度门拦下，继续用备用源
        f = {"s1": lambda: _df("2026-08-01"), "s2": lambda: _df("2026-09-30")}
        df = self._run(f, tmp_path)
        assert df is not None and df["date"].max().date() == date(2026, 9, 30)
        st = json.loads((tmp_path / "status.json").read_text())["datasets"]["demo"]
        assert st["chosen"] == "s2"
        assert st["sources"][0]["ok"] is False

    def test_all_fail_returns_none(self, tmp_path):
        f = {"s1": lambda: None, "s2": lambda: _df("2026-01-01")}
        df = self._run(f, tmp_path)
        assert df is None
        st = json.loads((tmp_path / "status.json").read_text())["datasets"]["demo"]
        assert st["ok"] is False and st["chosen"] is None
        assert len(st["sources"]) == 2

    def test_unknown_fetcher(self, tmp_path):
        df = sc.resolve_dataset("demo", cfg=_cfg([{"name": "nope"}]),
                                today=TODAY, fetchers={}, status_path=tmp_path / "s.json")
        assert df is None

    def test_missing_dataset(self, tmp_path):
        df = sc.resolve_dataset("nope", cfg=_cfg([]), today=TODAY,
                                fetchers={}, status_path=tmp_path / "s.json")
        assert df is None


class TestProbeAll:
    def test_probes_every_source(self, tmp_path):
        f = {"s1": lambda: _df("2026-09-30"), "s2": lambda: None}
        out = sc.probe_all(cfg=_cfg([{"name": "s1"}, {"name": "s2"}]),
                           today=TODAY, fetchers=f, status_path=tmp_path / "s.json")
        assert out["demo"]["chosen"] == "s1"
        # 探测会试所有源（含 s2），与 resolve 的「命中即停」不同
        assert len(out["demo"]["sources"]) == 2
