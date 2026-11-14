"""m3 临港果批采集：签名器从页面脚本中发现并在浏览器内执行。

- 枚举页面函数 -> 探针参数试跑 -> 试探请求验证 200，确定当日生效签名器；
- 签名始终由页面自身函数计算，采集端代码不含任何算法；
- 返回数据含 wholesale / landed 两类价格，按 price_type 分别落库。
"""
from __future__ import annotations

import sqlite3
from datetime import date

from common.config import MARKETS, WINDOW_START
from common.products import PRODUCTS
from collector.browser import browser_page
from collector.pipeline import (
    add_snapshot, finish_run, mark_calendar, save_screenshot, start_run, upsert_price,
)
from collector.sign_finder import discover_signer, sign_with


def collect_m3(con: sqlite3.Connection, day: date) -> dict:
    spec = MARKETS["m3"]
    run_id = start_run(con, "m3", day)
    result = {"market": "m3", "day": day.isoformat(), "held": 0, "verified": 0}
    try:
        with browser_page() as page:
            page.goto(f"{spec.base_url}/?day={day.isoformat()}", wait_until="networkidle")
            if "休市" in page.locator("body").inner_text():
                mark_calendar(con, "m3", day, "closed", run_id, 0, 0)
                finish_run(con, run_id, "ok", "休市", 0)
                result["status"] = "closed"
                return result

            shot = save_screenshot(page, "m3", day, "page")
            add_snapshot(con, "m3", day, "png", run_id, file_path=shot, url=page.url)

            day_str = day.isoformat()
            probe_params = {"day": day_str, "market": "m3", "ts": "1700000000"}

            def probe_url_factory(params: dict[str, str], sign: str):
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                resp = page.request.get(
                    f"{spec.base_url}/api/quotes?{qs}&sign={sign}"
                )
                return resp.status, resp.text()

            discovery = discover_signer(page, day, probe_params, probe_url_factory)
            add_snapshot(con, "m3", day, "json", run_id,
                         payload={"signer_discovery": discovery}, url=page.url)
            signer = discovery["signer"]
            if not signer:
                raise RuntimeError("未能在页面中发现可用签名器")

            # 正式请求：时间戳现取，签名现算
            ts = page.evaluate("() => String(Math.floor(Date.now()/1000))")
            params = {"day": day_str, "market": "m3", "ts": ts}
            sign = sign_with(page, signer, params, day_str)
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            resp = page.request.get(f"{spec.base_url}/api/quotes?{qs}&sign={sign}")
            if resp.status != 200:
                raise RuntimeError(f"签名请求被拒: HTTP {resp.status} {resp.text()[:200]}")
            data = resp.json()
            api_snap = add_snapshot(con, "m3", day, "json", run_id,
                                    payload=data, url=resp.url)

            verified = held = 0
            expected = len(PRODUCTS["m3"]) * len(spec.price_types)
            for q in data["quotes"]:
                out = upsert_price(
                    con, "m3", day, q["product_code"], q["price_type"],
                    float(q["price"]), api_snap, run_id, window_start=WINDOW_START,
                )
                verified += out == "verified"
                held += out == "held"

            mark_calendar(con, "m3", day, "done", run_id, expected, verified + held)
            finish_run(con, run_id, "ok" if held == 0 else "partial",
                       f"signer={signer} algo={discovery['algo_response']} "
                       f"verified={verified} held={held}", verified + held)
            result.update(status="ok", signer=signer, algo=discovery["algo_response"],
                          verified=verified, held=held)
    except Exception as exc:  # noqa: BLE001
        finish_run(con, run_id, "failed", repr(exc), 0)
        expected = len(PRODUCTS["m3"]) * len(MARKETS["m3"].price_types)
        mark_calendar(con, "m3", day, "missing", run_id, expected, 0)
        result.update(status="failed", error=repr(exc))
    return result
