from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from app.ingestion.social.twitter import (
    InjuryClassification,
    InjuryEpisode,
    InjuryEpisodeStateMachine,
    InjuryEvidenceKind,
    InjuryStage,
    PlayerAlias,
    PlayerIdentityCandidate,
    PlayerResolutionStatus,
    PlayerResolver,
    RuleBasedInjuryClassifier,
    SourceAccountKind,
    TwitterIngestionCursor,
    TwitterInjuryIngestionResult,
    TwitterInjuryIngestionService,
    TwitterRateLimit,
    TwitterRecentSearchClient,
    TwitterSearchPage,
    TwitterSourceAccount,
    TwitterTransientError,
    load_registry,
)
from app.ingestion.social.twitter.parser import parse_search_page_html
from app.jobs import (
    IngestTwitterInjuriesJobHandler,
    IngestTwitterInjuriesJobPayload,
    JobType,
    RetryableJobError,
    WorkerJob,
)
from app.scheduler.models import TwitterInjuryIngestionPlan

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
PLAYER_ID = UUID("00000000-0000-0000-0000-000000000101")

_SINGLE_TWEET_HTML = """\
<!DOCTYPE html>
<html><head></head><body>
<article data-testid="tweet">
  <div data-testid="Tweet-User-Avatar">
    <div data-testid="UserAvatar-Container-reporter1">
      <a href="https://x.com/reporter1"></a>
    </div>
  </div>
  <div data-testid="User-Name">
    <a href="https://x.com/reporter1" role="link">
      <span>Reporter One</span>
    </a>
  </div>
  <div data-testid="tweetText">Bukayo Saka returned to training today.</div>
  <time datetime="2026-07-18T11:00:00Z">Jul 18</time>
  <div role="group" aria-label="5 replies, 12 reposts, 80 likes, 3 bookmarks, 1200 views">
  </div>
  <a href="https://x.com/reporter1/status/200"></a>
</article>
</body></html>
"""

_TWO_TWEET_HTML = """\
<!DOCTYPE html>
<html><head></head><body>
<article data-testid="tweet">
  <div data-testid="Tweet-User-Avatar">
    <div data-testid="UserAvatar-Container-reporter1">
      <a href="https://x.com/reporter1"></a>
    </div>
  </div>
  <div data-testid="User-Name">
    <a href="https://x.com/reporter1" role="link">
      <span>Reporter One</span>
    </a>
  </div>
  <div data-testid="tweetText">Saka hamstring update: out for 2-3 weeks.</div>
  <time datetime="2026-07-18T11:00:00Z">Jul 18</time>
  <div role="group" aria-label="10 replies, 20 reposts, 150 likes, 5 bookmarks, 3000 views">
  </div>
  <a href="https://x.com/reporter1/status/300"></a>
</article>
<article data-testid="tweet">
  <div data-testid="Tweet-User-Avatar">
    <div data-testid="UserAvatar-Container-reporter2">
      <a href="https://x.com/reporter2"></a>
    </div>
  </div>
  <div data-testid="User-Name">
    <a href="https://x.com/reporter2" role="link">
      <span>Reporter Two</span>
    </a>
  </div>
  <div data-testid="tweetText">Martin Odegaard back in full training.</div>
  <time datetime="2026-07-18T10:00:00Z">Jul 18</time>
  <div role="group" aria-label="3 replies, 8 reposts, 45 likes, 1 bookmark, 800 views">
  </div>
  <a href="https://x.com/reporter2/status/250"></a>
</article>
</body></html>
"""

_EMPTY_HTML = """\
<!DOCTYPE html>
<html><head></head><body>
<div>Nothing here</div>
</body></html>
"""


def _html_response(html: str) -> bytes:
    return html.encode("utf-8")


class RuleBasedInjuryClassifierTests(unittest.TestCase):
    def test_extracts_confirmed_injury_body_type_and_absence_range(self) -> None:
        result = RuleBasedInjuryClassifier().classify(
            "Bukayo Saka suffered a hamstring strain and will miss 2-3 weeks.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
        )

        self.assertEqual(result.evidence_kind, InjuryEvidenceKind.CONFIRMED_INJURY)
        self.assertEqual(result.body_area, "hamstring")
        self.assertEqual(result.injury_type, "strain")
        self.assertEqual((result.absence_min_days, result.absence_max_days), (14, 21))
        self.assertEqual(result.confidence, 0.94)

    def test_negation_prevents_injury_evidence(self) -> None:
        result = RuleBasedInjuryClassifier().classify(
            "Bukayo Saka is not injured; the injury concern was ruled out.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
        )

        self.assertEqual(result.evidence_kind, InjuryEvidenceKind.NONE)
        self.assertTrue(result.negated)

    def test_fan_evidence_is_aggregate_only_and_confidence_capped(self) -> None:
        result = RuleBasedInjuryClassifier().classify(
            "Bukayo Saka suffered a knee injury and will miss 3 weeks.",
            _source(SourceAccountKind.FAN, trust_weight=0.25),
        )

        self.assertTrue(result.aggregate_only)
        self.assertLessEqual(result.confidence, 0.35)

    def test_uncertainty_reduces_curated_journalist_baseline(self) -> None:
        result = RuleBasedInjuryClassifier().classify(
            "Bukayo Saka may miss the match with a reported knock.",
            _source(SourceAccountKind.CURATED_JOURNALIST, trust_weight=0.95),
        )

        self.assertEqual(result.evidence_kind, InjuryEvidenceKind.SUSPECTED_INJURY)
        self.assertTrue(result.uncertain)
        self.assertLess(result.confidence, 0.6)


class SourceRegistryTests(unittest.TestCase):
    def test_journalist_defaults_to_reviewed_095_allowlist_weight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(
                json.dumps({
                    "sources": [{
                        "twitter_user_id": "10",
                        "username": "reporter",
                        "display_name": "Reporter",
                        "account_kind": "CURATED_JOURNALIST",
                        "manually_reviewed_at": NOW.isoformat(),
                        "reviewed_by": "editor",
                        "review_notes": "identity and affiliation manually checked",
                        "metadata": {"affiliation": "Publication"},
                    }],
                    "player_aliases": [],
                }),
                encoding="utf-8",
            )

            registry = load_registry(path)

        self.assertEqual(registry.sources[0].trust_weight, 0.95)
        self.assertEqual(registry.sources[0].reviewed_by, "editor")


class PlayerResolverTests(unittest.TestCase):
    def test_same_name_without_club_hint_is_explicitly_ambiguous(self) -> None:
        resolver = PlayerResolver(
            [
                PlayerIdentityCandidate(uuid4(), "Alex Smith", "North FC"),
                PlayerIdentityCandidate(uuid4(), "Alex Smith", "South FC"),
            ]
        )

        result = resolver.resolve("Alex Smith suffered an ankle injury")

        self.assertEqual(result.status, PlayerResolutionStatus.AMBIGUOUS)
        self.assertIsNone(result.player_id)
        self.assertEqual(len(result.candidate_player_ids), 2)

    def test_reviewed_handle_and_source_club_hint_resolve_player(self) -> None:
        north_id = uuid4()
        resolver = PlayerResolver(
            [
                PlayerIdentityCandidate(
                    north_id,
                    "Alex Smith",
                    "North FC",
                    aliases=(PlayerAlias("@alex10", "HANDLE", "North FC"),),
                ),
                PlayerIdentityCandidate(uuid4(), "Alex Smith", "South FC"),
            ]
        )

        result = resolver.resolve("@alex10 returned to training", "North FC")

        self.assertEqual(result.status, PlayerResolutionStatus.RESOLVED)
        self.assertEqual(result.player_id, north_id)


class InjuryEpisodeStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = InjuryEpisodeStateMachine()

    def test_four_stage_lifecycle_and_expected_absence(self) -> None:
        suspected = self.machine.decide(
            active_episode=None,
            latest_recovered_episode=None,
            classification=_classification(InjuryEvidenceKind.SUSPECTED_INJURY, 0.72),
            source_kind=SourceAccountKind.OFFICIAL_CLUB,
            observed_at=NOW,
        )
        self.assertEqual(suspected.stage, InjuryStage.SUSPECTED_INJURY)

        episode = _episode(InjuryStage.SUSPECTED_INJURY)
        confirmed = self.machine.decide(
            active_episode=episode,
            latest_recovered_episode=None,
            classification=_classification(
                InjuryEvidenceKind.CONFIRMED_INJURY,
                0.9,
                absence_max_days=21,
            ),
            source_kind=SourceAccountKind.CURATED_JOURNALIST,
            observed_at=NOW,
        )
        self.assertEqual(confirmed.stage, InjuryStage.CONFIRMED_INJURY)
        self.assertEqual(confirmed.expected_absence_until, NOW + timedelta(days=21))

        confirmed_episode = _episode(
            InjuryStage.CONFIRMED_INJURY,
            expected_absence_until=NOW + timedelta(days=21),
        )
        suspected_recovery = self.machine.decide(
            active_episode=confirmed_episode,
            latest_recovered_episode=None,
            classification=_classification(InjuryEvidenceKind.RETURN_TO_TRAINING, 0.82),
            source_kind=SourceAccountKind.OFFICIAL_CLUB,
            observed_at=NOW + timedelta(days=18),
        )
        self.assertEqual(suspected_recovery.stage, InjuryStage.SUSPECTED_RECOVERY)

        recovery_episode = _episode(InjuryStage.SUSPECTED_RECOVERY)
        recovered = self.machine.decide(
            active_episode=recovery_episode,
            latest_recovered_episode=None,
            classification=_classification(InjuryEvidenceKind.OFFICIAL_RECOVERY, 0.98),
            source_kind=SourceAccountKind.OFFICIAL_CLUB,
            observed_at=NOW + timedelta(days=22),
        )
        self.assertEqual(recovered.stage, InjuryStage.CONFIRMED_RECOVERED)

    def test_journalist_recovery_cannot_confirm_recovered(self) -> None:
        decision = self.machine.decide(
            active_episode=_episode(InjuryStage.CONFIRMED_INJURY),
            latest_recovered_episode=None,
            classification=_classification(InjuryEvidenceKind.OFFICIAL_RECOVERY, 0.93),
            source_kind=SourceAccountKind.CURATED_JOURNALIST,
            observed_at=NOW,
        )

        self.assertEqual(decision.stage, InjuryStage.SUSPECTED_RECOVERY)

    def test_new_injury_after_recovery_creates_linked_recurrence(self) -> None:
        recovered = _episode(InjuryStage.CONFIRMED_RECOVERED)
        decision = self.machine.decide(
            active_episode=None,
            latest_recovered_episode=recovered,
            classification=_classification(InjuryEvidenceKind.CONFIRMED_INJURY, 0.9),
            source_kind=SourceAccountKind.OFFICIAL_CLUB,
            observed_at=NOW + timedelta(days=30),
        )

        self.assertEqual(decision.action, "CREATE")
        self.assertEqual(decision.recurrence_of_episode_id, recovered.id)

    def test_strong_existing_match_participation_confirms_recovery(self) -> None:
        decision = self.machine.decide(
            active_episode=_episode(InjuryStage.SUSPECTED_RECOVERY),
            latest_recovered_episode=None,
            classification=_classification(InjuryEvidenceKind.MATCH_PARTICIPATION, 1.0),
            source_kind=None,
            observed_at=NOW,
        )

        self.assertEqual(decision.stage, InjuryStage.CONFIRMED_RECOVERED)


class HTMLParserTests(unittest.TestCase):
    def test_parses_single_tweet(self) -> None:
        page = parse_search_page_html(_SINGLE_TWEET_HTML)

        self.assertEqual(len(page.posts), 1)
        post = page.posts[0]
        self.assertEqual(post.post_id, "200")
        self.assertEqual(post.author_id, "reporter1")
        self.assertEqual(post.text, "Bukayo Saka returned to training today.")
        self.assertEqual(post.created_at, datetime(2026, 7, 18, 11, 0, tzinfo=UTC))
        self.assertIsNone(post.conversation_id)
        self.assertEqual(post.referenced_post_ids, ())
        self.assertEqual(post.edit_history_post_ids, ())
        self.assertEqual(page.newest_id, "200")
        self.assertIsNone(page.next_token)

    def test_parses_multiple_tweets_sorted_by_id(self) -> None:
        page = parse_search_page_html(_TWO_TWEET_HTML)

        self.assertEqual(len(page.posts), 2)
        self.assertEqual(page.posts[0].post_id, "300")
        self.assertEqual(page.posts[1].post_id, "250")
        self.assertEqual(page.newest_id, "300")

    def test_since_id_filters_older_posts(self) -> None:
        page = parse_search_page_html(_TWO_TWEET_HTML, since_id="270")

        self.assertEqual(len(page.posts), 1)
        self.assertEqual(page.posts[0].post_id, "300")

    def test_empty_html_returns_no_posts(self) -> None:
        page = parse_search_page_html(_EMPTY_HTML)

        self.assertEqual(len(page.posts), 0)
        self.assertIsNone(page.newest_id)
        self.assertIsNone(page.next_token)

    def test_extracts_engagement_metrics_from_group_label(self) -> None:
        page = parse_search_page_html(_SINGLE_TWEET_HTML)
        self.assertEqual(len(page.posts), 1)


class TwitterRecentSearchClientTests(unittest.TestCase):
    def test_search_page_fetches_html_and_parses(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                content=_html_response(_SINGLE_TWEET_HTML),
                headers={"content-type": "text/html; charset=utf-8"},
            )

        client = TwitterRecentSearchClient(
            policy_acknowledged=True,
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )
        page = client.search_page("injury -is:retweet", since_id="100")

        self.assertEqual(requests[0].url.host, "x.com")
        self.assertEqual(requests[0].url.path, "/search")
        self.assertIn("q=injury", str(requests[0].url))
        self.assertEqual(page.posts[0].author_id, "reporter1")
        self.assertEqual(page.posts[0].post_id, "200")

    def test_raises_when_policy_not_acknowledged(self) -> None:
        client = TwitterRecentSearchClient(
            policy_acknowledged=False,
            request_interval_seconds=0,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, html="")),
        )

        with self.assertRaises(Exception):
            client.search_page("injury")

    def test_403_raises_access_denied(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        client = TwitterRecentSearchClient(
            policy_acknowledged=True,
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(Exception):
            client.search_page("injury")

    def test_500_raises_transient_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        client = TwitterRecentSearchClient(
            policy_acknowledged=True,
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(TwitterTransientError):
            client.search_page("injury")

    def test_throttle_waits_between_requests(self) -> None:
        sleeps: list[float] = []
        clock_values = iter([100.0, 101.0, 102.5])

        def mock_clock() -> float:
            return next(clock_values)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_html_response(_SINGLE_TWEET_HTML),
                headers={"content-type": "text/html; charset=utf-8"},
            )

        client = TwitterRecentSearchClient(
            policy_acknowledged=True,
            request_interval_seconds=1.5,
            sleeper=sleeps.append,
            monotonic_clock=mock_clock,
            transport=httpx.MockTransport(handler),
        )
        client.search_page("injury")
        client.search_page("injury")

        self.assertEqual(sleeps, [0.5])


class CursorServiceTests(unittest.TestCase):
    def test_first_page_newest_id_advances_only_after_all_pages(self) -> None:
        repository = _CursorRepository()
        client = _PagedClient(
            [
                TwitterSearchPage((), "200", "next-1", TwitterRateLimit(450, 449, None)),
                TwitterSearchPage((), "150", None, TwitterRateLimit(450, 448, None)),
            ]
        )
        service = TwitterInjuryIngestionService(
            client,
            repository,
            clock=lambda: NOW,
        )

        result = service.ingest_recent("injury", "premier-league-injuries")

        self.assertEqual(result.pages_fetched, 2)
        self.assertEqual(client.calls, [(None, None), (None, "next-1")])
        self.assertEqual(repository.checkpoints[0].pending_newest_id, "200")
        self.assertEqual(repository.completed_since_id, "200")


class TwitterInjuryJobTests(unittest.TestCase):
    def test_handler_reports_ingestion_counts(self) -> None:
        service = _JobService()
        handler = IngestTwitterInjuriesJobHandler(service, "injury")

        result = handler.handle(
            WorkerJob.ingest_twitter_injuries(IngestTwitterInjuriesJobPayload("query-v1"))
        )

        self.assertEqual(result.job_type, JobType.INGEST_TWITTER_INJURIES)
        self.assertEqual(result.successful_items, 2)
        self.assertEqual(service.calls, [("injury", "query-v1")])

    def test_transient_x_error_becomes_retryable_job_error(self) -> None:
        handler = IngestTwitterInjuriesJobHandler(_FailingJobService(), "injury")

        with self.assertRaises(RetryableJobError):
            handler.handle(WorkerJob.ingest_twitter_injuries(IngestTwitterInjuriesJobPayload()))

    def test_schedule_is_disabled_by_default_and_uses_interval_window(self) -> None:
        plan = TwitterInjuryIngestionPlan(enabled=True, interval_minutes=5, query_key="query-v1")

        self.assertEqual(
            plan.window_key_for(datetime(2026, 7, 18, 12, 7, tzinfo=UTC)),
            "2026-07-18T12:05:00+00:00",
        )
        self.assertEqual(plan.build_job(NOW).job_type, JobType.INGEST_TWITTER_INJURIES)


def _source(
    kind: SourceAccountKind,
    trust_weight: float = 1.0,
) -> TwitterSourceAccount:
    return TwitterSourceAccount(
        id=uuid4(),
        twitter_user_id="10",
        username="source",
        display_name="Source",
        account_kind=kind,
        trust_weight=trust_weight,
        enabled=True,
        manually_reviewed_at=NOW,
        reviewed_by="test",
        review_notes="manual test fixture",
        metadata={},
    )


def _classification(
    kind: InjuryEvidenceKind,
    confidence: float,
    *,
    absence_max_days: int | None = None,
) -> InjuryClassification:
    return InjuryClassification(
        evidence_kind=kind,
        confidence=confidence,
        absence_max_days=absence_max_days,
    )


def _episode(
    stage: InjuryStage,
    *,
    expected_absence_until: datetime | None = None,
) -> InjuryEpisode:
    return InjuryEpisode(
        id=uuid4(),
        player_id=PLAYER_ID,
        stage=stage,
        started_at=NOW - timedelta(days=7),
        last_evidence_at=NOW - timedelta(days=1),
        expected_absence_until=expected_absence_until,
        expires_at=NOW + timedelta(days=90),
        confidence=0.9,
        recovered_at=NOW if stage is InjuryStage.CONFIRMED_RECOVERED else None,
    )


class _PagedClient:
    def __init__(self, pages: list[TwitterSearchPage]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str | None, str | None]] = []

    def search_page(
        self,
        query: str,
        *,
        since_id: str | None = None,
        next_token: str | None = None,
    ) -> TwitterSearchPage:
        self.calls.append((since_id, next_token))
        return self.pages.pop(0)


class _CursorRepository:
    def __init__(self) -> None:
        self.checkpoints: list[TwitterIngestionCursor] = []
        self.completed_since_id: str | None = None

    def load_cursor(self, query_key: str, query: str) -> TwitterIngestionCursor:
        return TwitterIngestionCursor(query_key=query_key, query=query)

    def expire_stale_episodes(self, as_of: datetime) -> int:
        return 0

    def list_source_accounts(self) -> list[object]:
        return []

    def list_player_candidates(self) -> list[object]:
        return []

    def checkpoint_cursor(self, cursor: TwitterIngestionCursor, polled_at: datetime) -> None:
        self.checkpoints.append(cursor)

    def complete_cursor(
        self,
        query_key: str,
        query: str,
        since_id: str | None,
        rate_limit: TwitterRateLimit,
        polled_at: datetime,
    ) -> None:
        self.completed_since_id = since_id

    def list_recovery_candidates(self) -> list[object]:
        return []


class _JobService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def ingest_recent(
        self,
        query: str,
        query_key: str | None = None,
    ) -> TwitterInjuryIngestionResult:
        self.calls.append((query, query_key))
        return TwitterInjuryIngestionResult(3, 2, 2, 2, 0, 1, 1, 1)


class _FailingJobService:
    def ingest_recent(
        self,
        query: str,
        query_key: str | None = None,
    ) -> TwitterInjuryIngestionResult:
        raise TwitterTransientError("temporary X outage")


if __name__ == "__main__":
    unittest.main()
