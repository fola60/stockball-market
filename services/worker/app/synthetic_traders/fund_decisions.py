"""Index fund decisions for engines that judge players on football fundamentals.

Stats, social, betting, and match-event engines score players against each other, so a fund
never enters their candidate pool: an "average player" would distort every percentile they
rank on. Instead a fund is judged by the engine's own view of its players, weighted by how
much of a unit's value each one makes up.

Market-data engines (noise, momentum, rebalancing) read only prices, trades, and holdings, so
they trade funds directly as candidates.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from app.synthetic_traders.config_models import AlphaDecisionConfig, CandidateUniverseConfig
from app.synthetic_traders.models import (
    CandidateInstrumentContext,
    StrategyDecision,
    StrategyEngine,
)

from .engines.base import candidate_exclusion_reason, decide_alpha_side

# Engines whose inputs exist for any instrument, so a fund is just another candidate to them.
INDEX_NATIVE_ENGINES = frozenset(
    {
        StrategyEngine.NOISE,
        StrategyEngine.MARKET_MOMENTUM,
        StrategyEngine.PORTFOLIO_REBALANCER,
    }
)
# A fund is judged only once the engine has scored at least this many of its players.
MIN_SCORED_CONSTITUENTS = 3
# Universe rules that apply to a fund. Trade-count and volume floors describe how liquid a
# player's own market is, which a fund inherits from its constituents.
FUND_EXCLUSION_REASONS = frozenset(
    {"inactive_instrument", "club_not_included", "club_excluded", "price_below_minimum"}
)


def index_fund_decisions(
    candidates: Sequence[CandidateInstrumentContext],
    decisions: Sequence[StrategyDecision],
    decision_config: AlphaDecisionConfig,
    universe: CandidateUniverseConfig,
) -> tuple[StrategyDecision, ...]:
    """A decision for each fund, from the value-weighted average of its players' decisions.

    Averaging shrinks alpha toward zero unless the engine agrees about most of a squad, so
    a fund crosses the buy or sell threshold far less often than a single player.
    """
    by_instrument = {decision.instrument_id: decision for decision in decisions}
    prices = {candidate.instrument_id: candidate.current_price for candidate in candidates}
    fund_decisions: list[StrategyDecision] = []
    for fund in candidates:
        if not fund.is_index_fund:
            continue
        if candidate_exclusion_reason(fund, universe) in FUND_EXCLUSION_REASONS:
            continue
        scored = [
            (float(shares_per_unit * prices[instrument_id]), by_instrument[instrument_id])
            for instrument_id, shares_per_unit in fund.index_basket
            if instrument_id in by_instrument and instrument_id in prices
        ]
        total_weight = sum(weight for weight, _ in scored)
        if len(scored) < MIN_SCORED_CONSTITUENTS or total_weight <= 0:
            continue

        def weighted(value_of) -> float:
            return sum(weight * value_of(decision) for weight, decision in scored) / total_weight

        alpha = weighted(lambda decision: decision.alpha_score)
        confidence = weighted(lambda decision: decision.confidence)
        basket_value = sum(
            (
                shares * prices.get(instrument_id, Decimal("0"))
                for instrument_id, shares in fund.index_basket
            ),
            Decimal("0"),
        )
        side = decide_alpha_side(
            alpha,
            confidence,
            buy_threshold=decision_config.buy_threshold,
            sell_threshold=decision_config.sell_threshold,
            min_confidence=decision_config.min_confidence,
            allow_sells=decision_config.allow_sells and fund.current_holding_quantity > 0,
        )
        fund_decisions.append(
            StrategyDecision(
                instrument_id=fund.instrument_id,
                side=side,
                alpha_score=alpha,
                expected_return=weighted(lambda decision: decision.expected_return),
                confidence=confidence,
                suggested_cash_pct=weighted(lambda decision: decision.suggested_cash_pct),
                reason={
                    "engine": "INDEX_FUND_BASKET",
                    "scored_constituents": len(scored),
                    "basket_size": len(fund.index_basket),
                    "scored_value_share": (
                        total_weight / float(basket_value) if basket_value > 0 else 0.0
                    ),
                },
            )
        )
    return tuple(fund_decisions)
