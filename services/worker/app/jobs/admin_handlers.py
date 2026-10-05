from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from app.jobs.models import IngestPlayersJobPayload, JobExecutionResult, JobType
from app.synthetic_traders import (
    BotStatus,
    SpawnNameStyle,
    SpawnSyntheticTraderCommand,
    StrategyEngine,
)


def market_value_import_handler(service):
    def execute(payload: Mapping[str, Any]) -> JobExecutionResult:
        result = service.import_transfermarkt_csv(
            valuations_csv_path=Path(str(payload["valuations_csv"])),
            players_csv_path=None if not payload.get("players_csv") else Path(str(payload["players_csv"])),
            source=str(payload.get("source", "transfermarkt_csv")),
            currency=str(payload.get("currency", "EUR")),
        )
        return JobExecutionResult(
            JobType.IMPORT_MARKET_VALUES, datetime.now(UTC), result.matched_rows,
            result.ambiguous_rows + result.unmatched_rows, result.rejected_rows,
            metrics={"batch_id": str(result.batch_id), "imported_rows": result.imported_rows,
                     "ambiguous_rows": result.ambiguous_rows, "unmatched_rows": result.unmatched_rows},
        )
    return execute


def seed_player_shares_handler(client):
    def execute(_: Mapping[str, Any]) -> JobExecutionResult:
        result = client.seed_player_shares()
        return JobExecutionResult(
            JobType.SEED_PLAYER_SHARES, datetime.now(UTC), result.created_count,
            result.skipped_existing_count, 0,
            metrics={"market_value_priced": result.market_value_priced_count,
                     "fallback_priced": result.fallback_priced_count},
        )
    return execute


def spawn_traders_handler(spawner):
    def execute(payload: Mapping[str, Any]) -> JobExecutionResult:
        result = spawner.spawn(SpawnSyntheticTraderCommand(
            count=int(payload["count"]),
            config_key=str(payload["config_key"]) if payload.get("config_key") else None,
            strategy_engine=StrategyEngine(str(payload["strategy_engine"])) if payload.get("strategy_engine") else None,
            name_style=SpawnNameStyle(str(payload.get("name_style", "PERSONA"))),
            handle_prefix=str(payload["handle_prefix"]) if payload.get("handle_prefix") else None,
            display_name_prefix=str(payload["display_name_prefix"]) if payload.get("display_name_prefix") else None,
            random_seed=int(payload["random_seed"]) if payload.get("random_seed") is not None else None,
            start_index=int(payload.get("start_index", 1)),
            status=BotStatus(str(payload.get("status", "ACTIVE"))),
        ))
        return JobExecutionResult(
            JobType.SPAWN_SYNTHETIC_TRADERS, datetime.now(UTC), result.spawned_count,
            result.requested_count - result.spawned_count, 0,
            metrics={"requested_count": result.requested_count, "config_key": result.config_key},
        )
    return execute


def bootstrap_portfolios_handler(service):
    def execute(payload: Mapping[str, Any]) -> JobExecutionResult:
        dry_run = bool(payload.get("dry_run", True))
        result = service.bootstrap(
            bot_ids=tuple(UUID(str(value)) for value in payload.get("bot_ids", ())),
            all_active_synthetic_bots=bool(payload.get("all_active_synthetic_bots", False)),
            seed=int(payload["seed"]) if payload.get("seed") is not None else None,
            min_holders_per_player=int(payload.get("min_holders_per_player", 3)),
            max_player_supply_per_bot=Decimal(str(payload.get("max_player_supply_per_bot", 20))),
            reserve_supply_percent=Decimal(str(payload.get("reserve_supply_percent", 10))),
            max_positions_per_bot=int(payload.get("max_positions_per_bot", 100)),
            top_player_holder_percent=Decimal(str(payload.get("top_player_holder_percent", 40))),
            target_seed_value_per_bot=Decimal(
                str(payload.get("target_seed_value_per_bot", 250000))
            ),
            seed_value_jitter_percent=Decimal(str(payload.get("seed_value_jitter_percent", 25))),
            holder_price_exponent=float(payload.get("holder_price_exponent", 1.0)),
            risk_limit_headroom_percent=Decimal(
                str(payload.get("risk_limit_headroom_percent", 75))
            ),
            dry_run=dry_run,
        )
        projected_positions = result.created_positions
        return JobExecutionResult(
            JobType.BOOTSTRAP_SYNTHETIC_PORTFOLIOS, datetime.now(UTC),
            0 if dry_run else projected_positions,
            len(result.skipped_instruments), 0,
            metrics={"seed": result.seed, "bots": len(result.selected_bot_ids),
                     "instruments": result.instruments_processed, "bot_shares": result.bot_shares,
                     "reserve_shares": result.reserve_shares, "dry_run": dry_run,
                     "total_bot_cash": str(result.total_bot_cash),
                     "average_bot_cash": str(result.average_bot_cash),
                     "projected_positions": projected_positions,
                     "bot_positions": result.bot_positions,
                     "reserve_positions": result.reserve_positions,
                     "distribution": result.bot_distribution(),
                     "holders_by_price_quintile": result.holders_by_price_quintile(),
                     "skipped_instruments": [
                         {"symbol": symbol, "reason": reason}
                         for symbol, reason in result.skipped_instruments[:25]
                     ]},
        )
    return execute


def set_bot_status_handler(repository):
    def execute(payload: Mapping[str, Any]) -> JobExecutionResult:
        bot_ids = tuple(UUID(str(value)) for value in payload.get("bot_ids", ()))
        count = repository.set_bot_status(bot_ids, BotStatus(str(payload["status"])))
        return JobExecutionResult(
            JobType.SET_SYNTHETIC_TRADER_STATUS, datetime.now(UTC), count,
            len(bot_ids) - count, 0, metrics={"status": str(payload["status"])},
        )
    return execute


def league_roster_handler(service):
    def execute(payload: Mapping[str, Any]) -> JobExecutionResult:
        request = IngestPlayersJobPayload.from_payload(payload)
        result = service.sync(request.league, request.season)
        return JobExecutionResult(
            JobType.SYNC_LEAGUE_ROSTER, datetime.now(UTC),
            result.halted + result.released + result.instruments_created,
            0 if result.skipped_reason is None else 1,
            len(result.failures),
            metrics={"season": result.season, "fetched_players": result.fetched_players,
                     "clubs_seen": result.clubs_seen,
                     "instruments_created": result.instruments_created,
                     "halted": result.halted, "released": result.released,
                     "skipped_reason": result.skipped_reason,
                     "failures": list(result.failures[:25])},
        )
    return execute
