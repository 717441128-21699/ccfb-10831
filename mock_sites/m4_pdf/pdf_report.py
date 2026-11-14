"""仿真市场 m4：西山产地 —— 只发周报 PDF，且表格跨页、含续页表头与合并行。

PDF 由 reportlab 生成：
- 每份周报覆盖 7 天（含休市日，休市日在表内注明「休市」无价格）；
- 每页固定行数，数据多时自然跨页，续页重复表头；
- 表头列为「产地价」，与 m3 的批发/到岸价天然隔离；
采集端用 pdfplumber 还原明细（见 collector/pdf_parser.py）。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from common.calendar_def import close_reason
from common.config import MOCK_DB, PDF_DIR
from common.products import PRODUCTS

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"

ROWS_PER_PAGE = 14  # 故意设小，保证 8 个商品 × 7 天的周报跨多页


def report_periods(start: date, end: date) -> list[tuple[date, date]]:
    """按窗口起点每 7 天切一份周报。"""
    periods = []
    cur = start
    while cur <= end:
        period_end = min(cur + timedelta(days=6), end)
        periods.append((cur, period_end))
        cur = period_end + timedelta(days=1)
    return periods


def _truth_rows(day: date) -> dict[str, float]:
    con = sqlite3.connect(MOCK_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT product_code,price FROM truth_prices WHERE market_id=? AND day=?",
        ("m4", day.isoformat()),
    ).fetchall()
    con.close()
    return {r["product_code"]: r["price"] for r in rows}


def build_weekly_pdf(period_start: date, period_end: date) -> Path:
    out = PDF_DIR / f"m4_weekly_{period_start.isoformat()}_{period_end.isoformat()}.pdf"
    if out.exists():
        return out

    styles = getSampleStyleSheet()
    base = ParagraphStyle("cn", parent=styles["Normal"], fontName=FONT, fontSize=10, leading=14)
    title = ParagraphStyle("cnt", parent=styles["Title"], fontName=FONT, fontSize=16, leading=22)
    note = ParagraphStyle("cnn", parent=base, textColor=colors.grey)

    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
    )
    story = [
        Paragraph("西山产地交易市场 · 产地收购价周报", title),
        Paragraph(f"报告周期：{period_start} 至 {period_end}（单位：元/计量单位）", base),
        Paragraph("发布机构：西山市场信息中心（仿真数据）", note),
        Spacer(1, 6 * mm),
    ]

    header = ["日期", "商品编码", "商品名称", "单位", "产地价", "备注"]
    data: list[list[str]] = [header]
    cur = period_start
    while cur <= period_end:
        reason = close_reason("m4", cur)
        prices = {} if reason else _truth_rows(cur)
        for code, name, unit in PRODUCTS["m4"]:
            if reason:
                data.append([cur.isoformat(), code, name, unit, "—", reason])
            else:
                data.append([cur.isoformat(), code, name, unit, f"{prices[code]:.2f}", ""])
        cur += timedelta(days=1)

    # 手工分页：每页 ROWS_PER_PAGE 条数据行，续页重复表头，模拟真实跨页表
    col_widths = [26 * mm, 24 * mm, 30 * mm, 22 * mm, 26 * mm, 40 * mm]
    first = True
    for page_start in range(1, len(data), ROWS_PER_PAGE):
        if not first:
            story.append(Spacer(1, 4 * mm))
        chunk = [header] + data[page_start:page_start + ROWS_PER_PAGE]
        tbl = Table(chunk, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                    ("ALIGN", (4, 1), (4, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(tbl)
        first = False
        if page_start + ROWS_PER_PAGE < len(data):
            story.append(PageBreak())

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("注：「—」表示当日休市无成交；本表价格均为产地收购价。", note))
    doc.build(story)
    return out


def ensure_all_reports(start: date, end: date) -> list[Path]:
    return [build_weekly_pdf(a, b) for a, b in report_periods(start, end)]
