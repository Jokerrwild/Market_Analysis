from __future__ import annotations

from typing import Any


CLASSIFICATION_LABELS = {
    "digital_commodity": "Digital Commodity",
    "stablecoin": "Stablecoin",
    "digital_security": "Digital Security",
    "digital_collectible": "Digital Collectible",
    "digital_tool": "Digital Tool",
}


def is_enabled(config: dict[str, Any]) -> bool:
    context = config.get("regulatory_context", {})
    return bool(context.get("enabled", True))


def configured_events(config: dict[str, Any]) -> list[dict[str, Any]]:
    if not is_enabled(config):
        return []
    context = config.get("regulatory_context", {})
    events = context.get("events", [])
    return [event for event in events if isinstance(event, dict)]


def affected_assets(event: dict[str, Any]) -> set[str]:
    return {
        str(asset).upper().strip()
        for asset in event.get("affected_assets", [])
        if str(asset).strip()
    }


def events_for_asset(config: dict[str, Any], asset: str) -> list[dict[str, Any]]:
    symbol = asset.upper().strip()
    return [
        event
        for event in configured_events(config)
        if symbol in affected_assets(event)
    ]


def classification_label(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return CLASSIFICATION_LABELS.get(key, key.replace("_", " ").title() if key else "Regulatory Context")


def support_score_for_asset(config: dict[str, Any], asset: str) -> float:
    score = 0.0
    for event in events_for_asset(config, asset):
        try:
            score += float(event.get("impact_score", 0))
        except (TypeError, ValueError):
            continue
    return max(0.0, min(score, 0.35))


def profile_for_asset(config: dict[str, Any], asset: str) -> dict[str, Any]:
    symbol = asset.upper().strip()
    profiles: list[dict[str, Any]] = []
    tags: list[str] = []
    for event in events_for_asset(config, symbol):
        classification = str(event.get("classification", "")).strip()
        label = classification_label(classification)
        tags.append(label)
        profiles.append(
            {
                "id": event.get("id", ""),
                "title": event.get("title", ""),
                "date": event.get("date", ""),
                "classification": classification,
                "classification_label": label,
                "summary": event.get("summary", ""),
                "source_urls": event.get("source_urls", []),
                "impact_score": event.get("impact_score", 0),
            }
        )
    return {
        "asset": symbol,
        "tags": sorted(set(tags)),
        "support_score": support_score_for_asset(config, symbol),
        "events": profiles,
    }


def context_for_assets(config: dict[str, Any], assets: set[str]) -> dict[str, Any]:
    profiles = {
        asset: profile_for_asset(config, asset)
        for asset in sorted({item.upper().strip() for item in assets if item.strip()})
    }
    active_profiles = {
        asset: profile
        for asset, profile in profiles.items()
        if profile["events"]
    }
    return {
        "enabled": is_enabled(config),
        "assets": profiles,
        "active_assets": sorted(active_profiles),
        "events": configured_events(config),
    }


def evidence_for_assets(config: dict[str, Any], assets: set[str], limit: int = 4) -> list[str]:
    evidence: list[str] = []
    for asset in sorted({item.upper().strip() for item in assets if item.strip()}):
        profile = profile_for_asset(config, asset)
        for event in profile["events"]:
            evidence.append(
                f"{asset} regulatory context: {event['classification_label']} under {event['title']} "
                f"({event['date']}); support factor {profile['support_score']:+.2f}."
            )
            break
        if len(evidence) >= limit:
            break
    return evidence


def source_note_for_asset(config: dict[str, Any], asset: str) -> str | None:
    events = events_for_asset(config, asset)
    if not events:
        return None
    event = events[0]
    return f"{event.get('title', 'Regulatory context')} ({event.get('date', '')})"
