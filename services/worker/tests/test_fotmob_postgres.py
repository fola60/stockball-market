"""Opt-in database tests, isolated in a temporary schema with its own copied identity tables."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from app.database import connection
from app.ingestion.fotmob.client import FotMobPlayerImage
from app.ingestion.fotmob.parsing import PlayerRating
from app.ingestion.fotmob.repository import FotMobRepository


@pytest.fixture
def repository():
    url = os.getenv("STOCKBALL_FOTMOB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set STOCKBALL_FOTMOB_TEST_DATABASE_URL to a migrated test database")
    schema = "fotmob_test_" + uuid4().hex
    admin = psycopg2.connect(url)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        for table in ("players", "player_provider_refs", "provider_raw_documents"):
            cur.execute(
                sql.SQL("CREATE TABLE {} (LIKE public.{} INCLUDING ALL)").format(
                    sql.Identifier(table), sql.Identifier(table)
                )
            )
        migrations = Path(__file__).resolve().parents[3] / "infra/postgres/migrations"
        cur.execute((migrations / "0030_fotmob_player_ratings.sql").read_text())
        cur.execute((migrations / "0031_fotmob_player_identity_matches.sql").read_text())
        cur.execute((migrations / "0034_fotmob_player_images.sql").read_text())
    try:
        yield FotMobRepository(make_dsn(url, options=f"-c search_path={schema},public"))
    finally:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def fixture(match_id="123", finished=True):
    return {
        "id": match_id,
        "home": {"id": "1", "name": "Home"},
        "away": {"id": "2", "name": "Away"},
        "pageUrl": f"/matches/example/abc#{match_id}",
        "status": {"finished": finished, "utcTime": "2025-08-15T19:00:00Z"},
    }


def test_retry_delay_resume_and_idempotent_corrections(repository):
    now = datetime.now(UTC)
    match = fixture()
    repository.discover([match, fixture("124", False)], 47, 2025)
    assert repository.due(47, 2025, backfill=False, refresh=False, limit=40, now=now) == []
    assert (
        len(
            repository.due(
                47, 2025, backfill=False, refresh=False, limit=40, now=now + timedelta(minutes=16)
            )
        )
        == 1
    )
    assert len(repository.due(47, 2025, backfill=True, refresh=False, limit=None, now=now)) == 1
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO players(provider,provider_player_id,display_name,club,position) VALUES ('FBREF','p1','João Test','Home','FW') RETURNING id::text"
        )
        player_id = cur.fetchone()[0]
    rating = PlayerRating("10", "Joao Test", "1", "Home", Decimal("7.125"), 90, {})
    assert repository.save_ratings(match, [rating], "url") == 0
    assert repository.reconcile_player_matches()["MATCHED"] == 1
    assert repository.save_ratings(match, [rating], "url") == 1
    assert repository.due(47, 2025, backfill=True, refresh=False, limit=None, now=now) == []
    correction = PlayerRating("10", "Joao Test", "1", "Home", Decimal("7.3"), 90, {})
    repository.save_ratings(match, [correction], "url")
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT player_id::text,rating FROM player_match_ratings")
        assert cur.fetchall() == [(player_id, Decimal("7.3"))]
        cur.execute("SELECT rated_appearances,average_rating FROM player_season_ratings")
        assert cur.fetchone() == (1, Decimal("7.3"))
    coverage = repository.coverage(47, 2025)
    assert coverage["fixtures"] == 2
    assert coverage["ingested_matches"] == 1
    assert coverage["pending_matches"] == 0


def test_ambiguous_players_are_preserved_unlinked_and_failed_matches_retry(repository):
    match = fixture()
    repository.discover([match], 47, 2025)
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO players(provider,provider_player_id,display_name,club,position) VALUES ('FBREF','p1','Same Name','Other','FW'), ('FBREF','p2','Same Name','Other','FW')"
        )
    rating = PlayerRating("10", "Same Name", "1", "Home", None, 5, {})
    assert repository.save_ratings(match, [rating], "url") == 0
    assert repository.reconcile_player_matches()["AMBIGUOUS"] == 1
    repository.discover([fixture("124")], 47, 2025)
    repository.record_error("124", "Incomplete data")
    due = repository.due(47, 2025, backfill=True, refresh=False, limit=None, now=datetime.now(UTC))
    assert [f["id"] for f in due] == ["124"]
    assert repository.coverage(47, 2025)["pending_matches"] == 1


def test_raw_document_deduplication(repository):
    repository.save_document("url", '{"a":1}', "application/json")
    repository.save_document("url", '{"a":1}', "application/json")
    repository.save_document("url", '{"a":2}', "application/json")
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM provider_raw_documents WHERE provider='FOTMOB'")
        assert cur.fetchone()[0] == 2


def test_profile_birth_date_resolves_name_variant_without_guessing(repository):
    match = fixture()
    repository.discover([match], 47, 2025)
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO players(provider,provider_player_id,display_name,club,position,metadata)
            VALUES ('FBREF','p1','Alisson','Liverpool','GK',
                    '{"date_of_birth":"1992-10-02"}') RETURNING id::text
        """)
        player_id = cur.fetchone()[0]
    repository.save_ratings(
        match,
        [PlayerRating("10", "Alisson Becker", "1", "Liverpool", Decimal("7.1"), 90, {})],
        "url",
    )
    assert repository.reconcile_player_matches()["UNMATCHED"] == 1
    assert repository.missing_profile_ids() == ["10"]
    repository.record_profile(
        "10",
        "https://www.fotmob.com/players/10",
        {"birthDate": {"utcTime": "1992-10-02T00:00:00Z"}},
    )
    assert repository.reconcile_player_matches()["MATCHED"] == 1
    assert repository.missing_profile_ids() == []
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT player_id::text FROM player_match_ratings")
        assert cur.fetchone()[0] == player_id
        cur.execute("SELECT match_reason,match_confidence FROM fotmob_player_identity_matches")
        assert cur.fetchone() == ("name_variant_date_of_birth_and_club", Decimal("0.950"))


def test_legacy_automatic_link_is_rechecked_but_reviewed_link_is_preserved(repository):
    match = fixture()
    repository.discover([match], 47, 2025)
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO players(provider,provider_player_id,display_name,club,position)
            VALUES ('FBREF','p1','Same Name','Other','FW') RETURNING id::text
        """)
        first_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO players(provider,provider_player_id,display_name,club,position)
            VALUES ('FBREF','p2','Same Name','Other','FW')
        """)
        cur.execute(
            """
            INSERT INTO player_provider_refs(provider,provider_player_id,player_id,raw_identity)
            VALUES ('FOTMOB','10',%s,'{"method":"unique_normalized_name"}')
        """,
            (first_id,),
        )
    repository.save_ratings(
        match, [PlayerRating("10", "Same Name", "1", "Home", Decimal("6.5"), 90, {})], "url"
    )
    assert repository.reconcile_player_matches()["AMBIGUOUS"] == 1
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT player_id FROM player_match_ratings")
        assert cur.fetchone()[0] is None
        cur.execute("SELECT count(*) FROM player_provider_refs WHERE provider='FOTMOB'")
        assert cur.fetchone()[0] == 0
        cur.execute(
            """
            INSERT INTO player_provider_refs(provider,provider_player_id,player_id,raw_identity)
            VALUES ('FOTMOB','10',%s,'{"method":"manual_review"}')
        """,
            (first_id,),
        )
    assert repository.reconcile_player_matches()["MATCHED"] == 1
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT player_id::text FROM player_match_ratings")
        assert cur.fetchone()[0] == first_id


def test_player_images_are_binary_resumable_and_preserved_on_refresh_failure(repository):
    now = datetime.now(UTC)
    match = fixture()
    repository.discover([match], 47, 2025)
    repository.save_ratings(
        match,
        [
            PlayerRating("10", "One", "1", "Home", Decimal("7"), 90, {}),
            PlayerRating("11", "Two", "1", "Home", Decimal("6"), 90, {}),
        ],
        "url",
    )
    assert repository.due_images(limit=10, now=now) == ["10", "11"]
    image = FotMobPlayerImage(
        "https://images.fotmob.com/image_resources/playerimages/10.png", b"png-data", 192, 192
    )
    repository.save_image("10", image)
    repository.record_image_failure("11", missing=True, error="not found")
    assert repository.due_images(limit=10, now=now + timedelta(days=1)) == []
    assert repository.image_coverage() == {
        "source_players": 2,
        "ready": 1,
        "missing": 1,
        "failed": 0,
        "pending": 0,
    }
    repository.record_image_failure("10", missing=False, error="timeout")
    with connection(repository.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status,image_data,content_sha256,last_error FROM fotmob_player_images "
            "WHERE provider_player_id='10'"
        )
        status, stored, digest, error = cur.fetchone()
        assert status == "READY"
        assert bytes(stored) == b"png-data"
        assert len(digest) == 64
        assert error == "timeout"
    assert repository.due_images(limit=10, now=now + timedelta(days=2)) == ["10"]
