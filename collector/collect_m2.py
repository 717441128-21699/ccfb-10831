"""m2 城南市场采集：Canvas 数字 OCR + 第二渠道交叉印证。

流程：
1. 浏览器打开行情页，等待 canvas 绘制完成，逐个 canvas 截图做模板 OCR；
2. 同时请求合作渠道 JSON；
3. 两边价格偏差 > 2% 时，以官网 Canvas 为准入价格库，但同时登记
   cross_mismatch 异常扣留，等待人工复核渠道冲突；
4. 暴涨暴跌仍由统一流水线的 spike 规则兜底。
"""
from __future__ import annotations

import io
import sqlite3
from datetime import date

from PIL import Image
from playwright.sync_api import Page

from common.config import CROSS_TOLERANCE, MARKETS, WINDOW_START
from common.products import PRODUCTS
from collector.browser import browser_page
from collector.pipeline import (
    add_snapshot, finish_run, hold_anomaly, mark_calendar, save_screenshot,
    start_run, upsert_price,
)
from collector.vision import build_digit_templates, ocr_digits


def _wait_canvas_ready(page: Page) -> None:
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('canvas')).every(cv => {
            const ctx = cv.getContext('2d');
            const data = ctx.getImageData(0, 0, cv.width, cv.height).data;
            return data.some(v => v !== 0);
        })""",
        timeout=15000,
    )


def collect_m2(con: sqlite3.Connection, day: date) -> dict:
    spec = MARKETS["m2"]
    run_id = start_run(con, "m2", day)
    result = {"market": "m2", "day": day.isoformat(), "held": 0, "verified": 0}
    try:
        with browser_page() as page:
            page.goto(f"{spec.base_url}/?day={day.isoformat()}", wait_until="networkidle")
            if "休市" in page.locator("body").inner_text():
                mark_calendar(con, "m2", day, "closed", run_id, 0, 0)
                finish_run(con, run_id, "ok", "休市", 0)
                result["status"] = "closed"
                return result

            _wait_canvas_ready(page)
            shot = save_screenshot(page, "m2", day, "page")
            page_snap = add_snapshot(con, "m2", day, "png", run_id, file_path=shot,
                                     url=page.url)

            # 第二渠道（在同一浏览器上下文里请求，保留真实采集形态）
            channel = page.request.get(f"{spec.base_url}/channel/quotes?day={day.isoformat()}")
            channel_data = channel.json()
            channel_snap = add_snapshot(con, "m2", day, "json", run_id,
                                        payload=channel_data, url=channel.url)
            channel_map = {q["product_code"]: float(q["price"]) for q in channel_data["quotes"]}

            templates = build_digit_templates()
            canvases = page.locator("canvas")
            rows = page.locator("tbody tr")
            ocr_records, max_conf = [], 0.0
            for i in range(canvases.count()):
                code = rows.nth(i).locator("td").nth(0).inner_text().strip()
                png_bytes = canvases.nth(i).screenshot()
                img = Image.open(io.BytesIO(png_bytes))
                text, confidence = ocr_digits(img, templates)
                max_conf = max(max_conf, confidence)
                ocr_records.append({"product_code": code, "ocr_text": text,
                                    "price": float(text), "worst_diff": confidence})

            verified = held = mismatches = 0
            for rec in ocr_records:
                code, price = rec["product_code"], rec["price"]
                other = channel_map.get(code)
                if other is not None and abs(price - other) / price > CROSS_TOLERANCE:
                    hold_anomaly(
                        con, "m2", day, code, "wholesale", price, other,
                        "cross_mismatch",
                        f"Canvas OCR={price:.2f} 与合作渠道={other:.2f} 偏差超 {CROSS_TOLERANCE:.0%}",
                        channel_snap,
                    )
                    upsert_price(con, "m2", day, code, "wholesale", price,
                                 page_snap, run_id, status="held")
                    mismatches += 1
                    held += 1
                    continue
                out = upsert_price(con, "m2", day, code, "wholesale", price,
                                   page_snap, run_id, window_start=WINDOW_START)
                verified += out == "verified"
                held += out == "held"

            add_snapshot(con, "m2", day, "json", run_id,
                         payload={"ocr": ocr_records, "worst_template_diff": max_conf},
                         url=page.url)
            mark_calendar(con, "m2", day, "done", run_id,
                          len(PRODUCTS["m2"]), verified + held)
            finish_run(con, run_id, "ok" if held == 0 else "partial",
                       f"verified={verified} held={held} cross_mismatch={mismatches} "
                       f"ocr_worst_diff={max_conf:.3f}",
                       verified + held)
            result.update(status="ok", verified=verified, held=held,
                          cross_mismatch=mismatches, ocr_worst_diff=max_conf)
    except Exception as exc:  # noqa: BLE001
        finish_run(con, run_id, "failed", repr(exc), 0)
        mark_calendar(con, "m2", day, "missing", run_id, len(PRODUCTS["m2"]), 0)
        result.update(status="failed", error=repr(exc))
    return result
