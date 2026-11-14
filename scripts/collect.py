"""采集 CLI。

用法：
  python -m scripts.collect run_window           # 顺序跑完整 30 天窗口
  python -m scripts.collect day m1 2026-10-20    # 单市场单日采集
  python -m scripts.collect backfill m1          # 只补真缺的开市日
  python -m scripts.collect missing m1           # 查看缺数日（休市日不算）
"""
from __future__ import annotations

import sys
from datetime import date

from collector.db import connect
from collector.scheduler import backfill, collect_day, find_missing_days, run_window
from common.config import WINDOW_END, WINDOW_START


def main() -> None:
    con = connect()
    args = sys.argv[1:]
    cmd = args[0] if args else "run_window"
    if cmd == "run_window":
        results = run_window(con, WINDOW_START, WINDOW_END)
        for r in results:
            print(r)
    elif cmd == "day":
        market_id, day_str = args[1], args[2]
        print(collect_day(market_id, date.fromisoformat(day_str), con))
    elif cmd == "backfill":
        market_id = args[1]
        for r in backfill(con, market_id, WINDOW_START, WINDOW_END):
            print("补采：", r)
    elif cmd == "missing":
        market_id = args[1]
        missing = find_missing_days(con, market_id, WINDOW_START, WINDOW_END)
        print(f"{market_id} 真缺数日（已排除休市）：", [d.isoformat() for d in missing])
    else:
        raise SystemExit(f"未知命令 {cmd}")
    con.close()


if __name__ == "__main__":
    main()
