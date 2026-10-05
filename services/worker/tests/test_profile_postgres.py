"""Run against a disposable migrated PostgreSQL DB and a Rust engine pointed at that DB.

Set STOCKBALL_PROFILE_TEST_DATABASE_URL and STOCKBALL_PROFILE_TEST_ENGINE_URL explicitly.
"""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from app.clients.trading_engine import (
    ExecuteOrderCommand,
    HttpTradingEngineClient,
    OrderSide,
    TradingEngineClientError,
)
from app.synthetic_traders.models import DecisionSide, StrategyDecision, StrategyEngine
from app.synthetic_traders.repository import PostgresSyntheticTraderRepository
from app.synthetic_traders.service import SyntheticTraderService

DB = os.getenv("STOCKBALL_PROFILE_TEST_DATABASE_URL")
ENGINE = os.getenv("STOCKBALL_PROFILE_TEST_ENGINE_URL")
pytestmark = pytest.mark.skipif(
    not DB or not ENGINE, reason="requires disposable profile test DB and engine"
)


@pytest.fixture
def market():
    account, portfolio, player, instrument, bot = [uuid4() for _ in range(5)]
    now = datetime.now(UTC)
    club = f"Review FC {player}"
    season = now.year if now.month >= 7 else now.year - 1
    with psycopg2.connect(DB) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts(id,handle,display_name,account_type,status) VALUES (%s,%s,'Review','SYNTHETIC_TRADER','ACTIVE')",
            (str(account), f"review-{account}"),
        )
        cur.execute(
            "INSERT INTO portfolios(id,account_id,cash_balance) VALUES (%s,%s,1000)",
            (str(portfolio), str(account)),
        )
        cur.execute(
            "INSERT INTO players(id,provider,provider_player_id,display_name,club,position) VALUES (%s,'review',%s,'Review Player',%s,'MID')",
            (str(player), str(player), club),
        )
        cur.execute(
            """INSERT INTO instruments(id,instrument_type,player_id,symbol,display_name,current_price,reference_price,shares_outstanding,net_shares_purchased,full_supply_price_multiplier,trading_status)
          VALUES (%s,'PLAYER_SHARE',%s,%s,'Review Share',20,20,1000,0,2.5,'ACTIVE')""",
            (str(instrument), str(player), f"R-{instrument}"),
        )
        cur.execute(
            """INSERT INTO synthetic_trader_bots(id,account_id,config_id,bot_key,display_name,config_overrides)
          SELECT %s,%s,id,%s,'Review Bot',%s FROM synthetic_trader_bot_configs WHERE config_key='NOISE_RETAIL_BUYER'""",
            (
                str(bot),
                str(account),
                str(bot),
                Json({"execution": {"trade_probability": 1, "size_noise_pct": 0}}),
            ),
        )
        cur.execute(
            """INSERT INTO player_season_stat_snapshots(player_id,provider,season,snapshot_date,tables)
          VALUES (%s,'review',%s,%s,%s)""",
            (
                str(player),
                season,
                now.date(),
                Json({"standard": [{"games": 10, "minutes": 900, "goals": 3, "assists": 2}]}),
            ),
        )
        cur.execute(
            """INSERT INTO fixtures(provider,provider_fixture_id,league_provider_id,season,kickoff_at,home_team_provider_id,home_team_name,away_team_provider_id,away_team_name,status_short)
          VALUES ('review',%s,'9',%s,%s,'h',%s,'a','Opponent','NS')""",
            (str(bot), season, now + timedelta(days=3), club),
        )
    repo = PostgresSyntheticTraderRepository(DB)
    client = HttpTradingEngineClient(ENGINE)
    record = repo.list_due_bots(now, bot_ids=(bot,))[0]
    yield repo, client, record, instrument, now
    client.close()


def command(bot, instrument, quantity="1"):
    return ExecuteOrderCommand(
        str(uuid4()), bot.account_id, bot.portfolio_id, instrument, OrderSide.BUY, quantity
    )


def test_worker_quotes_executes_and_reads_real_stats_and_cost_basis(market):
    repo, client, bot, instrument, now = market
    portfolio = repo.load_portfolio_context(bot)
    candidates = repo.load_candidate_instruments(portfolio, now)
    c = next(c for c in candidates if c.instrument_id == instrument)
    assert c.reference_price == 20
    assert c.fixture_score > 0
    assert c.stats.games == 10 and c.stats.latest_observed_at is not None
    assert "shots" not in c.stats.available_rates

    class Engine:
        def evaluate(self, context, config):
            return (StrategyDecision(instrument, DecisionSide.BUY, 0.9, 0.1, 0.9, 0.05, {}),)

    svc = SyntheticTraderService(repo, client, engine_registry={StrategyEngine.NOISE: Engine()})
    result = svc.tick_due_bots(now, bot_ids=(bot.id,))
    assert result.submitted_count == 1
    execution = result.outcomes[0].execution
    # Base profile permits at most 1.5% = 15; actual curve cost respects that budget.
    assert D("10") <= D(execution.gross_amount) <= D("15")
    assert D(execution.execution_price) > D(execution.old_price)
    after = repo.load_portfolio_context(bot)
    position = next(p for p in after.positions if p.instrument_id == instrument)
    expected = float(
        (position.current_price - D(execution.execution_price)) / D(execution.execution_price)
    )
    assert position.unrealized_return_pct == pytest.approx(expected)


@pytest.mark.parametrize("changed", ["price", "cash", "budget"])
def test_engine_enforces_quote_guards_atomically(market, changed):
    repo, client, bot, instrument, now = market
    cmd = command(bot, instrument)
    quote = client.quote_order(cmd)
    assert repo.load_portfolio_context(bot).cash_balance == 1000
    limits = {
        "expected_price": quote.old_price,
        "expected_cash_balance": "1000",
        "max_gross_amount": quote.gross_amount,
    }
    key = {
        "price": "expected_price",
        "cash": "expected_cash_balance",
        "budget": "max_gross_amount",
    }[changed]
    limits[key] = str(D(limits[key]) - D(".0001"))
    with pytest.raises(TradingEngineClientError) as error:
        client.execute_order(replace(cmd, execution_limits=limits))
    assert error.value.body["code"] == "quote_changed"
    portfolio = repo.load_portfolio_context(bot)
    assert portfolio.cash_balance == 1000 and not portfolio.positions
    with psycopg2.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trades WHERE portfolio_id=%s", (str(bot.portfolio_id),))
        assert cur.fetchone()[0] == 0


def test_guarded_order_remains_idempotent_after_price_changes(market):
    repo, client, bot, instrument, now = market
    cmd = command(bot, instrument)
    quote = client.quote_order(cmd)
    cmd = replace(
        cmd,
        execution_limits={
            "expected_price": quote.old_price,
            "expected_cash_balance": "1000",
            "max_gross_amount": quote.gross_amount,
        },
    )
    first = client.execute_order(cmd)
    duplicate = client.execute_order(cmd)
    assert first.trade_id == duplicate.trade_id
    assert repo.load_portfolio_context(bot).cash_balance == D(first.cash_balance_after)


def test_profile_migration_preserves_explicit_form_and_supported_overrides(market):
    from pathlib import Path

    from app.synthetic_traders.config import apply_config_overrides, parse_strategy_config

    _, _, bot, _, _ = market
    migration = (
        Path(__file__).resolve().parents[3]
        / "infra/postgres/migrations/0029_synthetic_profile_corrections.sql"
    )
    conn = psycopg2.connect(DB)
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE synthetic_trader_bot_configs SET config=jsonb_set(config,
                '{stats_inputs,form_weight}', '0') WHERE config_key='STATS_VALUE_CONSERVATIVE'""")
            cur.execute(
                """UPDATE synthetic_trader_bots SET config_id=(SELECT id FROM
                synthetic_trader_bot_configs WHERE config_key='SOCIAL_CONTRARIAN'),
                config_overrides=%s WHERE id=%s""",
                (
                    Json(
                        {
                            "signal_weights": {"mention_spike": -0.7, "pessimism_recovery": 0.8},
                            "lookbacks": {"news_window_hours": 24},
                            "execution": {"trade_probability": 0.42},
                        }
                    ),
                    str(bot.id),
                ),
            )
            cur.execute(migration.read_text())
            cur.execute(
                "SELECT config_key,strategy_engine,config FROM synthetic_trader_bot_configs"
            )
            rows = cur.fetchall()
            assert len(rows) == 10
            for key, engine, payload in rows:
                cfg = parse_strategy_config(StrategyEngine(engine), payload)
                if key == "STATS_VALUE_CONSERVATIVE":
                    assert cfg.stats_inputs.form_weight == 0
                if engine == "BETTING_MARKET_VALUE":
                    assert cfg.betting_inputs.min_observations_per_selection >= 2
            cur.execute(
                "SELECT config_overrides FROM synthetic_trader_bots WHERE id=%s", (str(bot.id),)
            )
            overrides = cur.fetchone()[0]
            assert overrides["signal_weights"] == {"pessimism_recovery": 0.8}
            assert overrides["execution"]["trade_probability"] == 0.42
            assert "news_window_hours" not in overrides["lookbacks"]
            base = next(payload for key, _, payload in rows if key == "SOCIAL_CONTRARIAN")
            cfg = parse_strategy_config(
                StrategyEngine.SOCIAL_SENTIMENT, apply_config_overrides(base, overrides)
            )
            assert cfg.signal_weights["pessimism_recovery"] == 0.8
    finally:
        conn.rollback()
        conn.close()


def test_newer_social_baseline_cannot_replace_current_hour(market):
    from psycopg2.extras import RealDictCursor

    _, _, bot, instrument, now = market
    repo = PostgresSyntheticTraderRepository(DB, social_signals_enabled=True)
    with psycopg2.connect(DB) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT player_id FROM instruments WHERE id=%s", (str(instrument),))
        player = str(cur.fetchone()["player_id"])
        for seconds, count, timestamp in (
            (3600, 6, now - timedelta(seconds=1)),
            (604800, 168, now),
        ):
            cur.execute(
                """INSERT INTO player_social_signal_snapshots
                (player_id,calculated_at,lookback_seconds,trusted_mention_count,
                credibility_weighted_sentiment,injury_confirmation_count,mention_velocity,
                corroborating_source_count,signal_confidence,signal_age_seconds)
                VALUES (%s,%s,%s,%s,.5,0,1,2,.8,0)""",
                (player, timestamp, seconds, count),
            )
        signal = repo._load_social(cur, [player], now)[player]
        assert signal.mention_count == 6
        assert signal.baseline_available
        assert signal.mention_spike_zscore > 0
