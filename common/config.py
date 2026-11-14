"""全局配置：路径、仿真窗口、市场注册表。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
SNAPSHOT_DIR = RUNTIME / "snapshots"
FONT_DIR = RUNTIME / "fonts"
PDF_DIR = RUNTIME / "pdfs"
COLLECTOR_DB = RUNTIME / "collector.db"
MOCK_DB = RUNTIME / "mock_truth.db"
REPORT_DIR = RUNTIME / "reports"

for _d in (RUNTIME, SNAPSHOT_DIR, FONT_DIR, PDF_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 30 天仿真窗口（含首尾）
WINDOW_START = date(2026, 10, 15)
WINDOW_END = date(2026, 11, 13)


@dataclass(frozen=True)
class MarketSpec:
    market_id: str
    name: str
    trick: str
    base_url: str
    # 该市场使用的价格类型；写库时强校验，防止批发/产地/到岸串价
    price_types: tuple[str, ...]
    # 周报市场：每 7 天一份 PDF
    weekly: bool = False


MARKETS: dict[str, MarketSpec] = {
    "m1": MarketSpec(
        market_id="m1",
        name="鑫丰农贸批发市场",
        trick="daily_rotated_font",
        base_url="http://127.0.0.1:8011",
        price_types=("wholesale",),
    ),
    "m2": MarketSpec(
        market_id="m2",
        name="城南农副产品批发市场",
        trick="canvas_digits",
        base_url="http://127.0.0.1:8012",
        price_types=("wholesale",),
    ),
    "m3": MarketSpec(
        market_id="m3",
        name="临港果品批发市场",
        trick="signed_api",
        base_url="http://127.0.0.1:8013",
        price_types=("wholesale", "landed"),
    ),
    "m4": MarketSpec(
        market_id="m4",
        name="西山产地交易市场",
        trick="weekly_pdf",
        base_url="http://127.0.0.1:8014",
        price_types=("farm",),
        weekly=True,
    ),
}

PRICE_TYPE_LABEL = {
    "wholesale": "批发价",
    "farm": "产地价",
    "landed": "到岸价",
}

# 异常阈值：日内相对上一开市日涨幅 > 3 倍或 < 1/3
SPIKE_HIGH = 3.0
SPIKE_LOW = 1.0 / 3.0
# 跨渠道印证允许偏差（2%）
CROSS_TOLERANCE = 0.02
