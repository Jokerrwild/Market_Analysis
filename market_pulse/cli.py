from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from datetime import datetime, timedelta

from .app import run_once
from .config import load_config
from .dashboard import serve_dashboard
from .db import database_stats, db_path as resolve_db_path
from .time_utils import resolve_timezone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="market_pulse",
        description="Run hybrid Bayesian cryptocurrency market analysis.",
    )
    parser.add_argument("--config", default="config.json", help="Path to config JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one analysis now.")
    run_parser.add_argument("--notes", help="Optional qualitative context to include.")

    watch_parser = subparsers.add_parser("watch", help="Run analysis repeatedly.")
    watch_parser.add_argument("--interval-minutes", type=float, help="Minutes between runs.")
    watch_parser.add_argument("--times", help="Comma-separated local clock times, such as 09:30,12:00,16:00.")
    watch_parser.add_argument("--between", help="Optional active window, such as 08:00-21:00.")
    watch_parser.add_argument("--run-now", action="store_true", help="Run immediately before waiting.")
    watch_parser.add_argument("--max-runs", type=int, help="Stop after this many runs.")
    watch_parser.add_argument("--notes", help="Optional qualitative context to include.")

    dashboard_parser = subparsers.add_parser("dashboard", help="Run the local dashboard server.")
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind host.")
    dashboard_parser.add_argument("--port", type=int, default=8765, help="Dashboard port.")
    dashboard_parser.add_argument("--ledger", default="ledger.json", help="Path to ledger JSON.")
    dashboard_parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")

    subparsers.add_parser("db-stats", help="Show SQLite collection counts and date ranges.")

    args = parser.parse_args(argv)

    if args.command == "run":
        return execute_run(args.config, args.notes)

    if args.command == "watch":
        return execute_watch(args)

    if args.command == "dashboard":
        if args.open:
            webbrowser.open(f"http://{args.host}:{args.port}")
        serve_dashboard(
            host=args.host,
            port=args.port,
            config_path=args.config,
            ledger_path=args.ledger,
        )
        return 0

    if args.command == "db-stats":
        config = load_config(args.config)
        print(json.dumps(database_stats(resolve_db_path(config)), indent=2))
        return 0

    parser.error("Unknown command.")
    return 2


def execute_run(config_path: str, notes: str | None) -> int:
    try:
        markdown_path, json_path, thesis = run_once(config_path=config_path, notes=notes)
    except Exception as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1

    print(thesis)
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    return 0


def execute_watch(args: argparse.Namespace) -> int:
    if not args.interval_minutes and not args.times:
        print("watch requires --interval-minutes or --times", file=sys.stderr)
        return 2
    if args.interval_minutes is not None and args.interval_minutes <= 0:
        print("--interval-minutes must be positive", file=sys.stderr)
        return 2

    config = load_config(args.config)
    timezone = resolve_timezone(config.get("timezone", "America/New_York"))
    active_window = parse_window(args.between) if args.between else None
    clock_times = parse_times(args.times) if args.times else None
    runs = 0

    print("Market Pulse watcher started. Press Ctrl+C to stop.")
    try:
        if args.run_now or args.interval_minutes:
            runs += run_and_print(args.config, args.notes)
            if args.max_runs and runs >= args.max_runs:
                return 0

        while True:
            now = datetime.now(timezone)
            if clock_times:
                next_run = next_clock_run(now, clock_times)
                sleep_until(next_run)
            else:
                next_run = now + timedelta(minutes=float(args.interval_minutes))
                sleep_until(next_run)

            if active_window and not is_inside_window(datetime.now(timezone), active_window):
                next_start = next_window_start(datetime.now(timezone), active_window)
                print(f"Outside active window. Sleeping until {next_start.isoformat()}.")
                sleep_until(next_start)

            runs += run_and_print(args.config, args.notes)
            if args.max_runs and runs >= args.max_runs:
                return 0
    except KeyboardInterrupt:
        print("Market Pulse watcher stopped.")
        return 0


def run_and_print(config_path: str, notes: str | None) -> int:
    markdown_path, json_path, thesis = run_once(config_path=config_path, notes=notes)
    print("")
    print(datetime.now().isoformat(timespec="seconds"))
    print(thesis)
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    return 1


def parse_times(value: str) -> list[tuple[int, int]]:
    times: list[tuple[int, int]] = []
    for part in value.split(","):
        hour, minute = parse_hhmm(part.strip())
        times.append((hour, minute))
    return sorted(set(times))


def parse_window(value: str) -> tuple[tuple[int, int], tuple[int, int]]:
    if "-" not in value:
        raise ValueError("--between must use HH:MM-HH:MM")
    start, end = value.split("-", 1)
    return parse_hhmm(start.strip()), parse_hhmm(end.strip())


def parse_hhmm(value: str) -> tuple[int, int]:
    pieces = value.split(":")
    if len(pieces) != 2:
        raise ValueError(f"Invalid time: {value}")
    hour = int(pieces[0])
    minute = int(pieces[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time: {value}")
    return hour, minute


def next_clock_run(now: datetime, times: list[tuple[int, int]]) -> datetime:
    candidates = [
        now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for hour, minute in times
    ]
    future = [candidate for candidate in candidates if candidate > now]
    if future:
        return min(future)
    first_hour, first_minute = times[0]
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=first_hour, minute=first_minute, second=0, microsecond=0)


def is_inside_window(now: datetime, window: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    start, end = window
    current_minutes = now.hour * 60 + now.minute
    start_minutes = start[0] * 60 + start[1]
    end_minutes = end[0] * 60 + end[1]
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes


def next_window_start(now: datetime, window: tuple[tuple[int, int], tuple[int, int]]) -> datetime:
    start, _ = window
    candidate = now.replace(hour=start[0], minute=start[1], second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def sleep_until(target: datetime) -> None:
    while True:
        seconds = (target - datetime.now(target.tzinfo)).total_seconds()
        if seconds <= 0:
            return
        print(f"Next run at {target.isoformat(timespec='minutes')} ({int(seconds // 60)} min).")
        time.sleep(min(seconds, 300))
