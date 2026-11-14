"""仿真真值引擎：确定性生成 30 天内每个市场/商品/价格类型的「真实价格」。

仿真站各自从这里取数渲染（字体、Canvas、签名接口、PDF），
harness 也从这里取数与采集结果逐条比对。所有数值由 (市场,商品,类型,日期)
哈希决定，完全可复现。

另外确定性注入两类异常素材：
- SPIKE：单日暴涨/暴跌（约 2% 的记录），采集端应识别并「扣留待复核」
- MISMATCH：m2 的第二渠道 JSON 与 Canvas 真值偶尔不一致，应触发交叉印证异常
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from common.calendar_def import is_closed, stable_jitter
from common.config import MARKETS, MOCK_DB, WINDOW_END, WINDOW_START
from common.products import PRODUCTS

# 基准价（元/单位）；m3 同时有批发价与到岸价
BASE_PRICES: dict[tuple[str, str, str], float] = {}
for _code, _name, _u in PRODUCTS["m1"]:
    BASE_PRICES[("m1", _code, "wholesale")] = round(2.0 + (len(_code) % 5) * 0.7, 2)
for _code, _name, _u in PRODUCTS["m2"]:
    BASE_PRICES[("m2", _code, "wholesale")] = round(4.0 + (len(_code) % 6) * 1.1, 2)
for _code, _name, _u in PRODUCTS["m3"]:
    BASE_PRICES[("m3", _code, "wholesale")] = round(6.0 + (len(_code) % 5) * 1.4, 2)
    BASE_PRICES[("m3", _code, "landed")] = round(
        BASE_PRICES[("m3", _code, "wholesale")] + 1.8, 2
    )
for _code, _name, _u in PRODUCTS["m4"]:
    BASE_PRICES[("m4", _code, "farm")] = round(1.2 + (len(_code) % 4) * 0.55, 2)


def _base(market_id: str, code: str, price_type: str) -> float:
    return BASE_PRICES[(market_id, code, price_type)]


def truth_price(market_id: str, code: str, price_type: str, day: date) -> float:
    """某商品某日的真实价格（两位小数），带缓慢漂移与日内波动。"""
    day_index = (day - WINDOW_START).days
    base = _base(market_id, code, price_type)
    # 周级别的缓慢供需漂移 ±12%
    drift = stable_jitter(f"drift|{market_id}|{code}|{price_type}|{day_index // 7}", -0.12, 0.12)
    # 日波动 ±6%
    noise = stable_jitter(f"noise|{market_id}|{code}|{price_type}|{day}", -0.06, 0.06)
    price = base * (1 + drift + noise)
    return round(price, 2)


def is_spike(market_id: str, code: str, price_type: str, day: date) -> bool:
    """确定性标记约 2% 的记录为异常波动日（相对前一开市日 ≥3 倍或 ≤1/3）。"""
    if stable_jitter(f"spike|{market_id}|{code}|{price_type}|{day}", 0, 1) >= 0.02:
        return False
    # 窗口第一天没有上一开市日，不制造 spike
    cur = day - timedelta(days=1)
    while cur >= WINDOW_START and is_closed(market_id, cur):
        cur -= timedelta(days=1)
    return cur >= WINDOW_START


def spike_price(prev_price: float, market_id: str, code: str, price_type: str, day: date) -> float:
    """制造极端价：一半概率 ×3.2，一半概率 ÷3.5。"""
    up = stable_jitter(f"spikeDir|{market_id}|{code}|{price_type}|{day}", 0, 1) > 0.5
    return round(prev_price * 3.2, 2) if up else round(prev_price / 3.5, 2)


def cross_channel_mismatch(market_id: str, code: str, day: date) -> bool:
    """m2 专用：第二渠道 JSON 是否与 Canvas 真值不一致（约 3%）。"""
    return stable_jitter(f"mismatch|{market_id}|{code}|{day}", 0, 1) < 0.03


def mismatch_price(canvas_price: float, market_id: str, code: str, day: date) -> float:
    delta = stable_jitter(f"mismatchAmt|{market_id}|{code}|{day}", 0.12, 0.35)
    sign = 1 if stable_jitter(f"mismatchSign|{market_id}|{code}|{day}", 0, 1) > 0.5 else -1
    return round(canvas_price * (1 + sign * delta), 2)


def generate_all_truth(db_path: Path = MOCK_DB) -> dict[str, int]:
    """把窗口内全部真值写入仿真站私有库，返回各市场行数统计。"""
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS truth_prices(
               market_id TEXT, day TEXT, product_code TEXT, price_type TEXT,
               price REAL, is_spike INTEGER, PRIMARY KEY(market_id,day,product_code,price_type))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS truth_calendar(
               market_id TEXT, day TEXT, is_closed INTEGER, reason TEXT,
               PRIMARY KEY(market_id,day))"""
    )
    con.execute("DELETE FROM truth_prices")
    con.execute("DELETE FROM truth_calendar")

    counts: dict[str, int] = {}
    cur_day = WINDOW_START
    while cur_day <= WINDOW_END:
        for mid, spec in MARKETS.items():
            from common.calendar_def import close_reason

            reason = close_reason(mid, cur_day)
            con.execute(
                "INSERT OR REPLACE INTO truth_calendar VALUES(?,?,?,?)",
                (mid, cur_day.isoformat(), 1 if reason else 0, reason),
            )
            if reason:
                continue
            for code, _name, _unit in PRODUCTS[mid]:
                for ptype in spec.price_types:
                    normal = truth_price(mid, code, ptype, cur_day)
                    price, spike = normal, 0
                    if is_spike(mid, code, ptype, cur_day):
                        # 找上一开市日的真值
                        prev = cur_day - timedelta(days=1)
                        while prev >= WINDOW_START and is_closed(mid, prev):
                            prev -= timedelta(days=1)
                        prev_price = truth_price(mid, code, ptype, prev)
                        price = spike_price(prev_price, mid, code, ptype, cur_day)
                        spike = 1
                    con.execute(
                        "INSERT OR REPLACE INTO truth_prices VALUES(?,?,?,?,?,?)",
                        (mid, cur_day.isoformat(), code, ptype, price, spike),
                    )
                    counts[mid] = counts.get(mid, 0) + 1
        cur_day += timedelta(days=1)
    con.commit()
    con.close()
    return counts


def read_truth(market_id: str, day: date, db_path: Path = MOCK_DB) -> list[sqlite3.Row]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM truth_prices WHERE market_id=? AND day=? ORDER BY product_code,price_type",
        (market_id, day.isoformat()),
    ).fetchall()
    con.close()
    return rows


def read_truth_range(
    market_id: str, start: date, end: date, db_path: Path = MOCK_DB
) -> list[sqlite3.Row]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM truth_prices WHERE market_id=? AND day BETWEEN ? AND ? "
        "ORDER BY day,product_code,price_type",
        (market_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    con.close()
    return rows
