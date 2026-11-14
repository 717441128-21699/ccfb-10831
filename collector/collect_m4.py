"""m4 西山产地采集：下载周报 PDF，跨页表格拆成逐日明细。

PDF 本身作为 pdf 类型快照留存；解析出的每条产地价都带该 PDF 的
snapshot_id，满足「每条价格追到原始快照」。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import requests

from common.config import MARKETS, SNAPSHOT_DIR, WINDOW_START
from common.products import PRODUCTS
from mock_sites.m4_pdf.pdf_report import report_periods
from collector.pdf_parser import parse_weekly_pdf
from collector.pipeline import (
    add_snapshot, finish_run, mark_calendar, start_run, upsert_price,
)


def _download(page_or_none, spec, period_start: date, period_end: date) -> Path:
    url = f"{spec.base_url}/download?period_start={period_start.isoformat()}" \
          f"&period_end={period_end.isoformat()}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    d = SNAPSHOT_DIR / "m4" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"m4_weekly_{period_start.isoformat()}_{period_end.isoformat()}.pdf"
    out.write_bytes(resp.content)
    return out


def collect_m4(con: sqlite3.Connection, window_start: date, window_end: date) -> dict:
    """周报市场按窗口批量采集（覆盖窗口内所有周报）。"""
    spec = MARKETS["m4"]
    run_id = start_run(con, "m4", None)
    result = {"market": "m4", "held": 0, "verified": 0}

    try:
        verified = held = 0
        per_day_status: dict[str, list[str]] = {}
        for period_start, period_end in report_periods(window_start, window_end):
            pdf_path = _download(None, spec, period_start, period_end)
            snap_id = add_snapshot(con, "m4", period_start, "pdf", run_id,
                                   file_path=pdf_path,
                                   url=f"{spec.base_url}/download")
            rows = parse_weekly_pdf(pdf_path)
            for r in rows:
                day = date.fromisoformat(r.day)
                out = upsert_price(con, "m4", day, r.product_code, "farm", r.price,
                                   snap_id, run_id, window_start=WINDOW_START)
                verified += out == "verified"
                held += out == "held"
                per_day_status.setdefault(r.day, []).append(out)

        # 更新窗口内每个开市日的日历状态
        cur = window_start
        while cur <= window_end:
            day_rows = per_day_status.get(cur.isoformat(), [])
            if day_rows:
                mark_calendar(con, "m4", cur, "done", run_id,
                              len(PRODUCTS["m4"]), len(day_rows))
            cur += timedelta(days=1)

        periods = report_periods(window_start, window_end)
        finish_run(con, run_id, "ok" if held == 0 else "partial",
                   f"PDF 周报 {len(periods)} 份 "
                   f"verified={verified} held={held}", verified + held)
        result.update(status="ok", verified=verified, held=held)
    except Exception as exc:  # noqa: BLE001
        finish_run(con, run_id, "failed", repr(exc), 0)
        result.update(status="failed", error=repr(exc))
    return result


def collect_m4_single_day(con: sqlite3.Connection, day: date) -> dict:
    """补采单日：找到包含该日的周报并重新解析落库。"""
    spec = MARKETS["m4"]
    run_id = start_run(con, "m4", day)
    try:
        target_period = next(
            ((a, b) for a, b in report_periods(WINDOW_START, day) if a <= day <= b),
            None,
        )
        if target_period is None:
            finish_run(con, run_id, "failed", "无对应周报", 0)
            return {"market": "m4", "day": day.isoformat(), "status": "failed"}
        pdf_path = _download(None, spec, *target_period)
        snap_id = add_snapshot(con, "m4", day, "pdf", run_id, file_path=pdf_path)
        rows = [r for r in parse_weekly_pdf(pdf_path) if r.day == day.isoformat()]
        verified = held = 0
        for r in rows:
            out = upsert_price(con, "m4", day, r.product_code, "farm", r.price,
                               snap_id, run_id, window_start=WINDOW_START)
            verified += out == "verified"
            held += out == "held"
        mark_calendar(con, "m4", day, "done", run_id, len(PRODUCTS["m4"]),
                      verified + held)
        finish_run(con, run_id, "ok" if held == 0 else "partial",
                   f"单日补采 verified={verified} held={held}", verified + held)
        return {"market": "m4", "day": day.isoformat(), "status": "ok",
                "verified": verified, "held": held}
    except Exception as exc:  # noqa: BLE001
        finish_run(con, run_id, "failed", repr(exc), 0)
        mark_calendar(con, "m4", day, "missing", run_id, len(PRODUCTS["m4"]), 0)
        return {"market": "m4", "day": day.isoformat(), "status": "failed",
                "error": repr(exc)}
