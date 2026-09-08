from __future__ import annotations

from dataclasses import dataclass
from random import Random

from app.clients import ApiClient, CreateSyntheticTraderAccountCommand

from .models import (
    CreateSyntheticTraderBotCommand,
    SpawnedSyntheticTrader,
    SpawnNameStyle,
    SpawnSyntheticTraderBatchResult,
    SpawnSyntheticTraderCommand,
    StrategyEngine,
)
from .names import SpawnedPersonaName, generate_persona_name
from .randomization import build_random_config_overrides
from .repository import SyntheticTraderRepository

DEFAULT_CONFIG_KEY_BY_ENGINE: dict[StrategyEngine, str] = {
    StrategyEngine.NOISE: "NOISE_RETAIL_BUYER",
    StrategyEngine.MARKET_MOMENTUM: "MARKET_MOMENTUM_TRADER",
    StrategyEngine.STATS_VALUE: "STATS_VALUE_CONSERVATIVE",
    StrategyEngine.SOCIAL_SENTIMENT: "SOCIAL_HYPE_CHASER",
    StrategyEngine.PORTFOLIO_REBALANCER: "PORTFOLIO_REBALANCER",
    StrategyEngine.BETTING_MARKET_VALUE: "BETTING_MARKET_CONSERVATIVE",
}


class SyntheticTraderConfigNotFoundError(Exception):
    def __init__(self, config_key: str) -> None:
        self.config_key = config_key
        super().__init__(f"synthetic trader config '{config_key}' was not found or is disabled")


@dataclass(frozen=True)
class SyntheticTraderSpawner:
    api_client: ApiClient
    repository: SyntheticTraderRepository

    def spawn(
        self,
        command: SpawnSyntheticTraderCommand,
    ) -> SpawnSyntheticTraderBatchResult:
        if command.count <= 0:
            raise ValueError("count must be greater than 0")
        if command.start_index <= 0:
            raise ValueError("start_index must be greater than 0")

        config_key = _resolve_config_key(command)
        config = self.repository.get_bot_config_by_key(config_key)
        if config is None:
            raise SyntheticTraderConfigNotFoundError(config_key)

        random_source = Random(command.random_seed)
        spawned: list[SpawnedSyntheticTrader] = []
        used_handles: set[str] = set()
        for offset in range(command.count):
            index = command.start_index + offset
            name = _build_spawn_name(command, index, random_source, used_handles)
            config_overrides = build_random_config_overrides(
                config_key=config.config_key,
                strategy_engine=config.strategy_engine,
                base_config=config.config,
                random_source=random_source,
            )
            account = self.api_client.create_synthetic_trader_account(
                CreateSyntheticTraderAccountCommand(
                    handle=name.handle,
                    display_name=name.display_name,
                )
            )
            bot = self.repository.create_bot(
                CreateSyntheticTraderBotCommand(
                    account_id=account.id,
                    config_id=config.id,
                    bot_key=name.handle,
                    display_name=name.display_name,
                    status=command.status,
                    config_overrides=config_overrides,
                )
            )
            spawned.append(
                SpawnedSyntheticTrader(
                    account_id=account.id,
                    portfolio_id=account.portfolio.id,
                    bot_id=bot.id,
                    config_id=config.id,
                    handle=account.handle,
                    bot_key=bot.bot_key,
                    display_name=bot.display_name,
                )
            )

        return SpawnSyntheticTraderBatchResult(
            config_key=config_key,
            requested_count=command.count,
            spawned=tuple(spawned),
        )


def _resolve_config_key(command: SpawnSyntheticTraderCommand) -> str:
    if command.config_key is not None and command.strategy_engine is not None:
        raise ValueError("specify either config_key or strategy_engine, not both")
    if command.config_key is not None:
        return command.config_key
    if command.strategy_engine is not None:
        return DEFAULT_CONFIG_KEY_BY_ENGINE[command.strategy_engine]
    raise ValueError("config_key or strategy_engine is required")


def _build_spawn_name(
    command: SpawnSyntheticTraderCommand,
    index: int,
    random_source: Random,
    used_handles: set[str],
) -> SpawnedPersonaName:
    if command.name_style is SpawnNameStyle.PERSONA:
        return generate_persona_name(random_source, used_handles)
    if command.name_style is SpawnNameStyle.NUMBERED:
        if command.handle_prefix is None or command.display_name_prefix is None:
            raise ValueError("handle_prefix and display_name_prefix are required for NUMBERED names")
        handle = _numbered_name(command.handle_prefix, index)
        used_handles.add(handle)
        return SpawnedPersonaName(
            handle=handle,
            display_name=_numbered_name(command.display_name_prefix, index),
        )
    raise ValueError(f"unsupported name style: {command.name_style}")


def _numbered_name(prefix: str, index: int) -> str:
    normalized = prefix.strip().rstrip("- ")
    if not normalized:
        raise ValueError("prefix must not be empty")
    separator = "-" if " " not in normalized else " "
    return f"{normalized}{separator}{index:03d}"
