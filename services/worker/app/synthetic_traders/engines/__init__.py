from __future__ import annotations

from random import Random

from app.synthetic_traders.models import StrategyEngine

from .base import StrategyEngineImplementation
from .market_momentum import MarketMomentumStrategyEngine
from .noise import NoiseStrategyEngine
from .portfolio_rebalancer import PortfolioRebalancerStrategyEngine
from .social_sentiment import SocialSentimentStrategyEngine
from .stats_value import StatsValueStrategyEngine


def default_engine_registry(
    random_source: Random | None = None,
) -> dict[StrategyEngine, StrategyEngineImplementation]:
    return {
        StrategyEngine.NOISE: NoiseStrategyEngine(
            random_source=random_source or Random()
        ),
        StrategyEngine.MARKET_MOMENTUM: MarketMomentumStrategyEngine(),
        StrategyEngine.STATS_VALUE: StatsValueStrategyEngine(),
        StrategyEngine.SOCIAL_SENTIMENT: SocialSentimentStrategyEngine(),
        StrategyEngine.PORTFOLIO_REBALANCER: PortfolioRebalancerStrategyEngine(),
    }


__all__ = [
    "MarketMomentumStrategyEngine",
    "NoiseStrategyEngine",
    "PortfolioRebalancerStrategyEngine",
    "SocialSentimentStrategyEngine",
    "StatsValueStrategyEngine",
    "StrategyEngineImplementation",
    "default_engine_registry",
]
