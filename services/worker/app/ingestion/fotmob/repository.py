from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from psycopg2.extras import Json

from app.database import connection
from app.ingestion.market_values.repository import PostgresMarketValueRepository

from .client import match_page_url
from .matching import FotMobIdentity, resolve_identity, source_name_counts
from .parsing import PlayerRating, is_finished, timestamp


class FotMobRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def save_document(self, url: str, body: str, content_type: str):
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO provider_raw_documents
                    (provider, source_url, content_hash, body, status_code, content_type)
                VALUES ('FOTMOB', %s, %s, %s, 200, %s)
                ON CONFLICT (provider, source_url, content_hash)
                DO UPDATE SET last_seen_at = now()
            """,
                (url, hashlib.sha256(body.encode()).hexdigest(), body, content_type),
            )

    def discover(self, matches: list[dict], league: int, season: int):
        with connection(self.database_url) as conn, conn.cursor() as cur:
            for match in matches:
                cur.execute(
                    """
                    INSERT INTO fotmob_matches
                        (match_id, league_id, season, kickoff_at, home_team_id, home_team_name,
                         away_team_id, away_team_name, finished, first_finished_at,
                         source_url, raw_fixture)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s THEN now() END,%s,%s)
                    ON CONFLICT (match_id) DO UPDATE SET
                        kickoff_at=EXCLUDED.kickoff_at, finished=EXCLUDED.finished,
                        first_finished_at=CASE WHEN EXCLUDED.finished THEN
                            COALESCE(fotmob_matches.first_finished_at, now()) END,
                        raw_fixture=EXCLUDED.raw_fixture, source_url=EXCLUDED.source_url,
                        discovered_at=now()
                """,
                    (
                        str(match["id"]),
                        league,
                        season,
                        timestamp(match["status"]["utcTime"]),
                        str(match["home"]["id"]),
                        match["home"]["name"],
                        str(match["away"]["id"]),
                        match["away"]["name"],
                        is_finished(match),
                        is_finished(match),
                        match_page_url(match),
                        Json(match),
                    ),
                )

    def due(
        self,
        league: int,
        season: int,
        *,
        backfill: bool,
        refresh: bool,
        limit: int | None,
        now: datetime,
    ) -> list[dict]:
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT raw_fixture FROM fotmob_matches
                WHERE league_id=%s AND season=%s AND finished AND kickoff_at < %s
                  AND (%s OR first_finished_at <= %s)
                  AND (%s OR ratings_fetched_at IS NULL OR
                       (NOT %s AND kickoff_at >= %s AND ratings_fetched_at <= %s))
                ORDER BY ratings_fetched_at NULLS FIRST, last_attempt_at NULLS FIRST, kickoff_at
                LIMIT %s
            """,
                (
                    league,
                    season,
                    now,
                    backfill,
                    now - timedelta(minutes=15),
                    refresh,
                    backfill,
                    now - timedelta(days=2),
                    now - timedelta(hours=6),
                    limit,
                ),
            )
            return [row[0] for row in cur.fetchall()]

    def save_ratings(self, fixture: dict, ratings: list[PlayerRating], source_url: str) -> int:
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT provider_player_id, player_id::text FROM player_provider_refs WHERE provider='FOTMOB'"
            )
            refs = dict(cur.fetchall())
            matched = 0
            for rating in ratings:
                player_id = refs.get(rating.player_id)
                matched += player_id is not None
                cur.execute(
                    """
                    INSERT INTO player_match_ratings
                        (provider_match_id,provider_player_id,player_id,display_name,
                         team_provider_id,team_name,rating,minutes_played,source_url,raw_payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (provider,provider_match_id,provider_player_id) DO UPDATE SET
                        player_id=COALESCE(EXCLUDED.player_id,player_match_ratings.player_id),
                        display_name=EXCLUDED.display_name,team_provider_id=EXCLUDED.team_provider_id,
                        team_name=EXCLUDED.team_name,rating=EXCLUDED.rating,
                        minutes_played=EXCLUDED.minutes_played,source_url=EXCLUDED.source_url,
                        raw_payload=EXCLUDED.raw_payload,updated_at=now()
                """,
                    (
                        str(fixture["id"]),
                        rating.player_id,
                        player_id,
                        rating.name,
                        rating.team_id,
                        rating.team_name,
                        rating.rating,
                        rating.minutes,
                        source_url,
                        Json(rating.raw),
                    ),
                )
            cur.execute(
                """
                UPDATE fotmob_matches SET ratings_fetched_at=now(),last_attempt_at=now(),last_error=NULL
                WHERE match_id=%s
            """,
                (str(fixture["id"]),),
            )
            return matched

    def missing_profile_ids(self) -> list[str]:
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT provider_player_id FROM fotmob_player_identity_matches
                WHERE match_status <> 'MATCHED'
                  AND evidence->>'profile_checked_at' IS NULL
                ORDER BY provider_player_id
            """)
            return [row[0] for row in cur.fetchall()]

    def record_profile(self, player_id: str, source_url: str, profile: dict) -> None:
        birth = profile.get("birthDate") or {}
        raw_date = birth.get("utcTime")
        birth_date = (
            datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date() if raw_date else None
        )
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fotmob_player_identity_matches
                SET evidence=evidence || %s::jsonb, updated_at=now()
                WHERE provider_player_id=%s
            """,
                (
                    Json(
                        {
                            "profile_url": source_url,
                            "profile_checked_at": datetime.now(UTC).isoformat(),
                            "date_of_birth": birth_date.isoformat() if birth_date else None,
                        }
                    ),
                    player_id,
                ),
            )

    def reconcile_player_matches(self) -> dict[str, int]:
        """Apply market-value identity rules to every historical FotMob player ID.

        Recheck the automatic name-only links created by the initial ingester, while
        preserving provider references that were reviewed or assigned externally.
        """
        candidates = PostgresMarketValueRepository(self.database_url).list_player_candidates()
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT provider_player_id, display_name, team_name
                FROM player_match_ratings WHERE provider='FOTMOB'
                ORDER BY provider_player_id, display_name, team_name
            """)
            evidence_by_id: dict[str, list[FotMobIdentity]] = defaultdict(list)
            for source_id, name, club in cur.fetchall():
                evidence_by_id[source_id].append(FotMobIdentity(source_id, name, club))
            counts = source_name_counts(
                item for evidence in evidence_by_id.values() for item in evidence
            )
            cur.execute("""
                SELECT provider_player_id, player_id::text, raw_identity
                FROM player_provider_refs WHERE provider='FOTMOB'
            """)
            refs = {row[0]: (UUID(row[1]), row[2] or {}) for row in cur.fetchall()}
            cur.execute("SELECT provider_player_id, evidence FROM fotmob_player_identity_matches")
            previous_evidence = dict(cur.fetchall())
            statuses = {"MATCHED": 0, "AMBIGUOUS": 0, "UNMATCHED": 0}
            changed_links = 0
            for source_id, evidence in evidence_by_id.items():
                ref = refs.get(source_id)
                automatic = ref is not None and (
                    ref[1].get("method") == "unique_normalized_name"
                    or ref[1].get("matcher") == "market_value_identity_v1"
                )
                trusted_ref = None if ref is None or automatic else ref[0]
                profile = previous_evidence.get(source_id, {})
                birth_date = (
                    date.fromisoformat(profile["date_of_birth"])
                    if profile.get("date_of_birth")
                    else None
                )
                match = resolve_identity(
                    evidence,
                    candidates=candidates,
                    name_counts=counts,
                    date_of_birth=birth_date,
                    trusted_ref=trusted_ref,
                )
                statuses[match.status.value] += 1
                names = sorted({item.name for item in evidence})
                clubs = sorted({item.club for item in evidence})
                identity = {
                    **profile,
                    "matcher": "market_value_identity_v1",
                    "reason": match.reason,
                    "names": names,
                    "clubs": clubs,
                }
                if match.player_id is not None and trusted_ref is None:
                    cur.execute(
                        """
                        INSERT INTO player_provider_refs
                            (provider,provider_player_id,player_id,provider_url,
                             confidence,is_primary,raw_identity)
                        VALUES ('FOTMOB',%s,%s,%s,%s,false,%s)
                        ON CONFLICT (provider,provider_player_id) DO UPDATE SET
                            player_id=EXCLUDED.player_id,
                            confidence=EXCLUDED.confidence,
                            raw_identity=EXCLUDED.raw_identity,last_seen_at=now()
                        WHERE player_provider_refs.raw_identity->>'method'='unique_normalized_name'
                           OR player_provider_refs.raw_identity->>'matcher'='market_value_identity_v1'
                    """,
                        (
                            source_id,
                            str(match.player_id),
                            f"https://www.fotmob.com/players/{source_id}",
                            match.confidence,
                            Json(identity),
                        ),
                    )
                elif match.player_id is None and automatic:
                    cur.execute(
                        """
                        DELETE FROM player_provider_refs
                        WHERE provider='FOTMOB' AND provider_player_id=%s
                          AND (raw_identity->>'method'='unique_normalized_name'
                            OR raw_identity->>'matcher'='market_value_identity_v1')
                    """,
                        (source_id,),
                    )
                cur.execute(
                    """
                    UPDATE player_match_ratings SET player_id=%s, updated_at=now()
                    WHERE provider='FOTMOB' AND provider_player_id=%s
                      AND player_id IS DISTINCT FROM %s
                """,
                    (
                        str(match.player_id) if match.player_id else None,
                        source_id,
                        str(match.player_id) if match.player_id else None,
                    ),
                )
                changed_links += cur.rowcount
                cur.execute(
                    """
                    INSERT INTO fotmob_player_identity_matches
                        (provider_player_id,player_id,match_status,match_confidence,
                         match_reason,source_names,source_clubs,evidence)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (provider_player_id) DO UPDATE SET
                        player_id=EXCLUDED.player_id,
                        match_status=EXCLUDED.match_status,
                        match_confidence=EXCLUDED.match_confidence,
                        match_reason=EXCLUDED.match_reason,
                        source_names=EXCLUDED.source_names,
                        source_clubs=EXCLUDED.source_clubs,
                        evidence=EXCLUDED.evidence,updated_at=now()
                """,
                    (
                        source_id,
                        str(match.player_id) if match.player_id else None,
                        match.status.value,
                        match.confidence,
                        match.reason,
                        names,
                        clubs,
                        Json(identity),
                    ),
                )
            return {**statuses, "changed_appearances": changed_links}

    def record_error(self, match_id: str, error: str):
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE fotmob_matches SET last_attempt_at=now(),last_error=%s WHERE match_id=%s",
                (error[:1000], match_id),
            )

    def coverage(self, league: int, season: int) -> dict:
        with connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*),count(*) FILTER (WHERE finished),
                       count(*) FILTER (WHERE finished AND ratings_fetched_at IS NOT NULL),
                       count(*) FILTER (WHERE finished AND ratings_fetched_at IS NULL)
                FROM fotmob_matches WHERE league_id=%s AND season=%s
            """,
                (league, season),
            )
            coverage_row = cur.fetchone()
            assert coverage_row is not None
            result: dict[str, int] = dict(
                zip(
                    ("fixtures", "finished_matches", "ingested_matches", "pending_matches"),
                    coverage_row,
                )
            )
            cur.execute(
                """
                SELECT count(*),count(rating),count(player_id),count(DISTINCT provider_player_id)
                FROM player_match_ratings r JOIN fotmob_matches m ON m.match_id=r.provider_match_id
                WHERE m.league_id=%s AND m.season=%s
            """,
                (league, season),
            )
            ratings_row = cur.fetchone()
            assert ratings_row is not None
            result.update(
                zip(("appearances", "ratings", "linked_appearances", "players"), ratings_row)
            )
            return result
