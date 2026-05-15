from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SeriesSummary:
    label: str
    source: str
    latest_time: str
    latest_close: float
    change_1_period_pct: float | None
    change_24h_pct: float | None
    change_7d_pct: float | None
    change_5d_pct: float | None
    change_20d_pct: float | None
    ema_20: float | None
    ema_50: float | None
    rsi_14: float | None
    realized_volatility_pct: float | None
    volume_impulse: float | None
    trend_score: float
    momentum_score: float
    volatility_score: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSnapshot:
    generated_at: datetime
    crypto: dict[str, SeriesSummary]
    macro: dict[str, SeriesSummary]
    errors: list[str]


@dataclass
class RegimeProbability:
    regime: str
    probability: float
    confidence: str
    key_evidence: str


@dataclass
class AnalysisResult:
    generated_at: datetime
    leading_thesis: str
    probabilities: list[RegimeProbability]
    quantitative_evidence: list[str]
    qualitative_evidence: list[str]
    interpretation: str
    invalidation_conditions: list[str]
    decision_support: list[str]
    monitor_next: list[str]
    snapshot: MarketSnapshot

