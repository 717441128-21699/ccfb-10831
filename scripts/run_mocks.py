"""启动 4 个仿真市场站点（后台进程）。"""
from __future__ import annotations

import time

from mock_sites.runner import APPS, launch


def main() -> None:
    procs = launch()
    print("仿真站全部就绪：")
    for (mod, port), p in zip(APPS, procs):
        print(f"  http://127.0.0.1:{port}  pid={p.pid}  ({mod})")
    print("按 Ctrl+C 停止。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
