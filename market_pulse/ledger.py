from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

EPSILON = 0.00000001


@dataclass
class LedgerTransaction:
    id: str
    timestamp: str
    asset: str
    side: str
    quantity: float
    price: float
    fees: float = 0.0
    notes: str = ""


@dataclass
class Ledger:
    initial_capital: float = 0.0
    target_roi_pct: float = 0.0
    target_days: int = 0
    goal_started_at: str = ""
    transactions: list[LedgerTransaction] = field(default_factory=list)


@dataclass
class LedgerSimulation:
    valid: bool
    errors: list[str]
    warnings: list[str]
    cash: float
    positions: dict[str, dict[str, float]]
    realized_pnl: float
    total_fees: float
    total_buy_cost: float
    total_sell_proceeds: float


def load_ledger(path: str | Path = "ledger.json") -> Ledger:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return Ledger()
    with ledger_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    transactions = [
        LedgerTransaction(
            id=str(item.get("id") or uuid4()),
            timestamp=str(item.get("timestamp") or datetime.now().isoformat(timespec="seconds")),
            asset=str(item.get("asset", "")).upper(),
            side=str(item.get("side", "")).upper(),
            quantity=float(item.get("quantity", 0)),
            price=float(item.get("price", 0)),
            fees=float(item.get("fees", 0)),
            notes=str(item.get("notes", "")),
        )
        for item in data.get("transactions", [])
    ]
    return Ledger(
        initial_capital=float(data.get("initial_capital", 0)),
        target_roi_pct=float(data.get("target_roi_pct", 0)),
        target_days=int(data.get("target_days", 0) or 0),
        goal_started_at=str(data.get("goal_started_at", "")),
        transactions=transactions,
    )


def parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def transaction_time_value(transaction: LedgerTransaction) -> float:
    try:
        parsed = parse_timestamp(transaction.timestamp)
        return parsed.timestamp()
    except ValueError:
        return float("inf")


def transaction_sort_key(transaction: LedgerTransaction) -> tuple[float, str]:
    return transaction_time_value(transaction), transaction.id


def chronological_transactions(transactions: list[LedgerTransaction]) -> list[LedgerTransaction]:
    indexed = enumerate(transactions)
    return [
        transaction
        for _, transaction in sorted(
            indexed,
            key=lambda item: (transaction_time_value(item[1]), item[0]),
        )
    ]


def save_ledger(ledger: Ledger, path: str | Path = "ledger.json") -> None:
    ledger_path = Path(path)
    payload = {
        "initial_capital": ledger.initial_capital,
        "target_roi_pct": ledger.target_roi_pct,
        "target_days": ledger.target_days,
        "goal_started_at": ledger.goal_started_at,
        "transactions": [transaction.__dict__ for transaction in ledger.transactions],
    }
    ledger_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def set_initial_capital(amount: float, path: str | Path = "ledger.json") -> Ledger:
    if amount < 0:
        raise ValueError("Initial capital cannot be negative.")
    ledger = load_ledger(path)
    ledger.initial_capital = amount
    ensure_valid_ledger(ledger)
    save_ledger(ledger, path)
    return ledger


def set_investment_goal(
    initial_capital: float,
    target_roi_pct: float,
    target_days: int,
    path: str | Path = "ledger.json",
) -> Ledger:
    if initial_capital < 0:
        raise ValueError("Initial capital cannot be negative.")
    if target_roi_pct < 0:
        raise ValueError("Target ROI cannot be negative.")
    if target_days < 1:
        raise ValueError("Target days must be at least 1.")

    ledger = load_ledger(path)
    reset_start = (
        ledger.initial_capital != initial_capital
        or ledger.target_roi_pct != target_roi_pct
        or ledger.target_days != target_days
        or not ledger.goal_started_at
    )
    ledger.initial_capital = initial_capital
    ledger.target_roi_pct = target_roi_pct
    ledger.target_days = target_days
    if reset_start:
        ledger.goal_started_at = datetime.now().isoformat(timespec="seconds")
    ensure_valid_ledger(ledger)
    save_ledger(ledger, path)
    return ledger


def available_cash(ledger: Ledger) -> float:
    return simulate_ledger(ledger).cash


def affordable_transactions(ledger: Ledger) -> tuple[list[LedgerTransaction], list[LedgerTransaction]]:
    repaired = Ledger(
        initial_capital=ledger.initial_capital,
        target_roi_pct=ledger.target_roi_pct,
        target_days=ledger.target_days,
        goal_started_at=ledger.goal_started_at,
    )
    kept: list[LedgerTransaction] = []
    removed: list[LedgerTransaction] = []

    for transaction in chronological_transactions(ledger.transactions):
        if transaction.side == "BUY":
            cost = transaction.quantity * transaction.price + transaction.fees
            if cost > available_cash(repaired) + EPSILON:
                removed.append(transaction)
                continue
        elif transaction.side == "SELL":
            current_quantity = sum(
                item.quantity if item.side == "BUY" else -item.quantity
                for item in repaired.transactions
                if item.asset == transaction.asset
            )
            if transaction.quantity > current_quantity + EPSILON:
                removed.append(transaction)
                continue

        repaired.transactions.append(transaction)
        kept.append(transaction)

    return kept, removed


def repair_ledger(path: str | Path = "ledger.json") -> list[LedgerTransaction]:
    ledger = load_ledger(path)
    kept, removed = affordable_transactions(ledger)
    if removed:
        ledger.transactions = kept
        save_ledger(ledger, path)
    return removed


def simulate_ledger(ledger: Ledger) -> LedgerSimulation:
    errors: list[str] = []
    warnings: list[str] = []
    cash = ledger.initial_capital
    positions: dict[str, dict[str, float]] = {}
    realized_pnl = 0.0
    total_fees = 0.0
    total_buy_cost = 0.0
    total_sell_proceeds = 0.0

    if ledger.initial_capital < 0:
        errors.append("Initial capital cannot be negative.")

    for transaction in chronological_transactions(ledger.transactions):
        asset = transaction.asset.upper().strip()
        side = transaction.side.upper().strip()
        context = f"{transaction.id} {side} {asset}"

        try:
            parse_timestamp(transaction.timestamp)
        except ValueError:
            errors.append(f"{context}: timestamp is invalid.")

        if side not in {"BUY", "SELL"}:
            errors.append(f"{context}: side must be BUY or SELL.")
            continue
        if not asset:
            errors.append(f"{transaction.id}: asset is required.")
            continue
        if transaction.quantity <= 0:
            errors.append(f"{context}: quantity must be greater than zero.")
            continue
        if transaction.price <= 0:
            errors.append(f"{context}: price must be greater than zero.")
            continue
        if transaction.fees < 0:
            errors.append(f"{context}: fees cannot be negative.")
            continue

        position = positions.setdefault(
            asset,
            {
                "quantity": 0.0,
                "cost_basis": 0.0,
                "realized_pnl": 0.0,
                "fees": 0.0,
            },
        )
        gross = transaction.quantity * transaction.price
        total_fees += transaction.fees
        position["fees"] += transaction.fees

        if side == "BUY":
            cost = gross + transaction.fees
            if cost > cash + EPSILON:
                errors.append(
                    f"{context}: BUY cost ${cost:,.2f} exceeds available cash ${cash:,.2f}."
                )
                continue
            cash -= cost
            total_buy_cost += cost
            position["quantity"] += transaction.quantity
            position["cost_basis"] += cost
            continue

        if transaction.quantity > position["quantity"] + EPSILON:
            errors.append(
                f"{context}: SELL quantity {transaction.quantity:g} exceeds recorded holdings "
                f"{position['quantity']:g}."
            )
            continue

        proceeds = gross - transaction.fees
        if proceeds < -EPSILON:
            errors.append(f"{context}: fees exceed sell proceeds.")
            continue
        average_cost = position["cost_basis"] / position["quantity"] if position["quantity"] else 0.0
        closed_cost = average_cost * transaction.quantity
        pnl = proceeds - closed_cost
        cash += proceeds
        total_sell_proceeds += proceeds
        position["quantity"] -= transaction.quantity
        position["cost_basis"] -= closed_cost
        position["realized_pnl"] += pnl
        realized_pnl += pnl

    if cash < -EPSILON:
        errors.append(f"Ledger cash is negative: ${cash:,.2f}.")
    for asset, position in positions.items():
        if position["quantity"] < -EPSILON:
            errors.append(f"{asset}: position quantity is negative.")
        if abs(position["quantity"]) <= EPSILON:
            position["quantity"] = 0.0
            position["cost_basis"] = 0.0

    if not ledger.transactions:
        warnings.append("No transactions have been recorded yet.")

    return LedgerSimulation(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        cash=cash,
        positions=positions,
        realized_pnl=realized_pnl,
        total_fees=total_fees,
        total_buy_cost=total_buy_cost,
        total_sell_proceeds=total_sell_proceeds,
    )


def ensure_valid_ledger(ledger: Ledger) -> None:
    simulation = simulate_ledger(ledger)
    if not simulation.valid:
        raise ValueError("Ledger validation failed: " + "; ".join(simulation.errors))


def add_transaction(payload: dict[str, Any], path: str | Path = "ledger.json") -> LedgerTransaction:
    side = str(payload.get("side", "")).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("Transaction side must be BUY or SELL.")
    asset = str(payload.get("asset", "")).upper().strip()
    if not asset:
        raise ValueError("Asset is required.")

    quantity = float(payload.get("quantity", 0))
    price = float(payload.get("price", 0))
    fees = float(payload.get("fees", 0) or 0)
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if price <= 0:
        raise ValueError("Price must be greater than zero.")
    if fees < 0:
        raise ValueError("Fees cannot be negative.")

    timestamp = str(payload.get("timestamp") or datetime.now().isoformat(timespec="seconds"))
    ledger = load_ledger(path)
    transaction = LedgerTransaction(
        id=str(uuid4()),
        timestamp=timestamp,
        asset=asset,
        side=side,
        quantity=quantity,
        price=price,
        fees=fees,
        notes=str(payload.get("notes", "")),
    )

    ledger.transactions.append(transaction)
    simulation = simulate_ledger(ledger)
    if not simulation.valid:
        friendly_errors = [
            error.replace(transaction.id, "New transaction")
            for error in simulation.errors
        ]
        raise ValueError("; ".join(friendly_errors))
    save_ledger(ledger, path)
    return transaction


def delete_transaction(transaction_id: str, path: str | Path = "ledger.json") -> bool:
    ledger = load_ledger(path)
    before = len(ledger.transactions)
    original_transactions = list(ledger.transactions)
    ledger.transactions = [item for item in ledger.transactions if item.id != transaction_id]
    changed = len(ledger.transactions) != before
    if changed:
        try:
            ensure_valid_ledger(ledger)
        except ValueError:
            ledger.transactions = original_transactions
            raise
        save_ledger(ledger, path)
    return changed


def summarize_ledger(
    ledger: Ledger,
    current_prices: dict[str, float],
) -> dict[str, Any]:
    simulation = simulate_ledger(ledger)
    cash = simulation.cash
    positions = simulation.positions
    realized_pnl = simulation.realized_pnl

    holdings: list[dict[str, Any]] = []
    holdings_value = 0.0
    unrealized_pnl = 0.0

    for asset, position in sorted(positions.items()):
        quantity = position["quantity"]
        current_price = current_prices.get(asset)
        market_value = quantity * current_price if current_price is not None else 0.0
        asset_unrealized = market_value - position["cost_basis"] if current_price is not None else 0.0
        holdings_value += market_value
        unrealized_pnl += asset_unrealized
        holdings.append(
            {
                "asset": asset,
                "quantity": quantity,
                "average_cost": position["cost_basis"] / quantity if quantity else 0.0,
                "cost_basis": position["cost_basis"],
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": asset_unrealized,
                "realized_pnl": position["realized_pnl"],
                "fees": position["fees"],
            }
        )

    total_equity = cash + holdings_value
    total_pnl = total_equity - ledger.initial_capital
    component_total_pnl = realized_pnl + unrealized_pnl
    roi_pct = (total_pnl / ledger.initial_capital) * 100 if ledger.initial_capital > 0 else None
    goal = summarize_goal(ledger, total_equity, total_pnl)
    reconciliation_delta = total_pnl - component_total_pnl

    return {
        "initial_capital": ledger.initial_capital,
        "target_roi_pct": ledger.target_roi_pct,
        "target_days": ledger.target_days,
        "goal_started_at": ledger.goal_started_at,
        "cash": cash,
        "holdings_value": holdings_value,
        "total_equity": total_equity,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "component_total_pnl": component_total_pnl,
        "reconciliation_delta": reconciliation_delta,
        "roi_pct": roi_pct,
        "ledger_valid": simulation.valid and abs(reconciliation_delta) <= 0.01,
        "validation_errors": simulation.errors,
        "validation_warnings": simulation.warnings,
        "math": {
            "cash_formula": "initial_capital - buy_costs + sell_proceeds",
            "cash": cash,
            "total_buy_cost": simulation.total_buy_cost,
            "total_sell_proceeds": simulation.total_sell_proceeds,
            "total_fees": simulation.total_fees,
            "holdings_value": holdings_value,
            "total_equity_formula": "cash + holdings_value",
            "total_pnl_formula": "total_equity - initial_capital",
            "component_pnl_formula": "realized_pnl + unrealized_pnl",
            "reconciliation_delta": reconciliation_delta,
        },
        "goal": goal,
        "holdings": holdings,
        "transactions": [transaction.__dict__ for transaction in reversed(chronological_transactions(ledger.transactions))],
    }


def summarize_goal(ledger: Ledger, total_equity: float, total_pnl: float) -> dict[str, Any]:
    if ledger.initial_capital <= 0 or ledger.target_roi_pct <= 0 or ledger.target_days <= 0:
        return {
            "active": False,
            "target_equity": None,
            "target_profit": None,
            "required_daily_return_pct": None,
            "progress_pct": None,
            "profit_remaining": None,
            "days_elapsed": None,
            "days_remaining": None,
            "pace_status": "Set capital, target ROI, and target days to activate goal tracking.",
        }

    target_profit = ledger.initial_capital * (ledger.target_roi_pct / 100)
    target_equity = ledger.initial_capital + target_profit
    required_daily_return_pct = (
        ((target_equity / ledger.initial_capital) ** (1 / ledger.target_days)) - 1
    ) * 100
    profit_remaining = target_equity - total_equity
    progress_pct = (total_pnl / target_profit) * 100 if target_profit else 0.0

    days_elapsed = 0
    if ledger.goal_started_at:
        try:
            started_at = datetime.fromisoformat(ledger.goal_started_at)
            days_elapsed = max(0, (datetime.now() - started_at).days)
        except ValueError:
            days_elapsed = 0
    days_remaining = max(0, ledger.target_days - days_elapsed)

    expected_progress = (days_elapsed / ledger.target_days) * 100 if ledger.target_days else 0.0
    if progress_pct >= 100:
        pace_status = "Goal reached."
    elif days_remaining == 0:
        pace_status = "Target window has ended."
    elif progress_pct >= expected_progress:
        pace_status = "On or ahead of target pace."
    else:
        pace_status = "Behind target pace."

    return {
        "active": True,
        "target_equity": target_equity,
        "target_profit": target_profit,
        "required_daily_return_pct": required_daily_return_pct,
        "progress_pct": progress_pct,
        "profit_remaining": profit_remaining,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "pace_status": pace_status,
    }
