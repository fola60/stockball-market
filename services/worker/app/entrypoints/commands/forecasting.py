"""Forecast model commands: training, daily forecasts, and history backfills."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import DatabaseSettings
from app.entrypoints.factories import build_forecast_service, configure_logging


def train_forecast_model(args) -> int:
    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    summary = build_forecast_service(settings).train(save=not args.dry_run)
    print(json.dumps(summary, sort_keys=True, default=str))
    return 0


def refresh_forecasts(args) -> int:
    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    retrain = True if args.retrain else False if args.no_retrain else None
    summary = build_forecast_service(settings).refresh(retrain=retrain)
    print(json.dumps(summary, sort_keys=True, default=str))
    return 0 if summary.get("status") == "ok" else 1


def backfill_market_value_history(args) -> int:
    from app.forecasting.backfill import backfill_market_value_history as backfill

    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    summary = backfill(
        settings.database_url,
        Path(args.valuations_csv),
        source=args.source,
        currency=args.currency,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


def import_match_odds(args) -> int:
    from app.forecasting import odds

    if not args.season and not args.csv:
        raise SystemExit("import-match-odds needs --season or --csv")
    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    texts = odds.read_csv_files(args.csv) + [odds.download_season(s) for s in args.season]
    summary = odds.import_match_odds(settings.database_url, texts)
    print(json.dumps(summary, sort_keys=True))
    return 0
