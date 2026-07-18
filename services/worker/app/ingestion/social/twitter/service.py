from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Callable, Protocol

from .classifier import InjuryClassifier, RuleBasedInjuryClassifier
from .episodes import InjuryEpisodeStateMachine
from .models import (
    InjuryClassification,
    InjuryEvidenceKind,
    PlayerResolutionStatus,
    TwitterIngestionCursor,
    TwitterInjuryIngestionResult,
    TwitterRateLimit,
    TwitterSearchPage,
)
from .repository import TwitterInjuryRepository
from .resolution import PlayerResolver


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TwitterSearchClient(Protocol):
    def search_page(
        self,
        query: str,
        *,
        since_id: str | None = None,
        next_token: str | None = None,
    ) -> TwitterSearchPage: ...


class TwitterInjuryIngestionService:
    def __init__(
        self,
        client: TwitterSearchClient,
        repository: TwitterInjuryRepository,
        *,
        classifier: InjuryClassifier | None = None,
        episode_state_machine: InjuryEpisodeStateMachine | None = None,
        max_pages_per_poll: int = 10,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client
        self._repository = repository
        self._classifier = classifier or RuleBasedInjuryClassifier()
        self._episode_state_machine = episode_state_machine or InjuryEpisodeStateMachine()
        self._max_pages_per_poll = max(max_pages_per_poll, 1)
        self._clock = clock

    def ingest_recent(self, query: str, query_key: str | None = None) -> TwitterInjuryIngestionResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("X recent-search query cannot be empty")
        effective_query_key = query_key or hashlib.sha256(
            normalized_query.encode("utf-8")
        ).hexdigest()[:24]
        cursor = self._repository.load_cursor(effective_query_key, normalized_query)
        self._repository.expire_stale_episodes(self._clock())

        sources = self._repository.list_source_accounts()
        sources_by_user_id = {source.twitter_user_id: source for source in sources}
        resolver = PlayerResolver(self._repository.list_player_candidates())

        counts = {
            "fetched_posts": 0,
            "persisted_posts": 0,
            "classified_posts": 0,
            "resolved_posts": 0,
            "ambiguous_posts": 0,
            "episode_updates": 0,
            "skipped_posts": 0,
            "pages_fetched": 0,
        }
        pending_newest_id = cursor.pending_newest_id
        next_token = cursor.next_token
        for _ in range(self._max_pages_per_poll):
            page = self._client.search_page(
                normalized_query,
                since_id=cursor.since_id,
                next_token=next_token,
            )
            counts["pages_fetched"] += 1
            counts["fetched_posts"] += len(page.posts)
            pending_newest_id = pending_newest_id or page.newest_id
            for post in page.posts:
                source = sources_by_user_id.get(post.author_id)
                if source is None:
                    counts["skipped_posts"] += 1
                    continue
                source_club_hint = _source_club_hint(source.metadata)
                resolution = resolver.resolve(post.text, source_club_hint)
                classification = self._classifier.classify(post.text, source)
                pending = self._repository.upsert_post_observation(
                    post,
                    source,
                    resolution,
                    classification,
                )
                counts["persisted_posts"] += int(pending.was_created)
                if classification.has_evidence:
                    counts["classified_posts"] += 1
                if resolution.status is PlayerResolutionStatus.RESOLVED:
                    counts["resolved_posts"] += 1
                elif resolution.status is PlayerResolutionStatus.AMBIGUOUS:
                    counts["ambiguous_posts"] += 1

                if pending.already_processed:
                    continue
                if (
                    resolution.status is not PlayerResolutionStatus.RESOLVED
                    or resolution.player_id is None
                    or not classification.has_evidence
                    or classification.aggregate_only
                ):
                    self._repository.mark_observation_processed(pending.observation_id)
                    continue

                active_episode = self._repository.get_active_episode(resolution.player_id)
                latest_recovered = (
                    None
                    if active_episode is not None
                    else self._repository.get_latest_recovered_episode(resolution.player_id)
                )
                decision = self._episode_state_machine.decide(
                    active_episode=active_episode,
                    latest_recovered_episode=latest_recovered,
                    classification=classification,
                    source_kind=source.account_kind,
                    observed_at=post.created_at,
                )
                self._repository.apply_episode_decision(
                    player_id=resolution.player_id,
                    decision=decision,
                    classification=classification,
                    observed_at=post.created_at,
                    source=source,
                    observation_id=pending.observation_id,
                    active_episode=active_episode,
                )
                if decision.action in {"CREATE", "UPDATE", "ATTACH"}:
                    counts["episode_updates"] += 1

            next_token = page.next_token
            polled_at = self._clock()
            if next_token:
                self._repository.checkpoint_cursor(
                    TwitterIngestionCursor(
                        query_key=effective_query_key,
                        query=normalized_query,
                        since_id=cursor.since_id,
                        next_token=next_token,
                        pending_newest_id=pending_newest_id,
                        rate_limit=page.rate_limit,
                    ),
                    polled_at,
                )
                continue
            self._repository.complete_cursor(
                effective_query_key,
                normalized_query,
                pending_newest_id or cursor.since_id,
                page.rate_limit,
                polled_at,
            )
            break

        participation_recoveries = self._reconcile_match_participation()
        return TwitterInjuryIngestionResult(
            **counts,
            participation_recoveries=participation_recoveries,
        )

    def _reconcile_match_participation(self) -> int:
        recovered_count = 0
        for episode in self._repository.list_recovery_candidates():
            participation = self._repository.find_strong_match_participation(
                episode.player_id,
                episode.last_evidence_at,
            )
            if participation is None:
                continue
            classification = InjuryClassification(
                evidence_kind=InjuryEvidenceKind.MATCH_PARTICIPATION,
                confidence=1.0,
                matched_rules=("existing_fixture_linked_stats_minutes_gt_zero",),
            )
            decision = self._episode_state_machine.decide(
                active_episode=episode,
                latest_recovered_episode=None,
                classification=classification,
                source_kind=None,
                observed_at=participation.observed_at,
            )
            self._repository.apply_episode_decision(
                player_id=episode.player_id,
                decision=decision,
                classification=classification,
                observed_at=participation.observed_at,
                source=None,
                observation_id=None,
                active_episode=episode,
                participation=participation,
            )
            if decision.stage is not None:
                recovered_count += 1
        return recovered_count


def _source_club_hint(metadata: object) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("club")
    return None if value is None else str(value)
