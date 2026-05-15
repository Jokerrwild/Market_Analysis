from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "timezone": "America/New_York",
    "report_dir": "reports",
    "database_path": "market_pulse.db",
    "database_retention_days": 5,
    "base_asset": "BTC",
    "crypto_lookback_days": 5,
    "crypto_assets": [
        {
            "label": "BTC",
            "source": "coinbase",
            "product_id": "BTC-USD",
            "granularity_seconds": 3600,
        },
        {
            "label": "ETH",
            "source": "coinbase",
            "product_id": "ETH-USD",
            "granularity_seconds": 3600,
        },
    ],
    "macro_assets": [
        {
            "label": "SPY",
            "source": "yahoo",
            "symbol": "SPY",
            "range": "3mo",
            "interval": "1d",
            "interpretation": "risk_on_equity",
        },
        {
            "label": "QQQ",
            "source": "yahoo",
            "symbol": "QQQ",
            "range": "3mo",
            "interval": "1d",
            "interpretation": "risk_on_equity",
        },
        {
            "label": "DXY",
            "source": "yahoo",
            "symbol": "DX-Y.NYB",
            "range": "3mo",
            "interval": "1d",
            "interpretation": "risk_off_dollar",
        },
        {
            "label": "10Y Yield",
            "source": "yahoo",
            "symbol": "^TNX",
            "range": "3mo",
            "interval": "1d",
            "interpretation": "risk_off_yield",
        },
    ],
    "regime_priors": {
        "Bullish accumulation": 0.14,
        "Bullish continuation": 0.16,
        "Neutral consolidation": 0.22,
        "Bearish distribution": 0.16,
        "Bearish continuation": 0.14,
        "High-volatility transition": 0.10,
        "Macro-driven risk-off": 0.08,
    },
    "regulatory_context": {
        "enabled": True,
        "events": [
            {
                "id": "sec-cftc-2026-crypto-asset-interpretation",
                "date": "2026-03-17",
                "title": "SEC/CFTC crypto asset interpretation",
                "classification": "digital_commodity",
                "impact_score": 0.18,
                "affected_assets": [
                    "APT",
                    "AVAX",
                    "BTC",
                    "BCH",
                    "ADA",
                    "LINK",
                    "DOGE",
                    "ETH",
                    "HBAR",
                    "LTC",
                    "DOT",
                    "SHIB",
                    "SOL",
                    "XLM",
                    "XTZ",
                    "XRP",
                ],
                "summary": (
                    "The SEC issued an interpretation clarifying crypto asset treatment under federal "
                    "securities laws, and the CFTC joined the interpretation for Commodity Exchange Act "
                    "administration. The event reduces U.S. regulatory ambiguity for listed digital commodities."
                ),
                "source_urls": [
                    "https://www.sec.gov/newsroom/press-releases/2026-30-sec-clarifies-application-federal-securities-laws-crypto-assets",
                    "https://www.sec.gov/rules-regulations/2026/03/s7-2026-09",
                    "https://www.cftc.gov/LawRegulation/FederalRegister/finalrules/2026-05635.html",
                ],
            }
        ],
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path = "config.json") -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)

    with config_path.open("r", encoding="utf-8") as handle:
        user_config = json.load(handle)
    return deep_merge(DEFAULT_CONFIG, user_config)


def save_config(config: dict[str, Any], path: str | Path = "config.json") -> None:
    config_path = Path(path)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def with_crypto_assets(
    config: dict[str, Any],
    assets: set[str],
    granularity_seconds: int = 3600,
) -> dict[str, Any]:
    expanded = deepcopy(config)
    tracked = expanded.setdefault("crypto_assets", [])
    existing_labels = {
        str(item.get("label") or item.get("product_id") or "").upper()
        for item in tracked
    }
    existing_products = {
        str(item.get("product_id") or "").upper()
        for item in tracked
    }

    for asset in sorted({item.upper().strip() for item in assets if item.strip()}):
        product_id = f"{asset}-USD"
        if asset in existing_labels or product_id in existing_products:
            continue
        tracked.append(
            {
                "label": asset,
                "source": "coinbase",
                "product_id": product_id,
                "granularity_seconds": granularity_seconds,
            }
        )
    return expanded


def add_tracked_crypto(
    asset: str,
    product_id: str,
    path: str | Path = "config.json",
    granularity_seconds: int = 3600,
) -> dict[str, Any]:
    config = load_config(path)
    asset_label = asset.upper().strip()
    product = product_id.upper().strip()
    if not asset_label:
        raise ValueError("Asset is required.")
    if not product:
        product = f"{asset_label}-USD"

    tracked = config.setdefault("crypto_assets", [])
    for item in tracked:
        if str(item.get("label", "")).upper() == asset_label:
            item["product_id"] = product
            item["source"] = "coinbase"
            item["granularity_seconds"] = granularity_seconds
            save_config(config, path)
            return config

    tracked.append(
        {
            "label": asset_label,
            "source": "coinbase",
            "product_id": product,
            "granularity_seconds": granularity_seconds,
        }
    )
    if not config.get("base_asset"):
        config["base_asset"] = asset_label
    save_config(config, path)
    return config


def remove_tracked_crypto(asset: str, path: str | Path = "config.json") -> dict[str, Any]:
    config = load_config(path)
    asset_label = asset.upper().strip()
    tracked = config.setdefault("crypto_assets", [])
    config["crypto_assets"] = [
        item
        for item in tracked
        if str(item.get("label", "")).upper() != asset_label
    ]
    if str(config.get("base_asset", "")).upper() == asset_label:
        config["base_asset"] = (
            str(config["crypto_assets"][0].get("label", ""))
            if config["crypto_assets"]
            else ""
        )
    save_config(config, path)
    return config
