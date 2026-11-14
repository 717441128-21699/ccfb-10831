"""清空采集端库与快照，保留仿真真值库（mock_truth.db），用于全量重跑。"""
from __future__ import annotations

import shutil

from common.config import COLLECTOR_DB, SNAPSHOT_DIR
from collector.db import init_db
from collector.scheduler import connect, register_markets


def main() -> None:
    if COLLECTOR_DB.exists():
        COLLECTOR_DB.unlink()
    if SNAPSHOT_DIR.exists():
        shutil.rmtree(SNAPSHOT_DIR)
    init_db()
    con = connect()
    register_markets(con)
    con.close()
    print("采集库与快照已重置（真值库保留）")


if __name__ == "__main__":
    main()
