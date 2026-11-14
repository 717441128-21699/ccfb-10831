"""采集调度：市场注册、按日采集、缺数检测与只补真缺日的补采。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from common.calendar_def import close_reason
from common.config import MARKETS, WINDOW_END, WINDOW_START
from common.products import PRODUCTS
from collector.collect_m1 import collect_m1
from collector.collect_m2 import collect_m2
from collector.collect_m3 import collect_m3
from collector.collect_m4 import collect_m4, collect_m4_single_day
from collector.db import connect
from collector.pipeline import init_calendar

DAILY_COLLECTORS = {
    "m1": collect_m1,
    "m2": collect_m2,
    "m3": collect_m3,
}


def register_markets(con: sqlite3.Connection) -> None:
    for mid, spec in MARKETS.items():
        con.execute(
            "INSERT OR REPLACE INTO markets(market_id,name,trick,base_url,price_types,enabled)"
            " VALUES(?,?,?,?,?,1)",
            (mid, spec.name, spec.trick, spec.base_url, ",".join(spec.price_types)),
        )
        expected_per_day = len(PRODUCTS[mid]) * len(spec.price_types)
        init_calendar(con, mid, WINDOW_START, WINDOW_END, expected_per_day)
    con.commit()


def collect_day(market_id: str, day: date, con: sqlite3.Connection | None = None) -> dict:
    own = con is None
    con = con or connect()
    try:
        if close_reason(market_id, day):
            from collector.pipeline import mark_calendar

            mark_calendar(con, market_id, day, "closed", None, 0, 0)
            return {"market": market_id, "day": day.isoformat(), "status": "closed"}
        if market_id in DAILY_COLLECTORS:
            return DAILY_COLLECTORS[market_id](con, day)
        if market_id == "m4":
            return collect_m4_single_day(con, day)
        raise KeyError(market_id)
    finally:
        if own:
            con.close()


def find_missing_days(con: sqlite3.Connection, market_id: str,
                      start: date, end: date) -> list[date]:
    """真缺数 = 应开市 且 日历状态不是 done（休市日自动排除）。"""
    rows = con.execute(
        "SELECT day,expected,collect_status FROM collection_calendar "
        "WHERE market_id=? AND day BETWEEN ? AND ? ORDER BY day",
        (market_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    missing = []
    for r in rows:
        if r["expected"] == "open" and r["collect_status"] != "done":
            missing.append(date.fromisoformat(r["day"]))
    return missing


def backfill(con: sqlite3.Connection, market_id: str, start: date, end: date) -> list[dict]:
    """只补真缺的开市日；休市日跳过并在结果里标明。"""
    results = []
    for day in find_missing_days(con, market_id, start, end):
        results.append(collect_day(market_id, day, con))
    return results


def run_window(con: sqlite3.Connection, start: date, end: date) -> list[dict]:
    """按时间顺序跑完整窗口（保证 spike 检测能找到上一开市日基准）。"""
    results = []
    cur = start
    while cur <= end:
        for mid in ("m1", "m2", "m3"):
            results.append(collect_day(mid, cur, con))
        cur += timedelta(days=1)
    # m4 周报在全部日报之后批量采集
    results.append(collect_m4(con, start, end))
    return results
