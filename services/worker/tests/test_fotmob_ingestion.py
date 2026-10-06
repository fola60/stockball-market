from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from app.ingestion.fotmob import FotMobClient, FotMobError, FotMobIngestionService
from app.ingestion.fotmob.matching import FotMobIdentity, resolve_identity, source_name_counts
from app.ingestion.fotmob.parsing import is_finished, parse_ratings
from app.ingestion.market_values.matching import PlayerCandidate
from app.jobs.fotmob import FotMobRatingsJobHandler
from app.jobs.models import JobType, WorkerJob
from app.queue import JobRoutingQueue
from app.scheduler.models import FotMobRatingsIngestionPlan


@pytest.fixture
def match_data():
    status = {"finished": True, "utcTime": "2025-08-15T19:00:00Z"}
    fixture = {
        "id": "123",
        "home": {"id": 1, "name": "Home"},
        "away": {"id": 2, "name": "Away"},
        "status": status,
    }
    players = {
        str(i): {
            "id": i,
            "name": f"Player {i}",
            "teamId": 1 if i < 12 else 2,
            "stats": [
                {
                    "stats": {
                        "Rating": {"key": "rating_title", "stat": {"value": 7.42}},
                        "Minutes": {"key": "minutes_played", "stat": {"value": 90}},
                    }
                }
            ],
        }
        for i in range(1, 23)
    }
    data = {
        "general": {
            "matchId": "123",
            "leagueId": 47,
            "finished": True,
            "matchTimeUTCDate": status["utcTime"],
            "homeTeam": {"id": 1},
            "awayTeam": {"id": 2},
        },
        "header": {"status": status},
        "content": {
            "playerStats": players,
            "lineup": {
                "homeTeam": {"starters": [{"id": i} for i in range(1, 12)]},
                "awayTeam": {"starters": [{"id": i} for i in range(12, 23)]},
            },
        },
    }
    return fixture, data


def test_rating_precision_unrated_and_unused_substitutes(match_data):
    fixture, data = match_data
    players = data["content"]["playerStats"]
    players["1"]["stats"][0]["stats"]["Rating"]["stat"]["value"] = None
    players["23"] = {"id": 23, "name": "Unused sub", "teamId": 1, "stats": []}
    rows = parse_ratings(data, fixture, 47)
    assert len(rows) == 22
    assert rows[0].rating is None
    assert rows[1].rating == Decimal("7.42")
    assert rows[1].minutes == 90


@pytest.mark.parametrize("value", ["NaN", "Infinity", -1, 10.01, "bad"])
def test_invalid_rating_never_stored(match_data, value):
    fixture, data = match_data
    data["content"]["playerStats"]["1"]["stats"][0]["stats"]["Rating"]["stat"]["value"] = value
    with pytest.raises(FotMobError):
        parse_ratings(data, fixture, 47)


@pytest.mark.parametrize(
    "field,value",
    [
        ("matchId", "999"),
        ("leagueId", 9),
        ("finished", False),
        ("matchTimeUTCDate", "2026-08-15T19:00:00Z"),
    ],
)
def test_rejects_latest_meeting_and_wrong_match_context(match_data, field, value):
    fixture, data = match_data
    data["general"][field] = value
    with pytest.raises(FotMobError):
        parse_ratings(data, fixture, 47)


def test_partial_statistics_remain_pending(match_data):
    fixture, data = match_data
    del data["content"]["playerStats"]["12"]
    with pytest.raises(FotMobError, match="Incomplete"):
        parse_ratings(data, fixture, 47)


@pytest.mark.parametrize(
    "status",
    [
        {"finished": False},
        {"finished": True, "cancelled": True},
        {"finished": True, "awarded": True},
        {"finished": True, "reason": {"short": "Ab"}},
    ],
)
def test_only_played_final_matches_qualify(status):
    assert not is_finished({"status": status})


def test_fixture_season_fallback_fails_closed():
    client = FotMobClient(interval_seconds=0)
    client._get = Mock(
        return_value='<script id="__NEXT_DATA__">'
        + json.dumps(
            {
                "props": {
                    "pageProps": {
                        "details": {"id": 47, "selectedSeason": "2026/2027"},
                        "fixtures": {"allMatches": [{"id": "1"}]},
                    }
                }
            }
        )
        + "</script>"
    )
    with pytest.raises(FotMobError, match="wrong league/season"):
        client.fixtures(47, 2025)
    client.close()


def test_archive_checks_match_identity(tmp_path):
    (tmp_path / "123.json").write_text('{"general":{"matchId":"999"}}')
    client = FotMobClient(archive_dir=tmp_path)
    with pytest.raises(FotMobError, match="different match"):
        client.match("123")
    client.close()


def test_refresh_ignores_archive(tmp_path, match_data):
    (tmp_path / "123.json").write_text("{}")
    client = FotMobClient(archive_dir=tmp_path)
    client._get = Mock(return_value=json.dumps(match_data[1]))
    assert client.match("123", refresh=True)[2]["general"]["matchId"] == "123"
    client._get.assert_called_once()
    client.close()


def test_failed_match_does_not_prevent_later_matches_or_checkpoint(match_data):
    fixture, data = match_data
    second = copy.deepcopy(fixture)
    second["id"] = "124"
    repository = Mock()
    repository.due.return_value = [second, fixture]
    repository.coverage.return_value = {}
    repository.save_ratings.return_value = 22
    repository.reconcile_player_matches.return_value = {"MATCHED": 22}
    repository.missing_profile_ids.return_value = []
    client = Mock()
    client.fixtures.return_value = ("url", "body", [second, fixture])
    client.match.side_effect = [httpx.ReadTimeout("timeout"), ("url", "{}", data)]
    result = FotMobIngestionService(client, repository).ingest(season=2025, backfill=True)
    assert result["failed_matches"] == 1
    assert result["processed_matches"] == 1
    repository.save_ratings.assert_called_once()
    repository.record_error.assert_called_once_with("124", "timeout")
    client.close.assert_called_once()


def test_scheduler_rollover_and_ingestion_queue():
    plan = FotMobRatingsIngestionPlan(enabled=True)
    before = datetime(2026, 6, 30, 23, 59, tzinfo=UTC)
    after = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    assert plan.build_job(before).payload["season"] == 2025
    assert plan.build_job(after).payload["season"] == 2026
    assert plan.window_key_for(before).endswith("23:45:00+00:00")
    trading, ingestion = Mock(), Mock()
    JobRoutingQueue(trading_queue=trading, ingestion_queue=ingestion).enqueue(plan.build_job(after))
    ingestion.enqueue.assert_called_once()
    trading.enqueue.assert_not_called()


def test_job_reports_retryable_failures():
    service = Mock()
    service.ingest.return_value = {"upserted_observations": 22, "failed_matches": 1}
    result = FotMobRatingsJobHandler(lambda: service).handle(
        WorkerJob(JobType.INGEST_FOTMOB_RATINGS, {"season": 2025})
    )
    assert result.successful_items == 22
    assert result.retryable_failures == 1


def test_market_value_name_and_club_rules_resolve_duplicate_names():
    source = FotMobIdentity("10", "João Test", "Manchester City")
    candidates = [
        PlayerCandidate(uuid4(), "Joao Test", "Man City", None, None, {}),
        PlayerCandidate(uuid4(), "Joao Test", "Arsenal", None, None, {}),
    ]
    match = resolve_identity(
        [source], candidates=candidates, name_counts=source_name_counts([source])
    )
    assert match.player_id == candidates[0].player_id
    assert match.reason == "name_and_club"
    assert match.confidence == Decimal("0.850")


def test_distinct_source_ids_block_name_only_matching():
    source = FotMobIdentity("10", "Same Name", "Unknown Club")
    another = FotMobIdentity("11", "Same Name", "Other Club")
    candidate = PlayerCandidate(uuid4(), "Same Name", "Arsenal", None, None, {})
    counts = source_name_counts([source, source, another])
    match = resolve_identity([source], candidates=[candidate], name_counts=counts)
    assert match.player_id is None
    assert match.reason == "ambiguous_name_or_club"


def test_conflicting_identity_evidence_remains_ambiguous():
    first = FotMobIdentity("10", "Same Name", "Arsenal")
    second = FotMobIdentity("10", "Same Name", "Chelsea")
    candidates = [
        PlayerCandidate(uuid4(), "Same Name", "Arsenal", None, None, {}),
        PlayerCandidate(uuid4(), "Same Name", "Chelsea", None, None, {}),
    ]
    match = resolve_identity(
        [first, second], candidates=candidates, name_counts=source_name_counts([first, second])
    )
    assert match.player_id is None
    assert match.reason == "conflicting_name_and_club_evidence"


def test_name_variant_needs_birth_date_and_club():
    source = FotMobIdentity("10", "Alisson Becker", "Liverpool")
    candidate = PlayerCandidate(uuid4(), "Alisson", "Liverpool", date(1992, 10, 2), None, {})
    counts = source_name_counts([source])
    assert resolve_identity([source], candidates=[candidate], name_counts=counts).player_id is None
    match = resolve_identity([source], candidates=[candidate], name_counts=counts,
                             date_of_birth=date(1992, 10, 2))
    assert match.player_id == candidate.player_id
    assert match.reason == "name_variant_date_of_birth_and_club"
    assert match.confidence == Decimal("0.950")
    wrong_club = FotMobIdentity("10", "Alisson Becker", "Chelsea")
    assert resolve_identity([wrong_club], candidates=[candidate], name_counts=counts,
                            date_of_birth=date(1992, 10, 2)).player_id is None


def test_name_variant_with_two_equal_candidates_remains_ambiguous():
    source = FotMobIdentity("10", "Gabriel", "Arsenal")
    candidates = [
        PlayerCandidate(uuid4(), "Gabriel Jesus", "Arsenal", date(1997, 1, 1), None, {}),
        PlayerCandidate(uuid4(), "Gabriel Magalhães", "Arsenal", date(1997, 1, 1), None, {}),
    ]
    match = resolve_identity([source], candidates=candidates,
                             name_counts=source_name_counts([source]),
                             date_of_birth=date(1997, 1, 1))
    assert match.player_id is None
    assert match.reason == "ambiguous_name_or_club"
