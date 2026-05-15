from __future__ import annotations

import math
from statistics import mean, pstdev

from .models import Candle, SeriesSummary


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def pct_change(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * 100


def value_periods_back(values: list[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    return values[-periods - 1]


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    smoothing = 2 / (period + 1)
    current = mean(values[:period])
    for value in values[period:]:
        current = (value * smoothing) + (current * (1 - smoothing))
    return current


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def realized_volatility(values: list[float], lookback: int = 24) -> float | None:
    if len(values) <= lookback:
        return None

    recent = values[-lookback - 1 :]
    returns: list[float] = []
    for previous, current in zip(recent[:-1], recent[1:]):
        if previous <= 0 or current <= 0:
            continue
        returns.append(math.log(current / previous))

    if len(returns) < 2:
        return None
    return pstdev(returns) * 100


def volume_impulse(volumes: list[float], lookback: int = 20) -> float | None:
    if len(volumes) <= lookback:
        return None
    baseline = mean(volumes[-lookback - 1 : -1])
    if baseline == 0:
        return None
    return (volumes[-1] - baseline) / baseline


def score_trend(
    latest_close: float,
    change_24h: float | None,
    change_5d: float | None,
    change_7d: float | None,
    change_20d: float | None,
    ema_20_value: float | None,
    ema_50_value: float | None,
) -> float:
    score = 0.0
    if change_24h is not None:
        score += clamp(change_24h / 4) * 0.25
    mid_term_change = change_5d if change_5d is not None else change_7d
    if mid_term_change is not None:
        score += clamp(mid_term_change / 8) * 0.35
    if change_20d is not None:
        score += clamp(change_20d / 12) * 0.20
    if ema_20_value is not None:
        score += (0.10 if latest_close >= ema_20_value else -0.10)
    if ema_50_value is not None:
        score += (0.10 if latest_close >= ema_50_value else -0.10)
    return clamp(score)


def score_momentum(rsi_value: float | None, change_1: float | None, change_24h: float | None) -> float:
    score = 0.0
    if rsi_value is not None:
        score += clamp((rsi_value - 50) / 25) * 0.70
    if change_1 is not None:
        score += clamp(change_1 / 1.5) * 0.15
    if change_24h is not None:
        score += clamp(change_24h / 4) * 0.15
    return clamp(score)


def score_volatility(volatility_pct: float | None) -> float:
    if volatility_pct is None:
        return 0.0
    return clamp((volatility_pct - 0.75) / 2.25, 0.0, 1.0)


def summarize_series(
    label: str,
    source: str,
    candles: list[Candle],
    periods_per_day: int = 1,
) -> SeriesSummary:
    if not candles:
        raise ValueError(f"No candles available for {label}")

    periods_per_day = max(1, periods_per_day)
    closes = [candle.close for candle in candles]
    volumes = [candle.volume for candle in candles]
    latest = candles[-1]
    latest_close = latest.close
    ema_20_value = ema(closes, 20)
    ema_50_value = ema(closes, 50)
    rsi_value = rsi(closes, 14)
    volatility_pct = realized_volatility(closes, 24)
    impulse = volume_impulse(volumes, 20)

    change_1 = pct_change(latest_close, value_periods_back(closes, 1))
    change_24h = pct_change(latest_close, value_periods_back(closes, periods_per_day))
    change_5d_reference = value_periods_back(closes, periods_per_day * 5)
    if change_5d_reference is None and len(closes) > 1:
        change_5d_reference = closes[0]
    change_5d = pct_change(latest_close, change_5d_reference)
    change_7d = pct_change(latest_close, value_periods_back(closes, periods_per_day * 7))
    change_20d = pct_change(latest_close, value_periods_back(closes, periods_per_day * 20))

    trend = score_trend(
        latest_close=latest_close,
        change_24h=change_24h,
        change_5d=change_5d,
        change_7d=change_7d,
        change_20d=change_20d,
        ema_20_value=ema_20_value,
        ema_50_value=ema_50_value,
    )
    momentum = score_momentum(rsi_value, change_1, change_24h)
    volatility = score_volatility(volatility_pct)

    return SeriesSummary(
        label=label,
        source=source,
        latest_time=latest.timestamp.isoformat(),
        latest_close=latest_close,
        change_1_period_pct=change_1,
        change_24h_pct=change_24h,
        change_7d_pct=change_7d,
        change_5d_pct=change_5d,
        change_20d_pct=change_20d,
        ema_20=ema_20_value,
        ema_50=ema_50_value,
        rsi_14=rsi_value,
        realized_volatility_pct=volatility_pct,
        volume_impulse=impulse,
        trend_score=trend,
        momentum_score=momentum,
        volatility_score=volatility,
        raw={
            "candle_count": len(candles),
            "first_time": candles[0].timestamp.isoformat(),
        },
    )
