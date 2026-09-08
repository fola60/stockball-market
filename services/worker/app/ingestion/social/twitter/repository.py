from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.database import connection as pooled_connection

from .models import (
    EpisodeDecision,
    InjuryClassification,
    InjuryEpisode,
    InjuryStage,
    MatchParticipationEvidence,
    PendingPostObservation,
    PlayerAlias,
    PlayerIdentityCandidate,
    PlayerResolution,
    SourceAccountKind,
    TwitterIngestionCursor,
    TwitterPost,
    TwitterRateLimit,
    TwitterSourceAccount,
)
from .registry import TwitterInjuryRegistry, TwitterInjuryRegistrySyncResult
from .resolution import normalize_identity


class TwitterInjuryRepository(Protocol):
    def load_cursor(self, query_key: str, query: str) -> TwitterIngestionCursor: ...

    def checkpoint_cursor(self, cursor: TwitterIngestionCursor, polled_at: datetime) -> None: ...

    def complete_cursor(
        self,
        query_key: str,
        query: str,
        since_id: str | None,
        rate_limit: TwitterRateLimit,
        polled_at: datetime,
    ) -> None: ...

    def list_source_accounts(self) -> list[TwitterSourceAccount]: ...

    def list_player_candidates(self) -> list[PlayerIdentityCandidate]: ...

    def upsert_post_observation(
        self,
        post: TwitterPost,
        source: TwitterSourceAccount,
        resolution: PlayerResolution,
        classification: InjuryClassification,
    ) -> PendingPostObservation: ...

    def mark_observation_processed(self, observation_id: UUID) -> None: ...

    def expire_stale_episodes(self, as_of: datetime) -> int: ...

    def get_active_episode(self, player_id: UUID) -> InjuryEpisode | None: ...

    def get_latest_recovered_episode(self, player_id: UUID) -> InjuryEpisode | None: ...

    def apply_episode_decision(
        self,
        *,
        player_id: UUID,
        decision: EpisodeDecision,
        classification: InjuryClassification,
        observed_at: datetime,
        source: TwitterSourceAccount | None,
        observation_id: UUID | None,
        active_episode: InjuryEpisode | None,
        participation: MatchParticipationEvidence | None = None,
    ) -> InjuryEpisode | None: ...

    def list_recovery_candidates(self) -> list[InjuryEpisode]: ...

    def find_strong_match_participation(
        self,
        player_id: UUID,
        since: datetime,
    ) -> MatchParticipationEvidence | None: ...


class PostgresTwitterInjuryRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def sync_registry(self, registry: TwitterInjuryRegistry) -> TwitterInjuryRegistrySyncResult:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE twitter_injury_source_accounts
                        SET enabled = false, updated_at = now()
                        """
                    )
                    cursor.execute(
                        """
                        UPDATE twitter_player_aliases
                        SET enabled = false, updated_at = now()
                        """
                    )
                    for source in registry.sources:
                        cursor.execute(
                            """
                            INSERT INTO twitter_injury_source_accounts (
                                twitter_user_id, username, display_name, account_kind,
                                trust_weight, enabled, manually_reviewed_at,
                                reviewed_by, review_notes, metadata
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (twitter_user_id) DO UPDATE
                            SET
                                username = EXCLUDED.username,
                                display_name = EXCLUDED.display_name,
                                account_kind = EXCLUDED.account_kind,
                                trust_weight = EXCLUDED.trust_weight,
                                enabled = EXCLUDED.enabled,
                                manually_reviewed_at = EXCLUDED.manually_reviewed_at,
                                reviewed_by = EXCLUDED.reviewed_by,
                                review_notes = EXCLUDED.review_notes,
                                metadata = EXCLUDED.metadata,
                                updated_at = now()
                            """,
                            (
                                source.twitter_user_id,
                                source.username,
                                source.display_name,
                                source.account_kind.value,
                                source.trust_weight,
                                source.enabled,
                                source.manually_reviewed_at,
                                source.reviewed_by,
                                source.review_notes,
                                Json(dict(source.metadata)),
                            ),
                        )
                    for registered_alias in registry.player_aliases:
                        alias = registered_alias.alias
                        cursor.execute(
                            """
                            INSERT INTO twitter_player_aliases (
                                player_id, alias, normalized_alias, alias_type,
                                club_hint, manually_reviewed_at, reviewed_by, metadata
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (player_id, normalized_alias) DO UPDATE
                            SET
                                alias = EXCLUDED.alias,
                                alias_type = EXCLUDED.alias_type,
                                club_hint = EXCLUDED.club_hint,
                                manually_reviewed_at = EXCLUDED.manually_reviewed_at,
                                reviewed_by = EXCLUDED.reviewed_by,
                                metadata = EXCLUDED.metadata,
                                enabled = true,
                                updated_at = now()
                            """,
                            (
                                str(registered_alias.player_id),
                                alias.alias,
                                normalize_identity(alias.alias),
                                alias.alias_type,
                                alias.club_hint,
                                registered_alias.manually_reviewed_at,
                                registered_alias.reviewed_by,
                                Json(dict(registered_alias.metadata)),
                            ),
                        )
        return TwitterInjuryRegistrySyncResult(
            source_accounts=len(registry.sources),
            player_aliases=len(registry.player_aliases),
        )

    def load_cursor(self, query_key: str, query: str) -> TwitterIngestionCursor:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM twitter_injury_ingestion_cursors
                    WHERE query_key = %s
                    """,
                    (query_key,),
                )
                row = cursor.fetchone()
        if row is None:
            return TwitterIngestionCursor(query_key=query_key, query=query)
        if str(row["query"]) != query:
            raise ValueError(
                f"X query_key {query_key!r} already belongs to a different search query"
            )
        return TwitterIngestionCursor(
            query_key=query_key,
            query=query,
            since_id=_optional_string(row["since_id"]),
            next_token=_optional_string(row["next_token"]),
            pending_newest_id=_optional_string(row["pending_newest_id"]),
            rate_limit=TwitterRateLimit(
                limit=row["rate_limit_limit"],
                remaining=row["rate_limit_remaining"],
                reset_at=row["rate_limit_reset_at"],
            ),
        )

    def checkpoint_cursor(self, cursor: TwitterIngestionCursor, polled_at: datetime) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as db_cursor:
                    db_cursor.execute(
                        """
                        INSERT INTO twitter_injury_ingestion_cursors (
                            query_key, query, since_id, next_token, pending_newest_id,
                            rate_limit_limit, rate_limit_remaining, rate_limit_reset_at,
                            last_polled_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (query_key) DO UPDATE
                        SET
                            query = EXCLUDED.query,
                            since_id = EXCLUDED.since_id,
                            next_token = EXCLUDED.next_token,
                            pending_newest_id = EXCLUDED.pending_newest_id,
                            rate_limit_limit = EXCLUDED.rate_limit_limit,
                            rate_limit_remaining = EXCLUDED.rate_limit_remaining,
                            rate_limit_reset_at = EXCLUDED.rate_limit_reset_at,
                            last_polled_at = EXCLUDED.last_polled_at,
                            updated_at = now()
                        """,
                        (
                            cursor.query_key,
                            cursor.query,
                            cursor.since_id,
                            cursor.next_token,
                            cursor.pending_newest_id,
                            cursor.rate_limit.limit,
                            cursor.rate_limit.remaining,
                            cursor.rate_limit.reset_at,
                            polled_at,
                        ),
                    )

    def complete_cursor(
        self,
        query_key: str,
        query: str,
        since_id: str | None,
        rate_limit: TwitterRateLimit,
        polled_at: datetime,
    ) -> None:
        self.checkpoint_cursor(
            TwitterIngestionCursor(
                query_key=query_key,
                query=query,
                since_id=since_id,
                next_token=None,
                pending_newest_id=None,
                rate_limit=rate_limit,
            ),
            polled_at,
        )

    def list_source_accounts(self) -> list[TwitterSourceAccount]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM twitter_injury_source_accounts
                    WHERE enabled = true
                    ORDER BY account_kind, username
                    """
                )
                rows = cursor.fetchall()
        return [_source_account(row) for row in rows]

    def list_player_candidates(self) -> list[PlayerIdentityCandidate]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        player.id AS player_id,
                        player.display_name,
                        player.club,
                        alias.alias,
                        alias.alias_type,
                        alias.club_hint
                    FROM players AS player
                    LEFT JOIN twitter_player_aliases AS alias
                        ON alias.player_id = player.id
                       AND alias.enabled = true
                    ORDER BY player.id, alias.alias
                    """
                )
                rows = cursor.fetchall()
        grouped: dict[UUID, dict[str, object]] = {}
        for row in rows:
            player_id = UUID(str(row["player_id"]))
            record = grouped.setdefault(
                player_id,
                {
                    "display_name": str(row["display_name"]),
                    "club": _optional_string(row["club"]),
                    "aliases": [],
                },
            )
            if row["alias"] is not None:
                aliases = record["aliases"]
                assert isinstance(aliases, list)
                aliases.append(
                    PlayerAlias(
                        alias=str(row["alias"]),
                        alias_type=str(row["alias_type"]),
                        club_hint=_optional_string(row["club_hint"]),
                    )
                )
        return [
            PlayerIdentityCandidate(
                player_id=player_id,
                display_name=str(record["display_name"]),
                club=_optional_string(record["club"]),
                aliases=tuple(record["aliases"]),
            )
            for player_id, record in grouped.items()
        ]

    def upsert_post_observation(
        self,
        post: TwitterPost,
        source: TwitterSourceAccount,
        resolution: PlayerResolution,
        classification: InjuryClassification,
    ) -> PendingPostObservation:
        if source.id is None:
            raise ValueError("persisted X source account must have an id")
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO twitter_injury_posts (
                            twitter_post_id, twitter_author_id, source_account_id,
                            posted_at, lang, raw_metadata
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (twitter_post_id) DO UPDATE
                        SET
                            twitter_author_id = EXCLUDED.twitter_author_id,
                            source_account_id = EXCLUDED.source_account_id,
                            posted_at = EXCLUDED.posted_at,
                            lang = EXCLUDED.lang,
                            raw_metadata = EXCLUDED.raw_metadata
                        """,
                        (
                            post.post_id,
                            post.author_id,
                            str(source.id),
                            post.created_at,
                            post.lang,
                            Json(dict(post.terms_compatible_metadata)),
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO twitter_injury_post_observations (
                            twitter_post_id, resolution_status, player_id,
                            candidate_player_ids, matched_aliases, resolution_reason,
                            evidence_kind, confidence, injury_type, body_area,
                            absence_min_days, absence_max_days, negated, uncertain,
                            aggregate_only, matched_rules
                        ) VALUES (
                            %s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (twitter_post_id) DO NOTHING
                        RETURNING id, processed_at, episode_id
                        """,
                        (
                            post.post_id,
                            resolution.status.value,
                            None if resolution.player_id is None else str(resolution.player_id),
                            [str(value) for value in resolution.candidate_player_ids],
                            list(resolution.matched_aliases),
                            resolution.reason,
                            classification.evidence_kind.value,
                            classification.confidence,
                            classification.injury_type,
                            classification.body_area,
                            classification.absence_min_days,
                            classification.absence_max_days,
                            classification.negated,
                            classification.uncertain,
                            classification.aggregate_only,
                            list(classification.matched_rules),
                        ),
                    )
                    row = cursor.fetchone()
                    was_created = row is not None
                    if row is None:
                        cursor.execute(
                            """
                            SELECT id, processed_at, episode_id
                            FROM twitter_injury_post_observations
                            WHERE twitter_post_id = %s
                            """,
                            (post.post_id,),
                        )
                        row = cursor.fetchone()
        return PendingPostObservation(
            observation_id=UUID(str(row["id"])),
            already_processed=row["processed_at"] is not None,
            episode_id=None if row["episode_id"] is None else UUID(str(row["episode_id"])),
            was_created=was_created,
        )

    def mark_observation_processed(self, observation_id: UUID) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE twitter_injury_post_observations
                        SET processed_at = now()
                        WHERE id = %s
                        """,
                        (str(observation_id),),
                    )

    def expire_stale_episodes(self, as_of: datetime) -> int:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE player_injury_episodes
                        SET expired_at = %s, updated_at = now()
                        WHERE expired_at IS NULL
                          AND stage <> 'CONFIRMED_RECOVERED'
                          AND expires_at <= %s
                        """,
                        (as_of, as_of),
                    )
                    return cursor.rowcount

    def get_active_episode(self, player_id: UUID) -> InjuryEpisode | None:
        return self._get_episode(
            """
            SELECT *
            FROM player_injury_episodes
            WHERE player_id = %s
              AND expired_at IS NULL
              AND stage <> 'CONFIRMED_RECOVERED'
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (str(player_id),),
        )

    def get_latest_recovered_episode(self, player_id: UUID) -> InjuryEpisode | None:
        return self._get_episode(
            """
            SELECT latest.*
            FROM (
                SELECT *
                FROM player_injury_episodes
                WHERE player_id = %s
                ORDER BY started_at DESC, id DESC
                LIMIT 1
            ) AS latest
            WHERE latest.stage = 'CONFIRMED_RECOVERED'
            """,
            (str(player_id),),
        )

    def _get_episode(self, query: str, params: tuple[object, ...]) -> InjuryEpisode | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
        return None if row is None else _episode(row)

    def apply_episode_decision(
        self,
        *,
        player_id: UUID,
        decision: EpisodeDecision,
        classification: InjuryClassification,
        observed_at: datetime,
        source: TwitterSourceAccount | None,
        observation_id: UUID | None,
        active_episode: InjuryEpisode | None,
        participation: MatchParticipationEvidence | None = None,
    ) -> InjuryEpisode | None:
        if decision.action not in {"CREATE", "UPDATE", "ATTACH"}:
            if observation_id is not None:
                self.mark_observation_processed(observation_id)
            return active_episode
        if decision.action == "CREATE" and decision.stage is None:
            raise ValueError("episode create decision requires a stage")
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    if decision.action == "CREATE":
                        cursor.execute(
                            """
                            INSERT INTO player_injury_episodes (
                                player_id, recurrence_of_episode_id, stage,
                                injury_type, body_area, confidence, started_at,
                                last_evidence_at, expected_absence_until,
                                recovered_at, expires_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING *
                            """,
                            (
                                str(player_id),
                                (
                                    None
                                    if decision.recurrence_of_episode_id is None
                                    else str(decision.recurrence_of_episode_id)
                                ),
                                decision.stage.value,
                                decision.injury_type,
                                decision.body_area,
                                decision.confidence,
                                observed_at,
                                observed_at,
                                decision.expected_absence_until,
                                (
                                    observed_at
                                    if decision.stage is InjuryStage.CONFIRMED_RECOVERED
                                    else None
                                ),
                                decision.expires_at,
                            ),
                        )
                        row = cursor.fetchone()
                        episode = _episode(row)
                        stage_before = None
                    else:
                        if active_episode is None:
                            raise ValueError("episode update decision requires an active episode")
                        target_stage = decision.stage or active_episode.stage
                        cursor.execute(
                            """
                            UPDATE player_injury_episodes
                            SET
                                stage = %s,
                                injury_type = %s,
                                body_area = %s,
                                confidence = %s,
                                last_evidence_at = %s,
                                expected_absence_until = %s,
                                recovered_at = CASE
                                    WHEN %s = 'CONFIRMED_RECOVERED' THEN %s
                                    ELSE recovered_at
                                END,
                                expires_at = COALESCE(%s, expires_at),
                                updated_at = now()
                            WHERE id = %s
                            RETURNING *
                            """,
                            (
                                target_stage.value,
                                decision.injury_type or active_episode.injury_type,
                                decision.body_area or active_episode.body_area,
                                max(decision.confidence, active_episode.confidence),
                                observed_at,
                                (
                                    decision.expected_absence_until
                                    if decision.expected_absence_until is not None
                                    else active_episode.expected_absence_until
                                ),
                                target_stage.value,
                                observed_at,
                                decision.expires_at,
                                str(active_episode.id),
                            ),
                        )
                        episode = _episode(cursor.fetchone())
                        stage_before = active_episode.stage

                    if classification.has_evidence:
                        cursor.execute(
                            """
                            INSERT INTO player_injury_episode_evidence (
                                injury_episode_id, post_observation_id, fixture_id,
                                source_account_id, evidence_kind, stage_before,
                                stage_after, confidence, observed_at, details
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                str(episode.id),
                                None if observation_id is None else str(observation_id),
                                (
                                    None
                                    if participation is None
                                    else str(participation.fixture_id)
                                ),
                                (
                                    None
                                    if source is None or source.id is None
                                    else str(source.id)
                                ),
                                classification.evidence_kind.value,
                                None if stage_before is None else stage_before.value,
                                episode.stage.value,
                                classification.confidence,
                                observed_at,
                                Json(
                                    {
                                        "decision_reason": decision.reason,
                                        "matched_rules": list(classification.matched_rules),
                                        "absence_min_days": classification.absence_min_days,
                                        "absence_max_days": classification.absence_max_days,
                                        "participation_minutes": (
                                            None if participation is None else participation.minutes
                                        ),
                                        "participation_provider": (
                                            None if participation is None else participation.provider
                                        ),
                                    }
                                ),
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT INTO player_injury_availability_observations (
                                player_id, injury_episode_id, stage, confidence,
                                is_available, expected_absence_until, injury_type,
                                body_area, evidence_kind, source_account_kind, observed_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                str(player_id),
                                str(episode.id),
                                episode.stage.value,
                                episode.confidence,
                                episode.stage is InjuryStage.CONFIRMED_RECOVERED,
                                episode.expected_absence_until,
                                episode.injury_type,
                                episode.body_area,
                                classification.evidence_kind.value,
                                None if source is None else source.account_kind.value,
                                observed_at,
                            ),
                        )
                    if observation_id is not None:
                        cursor.execute(
                            """
                            UPDATE twitter_injury_post_observations
                            SET episode_id = %s, processed_at = now()
                            WHERE id = %s
                            """,
                            (str(episode.id), str(observation_id)),
                        )
        return episode

    def list_recovery_candidates(self) -> list[InjuryEpisode]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM player_injury_episodes
                    WHERE stage IN (
                        'SUSPECTED_INJURY',
                        'CONFIRMED_INJURY',
                        'SUSPECTED_RECOVERY'
                    )
                      AND expired_at IS NULL
                    ORDER BY last_evidence_at
                    """
                )
                rows = cursor.fetchall()
        return [_episode(row) for row in rows]

    def find_strong_match_participation(
        self,
        player_id: UUID,
        since: datetime,
    ) -> MatchParticipationEvidence | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        observation.player_id,
                        observation.fixture_id,
                        fixture.kickoff_at AS observed_at,
                        (observation.stats ->> 'minutes')::numeric AS minutes,
                        observation.provider
                    FROM player_stat_observations AS observation
                    JOIN fixtures AS fixture
                        ON fixture.id = observation.fixture_id
                    WHERE observation.player_id = %s
                      AND fixture.kickoff_at >= %s
                      AND fixture.status_short IN ('FT', 'AET', 'PEN')
                      AND observation.stats ? 'minutes'
                      AND (observation.stats ->> 'minutes') ~ '^[0-9]+([.][0-9]+)?$'
                      AND (observation.stats ->> 'minutes')::numeric > 0
                    ORDER BY fixture.kickoff_at DESC, observation.id DESC
                    LIMIT 1
                    """,
                    (str(player_id), since),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return MatchParticipationEvidence(
            player_id=UUID(str(row["player_id"])),
            fixture_id=UUID(str(row["fixture_id"])),
            observed_at=row["observed_at"],
            minutes=float(row["minutes"]),
            provider=str(row["provider"]),
        )


def _source_account(row: dict[str, object]) -> TwitterSourceAccount:
    return TwitterSourceAccount(
        id=UUID(str(row["id"])),
        twitter_user_id=str(row["twitter_user_id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        account_kind=SourceAccountKind(str(row["account_kind"])),
        trust_weight=float(row["trust_weight"]),
        enabled=bool(row["enabled"]),
        manually_reviewed_at=row["manually_reviewed_at"],
        reviewed_by=str(row["reviewed_by"]),
        review_notes=str(row["review_notes"]),
        metadata=dict(row["metadata"]) if isinstance(row["metadata"], dict) else {},
    )


def _episode(row: dict[str, object]) -> InjuryEpisode:
    return InjuryEpisode(
        id=UUID(str(row["id"])),
        player_id=UUID(str(row["player_id"])),
        stage=InjuryStage(str(row["stage"])),
        started_at=row["started_at"],
        last_evidence_at=row["last_evidence_at"],
        expected_absence_until=row["expected_absence_until"],
        expires_at=row["expires_at"],
        confidence=float(row["confidence"]),
        injury_type=_optional_string(row["injury_type"]),
        body_area=_optional_string(row["body_area"]),
        recurrence_of_episode_id=(
            None
            if row["recurrence_of_episode_id"] is None
            else UUID(str(row["recurrence_of_episode_id"]))
        ),
        recovered_at=row["recovered_at"],
        expired_at=row["expired_at"],
    )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)
