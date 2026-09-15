from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Callable, Mapping, Protocol

from app.ingestion.betting_markets import BettingMarketIngestionService
from app.ingestion.fixtures import FixtureIngestionService
from app.ingestion.players import PlayerSeedService
from app.ingestion.social import (
    ArticleFetcher,
    InvalidSubscription,
    PermanentProviderError,
    PolicyDisabled,
    RateLimited,
    SocialArticleEnrichmentService,
    SocialDocumentProcessor,
    SocialIngestionService,
    SocialProcessingService,
    SocialProvider,
    SocialSignalAggregationService,
    TransientProviderError,
)
from app.ingestion.social.repository import PostgresSocialRepository
from app.ingestion.social.twitter import TwitterInjuryIngestionService, TwitterTransientError
from app.ingestion.stats import PlayerStatsIngestionService
from app.jobs.models import (
    AggregateSocialSignalsJobPayload,
    Bet365IngestionMode,
    IngestBet365OddsJobPayload,
    IngestFixturesJobPayload,
    IngestPlayersJobPayload,
    IngestPlayerStatsJobPayload,
    IngestSocialFeedsJobPayload,
    IngestSocialSourceJobPayload,
    IngestTwitterInjuriesJobPayload,
    JobExecutionResult,
    JobType,
    ProcessSocialDocumentsJobPayload,
    SyntheticTraderTickJobPayload,
    TopupJobPayload,
    WorkerJob,
)
from app.synthetic_traders import (
    SyntheticTraderService,
    SyntheticTraderTickBatchResult,
    SyntheticTraderTickDiagnostics,
)
from app.topups import TopupCadence, TopupOutcomeStatus, TopupService


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobHandler(Protocol):
    def handle(self, job: WorkerJob) -> JobExecutionResult: ...


@dataclass(frozen=True)
class FunctionJobHandler:
    job_type: JobType
    execute: Callable[[Mapping[str, object]], JobExecutionResult]

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not self.job_type:
            raise UnknownJobError(f"handler cannot process {job.job_type.value}")
        return self.execute(job.payload)


class UnknownJobError(Exception):
    pass


class RetryableJobError(Exception):
    def __init__(self, message: str, result: JobExecutionResult) -> None:
        self.result = result
        super().__init__(message)


class SyntheticTopupPolicyProvisioner(Protocol):
    def ensure_active_synthetic_trader_policies(
        self, cadence: TopupCadence, amount: str
    ) -> int: ...


@dataclass(frozen=True)
class TopupJobHandler:
    topup_service: TopupService
    synthetic_policy_provisioner: SyntheticTopupPolicyProvisioner | None = None
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.APPLY_TOPUPS:
            raise UnknownJobError(f"top-up handler cannot process {job.job_type.value}")

        payload = TopupJobPayload.from_payload(job.payload)
        configured_policies = 0
        if payload.synthetic_trader_amount is not None:
            if self.synthetic_policy_provisioner is None:
                raise RuntimeError("synthetic top-up policy provisioner is not configured")
            configured_policies = (
                self.synthetic_policy_provisioner.ensure_active_synthetic_trader_policies(
                    payload.cadence, payload.synthetic_trader_amount
                )
            )
        result = self.topup_service.apply_topups(payload.cadence, payload.effective_at)
        credited_amount = sum(
            Decimal(outcome.amount)
            for outcome in result.outcomes
            if outcome.status is TopupOutcomeStatus.APPLIED
        )
        job_result = JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.applied_count,
            skipped_items=result.skipped_count,
            failed_items=result.failed_count,
            retryable_failures=result.retryable_failure_count,
            metrics={
                "cadence": payload.cadence.value,
                "window": result.window.key,
                "configured_policies": configured_policies,
                "credited_amount": str(credited_amount),
                "amount_per_synthetic_trader": payload.synthetic_trader_amount,
            },
        )
        if result.has_retryable_failures:
            raise RetryableJobError(
                "top-up job encountered retryable trading-engine failures",
                job_result,
            )
        return job_result


@dataclass(frozen=True)
class SyntheticTraderTickJobHandler:
    synthetic_trader_service: SyntheticTraderService
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.SYNTHETIC_TRADER_TICK:
            raise UnknownJobError(
                f"synthetic-trader handler cannot process {job.job_type.value}"
            )

        payload = SyntheticTraderTickJobPayload.from_payload(job.payload)
        results = [
            self.synthetic_trader_service.tick_due_bots(
                payload.effective_at + timedelta(microseconds=iteration),
                limit=500 if payload.force_timing else 100,
                force_timing=payload.force_timing,
                bot_ids=payload.bot_ids,
            )
            for iteration in range(payload.tick_count)
        ]
        diagnostics = _aggregate_tick_diagnostics(results)
        execution_failures = _aggregate_execution_failures(results)
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=sum(result.submitted_count for result in results),
            skipped_items=sum(result.skipped_count for result in results),
            failed_items=sum(result.failed_count for result in results),
            metrics={
                "processed_bots": sum(result.processed_bots for result in results),
                "forced": payload.force_timing,
                "targeted_bots": len(payload.bot_ids) if payload.bot_ids else "ALL_ACTIVE",
                "ticks_requested": payload.tick_count,
                "ticks_completed": len(results),
                "decision_diagnostics": diagnostics,
                "execution_failures": execution_failures,
                "failed_order_samples": _failed_order_samples(results),
                "tick_diagnostics": [
                    {
                        "tick": index + 1,
                        **_summarize_tick_diagnostics(result.diagnostics, include_profiles=False),
                    }
                    for index, result in enumerate(results)
                ],
            },
        )


def _aggregate_tick_diagnostics(
    results: list[SyntheticTraderTickBatchResult],
) -> dict[str, object]:
    return _summarize_tick_diagnostics(
        tuple(diagnostic for result in results for diagnostic in result.diagnostics),
        include_profiles=True,
    )


def _summarize_tick_diagnostics(
    diagnostics: tuple[SyntheticTraderTickDiagnostics, ...],
    *,
    include_profiles: bool,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "bots": len(diagnostics),
        "candidates_loaded": sum(item.candidates_loaded for item in diagnostics),
        "candidates_evaluated": sum(item.candidates_evaluated for item in diagnostics),
        "recovery_decisions": sum(item.recovery_decisions for item in diagnostics),
        "recovery_orders": sum(item.recovery_orders for item in diagnostics),
        "decisions": _sum_diagnostic_maps(item.decisions for item in diagnostics),
        "negative_alpha": _sum_diagnostic_maps(item.negative_alpha for item in diagnostics),
        "candidate_exclusions": _sum_diagnostic_maps(
            item.candidate_exclusions for item in diagnostics
        ),
        "rejection_reasons": _sum_diagnostic_maps(
            item.rejection_reasons for item in diagnostics
        ),
    }
    if include_profiles:
        profiles: dict[str, dict[str, object]] = {}
        for strategy_engine in sorted({item.strategy_engine.value for item in diagnostics}):
            profile_diagnostics = tuple(
                item for item in diagnostics if item.strategy_engine.value == strategy_engine
            )
            profiles[strategy_engine] = _summarize_tick_diagnostics(
                profile_diagnostics,
                include_profiles=False,
            )
        summary["by_strategy"] = profiles
    return summary


def _sum_diagnostic_maps(values) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for value in values:
        totals.update(value)
    return dict(sorted(totals.items()))


def _aggregate_execution_failures(
    results: list[SyntheticTraderTickBatchResult],
) -> dict[str, int]:
    failures: Counter[str] = Counter()
    for result in results:
        for outcome in result.outcomes:
            if outcome.status.value != "FAILED":
                continue
            key = outcome.error_code or outcome.message or "unknown_error"
            failures[key] += 1
    return dict(sorted(failures.items()))


def _failed_order_samples(
    results: list[SyntheticTraderTickBatchResult],
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for result in results:
        for outcome in result.outcomes:
            if outcome.status.value != "FAILED" or outcome.request_id is None:
                continue
            samples.append(
                {
                    "request_id": outcome.request_id,
                    "bot_id": str(outcome.bot_id),
                    "instrument_id": (
                        str(outcome.instrument_id) if outcome.instrument_id else None
                    ),
                    "side": outcome.side.value if outcome.side else None,
                    "code": outcome.error_code,
                    "message": outcome.message,
                    "details": outcome.error_details,
                }
            )
            if len(samples) >= limit:
                return samples
    return samples


@dataclass(frozen=True)
class IngestPlayersJobHandler:
    player_seed_service: PlayerSeedService
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_PLAYERS:
            raise UnknownJobError(f"player ingestion handler cannot process {job.job_type.value}")

        payload = IngestPlayersJobPayload.from_payload(job.payload)
        result = self.player_seed_service.seed_players(payload.league, payload.season)
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.upserted_players,
            skipped_items=0,
            failed_items=0,
            metrics={"fetched_players": result.fetched_players, "clubs_seen": result.clubs_seen},
        )


@dataclass(frozen=True)
class IngestFixturesJobHandler:
    fixture_ingestion_service: FixtureIngestionService
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_FIXTURES:
            raise UnknownJobError(f"fixture ingestion handler cannot process {job.job_type.value}")

        payload = IngestFixturesJobPayload.from_payload(job.payload)
        result = self.fixture_ingestion_service.ingest_fixtures(
            league=payload.league,
            season=payload.season,
            from_date=payload.from_date,
            to_date=payload.to_date,
        )
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.upserted_fixtures,
            skipped_items=0,
            failed_items=0,
            metrics={"fetched_fixtures": result.fetched_fixtures},
        )


@dataclass(frozen=True)
class IngestPlayerStatsJobHandler:
    stats_ingestion_service: PlayerStatsIngestionService
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_PLAYER_STATS:
            raise UnknownJobError(
                f"player-stats handler cannot process {job.job_type.value}"
            )

        payload = IngestPlayerStatsJobPayload.from_payload(job.payload)
        result = self.stats_ingestion_service.ingest_player_stats(
            league=payload.league,
            season=payload.season,
            stat_types=payload.stat_types or None,
        )
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.upserted_observations,
            skipped_items=0,
            failed_items=0,
            metrics={"fetched_observations": result.fetched_observations, "matched_players": result.matched_players},
        )


@dataclass(frozen=True)
class IngestBet365OddsJobHandler:
    betting_market_ingestion_service: BettingMarketIngestionService
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_BET365_ODDS:
            raise UnknownJobError(f"Bet365 handler cannot process {job.job_type.value}")
        payload = IngestBet365OddsJobPayload.from_payload(job.payload)
        handled_at = self.clock()
        if payload.mode is Bet365IngestionMode.LIVE:
            result = self.betting_market_ingestion_service.ingest_live_markets(
                payload.effective_at or handled_at
            )
        else:
            result = self.betting_market_ingestion_service.ingest_pre_match_markets(payload.league)
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=handled_at,
            successful_items=result.upserted_observations,
            skipped_items=0,
            failed_items=0,
            metrics={"fetched_observations": result.fetched_observations},
        )


@dataclass(frozen=True)
class IngestTwitterInjuriesJobHandler:
    twitter_injury_ingestion_service: TwitterInjuryIngestionService
    search_query: str
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_TWITTER_INJURIES:
            raise UnknownJobError(f"Twitter injury handler cannot process {job.job_type.value}")
        payload = IngestTwitterInjuriesJobPayload.from_payload(job.payload)
        try:
            result = self.twitter_injury_ingestion_service.ingest_recent(
                self.search_query,
                payload.query_key,
            )
        except TwitterTransientError as error:
            job_result = JobExecutionResult(
                job_type=job.job_type,
                handled_at=self.clock(),
                successful_items=0,
                skipped_items=0,
                failed_items=1,
                retryable_failures=1,
            )
            raise RetryableJobError(str(error), job_result) from error
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.persisted_posts,
            skipped_items=result.skipped_posts + result.ambiguous_posts,
            failed_items=0,
            metrics={
                "fetched_posts": result.fetched_posts,
                "classified_posts": result.classified_posts,
                "resolved_posts": result.resolved_posts,
                "ambiguous_posts": result.ambiguous_posts,
                "episode_updates": result.episode_updates,
                "pages_fetched": result.pages_fetched,
            },
        )


@dataclass(frozen=True)
class IngestSocialSourceJobHandler:
    social_ingestion_service: SocialIngestionService
    clock: Callable[[], datetime] = _utc_now
    repository: PostgresSocialRepository | None = None
    article_fetcher: ArticleFetcher | None = None

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_SOCIAL_SOURCE:
            raise UnknownJobError(f"social ingestion handler cannot process {job.job_type.value}")
        payload = IngestSocialSourceJobPayload.from_payload(job.payload)
        try:
            result = asyncio.run(self.social_ingestion_service.ingest(payload.subscription_id))
        except (RateLimited, TransientProviderError) as error:
            job_result = JobExecutionResult(
                job_type=job.job_type,
                handled_at=self.clock(),
                successful_items=0,
                skipped_items=0,
                failed_items=1,
                retryable_failures=1,
            )
            raise RetryableJobError(str(error), job_result) from error
        except (InvalidSubscription, PolicyDisabled, PermanentProviderError):
            return JobExecutionResult(
                job_type=job.job_type,
                handled_at=self.clock(),
                successful_items=0,
                skipped_items=0,
                failed_items=1,
            )
        metrics: dict[str, object] = {
            "provider": result.provider.value,
            "fetched_documents": result.fetched_documents,
            "duplicate_documents": result.duplicate_documents,
            "immediate_articles_enriched": 0,
            "immediate_article_enrichments_skipped": 0,
            "immediate_article_enrichments_failed": 0,
            "immediate_documents_processed": 0,
            "immediate_processing_failures": 0,
        }
        if self.repository is not None and result.inserted_documents:
            enrichment = SocialArticleEnrichmentService(
                self.repository, self.article_fetcher
            ).enrich_pending(
                limit=result.inserted_documents,
                subscription_id=payload.subscription_id,
            )
            processing = SocialProcessingService(
                self.repository,
                SocialDocumentProcessor(
                    self.repository.list_player_candidates(), self.repository
                ),
            ).process_pending(
                limit=result.inserted_documents,
                subscription_id=payload.subscription_id,
            )
            metrics.update(
                {
                    "immediate_articles_enriched": enrichment.enriched,
                    "immediate_article_enrichments_skipped": enrichment.skipped,
                    "immediate_article_enrichments_failed": enrichment.failed,
                    "immediate_documents_processed": processing.processed,
                    "immediate_processing_failures": processing.failed,
                }
            )
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.inserted_documents,
            skipped_items=result.duplicate_documents,
            failed_items=0,
            metrics=metrics,
        )


@dataclass(frozen=True)
class IngestSocialFeedsJobHandler:
    repository: PostgresSocialRepository
    source_handler: IngestSocialSourceJobHandler
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_SOCIAL_FEEDS:
            raise UnknownJobError(
                f"social feed batch handler cannot process {job.job_type.value}"
            )
        payload = IngestSocialFeedsJobPayload.from_payload(job.payload)
        provider = None if payload.provider == "ALL" else SocialProvider(payload.provider).value
        subscription_ids = self.repository.list_due_subscriptions(
            self.clock(), limit=payload.limit, provider=provider
        )
        totals: Counter[str] = Counter()
        failed_sources = 0
        for subscription_id in subscription_ids:
            result = self.source_handler.handle(
                WorkerJob.ingest_social_source(
                    IngestSocialSourceJobPayload(subscription_id=subscription_id)
                )
            )
            totals["fetched_documents"] += int(result.metrics.get("fetched_documents", 0))
            totals["inserted_documents"] += result.successful_items
            totals["duplicate_documents"] += result.skipped_items
            totals["articles_enriched"] += int(
                result.metrics.get("immediate_articles_enriched", 0)
            )
            totals["article_enrichments_skipped"] += int(
                result.metrics.get("immediate_article_enrichments_skipped", 0)
            )
            totals["article_enrichments_failed"] += int(
                result.metrics.get("immediate_article_enrichments_failed", 0)
            )
            totals["documents_processed"] += int(
                result.metrics.get("immediate_documents_processed", 0)
            )
            totals["processing_failures"] += int(
                result.metrics.get("immediate_processing_failures", 0)
            )
            if result.failed_items:
                failed_sources += 1
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=totals["inserted_documents"],
            skipped_items=totals["duplicate_documents"],
            failed_items=failed_sources + totals["processing_failures"],
            retryable_failures=totals["article_enrichments_failed"],
            metrics={
                "provider": payload.provider,
                "subscription_limit": payload.limit,
                "subscriptions_polled": len(subscription_ids),
                "source_failures": failed_sources,
                **dict(totals),
            },
        )


@dataclass(frozen=True)
class ProcessSocialDocumentsJobHandler:
    repository: PostgresSocialRepository
    clock: Callable[[], datetime] = _utc_now
    article_fetcher: ArticleFetcher | None = None

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.PROCESS_SOCIAL_DOCUMENTS:
            raise UnknownJobError(f"social processing handler cannot process {job.job_type.value}")
        payload = ProcessSocialDocumentsJobPayload.from_payload(job.payload)
        enrichment = SocialArticleEnrichmentService(
            self.repository, self.article_fetcher
        ).enrich_pending(limit=min(payload.limit, 20))
        service = SocialProcessingService(
            self.repository,
            SocialDocumentProcessor(self.repository.list_player_candidates(), self.repository),
        )
        result = service.process_pending(limit=payload.limit)
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.processed,
            skipped_items=0,
            failed_items=result.failed,
            retryable_failures=result.failed,
            metrics={
                "claimed_documents": result.claimed,
                "episode_updates": result.evidence_updates,
                "article_enrichments_claimed": enrichment.claimed,
                "articles_enriched": enrichment.enriched,
                "article_enrichments_skipped": enrichment.skipped,
                "article_enrichments_failed": enrichment.failed,
            },
        )


@dataclass(frozen=True)
class AggregateSocialSignalsJobHandler:
    repository: PostgresSocialRepository
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.AGGREGATE_SOCIAL_SIGNALS:
            raise UnknownJobError(f"social signal handler cannot process {job.job_type.value}")
        payload = AggregateSocialSignalsJobPayload.from_payload(job.payload)
        result = SocialSignalAggregationService(
            self.repository, clock=self.clock
        ).aggregate(timedelta(seconds=payload.lookback_seconds))
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=result.calculated_at,
            successful_items=result.snapshots_written,
            skipped_items=0,
            failed_items=0,
            metrics={"lookback_seconds": payload.lookback_seconds},
        )


class WorkerJobRunner:
    def __init__(self, handlers: Mapping[JobType, JobHandler]) -> None:
        self._handlers = dict(handlers)

    def run(self, job: WorkerJob) -> JobExecutionResult:
        return self.handler_for(job.job_type).handle(job)

    def handler_for(self, job_type: JobType) -> JobHandler:
        handler = self._handlers.get(job_type)
        if handler is None:
            raise UnknownJobError(f"no handler registered for {job_type.value}")
        return handler
