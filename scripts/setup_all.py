"""一键全流程：启动仿真站 -> 初始化 -> 跑满 30 天 -> 真值比对。

也可分步：
  python -m scripts.init_data
  python -m scripts.run_mocks     # 另开终端保持运行
  python -m scripts.collect run_window
  python -m harness.verify
"""
from __future__ import annotations

from common.config import WINDOW_END, WINDOW_START
from common.truth import generate_all_truth
from collector.db import connect, init_db
from collector.scheduler import register_markets, run_window
from harness.verify import print_report, verify
from mock_sites.m4_pdf.pdf_report import ensure_all_reports
from mock_sites.runner import launch


def main() -> None:
    print("[1/5] 初始化数据库与仿真真值 ...")
    init_db()
    counts = generate_all_truth()
    con = connect()
    register_markets(con)
    ensure_all_reports(WINDOW_START, WINDOW_END)
    print("      真值行数：", counts)

    print("[2/5] 启动 4 个仿真市场 ...")
    procs = launch()
    try:
        print("[3/5] 顺序采集 30 天窗口（字体/Canvas/签名每日实时处理）...")
        results = run_window(con, WINDOW_START, WINDOW_END)
        failed = [r for r in results if r.get("status") == "failed"]
        print(f"      采集任务 {len(results)} 个，失败 {len(failed)} 个")
        for r in failed:
            print("      FAIL:", r)

        print("[4/5] 真值逐条比对 ...")
        con.close()
        summary = verify()
        print_report(summary)

        print("[5/5] 报告已写入 runtime/reports/truth_verification.json")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
