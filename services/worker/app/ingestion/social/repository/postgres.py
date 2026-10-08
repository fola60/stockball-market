from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Iterator, Mapping
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.database import connection as pooled_connection

from ..domain import (
    IngestionCursor,
    PollResult,
    RateLimitState,
    SocialDocument,
    SocialDocumentKind,
    SocialEntityType,
    SocialObservationClassification,
    SocialObservationStatus,
    SocialPolicyStatus,
    SocialProvider,
    SocialSource,
    SocialSourceCategory,
    SocialSubscription,
    SocialSubscriptionMode,
)
from ..enrichment import ArticleEnrichmentCandidate
from ..twitter.episodes import InjuryEpisodeStateMachine
from ..twitter.models import (
    InjuryClassification,
    InjuryEpisode,
    InjuryStage,
    PlayerAlias,
    PlayerIdentityCandidate,
    PlayerResolution,
    SourceAccountKind,
)


class PostgresSocialRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def get_source(self, source_id: UUID) -> SocialSource | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM social_sources WHERE id = %s", (str(source_id),))
                row = cursor.fetchone()
        return None if row is None else _source(row)

    def upsert_source(self, source: SocialSource) -> UUID:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO social_sources (
                            id, provider, external_source_id, display_handle,
                            canonical_url, source_category, trust_weight, enabled,
                            policy_status, terms_reviewed_at, retention_days,
                            approved_by, approved_at, metadata
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (provider, external_source_id) DO UPDATE SET
                            display_handle = EXCLUDED.display_handle,
                            canonical_url = EXCLUDED.canonical_url,
                            source_category = EXCLUDED.source_category,
                            trust_weight = EXCLUDED.trust_weight,
                            enabled = EXCLUDED.enabled,
                            policy_status = EXCLUDED.policy_status,
                            terms_reviewed_at = EXCLUDED.terms_reviewed_at,
                            retention_days = EXCLUDED.retention_days,
                            approved_by = EXCLUDED.approved_by,
                            approved_at = EXCLUDED.approved_at,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
                        RETURNING id
                        """,
                        (
                            str(source.id),
                            source.provider.value,
                            source.external_source_id,
                            source.display_handle,
                            source.canonical_url,
                            source.source_category.value,
                            source.trust_weight,
                            source.enabled,
                            source.policy_status.value,
                            source.terms_reviewed_at,
                            source.retention_days,
                            source.approved_by,
                            source.approved_at,
                            Json(dict(source.metadata)),
                        ),
                    )
                    row = cursor.fetchone()
        return UUID(str(row[0]))

    def get_subscription(self, subscription_id: UUID) -> SocialSubscription | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM social_subscriptions WHERE id = %s",
                    (str(subscription_id),),
                )
                row = cursor.fetchone()
        return None if row is None else _subscription(row)

    def upsert_subscription(self, subscription: SocialSubscription) -> UUID:
        forbidden_keys = {
            "access_token",
            "authorization",
            "password",
            "secret",
            "token",
        }
        if forbidden_keys.intersection(key.casefold() for key in subscription.configuration):
            raise ValueError("social subscription configuration must not contain secrets")
        source = self.get_source(subscription.source_id)
        if source is None or source.provider is not subscription.provider:
            raise ValueError("social subscription must match an existing source provider")
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO social_subscriptions (
                            id, source_id, provider, mode, configuration,
                            polling_interval_seconds, enabled, next_eligible_poll_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            source_id = EXCLUDED.source_id,
                            provider = EXCLUDED.provider,
                            mode = EXCLUDED.mode,
                            configuration = EXCLUDED.configuration,
                            polling_interval_seconds = EXCLUDED.polling_interval_seconds,
                            enabled = EXCLUDED.enabled,
                            next_eligible_poll_at = EXCLUDED.next_eligible_poll_at,
                            updated_at = now()
                        RETURNING id
                        """,
                        (
                            str(subscription.id),
                            str(subscription.source_id),
                            subscription.provider.value,
                            subscription.mode.value,
                            Json(dict(subscription.configuration)),
                            round(subscription.polling_interval.total_seconds()),
                            subscription.enabled,
                            subscription.next_eligible_poll_at,
                        ),
                    )
                    row = cursor.fetchone()
        return UUID(str(row[0]))

    def list_player_candidates(self) -> list[PlayerIdentityCandidate]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT player.id AS player_id, player.display_name, player.club,
                           alias.alias, alias.alias_type, alias.club_hint
                    FROM players AS player
                    LEFT JOIN twitter_player_aliases AS alias
                      ON alias.player_id = player.id AND alias.enabled = true
                    ORDER BY player.id, alias.alias
                    """
                )
                rows = cursor.fetchall()
        grouped: dict[UUID, dict[str, object]] = {}
        for row in rows:
            player_id = UUID(str(row["player_id"]))
            item = grouped.setdefault(
                player_id,
                {
                    "display_name": str(row["display_name"]),
                    "club": _optional_string(row["club"]),
                    "aliases": [],
                },
            )
            if row["alias"] is not None:
                aliases = item["aliases"]
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
                display_name=str(item["display_name"]),
                club=_optional_string(item["club"]),
                aliases=tuple(item["aliases"]),
            )
            for player_id, item in grouped.items()
        ]

    def list_due_subscriptions(
        self,
        as_of: datetime,
        *,
        limit: int = 100,
        provider: str | None = None,
    ) -> list[UUID]:
        if limit <= 0:
            return []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT subscription.id
                    FROM social_subscriptions AS subscription
                    JOIN social_sources AS source ON source.id = subscription.source_id
                    LEFT JOIN social_ingestion_cursors AS ingestion_cursor
                        ON ingestion_cursor.subscription_id = subscription.id
                    WHERE subscription.enabled = true
                      AND source.enabled = true
                      AND source.policy_status = 'APPROVED'
                      AND (%s IS NULL OR subscription.provider = %s)
                      AND COALESCE(
                            ingestion_cursor.next_eligible_poll_at,
                            subscription.next_eligible_poll_at,
                            '-infinity'::timestamptz
                          ) <= %s
                    ORDER BY COALESCE(
                        ingestion_cursor.next_eligible_poll_at,
                        subscription.next_eligible_poll_at,
                        '-infinity'::timestamptz
                    ), subscription.id
                    LIMIT %s
                    """,
                    (provider, provider, as_of, limit),
                )
                rows = cursor.fetchall()
        return [UUID(str(row[0])) for row in rows]

    def load_cursor(self, subscription_id: UUID) -> IngestionCursor | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM social_ingestion_cursors WHERE subscription_id = %s",
                    (str(subscription_id),),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        raw_limit = row["rate_limit_metadata"] or {}
        reset_at = raw_limit.get("reset_at") if isinstance(raw_limit, Mapping) else None
        return IngestionCursor(
            subscription_id=subscription_id,
            cursor=row["cursor"],
            etag=_optional_string(row["etag"]),
            last_modified=_optional_string(row["last_modified"]),
            last_polled_at=row["last_polled_at"],
            last_success_at=row["last_success_at"],
            consecutive_failures=int(row["consecutive_failure_count"]),
            next_eligible_poll_at=row["next_eligible_poll_at"],
            rate_limit=(
                None
                if not raw_limit
                else RateLimitState(
                    limit=_optional_int(raw_limit.get("limit")),
                    remaining=_optional_int(raw_limit.get("remaining")),
                    reset_at=_optional_datetime(reset_at),
                    metadata=raw_limit.get("metadata", {}),
                )
            ),
        )

    def persist_poll_result(
        self,
        subscription: SocialSubscription,
        result: PollResult,
        polled_at: datetime,
    ) -> tuple[int, int]:
        for document in result.documents:
            if document.provider is not subscription.provider:
                raise ValueError("connector returned a document for a different provider")
            if document.source_id != subscription.source_id:
                raise ValueError("connector returned a document for a different source")
        inserted = 0
        next_eligible = polled_at + (result.retry_after or subscription.polling_interval)
        provider_cursor = None if result.next_cursor is None else dict(result.next_cursor)
        etag = _pop_string(provider_cursor, "etag")
        last_modified = _pop_string(provider_cursor, "last_modified")
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    for document in result.documents:
                        cursor.execute(
                            """
                            INSERT INTO social_documents (
                                provider, external_id, source_id, subscription_id,
                                document_kind, author_external_id, published_at,
                                ingested_at, canonical_url, language, normalized_text,
                                source_text, content_hash, provider_metadata
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            ON CONFLICT (provider, external_id) DO UPDATE
                                -- Entries stored before headlines were kept gain them
                                -- when the feed serves them again; nothing else changes.
                                SET provider_metadata = social_documents.provider_metadata
                                    || jsonb_build_object('title', EXCLUDED.provider_metadata->'title')
                                WHERE EXCLUDED.provider_metadata ? 'title'
                                  AND NOT social_documents.provider_metadata ? 'title'
                            RETURNING id, (xmax = 0) AS inserted
                            """,
                            (
                                document.provider.value,
                                document.external_id,
                                str(document.source_id),
                                str(subscription.id),
                                document.document_kind.value,
                                document.author_external_id,
                                document.published_at,
                                polled_at,
                                document.canonical_url,
                                document.language,
                                document.text,
                                document.text,
                                hashlib.sha256(document.text.encode("utf-8")).hexdigest(),
                                Json(dict(document.metadata)),
                            ),
                        )
                        row = cursor.fetchone()
                        if row is None or not row["inserted"]:
                            continue
                        inserted += 1
                        cursor.execute(
                            """
                            INSERT INTO social_document_processing_queue (document_id)
                            VALUES (%s)
                            ON CONFLICT (document_id) DO NOTHING
                            """,
                            (str(row["id"]),),
                        )
                        cursor.execute(
                            """
                            INSERT INTO social_document_enrichments (document_id)
                            SELECT %s
                            FROM social_sources source
                            WHERE source.id = %s
                              AND source.enabled
                              AND source.policy_status = 'APPROVED'
                              AND COALESCE(
                                  (source.metadata->'article_enrichment'->>'enabled')::boolean,
                                  false
                              )
                            ON CONFLICT (document_id) DO NOTHING
                            """,
                            (str(row["id"]), str(document.source_id)),
                        )
                    cursor.execute(
                        """
                        INSERT INTO social_ingestion_cursors (
                            subscription_id, cursor, etag, last_modified,
                            last_polled_at, last_success_at, consecutive_failure_count,
                            next_eligible_poll_at, rate_limit_metadata, last_error_type
                        ) VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, NULL)
                        ON CONFLICT (subscription_id) DO UPDATE SET
                            cursor = EXCLUDED.cursor,
                            etag = COALESCE(EXCLUDED.etag, social_ingestion_cursors.etag),
                            last_modified = COALESCE(
                                EXCLUDED.last_modified, social_ingestion_cursors.last_modified
                            ),
                            last_polled_at = EXCLUDED.last_polled_at,
                            last_success_at = EXCLUDED.last_success_at,
                            consecutive_failure_count = 0,
                            next_eligible_poll_at = EXCLUDED.next_eligible_poll_at,
                            rate_limit_metadata = EXCLUDED.rate_limit_metadata,
                            last_error_type = NULL,
                            updated_at = now()
                        """,
                        (
                            str(subscription.id),
                            None if provider_cursor is None else Json(provider_cursor),
                            etag,
                            last_modified,
                            polled_at,
                            polled_at,
                            next_eligible,
                            Json(_rate_limit_payload(result.rate_limit)),
                        ),
                    )
        return inserted, len(result.documents) - inserted

    def record_failure(
        self,
        subscription_id: UUID,
        failed_at: datetime,
        next_eligible_poll_at: datetime,
        error_type: str,
    ) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO social_ingestion_cursors (
                            subscription_id, last_polled_at, consecutive_failure_count,
                            next_eligible_poll_at, last_error_type
                        ) VALUES (%s, %s, 1, %s, %s)
                        ON CONFLICT (subscription_id) DO UPDATE SET
                            last_polled_at = EXCLUDED.last_polled_at,
                            consecutive_failure_count =
                                social_ingestion_cursors.consecutive_failure_count + 1,
                            next_eligible_poll_at = EXCLUDED.next_eligible_poll_at,
                            last_error_type = EXCLUDED.last_error_type,
                            updated_at = now()
                        """,
                        (str(subscription_id), failed_at, next_eligible_poll_at, error_type),
                    )

    def record_social_observation(
        self,
        *,
        document: SocialDocument,
        source: SocialSource,
        resolution: PlayerResolution,
        entity_type: SocialEntityType,
        team_name: str | None,
        classification: SocialObservationClassification,
        classifier_version: str,
        observation_status: SocialObservationStatus,
    ) -> UUID:
        document_id = document.metadata.get("document_id")
        if document_id is None:
            raise ValueError("persisted social document id is required")
        resolution_confidence = {
            "RESOLVED": 1.0,
            "AMBIGUOUS": 0.5,
            "UNRESOLVED": 0.0,
        }[resolution.status.value]
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO social_observations (
                            document_id, classifier_version, resolution_status,
                            entity_type, player_id, team_name, resolution_confidence,
                            candidate_player_ids, matched_aliases, topic, sentiment,
                            sentiment_score, classification_confidence,
                            observation_status, metadata
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s,
                            %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (document_id, classifier_version) DO UPDATE SET
                            resolution_status = EXCLUDED.resolution_status,
                            entity_type = EXCLUDED.entity_type,
                            player_id = EXCLUDED.player_id,
                            team_name = EXCLUDED.team_name,
                            resolution_confidence = EXCLUDED.resolution_confidence,
                            candidate_player_ids = EXCLUDED.candidate_player_ids,
                            matched_aliases = EXCLUDED.matched_aliases,
                            topic = EXCLUDED.topic,
                            sentiment = EXCLUDED.sentiment,
                            sentiment_score = EXCLUDED.sentiment_score,
                            classification_confidence = EXCLUDED.classification_confidence,
                            observation_status = EXCLUDED.observation_status,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
                        RETURNING id
                        """,
                        (
                            str(document_id),
                            classifier_version,
                            resolution.status.value,
                            entity_type.value,
                            None if resolution.player_id is None else str(resolution.player_id),
                            team_name,
                            resolution_confidence,
                            [str(value) for value in resolution.candidate_player_ids],
                            list(resolution.matched_aliases),
                            classification.topic.value,
                            classification.sentiment.value,
                            classification.sentiment_score,
                            classification.confidence,
                            observation_status.value,
                            Json({"matched_rules": list(classification.matched_rules)}),
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RuntimeError("social observation upsert returned no identity")
        return UUID(str(row["id"]))

    def record_injury_observation(
        self,
        *,
        document: SocialDocument,
        source: SocialSource,
        resolution: PlayerResolution,
        classification: InjuryClassification,
        classifier_version: str,
        evidence_status: str,
        social_observation_id: UUID | None = None,
    ) -> bool:
        document_id = document.metadata.get("document_id")
        if document_id is None:
            raise ValueError("persisted social document id is required")
        resolution_confidence = {
            "RESOLVED": 1.0,
            "AMBIGUOUS": 0.5,
            "UNRESOLVED": 0.0,
        }[resolution.status.value]
        window_start = document.published_at if classification.absence_min_days is not None else None
        window_end = (
            None
            if classification.absence_max_days is None
            else document.published_at + timedelta(days=classification.absence_max_days)
        )
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO social_injury_observations (
                            document_id, social_observation_id, classifier_version, resolution_status,
                            player_id, resolution_confidence, candidate_player_ids,
                            matched_aliases, injury_classification,
                            classification_confidence, availability_window_start,
                            availability_window_end, evidence_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (document_id, classifier_version) DO NOTHING
                        RETURNING id
                        """,
                        (
                            str(document_id),
                            None if social_observation_id is None else str(social_observation_id),
                            classifier_version,
                            resolution.status.value,
                            None if resolution.player_id is None else str(resolution.player_id),
                            resolution_confidence,
                            [str(value) for value in resolution.candidate_player_ids],
                            list(resolution.matched_aliases),
                            classification.evidence_kind.value,
                            classification.confidence,
                            window_start,
                            window_end,
                            evidence_status,
                        ),
                    )
                    observation_row = cursor.fetchone()
                    if observation_row is None:
                        return False
                    if evidence_status != "ACTIONABLE" or resolution.player_id is None:
                        return False
                    return self._apply_episode_observation(
                        cursor=cursor,
                        observation_id=UUID(str(observation_row["id"])),
                        document=document,
                        source=source,
                        player_id=resolution.player_id,
                        classification=classification,
                    )

    def _apply_episode_observation(
        self,
        *,
        cursor,
        observation_id: UUID,
        document: SocialDocument,
        source: SocialSource,
        player_id: UUID,
        classification: InjuryClassification,
    ) -> bool:
        cursor.execute(
            """
            SELECT * FROM player_injury_episodes
            WHERE player_id = %s AND expired_at IS NULL
              AND stage <> 'CONFIRMED_RECOVERED'
            ORDER BY started_at DESC, id DESC LIMIT 1
            FOR UPDATE
            """,
            (str(player_id),),
        )
        active_row = cursor.fetchone()
        active = None if active_row is None else _injury_episode(active_row)
        latest_recovered = None
        if active is None:
            cursor.execute(
                """
                SELECT * FROM player_injury_episodes
                WHERE player_id = %s AND stage = 'CONFIRMED_RECOVERED'
                ORDER BY started_at DESC, id DESC LIMIT 1
                """,
                (str(player_id),),
            )
            recovered_row = cursor.fetchone()
            latest_recovered = (
                None if recovered_row is None else _injury_episode(recovered_row)
            )
        decision = InjuryEpisodeStateMachine().decide(
            active_episode=active,
            latest_recovered_episode=latest_recovered,
            classification=classification,
            source_kind=_legacy_source_kind(source.source_category),
            observed_at=document.published_at,
        )
        if decision.action == "IGNORE":
            return False
        stage_before = None if active is None else active.stage.value
        if decision.action == "CREATE":
            cursor.execute(
                """
                INSERT INTO player_injury_episodes (
                    player_id, recurrence_of_episode_id, stage, injury_type,
                    body_area, confidence, started_at, last_evidence_at,
                    expected_absence_until, recovered_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    str(player_id),
                    None
                    if decision.recurrence_of_episode_id is None
                    else str(decision.recurrence_of_episode_id),
                    decision.stage.value if decision.stage else None,
                    decision.injury_type,
                    decision.body_area,
                    decision.confidence,
                    document.published_at,
                    document.published_at,
                    decision.expected_absence_until,
                    document.published_at
                    if decision.stage is InjuryStage.CONFIRMED_RECOVERED
                    else None,
                    decision.expires_at,
                ),
            )
            episode = _injury_episode(cursor.fetchone())
        elif active is not None and decision.action == "UPDATE":
            cursor.execute(
                """
                UPDATE player_injury_episodes SET
                    stage = %s, injury_type = %s, body_area = %s,
                    confidence = %s, last_evidence_at = GREATEST(last_evidence_at, %s),
                    expected_absence_until = %s, recovered_at = %s,
                    expires_at = %s, updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (
                    decision.stage.value if decision.stage else active.stage.value,
                    decision.injury_type,
                    decision.body_area,
                    decision.confidence,
                    document.published_at,
                    decision.expected_absence_until,
                    document.published_at
                    if decision.stage is InjuryStage.CONFIRMED_RECOVERED
                    else active.recovered_at,
                    decision.expires_at or active.expires_at,
                    str(active.id),
                ),
            )
            episode = _injury_episode(cursor.fetchone())
        elif active is not None:
            episode = active
        else:
            return False
        cursor.execute(
            """
            INSERT INTO social_player_injury_episode_evidence (
                injury_episode_id, social_injury_observation_id, social_source_id,
                evidence_kind, stage_before, stage_after, confidence,
                observed_at, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (social_injury_observation_id) DO NOTHING
            """,
            (
                str(episode.id),
                str(observation_id),
                str(source.id),
                classification.evidence_kind.value,
                stage_before,
                episode.stage.value,
                classification.confidence,
                document.published_at,
                Json({"provider": document.provider.value, "external_id": document.external_id}),
            ),
        )
        cursor.execute(
            """
            UPDATE social_injury_observations SET injury_episode_id = %s, updated_at = now()
            WHERE id = %s
            """,
            (str(episode.id), str(observation_id)),
        )
        cursor.execute(
            """
            INSERT INTO player_injury_availability_observations (
                player_id, injury_episode_id, stage, confidence, is_available,
                expected_absence_until, injury_type, body_area, evidence_kind,
                source_account_kind, observed_at
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
                _legacy_source_kind(source.source_category).value,
                document.published_at,
            ),
        )
        return True

    def calculate_signal_snapshots(
        self, calculated_at: datetime, lookback: timedelta
    ) -> int:
        lookback_seconds = max(round(lookback.total_seconds()), 1)
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO player_social_signal_snapshots (
                            player_id, calculated_at, lookback_seconds,
                            trusted_mention_count, credibility_weighted_sentiment,
                            injury_confirmation_count, mention_velocity,
                            corroborating_source_count, signal_confidence,
                            signal_age_seconds, metadata
                        )
                        SELECT
                            observation.player_id,
                            %(calculated_at)s,
                            %(lookback_seconds)s,
                            COUNT(*) FILTER (
                                WHERE source.source_category <> 'COMMUNITY'
                            ),
                            SUM(
                                observation.sentiment_score
                                * observation.classification_confidence
                                * source.trust_weight
                            ) / NULLIF(SUM(
                                observation.classification_confidence * source.trust_weight
                            ), 0),
                            COUNT(*) FILTER (
                                WHERE injury.injury_classification = 'CONFIRMED_INJURY'
                                  AND injury.evidence_status = 'ACTIONABLE'
                            ),
                            COUNT(*)::numeric / GREATEST(%(lookback_seconds)s / 3600.0, 1),
                            COUNT(DISTINCT source.id) FILTER (
                                WHERE source.source_category <> 'COMMUNITY'
                            ),
                            LEAST(1, AVG(
                                observation.classification_confidence * source.trust_weight
                            )),
                            GREATEST(
                                0,
                                EXTRACT(EPOCH FROM (%(calculated_at)s - MAX(document.published_at)))
                            )::integer,
                            jsonb_build_object(
                                'sentiment_available', true,
                                'positive_mentions', COUNT(*) FILTER (
                                    WHERE observation.sentiment = 'POSITIVE'
                                ),
                                'negative_mentions', COUNT(*) FILTER (
                                    WHERE observation.sentiment = 'NEGATIVE'
                                ),
                                'neutral_mentions', COUNT(*) FILTER (
                                    WHERE observation.sentiment = 'NEUTRAL'
                                ),
                                'mixed_mentions', COUNT(*) FILTER (
                                    WHERE observation.sentiment = 'MIXED'
                                )
                            )
                        FROM social_observations AS observation
                        JOIN social_documents AS document ON document.id = observation.document_id
                        JOIN social_sources AS source ON source.id = document.source_id
                        LEFT JOIN social_injury_observations AS injury
                          ON injury.social_observation_id = observation.id
                         AND injury.invalidated_at IS NULL
                        WHERE observation.player_id IS NOT NULL
                          AND observation.invalidated_at IS NULL
                          AND observation.observation_status IN ('INCLUDED', 'AGGREGATE_ONLY')
                          AND document.deleted_at IS NULL
                          AND document.published_at > %(calculated_at)s - %(lookback)s
                          AND document.published_at <= %(calculated_at)s
                        GROUP BY observation.player_id
                        ON CONFLICT (player_id, calculated_at, lookback_seconds) DO UPDATE SET
                            trusted_mention_count = EXCLUDED.trusted_mention_count,
                            credibility_weighted_sentiment = EXCLUDED.credibility_weighted_sentiment,
                            injury_confirmation_count = EXCLUDED.injury_confirmation_count,
                            mention_velocity = EXCLUDED.mention_velocity,
                            corroborating_source_count = EXCLUDED.corroborating_source_count,
                            signal_confidence = EXCLUDED.signal_confidence,
                            signal_age_seconds = EXCLUDED.signal_age_seconds,
                            metadata = EXCLUDED.metadata
                        """,
                        {
                            "calculated_at": calculated_at,
                            "lookback": lookback,
                            "lookback_seconds": lookback_seconds,
                        },
                    )
                    return cursor.rowcount

    def enforce_retention(self, as_of: datetime) -> int:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT enforce_social_retention(%s)", (as_of,))
                    row = cursor.fetchone()
        return 0 if row is None else int(row[0])

    def claim_article_enrichments(
        self, *, limit: int, subscription_id: UUID | None = None
    ) -> list[ArticleEnrichmentCandidate]:
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        WITH claimed AS (
                            SELECT enrichment.document_id
                            FROM social_document_enrichments enrichment
                            JOIN social_documents document
                              ON document.id = enrichment.document_id
                            JOIN social_sources source ON source.id = document.source_id
                            WHERE enrichment.status = 'PENDING'
                              AND enrichment.available_at <= now()
                              AND (
                                  enrichment.claimed_at IS NULL
                                  OR enrichment.claimed_at < now() - interval '15 minutes'
                              )
                              AND document.deleted_at IS NULL
                              AND (%s::uuid IS NULL OR document.subscription_id = %s::uuid)
                              AND source.enabled
                              AND source.policy_status = 'APPROVED'
                              AND COALESCE(
                                  (source.metadata->'article_enrichment'->>'enabled')::boolean,
                                  false
                              )
                            ORDER BY
                                CASE WHEN %s::uuid IS NOT NULL
                                     THEN document.ingested_at END DESC,
                                enrichment.available_at,
                                enrichment.document_id
                            FOR UPDATE OF enrichment SKIP LOCKED
                            LIMIT %s
                        )
                        UPDATE social_document_enrichments enrichment
                        SET claimed_at = now(), updated_at = now()
                        FROM claimed
                        WHERE enrichment.document_id = claimed.document_id
                        RETURNING enrichment.document_id
                        """,
                        (
                            None if subscription_id is None else str(subscription_id),
                            None if subscription_id is None else str(subscription_id),
                            None if subscription_id is None else str(subscription_id),
                            limit,
                        ),
                    )
                    ids = [str(row["document_id"]) for row in cursor.fetchall()]
                    if not ids:
                        return []
                    cursor.execute(
                        """
                        SELECT
                            document.id AS document_id,
                            document.canonical_url,
                            source.metadata->'article_enrichment'->'allowed_hosts'
                                AS allowed_hosts,
                            source.metadata->'article_enrichment'->>'max_article_bytes'
                                AS max_article_bytes
                        FROM social_documents document
                        JOIN social_sources source ON source.id = document.source_id
                        WHERE document.id = ANY(%s::uuid[])
                        """,
                        (ids,),
                    )
                    rows = cursor.fetchall()
        candidates: list[ArticleEnrichmentCandidate] = []
        for row in rows:
            raw_hosts = row["allowed_hosts"]
            allowed_hosts = (
                tuple(str(host) for host in raw_hosts)
                if isinstance(raw_hosts, list)
                else ()
            )
            candidates.append(
                ArticleEnrichmentCandidate(
                    document_id=UUID(str(row["document_id"])),
                    canonical_url=str(row["canonical_url"]),
                    allowed_hosts=allowed_hosts,
                    max_response_bytes=int(row["max_article_bytes"] or 1_500_000),
                )
            )
        return candidates

    def complete_article_enrichment(
        self,
        document_id: UUID,
        *,
        article_text: str,
        final_url: str,
        http_status: int,
        extraction_method: str,
    ) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE social_documents
                        SET enriched_text = %s,
                            normalized_text = source_text || E'\\n\\n' || %s,
                            content_hash = encode(
                                sha256(convert_to(source_text || E'\\n\\n' || %s, 'UTF8')),
                                'hex'
                            ),
                            provider_metadata = provider_metadata || jsonb_build_object(
                                'article_url', %s,
                                'article_extraction_method', %s
                            )
                        WHERE id = %s AND deleted_at IS NULL
                        """,
                        (
                            article_text,
                            article_text,
                            article_text,
                            final_url,
                            extraction_method,
                            str(document_id),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("article enrichment document is unavailable")
                    cursor.execute(
                        """
                        UPDATE social_document_enrichments
                        SET status = 'SUCCEEDED',
                            claimed_at = NULL,
                            attempt_count = attempt_count + 1,
                            completed_at = now(),
                            final_url = %s,
                            http_status = %s,
                            extraction_method = %s,
                            extracted_characters = %s,
                            last_error = NULL,
                            updated_at = now()
                        WHERE document_id = %s AND status = 'PENDING'
                        """,
                        (
                            final_url,
                            http_status,
                            extraction_method,
                            len(article_text),
                            str(document_id),
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE social_document_processing_queue
                        SET available_at = now(), claimed_at = NULL, processed_at = NULL,
                            failure_count = 0, last_error = NULL
                        WHERE document_id = %s
                        """,
                        (str(document_id),),
                    )

    def skip_article_enrichment(self, document_id: UUID, reason: str) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE social_document_enrichments
                        SET status = 'SKIPPED', claimed_at = NULL,
                            attempt_count = attempt_count + 1, completed_at = now(),
                            last_error = %s, updated_at = now()
                        WHERE document_id = %s AND status = 'PENDING'
                        """,
                        (reason[:500], str(document_id)),
                    )

    def fail_article_enrichment(self, document_id: UUID, reason: str) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE social_document_enrichments
                        SET status = CASE WHEN attempt_count + 1 >= 3
                                          THEN 'FAILED' ELSE 'PENDING' END,
                            claimed_at = NULL,
                            attempt_count = attempt_count + 1,
                            completed_at = CASE WHEN attempt_count + 1 >= 3
                                                THEN now() ELSE NULL END,
                            last_error = %s,
                            available_at = now() + LEAST(
                                interval '30 minutes',
                                interval '30 seconds' * power(2, LEAST(attempt_count, 6))
                            ),
                            updated_at = now()
                        WHERE document_id = %s AND status = 'PENDING'
                        """,
                        (reason[:500], str(document_id)),
                    )

    def claim_documents(
        self, *, limit: int, subscription_id: UUID | None = None
    ) -> list[tuple[SocialDocument, SocialSource]]:
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        WITH claimed AS (
                            SELECT queue.document_id
                            FROM social_document_processing_queue AS queue
                            WHERE queue.processed_at IS NULL
                              AND queue.available_at <= now()
                              AND (
                                  %s::uuid IS NULL
                                  OR EXISTS (
                                      SELECT 1 FROM social_documents scoped_document
                                      WHERE scoped_document.id = queue.document_id
                                        AND scoped_document.subscription_id = %s::uuid
                                  )
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM social_document_enrichments enrichment
                                  WHERE enrichment.document_id = queue.document_id
                                    AND enrichment.status = 'PENDING'
                              )
                              AND (
                                  queue.claimed_at IS NULL
                                  OR queue.claimed_at < now() - interval '15 minutes'
                              )
                            ORDER BY
                                CASE WHEN %s::uuid IS NOT NULL THEN (
                                    SELECT scoped_document.ingested_at
                                    FROM social_documents scoped_document
                                    WHERE scoped_document.id = queue.document_id
                                ) END DESC,
                                queue.available_at,
                                queue.document_id
                            FOR UPDATE SKIP LOCKED
                            LIMIT %s
                        )
                        UPDATE social_document_processing_queue AS queue
                        SET claimed_at = now()
                        FROM claimed
                        WHERE queue.document_id = claimed.document_id
                        RETURNING queue.document_id
                        """,
                        (
                            None if subscription_id is None else str(subscription_id),
                            None if subscription_id is None else str(subscription_id),
                            None if subscription_id is None else str(subscription_id),
                            limit,
                        ),
                    )
                    ids = [str(row["document_id"]) for row in cursor.fetchall()]
                    if not ids:
                        return []
                    cursor.execute(
                        """
                        SELECT
                            document.*,
                            document.id AS document_record_id,
                            document.provider AS document_provider,
                            source.id AS social_source_id,
                            source.provider AS source_provider,
                            source.external_source_id AS source_external_source_id,
                            source.display_handle AS source_display_handle,
                            source.canonical_url AS source_canonical_url,
                            source.source_category,
                            source.trust_weight,
                            source.enabled AS source_enabled,
                            source.policy_status,
                            source.terms_reviewed_at,
                            source.retention_days,
                            source.approved_by,
                            source.approved_at,
                            source.metadata AS source_metadata
                        FROM social_documents AS document
                        JOIN social_sources AS source ON source.id = document.source_id
                        WHERE document.id = ANY(%s::uuid[])
                        """,
                        (ids,),
                    )
                    rows = cursor.fetchall()
        return [(_document(row), _source_from_join(row)) for row in rows]

    def complete_document(self, document_id: UUID) -> None:
        self._finish_document(document_id, None)

    def fail_document(self, document_id: UUID, reason: str) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE social_document_processing_queue
                        SET claimed_at = NULL,
                            failure_count = failure_count + 1,
                            last_error = %s,
                            available_at = now() + LEAST(
                                interval '6 hours',
                                interval '30 seconds' * power(2, LEAST(failure_count, 10))
                            )
                        WHERE document_id = %s AND processed_at IS NULL
                        """,
                        (reason[:200], str(document_id)),
                    )

    def _finish_document(self, document_id: UUID, reason: str | None) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE social_document_processing_queue
                        SET processed_at = now(), last_error = %s
                        WHERE document_id = %s
                        """,
                        (reason, str(document_id)),
                    )


def _source(row: Mapping[str, object]) -> SocialSource:
    return SocialSource(
        id=UUID(str(row["id"])),
        provider=SocialProvider(str(row["provider"])),
        external_source_id=str(row["external_source_id"]),
        display_handle=_optional_string(row["display_handle"]),
        canonical_url=str(row["canonical_url"]),
        source_category=SocialSourceCategory(str(row["source_category"])),
        trust_weight=float(row["trust_weight"]),
        enabled=bool(row["enabled"]),
        policy_status=SocialPolicyStatus(str(row["policy_status"])),
        terms_reviewed_at=row["terms_reviewed_at"],  # type: ignore[arg-type]
        retention_days=int(row["retention_days"]),
        approved_by=str(row["approved_by"]),
        approved_at=row["approved_at"],  # type: ignore[arg-type]
        metadata=row["metadata"] if isinstance(row["metadata"], Mapping) else {},
    )


def _source_from_join(row: Mapping[str, object]) -> SocialSource:
    return SocialSource(
        id=UUID(str(row["social_source_id"])),
        provider=SocialProvider(str(row["source_provider"])),
        external_source_id=str(row["source_external_source_id"]),
        display_handle=_optional_string(row["source_display_handle"]),
        canonical_url=str(row["source_canonical_url"]),
        source_category=SocialSourceCategory(str(row["source_category"])),
        trust_weight=float(row["trust_weight"]),
        enabled=bool(row["source_enabled"]),
        policy_status=SocialPolicyStatus(str(row["policy_status"])),
        terms_reviewed_at=row["terms_reviewed_at"],  # type: ignore[arg-type]
        retention_days=int(row["retention_days"]),
        approved_by=str(row["approved_by"]),
        approved_at=row["approved_at"],  # type: ignore[arg-type]
        metadata=(
            row["source_metadata"] if isinstance(row["source_metadata"], Mapping) else {}
        ),
    )


def _subscription(row: Mapping[str, object]) -> SocialSubscription:
    return SocialSubscription(
        id=UUID(str(row["id"])),
        source_id=UUID(str(row["source_id"])),
        provider=SocialProvider(str(row["provider"])),
        mode=SocialSubscriptionMode(str(row["mode"])),
        configuration=(
            row["configuration"] if isinstance(row["configuration"], Mapping) else {}
        ),
        polling_interval=timedelta(seconds=int(row["polling_interval_seconds"])),
        enabled=bool(row["enabled"]),
        next_eligible_poll_at=row["next_eligible_poll_at"],  # type: ignore[arg-type]
    )


def _document(row: Mapping[str, object]) -> SocialDocument:
    metadata = row["provider_metadata"] if isinstance(row["provider_metadata"], Mapping) else {}
    source_text = str(row["source_text"])
    enriched_text = _optional_string(row["enriched_text"])
    return SocialDocument(
        provider=SocialProvider(str(row["document_provider"])),
        external_id=str(row["external_id"]),
        source_id=UUID(str(row["source_id"])),
        document_kind=SocialDocumentKind(str(row["document_kind"])),
        author_external_id=_optional_string(row["author_external_id"]),
        text=str(row["normalized_text"]),
        published_at=row["published_at"],  # type: ignore[arg-type]
        canonical_url=str(row["canonical_url"]),
        language=_optional_string(row["language"]),
        metadata={
            **metadata,
            "document_id": str(row["document_record_id"]),
            "source_text": source_text,
            "enriched_text": enriched_text,
        },
    )


def _injury_episode(row: Mapping[str, object]) -> InjuryEpisode:
    return InjuryEpisode(
        id=UUID(str(row["id"])),
        player_id=UUID(str(row["player_id"])),
        stage=InjuryStage(str(row["stage"])),
        started_at=row["started_at"],  # type: ignore[arg-type]
        last_evidence_at=row["last_evidence_at"],  # type: ignore[arg-type]
        expected_absence_until=row["expected_absence_until"],  # type: ignore[arg-type]
        expires_at=row["expires_at"],  # type: ignore[arg-type]
        confidence=float(row["confidence"]),
        injury_type=_optional_string(row["injury_type"]),
        body_area=_optional_string(row["body_area"]),
        recurrence_of_episode_id=(
            None
            if row["recurrence_of_episode_id"] is None
            else UUID(str(row["recurrence_of_episode_id"]))
        ),
        recovered_at=row["recovered_at"],  # type: ignore[arg-type]
        expired_at=row["expired_at"],  # type: ignore[arg-type]
    )


def _legacy_source_kind(category: SocialSourceCategory) -> SourceAccountKind:
    return {
        SocialSourceCategory.OFFICIAL_CLUB: SourceAccountKind.OFFICIAL_CLUB,
        SocialSourceCategory.OFFICIAL_LEAGUE: SourceAccountKind.OFFICIAL_LEAGUE,
        SocialSourceCategory.PLAYER: SourceAccountKind.PLAYER_OWNED,
        SocialSourceCategory.JOURNALIST: SourceAccountKind.CURATED_JOURNALIST,
        SocialSourceCategory.NEWS_ORGANISATION: SourceAccountKind.CURATED_JOURNALIST,
        SocialSourceCategory.COMMUNITY: SourceAccountKind.FAN,
    }[category]


def _pop_string(payload: dict[str, object] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.pop(key, None)
    return value if isinstance(value, str) else None


def _rate_limit_payload(value: RateLimitState | None) -> dict[str, object]:
    if value is None:
        return {}
    return {
        "limit": value.limit,
        "remaining": value.remaining,
        "reset_at": None if value.reset_at is None else value.reset_at.isoformat(),
        "metadata": dict(value.metadata),
    }


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
