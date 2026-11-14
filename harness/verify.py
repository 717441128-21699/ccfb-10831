"""30 天闭环验证：采集结果与仿真真值逐条比对。

校验维度：
1. 覆盖率：每个市场每个开市日每个 (商品, 价格类型) 都有结果（verified 或 held）；
2. 准确率：verified 价格与真值逐条相等（float 容差 0.001）；
3. 异常捕获：真值标记 is_spike=1 的记录必须产生扣留异常；
4. 休市规则：休市日不得出现价格、也不得被记为缺数；
5. 快照可追溯：每条价格都带有效 snapshot_id，文件真实存在；
6. 跨渠道印证：m2 的 mismatch 注入必须产生 cross_mismatch 异常；
7. 价格类型隔离：批发/产地/到岸价严格分列。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from common.config import (
    COLLECTOR_DB, MARKETS, MOCK_DB, REPORT_DIR, WINDOW_END, WINDOW_START,
)
from common.calendar_def import close_reason
from common.truth import cross_channel_mismatch


@dataclass
class MarketReport:
    market_id: str
    expected_rows: int = 0
    verified_rows: int = 0
    held_rows: int = 0
    value_mismatches: list[dict] = field(default_factory=list)
    missing_rows: list[dict] = field(default_factory=list)
    spike_caught: int = 0
    spike_total: int = 0
    cross_caught: int = 0
    cross_total: int = 0
    holiday_violations: list[dict] = field(default_factory=list)
    snapshot_broken: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.value_mismatches or self.missing_rows or self.holiday_violations
            or self.snapshot_broken or self.spike_total != self.spike_caught
            or self.cross_total != self.cross_caught
        )


def _truth(con: sqlite3.Connection, market_id: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM truth_prices WHERE market_id=? ORDER BY day,product_code,price_type",
        (market_id,),
    ).fetchall()


def verify() -> dict:
    truth_con = sqlite3.connect(MOCK_DB)
    truth_con.row_factory = sqlite3.Row
    col_con = sqlite3.connect(COLLECTOR_DB)
    col_con.row_factory = sqlite3.Row

    reports: dict[str, MarketReport] = {}
    for mid, spec in MARKETS.items():
        rep = MarketReport(mid)
        truth_rows = _truth(truth_con, mid)
        rep.expected_rows = len(truth_rows)

        for t in truth_rows:
            key = (t["day"], t["product_code"], t["price_type"])
            p = col_con.execute(
                "SELECT * FROM prices WHERE market_id=? AND day=? AND product_code=? "
                "AND price_type=?",
                (mid, *key),
            ).fetchone()
            if p is None:
                rep.missing_rows.append({"day": t["day"], "product": t["product_code"],
                                         "type": t["price_type"]})
                if t["is_spike"]:
                    rep.spike_total += 1
                continue

            # 快照可追溯
            snap = col_con.execute(
                "SELECT file_path,payload_ref FROM snapshots WHERE snapshot_id=?",
                (p["snapshot_id"],),
            ).fetchone() if p["snapshot_id"] else None
            if snap is None or not (
                (snap["file_path"] and Path(snap["file_path"]).exists())
                or (snap["payload_ref"] and Path(snap["payload_ref"]).exists())
            ):
                rep.snapshot_broken.append({"day": t["day"], "product": t["product_code"],
                                            "snapshot_id": p["snapshot_id"]})

            if t["is_spike"]:
                rep.spike_total += 1
                anom = col_con.execute(
                    "SELECT 1 FROM anomalies WHERE market_id=? AND day=? AND product_code=? "
                    "AND price_type=? AND reason IN ('spike_high','spike_low')",
                    (mid, *key),
                ).fetchone()
                if anom:
                    rep.spike_caught += 1
                if p["status"] == "verified":
                    # spike 记录在复核前不应是 verified
                    rep.value_mismatches.append(
                        {"day": t["day"], "product": t["product_code"],
                         "issue": "spike not held", "truth": t["price"], "got": p["price"]}
                    )
                if p["status"] == "held":
                    rep.held_rows += 1
                continue

            if p["status"] == "held":
                rep.held_rows += 1
                # 扣留必须有对应异常单（spike 或跨渠道冲突），否则属异常扣留
                anom_any = col_con.execute(
                    "SELECT 1 FROM anomalies WHERE market_id=? AND day=? AND product_code=? "
                    "AND price_type=? AND status='held'",
                    (mid, *key),
                ).fetchone()
                if not anom_any:
                    rep.value_mismatches.append(
                        {"day": t["day"], "product": t["product_code"],
                         "issue": "held without anomaly", "truth": t["price"], "got": p["price"]}
                    )
                continue

            rep.verified_rows += 1
            if abs(float(p["price"]) - float(t["price"])) > 0.001:
                rep.value_mismatches.append(
                    {"day": t["day"], "product": t["product_code"], "type": t["price_type"],
                     "issue": "value", "truth": t["price"], "got": p["price"]}
                )

        # m2 跨渠道印证校验
        if mid == "m2":
            for t in truth_rows:
                d = date.fromisoformat(t["day"])
                if cross_channel_mismatch("m2", t["product_code"], d):
                    rep.cross_total += 1
                    hit = col_con.execute(
                        "SELECT 1 FROM anomalies WHERE market_id=? AND day=? AND product_code=? "
                        "AND reason='cross_mismatch' AND status='held'",
                        (mid, t["day"], t["product_code"]),
                    ).fetchone()
                    if hit:
                        rep.cross_caught += 1

        # 休市日校验：无价格、日历为 closed
        cur = WINDOW_START
        from datetime import timedelta
        while cur <= WINDOW_END:
            if close_reason(mid, cur):
                bad_prices = col_con.execute(
                    "SELECT COUNT(*) c FROM prices WHERE market_id=? AND day=?",
                    (mid, cur.isoformat()),
                ).fetchone()["c"]
                cal = col_con.execute(
                    "SELECT collect_status FROM collection_calendar WHERE market_id=? AND day=?",
                    (mid, cur.isoformat()),
                ).fetchone()
                if bad_prices or not cal or cal["collect_status"] != "closed":
                    rep.holiday_violations.append(
                        {"day": cur.isoformat(), "prices": bad_prices,
                         "calendar": cal["collect_status"] if cal else None}
                    )
            cur += timedelta(days=1)

        # 价格类型隔离校验：该市场出现了不允许的类型即为串价
        allowed = ",".join("?" for _ in spec.price_types)
        bad_types = col_con.execute(
            f"SELECT DISTINCT price_type FROM prices WHERE market_id=? "
            f"AND price_type NOT IN ({allowed})",
            (mid, *spec.price_types),
        ).fetchall()
        for b in bad_types:
            rep.holiday_violations.append({"issue": "price_type_leak", "type": b["price_type"]})

        reports[mid] = rep

    truth_con.close()
    col_con.close()
    return _summarize(reports)


def _summarize(reports: dict[str, MarketReport]) -> dict:
    summary = {"window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()], "markets": {}}
    all_ok = True
    for mid, rep in reports.items():
        all_ok &= rep.ok
        summary["markets"][mid] = {
            "name": MARKETS[mid].name,
            "expected_rows": rep.expected_rows,
            "verified_rows": rep.verified_rows,
            "held_rows": rep.held_rows,
            "value_mismatches": rep.value_mismatches,
            "missing_rows": rep.missing_rows,
            "spike": {"caught": rep.spike_caught, "total": rep.spike_total},
            "cross_mismatch": {"caught": rep.cross_caught, "total": rep.cross_total},
            "holiday_violations": rep.holiday_violations,
            "snapshot_broken": rep.snapshot_broken,
            "pass": rep.ok,
        }
    summary["all_pass"] = all_ok
    out = REPORT_DIR / "truth_verification.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def print_report(summary: dict) -> None:
    print(f"\n===== 30 天真值比对报告（{summary['window'][0]} ~ {summary['window'][1]}）=====")
    for mid, m in summary["markets"].items():
        print(f"\n[{mid}] {m['name']}  {'PASS' if m['pass'] else 'FAIL'}")
        print(f"  期望行数 {m['expected_rows']} | 已验证 {m['verified_rows']} | "
              f"扣留 {m['held_rows']} | 缺数 {len(m['missing_rows'])} | "
              f"数值不符 {len(m['value_mismatches'])}")
        print(f"  异常波动捕获 {m['spike']['caught']}/{m['spike']['total']} | "
              f"跨渠道冲突捕获 {m['cross_mismatch']['caught']}/{m['cross_mismatch']['total']} | "
              f"休市违规 {len(m['holiday_violations'])} | 快照断链 {len(m['snapshot_broken'])}")
        for key in ("missing_rows", "value_mismatches", "holiday_violations", "snapshot_broken"):
            for item in m[key][:5]:
                print(f"    ! {key}: {item}")
    print("\n总判定：", "全部通过 ✅" if summary["all_pass"] else "存在失败项 ❌")


if __name__ == "__main__":
    print_report(verify())
