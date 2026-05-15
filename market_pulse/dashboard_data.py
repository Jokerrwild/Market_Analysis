from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from .bayesian import analyze_snapshot
from .config import load_config, with_crypto_assets
from .db import (
    database_stats,
    db_path as resolve_db_path,
    get_crypto_candles,
    get_latest_market_breadth,
    save_analysis_run,
    upsert_crypto_candles,
)
from .indicators import summarize_series
from .ledger import EPSILON, Ledger, load_ledger, simulate_ledger, summarize_ledger
from .regulatory import context_for_assets, profile_for_asset, support_score_for_asset
from .sources import asset_info, collect_coinbase_market_breadth, collect_snapshot, fetch_coinbase_candles
from .time_utils import resolve_timezone


def candle_to_dict(candle: Any) -> dict[str, Any]:
    return {
        "time": candle.timestamp.isoformat(),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


def current_holding_assets(ledger: Ledger) -> set[str]:
    simulation = simulate_ledger(ledger)
    return {
        asset.upper()
        for asset, position in simulation.positions.items()
        if position.get("quantity", 0) > EPSILON
    }


def trade_posture(analysis: Any, config: dict[str, Any]) -> dict[str, Any]:
    leading = analysis.probabilities[0] if analysis.probabilities else None
    regime = leading.regime if leading else "Unknown"
    probability = leading.probability if leading else 0.0
    confidence = leading.confidence if leading else "Low"
    base_label = config.get("base_asset", "BTC")
    base = analysis.snapshot.crypto.get(base_label) or next(iter(analysis.snapshot.crypto.values()), None)

    if "Bullish" in regime:
        posture = "Long-biased setup"
        trigger = "Confirmation improves if price holds above EMA20 and momentum remains constructive."
        bias = "Constructive"
    elif "Bearish" in regime or "risk-off" in regime:
        posture = "Defensive or short-biased setup"
        trigger = "Confirmation improves if price remains below EMA20/EMA50 while macro risk strengthens."
        bias = "Defensive"
    elif "High-volatility" in regime:
        posture = "Wait-for-resolution setup"
        trigger = "Confirmation improves after a clean break from the current volatility range."
        bias = "Cautious"
    else:
        posture = "Range or no-trade setup"
        trigger = "Confirmation improves only after trend and macro signals align."
        bias = "Neutral"

    return {
        "bias": bias,
        "posture": posture,
        "regime": regime,
        "probability": probability,
        "confidence": confidence,
        "base_asset": base.label if base else base_label,
        "reference_price": base.latest_close if base else None,
        "entry_trigger": trigger,
        "invalidation": analysis.invalidation_conditions[0] if analysis.invalidation_conditions else "No invalidation available.",
        "risk_note": "Decision support only. Use your own risk limits, position sizing, and compliance checks.",
    }


def build_goal_plan(
    ledger_summary: dict[str, Any],
    market_breadth: dict[str, Any],
    lookback_days: int,
    end_time: datetime,
    database_path: str,
    config: dict[str, Any],
    refresh_candidate_candles: bool = False,
) -> dict[str, Any]:
    goal = ledger_summary.get("goal", {})
    initial_capital = float(ledger_summary.get("initial_capital", 0) or 0)
    cash = float(ledger_summary.get("cash", 0) or 0)
    target_profit = goal.get("target_profit") or 0
    days_remaining = goal.get("days_remaining") or ledger_summary.get("target_days") or 0
    daily_profit_needed = (goal.get("profit_remaining") or 0) / days_remaining if days_remaining else None
    suggested_notional = min(max(initial_capital * 0.10, 0), max(cash, 0))

    candidates_by_asset: dict[str, dict[str, Any]] = {}
    for source_name, rows in (
        ("mover", market_breadth.get("top_movers", [])),
        ("gainer", market_breadth.get("top_gainers", [])),
        ("traded", market_breadth.get("top_traded", [])),
    ):
        for row in rows:
            asset = row["asset"]
            current = candidates_by_asset.setdefault(asset, dict(row, sources=[]))
            current["sources"].append(source_name)

    candidates: list[dict[str, Any]] = []
    max_volume = max(
        [item.get("quote_volume_24h", 0) for item in candidates_by_asset.values()] or [1]
    )
    for item in candidates_by_asset.values():
        change = float(item.get("change_24h_pct", 0))
        if change <= 0:
            continue
        summary = summarize_recommended_asset(
            item,
            lookback_days,
            end_time,
            database_path,
            refresh_live=refresh_candidate_candles,
        )
        liquidity_score = (float(item.get("quote_volume_24h", 0)) / max_volume) * 100
        momentum_score = min(change * 8, 100)
        trend_score = max(float(summary.get("trend_score") or 0), 0) * 100
        regulatory_support = support_score_for_asset(config, item["asset"])
        regulatory_score = regulatory_support * 100
        source_bonus = min(len(set(item["sources"])) * 6, 18)
        opportunity_score = min(
            (momentum_score * 0.42)
            + (trend_score * 0.26)
            + (liquidity_score * 0.24)
            + (regulatory_score * 0.08)
            + source_bonus,
            100,
        )
        estimated_profit_if_repeat = suggested_notional * (change / 100) if suggested_notional else 0
        candidates.append(
            {
                "asset": item["asset"],
                "product_id": item["product_id"],
                "price": item["price"],
                "change_24h_pct": change,
                "quote_volume_24h": item["quote_volume_24h"],
                "opportunity_score": opportunity_score,
                "regulatory_support": regulatory_support,
                "regulatory_tags": profile_for_asset(config, item["asset"]).get("tags", []),
                "suggested_notional": suggested_notional,
                "estimated_profit_if_repeat": estimated_profit_if_repeat,
                "summary": summary,
                "source_tags": sorted(set(item["sources"])),
                "trade_frame": "Momentum candidate; require confirmation and use explicit invalidation.",
            }
        )

    candidates.sort(key=lambda item: item["opportunity_score"], reverse=True)
    top_candidates = candidates[:10]
    top_estimated_profit = sum(item["estimated_profit_if_repeat"] for item in top_candidates[:3])

    if not goal.get("active"):
        narrative = "Set capital, target ROI, and target days to activate goal-aware trade planning."
    elif not top_candidates:
        narrative = "No positive-momentum candidates survived the current filter."
    elif daily_profit_needed and top_estimated_profit < daily_profit_needed:
        narrative = (
            "Current high-momentum candidates do not appear sufficient to match the required daily pace "
            "without taking unusually concentrated risk."
        )
    else:
        narrative = (
            "Current high-momentum candidates may be worth closer review, but entries still need confirmation."
        )

    return {
        "active": bool(goal.get("active")),
        "daily_profit_needed": daily_profit_needed,
        "suggested_notional": suggested_notional,
        "target_profit": target_profit,
        "top_three_estimated_profit_if_repeat": top_estimated_profit,
        "narrative": narrative,
        "candidates": top_candidates,
    }


def summarize_recommended_asset(
    item: dict[str, Any],
    lookback_days: int,
    end_time: datetime,
    database_path: str,
    refresh_live: bool = False,
) -> dict[str, Any]:
    fetch_error: Exception | None = None
    if refresh_live:
        try:
            candles = fetch_coinbase_candles(
                product_id=item["product_id"],
                granularity_seconds=3600,
                lookback_days=lookback_days,
                end_time=end_time,
                timeout_seconds=5,
            )
            upsert_crypto_candles(
                database_path,
                asset=str(item["asset"]).upper(),
                product_id=item["product_id"],
                source="coinbase",
                granularity_seconds=3600,
                candles=candles,
                collected_at=end_time,
            )
        except Exception as exc:
            fetch_error = exc

    try:
        candles = get_crypto_candles(
            database_path,
            product_id=item["product_id"],
            granularity_seconds=3600,
            start=end_time - timedelta(days=lookback_days),
            end=end_time,
        )
        if not candles and fetch_error:
            raise fetch_error
        if not candles:
            raise ValueError(f"No stored candles available for {item['asset']}")
        summary = summarize_series(
            item["asset"],
            "coinbase",
            candles,
            periods_per_day=24,
        )
        return {
            "price": summary.latest_close,
            "change_24h_pct": summary.change_24h_pct,
            "change_5d_pct": summary.change_5d_pct,
            "rsi_14": summary.rsi_14,
            "trend_score": summary.trend_score,
            "momentum_score": summary.momentum_score,
            "candle_count": summary.raw.get("candle_count"),
        }
    except Exception as exc:
        return {
            "price": item.get("price"),
            "change_24h_pct": item.get("change_24h_pct"),
            "change_5d_pct": None,
            "rsi_14": None,
            "trend_score": None,
            "momentum_score": None,
            "error": str(exc),
        }


def build_dashboard_payload(
    config_path: str = "config.json",
    ledger_path: str = "ledger.json",
    live_refresh: bool = False,
) -> dict[str, Any]:
    config = load_config(config_path)
    database_path = resolve_db_path(config)
    retention_days = int(config.get("database_retention_days", 5))
    timezone = resolve_timezone(config.get("timezone", "America/New_York"))
    generated_at = datetime.now(timezone)
    ledger = load_ledger(ledger_path)
    holding_assets = current_holding_assets(ledger)
    runtime_config = with_crypto_assets(config, holding_assets)
    configured_assets = {
        str(asset.get("label") or asset.get("product_id") or "").upper()
        for asset in runtime_config.get("crypto_assets", [])
    }
    excluded_assets = holding_assets or configured_assets

    snapshot = collect_snapshot(
        runtime_config,
        generated_at,
        live_refresh=live_refresh,
        timeout_seconds=5,
    )
    analysis = analyze_snapshot(snapshot, runtime_config)
    market_breadth = None if live_refresh else get_latest_market_breadth(database_path)
    if market_breadth is None:
        try:
            market_breadth = collect_coinbase_market_breadth(
                excluded_assets=excluded_assets,
                limit=10,
                database_path=database_path,
                generated_at=generated_at,
                timeout_seconds=5,
            )
        except Exception as exc:
            market_breadth = {
                "excluded_assets": sorted(excluded_assets),
                "excluded_markets": [],
                "price_map": {},
                "top_traded": [],
                "top_movers": [],
                "top_gainers": [],
                "top_losers": [],
                "error": str(exc),
            }
    save_analysis_run(database_path, analysis, market_breadth)

    charts: dict[str, list[dict[str, Any]]] = {}
    chart_errors: list[str] = []
    lookback_days = int(config.get("crypto_lookback_days", 5))
    for asset in runtime_config.get("crypto_assets", []):
        label = asset.get("label") or asset.get("product_id") or "crypto"
        if asset.get("source", "coinbase") != "coinbase":
            continue
        try:
            granularity = int(asset.get("granularity_seconds", 3600))
            candles = get_crypto_candles(
                database_path,
                product_id=asset["product_id"],
                granularity_seconds=granularity,
                start=generated_at - timedelta(days=lookback_days),
                end=generated_at,
            )
            charts[label] = [candle_to_dict(candle) for candle in candles[-120:]]
        except Exception as exc:
            chart_errors.append(f"{label}: {exc}")

    current_prices = {
        label: summary.latest_close
        for label, summary in snapshot.crypto.items()
    }
    for asset in holding_assets:
        if asset in market_breadth.get("price_map", {}):
            current_prices.setdefault(asset, market_breadth["price_map"][asset])
    for item in market_breadth.get("top_traded", []) + market_breadth.get("top_movers", []):
        current_prices.setdefault(item["asset"], item["price"])
    ledger_summary = summarize_ledger(ledger, current_prices)
    goal_plan = build_goal_plan(
        ledger_summary,
        market_breadth,
        lookback_days,
        generated_at,
        database_path,
        runtime_config,
    )
    tradeable_assets = sorted(
        set(current_prices)
        | {item["asset"] for item in market_breadth.get("top_traded", [])}
        | {item["asset"] for item in market_breadth.get("top_movers", [])}
    )
    metadata_assets = (
        set(tradeable_assets)
        | set(configured_assets)
        | set(holding_assets)
        | set(snapshot.crypto)
        | {
            item["asset"]
            for item in market_breadth.get("excluded_markets", [])
            + market_breadth.get("top_gainers", [])
            + market_breadth.get("top_losers", [])
        }
    )
    asset_metadata = dict(market_breadth.get("asset_info", {}))
    for asset in metadata_assets:
        product_id = next(
            (
                str(item.get("product_id"))
                for item in runtime_config.get("crypto_assets", [])
                if str(item.get("label") or "").upper() == asset
            ),
            f"{asset}-USD",
        )
        asset_metadata.setdefault(asset, asset_info(asset, product_id=product_id))
        regulatory_profile = profile_for_asset(runtime_config, asset)
        if regulatory_profile["tags"]:
            asset_metadata[asset]["regulatory_tags"] = regulatory_profile["tags"]
            asset_metadata[asset]["regulatory_support"] = regulatory_profile["support_score"]
            asset_metadata[asset]["regulatory_events"] = regulatory_profile["events"]

    payload = {
        "generated_at": generated_at.isoformat(),
        "data_window": {
            "crypto_lookback_days": lookback_days,
            "database_retention_days": retention_days,
            "crypto_granularity_seconds": [
                int(asset.get("granularity_seconds", 3600))
                for asset in runtime_config.get("crypto_assets", [])
            ],
        },
        "database": {
            **database_stats(database_path),
            "retention_days": retention_days,
            "crypto_analysis_window_days": lookback_days,
        },
        "analysis": asdict(analysis),
        "trade_posture": trade_posture(analysis, runtime_config),
        "charts": charts,
        "prices": current_prices,
        "ledger": ledger_summary,
        "goal_plan": goal_plan,
        "market_breadth": market_breadth,
        "asset_info": asset_metadata,
        "regulatory_context": context_for_assets(runtime_config, metadata_assets),
        "portfolio_holding_assets": sorted(holding_assets),
        "warnings": (
            snapshot.errors
            + chart_errors
            + ledger_summary.get("validation_errors", [])
            + ([market_breadth["error"]] if market_breadth.get("error") else [])
        ),
        "assets": tradeable_assets,
    }
    return payload
