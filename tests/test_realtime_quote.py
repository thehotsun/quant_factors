"""Tests for 多源期货实时行情解析（东财 push2 + 新浪 nf_）。

只测纯解析/合并函数，不触网。
"""
from datetime import datetime

import core.realtime_quote as rq


SINA_TEXT = (
    'var hq_str_nf_M0="豆粕连续,150448,3366.000,3390.000,3350.000,3372.000,'
    '3370.000,3372.000,3372.000,3369.000,3347.000,1,42,2445036.000,845761,'
    '连,豆粕,2026-09-30";'
    'var hq_str_nf_RB0="螺纹钢连续,150000,3111.000,3131.000,3108.000,3112.000,'
    '3112.000,3113.000,3112.000,3116.000,3109.000,407,60,1592266.000,638932,'
    '沪,螺纹钢,2026-09-30";'
    'var hq_str_nf_LH0="";'
)

EM_DIFF = [
    {"f2": 3372.0, "f3": 0.75, "f4": 25.0, "f12": "mm", "f13": 114, "f124": 1790751888},
    {"f2": 3112.0, "f3": 0.1, "f4": 3.0, "f12": "rbm", "f13": 113, "f124": 1790753124},
    {"f2": "-", "f12": "lhm", "f13": 114, "f124": 0},
    {"f2": 999.0, "f12": "unknown", "f13": 999, "f124": 0},
]


class TestSinaParse:
    def test_parse_basic(self):
        out = rq.parse_sina_text(SINA_TEXT)
        assert set(out) == {"M0", "RB0"}
        m = out["M0"]
        assert m["price"] == 3372.0
        assert m["prev_settle"] == 3347.0  # 昨结算优先
        assert m["source"] == "sina"
        assert m["ts"] == datetime(2026, 9, 30, 15, 4, 48)

    def test_empty_skipped(self):
        out = rq.parse_sina_text(SINA_TEXT)
        assert "LH0" not in out

    def test_ts_has_date(self):
        out = rq.parse_sina_text(SINA_TEXT)
        assert out["RB0"]["ts"].date() == datetime(2026, 9, 30).date()
        assert out["RB0"]["ts"].strftime("%H:%M") == "15:00"


class TestEastmoneyParse:
    def test_parse_basic(self):
        out = rq.parse_eastmoney_diff(EM_DIFF)
        assert set(out) == {"M0", "RB0"}
        m = out["M0"]
        assert m["price"] == 3372.0
        assert m["prev_settle"] == 3347.0  # price - f4
        assert m["source"] == "eastmoney"
        assert m["ts"] == datetime(2026, 9, 30, 15, 4, 48)

    def test_missing_price_skipped(self):
        out = rq.parse_eastmoney_diff(EM_DIFF)
        assert "LH0" not in out  # f2 == "-"

    def test_unknown_symbol_skipped(self):
        out = rq.parse_eastmoney_diff(EM_DIFF)
        assert "unknown" not in out


class TestPick:
    def test_eastmoney_used_only_when_strictly_newer(self):
        a = {"price": 1.0, "ts": datetime(2026, 9, 30, 10, 30), "source": "eastmoney"}
        b = {"price": 2.0, "ts": datetime(2026, 9, 30, 10, 0), "source": "sina"}
        assert rq._pick(a, b) is a

    def test_tie_prefers_sina(self):
        a = {"price": 1.0, "ts": datetime(2026, 9, 30, 10, 0), "source": "eastmoney"}
        b = {"price": 2.0, "ts": datetime(2026, 9, 30, 10, 0), "source": "sina"}
        assert rq._pick(a, b) is b

    def test_older_eastmoney_falls_back_to_sina(self):
        a = {"price": 1.0, "ts": datetime(2026, 9, 30, 9, 0), "source": "eastmoney"}
        b = {"price": 2.0, "ts": datetime(2026, 9, 30, 10, 0), "source": "sina"}
        assert rq._pick(a, b) is b

    def test_fallback_when_one_missing(self):
        a = {"price": 1.0, "ts": None, "source": "eastmoney"}
        assert rq._pick(a, None) is a
        assert rq._pick(None, a) is a
        assert rq._pick(None, None) is None

    def test_tsless_prefers_sina(self):
        a = {"price": 1.0, "ts": None, "source": "eastmoney"}
        b = {"price": 2.0, "ts": None, "source": "sina"}
        assert rq._pick(a, b) is b
