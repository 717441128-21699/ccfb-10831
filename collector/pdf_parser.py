"""周报 PDF 解析（对应需求 4：跨页表格拆成明细）。

用 pdfplumber 逐页抽表：
- 每页都会重复表头，解析时跳过所有表头行；
- 休市行价格列为「—」，按休市记录跳过（不生成价格）；
- 同一商品跨页出现时按 (日期, 商品) 归并，天然还原为逐行明细；
- 只接受该市场允许的价格类型（m4=产地价），防止串价。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber

HEADER_CELLS = {"日期", "商品编码", "商品名称", "单位", "产地价", "备注"}


@dataclass
class PdfRow:
    day: str
    product_code: str
    product_name: str
    unit: str
    price: float
    note: str


def parse_weekly_pdf(pdf_path: Path) -> list[PdfRow]:
    rows: list[PdfRow] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [(c or "").strip() for c in raw]
                    if len(cells) < 6:
                        continue
                    # 跳过续页/首页表头
                    if cells[0] == "日期" or set(cells) >= {"商品编码", "产地价"}:
                        continue
                    day, code, name, unit, price_text, note = cells[:6]
                    if not day or not code:
                        continue
                    if price_text in ("—", "-", ""):
                        # 休市行：无价格，仅保留备注语义，不产生明细
                        continue
                    try:
                        price = float(price_text)
                    except ValueError:
                        continue
                    rows.append(PdfRow(day, code, name, unit, price, note))
    # 去重（极端情况下同一行在两页边界重复）
    dedup = {(r.day, r.product_code): r for r in rows}
    return [dedup[k] for k in sorted(dedup)]


def parse_all(pdf_dir: Path, market_id: str = "m4") -> list[PdfRow]:
    out: list[PdfRow] = []
    for pdf in sorted(pdf_dir.glob(f"{market_id}_weekly_*.pdf")):
        out.extend(parse_weekly_pdf(pdf))
    return out
