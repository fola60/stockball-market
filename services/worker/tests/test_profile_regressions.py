"""Behavioral regressions from the engine profile review, using the shipped seed configs."""

import json
import re
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from random import Random
from types import SimpleNamespace
from uuid import UUID

import pytest

import tests.test_synthetic_trader_engines as engine_fixtures
from app.clients.trading_engine import OrderQuoteRecord, OrderSide, TradingEngineClientError
from app.player_stats import SeasonTotals, build_profile
from app.scheduler.social import DueSocialSubscriptionDispatcher
from app.synthetic_traders.config import parse_strategy_config
from app.synthetic_traders.engines import default_engine_registry
from app.synthetic_traders.engines.base import filter_candidates, rank_percentiles
from app.synthetic_traders.engines.betting_market_value import _normalized_probability
from app.synthetic_traders.models import (
    BettingMarketContext,
    BotPositionContext,
    DecisionSide,
    PlayerStatsContext,
    SocialSignalContext,
    StrategyDecision,
    StrategyEngine,
)
from app.synthetic_traders.repository import PostgresSyntheticTraderRepository, _average_cost
from app.synthetic_traders.service import SyntheticTraderService
from tests.test_synthetic_trader_engines import (
    _betting_context,
    _candidate,
    _context,
)
from tests.test_synthetic_trader_repository import SequencedCursor


@pytest.fixture
def configs():
    root = Path(__file__).resolve().parents[3]
    result = {}
    for name in (
        "0007_synthetic_trader_config_seeds.sql",
        "0011_betting_market_trader_profiles.sql",
    ):
        source = (root / "infra/postgres/migrations" / name).read_text()
        for key, engine, blob in re.findall(
            r"\(\s*'([^']+)',\s*'[^']+',\s*'([^']+)',\s*1,\s*\$\$(.*?)\$\$::jsonb", source, re.S
        ):
            result[key] = parse_strategy_config(StrategyEngine(engine), json.loads(blob))
    assert len(result) == 10
    return result


@pytest.fixture
def context():
    t = engine_fixtures.SyntheticTraderEngineTests()
    t.setUp()
    c = _candidate(current_price=D("20"), recent_price_values=(D("20"),) * 3, recent_trade_sides=())
    return _context(t.bot, candidates=(c,))


def evaluate(context, config, engine):
    return default_engine_registry(Random(42))[engine].evaluate(context, config)


def decision(candidate, side=DecisionSide.BUY, pct=0.02, reason=None):
    return StrategyDecision(candidate.instrument_id, side, 0.9, 0.2, 0.9, pct, reason or {})


def funded(context, count=10, cash=D("700"), equity=D("10000")):
    value = (equity - cash) / count
    cs = tuple(
        replace(
            context.candidates[0],
            instrument_id=UUID(int=i + 1),
            club=str(i),
            current_price=D("1"),
            current_holding_quantity=value,
            current_holding_value=value,
        )
        for i in range(count)
    )
    positions = tuple(
        BotPositionContext(c.instrument_id, c.player_id, c.club, value, D("1"), value) for c in cs
    )
    return replace(
        context,
        candidates=cs,
        portfolio=replace(
            context.portfolio,
            cash_balance=cash,
            total_position_value=equity - cash,
            total_equity=equity,
            positions=positions,
        ),
    )


def test_percentiles_are_neutral_for_ties_and_singletons():
    assert rank_percentiles({"a": 0, "b": 0, "c": 0}) == dict.fromkeys(("a", "b", "c"), 0.5)
    assert rank_percentiles({"a": 7}) == {"a": 0.5}
    assert rank_percentiles({"a": 1, "b": 1, "c": 2}) == {"a": 0.25, "b": 0.25, "c": 1}


def test_candidate_sampling_is_reproducible_diverse_and_keeps_discovery(context, configs):
    cs = tuple(
        replace(
            context.candidates[0],
            instrument_id=UUID(int=i + 1),
            current_price=D(i + 1),
            current_holding_quantity=D(1) if i < 30 else D(0),
        )
        for i in range(100)
    )
    universe = replace(configs["NOISE_RETAIL_BUYER"].universe, max_candidates=10)
    a = filter_candidates(cs, universe, "bot-a:day1")
    assert a == filter_candidates(tuple(reversed(cs)), universe, "bot-a:day1")
    assert a != filter_candidates(cs, universe, "bot-b:day1")
    assert any(c.current_holding_quantity == 0 for c in a)
    assert sum(c.current_holding_quantity > 0 for c in a) >= 5


@pytest.mark.parametrize("key", ["NOISE_RETAIL_BUYER", "NOISE_RETAIL_SELLER"])
def test_activity_floor_cannot_reverse_noise_direction(context, configs, key):
    ctx = funded(context)
    cfg = configs[key]
    boosted = replace(cfg, randomness=replace(cfg.randomness, activity_floor_weight=0.65))
    plain = evaluate(ctx, cfg, StrategyEngine.NOISE)
    active = evaluate(ctx, boosted, StrategyEngine.NOISE)
    assert [(d.side, d.alpha_score) for d in plain] == [(d.side, d.alpha_score) for d in active]


def test_probability_is_per_tick_not_per_candidate(context, configs):
    cfg = configs["NOISE_RETAIL_BUYER"]
    cfg = replace(
        cfg,
        execution=replace(cfg.execution, trade_probability=0.3, size_noise_pct=0),
        risk=replace(cfg.risk, min_trade_cash_amount=D("1")),
    )

    class Draw:
        def random(self):
            return 0.4

        def uniform(self, a, b):
            return 1

    svc = SyntheticTraderService(None, None, random_source=Draw())
    ctx = replace(
        context,
        candidates=tuple(
            replace(context.candidates[0], instrument_id=UUID(int=i + 1)) for i in range(50)
        ),
    )
    assert (
        svc._build_order_intents(
            context=ctx, strategy_config=cfg, decisions=tuple(decision(c) for c in ctx.candidates)
        )
        == []
    )


def test_recovery_consumes_cash_deficit_once(context, configs):
    ctx = funded(context)
    cfg = configs["PORTFOLIO_REBALANCER"]
    svc = SyntheticTraderService(None, None)
    ds = svc._build_recovery_decisions(context=ctx, strategy_config=cfg, decisions=())
    orders = svc._build_order_intents(context=ctx, strategy_config=cfg, decisions=ds)
    assert sum(o.notional_cash for o in orders) == D("100")
    assert len(orders) == 1


def test_team_recovery_consumes_team_excess_once(context, configs):
    ctx = funded(context, count=10, cash=D("5000"))
    cs = tuple(replace(c, club="shared" if i < 3 else str(i)) for i, c in enumerate(ctx.candidates))
    ps = tuple(replace(p, club=cs[i].club) for i, p in enumerate(ctx.portfolio.positions))
    ctx = replace(ctx, candidates=cs, portfolio=replace(ctx.portfolio, positions=ps))
    cfg = configs["PORTFOLIO_REBALANCER"]
    cfg = replace(cfg, portfolio_targets=replace(cfg.portfolio_targets, max_team_exposure_pct=0.14))
    svc = SyntheticTraderService(None, None)
    ds = svc._build_recovery_decisions(context=ctx, strategy_config=cfg, decisions=())
    orders = svc._build_order_intents(context=ctx, strategy_config=cfg, decisions=ds)
    assert sum(o.notional_cash for o in orders) == D("100")


def test_rebalancer_deploys_cash_above_band_without_alpha(context, configs):
    ctx = replace(
        context,
        portfolio=replace(context.portfolio, cash_balance=D("360"), total_position_value=D("640")),
        candidates=(replace(context.candidates[0], stats=PlayerStatsContext(average_rating=6.5)),),
    )
    assert (
        evaluate(ctx, configs["PORTFOLIO_REBALANCER"], StrategyEngine.PORTFOLIO_REBALANCER)[0].side
        is DecisionSide.BUY
    )


def test_rebalancer_limits_new_positions_but_allows_existing_topups(context, configs):
    ctx = funded(context, count=1, cash=D("9500"))
    cs = ctx.candidates + tuple(
        replace(
            context.candidates[0],
            instrument_id=UUID(int=50 + i),
            club=str(i),
            current_holding_quantity=D(0),
            current_holding_value=D(0),
        )
        for i in range(3)
    )
    ctx = replace(ctx, candidates=cs)
    cfg = configs["PORTFOLIO_REBALANCER"]
    cfg = replace(
        cfg,
        portfolio_targets=replace(cfg.portfolio_targets, max_position_count=2),
        execution=replace(
            cfg.execution, trade_probability=1, size_noise_pct=0, max_orders_per_tick=3
        ),
    )
    svc = SyntheticTraderService(None, None)
    orders = svc._build_order_intents(
        context=ctx, strategy_config=cfg, decisions=tuple(decision(c) for c in cs)
    )
    assert len(orders) == 2
    assert orders[0].instrument_id == cs[0].instrument_id


def test_rebalancer_does_not_buy_and_sell_same_instrument(context, configs):
    ctx = funded(context, count=1, cash=D("9500"))
    cfg = configs["PORTFOLIO_REBALANCER"]
    cfg = replace(cfg, execution=replace(cfg.execution, trade_probability=1, size_noise_pct=0))
    svc = SyntheticTraderService(None, None)
    c = ctx.candidates[0]
    orders = svc._build_order_intents(
        context=ctx, strategy_config=cfg, decisions=(decision(c, DecisionSide.SELL), decision(c))
    )
    assert len(orders) == 1


def test_average_cost_survives_sales_and_rebuys():
    events = [
        {"side": "BUY", "quantity": "10", "gross_amount": "100"},
        {"side": "BUY", "quantity": "10", "gross_amount": "300"},
        {"side": "SELL", "quantity": "10", "gross_amount": "900"},
        {"side": "BUY", "quantity": "10", "gross_amount": "400"},
    ]
    assert _average_cost(events, D("20")) == D("30")
    assert _average_cost(events, D("30")) is None


def test_quote_shrinks_order_to_budget_and_binds_execution(context, configs):
    class Curved:
        def quote_order(self, command):
            q = D(command.quantity)
            cost = 20 * q + q * q
            return OrderQuoteRecord(
                str(q), str(cost), str(1000 - cost), str(q), "20", str(20 + 2 * q)
            )

    svc = SyntheticTraderService(None, Curved())
    cfg = configs["NOISE_RETAIL_BUYER"]
    cfg = replace(cfg, execution=replace(cfg.execution, trade_probability=1, size_noise_pct=0))
    order = svc._build_order_intents(
        context=context, strategy_config=cfg, decisions=(decision(context.candidates[0]),)
    )[0]
    fitted = svc._fit_quoted_intent(context, cfg, order)
    assert fitted and fitted.notional_cash <= order.notional_cash
    assert fitted.quantity < order.quantity
    assert fitted.execution_limits["expected_price"] == "20"
    assert D(fitted.execution_limits["expected_cash_balance"]) == 1000


def test_failed_sell_cannot_fund_a_later_buy(context, configs):
    ctx = funded(context, count=1, cash=D("0"))
    new = replace(context.candidates[0], instrument_id=UUID(int=50))
    ctx = replace(ctx, candidates=ctx.candidates + (new,))
    cfg = configs["PORTFOLIO_REBALANCER"]
    cfg = replace(cfg, execution=replace(cfg.execution, trade_probability=1, size_noise_pct=0))

    class Rejecting:
        commands = []

        def quote_order(self, command):
            raise TradingEngineClientError(409, {"code": "instrument_frozen"})

        def execute_order(self, command):
            self.commands.append(command)

    repo = SimpleNamespace(
        load_portfolio_context=lambda bot: ctx.portfolio,
        load_activity_context=lambda bot, as_of: ctx.activity,
    )
    svc = SyntheticTraderService(repo, Rejecting())
    # Explicitly hand it both intents to exercise execution-time revalidation after failure.
    sell = svc._build_order_intents(
        context=ctx,
        strategy_config=cfg,
        decisions=(decision(ctx.candidates[0], DecisionSide.SELL),),
    )[0]
    buy = replace(sell, instrument_id=new.instrument_id, side=OrderSide.BUY, reason={})
    outcomes = svc._submit_intents(ctx, [sell, buy], cfg)
    assert [o.status.value for o in outcomes] == ["FAILED", "SKIPPED"]
    assert not svc.trading_engine_client.commands


def test_missing_stat_family_retains_prior_and_observed_zero_is_evidence():
    missing = SeasonTotals.from_tables({"standard": [{"games": 10, "minutes": 900}]})
    observed = SeasonTotals.from_tables(
        {"standard": [{"games": 10, "minutes": 900}], "shooting": [{"shots": 0}]}
    )
    assert build_profile(2026, missing, {"shots": 2}).shots_per90 == 2
    assert build_profile(2026, observed, {"shots": 2}).shots_per90 < 2
    assert "shots" not in build_profile(2026, missing, {}).available_rates


def test_key_pass_score_is_monotonic_including_zero(context, configs):
    engine = default_engine_registry()[StrategyEngine.STATS_VALUE]
    c = context.candidates[0]
    stats = PlayerStatsContext(
        games=10,
        minutes_per_game=90,
        goals_per90=0.5,
        assists_per90=0.3,
        shots_per90=3,
        defensive_actions_per90=3,
    )
    scores = [
        engine._performance_score(
            replace(c, stats=replace(stats, key_passes_per90=k)),
            configs["STATS_VALUE_CONSERVATIVE"],
        )
        for k in [0, 0.01, 0.5, 2]
    ]
    assert scores == sorted(scores)


def test_existing_stats_profiles_have_form_and_stale_data_is_excluded(context, configs):
    cfg = configs["STATS_VALUE_CONSERVATIVE"]
    assert cfg.stats_inputs.form_weight == 0.1
    c = replace(
        context.candidates[0],
        stats=PlayerStatsContext(games=10, latest_observed_at=context.as_of - timedelta(days=31)),
    )
    assert evaluate(replace(context, candidates=(c,)), cfg, StrategyEngine.STATS_VALUE) == ()


def test_repository_cold_start_social_signal_has_no_invented_spike(context):
    cursor = SequencedCursor(
        [
            [
                dict(
                    player_id=str(context.candidates[0].player_id),
                    lookback_seconds=3600,
                    trusted_mention_count=6,
                    mention_velocity=6,
                    credibility_weighted_sentiment=0.8,
                    injury_confirmation_count=0,
                    corroborating_source_count=3,
                    signal_confidence=0.9,
                    calculated_at=context.as_of,
                )
            ],
            [],
        ]
    )
    repo = PostgresSyntheticTraderRepository("unused", social_signals_enabled=True)
    signal = next(
        iter(
            repo._load_social(
                cursor, [str(context.candidates[0].player_id)], context.as_of
            ).values()
        )
    )
    assert signal.mention_spike_zscore == 0
    assert not signal.baseline_available


def test_scheduler_creates_long_and_short_social_windows(context):
    jobs = []
    dispatcher = DueSocialSubscriptionDispatcher(
        SimpleNamespace(list_due_subscriptions=lambda *a, **k: ()),
        SimpleNamespace(enqueue=jobs.append),
        SimpleNamespace(claim=lambda *a: True),
    )
    dispatcher.dispatch_due(context.as_of.replace(minute=0))
    windows = [j.payload["lookback_seconds"] for j in jobs if "lookback_seconds" in j.payload]
    assert windows == [7 * 24 * 3600, 3600]


def test_contrarian_can_buy_recovery_sell_hype_and_avoid_injury(context, configs):
    cfg = configs["SOCIAL_CONTRARIAN"]
    c = replace(
        context.candidates[0],
        current_holding_quantity=D("1"),
        current_holding_value=D("20"),
        stats=PlayerStatsContext(games=10, strength=1),
        social=SocialSignalContext(
            mention_count=20,
            news_count=3,
            trusted_news_count=3,
            source_credibility=1,
            sentiment_score=-1,
        ),
    )
    assert (
        evaluate(replace(context, candidates=(c,)), cfg, StrategyEngine.SOCIAL_SENTIMENT)[0].side
        is DecisionSide.BUY
    )
    injured = replace(c, social=replace(c.social, injury_count=2))
    assert (
        evaluate(replace(context, candidates=(injured,)), cfg, StrategyEngine.SOCIAL_SENTIMENT)[
            0
        ].side
        is not DecisionSide.BUY
    )
    hype = replace(c, current_price=D("24"), social=replace(c.social, sentiment_score=1))
    assert (
        evaluate(replace(context, candidates=(hype,)), cfg, StrategyEngine.SOCIAL_SENTIMENT)[0].side
        is DecisionSide.SELL
    )


def test_social_without_baseline_holds_even_with_positive_news(context, configs):
    c = replace(
        context.candidates[0],
        social=SocialSignalContext(
            baseline_available=False,
            mention_count=20,
            mention_velocity=1,
            mention_spike_zscore=10,
            sentiment_score=1,
            news_count=3,
            trusted_news_count=3,
            source_credibility=1,
        ),
    )
    assert (
        evaluate(
            replace(context, candidates=(c,)),
            configs["SOCIAL_HYPE_CHASER"],
            StrategyEngine.SOCIAL_SENTIMENT,
        )[0].side
        is DecisionSide.HOLD
    )


def test_momentum_requires_recent_liquidity_and_counts_buyers(context, configs):
    cfg = configs["MARKET_MOMENTUM_TRADER"]
    c = _candidate(recent_trade_sides=(OrderSide.SELL,) * 4)
    c = replace(
        c,
        recent_trades=tuple(
            replace(t, executed_at=context.as_of - timedelta(days=10)) for t in c.recent_trades
        ),
    )
    assert evaluate(replace(context, candidates=(c,)), cfg, StrategyEngine.MARKET_MOMENTUM) == ()
    c = replace(
        c, recent_trades=tuple(replace(t, executed_at=context.as_of) for t in c.recent_trades)
    )
    assert (
        evaluate(replace(context, candidates=(c,)), cfg, StrategyEngine.MARKET_MOMENTUM)[0].reason[
            "unique_participation"
        ]
        == 0
    )


def betting_candidates(context):
    return tuple(
        replace(
            context.candidates[0],
            instrument_id=UUID(int=i + 1),
            reference_price=D("20"),
            betting=_betting_context(
                context.as_of, current_probabilities=now, previous_probabilities=old
            ),
        )
        for i, (now, old) in enumerate(
            [((D(".7"), D(".8")), (D(".5"), D(".6"))), ((D(".2"), D(".3")), (D(".3"), D(".4")))]
        )
    )


def test_betting_price_changes_value_and_correlated_markets_count_once(context, configs):
    a, b = betting_candidates(context)
    cfg = configs["BETTING_MARKET_AGGRESSIVE"]
    ds = evaluate(replace(context, candidates=(a, b)), cfg, StrategyEngine.BETTING_MARKET_VALUE)
    winner = next(d for d in ds if d.instrument_id == a.instrument_id)
    assert winner.side is DecisionSide.BUY
    assert winner.reason["independent_market_families"] == 1
    a = replace(a, current_price=D("2000"))
    ds = evaluate(replace(context, candidates=(a, b)), cfg, StrategyEngine.BETTING_MARKET_VALUE)
    assert next(d for d in ds if d.instrument_id == a.instrument_id).side is not DecisionSide.BUY


@pytest.mark.parametrize(
    "case", ["one_quote", "same_timestamp", "started", "unknown_kickoff", "wrong_line"]
)
def test_betting_rejects_unusable_evidence(context, configs, case):
    a, b = betting_candidates(context)
    quotes = a.betting.quotes
    if case == "one_quote":
        quotes = tuple(q for q in quotes if q.observed_at == context.as_of)
    if case == "same_timestamp":
        quotes = tuple(replace(q, observed_at=context.as_of) for q in quotes)
    if case == "started":
        quotes = tuple(replace(q, kickoff_at=context.as_of - timedelta(minutes=1)) for q in quotes)
    if case == "unknown_kickoff":
        quotes = tuple(replace(q, kickoff_at=None) for q in quotes)
    if case == "wrong_line":
        quotes = tuple(replace(q, outcome_type="AT_LEAST", line=D("3")) for q in quotes)
    a = replace(a, betting=BettingMarketContext(quotes))
    ds = evaluate(
        replace(context, candidates=(a, b)),
        configs["BETTING_MARKET_AGGRESSIVE"],
        StrategyEngine.BETTING_MARKET_VALUE,
    )
    assert next(d for d in ds if d.instrument_id == a.instrument_id).side is DecisionSide.HOLD


def test_betting_normalizes_only_complementary_outcomes(context):
    q = betting_candidates(context)[0].betting.quotes[0]
    over = replace(q, outcome_type="OVER", line=D(".5"), implied_probability=D(".6"))
    under = replace(over, outcome_type="UNDER", implied_probability=D(".5"))
    assert _normalized_probability(over, [over, under]) == pytest.approx(0.6 / 1.1)


def test_discovery_survives_a_universe_dominated_by_holdings(context, configs):
    held = tuple(
        replace(context.candidates[0], instrument_id=UUID(int=i + 1), current_holding_quantity=D(1))
        for i in range(100)
    )
    new = replace(context.candidates[0], instrument_id=UUID(int=101), current_holding_quantity=D(0))
    universe = replace(configs["NOISE_RETAIL_BUYER"].universe, max_candidates=4)
    assert new in filter_candidates(held + (new,), universe, "bot")


def test_sizing_penalties_reduce_risk_but_concentration_does_not_reduce_sells(context, configs):
    svc = SyntheticTraderService(None, None)
    c = replace(context.candidates[0], current_holding_value=D(100))
    cfg = configs["STATS_VALUE_AGGRESSIVE"]
    cfg = replace(cfg, execution=replace(cfg.execution, size_noise_pct=0))

    def size(side, volatility=0):
        return svc._apply_size_adjustments(
            cfg,
            decision=decision(c, side, reason={"volatility_risk": volatility}),
            candidate=c,
            requested_notional=D(100),
            total_equity=D(1000),
        )

    assert size(DecisionSide.BUY, 1) < size(DecisionSide.BUY) < size(DecisionSide.SELL) == 100
    social = configs["SOCIAL_HYPE_CHASER"]
    social = replace(social, execution=replace(social.execution, size_noise_pct=0))

    def hype_size(hype):
        return svc._apply_size_adjustments(
            social,
            decision=decision(c, reason={"hype_overextension": hype}),
            candidate=c,
            requested_notional=D(100),
            total_equity=D(1000),
        )

    assert hype_size(1) < hype_size(0)


def test_explanations_honor_visibility_and_record_effective_config(context, configs):
    svc = SyntheticTraderService(None, None)
    cfg = configs["NOISE_RETAIL_BUYER"]
    ds = (decision(context.candidates[0], reason={"test_component": 0.3}),) * 3
    assert svc._explanation(cfg, ds) == {}
    cfg = replace(
        cfg,
        explainability=replace(
            cfg.explainability,
            enabled=True,
            record_top_signal_count=1,
            include_raw_component_scores=True,
        ),
    )
    detail = svc._explanation(cfg, ds)
    assert len(detail["decisions"]) == 1
    assert detail["decisions"][0]["components"] == {"test_component": 0.3}
    assert detail["effective_config"]["signal_weights"] == cfg.signal_weights
    cfg = replace(
        cfg, explainability=replace(cfg.explainability, include_raw_component_scores=False)
    )
    assert "components" not in svc._explanation(cfg, ds)["decisions"][0]


def test_stale_candidates_cannot_displace_fresh_stats(context, configs):
    c = context.candidates[0]
    stale = tuple(
        replace(
            c,
            instrument_id=UUID(int=i + 1),
            stats=replace(c.stats, latest_observed_at=context.as_of - timedelta(days=31)),
        )
        for i in range(100)
    )
    fresh = replace(
        c, instrument_id=UUID(int=101), stats=replace(c.stats, latest_observed_at=context.as_of)
    )
    cfg = configs["STATS_VALUE_AGGRESSIVE"]
    cfg = replace(cfg, universe=replace(cfg.universe, max_candidates=1))
    ds = evaluate(replace(context, candidates=stale + (fresh,)), cfg, StrategyEngine.STATS_VALUE)
    assert [d.instrument_id for d in ds] == [fresh.instrument_id]


def test_sampled_stats_styles_change_actual_buy_selection(context, configs):
    from dataclasses import asdict

    from app.synthetic_traders.config import apply_config_overrides
    from app.synthetic_traders.randomization import build_random_config_overrides

    styles = (
        {"goals_per90": 0.5, "shots_per90": 3},
        {"assists_per90": 0.3, "key_passes_per90": 2},
        {"defensive_actions_per90": 3, "clean_sheets_per_game": 0.45},
    )
    cs = tuple(
        replace(
            context.candidates[0],
            instrument_id=UUID(int=i + 1),
            position="MID",
            club=str(i),
            fixture_score=1,
            stats=PlayerStatsContext(games=20, minutes_per_game=90, **style),
        )
        for i, style in enumerate(styles)
    )
    ctx = replace(context, candidates=cs)
    raw = asdict(configs["STATS_VALUE_AGGRESSIVE"])
    selected = set()
    for seed in range(30):
        overrides = build_random_config_overrides(
            config_key="STATS_VALUE_AGGRESSIVE",
            strategy_engine=StrategyEngine.STATS_VALUE,
            base_config=raw,
            random_source=Random(seed),
        )
        cfg = parse_strategy_config(
            StrategyEngine.STATS_VALUE, apply_config_overrides(raw, overrides)
        )
        # Keep participation certain to isolate persistent taste from timing randomness.
        cfg = replace(cfg, execution=replace(cfg.execution, trade_probability=1, size_noise_pct=0))
        ds = evaluate(ctx, cfg, StrategyEngine.STATS_VALUE)
        orders = SyntheticTraderService(None, None)._build_order_intents(
            context=ctx, strategy_config=cfg, decisions=ds
        )
        selected.update(o.instrument_id for o in orders if o.side is OrderSide.BUY)
    assert len(selected) >= 2


def test_rebalancer_full_exit_setting_is_enforced(context, configs):
    ctx = funded(context, count=1, cash=D("9500"))
    cfg = configs["PORTFOLIO_REBALANCER"]
    cfg = replace(
        cfg,
        execution=replace(cfg.execution, trade_probability=1, size_noise_pct=0),
        risk=replace(cfg.risk, max_trade_cash_pct=1, max_trade_cash_amount=D("10000")),
    )
    svc = SyntheticTraderService(None, None)
    ds = (decision(ctx.candidates[0], DecisionSide.SELL, pct=1),)
    partial = svc._build_order_intents(context=ctx, strategy_config=cfg, decisions=ds)[0]
    cfg = replace(cfg, rebalance_rules=replace(cfg.rebalance_rules, allow_full_exit=True))
    full = svc._build_order_intents(context=ctx, strategy_config=cfg, decisions=ds)[0]
    assert partial.quantity < full.quantity == ctx.portfolio.positions[0].quantity


def test_betting_honors_observation_depth_on_compacted_repository_history(context, configs):
    cs = betting_candidates(context)
    cfg = configs["BETTING_MARKET_AGGRESSIVE"]
    cfg = replace(cfg, betting_inputs=replace(cfg.betting_inputs, min_observations_per_selection=3))
    c = replace(
        cs[0],
        betting=BettingMarketContext(
            tuple(replace(q, observation_count=4) for q in cs[0].betting.quotes)
        ),
    )
    ds = evaluate(
        replace(context, candidates=(c,) + cs[1:]), cfg, StrategyEngine.BETTING_MARKET_VALUE
    )
    result = next(d for d in ds if d.instrument_id == c.instrument_id)
    assert result.reason["market_type_count"] >= cfg.betting_inputs.min_distinct_market_types
