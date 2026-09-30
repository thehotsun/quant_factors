"""Tests for 盘中异动告警的「数据新鲜度闸门」。

覆盖：
- 夜盘/日盘窗口判断（含无夜盘品种、跨日窗口）
- 期货行情时间新鲜度判定（正常/冻结/跨零点/缺失）
- 现货新鲜度判定
- 数据不新提醒「每个事件只提醒一次」
"""
from datetime import datetime

import pytest


# ── 开市窗口 ──────────────────────────────────────────────

class TestFuturesWindow:
    def test_day_session_live(self):
        import core.market_alert as ma
        assert ma._futures_symbol_is_live("CU0", 10 * 60) is True

    def test_lunch_break_not_live(self):
        import core.market_alert as ma
        assert ma._futures_symbol_is_live("CU0", 12 * 60) is False

    def test_night_session_cu(self):
        import core.market_alert as ma
        assert ma._futures_symbol_is_live("CU0", 22 * 60) is True

    def test_no_night_session_lh(self):
        import core.market_alert as ma
        # 生猪无夜盘：夜盘时段不要求更新
        assert ma._futures_symbol_is_live("LH0", 22 * 60) is False

    def test_cross_midnight_window(self):
        import core.market_alert as ma
        # 黄金夜盘 21:00-02:30，凌晨 01:00 仍在窗口内
        assert ma._futures_symbol_is_live("AU0", 1 * 60) is True

    def test_open_grace(self):
        import core.market_alert as ma
        # 09:00 刚开盘（缓冲期内）不算 live，避免数据未开始跳时误报
        assert ma._futures_symbol_is_live("CU0", 9 * 60) is False


# ── 期货新鲜度 ────────────────────────────────────────────

class TestFuturesFreshness:
    def test_fresh_when_time_matches_now(self):
        import core.market_alert as ma
        now = datetime(2026, 9, 30, 10, 0, 0)
        ok, reason = ma._is_price_fresh("SC0", "100000", now=now)
        assert ok and reason == ""

    def test_stale_when_frozen_at_prev_close(self):
        import core.market_alert as ma
        now = datetime(2026, 9, 30, 10, 0, 0)
        # 数据停在 15:04（昨天收盘），明显不新
        ok, reason = ma._is_price_fresh("SC0", "150441", now=now)
        assert not ok
        assert "15:04" in reason

    def test_not_required_for_non_live_symbol(self):
        import core.market_alert as ma
        # 夜盘时段看生猪：本就不跳，不作新鲜度要求
        now = datetime(2026, 9, 30, 22, 0, 0)
        ok, _ = ma._is_price_fresh("LH0", "150441", now=now)
        assert ok

    def test_cross_midnight_stale(self):
        import core.market_alert as ma
        now = datetime(2026, 9, 30, 0, 10, 0)
        # 23:30 距现在 40 分钟 > 20 分钟容差
        ok, _ = ma._is_price_fresh("SC0", "233000", now=now)
        assert not ok

    def test_cross_midnight_fresh(self):
        import core.market_alert as ma
        now = datetime(2026, 9, 30, 0, 10, 0)
        # 00:05 距现在 5 分钟
        ok, _ = ma._is_price_fresh("SC0", "000500", now=now)
        assert ok

    def test_slightly_ahead_is_fresh(self):
        import core.market_alert as ma
        now = datetime(2026, 9, 30, 10, 0, 0)
        # 时间戳比本机略快 1 分钟，视为正常
        ok, _ = ma._is_price_fresh("SC0", "100100", now=now)
        assert ok

    def test_missing_time_stale(self):
        import core.market_alert as ma
        now = datetime(2026, 9, 30, 10, 0, 0)
        ok, reason = ma._is_price_fresh("SC0", "", now=now)
        assert not ok and reason


# ── 现货新鲜度 ────────────────────────────────────────────

class TestSpotFreshness:
    def test_corn_stale_when_old_date(self, monkeypatch):
        import core.market_alert as ma
        monkeypatch.setattr(ma, "_latest_trading_day", lambda d=None: datetime(2026, 9, 30).date())
        ok, reason = ma._spot_is_fresh("corn", {"date": "2026-09-25"})
        assert not ok
        assert "2026-09-25" in reason

    def test_corn_fresh_when_latest(self, monkeypatch):
        import core.market_alert as ma
        monkeypatch.setattr(ma, "_latest_trading_day", lambda d=None: datetime(2026, 9, 30).date())
        ok, _ = ma._spot_is_fresh("corn", {"date": "2026-09-30"})
        assert ok

    def test_pork_lenient(self):
        import core.market_alert as ma
        # 生猪无日期字段，弱判断：返回非空即视为新
        ok, _ = ma._spot_is_fresh("pork", {"price": 12345.0})
        assert ok


# ── 不新提醒去重 ──────────────────────────────────────────

class TestStaleNotifyOnce:
    def test_notify_once_per_event(self, monkeypatch):
        import core.market_alert as ma
        monkeypatch.setattr(ma, "_FRESHNESS_NOTIFY_STALE", True)
        pushes = []

        def pf(title, content):
            pushes.append((title, content))

        state = {}
        items = [{"symbol": "SC0", "name": "原油", "reason": "行情停在 15:04"}]

        ma._handle_stale_notifications(state, items, pf)
        assert len(pushes) == 1

        # 同一事件再次出现，不重复提醒
        ma._handle_stale_notifications(state, items, pf)
        assert len(pushes) == 1

        # 恢复后再不新 → 重新提醒
        ma._handle_stale_notifications(state, [], pf)
        ma._handle_stale_notifications(state, items, pf)
        assert len(pushes) == 2

    def test_multiple_symbols_combined(self, monkeypatch):
        import core.market_alert as ma
        monkeypatch.setattr(ma, "_FRESHNESS_NOTIFY_STALE", True)
        pushes = []
        state = {}
        items = [
            {"symbol": "SC0", "name": "原油", "reason": "行情停在 15:04"},
            {"symbol": "spot_corn", "name": "玉米现货", "reason": "现货日期停在 2026-09-25"},
        ]
        ma._handle_stale_notifications(state, items, lambda t, c: pushes.append((t, c)))
        assert len(pushes) == 1
        assert "原油" in pushes[0][1] and "玉米现货" in pushes[0][1]

    def test_silent_when_disabled(self, monkeypatch):
        """notify_stale=false（默认）：数据不新时不推送，仅记日志。"""
        import core.market_alert as ma
        monkeypatch.setattr(ma, "_FRESHNESS_NOTIFY_STALE", False)
        pushes = []
        state = {}
        items = [{"symbol": "SC0", "name": "原油", "reason": "行情停在 15:04"}]
        ma._handle_stale_notifications(state, items, lambda t, c: pushes.append((t, c)))
        assert pushes == []
        # 状态仍被记录，便于后续开关/诊断
        assert "SC0" in state.get("stale", {})
