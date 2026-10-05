from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.synthetic_traders.config import SocialSentimentConfig
from app.synthetic_traders.models import (
    BotTickContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import clamp, filter_candidates, price_change_pct, sorted_decisions
from .base import stats_confirmation as shared_stats_confirmation

# Independent sources covering a player before news reads as a full-strength signal.
NEWS_SOURCES_FOR_FULL_SIGNAL = 3.0
# Confirmed injury reports before injury risk is at full strength.
INJURY_REPORTS_FOR_FULL_RISK = 2.0


@dataclass(frozen=True)
class SocialSentimentStrategyEngine:
    strategy_engine: StrategyEngine = StrategyEngine.SOCIAL_SENTIMENT

    def evaluate(
        self,
        context: BotTickContext,
        config: SocialSentimentConfig,
    ) -> tuple[StrategyDecision, ...]:
        candidates = filter_candidates(
            context.candidates, config.universe, f"{context.bot.id}:{context.as_of.date()}"
        )
        if not candidates:
            return ()

        price_window_start = context.as_of - timedelta(hours=config.lookbacks.price_momentum_hours)
        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            social = candidate.social
            mention_spike = clamp(
                social.mention_spike_zscore
                / max(config.social_inputs.mention_spike_zscore_to_trade, 0.1),
                -1.0,
                1.0,
            )
            mention_velocity = clamp(social.mention_velocity, -1.0, 1.0)
            sentiment = clamp(social.sentiment_score, -1.0, 1.0)
            news_velocity = clamp(social.news_count / NEWS_SOURCES_FOR_FULL_SIGNAL, 0.0, 1.0)
            source_credibility = clamp(social.source_credibility, 0.0, 1.0)
            price_momentum = price_change_pct(
                candidate.recent_prices,
                candidate.current_price,
                price_window_start,
            )
            price_momentum_score = clamp(price_momentum / 0.15, -1.0, 1.0)
            stats_confirmation = shared_stats_confirmation(candidate.stats)
            hype_overextension = max(
                social.hype_overextension,
                max(price_momentum_score - max(sentiment, 0.0), 0.0),
            )
            negative_news_risk = 0.0
            if sentiment < config.social_inputs.negative_sentiment_threshold:
                negative_news_risk = abs(sentiment)
            # Confirmed injury reports are bad news whatever the overall sentiment.
            negative_news_risk = max(
                negative_news_risk,
                clamp(social.injury_count / INJURY_REPORTS_FOR_FULL_RISK, 0.0, 1.0),
            )
            credibility = clamp(
                source_credibility
                * (
                    config.social_inputs.trusted_source_multiplier
                    if social.trusted_news_count > 0
                    else config.social_inputs.untrusted_source_multiplier
                ),
                0.0,
                1.0,
            )
            direction = 1.0
            alpha = (
                direction * config.signal_weights.get("mention_spike", 0.0) * mention_spike
                + direction * config.signal_weights.get("mention_velocity", 0.0) * mention_velocity
                + direction * config.signal_weights.get("sentiment", 0.0) * sentiment
                + direction * config.signal_weights.get("news_velocity", 0.0) * news_velocity
                + config.signal_weights.get("source_credibility", 0.0) * sentiment * credibility
                + config.signal_weights.get("stockball_price_momentum", 0.0) * price_momentum_score
                + config.signal_weights.get("stats_confirmation", 0.0) * stats_confirmation
                + config.signal_weights.get("hype_overextension", 0.0) * hype_overextension
                + config.signal_weights.get("negative_news_risk", 0.0) * negative_news_risk
            )
            alpha *= credibility
            if config.social_inputs.contrarian_mode:
                # Buy pessimism only when fundamentals support recovery and price is stabilizing.
                recovery = (
                    max(-sentiment, 0.0)
                    * max(stats_confirmation, 0.0)
                    * (1.0 - max(-price_momentum_score, 0.0))
                )
                fade = max(sentiment, 0.0) * max(price_momentum_score, 0.0)
                alpha = credibility * (
                    config.signal_weights.get("pessimism_recovery", 1.0) * recovery
                    - config.signal_weights.get("hype_fade", 1.0) * fade
                    - max(hype_overextension, 0.0)
                    * abs(config.signal_weights.get("hype_overextension", 0.0))
                )
                alpha -= clamp(social.injury_count / INJURY_REPORTS_FOR_FULL_RISK, 0.0, 1.0)
            signal_presence = 0.0
            if social.mention_count >= config.social_inputs.min_mentions:
                signal_presence += 0.4
            if social.news_count > 0:
                signal_presence += 0.3
            if abs(sentiment) >= config.social_inputs.positive_sentiment_threshold:
                signal_presence += 0.2
            confidence = clamp(signal_presence + min(abs(alpha), 0.3), 0.0, 1.0)
            if not social.baseline_available:
                confidence = min(confidence, 0.3)
            side = DecisionSide.HOLD
            if (
                abs(alpha) > config.decision.hold_band
                and confidence >= config.decision.min_confidence
            ):
                if alpha >= config.decision.buy_threshold:
                    side = DecisionSide.BUY
                elif (
                    config.decision.allow_sells
                    and candidate.current_holding_quantity > 0
                    and alpha <= config.decision.sell_threshold
                ):
                    side = DecisionSide.SELL
            suggested_cash_pct = config.sizing.base_cash_pct * (
                1.0
                + config.sizing.confidence_multiplier * confidence
                + config.sizing.hype_multiplier * max(mention_spike, 0.0)
                + config.sizing.sentiment_multiplier * max(sentiment, 0.0)
            )
            decisions.append(
                StrategyDecision(
                    instrument_id=candidate.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=price_momentum,
                    confidence=confidence,
                    suggested_cash_pct=suggested_cash_pct,
                    reason={
                        "engine": self.strategy_engine.value,
                        "mention_spike": mention_spike,
                        "mention_velocity": mention_velocity,
                        "sentiment": sentiment,
                        "news_velocity": news_velocity,
                        "hype_overextension": hype_overextension,
                        "signal_present": signal_presence > 0,
                        "baseline_available": social.baseline_available,
                        "injury_risk": negative_news_risk,
                        "credibility": credibility,
                    },
                )
            )

        return sorted_decisions(decisions)
