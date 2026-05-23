"""P0-2: 验证 factor_value_source 标记和 fallback 检测。

- 显式声明 factor_value 的因子：factor_value_source == "explicit"
- 通过 fallback key 推断的因子：factor_value_source == "fallback:<key>"
- 无法推断的因子：factor_value_source == "none"
"""

import unittest

from core.factor_runner import normalize_factor_data


class TestFactorValueSource(unittest.TestCase):
    """normalize_factor_data 必须标记 factor_value_source。"""

    def test_explicit_factor_value(self):
        """显式 factor_value → source 为 explicit。"""
        data = {"factor_value": 1.23, "current_cpi": 1.2}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "explicit")
        self.assertEqual(result["factor_value"], 1.23)

    def test_fallback_zscore(self):
        """无 factor_value，有 zscore → fallback:zscore。"""
        data = {"zscore": 1.5, "current_price": 100}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "fallback:zscore")
        self.assertEqual(result["factor_value"], 1.5)
        self.assertEqual(result["factor_value_type"], "zscore")

    def test_fallback_ratio(self):
        """无 factor_value，有 pig_grain_ratio → fallback:pig_grain_ratio。"""
        data = {"pig_grain_ratio": 6.5}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "fallback:pig_grain_ratio")
        self.assertEqual(result["factor_value_type"], "ratio")

    def test_fallback_current(self):
        """无 factor_value，有 current → fallback 取 FACTOR_VALUE_KEYS 中第一个命中的。"""
        data = {"current": 42.0}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "fallback:current")
        self.assertEqual(result["factor_value_type"], "raw_value")

    def test_no_value_at_all(self):
        """既无 factor_value 也无 fallback key → none。"""
        data = {"some_field": "irrelevant"}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "none")
        self.assertIsNone(result["factor_value"])

    def test_none_data_passthrough(self):
        """None 数据直接返回，不崩溃。"""
        result = normalize_factor_data(None, "test")
        self.assertIsNone(result)

    def test_non_dict_passthrough(self):
        """非 dict 数据直接返回。"""
        result = normalize_factor_data([1, 2, 3], "test")
        self.assertEqual(result, [1, 2, 3])

    def test_explicit_factor_value_zero(self):
        """factor_value=0 也是显式，不是 fallback。"""
        data = {"factor_value": 0, "zscore": 1.5}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "explicit")
        self.assertEqual(result["factor_value"], 0)

    def test_existing_source_not_overwritten(self):
        """如果已经设置了 factor_value_source，不覆盖。"""
        data = {"factor_value": 1.0, "factor_value_source": "custom"}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_source"], "custom")


if __name__ == "__main__":
    unittest.main()
