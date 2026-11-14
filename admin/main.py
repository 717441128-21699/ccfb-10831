"""管理后台：市场管理 / 采集日历 / 原始快照 / 价格库 / 异常价格。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from common.config import MARKETS, PRICE_TYPE_LABEL, SNAPSHOT_DIR
from collector.db import connect
from collector.review import review_anomaly
from collector.scheduler import collect_day, find_missing_days
from common.config import WINDOW_END, WINDOW_START

app = FastAPI(title="农批价格指数采集后台")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/snapshot_files", StaticFiles(directory=str(SNAPSHOT_DIR)), name="snapshot_files")


def _rel(p: str | None) -> str | None:
    if not p:
        return None
    try:
        return str(Path(p).relative_to(SNAPSHOT_DIR)).replace("\\", "/")
    except ValueError:
        return None


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    con = connect()
    stats = {
        "prices": con.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"],
        "held": con.execute("SELECT COUNT(*) c FROM prices WHERE status='held'").fetchone()["c"],
        "anomalies_held": con.execute(
            "SELECT COUNT(*) c FROM anomalies WHERE status='held'").fetchone()["c"],
        "snapshots": con.execute("SELECT COUNT(*) c FROM snapshots").fetchone()["c"],
        "runs_failed": con.execute(
            "SELECT COUNT(*) c FROM collection_runs WHERE status='failed'").fetchone()["c"],
    }
    con.close()
    return TEMPLATES.TemplateResponse(request, "home.html", {"stats": stats})


# ---------- 1. 市场管理 ----------
@app.get("/markets", response_class=HTMLResponse)
def markets_page(request: Request):
    con = connect()
    rows = con.execute("SELECT * FROM markets ORDER BY market_id").fetchall()
    latest_runs = {}
    for r in rows:
        run = con.execute(
            "SELECT * FROM collection_runs WHERE market_id=? ORDER BY run_id DESC LIMIT 1",
            (r["market_id"],),
        ).fetchone()
        latest_runs[r["market_id"]] = run
    con.close()
    return TEMPLATES.TemplateResponse(
        request, "markets.html",
        {"rows": rows, "runs": latest_runs, "type_label": PRICE_TYPE_LABEL},
    )


@app.post("/markets/{market_id}/toggle")
def toggle_market(market_id: str):
    con = connect()
    con.execute("UPDATE markets SET enabled = 1 - enabled WHERE market_id=?", (market_id,))
    con.commit()
    con.close()
    return RedirectResponse("/markets", status_code=303)


# ---------- 2. 采集日历 ----------
@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, market_id: str = "m1"):
    con = connect()
    rows = con.execute(
        "SELECT * FROM collection_calendar WHERE market_id=? ORDER BY day", (market_id,)
    ).fetchall()
    missing = find_missing_days(con, market_id, WINDOW_START, WINDOW_END)
    markets = con.execute("SELECT market_id,name FROM markets ORDER BY market_id").fetchall()
    con.close()
    by_day = {r["day"]: r for r in rows}
    # 按周分组便于渲染；窗口起点不是周一时前面补空单元格
    weeks: list[list] = []
    from datetime import timedelta
    cur = WINDOW_START
    bucket = [None] * cur.weekday()
    while cur <= WINDOW_END:
        bucket.append((cur, by_day.get(cur.isoformat())))
        if cur.weekday() == 6:
            weeks.append(bucket)
            bucket = []
        cur += timedelta(days=1)
    if any(bucket):
        bucket += [None] * (7 - len(bucket))
        weeks.append(bucket)
    return TEMPLATES.TemplateResponse(
        request, "calendar.html",
        {"weeks": weeks, "market_id": market_id,
         "markets": markets, "missing": [d.isoformat() for d in missing]},
    )


@app.post("/calendar/collect")
def manual_collect(market_id: str = Form(...), day: str = Form(...)):
    con = connect()
    collect_day(market_id, date.fromisoformat(day), con)
    con.close()
    return RedirectResponse(f"/calendar?market_id={market_id}", status_code=303)


# ---------- 3. 原始快照 ----------
@app.get("/snapshots", response_class=HTMLResponse)
def snapshots_page(request: Request, market_id: str = "m1", kind: str = ""):
    con = connect()
    sql = "SELECT * FROM snapshots WHERE market_id=?"
    params: list = [market_id]
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    sql += " ORDER BY snapshot_id DESC LIMIT 200"
    rows = con.execute(sql, params).fetchall()
    enriched = []
    for r in rows:
        d = dict(r)
        d["file_url"] = "/snapshot_files/" + _rel(r["file_path"]) if _rel(r["file_path"]) else None
        d["payload_url"] = (
            "/snapshot_files/" + _rel(r["payload_ref"]) if _rel(r["payload_ref"]) else None
        )
        enriched.append(d)
    markets = con.execute("SELECT market_id,name FROM markets ORDER BY market_id").fetchall()
    con.close()
    return TEMPLATES.TemplateResponse(
        request, "snapshots.html",
        {"rows": enriched, "market_id": market_id,
         "kind": kind, "markets": markets},
    )


# ---------- 4. 价格库 ----------
@app.get("/prices", response_class=HTMLResponse)
def prices_page(request: Request, market_id: str = "m1", day: str = "",
                price_type: str = "", status: str = ""):
    con = connect()
    sql = """SELECT p.*, s.file_path, s.payload_ref FROM prices p
             LEFT JOIN snapshots s ON s.snapshot_id=p.snapshot_id
             WHERE p.market_id=?"""
    params: list = [market_id]
    if day:
        sql += " AND p.day=?"
        params.append(day)
    if price_type:
        sql += " AND p.price_type=?"
        params.append(price_type)
    if status:
        sql += " AND p.status=?"
        params.append(status)
    sql += " ORDER BY p.day DESC, p.product_code LIMIT 500"
    rows = []
    for r in con.execute(sql, params).fetchall():
        d = dict(r)
        d["file_url"] = "/snapshot_files/" + _rel(r["file_path"]) if _rel(r["file_path"]) else None
        d["payload_url"] = (
            "/snapshot_files/" + _rel(r["payload_ref"]) if _rel(r["payload_ref"]) else None
        )
        rows.append(d)
    markets = con.execute("SELECT market_id,name FROM markets ORDER BY market_id").fetchall()
    allowed_types = MARKETS[market_id].price_types
    con.close()
    return TEMPLATES.TemplateResponse(
        request, "prices.html",
        {"rows": rows, "market_id": market_id, "day": day,
         "price_type": price_type, "status": status, "markets": markets,
         "allowed_types": allowed_types, "type_label": PRICE_TYPE_LABEL},
    )


# ---------- 5. 异常价格 ----------
@app.get("/anomalies", response_class=HTMLResponse)
def anomalies_page(request: Request, status: str = "held"):
    con = connect()
    rows = con.execute(
        "SELECT * FROM anomalies WHERE status=? ORDER BY day DESC, anomaly_id DESC",
        (status,),
    ).fetchall()
    counts = dict(con.execute(
        "SELECT status, COUNT(*) c FROM anomalies GROUP BY status").fetchall())
    con.close()
    return TEMPLATES.TemplateResponse(
        request, "anomalies.html",
        {"rows": rows, "status": status, "counts": counts,
         "type_label": PRICE_TYPE_LABEL},
    )


@app.post("/anomalies/{anomaly_id}/review")
def review(anomaly_id: int, decision: str = Form(...), note: str = Form("")):
    con = connect()
    review_anomaly(con, anomaly_id, decision, note)
    con.close()
    return RedirectResponse("/anomalies?status=held", status_code=303)


@app.get("/media/snapshot")
def media_snapshot(snapshot_id: int):
    """按 snapshot_id 直接代理原始文件（截图/PDF）。"""
    con = connect()
    r = con.execute(
        "SELECT file_path,payload_ref,kind FROM snapshots WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    con.close()
    if r is None:
        return HTMLResponse("快照不存在", status_code=404)
    target = r["file_path"] or r["payload_ref"]
    if not target or not Path(target).exists():
        return HTMLResponse("快照文件丢失", status_code=404)
    media = "application/pdf" if r["kind"] == "pdf" else "image/png"
    return FileResponse(target, media_type=media)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
