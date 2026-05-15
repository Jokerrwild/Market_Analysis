from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, quote

from .db import (
    db_path as resolve_db_path,
    get_crypto_candles,
    get_macro_candles,
    init_db,
    prune_old_data,
    save_market_breadth,
    upsert_crypto_candles,
    upsert_macro_candles,
)
from .http import FetchError, fetch_json
from .indicators import summarize_series
from .models import Candle, MarketSnapshot, SeriesSummary


ASSET_INFO_OVERRIDES: dict[str, dict[str, str]] = {
    "BTC": {
        "name": "Bitcoin",
        "description": "The original decentralized cryptocurrency and the largest crypto asset by market capitalization.",
    },
    "ETH": {
        "name": "Ethereum",
        "description": "A smart-contract blockchain used for decentralized applications, tokens, and on-chain settlement.",
    },
    "SOL": {
        "name": "Solana",
        "description": "A high-throughput smart-contract blockchain known for fast, low-cost transactions.",
    },
    "XRP": {
        "name": "XRP",
        "description": "The native asset of the XRP Ledger, commonly used for payments and liquidity transfer.",
    },
    "DOGE": {
        "name": "Dogecoin",
        "description": "A community-driven proof-of-work cryptocurrency that began as a meme coin.",
    },
    "BILL": {
        "name": "Billions Network",
        "description": "A recently listed Coinbase token traded under the BILL ticker.",
    },
    "USDC": {
        "name": "USD Coin",
        "description": "A U.S. dollar-pegged stablecoin issued by Circle.",
    },
    "ADA": {
        "name": "Cardano",
        "description": "A proof-of-stake blockchain focused on smart contracts and formal research-driven development.",
    },
    "AVAX": {
        "name": "Avalanche",
        "description": "A smart-contract platform designed around fast finality and interoperable subnets.",
    },
    "LINK": {
        "name": "Chainlink",
        "description": "A decentralized oracle network used to connect smart contracts with external data.",
    },
    "LTC": {
        "name": "Litecoin",
        "description": "A long-running proof-of-work cryptocurrency designed for lower-cost peer-to-peer payments.",
    },
}


def asset_info(
    asset: str,
    product_id: str | None = None,
    quote_currency: str = "USD",
    display_name: str | None = None,
    status: str | None = None,
) -> dict[str, str]:
    symbol = asset.upper().strip()
    product = product_id or f"{symbol}-{quote_currency.upper()}"
    override = ASSET_INFO_OVERRIDES.get(symbol, {})
    name = override.get("name") or display_name or symbol
    description = override.get("description") or (
        f"{symbol} is listed on Coinbase as {product} against {quote_currency.upper()}."
    )
    return {
        "symbol": symbol,
        "name": name,
        "description": description,
        "product_id": product,
        "quote_currency": quote_currency.upper(),
        "display_name": display_name or product,
        "status": status or "",
    }


def asset_info_from_product(product: dict[str, Any]) -> dict[str, str]:
    return asset_info(
        asset=str(product.get("base_currency", "")),
        product_id=str(product.get("id", "")),
        quote_currency=str(product.get("quote_currency", "USD")),
        display_name=str(product.get("display_name") or product.get("id") or ""),
        status=str(product.get("status") or ""),
    )


def fetch_coinbase_candles(
    product_id: str,
    granularity_seconds: int,
    lookback_days: int | None = None,
    end_time: datetime | None = None,
    timeout_seconds: int = 8,
) -> list[Candle]:
    product = quote(product_id, safe="")
    query: dict[str, str | int] = {"granularity": granularity_seconds}
    if lookback_days:
        end = (end_time or datetime.now(UTC)).astimezone(UTC)
        start = end - timedelta(days=lookback_days)
        query["start"] = start.isoformat().replace("+00:00", "Z")
        query["end"] = end.isoformat().replace("+00:00", "Z")
    url = (
        "https://api.exchange.coinbase.com/products/"
        f"{product}/candles?{urlencode(query)}"
    )
    data = fetch_json(url, timeout_seconds=timeout_seconds)
    if not isinstance(data, list):
        raise FetchError(f"Unexpected Coinbase response for {product_id}")

    candles: list[Candle] = []
    for item in data:
        if not isinstance(item, list) or len(item) < 6:
            continue
        timestamp, low, high, open_, close, volume = item[:6]
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(timestamp), tz=UTC),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    candles.sort(key=lambda candle: candle.timestamp)
    return candles


def fetch_coinbase_products(timeout_seconds: int = 8) -> list[dict[str, Any]]:
    data = fetch_json("https://api.exchange.coinbase.com/products", timeout_seconds=timeout_seconds)
    if not isinstance(data, list):
        raise FetchError("Unexpected Coinbase products response")
    return [item for item in data if isinstance(item, dict)]


def fetch_coinbase_all_stats(timeout_seconds: int = 8) -> dict[str, Any]:
    data = fetch_json("https://api.exchange.coinbase.com/products/stats", timeout_seconds=timeout_seconds)
    if not isinstance(data, dict):
        raise FetchError("Unexpected Coinbase stats response")
    return data


def collect_coinbase_market_breadth(
    excluded_assets: set[str],
    limit: int = 10,
    database_path: str | None = None,
    generated_at: datetime | None = None,
    timeout_seconds: int = 8,
) -> dict[str, Any]:
    products = fetch_coinbase_products(timeout_seconds=timeout_seconds)
    stats = fetch_coinbase_all_stats(timeout_seconds=timeout_seconds)
    excluded = {asset.upper() for asset in excluded_assets}
    candidates: list[dict[str, Any]] = []
    excluded_markets: list[dict[str, Any]] = []
    price_map: dict[str, float] = {}
    asset_info_map: dict[str, dict[str, str]] = {}

    for product in products:
        product_id = str(product.get("id", ""))
        base = str(product.get("base_currency", "")).upper()
        quote_currency = str(product.get("quote_currency", "")).upper()
        if quote_currency != "USD" or not base:
            continue
        info = asset_info_from_product(product)
        asset_info_map[base] = info
        if product.get("status") != "online" or product.get("trading_disabled"):
            continue
        stat_block = stats.get(product_id, {})
        day_stats = stat_block.get("stats_24hour", {}) if isinstance(stat_block, dict) else {}
        try:
            open_price = float(day_stats.get("open", 0))
            last_price = float(day_stats.get("last", 0))
            high = float(day_stats.get("high", 0))
            low = float(day_stats.get("low", 0))
            volume = float(day_stats.get("volume", 0))
        except (TypeError, ValueError):
            continue
        if open_price <= 0 or last_price <= 0 or volume <= 0:
            continue
        change_pct = ((last_price - open_price) / open_price) * 100
        quote_volume = volume * last_price
        row = {
            "asset": base,
            "name": info["name"],
            "product_id": product_id,
            "price": last_price,
            "change_24h_pct": change_pct,
            "high_24h": high,
            "low_24h": low,
            "volume_24h": volume,
            "quote_volume_24h": quote_volume,
        }
        price_map[base] = last_price
        if base in excluded:
            excluded_markets.append(row)
        else:
            candidates.append(row)

    top_traded = sorted(candidates, key=lambda item: item["quote_volume_24h"], reverse=True)[:limit]
    top_movers = sorted(candidates, key=lambda item: abs(item["change_24h_pct"]), reverse=True)[:limit]
    top_gainers = sorted(candidates, key=lambda item: item["change_24h_pct"], reverse=True)[:limit]
    top_losers = sorted(candidates, key=lambda item: item["change_24h_pct"])[:limit]
    result = {
        "excluded_assets": sorted(excluded),
        "excluded_markets": sorted(excluded_markets, key=lambda item: item["quote_volume_24h"], reverse=True),
        "price_map": price_map,
        "asset_info": asset_info_map,
        "top_traded": top_traded,
        "top_movers": top_movers,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
    }
    if database_path:
        save_market_breadth(database_path, generated_at or datetime.now(UTC), result)
    return result


def fetch_yahoo_chart(
    symbol: str,
    range_: str,
    interval: str,
    timeout_seconds: int = 8,
) -> list[Candle]:
    encoded = quote(symbol, safe="")
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{encoded}?range={quote(range_, safe='')}&interval={quote(interval, safe='')}"
    )
    data = fetch_json(url, timeout_seconds=timeout_seconds)
    if not isinstance(data, dict):
        raise FetchError(f"Unexpected Yahoo response for {symbol}")

    chart = data.get("chart", {})
    error = chart.get("error")
    if error:
        description = error.get("description", "unknown error")
        raise FetchError(f"Yahoo error for {symbol}: {description}")

    results = chart.get("result") or []
    if not results:
        raise FetchError(f"No Yahoo chart data for {symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote_data.get("open") or []
    highs = quote_data.get("high") or []
    lows = quote_data.get("low") or []
    closes = quote_data.get("close") or []
    volumes = quote_data.get("volume") or []

    candles: list[Candle] = []
    for index, timestamp in enumerate(timestamps):
        try:
            open_ = opens[index]
            high = highs[index]
            low = lows[index]
            close = closes[index]
            volume = volumes[index] if index < len(volumes) else 0
        except IndexError:
            continue
        if None in (open_, high, low, close):
            continue
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(timestamp), tz=UTC),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume or 0),
            )
        )
    candles.sort(key=lambda candle: candle.timestamp)
    return candles


def collect_snapshot(
    config: dict[str, Any],
    generated_at: datetime,
    live_refresh: bool = True,
    timeout_seconds: int = 8,
) -> MarketSnapshot:
    crypto: dict[str, SeriesSummary] = {}
    macro: dict[str, SeriesSummary] = {}
    errors: list[str] = []
    database_path = resolve_db_path(config)
    retention_days = int(config.get("database_retention_days", 5))
    lookback_days = int(config.get("crypto_lookback_days", 5))
    init_db(database_path)
    prune_old_data(database_path, generated_at, retention_days=retention_days)

    for asset in config.get("crypto_assets", []):
        label = asset.get("label") or asset.get("product_id") or "crypto"
        source = asset.get("source", "coinbase")
        product_id = asset.get("product_id")
        granularity = int(asset.get("granularity_seconds", 3600))
        start_time = generated_at - timedelta(days=lookback_days)
        fetch_error: Exception | None = None
        if live_refresh:
            try:
                if source != "coinbase":
                    raise FetchError(f"Unsupported crypto source: {source}")
                candles = fetch_coinbase_candles(
                    product_id=product_id,
                    granularity_seconds=granularity,
                    lookback_days=lookback_days,
                    end_time=generated_at,
                    timeout_seconds=timeout_seconds,
                )
                upsert_crypto_candles(
                    database_path,
                    asset=str(label).upper(),
                    product_id=str(product_id),
                    source=source,
                    granularity_seconds=granularity,
                    candles=candles,
                    collected_at=generated_at,
                )
            except Exception as exc:
                fetch_error = exc

        try:
            stored_candles = get_crypto_candles(
                database_path,
                product_id=str(product_id),
                granularity_seconds=granularity,
                start=start_time,
                end=generated_at,
            )
            if not stored_candles and fetch_error:
                raise fetch_error
            if not stored_candles:
                raise FetchError(f"No stored candles available for {label}")
            periods_per_day = max(1, round(86400 / granularity))
            crypto[label] = summarize_series(
                label,
                source,
                stored_candles,
                periods_per_day=periods_per_day,
            )
            if fetch_error:
                errors.append(
                    f"{label}: live fetch failed ({fetch_error}); using {len(stored_candles)} stored candles."
                )
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    for asset in config.get("macro_assets", []):
        label = asset.get("label") or asset.get("symbol") or "macro"
        source = asset.get("source", "yahoo")
        symbol = asset.get("symbol")
        interval_name = asset.get("interval", "1d")
        macro_start = generated_at - timedelta(days=max(95, retention_days))
        fetch_error = None
        if live_refresh:
            try:
                if source != "yahoo":
                    raise FetchError(f"Unsupported macro source: {source}")
                candles = fetch_yahoo_chart(
                    symbol=symbol,
                    range_=asset.get("range", "3mo"),
                    interval=interval_name,
                    timeout_seconds=timeout_seconds,
                )
                upsert_macro_candles(
                    database_path,
                    label=str(label),
                    symbol=str(symbol),
                    source=source,
                    interval_name=interval_name,
                    candles=candles,
                    collected_at=generated_at,
                )
            except Exception as exc:
                fetch_error = exc

        try:
            stored_candles = get_macro_candles(
                database_path,
                symbol=str(symbol),
                interval_name=interval_name,
                start=macro_start,
                end=generated_at,
            )
            if not stored_candles and fetch_error:
                raise fetch_error
            if not stored_candles:
                raise FetchError(f"No stored macro candles available for {label}")
            macro[label] = summarize_series(label, source, stored_candles, periods_per_day=1)
            if fetch_error:
                errors.append(
                    f"{label}: live fetch failed ({fetch_error}); using {len(stored_candles)} stored candles."
                )
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    return MarketSnapshot(
        generated_at=generated_at,
        crypto=crypto,
        macro=macro,
        errors=errors,
    )
