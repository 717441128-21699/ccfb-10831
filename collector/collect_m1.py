"""m1 鑫丰农贸采集：浏览器渲染 + 当日字体自动重解。"""
from __future__ import annotations

import sqlite3
from datetime import date

from common.config import MARKETS, WINDOW_START
from collector.browser import browser_page
from collector.font_decoder import decode_page_font, decode_price, save_mapping
from collector.pipeline import (
    add_snapshot, finish_run, mark_calendar, save_screenshot, start_run, upsert_price,
)
from common.products import PRODUCTS


def collect_m1(con: sqlite3.Connection, day: date) -> dict:
    spec = MARKETS["m1"]
    run_id = start_run(con, "m1", day)
    result = {"market": "m1", "day": day.isoformat(), "held": 0, "verified": 0}
    try:
        with browser_page() as page:
            page.goto(f"{spec.base_url}/?day={day.isoformat()}", wait_until="networkidle")
            if "休市" in page.locator("body").inner_text():
                mark_calendar(con, "m1", day, "closed", run_id, 0, 0)
                finish_run(con, run_id, "ok", "休市", 0)
                result["status"] = "closed"
                return result

            # 1) 每次运行重新解码当日字体（不沿用任何历史映射）
            mapping = decode_page_font(page, ".price")
            save_mapping(con, "m1", day, mapping)

            # 2) 整页截图作为原始快照
            shot = save_screenshot(page, "m1", day, "page")
            snap_id = add_snapshot(con, "m1", day, "png", run_id, file_path=shot,
                                   url=page.url)

            # 3) 逐行还原价格
            rows = page.locator("tbody tr")
            verified = held = 0
            parsed = []
            for i in range(rows.count()):
                code = rows.nth(i).locator("td").nth(0).inner_text().strip()
                raw = rows.nth(i).locator("td.price").inner_text().strip()
                price_text = decode_price(raw, mapping)
                price = float(price_text)
                parsed.append({"product_code": code, "raw_pua": raw,
                               "decoded": price_text, "price": price})
                out = upsert_price(con, "m1", day, code, "wholesale", price,
                                   snap_id, run_id, window_start=WINDOW_START)
                verified += out == "verified"
                held += out == "held"

            add_snapshot(con, "m1", day, "json", run_id,
                         payload={"font_mapping": mapping, "rows": parsed}, url=page.url)
            mark_calendar(con, "m1", day, "done", run_id,
                          expected_per_day(), verified + held)
            finish_run(con, run_id, "ok" if held == 0 else "partial",
                       f"verified={verified} held={held}", verified + held)
            result.update(status="ok", verified=verified, held=held)
    except Exception as exc:  # noqa: BLE001
        finish_run(con, run_id, "failed", repr(exc), 0)
        mark_calendar(con, "m1", day, "missing", run_id, expected_per_day(), 0)
        result.update(status="failed", error=repr(exc))
    return result


def expected_per_day() -> int:
    return len(PRODUCTS["m1"])
