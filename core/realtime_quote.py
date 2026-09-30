"""期货实时行情：多源获取（东财 push2 批量 + 新浪 nf_ 原始）。

两个源都返回**带「日期 + 时间」的时间戳**，用于判断行情是否为新
（此前 akshare `futures_zh_spot` 只给 HHMMSS、丢了日期，导致无法判断是否当日）。

策略：
- 新浪 `nf_` 原始接口为主（本机可稳定访问，且自带日期+时间；单位与旧代码一致）；
- 东财 push2 `ulist.np`（fltt=2，一次请求批量、价格已是真实值）为兜底 / 交叉校验；
  注：本机对东财 push2 主站访问不稳定（多为端口拒连），主站不通时自动尝试 push2delay；
- 合并时按「时间戳较新者」选取（相同则优先新浪），两者都缺则跳过该品种。

返回结构：{symbol: {"price": float, "prev_settle": float, "ts": datetime|None, "source": str}}
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# 监控品种 -> 东财 secid（市场ID.主连代码）
# 市场ID：113=上期所 114=大商所 115=郑商所 142=上海国际能源交易中心
_EM_SECIDS: Dict[str, str] = {
    'LH0': '114.lhm', 'JD0': '114.jdm', 'M0': '114.mm', 'C0': '114.cm',
    'CU0': '113.cum', 'AL0': '113.alm', 'RB0': '113.rbm', 'AU0': '113.aum',
    'AG0': '113.agm', 'I0': '114.im', 'SC0': '142.scm', 'A0': '114.am',
    'B0': '114.bm', 'RM0': '115.RMM', 'Y0': '114.ym',
}

# secid -> symbol 反向映射
_EM_REV: Dict[str, str] = {v: k for k, v in _EM_SECIDS.items()}

_HEADERS = {
    "Referer": "https://vip.stock.finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
}

_EM_HOSTS = [
    "https://push2.eastmoney.com",       # 主站（本机可能不通）
    "https://push2delay.eastmoney.com",  # 延迟站（备用）
]

_EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"


# ── 东财 ──────────────────────────────────────────────────

def parse_eastmoney_diff(diff: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """解析东财 ulist 的 diff 列表（纯函数，便于测试）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for it in diff or []:
        mkt = it.get("f13")
        code = it.get("f12")
        sym = _EM_REV.get(f"{mkt}.{code}")
        if not sym:
            continue
        price = it.get("f2")
        if price in (None, "-", ""):
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        chg = it.get("f4")
        try:
            prev = price - float(chg) if chg not in (None, "-", "") else 0.0
        except (TypeError, ValueError):
            prev = 0.0
        ts = None
        f124 = it.get("f124")
        if f124:
            try:
                ts = datetime.fromtimestamp(int(f124))
            except (TypeError, ValueError, OSError):
                ts = None
        out[sym] = {"price": price, "prev_settle": prev, "ts": ts, "source": "eastmoney"}
    return out


def _fetch_eastmoney(symbols: List[str], timeout: float = 5) -> Dict[str, Dict[str, Any]]:
    secids = [_EM_SECIDS[s] for s in symbols if s in _EM_SECIDS]
    if not secids:
        return {}
    params = {
        "fltt": "2",
        "secids": ",".join(secids),
        "fields": "f2,f3,f4,f12,f13,f124",
        "ut": _EM_UT,
    }
    for host in _EM_HOSTS:
        try:
            j = requests.get(f"{host}/api/qt/ulist.np/get", params=params,
                             headers=_HEADERS, timeout=timeout).json()
            diff = ((j or {}).get("data") or {}).get("diff") or []
            if diff:
                return parse_eastmoney_diff(diff)
        except Exception as e:  # noqa: BLE001
            logger.debug("东财行情获取失败(%s): %s", host, e)
    return {}


# ── 新浪 nf_ ──────────────────────────────────────────────

# nf_ 返回字段（逗号分隔）：
# 0 名称 1 时间HHMMSS 2 开 3 高 4 低 5 昨收 6 买 7 卖 8 最新 9 均价
# 10 昨结算 11 买量 12 卖量 13 持仓 14 成交量 15 交易所 16 品种 17 日期YYYY-MM-DD
def parse_sina_text(text: str) -> Dict[str, Dict[str, Any]]:
    """解析新浪 nf_ 原始文本（纯函数，便于测试）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for line in text.split(";"):
        m = re.search(r'hq_str_nf_(\w+)="(.*)"', line)
        if not m:
            continue
        sym = m.group(1)
        body = m.group(2)
        if not body:
            continue
        f = body.split(",")
        if len(f) < 18:
            continue
        try:
            price = float(f[8])
            settle = float(f[10]) if f[10] else 0.0
            last_close = float(f[5]) if f[5] else 0.0
        except ValueError:
            continue
        prev = settle if settle > 0 else last_close
        ts: Optional[datetime] = None
        try:
            ts = datetime.strptime(f[17] + f[1], "%Y-%m-%d%H%M%S")
        except (ValueError, IndexError):
            try:
                ts = datetime.strptime(f[17], "%Y-%m-%d")
            except (ValueError, IndexError):
                ts = None
        out[sym] = {"price": price, "prev_settle": prev, "ts": ts, "source": "sina"}
    return out


def _fetch_sina(symbols: List[str], timeout: float = 10) -> Dict[str, Dict[str, Any]]:
    sub = ",".join("nf_" + s for s in symbols)
    url = f"https://hq.sinajs.cn/rn={int(datetime.now().timestamp())}&list={sub}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        r.encoding = "gbk"
        return parse_sina_text(r.text)
    except Exception as e:  # noqa: BLE001
        logger.debug("新浪行情获取失败: %s", e)
        return {}


# ── 合并 ──────────────────────────────────────────────────

def _pick(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """合并两源（a=东财, b=新浪）：东财时间戳**严格更新**时才用它，否则优先新浪。"""
    if a and b:
        ats, bts = a.get("ts"), b.get("ts")
        if ats and bts:
            return a if ats > bts else b
        return b if bts else (a if ats else b)
    return a or b


def fetch_futures_quotes(symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """获取期货实时行情（多源合并）。"""
    if symbols is None:
        symbols = list(_EM_SECIDS.keys())
    em = _fetch_eastmoney(symbols)
    sina = _fetch_sina(symbols)
    out: Dict[str, Dict[str, Any]] = {}
    for s in symbols:
        pick = _pick(em.get(s), sina.get(s))
        if pick:
            out[s] = pick
    return out
