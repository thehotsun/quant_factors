"""Tests for factor_value semantics: factor_value_type, factor_direction, horizon_days."""
import unittest
from core.factor_runner import normalize_factor_data, extract_factor_value


class FactorValueTypeTest(unittest.TestCase):
    def test_normalize_infers_zscore_type(self):
        data = {"zscore": 1.5, "current": 100.0}
        result = normalize_factor_data(data, "test_factor")
        self.assertEqual(result["factor_value"], 1.5)
        self.assertEqual(result["factor_value_type"], "zscore")

    def test_normalize_infers_ratio_type(self):
        data = {"pig_grain_ratio": 6.5}
        result = normalize_factor_data(data, "pig_grain_ratio")
        self.assertEqual(result["factor_value"], 6.5)
        self.assertEqual(result["factor_value_type"], "ratio")

    def test_normalize_infers_spread_type(self):
        data = {"spread": 200.0}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_type"], "spread")

    def test_normalize_infers_yoy_type(self):
        data = {"m2_yoy": 9.5}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_type"], "yoy")

    def test_normalize_preserves_explicit_type(self):
        data = {"zscore": 1.5, "factor_value_type": "custom_type"}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_type"], "custom_type")

    def test_normalize_infers_return_type(self):
        data = {"change": 0.03}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_type"], "return")

    def test_normalize_infers_score_type(self):
        data = {"momentum_score": 0.8}
        result = normalize_factor_data(data, "test")
        self.assertEqual(result["factor_value_type"], "score")

    def test_normalize_handles_none_data(self):
        result = normalize_factor_data(None, "test")
        self.assertIsNone(result)

    def test_normalize_handles_non_dict(self):
        result = normalize_factor_data([1, 2, 3], "test")
        self.assertEqual(result, [1, 2, 3])


class FactorValueExtractionTest(unittest.TestCase):
    def test_extracts_direct_factor_value(self):
        self.assertEqual(extract_factor_value({"factor_value": 42.0}, "t"), 42.0)

    def test_extracts_zscore_fallback(self):
        self.assertEqual(extract_factor_value({"zscore": -1.2}, "t"), -1.2)

    def test_returns_none_for_empty(self):
        self.assertIsNone(extract_factor_value({}, "t"))

    def test_returns_none_for_none(self):
        self.assertIsNone(extract_factor_value(None, "t"))


if __name__ == "__main__":
    unittest.main()
