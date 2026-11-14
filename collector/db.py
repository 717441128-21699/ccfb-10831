"""采集端 SQLite 库结构与基础读写。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from common.config import COLLECTOR_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets(
  market_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  trick TEXT NOT NULL,
  base_url TEXT NOT NULL,
  price_types TEXT NOT NULL,
  enabled INTEGER DEFAULT 1
);

-- 采集日历：每个市场每天的应采状态（open/closed）、实际采集状态与缺数标记
CREATE TABLE IF NOT EXISTS collection_calendar(
  market_id TEXT NOT NULL,
  day TEXT NOT NULL,
  expected TEXT NOT NULL,              -- open / closed
  close_reason TEXT,
  collect_status TEXT DEFAULT 'pending', -- pending/done/missing/closed
  run_id INTEGER,
  expected_count INTEGER DEFAULT 0,
  collected_count INTEGER DEFAULT 0,
  PRIMARY KEY(market_id, day)
);

CREATE TABLE IF NOT EXISTS collection_runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id TEXT NOT NULL,
  day TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT,                         -- ok / partial / failed
  message TEXT,
  rows_collected INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snapshots(
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id TEXT NOT NULL,
  day TEXT NOT NULL,
  kind TEXT NOT NULL,                  -- html / png / json / pdf / font
  file_path TEXT,
  payload_ref TEXT,                    -- 原始报文（JSON 等）在 runtime 下的路径
  url TEXT,
  created_at TEXT NOT NULL,
  run_id INTEGER
);

-- 原始报文留存（JSON/解析中间结果），与截图一起构成可追溯证据链
CREATE TABLE IF NOT EXISTS raw_payloads(
  payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id TEXT, day TEXT, content_type TEXT,
  body TEXT, created_at TEXT
);

-- 字体映射每日重解的结果（仅存解码后结果，不依赖仿真站私有映射）
CREATE TABLE IF NOT EXISTS font_mappings(
  market_id TEXT, day TEXT, pua_char TEXT, real_char TEXT,
  method TEXT, PRIMARY KEY(market_id, day, pua_char)
);

-- 价格库：三类价格分列 + CHECK 强约束，防止批发/产地/到岸串价
CREATE TABLE IF NOT EXISTS prices(
  price_id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id TEXT NOT NULL,
  day TEXT NOT NULL,
  product_code TEXT NOT NULL,
  price_type TEXT NOT NULL CHECK(price_type IN ('wholesale','farm','landed')),
  price REAL NOT NULL,
  unit TEXT,
  snapshot_id INTEGER,
  run_id INTEGER,
  status TEXT DEFAULT 'verified',      -- verified / held
  collected_at TEXT NOT NULL,
  UNIQUE(market_id, day, product_code, price_type),
  FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
);

-- 异常价格：扣留待复核，不直接进 verified 价格库
CREATE TABLE IF NOT EXISTS anomalies(
  anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id TEXT NOT NULL,
  day TEXT NOT NULL,
  product_code TEXT NOT NULL,
  price_type TEXT NOT NULL,
  observed_price REAL,
  reference_price REAL,
  reason TEXT NOT NULL,                -- spike_high / spike_low / cross_mismatch
  detail TEXT,
  snapshot_id INTEGER,
  status TEXT DEFAULT 'held',          -- held / approved / rejected
  reviewed_at TEXT,
  review_note TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_day ON prices(market_id, day);
CREATE INDEX IF NOT EXISTS idx_anom_status ON anomalies(status);
"""


def connect(db_path: Path = COLLECTOR_DB) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path: Path = COLLECTOR_DB) -> None:
    con = connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
