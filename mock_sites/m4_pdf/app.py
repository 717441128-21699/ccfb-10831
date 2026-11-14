"""仿真市场 m4 站点：周报 PDF 下载入口（无在线行情页）。"""
from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from common.config import MARKETS, PDF_DIR, WINDOW_END, WINDOW_START
from mock_sites.m4_pdf.pdf_report import ensure_all_reports, report_periods

app = FastAPI(title="西山产地交易市场（仿真）")
SPEC = MARKETS["m4"]


@app.get("/", response_class=HTMLResponse)
def index():
    ensure_all_reports(WINDOW_START, WINDOW_END)
    items = "".join(
        f"<li>{a} ~ {b}：<a href='/download?period_start={a}&period_end={b}'>"
        f"周报 PDF 下载</a></li>"
        for a, b in report_periods(WINDOW_START, WINDOW_END)
    )
    return HTMLResponse(
        f"<html><head><meta charset='utf-8'><title>西山产地市场 周报</title></head>"
        f"<body style='font-family:Microsoft YaHei;margin:24px'>"
        f"<h1>西山产地交易市场 · 信息公开</h1>"
        f"<p>本市场不提供逐日在线行情，每周发布一次产地收购价周报（PDF）。</p>"
        f"<ul>{items}</ul></body></html>"
    )


@app.get("/download")
def download(period_start: date, period_end: date):
    path = PDF_DIR / f"m4_weekly_{period_start.isoformat()}_{period_end.isoformat()}.pdf"
    if not path.exists():
        raise HTTPException(404, "周报尚未发布")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/health")
def health():
    return JSONResponse({"market": "m4", "ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8014, log_level="warning")
