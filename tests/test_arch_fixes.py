"""架构修复的回归测试。

覆盖:
1. BaseFactor 缓存回填
2. _threshold_cache key 稳定性
3. RSI 计算正确性
4. _make_signal schema 稳定性
5. SignalAggregator 相关性折扣
6. Blueprint 路由注册
"""
import pytest
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── BaseFactor 测试 ──────────────────────────────────────────

class TestBaseFactorCache:
    """测试 BaseFactor 缓存回填修复。"""

    def _make_factor(self):
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            call_count = 0
            def calculate(self):
                DummyFactor.call_count += 1
                return {"value": 42}

        return DummyFactor

    def test_cache_backfill(self):
        """_get_or_calculate 应回填 _cached_data。"""
        Factor = self._make_factor()
        f = Factor()
        result = f._get_or_calculate()
        assert f._cached_data is not None, "Cache should be backfilled"
        assert result == {"value": 42}
        assert f._cached_data == {"value": 42}

    def test_cache_hit(self):
        """第二次调用应使用缓存，不重复计算。"""
        Factor = self._make_factor()
        f = Factor()
        Factor.call_count = 0
        f._get_or_calculate()
        f._get_or_calculate()
        assert Factor.call_count == 1, f"calculate() should be called once, got {Factor.call_count}"


class TestThresholdCacheKey:
    """测试 _threshold_cache key 稳定性。"""

    def test_different_series_different_keys(self):
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        s1 = pd.Series(range(100))
        s2 = pd.Series(range(101))
        t1 = f._adaptive_threshold("test", 0.5, s1)
        t2 = f._adaptive_threshold("test", 0.5, s2)
        assert len(f._threshold_cache) == 2, "Different series should produce different cache keys"

    def test_same_series_same_key(self):
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        s = pd.Series(range(100))
        t1 = f._adaptive_threshold("test", 0.5, s)
        t2 = f._adaptive_threshold("test", 0.5, s)
        assert len(f._threshold_cache) == 1, "Same series should reuse cache"


# ── RSI 测试 ─────────────────────────────────────────────────

class TestRSI:
    """测试 RSI 计算修复（ewm 替代 for 循环）。"""

    def test_rsi_range(self):
        """RSI 应在 0-100 之间。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        np.random.seed(42)
        prices = pd.Series(np.cumsum(np.random.randn(100)) + 100)
        rsi = f._rsi(prices, 14)
        assert 0 <= rsi <= 100, f"RSI should be 0-100, got {rsi}"

    def test_rsi_uptrend(self):
        """持续上涨序列的 RSI 应接近 100。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        prices = pd.Series(range(50, 150))  # 持续上涨
        rsi = f._rsi(prices, 14)
        assert rsi > 70, f"RSI for uptrend should be > 70, got {rsi}"

    def test_rsi_downtrend(self):
        """持续下跌序列的 RSI 应接近 0。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        prices = pd.Series(range(150, 50, -1))  # 持续下跌
        rsi = f._rsi(prices, 14)
        assert rsi < 30, f"RSI for downtrend should be < 30, got {rsi}"


# ── _make_signal 测试 ─────────────────────────────────────────

class TestMakeSignal:
    """测试 _make_signal schema 稳定性。"""

    def test_has_required_fields(self):
        """输出应包含所有必需字段。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        signal = f._make_signal(
            asset="test", direction="BUY", reason="test reason",
            holding_days=10, stop_loss=-0.03, confidence=0.6, strength=0.7,
        )
        required = ["asset", "direction", "strength", "signal_strength",
                     "trade_signal_strength", "reason", "holding_days",
                     "stop_loss", "confidence", "trigger", "factor_value", "meta"]
        for field in required:
            assert field in signal, f"Missing required field: {field}"

    def test_strength_clamped(self):
        """strength 应被裁剪到 [-1, 1]。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        signal = f._make_signal(asset="t", direction="BUY", reason="r", strength=1.5)
        assert -1.0 <= signal["strength"] <= 1.0

    def test_confidence_clamped(self):
        """confidence 应被裁剪到 [0, 1]。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        signal = f._make_signal(asset="t", direction="BUY", reason="r", confidence=1.5)
        assert 0.0 <= signal["confidence"] <= 1.0

    def test_trade_signal_strength_buy(self):
        """BUY 方向的 trade_signal_strength 应为正。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        signal = f._make_signal(asset="t", direction="BUY", reason="r", strength=0.6)
        assert signal["trade_signal_strength"] > 0

    def test_trade_signal_strength_sell(self):
        """SELL 方向的 trade_signal_strength 应为负。"""
        from factors.base import BaseFactor

        class DummyFactor(BaseFactor):
            def calculate(self):
                return {}

        f = DummyFactor()
        signal = f._make_signal(asset="t", direction="SELL", reason="r", strength=0.6)
        assert signal["trade_signal_strength"] < 0


# ── SignalAggregator 测试 ─────────────────────────────────────

class TestCorrelationDiscount:
    """测试 SignalAggregator 相关性折扣。"""

    def test_empty_signals(self):
        """空信号列表应返回空 dict。"""
        from core.signal_aggregator import SignalAggregator
        result = SignalAggregator.compute_signal_correlation_discount([])
        assert result == {}

    def test_single_signal(self):
        """单个信号应返回空 dict。"""
        from core.signal_aggregator import SignalAggregator
        result = SignalAggregator.compute_signal_correlation_discount([{"trigger": "a"}])
        assert result == {}

    def test_no_history(self):
        """无历史数据应返回空 dict。"""
        from core.signal_aggregator import SignalAggregator
        signals = [{"trigger": "a"}, {"trigger": "b"}]
        result = SignalAggregator.compute_signal_correlation_discount(signals, history=None)
        assert result == {}

    def test_correlated_signals(self):
        """高相关信号应被折扣。"""
        from core.signal_aggregator import SignalAggregator
        # Create two identical price series (correlation = 1.0)
        np.random.seed(42)
        returns = np.random.randn(100)
        prices = pd.DataFrame({"close": 100 + np.cumsum(returns)})
        history = {"dep_a": prices, "dep_b": prices}
        signals = [{"trigger": "a"}, {"trigger": "b"}]
        result = SignalAggregator.compute_signal_correlation_discount(signals, history=history)
        # Both should be discounted
        assert result.get("a", 1.0) < 1.0, "Correlated signal 'a' should be discounted"
        assert result.get("b", 1.0) < 1.0, "Correlated signal 'b' should be discounted"

    def test_uncorrelated_signals(self):
        """低相关信号不应被折扣。"""
        from core.signal_aggregator import SignalAggregator
        # Use truly uncorrelated data: one trending up, one random walk
        np.random.seed(123)
        prices_a = pd.DataFrame({"close": np.linspace(100, 200, 100)})
        prices_b = pd.DataFrame({"close": 150 + np.cumsum(np.random.randn(100) * 0.5)})
        history = {"dep_a": prices_a, "dep_b": prices_b}
        signals = [{"trigger": "dep_a"}, {"trigger": "dep_b"}]
        result = SignalAggregator.compute_signal_correlation_discount(signals, history=history)
        # Should not be discounted (low correlation)
        assert result.get("dep_a", 1.0) == 1.0, "Uncorrelated signal 'dep_a' should not be discounted"
        assert result.get("dep_b", 1.0) == 1.0, "Uncorrelated signal 'dep_b' should not be discounted"


# ── Blueprint 路由测试 ────────────────────────────────────────

class TestBlueprintRoutes:
    """测试 Blueprint 路由注册。"""

    @pytest.fixture(autouse=True)
    def reset_singletons(self):
        """Reset DataBus singleton before each test to avoid cross-test pollution."""
        from core.data_bus import DataBus
        DataBus.reset()
        yield
        DataBus.reset()

    def test_all_routes_registered(self):
        """所有预期路由应已注册。"""
        from server import create_app
        app = create_app({"skip_scheduler": True})
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        expected = [
            "/health",
            "/chains",
            "/registry",
            "/analyze/<chain>",
            "/factor/<chain_name>",
            "/signal/<chain_name>",
            "/recommend/<chain_name>",
            "/recommendations/daily",
            "/signals/history",
            "/signals/stats",
            "/ic/<factor_name>",
            "/ic/health",
            "/trigger_backtest",
            "/recommendation_backtest",
            "/driver_health",
            "/driver_health/<chain_name>",
            "/push/<chain_name>",
        ]
        for r in expected:
            assert r in routes, f"Missing route: {r}"

    def test_health_endpoint(self):
        """/health 应返回 ok。"""
        from server import create_app
        app = create_app({"skip_scheduler": True})
        with app.test_client() as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "ok"

    def test_chains_endpoint(self):
        """/chains 应返回链条列表。"""
        from server import create_app
        app = create_app({"skip_scheduler": True})
        with app.test_client() as client:
            resp = client.get("/chains")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "chains" in data
            assert "total" in data
            assert data["total"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
