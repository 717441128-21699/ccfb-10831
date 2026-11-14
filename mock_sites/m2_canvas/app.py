"""仿真市场 m2：城南农副 —— 价格画在 Canvas 上，DOM 里没有数字。

同时提供一个「合作渠道 JSON 接口」用于交叉印证，但该渠道约 3% 的
记录与官网 Canvas 真值不一致（模拟多源数据冲突），采集端需要发现。
"""
from __future__ import annotations

import io
import sqlite3
from datetime import date, datetime

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from PIL import Image, ImageDraw, ImageFont

from common.calendar_def import close_reason
from common.config import MARKETS, MOCK_DB
from common.products import PRODUCTS
from common.truth import cross_channel_mismatch, mismatch_price

app = FastAPI(title="城南农副产品批发市场（仿真）")
SPEC = MARKETS["m2"]

# 多个渲染字体，增加 OCR 难度（采集端用浏览器渲染模板匹配，不依赖字体文件）
RENDER_FONTS = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
]
ROW_H, ROW_W = 64, 760


def _rows(day: date) -> list[sqlite3.Row]:
    con = sqlite3.connect(MOCK_DB)
    con.row_factory = sqlite3.Row
    data = con.execute(
        "SELECT * FROM truth_prices WHERE market_id=? AND day=? ORDER BY product_code",
        ("m2", day.isoformat()),
    ).fetchall()
    con.close()
    return data


def _name(code: str) -> str:
    for c, n, _u in PRODUCTS["m2"]:
        if c == code:
            return n
    return code


def _unit(code: str) -> str:
    for c, _n, u in PRODUCTS["m2"]:
        if c == code:
            return u
    return ""


@app.get("/", response_class=HTMLResponse)
def index(request: Request, day: str | None = Query(default=None)):
    target = date.fromisoformat(day) if day else datetime.now().date()
    reason = close_reason("m2", target)
    if reason:
        return HTMLResponse(
            f"<html><body><h1>城南农副产品批发市场</h1><p>{target} {reason}，今日休市。</p></body></html>"
        )
    rows = _rows(target)
    body_rows = "".join(
        f"<tr><td>{r['product_code']}</td><td>{_name(r['product_code'])}</td>"
        f"<td><canvas id='cv_{r['product_code']}' width='150' height='34'></canvas></td>"
        f"<td>{_unit(r['product_code'])}</td></tr>"
        for r in rows
    )
    # 价格只通过图片接口下发，脚本把图片画进 canvas；页面文本中不出现任何数字
    img_js = "".join(
        f"""
(async()=>{{
  const img = new Image();
  img.src = '/price_image?day={target.isoformat()}&code={r['product_code']}';
  await img.decode();
  const cv = document.getElementById('cv_{r['product_code']}');
  cv.getContext('2d').drawImage(img, 0, 0);
}})();"""
        for r in rows
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>城南市场 果品行行情</title>
<style>body {{ font-family:'Microsoft YaHei',sans-serif; margin:24px; }}
table {{ border-collapse:collapse; }} td,th {{ border:1px solid #999; padding:6px 14px; }}</style>
</head><body>
<h1>城南农副产品批发市场 · 果品行情</h1>
<p>报价日期：{target}</p>
<table><thead><tr><th>编码</th><th>品名</th><th>批发价</th><th>单位</th></tr></thead>
<tbody>{body_rows}</tbody></table>
<script>{img_js}</script>
</body></html>"""
    return HTMLResponse(html)


@app.get("/price_image")
def price_image(day: str, code: str):
    target = date.fromisoformat(day)
    rows = _rows(target)
    rec = next((r for r in rows if r["product_code"] == code), None)
    if rec is None:
        return Response(status_code=404)
    font_path = RENDER_FONTS[target.toordinal() % len(RENDER_FONTS)]
    font = ImageFont.truetype(font_path, 24)
    img = Image.new("RGB", (150, 34), "white")
    draw = ImageDraw.Draw(img)
    draw.text((8, 3), f"{rec['price']:.2f}", fill=(20, 20, 20), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.get("/channel/quotes")
def channel_quotes(day: str):
    """第二渠道：结构化 JSON，便于采集端交叉印证，但含确定性偏差。"""
    target = date.fromisoformat(day)
    out = []
    for r in _rows(target):
        canvas_price = r["price"]
        if cross_channel_mismatch("m2", r["product_code"], target):
            shown = mismatch_price(canvas_price, "m2", r["product_code"], target)
        else:
            shown = canvas_price
        out.append(
            {
                "product_code": r["product_code"],
                "price": shown,
                "source": "partner-feed-b",
                "updated_at": f"{day}T06:05:00",
            }
        )
    return JSONResponse({"day": day, "quotes": out})


@app.get("/health")
def health():
    return JSONResponse({"market": "m2", "ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8012, log_level="warning")
