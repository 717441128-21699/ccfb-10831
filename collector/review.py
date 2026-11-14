"""异常价格复核：扣留的记录经人工确认后才能转正或驳回。"""
from __future__ import annotations

import sqlite3

from collector.pipeline import now_iso


def review_anomaly(con: sqlite3.Connection, anomaly_id: int, decision: str,
                   note: str = "") -> dict:
    """decision: approved（采信观察价，转入价格库 verified）/ rejected（驳回）。"""
    row = con.execute("SELECT * FROM anomalies WHERE anomaly_id=?", (anomaly_id,)).fetchone()
    if row is None:
        raise KeyError(anomaly_id)
    if row["status"] != "held":
        raise ValueError(f"异常单 {anomaly_id} 已处理：{row['status']}")

    if decision == "approved":
        con.execute(
            "INSERT INTO prices(market_id,day,product_code,price_type,price,unit,"
            "snapshot_id,run_id,status,collected_at) VALUES(?,?,?,?,?,?,?,?, 'verified', ?) "
            "ON CONFLICT(market_id,day,product_code,price_type) DO UPDATE SET "
            "price=excluded.price,status='verified',collected_at=excluded.collected_at",
            (row["market_id"], row["day"], row["product_code"], row["price_type"],
             row["observed_price"], None, row["snapshot_id"], None, now_iso()),
        )
    con.execute(
        "UPDATE anomalies SET status=?, reviewed_at=?, review_note=? WHERE anomaly_id=?",
        (decision, now_iso(), note, anomaly_id),
    )
    # 同步处理 held 状态的价格行（cross_mismatch 时会有一条 held 价格）
    con.execute(
        "UPDATE prices SET status=? WHERE market_id=? AND day=? AND product_code=? "
        "AND price_type=? AND status='held'",
        ("verified" if decision == "approved" else "rejected",
         row["market_id"], row["day"], row["product_code"], row["price_type"]),
    )
    con.commit()
    return {"anomaly_id": anomaly_id, "decision": decision}
