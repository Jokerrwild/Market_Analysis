from __future__ import annotations

import math
from typing import Any

from .indicators import clamp
from .models import AnalysisResult, MarketSnapshot, RegimeProbability, SeriesSummary
from .regulatory import evidence_for_assets, source_note_for_asset, support_score_for_asset


REGIMES = [
    "Bullish accumulation",
    "Bullish continuation",
    "Neutral consolidation",
    "Bearish distribution",
    "Bearish continuation",
    "High-volatility transition",
    "Macro-driven risk-off",
]


def softmax(scores: dict[str, float]) -> dict[str, float]:
    highest = max(scores.values())
    exps = {key: math.exp(value - highest) for key, value in scores.items()}
    total = sum(exps.values())
    return {key: value / total for key, value in exps.items()}


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def price(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 100:
        return f"{value:,.2f}"
    return f"{value:.4f}"


def number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def confidence_label(score: float) -> str:
    if score >= 0.72:
        return "High"
    if score >= 0.48:
        return "Medium"
    return "Low"


def macro_scores(snapshot: MarketSnapshot) -> tuple[float, float, list[str]]:
    risk_on_components: list[float] = []
    risk_off_components: list[float] = []
    evidence: list[str] = []

    for label, summary in snapshot.macro.items():
        lower = label.lower()
        trend = summary.trend_score
        if label in {"SPY", "QQQ"} or "spy" in lower or "qqq" in lower:
            risk_on_components.append(trend)
            evidence.append(f"{label} trend score {trend:+.2f}, 5d {pct(summary.change_5d_pct)}")
        elif "dxy" in lower or "dollar" in lower:
            risk_off_components.append(trend)
            evidence.append(f"{label} trend score {trend:+.2f}, 5d {pct(summary.change_5d_pct)}")
        elif "yield" in lower or "tnx" in lower:
            risk_off_components.append(trend * 0.75)
            evidence.append(f"{label} trend score {trend:+.2f}, 5d {pct(summary.change_5d_pct)}")

    risk_on = mean_or_zero(risk_on_components)
    risk_off = mean_or_zero(risk_off_components)
    macro_risk = clamp((risk_off - risk_on) / 1.5, -1.0, 1.0)
    macro_support = clamp((risk_on - risk_off) / 1.5, -1.0, 1.0)
    return macro_support, macro_risk, evidence


def mean_or_zero(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def regime_key_evidence(regime: str, base: SeriesSummary | None, macro_risk: float, macro_support: float) -> str:
    if base is None:
        return "Insufficient crypto data; regime relies on macro and prior assumptions."

    if regime == "Bullish continuation":
        return f"Trend {base.trend_score:+.2f}, momentum {base.momentum_score:+.2f}, macro support {macro_support:+.2f}"
    if regime == "Bullish accumulation":
        return f"Momentum {base.momentum_score:+.2f} with limited trend extension; volatility {base.volatility_score:.2f}"
    if regime == "Neutral consolidation":
        return f"Trend {base.trend_score:+.2f}, momentum {base.momentum_score:+.2f}, mixed directional evidence"
    if regime == "Bearish distribution":
        return f"Trend {base.trend_score:+.2f}, momentum {base.momentum_score:+.2f}, macro risk {macro_risk:+.2f}"
    if regime == "Bearish continuation":
        return f"Downside trend/momentum pressure with macro risk {macro_risk:+.2f}"
    if regime == "High-volatility transition":
        return f"Realized volatility score {base.volatility_score:.2f} and signal disagreement risk"
    if regime == "Macro-driven risk-off":
        return f"Macro risk score {macro_risk:+.2f} versus crypto trend {base.trend_score:+.2f}"
    return "Evidence unavailable."


def analyze_snapshot(snapshot: MarketSnapshot, config: dict[str, Any], notes: str | None = None) -> AnalysisResult:
    base_label = config.get("base_asset", "BTC")
    base = snapshot.crypto.get(base_label) or next(iter(snapshot.crypto.values()), None)
    priors = config.get("regime_priors", {})
    macro_support, macro_risk, macro_evidence = macro_scores(snapshot)

    trend = base.trend_score if base else 0.0
    momentum = base.momentum_score if base else 0.0
    volatility = base.volatility_score if base else 0.0
    volume = clamp(base.volume_impulse or 0.0, -1.0, 1.0) if base else 0.0
    disagreement = clamp(abs(trend - momentum), 0.0, 1.0)
    regulatory_support = support_score_for_asset(config, base.label) if base else 0.0

    scores = {}
    for regime in REGIMES:
        prior = float(priors.get(regime, 1 / len(REGIMES)))
        scores[regime] = math.log(max(prior, 0.001))

    scores["Bullish continuation"] += 1.40 * trend + 1.20 * momentum + 0.80 * macro_support - 0.35 * volatility
    scores["Bullish accumulation"] += 0.75 * momentum - 0.25 * trend + 0.35 * macro_support + 0.35 * (1 - volatility)
    scores["Neutral consolidation"] += 1.15 * (1 - abs(trend)) + 0.75 * (1 - abs(momentum)) - 0.45 * volatility
    scores["Bearish distribution"] += -0.70 * trend - 0.95 * momentum + 0.70 * macro_risk + 0.30 * max(volume, 0)
    scores["Bearish continuation"] += -1.35 * trend - 1.20 * momentum + 0.55 * macro_risk
    scores["High-volatility transition"] += 1.35 * volatility + 0.60 * disagreement + 0.30 * (1 - abs(trend))
    scores["Macro-driven risk-off"] += 1.70 * macro_risk - 0.30 * trend - 0.20 * momentum
    scores["Bullish continuation"] += 0.25 * regulatory_support
    scores["Bullish accumulation"] += 0.35 * regulatory_support
    scores["Neutral consolidation"] += 0.15 * regulatory_support
    scores["Bearish distribution"] -= 0.20 * regulatory_support
    scores["Macro-driven risk-off"] -= 0.15 * regulatory_support

    posterior = softmax(scores)
    ordered = sorted(posterior.items(), key=lambda item: item[1], reverse=True)
    leading_regime, leading_probability = ordered[0]
    second_probability = ordered[1][1] if len(ordered) > 1 else 0.0
    data_coverage = min(1.0, (len(snapshot.crypto) + len(snapshot.macro)) / 6)
    confidence_score = clamp(
        (leading_probability - second_probability) * 1.4 + data_coverage * 0.35 + (1 - disagreement) * 0.20,
        0.0,
        1.0,
    )
    if leading_probability < 0.45:
        confidence_score = min(confidence_score, 0.68)
    if leading_probability < 0.33:
        confidence_score = min(confidence_score, 0.45)
    leading_confidence = confidence_label(confidence_score)

    probabilities = [
        RegimeProbability(
            regime=regime,
            probability=probability,
            confidence=leading_confidence if regime == leading_regime else confidence_label(confidence_score * 0.75),
            key_evidence=regime_key_evidence(regime, base, macro_risk, macro_support),
        )
        for regime, probability in ordered
    ]

    quantitative_evidence = build_quantitative_evidence(snapshot, base, macro_evidence, macro_support, macro_risk)
    qualitative_evidence = build_qualitative_evidence(leading_regime, macro_risk, notes, snapshot.errors)
    qualitative_evidence.extend(
        evidence_for_assets(config, set(snapshot.crypto), limit=4)
    )
    leading_thesis = (
        f"Current evidence favors {leading_regime.lower()} at {leading_probability * 100:.1f}% "
        f"posterior probability with {leading_confidence.lower()} confidence."
    )

    interpretation = build_interpretation(
        leading_regime,
        leading_probability,
        leading_confidence,
        base,
        macro_risk,
        regulatory_support,
    )
    invalidation_conditions = build_invalidation_conditions(leading_regime, base)
    decision_support = build_decision_support(
        leading_regime,
        leading_confidence,
        source_note_for_asset(config, base.label) if base else None,
    )
    monitor_next = build_monitor_next(base, macro_risk)

    return AnalysisResult(
        generated_at=snapshot.generated_at,
        leading_thesis=leading_thesis,
        probabilities=probabilities,
        quantitative_evidence=quantitative_evidence,
        qualitative_evidence=qualitative_evidence,
        interpretation=interpretation,
        invalidation_conditions=invalidation_conditions,
        decision_support=decision_support,
        monitor_next=monitor_next,
        snapshot=snapshot,
    )


def build_quantitative_evidence(
    snapshot: MarketSnapshot,
    base: SeriesSummary | None,
    macro_evidence: list[str],
    macro_support: float,
    macro_risk: float,
) -> list[str]:
    evidence: list[str] = []
    if base:
        evidence.append(
            f"{base.label} close {price(base.latest_close)}; 24h {pct(base.change_24h_pct)}; "
            f"5d {pct(base.change_5d_pct)}; RSI {number(base.rsi_14, 1)}"
        )
        evidence.append(
            f"{base.label} trend score {base.trend_score:+.2f}, momentum score {base.momentum_score:+.2f}, "
            f"volatility score {base.volatility_score:.2f}"
        )
        if base.ema_20 and base.ema_50:
            evidence.append(f"{base.label} EMA20 {price(base.ema_20)} and EMA50 {price(base.ema_50)}")

    for label, summary in snapshot.crypto.items():
        if base and label == base.label:
            continue
        evidence.append(
            f"{label} close {price(summary.latest_close)}; 24h {pct(summary.change_24h_pct)}; "
            f"trend {summary.trend_score:+.2f}; momentum {summary.momentum_score:+.2f}"
        )

    evidence.extend(macro_evidence)
    evidence.append(f"Macro support score {macro_support:+.2f}; macro risk score {macro_risk:+.2f}")
    return evidence


def build_qualitative_evidence(
    leading_regime: str,
    macro_risk: float,
    notes: str | None,
    errors: list[str],
) -> list[str]:
    evidence = [
        f"The leading regime is interpreted through a probability lens rather than as a direct trade signal.",
    ]
    if macro_risk > 0.25:
        evidence.append("Macro context is acting as a headwind for crypto risk appetite.")
    elif macro_risk < -0.25:
        evidence.append("Macro context is acting as a tailwind for risk assets.")
    else:
        evidence.append("Macro context is mixed enough that crypto-native signals deserve extra weight.")

    if "High-volatility" in leading_regime:
        evidence.append("Volatility regime risk is elevated, so timing and position sizing would matter more than directional conviction.")
    if notes:
        evidence.append(f"User context note: {notes}")
    if errors:
        evidence.append(f"Data limitations: {'; '.join(errors)}")
    return evidence


def build_interpretation(
    leading_regime: str,
    probability: float,
    confidence: str,
    base: SeriesSummary | None,
    macro_risk: float,
    regulatory_support: float = 0.0,
) -> str:
    base_text = "the base asset" if base is None else base.label
    interpretation = (
        f"The posterior distribution gives {leading_regime.lower()} the largest weight, but at "
        f"{probability * 100:.1f}% this should be read as a leaning rather than certainty. "
        f"{confidence} confidence means the model sees useful evidence, while still leaving room for competing regimes. "
        f"For {base_text}, the key tension is crypto trend/momentum versus macro risk ({macro_risk:+.2f})."
    )
    if regulatory_support > 0:
        interpretation += (
            f" Regulatory clarity contributes a separate support factor of {regulatory_support:+.2f}, "
            "which improves context but does not replace price confirmation."
        )
    return interpretation


def build_invalidation_conditions(leading_regime: str, base: SeriesSummary | None) -> list[str]:
    label = base.label if base else "the base asset"
    ema_20_value = price(base.ema_20) if base else "its 20-period EMA"
    ema_50_value = price(base.ema_50) if base else "its 50-period EMA"

    if "Bullish" in leading_regime:
        return [
            f"{label} loses {ema_20_value} with expanding volume.",
            f"{label} fails to hold above {ema_50_value} after a breakout attempt.",
            "DXY and yields strengthen while SPY/QQQ weaken.",
        ]
    if "Bearish" in leading_regime or "risk-off" in leading_regime:
        return [
            f"{label} reclaims {ema_20_value} and {ema_50_value} with improving momentum.",
            "SPY/QQQ turn higher while DXY and yields fade.",
            "Volatility contracts after a failed downside move.",
        ]
    if "High-volatility" in leading_regime:
        return [
            f"{label} resolves above {ema_20_value} and {ema_50_value} with stable follow-through.",
            f"{label} breaks below both moving averages without immediate reversal.",
            "Macro proxies stop sending mixed risk signals.",
        ]
    return [
        f"{label} leaves the current range with strong volume confirmation.",
        "Macro proxies align decisively risk-on or risk-off.",
        "Momentum readings move away from neutral.",
    ]


def build_decision_support(
    leading_regime: str,
    confidence: str,
    regulatory_source_note: str | None = None,
) -> list[str]:
    support = [
        "Conservative interpretation: wait for confirmation from both crypto trend and macro proxies.",
        "Aggressive interpretation: treat the leading regime as a working thesis with explicit invalidation.",
    ]
    if confidence == "Low":
        support.append("Risk-management consideration: low confidence favors smaller exposure or no new action until signals align.")
    elif confidence == "Medium":
        support.append("Risk-management consideration: medium confidence supports scenario planning, not certainty.")
    else:
        support.append("Risk-management consideration: even high confidence should still use predefined risk limits.")

    if "Bearish" in leading_regime or "risk-off" in leading_regime:
        support.append("Decision frame: prioritize capital preservation and watch for failed breakdowns before assuming continuation.")
    elif "Bullish" in leading_regime:
        support.append("Decision frame: upside participation is more defensible if pullbacks hold key moving averages.")
    else:
        support.append("Decision frame: range behavior can reward patience more than directional urgency.")
    if regulatory_source_note:
        support.append(
            f"Regulatory frame: {regulatory_source_note} reduces classification uncertainty, but trade timing still depends on liquidity, trend, and risk limits."
        )
    return support


def build_monitor_next(base: SeriesSummary | None, macro_risk: float) -> list[str]:
    label = base.label if base else "the base asset"
    monitor = [
        f"{label} reaction around EMA20 and EMA50.",
        "Whether RSI confirms or diverges from price direction.",
        "SPY/QQQ versus DXY and 10Y Yield alignment.",
    ]
    if macro_risk > 0.25:
        monitor.append("Whether macro risk cools enough to stop pressuring crypto beta.")
    elif macro_risk < -0.25:
        monitor.append("Whether risk-on macro support persists or fades.")
    else:
        monitor.append("Whether macro signals break out of the current mixed state.")
    return monitor
