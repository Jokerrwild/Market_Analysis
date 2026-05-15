from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .bayesian import analyze_snapshot
from .config import load_config, with_crypto_assets
from .db import db_path as resolve_db_path, save_analysis_run
from .ledger import EPSILON, load_ledger, simulate_ledger
from .reports import write_reports
from .sources import collect_coinbase_market_breadth, collect_snapshot
from .time_utils import resolve_timezone


def run_once(config_path: str = "config.json", notes: str | None = None) -> tuple[Path, Path, str]:
    config = load_config(config_path)
    database_path = resolve_db_path(config)
    timezone = resolve_timezone(config.get("timezone", "America/New_York"))
    generated_at = datetime.now(timezone)
    ledger = load_ledger("ledger.json")
    holding_assets = {
        asset.upper()
        for asset, position in simulate_ledger(ledger).positions.items()
        if position.get("quantity", 0) > EPSILON
    }
    runtime_config = with_crypto_assets(config, holding_assets)
    snapshot = collect_snapshot(runtime_config, generated_at)
    analysis = analyze_snapshot(snapshot, runtime_config, notes=notes)
    configured_assets = {
        str(asset.get("label") or asset.get("product_id") or "").upper()
        for asset in runtime_config.get("crypto_assets", [])
    }
    try:
        market_breadth = collect_coinbase_market_breadth(
            holding_assets or configured_assets,
            limit=10,
            database_path=database_path,
            generated_at=generated_at,
        )
    except Exception as exc:
        market_breadth = {"excluded_assets": sorted(holding_assets or configured_assets), "top_movers": [], "top_traded": [], "error": str(exc)}
    save_analysis_run(database_path, analysis, market_breadth)
    markdown_path, json_path = write_reports(
        analysis,
        config.get("report_dir", "reports"),
        market_breadth=market_breadth,
    )
    return markdown_path, json_path, analysis.leading_thesis
