"""仿真市场 m1：鑫丰农贸 —— 每日轮换自定义字体反爬。

页面价格在 HTML 源码里是 PUA 乱码，需加载当日 TTF 才能显示真实数字。
字体映射每天重新洗牌，旧字体解不了新页面。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from common.calendar_def import close_reason
from common.config import FONT_DIR, MARKETS, MOCK_DB
from common.font_builder import build_daily_font, encode_text
from common.products import PRODUCTS

app = FastAPI(title="鑫丰农贸批发市场（仿真）")
SPEC = MARKETS["m1"]
FONT_SUBDIR = FONT_DIR / "m1"


def _ensure_font(day: date) -> dict:
    meta_path = FONT_SUBDIR / f"agriquote-{day.isoformat()}.json"
    if meta_path.exists():
        import json

        return json.loads(meta_path.read_text(encoding="utf-8"))
    return build_daily_font(day, FONT_SUBDIR)


def _rows(day: date) -> list[sqlite3.Row]:
    con = sqlite3.connect(MOCK_DB)
    con.row_factory = sqlite3.Row
    data = con.execute(
        "SELECT * FROM truth_prices WHERE market_id=? AND day=? ORDER BY product_code",
        ("m1", day.isoformat()),
    ).fetchall()
    con.close()
    return data


@app.get("/", response_class=HTMLResponse)
def index(request: Request, day: str | None = Query(default=None)):
    target = date.fromisoformat(day) if day else datetime.now().date()
    reason = close_reason("m1", target)
    if reason:
        return HTMLResponse(
            f"<html><body><h1>鑫丰农贸批发市场</h1><p>{target} {reason}，今日休市。</p></body></html>"
        )
    meta = _ensure_font(target)
    rows = _rows(target)
    trs = []
    for r in rows:
        price_text = f"{r['price']:.2f}"
        garbled = encode_text(price_text, meta["char_to_pua"])
        trs.append(
            f"<tr><td>{r['product_code']}</td><td class='pname'>{_name(r['product_code'])}</td>"
            f"<td class='price' data-code='{r['product_code']}'>{garbled}</td>"
            f"<td>{_unit(r['product_code'])}</td></tr>"
        )
    font_url = f"/fonts/{meta['font_file']}?day={target.isoformat()}"
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>鑫丰农贸 每日行情</title>
<style>
@font-face {{ font-family: 'AgriQuote'; src: url('{font_url}') format('truetype'); }}
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; }} td,th {{ border: 1px solid #999; padding: 6px 14px; }}
.price {{ font-family: 'AgriQuote', sans-serif; font-size: 18px; }}
</style></head><body>
<h1>鑫丰农贸批发市场 · 蔬菜行情</h1>
<p>报价日期：{target}（每日 06:00 更新）</p>
<table><thead><tr><th>编码</th><th>品名</th><th>批发价</th><th>单位</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table>
</body></html>"""
    return HTMLResponse(html)


def _name(code: str) -> str:
    for c, n, _u in PRODUCTS["m1"]:
        if c == code:
            return n
    return code


def _unit(code: str) -> str:
    for c, _n, u in PRODUCTS["m1"]:
        if c == code:
            return u
    return ""


@app.get("/fonts/{name}")
def font_file(name: str, day: str | None = None):
    # 校验文件归属，避免路径穿越
    if not name.startswith("agriquote-") or not name.endswith(".ttf"):
        raise HTTPException(404)
    path = (FONT_SUBDIR / name).resolve()
    if FONT_SUBDIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="font/ttf")


@app.get("/health")
def health():
    return JSONResponse({"market": "m1", "ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8011, log_level="warning")
