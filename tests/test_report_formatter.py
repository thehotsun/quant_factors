"""Tests for core.report_formatter shared formatting layer (A2-2)."""
import unittest
from core.report_formatter import (
    format_chain_report, format_chain_report_markdown,
    direction_emoji, position_label, period_label, format_trend,
)


class ReportFormatterTest(unittest.TestCase):
    def test_format_chain_report_structure(self):
        composite = {
            "chain": "test_chain",
            "description": "Test",
            "aggregated_signal": {
                "direction": "BUY", "strength": 0.5, "confidence": 0.7,
                "signal_count": 2, "buy_count": 2, "sell_count": 0,
                "conflict_score": 0.0, "dedup_applied": False,
            },
            "active_signals": [
                {"trigger": "t1", "direction": "BUY", "strength": 0.6, "confidence": 0.7, "reason": "r1"},
            ],
            "all_results": {"sub1": {"error": "fail"}},
        }
        report = format_chain_report(composite)
        self.assertEqual(report["chain"], "test_chain")
        self.assertEqual(report["aggregated"]["direction"], "BUY")
        self.assertEqual(report["aggregated"]["conflict_score"], 0.0)
        self.assertEqual(len(report["signals"]), 1)
        self.assertEqual(len(report["errors"]), 1)

    def test_format_chain_report_markdown(self):
        report = {
            "chain": "test", "description": "desc",
            "aggregated": {"direction": "SELL", "strength": -0.3, "confidence": 0.6,
                           "signal_count": 1, "buy_count": 0, "sell_count": 1,
                           "conflict_score": 0.0, "dedup_applied": False},
            "signals": [{"trigger": "t1", "direction": "SELL", "reason": "overbought"}],
            "errors": [],
        }
        md = format_chain_report_markdown(report)
        self.assertIn("SELL", md)
        self.assertIn("t1", md)
        self.assertIn("冲突度", md)

    def test_format_chain_report_markdown_with_price_context(self):
        report = {"chain": "t", "description": "d", "aggregated": None, "signals": [], "errors": []}
        ctx = [{"label": "铜", "trend": "100 → 105 ↑ (+5.0%)", "position": "📍 近1年：偏高区间"}]
        md = format_chain_report_markdown(report, price_context=ctx)
        self.assertIn("铜", md)
        self.assertIn("偏高区间", md)

    def test_direction_emoji(self):
        self.assertEqual(direction_emoji("BUY"), "🟢")
        self.assertEqual(direction_emoji("SELL"), "🔴")
        self.assertEqual(direction_emoji("HOLD"), "⚪")

    def test_position_label(self):
        self.assertEqual(position_label(10), "接近底部区间")
        self.assertEqual(position_label(50), "中等水平")
        self.assertEqual(position_label(90), "接近顶部区间")

    def test_period_label(self):
        self.assertEqual(period_label(5), "近5天")
        self.assertEqual(period_label(60), "近2个月")
        self.assertEqual(period_label(250), "近1年")

    def test_format_trend(self):
        result = format_trend([100.0, 105.0, 110.0])
        self.assertIn("↑", result)
        self.assertIn("+10.0%", result)

    def test_format_trend_down(self):
        result = format_trend([110.0, 105.0, 100.0])
        self.assertIn("↓", result)
        self.assertIn("-9.1%", result)

    def test_format_trend_flat(self):
        result = format_trend([100.0, 100.0])
        self.assertIn("→", result)

    def test_format_trend_empty(self):
        self.assertEqual(format_trend([]), "")
        self.assertEqual(format_trend([100.0]), "")


if __name__ == "__main__":
    unittest.main()
