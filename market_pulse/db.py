from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import AnalysisResult, Candle


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS crypto_candles (
    asset TEXT NOT NULL,
    product_id TEXT NOT NULL,
    source TEXT NOT NULL,
    granularity_seconds INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (product_id, granularity_seconds, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_crypto_candles_asset_time
ON crypto_candles(asset, timestamp);

CREATE TABLE IF NOT EXISTS macro_candles (
    label TEXT NOT NULL,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,
    interval_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (symbol, interval_name, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_macro_candles_label_time
ON macro_candles(label, timestamp);

CREATE TABLE IF NOT EXISTS market_breadth_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    excluded_assets_json TEXT NOT NULL,
    price_map_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_breadth_generated_at
ON market_breadth_snapshots(generated_at);

CREATE TABLE IF NOT EXISTS market_breadth_items (
    snapshot_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    rank INTEGER NOT NULL,
    asset TEXT NOT NULL,
    product_id TEXT NOT NULL,
    price REAL NOT NULL,
    change_24h_pct REAL NOT NULL,
    high_24h REAL,
    low_24h REAL,
    volume_24h REAL NOT NULL,
    quote_volume_24h REAL NOT NULL,
    PRIMARY KEY (snapshot_id, category, product_id),
    FOREIGN KEY (snapshot_id) REFERENCES market_breadth_snapshots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    generated_at TEXT PRIMARY KEY,
    leading_thesis TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def db_path(config: dict[str, Any]) -> str:
    return str(config.get("database_path", "market_pulse.db"))


def connect(path: str | Path = "market_pulse.db") -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db(path: str | Path = "market_pulse.db") -> None:
    with closing(connect(path)) as connection:
        connection.executescript(SCHEMA)
        connection.commit()


def candle_row_to_model(row: sqlite3.Row) -> Candle:
    return Candle(
        timestamp=parse_iso(row["timestamp"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )


def upsert_crypto_candles(
    path: str | Path,
    asset: str,
    product_id: str,
    source: str,
    granularity_seconds: int,
    candles: list[Candle],
    collected_at: datetime,
) -> None:
    init_db(path)
    rows = [
        (
            asset,
            product_id,
            source,
            granularity_seconds,
            utc_iso(candle.timestamp),
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            utc_iso(collected_at),
        )
        for candle in candles
    ]
    with closing(connect(path)) as connection:
        connection.executemany(
            """
            INSERT INTO crypto_candles (
                asset, product_id, source, granularity_seconds, timestamp,
                open, high, low, close, volume, collected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, granularity_seconds, timestamp) DO UPDATE SET
                asset=excluded.asset,
                source=excluded.source,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                collected_at=excluded.collected_at
            """,
            rows,
        )
        connection.commit()


def get_crypto_candles(
    path: str | Path,
    product_id: str,
    granularity_seconds: int,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    init_db(path)
    with closing(connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM crypto_candles
            WHERE product_id = ?
              AND granularity_seconds = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (product_id, granularity_seconds, utc_iso(start), utc_iso(end)),
        ).fetchall()
    return [candle_row_to_model(row) for row in rows]


def upsert_macro_candles(
    path: str | Path,
    label: str,
    symbol: str,
    source: str,
    interval_name: str,
    candles: list[Candle],
    collected_at: datetime,
) -> None:
    init_db(path)
    rows = [
        (
            label,
            symbol,
            source,
            interval_name,
            utc_iso(candle.timestamp),
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            utc_iso(collected_at),
        )
        for candle in candles
    ]
    with closing(connect(path)) as connection:
        connection.executemany(
            """
            INSERT INTO macro_candles (
                label, symbol, source, interval_name, timestamp,
                open, high, low, close, volume, collected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval_name, timestamp) DO UPDATE SET
                label=excluded.label,
                source=excluded.source,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                collected_at=excluded.collected_at
            """,
            rows,
        )
        connection.commit()


def get_macro_candles(
    path: str | Path,
    symbol: str,
    interval_name: str,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    init_db(path)
    with closing(connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM macro_candles
            WHERE symbol = ?
              AND interval_name = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (symbol, interval_name, utc_iso(start), utc_iso(end)),
        ).fetchall()
    return [candle_row_to_model(row) for row in rows]


def save_market_breadth(
    path: str | Path,
    generated_at: datetime,
    market_breadth: dict[str, Any],
) -> int:
    init_db(path)
    with closing(connect(path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO market_breadth_snapshots (
                generated_at, excluded_assets_json, price_map_json
            )
            VALUES (?, ?, ?)
            """,
            (
                utc_iso(generated_at),
                json.dumps(market_breadth.get("excluded_assets", [])),
                json.dumps(market_breadth.get("price_map", {})),
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        rows: list[tuple[Any, ...]] = []
        for category in ("excluded_markets", "top_traded", "top_movers", "top_gainers", "top_losers"):
            for rank, item in enumerate(market_breadth.get(category, []), start=1):
                rows.append(
                    (
                        snapshot_id,
                        category,
                        rank,
                        item["asset"],
                        item["product_id"],
                        item["price"],
                        item["change_24h_pct"],
                        item.get("high_24h"),
                        item.get("low_24h"),
                        item["volume_24h"],
                        item["quote_volume_24h"],
                    )
                )
        connection.executemany(
            """
            INSERT INTO market_breadth_items (
                snapshot_id, category, rank, asset, product_id, price,
                change_24h_pct, high_24h, low_24h, volume_24h, quote_volume_24h
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    return snapshot_id


def get_latest_market_breadth(path: str | Path) -> dict[str, Any] | None:
    init_db(path)
    with closing(connect(path)) as connection:
        snapshot = connection.execute(
            """
            SELECT *
            FROM market_breadth_snapshots
            ORDER BY generated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if snapshot is None:
            return None
        rows = connection.execute(
            """
            SELECT *
            FROM market_breadth_items
            WHERE snapshot_id = ?
            ORDER BY category ASC, rank ASC
            """,
            (snapshot["id"],),
        ).fetchall()

    result: dict[str, Any] = {
        "generated_at": snapshot["generated_at"],
        "excluded_assets": json.loads(snapshot["excluded_assets_json"]),
        "price_map": json.loads(snapshot["price_map_json"]),
        "excluded_markets": [],
        "top_traded": [],
        "top_movers": [],
        "top_gainers": [],
        "top_losers": [],
    }
    for row in rows:
        category = row["category"]
        if category not in result:
            result[category] = []
        result[category].append(
            {
                "asset": row["asset"],
                "product_id": row["product_id"],
                "price": row["price"],
                "change_24h_pct": row["change_24h_pct"],
                "high_24h": row["high_24h"],
                "low_24h": row["low_24h"],
                "volume_24h": row["volume_24h"],
                "quote_volume_24h": row["quote_volume_24h"],
            }
        )
    return result


def save_analysis_run(path: str | Path, result: AnalysisResult, market_breadth: dict[str, Any] | None) -> None:
    init_db(path)
    payload = asdict(result)
    if market_breadth is not None:
        payload["market_breadth"] = market_breadth
    with closing(connect(path)) as connection:
        connection.execute(
            """
            INSERT INTO analysis_runs (generated_at, leading_thesis, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(generated_at) DO UPDATE SET
                leading_thesis=excluded.leading_thesis,
                payload_json=excluded.payload_json
            """,
            (
                utc_iso(result.generated_at),
                result.leading_thesis,
                json.dumps(payload, indent=2, default=str),
            ),
        )
        connection.commit()


def prune_old_data(path: str | Path, now: datetime, retention_days: int = 5) -> None:
    init_db(path)
    cutoff = utc_iso(now.astimezone(UTC) - timedelta(days=retention_days))
    macro_cutoff = utc_iso(now.astimezone(UTC) - timedelta(days=max(95, retention_days)))
    with closing(connect(path)) as connection:
        connection.execute("DELETE FROM crypto_candles WHERE timestamp < ?", (cutoff,))
        connection.execute(
            "DELETE FROM market_breadth_snapshots WHERE generated_at < ?",
            (cutoff,),
        )
        connection.execute("DELETE FROM macro_candles WHERE timestamp < ?", (macro_cutoff,))
        connection.execute("DELETE FROM analysis_runs WHERE generated_at < ?", (cutoff,))
        connection.commit()


def database_stats(path: str | Path = "market_pulse.db") -> dict[str, Any]:
    init_db(path)
    with closing(connect(path)) as connection:
        tables = [
            "crypto_candles",
            "macro_candles",
            "market_breadth_snapshots",
            "market_breadth_items",
            "analysis_runs",
        ]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        crypto_range = connection.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM crypto_candles"
        ).fetchone()
        macro_range = connection.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM macro_candles"
        ).fetchone()
    return {
        "path": str(path),
        "counts": counts,
        "crypto_range": {"first": crypto_range[0], "latest": crypto_range[1]},
        "macro_range": {"first": macro_range[0], "latest": macro_range[1]},
    }
