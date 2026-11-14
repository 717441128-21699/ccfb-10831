"""休市日历：节假日 / 市场轮休，确定性生成，仿真站与采集端共用同一份规则。

规则（仿真设定，与现实节假日无关）：
- 全局休市：2026-10-18（周日，模拟中秋调休）、2026-11-01（模拟市场检修）
- 各市场额外轮休日不同，用于检验「补采只补真缺的」
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

GLOBAL_HOLIDAYS = {
    date(2026, 10, 18): "中秋休市",
    date(2026, 11, 1): "全市供电检修",
}

# 每个市场额外的轮休（一周固定一天轮休 + 个别临时休市）
MARKET_WEEKLY_OFF = {
    "m1": 6,  # 周六
    "m2": 0,  # 周日（10-18 已全局休市，不重复计）
    "m3": 2,  # 周二
    "m4": 3,  # 周三（周报市场，出报日照常发布上周数据）
}
MARKET_EXTRA_OFF = {
    "m1": {date(2026, 10, 27): "场地消杀"},
    "m2": {date(2026, 11, 5): "消防演练"},
    "m3": {date(2026, 10, 22): "冷库维护"},
    "m4": {date(2026, 11, 10): "产区道路管制"},
}


def is_closed(market_id: str, day: date) -> bool:
    if day in GLOBAL_HOLIDAYS:
        return True
    if day.weekday() == MARKET_WEEKLY_OFF.get(market_id, -1):
        return True
    if day in MARKET_EXTRA_OFF.get(market_id, {}):
        return True
    return False


def close_reason(market_id: str, day: date) -> str | None:
    if day in GLOBAL_HOLIDAYS:
        return GLOBAL_HOLIDAYS[day]
    if day.weekday() == MARKET_WEEKLY_OFF.get(market_id, -1):
        return "例行轮休"
    extra = MARKET_EXTRA_OFF.get(market_id, {})
    if day in extra:
        return extra[day]
    return None


def expected_open_days(market_id: str, start: date, end: date) -> list[date]:
    """窗口内该市场应开市的日期（周报市场按发布日计算见 m4 模块）。"""
    out, cur = [], start
    while cur <= end:
        if not is_closed(market_id, cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def stable_jitter(seed_text: str, low: float, high: float) -> float:
    """确定性伪随机：同一输入永远得到同一结果，保证真值可复现。"""
    h = hashlib.sha256(seed_text.encode("utf-8")).digest()
    v = int.from_bytes(h[:8], "big") / 2**64
    return low + (high - low) * v
