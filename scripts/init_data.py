"""初始化：建采集库 + 生成 30 天仿真真值 + 预生成 m4 周报 PDF。"""
from __future__ import annotations

from common.config import WINDOW_END, WINDOW_START
from common.truth import generate_all_truth
from collector.db import init_db
from collector.scheduler import register_markets, connect
from mock_sites.m4_pdf.pdf_report import ensure_all_reports


def main() -> None:
    init_db()
    counts = generate_all_truth()
    con = connect()
    register_markets(con)
    con.close()
    pdfs = ensure_all_reports(WINDOW_START, WINDOW_END)
    print("真值生成完成：", counts)
    print(f"m4 周报 PDF {len(pdfs)} 份已生成")
    print(f"仿真窗口：{WINDOW_START} ~ {WINDOW_END}")


if __name__ == "__main__":
    main()
