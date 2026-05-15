from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from shutil import copyfile

from .models import AnalysisResult


def write_reports(
    result: AnalysisResult,
    report_dir: str | Path,
    market_breadth: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    root = Path(report_dir)
    timestamp = result.generated_at.strftime("%Y%m%d_%H%M%S")
    run_dir = root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = run_dir / "analysis.md"
    json_path = run_dir / "analysis.json"

    markdown_path.write_text(render_markdown(result, market_breadth=market_breadth), encoding="utf-8")
    payload = asdict(result)
    if market_breadth is not None:
        payload["market_breadth"] = market_breadth
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    latest_path = root / "latest.md"
    copyfile(markdown_path, latest_path)
    return markdown_path, json_path


def render_markdown(result: AnalysisResult, market_breadth: dict[str, object] | None = None) -> str:
    lines: list[str] = []
    lines.append("# Market Pulse Analysis")
    lines.append("")
    lines.append(f"Generated at: `{result.generated_at.isoformat()}`")
    lines.append("")
    lines.append("## Market Thesis")
    lines.append("")
    lines.append(result.leading_thesis)
    lines.append("")
    lines.append("## Probability Table")
    lines.append("")
    lines.append("| Market Regime | Posterior Probability | Confidence | Key Evidence |")
    lines.append("| --- | ---: | --- | --- |")
    for item in result.probabilities:
        lines.append(
            f"| {item.regime} | {item.probability * 100:.1f}% | {item.confidence} | {item.key_evidence} |"
        )
    lines.append("")
    lines.append("## Quantitative Evidence")
    lines.append("")
    lines.extend(f"- {item}" for item in result.quantitative_evidence)
    lines.append("")
    if market_breadth:
        lines.append("## Market Breadth")
        lines.append("")
        excluded = market_breadth.get("excluded_assets", [])
        if excluded:
            lines.append(f"Excluding portfolio/tracked assets: `{', '.join(excluded)}`")
            lines.append("")
        lines.append("### Top Currency Movers")
        lines.append("")
        lines.append("| Asset | 24h Move | Last Price | 24h Dollar Volume |")
        lines.append("| --- | ---: | ---: | ---: |")
        for item in market_breadth.get("top_movers", [])[:10]:
            lines.append(
                f"| {item['asset']} | {item['change_24h_pct']:+.2f}% | "
                f"${item['price']:,.4f} | ${item['quote_volume_24h']:,.0f} |"
            )
        lines.append("")
        lines.append("### Top 10 Traded")
        lines.append("")
        lines.append("| Asset | 24h Dollar Volume | 24h Move | Last Price |")
        lines.append("| --- | ---: | ---: | ---: |")
        for item in market_breadth.get("top_traded", [])[:10]:
            lines.append(
                f"| {item['asset']} | ${item['quote_volume_24h']:,.0f} | "
                f"{item['change_24h_pct']:+.2f}% | ${item['price']:,.4f} |"
            )
        lines.append("")
    lines.append("## Qualitative Evidence")
    lines.append("")
    lines.extend(f"- {item}" for item in result.qualitative_evidence)
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(result.interpretation)
    lines.append("")
    lines.append("## Invalidation Conditions")
    lines.append("")
    lines.extend(f"- {item}" for item in result.invalidation_conditions)
    lines.append("")
    lines.append("## Risk-Aware Decision Support")
    lines.append("")
    lines.extend(f"- {item}" for item in result.decision_support)
    lines.append("")
    lines.append("## What To Monitor Next")
    lines.append("")
    lines.extend(f"- {item}" for item in result.monitor_next)

    if result.snapshot.errors:
        lines.append("")
        lines.append("## Data Source Warnings")
        lines.append("")
        lines.extend(f"- {item}" for item in result.snapshot.errors)

    lines.append("")
    return "\n".join(lines)
