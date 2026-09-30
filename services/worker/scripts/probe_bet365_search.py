"""Quick local test: discover Bet365 fixtures and print normalized market odds.

Usage:
    python3 -m scripts.probe_bet365_search --league PL --max-matches 5
    python3 -m scripts.probe_bet365_search --dedicated-profile

This calls the same ``Bet365Client`` used by the worker, but does not persist results.
It uses an isolated temporary Chrome profile unless a dedicated profile is requested.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from app.config import (
    DEFAULT_BET365_BROWSER_IDLE_SECONDS,
    DEFAULT_BET365_COMPETITION_NAME,
    DEFAULT_BET365_MAX_MATCHES,
    DEFAULT_BET365_PRE_MATCH_CUTOFF_MINUTES,
    DEFAULT_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS,
    DEFAULT_BET365_WEBSITE_URL,
)
from app.ingestion.betting_markets import (
    Bet365Client,
    Bet365IngestionError,
    BettingMarketObservation,
)
from scripts.open_chrome_profile import (
    DEFAULT_WORKER_CHROME_USER_DATA_DIR,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Bet365 match and player markets with the worker browser client"
    )
    parser.add_argument(
        "--league",
        default="PL",
        help="competition alias or exact label, default: PL",
    )
    parser.add_argument(
        "--competition",
        default=DEFAULT_BET365_COMPETITION_NAME,
        help=f"configured competition label, default: {DEFAULT_BET365_COMPETITION_NAME}",
    )
    parser.add_argument(
        "--homepage-url",
        default=DEFAULT_BET365_WEBSITE_URL,
        help=f"Bet365 homepage route, default: {DEFAULT_BET365_WEBSITE_URL}",
    )
    parser.add_argument(
        "--max-matches",
        type=_positive_int,
        default=DEFAULT_BET365_MAX_MATCHES,
        help=f"maximum fixture pages to inspect, default: {DEFAULT_BET365_MAX_MATCHES}",
    )
    parser.add_argument(
        "--pre-match-cutoff-minutes",
        type=_non_negative_int,
        default=DEFAULT_BET365_PRE_MATCH_CUTOFF_MINUTES,
        help=(
            "exclude fixtures starting within this many minutes, "
            f"default: {DEFAULT_BET365_PRE_MATCH_CUTOFF_MINUTES}"
        ),
    )
    parser.add_argument(
        "--navigation-interval-seconds",
        type=_non_negative_float,
        default=DEFAULT_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS,
        help=(
            "minimum delay between browser navigations, "
            f"default: {DEFAULT_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS:g}"
        ),
    )
    parser.add_argument(
        "--browser-idle-seconds",
        type=_non_negative_float,
        default=DEFAULT_BET365_BROWSER_IDLE_SECONDS,
        help=f"render wait after navigation, default: {DEFAULT_BET365_BROWSER_IDLE_SECONDS:g}",
    )
    parser.add_argument(
        "--profile",
        help="profile directory inside --user-data-dir; default: Default",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        help="explicit persistent Chrome root; omitted uses a temporary profile",
    )
    parser.add_argument(
        "--dedicated-profile",
        action="store_true",
        help="use Stockball's isolated persistent Chrome profile",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        user_data_dir, profile = _resolve_profile(args)
        client = Bet365Client(
            browser_enabled=True,
            homepage_url=args.homepage_url,
            competition_name=args.competition,
            max_matches=args.max_matches,
            pre_match_cutoff_minutes=args.pre_match_cutoff_minutes,
            request_interval_seconds=args.navigation_interval_seconds,
            browser_idle_seconds=args.browser_idle_seconds,
            browser_user_data_dir=(
                None if user_data_dir is None else str(user_data_dir)
            ),
            browser_profile_directory=profile,
        )

        print(f"Competition: {args.league}", flush=True)
        if user_data_dir is None:
            print("Using an isolated temporary Chrome profile\n", flush=True)
        else:
            print(f"Using Chrome profile: {profile} ({user_data_dir})\n", flush=True)
        observations = client.list_pre_match_markets(args.league)
    except (Bet365IngestionError, OSError, ValueError) as exc:
        print(f"Bet365 fetch failed: {exc}", file=sys.stderr)
        if exc.__cause__ is not None:
            print(f"Cause: {exc.__cause__}", file=sys.stderr)
        return 1

    _print_observations(observations)
    return 0


def _resolve_profile(args: argparse.Namespace) -> tuple[Path | None, str | None]:
    if args.dedicated_profile:
        user_data_dir = args.user_data_dir or DEFAULT_WORKER_CHROME_USER_DATA_DIR
        user_data_dir.mkdir(parents=True, exist_ok=True)
        return user_data_dir, args.profile or "Default"
    if args.user_data_dir is not None:
        return args.user_data_dir, args.profile or "Default"
    if args.profile is not None:
        raise ValueError("--profile requires --user-data-dir or --dedicated-profile")
    return None, None


def _print_observations(observations: list[BettingMarketObservation]) -> None:
    grouped: dict[str, list[BettingMarketObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.provider_event_id, []).append(observation)

    print(f"Found {len(grouped)} matches and {len(observations)} market selections\n")
    for index, (event_id, selections) in enumerate(grouped.items(), 1):
        match_selection = next(
            (selection for selection in selections if "home_team" in selection.raw_payload),
            selections[0],
        )
        home_team = str(match_selection.raw_payload.get("home_team", "Home"))
        away_team = str(match_selection.raw_payload.get("away_team", "Away"))
        print(f"{index}. {home_team} vs {away_team}")
        print(f"   event_id={event_id}")
        print(f"   observed_at={match_selection.observed_at.isoformat()}")
        if match_selection.source_url:
            print(f"   url={match_selection.source_url}")

        market_counts: dict[str, int] = {}
        for observation in selections:
            market_type = observation.selection.market_type
            market_counts[market_type] = market_counts.get(market_type, 0) + 1
        summary = ", ".join(
            f"{market_type}={count}"
            for market_type, count in sorted(market_counts.items())
        )
        print(f"   markets: {summary}")

        for observation in sorted(
            selections,
            key=lambda item: (
                item.selection.market_type,
                item.selection.participants[0].provider_player_name
                if item.selection.participants
                else item.selection.provider_selection_label,
                item.selection.line or Decimal("0"),
            ),
        ):
            selection = observation.selection
            participants = ", ".join(
                participant.provider_player_name
                for participant in selection.participants
            )
            subject = participants or selection.provider_selection_label
            line = "-" if selection.line is None else str(selection.line)
            display_odds = str(observation.raw_payload.get("display_odds", "unknown"))
            implied_percent = observation.implied_probability * Decimal("100")
            print(
                f"   {selection.market_type:<24} {subject}: "
                f"outcome={selection.outcome_type.value} line={line} "
                f"decimal={observation.decimal_odds} quoted={display_odds} "
                f"implied={implied_percent:.2f}%"
            )
        print()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
