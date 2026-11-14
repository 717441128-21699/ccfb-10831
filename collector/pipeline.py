"""采集公共流水线：快照、异常检测、价格落库、日历状态。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from common.calendar_def import close_reason, is_closed
from common.config import MARKETS, SNAPSHOT_DIR, SPIKE_HIGH, SPIKE_LOW
from common.products import product_unit


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_run(con: sqlite3.Connection, market_id: str, day: date | None) -> int:
    cur = con.execute(
        "INSERT INTO collection_runs(market_id,day,started_at,status) VALUES(?,?,?,?)",
        (market_id, day.isoformat() if day else None, now_iso(), "running"),
    )
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id: int, status: str, message: str, rows_collected: int) -> None:
    con.execute(
        "UPDATE collection_runs SET finished_at=?,status=?,message=?,rows_collected=? WHERE run_id=?",
        (now_iso(), status, message, rows_collected, run_id),
    )
    con.commit()


def add_snapshot(con, market_id: str, day: date, kind: str, run_id: int,
                 file_path: Path | None = None, payload: dict | list | None = None,
                 url: str | None = None) -> int:
    payload_ref = None
    if payload is not None:
        payload_dir = SNAPSHOT_DIR / market_id / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        # 同一 run 可能产生多个同类型报文（如 m3 的签名发现记录与 API 响应），
        # 用短哈希区分，避免文件互相覆盖
        digest = hashlib.sha1(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:8]
        pf = payload_dir / f"{day.isoformat()}_{kind}_{run_id}_{digest}.json"
        pf.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload_ref = str(pf)
    cur = con.execute(
        "INSERT INTO snapshots(market_id,day,kind,file_path,payload_ref,url,created_at,run_id)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (market_id, day.isoformat(), kind, str(file_path) if file_path else None,
         payload_ref, url, now_iso(), run_id),
    )
    con.commit()
    return cur.lastrowid


def save_screenshot(page, market_id: str, day: date, tag: str) -> Path:
    d = SNAPSHOT_DIR / market_id / day.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{tag}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def _previous_open_day(market_id: str, day: date, start: date) -> date | None:
    cur = day - timedelta(days=1)
    while cur >= start:
        if not is_closed(market_id, cur):
            return cur
        cur -= timedelta(days=1)
    return None


def check_spike(con, market_id: str, day: date, product_code: str,
                price_type: str, price: float, window_start: date) -> tuple[bool, str, float | None]:
    """与上一开市日的已验证价格比较，返回 (是否异常, 原因, 参考价)。"""
    prev = _previous_open_day(market_id, day, window_start)
    if prev is None:
        return False, "", None
    row = con.execute(
        "SELECT price FROM prices WHERE market_id=? AND day=? AND product_code=? "
        "AND price_type=? AND status='verified'",
        (market_id, prev.isoformat(), product_code, price_type),
    ).fetchone()
    if row is None:
        return False, "", None
    ref = float(row["price"])
    ratio = price / ref if ref else 1.0
    if ratio >= SPIKE_HIGH:
        return True, "spike_high", ref
    if ratio <= SPIKE_LOW:
        return True, "spike_low", ref
    return False, "", ref


def hold_anomaly(con, market_id: str, day: date, product_code: str, price_type: str,
                 observed: float, reference: float | None, reason: str, detail: str,
                 snapshot_id: int) -> int:
    cur = con.execute(
        "INSERT INTO anomalies(market_id,day,product_code,price_type,observed_price,"
        "reference_price,reason,detail,snapshot_id,status,created_at) VALUES(?,?,?,?,?,?,?,?,?, 'held', ?)",
        (market_id, day.isoformat(), product_code, price_type, observed, reference,
         reason, detail, snapshot_id, now_iso()),
    )
    con.commit()
    return cur.lastrowid


def upsert_price(con, market_id: str, day: date, product_code: str, price_type: str,
                 price: float, snapshot_id: int, run_id: int,
                 status: str = "verified", window_start: date | None = None) -> str:
    """写入一条价格。

    - price_type 受 markets.price_types 与表级 CHECK 双重约束，杜绝三类价格串写；
    - 超阈值波动先写 anomalies 扣留，不进 verified 价格库。
    返回 'verified' / 'held' / 'updated'。
    """
    spec = MARKETS[market_id]
    if price_type not in spec.price_types:
        raise ValueError(
            f"市场 {market_id} 不允许价格类型 {price_type}（允许：{spec.price_types}）"
        )
    unit = product_unit(market_id, product_code)

    if status == "verified" and window_start is not None:
        bad, reason, ref = check_spike(
            con, market_id, day, product_code, price_type, price, window_start
        )
        if bad:
            hold_anomaly(con, market_id, day, product_code, price_type, price, ref,
                         reason, f"相对上一开市日 {ref} 波动超阈值", snapshot_id)
            # 扣留而非丢弃：留一条 held 价格行，复核后可直接转正，保证价格库不缺数
            status = "held"

    con.execute(
        "INSERT INTO prices(market_id,day,product_code,price_type,price,unit,"
        "snapshot_id,run_id,status,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(market_id,day,product_code,price_type) DO UPDATE SET "
        "price=excluded.price,unit=excluded.unit,snapshot_id=excluded.snapshot_id,"
        "run_id=excluded.run_id,status=excluded.status,collected_at=excluded.collected_at",
        (market_id, day.isoformat(), product_code, price_type, price, unit,
         snapshot_id, run_id, status, now_iso()),
    )
    con.commit()
    return status


def mark_calendar(con, market_id: str, day: date, status: str, run_id: int | None,
                  expected_count: int, collected_count: int) -> None:
    reason = close_reason(market_id, day)
    expected = "closed" if reason else "open"
    con.execute(
        "INSERT INTO collection_calendar(market_id,day,expected,close_reason,collect_status,"
        "run_id,expected_count,collected_count) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(market_id,day) DO UPDATE SET collect_status=excluded.collect_status,"
        "run_id=excluded.run_id,expected_count=excluded.expected_count,"
        "collected_count=excluded.collected_count",
        (market_id, day.isoformat(), expected, reason,
         "closed" if reason else status, run_id, expected_count, collected_count),
    )
    con.commit()


def init_calendar(con, market_id: str, start: date, end: date, expected_per_day: int) -> None:
    """初始化窗口内日历：休市日直接置 closed，其余 pending。"""
    cur = start
    while cur <= end:
        reason = close_reason(market_id, cur)
        con.execute(
            "INSERT OR IGNORE INTO collection_calendar(market_id,day,expected,close_reason,"
            "collect_status,expected_count) VALUES(?,?,?,?,?,?)",
            (market_id, cur.isoformat(), "closed" if reason else "open", reason,
             "closed" if reason else "pending", 0 if reason else expected_per_day),
        )
        cur += timedelta(days=1)
    con.commit()
