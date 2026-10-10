"""Tests for 数据源探测后台异步化（core/source_chain.py 的 probe 状态机）。

离线：注入假 probe_all，不联网。
"""
import json
import threading
import time
from datetime import datetime, timedelta

import core.source_chain as sc


class TestProbeStateHelpers:
    def test_stale_running_treated_as_not_running(self, tmp_path):
        p = tmp_path / "probe_state.json"
        old = (datetime.now() - timedelta(seconds=1000)).isoformat(timespec="seconds")
        p.write_text(json.dumps({"running": True, "started_at": old}), encoding="utf-8")
        assert sc.is_probe_running(p) is False

    def test_fresh_running(self, tmp_path):
        p = tmp_path / "probe_state.json"
        now = datetime.now().isoformat(timespec="seconds")
        p.write_text(json.dumps({"running": True, "started_at": now}), encoding="utf-8")
        assert sc.is_probe_running(p) is True

    def test_missing_file_not_running(self, tmp_path):
        assert sc.is_probe_running(tmp_path / "nope.json") is False


class TestStartBackground:
    def test_start_and_complete(self, monkeypatch, tmp_path):
        p = tmp_path / "probe_state.json"
        calls = []
        monkeypatch.setattr(sc, "probe_all", lambda **k: calls.append(1) or {})
        assert sc.start_probe_background(timeout=10, path=p) is True
        for _ in range(300):
            if not sc.is_probe_running(p):
                break
            time.sleep(0.01)
        st = sc.probe_state(p)
        assert st["running"] is False
        assert st["finished_at"] is not None
        assert st["error"] is None
        assert calls == [1]

    def test_reject_when_running(self, monkeypatch, tmp_path):
        p = tmp_path / "probe_state.json"
        gate = threading.Event()
        monkeypatch.setattr(sc, "probe_all", lambda **k: gate.wait(3))
        assert sc.start_probe_background(timeout=10, path=p) is True
        # 第一次立刻返回 running=True；紧接着再触发应被拒
        assert sc.is_probe_running(p) is True
        assert sc.start_probe_background(timeout=10, path=p) is False
        gate.set()

    def test_error_recorded(self, monkeypatch, tmp_path):
        p = tmp_path / "probe_state.json"

        def boom(**k):
            raise RuntimeError("boom-xyz")

        monkeypatch.setattr(sc, "probe_all", boom)
        assert sc.start_probe_background(timeout=5, path=p) is True
        for _ in range(300):
            if not sc.is_probe_running(p):
                break
            time.sleep(0.01)
        st = sc.probe_state(p)
        assert st["running"] is False
        assert "boom-xyz" in (st["error"] or "")

    def test_timeout_recorded(self, monkeypatch, tmp_path):
        p = tmp_path / "probe_state.json"
        monkeypatch.setattr(sc, "probe_all", lambda **k: time.sleep(5))
        assert sc.start_probe_background(timeout=0.2, path=p) is True
        for _ in range(300):
            if not sc.is_probe_running(p):
                break
            time.sleep(0.01)
        st = sc.probe_state(p)
        assert st["running"] is False
        assert "超时" in (st["error"] or "")


class TestRoutesWiring:
    def test_probe_route_exists(self):
        src = __import__("pathlib").Path("routes/system.py").read_text(encoding="utf-8")
        assert "/sources/probe" in src
        assert "start_probe_background" in src
        # 旧写法保留为后台触发（不再同步 probe_all）
        assert "probe_all()" not in src
