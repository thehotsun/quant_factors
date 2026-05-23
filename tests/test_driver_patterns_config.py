"""P1-2: 验证 driver_patterns 从配置加载，支持热更新。"""

import unittest
from core.signal_aggregator import SignalAggregator, _load_driver_patterns


class TestDriverPatternsConfig(unittest.TestCase):
    """driver_patterns 应从 config/factor_params.yaml 加载。"""

    def test_driver_patterns_loaded(self):
        """加载后应包含预期的 driver 分类。"""
        patterns = SignalAggregator.DRIVER_PATTERNS
        self.assertIn("growth", patterns)
        self.assertIn("inflation", patterns)
        self.assertIn("risk_off", patterns)
        self.assertIn("pmi", patterns["growth"])
        self.assertIn("cpi", patterns["inflation"])
        self.assertIn("vix", patterns["risk_off"])

    def test_classify_driver_from_config(self):
        """_classify_driver 应使用配置中的 patterns。"""
        self.assertEqual(SignalAggregator._classify_driver("pmi_expansion"), "growth")
        self.assertEqual(SignalAggregator._classify_driver("cpi_surprise"), "inflation")
        self.assertEqual(SignalAggregator._classify_driver("vix_high"), "risk_off")
        self.assertEqual(SignalAggregator._classify_driver("feed_cost_high"), "cost")
        self.assertEqual(SignalAggregator._classify_driver("unknown_trigger"), "other")

    def test_reload_config(self):
        """reload_config 应重新加载配置。"""
        # 保存原始
        original = dict(SignalAggregator.DRIVER_PATTERNS)
        try:
            SignalAggregator.reload_config()
            # 重新加载后应仍然有效
            self.assertIn("growth", SignalAggregator.DRIVER_PATTERNS)
        finally:
            # 恢复（虽然 reload 已经恢复了）
            SignalAggregator.DRIVER_PATTERNS = original

    def test_driver_patterns_is_dict_of_lists(self):
        """DRIVER_PATTERNS 应是 Dict[str, List[str]]。"""
        for driver, patterns in SignalAggregator.DRIVER_PATTERNS.items():
            self.assertIsInstance(driver, str)
            self.assertIsInstance(patterns, list)
            for p in patterns:
                self.assertIsInstance(p, str)


class TestCorrelationDiscountInterface(unittest.TestCase):
    """compute_signal_correlation_discount 预留接口。"""

    def test_returns_empty_dict(self):
        """当前实现应返回空 dict。"""
        result = SignalAggregator.compute_signal_correlation_discount([])
        self.assertEqual(result, {})

    def test_accepts_signals_and_history(self):
        """应接受 signals 和 history 参数。"""
        signals = [{"trigger": "test", "strength": 0.5}]
        result = SignalAggregator.compute_signal_correlation_discount(signals, history=None)
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
