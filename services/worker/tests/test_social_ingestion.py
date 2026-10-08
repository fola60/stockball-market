from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from app.ingestion.social import (
    BlueskyClient,
    BlueskyConnector,
    IngestionCursor,
    PolicyDisabled,
    PollResult,
    RssClient,
    RssConnector,
    SocialDocument,
    SocialDocumentKind,
    SocialDocumentProcessor,
    SocialEntityType,
    SocialIngestionService,
    SocialObservationClassifier,
    SocialObservationStatus,
    SocialObservationTopic,
    SocialPolicyStatus,
    SocialProvider,
    SocialSentiment,
    SocialSource,
    SocialSourceCategory,
    SocialSubscription,
    SocialSubscriptionMode,
    SourceRegistry,
)
from app.ingestion.social.injuries import (
    InjuryDocumentProcessor,
    PlayerIdentityCandidate,
    SocialInjuryClassifier,
)
from app.ingestion.social.observations import SocialPlayerResolver
from app.scheduler import DueSocialSubscriptionDispatcher
from app.scheduler.service import InMemoryJobQueue, InMemoryScheduleClaimStore

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class InMemorySocialRepository:
    def __init__(self, source: SocialSource, subscription: SocialSubscription) -> None:
        self.source = source
        self.subscription = subscription
        self.cursor: IngestionCursor | None = None
        self.documents: set[tuple[SocialProvider, str]] = set()
        self.failures: list[tuple] = []

    def get_source(self, source_id):
        return self.source if source_id == self.source.id else None

    def get_subscription(self, subscription_id):
        return self.subscription if subscription_id == self.subscription.id else None

    def load_cursor(self, subscription_id):
        return self.cursor

    def persist_poll_result(self, subscription, result, polled_at):
        before = len(self.documents)
        self.documents.update((item.provider, item.external_id) for item in result.documents)
        inserted = len(self.documents) - before
        self.cursor = IngestionCursor(
            subscription_id=subscription.id,
            cursor=result.next_cursor,
            last_polled_at=polled_at,
            last_success_at=polled_at,
            next_eligible_poll_at=polled_at + subscription.polling_interval,
        )
        return inserted, len(result.documents) - inserted

    def record_failure(self, *args):
        self.failures.append(args)


class FakeConnector:
    provider = SocialProvider.BLUESKY

    def __init__(self, result: PollResult) -> None:
        self.result = result

    async def poll(self, subscription, cursor):
        return self.result


class SocialIngestionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_gate_runs_before_connector_and_replay_is_idempotent(self) -> None:
        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        document = _document(source.id)
        repository = InMemorySocialRepository(source, subscription)
        service = SocialIngestionService(
            repository,
            SourceRegistry((FakeConnector(PollResult((document,), {"cursor": "next"})),)),
            clock=lambda: NOW,
        )

        first = await service.ingest(subscription.id)
        repository.cursor = None
        second = await service.ingest(subscription.id)

        self.assertEqual(first.inserted_documents, 1)
        self.assertEqual(second.duplicate_documents, 1)

    async def test_disabled_source_cannot_make_network_request(self) -> None:
        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        source = SocialSource(
            **{**source.__dict__, "enabled": False, "policy_status": SocialPolicyStatus.REVOKED}
        )
        repository = InMemorySocialRepository(source, subscription)
        service = SocialIngestionService(
            repository, SourceRegistry((FakeConnector(PollResult(())),)), clock=lambda: NOW
        )

        with self.assertRaises(PolicyDisabled):
            await service.ingest(subscription.id)


class BlueskyConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_original_posts_and_ignores_reposts(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "cursor": "page-2",
                    "feed": [
                        {
                            "post": {
                                "uri": "at://did:plc:club/app.bsky.feed.post/abc",
                                "cid": "cid",
                                "author": {"did": "did:plc:club", "handle": "club.test"},
                                "record": {
                                    "text": "Player ruled out with a knee injury",
                                    "createdAt": NOW.isoformat(),
                                    "langs": ["en"],
                                },
                            }
                        },
                        {"reason": {"$type": "repost"}, "post": {}},
                    ],
                },
            )

        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        connector = BlueskyConnector(
            BlueskyClient(transport=httpx.MockTransport(handler))
        )
        result = await connector.poll(subscription, None)

        self.assertEqual(len(result.documents), 1)
        self.assertEqual(result.documents[0].author_external_id, "did:plc:club")
        self.assertEqual(result.next_cursor, {"cursor": "page-2"})

    async def test_ignores_posts_without_text(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "feed": [
                        {
                            "post": {
                                "uri": "at://did:plc:club/app.bsky.feed.post/no-text",
                                "cid": "cid",
                                "author": {"did": "did:plc:club", "handle": "club.test"},
                                "record": {"createdAt": NOW.isoformat()},
                            }
                        }
                    ]
                },
            )

        _, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        connector = BlueskyConnector(BlueskyClient(transport=httpx.MockTransport(handler)))

        result = await connector.poll(subscription, None)

        self.assertEqual(result.documents, ())


class RssConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_atom_sanitizes_html_and_sends_validators(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                headers={"ETag": '"v2"', "Last-Modified": "Tue, 08 Sep 2026 12:00:00 GMT"},
                content=b"""<?xml version='1.0'?>
                <feed xmlns='http://www.w3.org/2005/Atom' xml:lang='en'>
                  <entry><id>tag:club.test,2026:1</id><title>Squad update</title>
                  <content type='html'>&lt;b&gt;Player&lt;/b&gt; returned to training.</content>
                  <link href='/news/1'/><updated>2026-09-08T11:00:00Z</updated></entry>
                </feed>""",
            )

        source, subscription = _source_and_subscription(SocialProvider.RSS)
        connector = RssConnector(RssClient(transport=httpx.MockTransport(handler)))
        cursor = IngestionCursor(
            subscription.id, etag='"v1"', last_modified="Mon, 07 Sep 2026 12:00:00 GMT"
        )
        result = await connector.poll(subscription, cursor)

        self.assertEqual(result.documents[0].text, "Squad update Player returned to training.")
        self.assertEqual(result.documents[0].metadata["title"], "Squad update")
        self.assertEqual(result.documents[0].canonical_url, "https://club.test/news/1")
        self.assertEqual(requests[0].headers["if-none-match"], '"v1"')
        self.assertEqual(result.next_cursor["etag"], '"v2"')

    async def test_parses_standard_rss_pubdate_case_insensitively(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"""<?xml version='1.0'?>
                <rss version='2.0'><channel><item>
                  <guid>club-news-1</guid><title>Team news</title>
                  <description>Player ruled out with an ankle injury.</description>
                  <link>https://club.test/news/1</link>
                  <pubDate>Thu, 10 Sep 2026 12:00:00 GMT</pubDate>
                </item></channel></rss>""",
            )

        _, subscription = _source_and_subscription(SocialProvider.RSS)
        connector = RssConnector(RssClient(transport=httpx.MockTransport(handler)))

        result = await connector.poll(subscription, None)

        self.assertEqual(len(result.documents), 1)
        self.assertEqual(result.documents[0].external_id, "club-news-1")
        self.assertEqual(result.documents[0].metadata["title"], "Team news")
        self.assertEqual(
            result.documents[0].published_at,
            datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        )


class SocialSchedulingTests(unittest.TestCase):
    def test_dispatches_one_parent_feed_job_plus_processing(self) -> None:
        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        repository = InMemorySocialRepository(source, subscription)
        repository.list_due_subscriptions = lambda as_of, limit=100: [subscription.id]
        queue = InMemoryJobQueue()
        dispatcher = DueSocialSubscriptionDispatcher(
            repository, queue, InMemoryScheduleClaimStore()
        )

        names = dispatcher.dispatch_due(NOW.replace(minute=1))

        self.assertEqual(len(names), 2)
        self.assertEqual(names[0], "social-feed-ingestion")
        self.assertEqual(queue.jobs[0].job_type.value, "INGEST_SOCIAL_FEEDS")
        self.assertEqual(queue.jobs[0].payload, {"provider": "ALL", "limit": 100})
        self.assertEqual(queue.jobs[1].job_type.value, "PROCESS_SOCIAL_DOCUMENTS")

    def test_scheduled_parent_feed_job_is_correlated_to_a_run(self) -> None:
        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        repository = InMemorySocialRepository(source, subscription)
        repository.list_due_subscriptions = lambda as_of, limit=100: [subscription.id]
        queue = InMemoryJobQueue()

        class RunRepository:
            created = None

            def has_in_flight(self, schedule_name):
                return False

            def create_run(self, *args):
                self.created = args
                return True

            def mark_enqueue_failed(self, run_id, message):
                raise AssertionError("enqueue should not fail")

        run_repository = RunRepository()
        dispatcher = DueSocialSubscriptionDispatcher(
            repository,
            queue,
            InMemoryScheduleClaimStore(),
            run_repository=run_repository,
        )

        dispatcher.dispatch_due(NOW)

        self.assertIsNotNone(queue.jobs[0].operation_run_id)
        self.assertEqual(run_repository.created[1], "social-feed-ingestion")
        self.assertEqual(run_repository.created[3].value, "INGEST_SOCIAL_FEEDS")
        self.assertFalse(run_repository.created[5])

    def test_does_not_enqueue_a_second_parent_feed_run_while_one_is_in_flight(self) -> None:
        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        repository = InMemorySocialRepository(source, subscription)
        repository.list_due_subscriptions = lambda as_of, limit=100: [subscription.id]
        queue = InMemoryJobQueue()

        class RunRepository:
            def has_in_flight(self, schedule_name):
                return True

            def create_run(self, *args):
                raise AssertionError("an in-flight schedule must not create another run")

            def mark_enqueue_failed(self, run_id, message):
                raise AssertionError("enqueue should not be attempted")

        dispatcher = DueSocialSubscriptionDispatcher(
            repository,
            queue,
            InMemoryScheduleClaimStore(),
            run_repository=RunRepository(),
        )

        names = dispatcher.dispatch_due(NOW.replace(minute=1))

        self.assertEqual(names, ("social-document-processing",))
        self.assertEqual(len(queue.jobs), 1)
        self.assertEqual(queue.jobs[0].job_type.value, "PROCESS_SOCIAL_DOCUMENTS")

    def test_dispatcher_respects_social_process_pause(self) -> None:
        source, subscription = _source_and_subscription(SocialProvider.BLUESKY)
        repository = InMemorySocialRepository(source, subscription)
        repository.list_due_subscriptions = lambda as_of, limit=100: [subscription.id]
        queue = InMemoryJobQueue()

        class PausedControlStore:
            def is_enabled(self, schedule_name, default):
                self.request = (schedule_name, default)
                return False

        control_store = PausedControlStore()
        dispatcher = DueSocialSubscriptionDispatcher(
            repository,
            queue,
            InMemoryScheduleClaimStore(),
            control_store=control_store,
        )

        names = dispatcher.dispatch_due(NOW)

        self.assertEqual(names, ())
        self.assertEqual(queue.jobs, [])
        self.assertEqual(control_store.request, ("social-feed-ingestion", True))


class InjuryProcessingPolicyTests(unittest.TestCase):
    def test_revoked_source_cannot_create_actionable_evidence(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.BLUESKY)
        source = SocialSource(
            **{**source.__dict__, "enabled": False, "policy_status": SocialPolicyStatus.REVOKED}
        )
        player_id = uuid4()

        class Sink:
            status = None

            def record_injury_observation(self, **kwargs):
                self.status = kwargs["evidence_status"]
                return self.status == "ACTIONABLE"

        sink = Sink()
        processor = InjuryDocumentProcessor(
            [PlayerIdentityCandidate(player_id, "Player", "Club")], sink
        )
        document = SocialDocument(
            **{
                **_document(source.id).__dict__,
                "text": "Player suffered a knee injury and will miss 3 weeks.",
            }
        )

        updated = processor.process(document, source)

        self.assertFalse(updated)
        self.assertEqual(sink.status, "REJECTED")


class GeneralSocialObservationTests(unittest.TestCase):
    def test_classifies_positive_performance(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.BLUESKY)
        injury = SocialInjuryClassifier().classify(
            "Player scored a brilliant winning goal", source
        )

        result = SocialObservationClassifier().classify(
            "Player scored a brilliant winning goal", injury
        )

        self.assertEqual(result.topic, SocialObservationTopic.PERFORMANCE)
        self.assertEqual(result.sentiment, SocialSentiment.POSITIVE)
        self.assertGreater(result.sentiment_score, 0)

    def test_classifies_injury_as_negative(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.BLUESKY)
        injury = SocialInjuryClassifier().classify(
            "Player ruled out with a knee injury", source
        )

        result = SocialObservationClassifier().classify(
            "Player ruled out with a knee injury", injury
        )

        self.assertEqual(result.topic, SocialObservationTopic.INJURY)
        self.assertEqual(result.sentiment, SocialSentiment.NEGATIVE)
        self.assertLess(result.sentiment_score, 0)

    def test_processor_records_general_non_injury_observation(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.BLUESKY)
        player_id = uuid4()

        class Sink:
            general = None
            injury_calls = 0

            def record_social_observation(self, **kwargs):
                self.general = kwargs
                return uuid4()

            def record_injury_observation(self, **kwargs):
                self.injury_calls += 1
                return False

        sink = Sink()
        processor = SocialDocumentProcessor(
            [PlayerIdentityCandidate(player_id, "Player", "Club")], sink
        )
        document = SocialDocument(
            **{
                **_document(source.id).__dict__,
                "text": "Player scored a fantastic goal in the victory",
            }
        )

        updated = processor.process(document, source)

        self.assertFalse(updated)
        self.assertEqual(sink.injury_calls, 0)
        self.assertEqual(sink.general["entity_type"], SocialEntityType.PLAYER)
        self.assertEqual(sink.general["observation_status"], SocialObservationStatus.INCLUDED)
        self.assertEqual(
            sink.general["classification"].sentiment,
            SocialSentiment.POSITIVE,
        )

    def test_processor_records_general_and_specialized_injury_observations(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.BLUESKY)
        player_id = uuid4()

        class Sink:
            observation_id = uuid4()
            injury = None

            def record_social_observation(self, **kwargs):
                return self.observation_id

            def record_injury_observation(self, **kwargs):
                self.injury = kwargs
                return True

        sink = Sink()
        processor = SocialDocumentProcessor(
            [PlayerIdentityCandidate(player_id, "Player", "Club")], sink
        )
        document = SocialDocument(
            **{
                **_document(source.id).__dict__,
                "text": "Player suffered a knee injury and will miss 3 weeks",
            }
        )

        updated = processor.process(document, source)

        self.assertTrue(updated)
        self.assertEqual(sink.injury["social_observation_id"], sink.observation_id)
        self.assertEqual(sink.injury["evidence_status"], "ACTIONABLE")

    def test_unique_first_and_surname_resolve_for_sentiment(self) -> None:
        haaland_id = uuid4()
        rashford_id = uuid4()
        resolver = SocialPlayerResolver(
            [
                PlayerIdentityCandidate(haaland_id, "Erling Haaland", "Manchester City"),
                PlayerIdentityCandidate(rashford_id, "Marcus Rashford", "Manchester Utd"),
            ]
        )

        first_name = resolver.resolve("Erling was outstanding today")
        surname = resolver.resolve("Rashford scored the winner")

        self.assertEqual(first_name.player.player_id, haaland_id)
        self.assertEqual(first_name.player.reason, "globally_unique_name")
        self.assertEqual(surname.player.player_id, rashford_id)
        self.assertEqual(surname.player.reason, "globally_unique_name")

    def test_rss_summary_resolution_wins_over_multi_player_article_body(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.RSS)
        saka_id, odegaard_id = uuid4(), uuid4()

        class Sink:
            general = None

            def record_social_observation(self, **kwargs):
                self.general = kwargs
                return uuid4()

            def record_injury_observation(self, **kwargs):
                return False

        sink = Sink()
        processor = SocialDocumentProcessor(
            [
                PlayerIdentityCandidate(saka_id, "Bukayo Saka", "Arsenal"),
                PlayerIdentityCandidate(odegaard_id, "Martin Odegaard", "Arsenal"),
            ],
            sink,
        )
        document = SocialDocument(
            **{
                **_document(source.id).__dict__,
                "provider": SocialProvider.RSS,
                "text": (
                    "Saka was outstanding in Arsenal's victory. "
                    "Bukayo Saka and Martin Odegaard both created chances throughout the match."
                ),
                "metadata": {"source_text": "Saka was outstanding in Arsenal's victory."},
            }
        )

        processor.process(document, source)

        self.assertEqual(sink.general["resolution"].player_id, saka_id)

    def test_united_and_club_unique_first_name_disambiguate(self) -> None:
        united_alex = uuid4()
        arsenal_alex = uuid4()
        resolver = SocialPlayerResolver(
            [
                PlayerIdentityCandidate(united_alex, "Alex Red", "Manchester Utd"),
                PlayerIdentityCandidate(arsenal_alex, "Alex Gunner", "Arsenal"),
            ]
        )

        result = resolver.resolve("United confirm Alex starts tonight")

        self.assertEqual(result.team_name, "Manchester Utd")
        self.assertEqual(result.player.player_id, united_alex)
        self.assertEqual(result.player.reason, "club_context_unique_name")

    def test_longer_club_name_wins_over_united_shortcut(self) -> None:
        resolver = SocialPlayerResolver(
            [
                PlayerIdentityCandidate(uuid4(), "Manchester Player", "Manchester Utd"),
                PlayerIdentityCandidate(uuid4(), "Leeds Player", "Leeds United"),
            ]
        )

        result = resolver.resolve("Leeds United announce their starting XI")

        self.assertEqual(result.team_name, "Leeds United")

    def test_partial_name_is_not_used_for_injury_resolution(self) -> None:
        source, _ = _source_and_subscription(SocialProvider.BLUESKY)
        player_id = uuid4()

        class Sink:
            general = None
            injury = None

            def record_social_observation(self, **kwargs):
                self.general = kwargs
                return uuid4()

            def record_injury_observation(self, **kwargs):
                self.injury = kwargs
                return False

        sink = Sink()
        processor = SocialDocumentProcessor(
            [PlayerIdentityCandidate(player_id, "Erling Haaland", "Manchester City")],
            sink,
        )
        document = SocialDocument(
            **{
                **_document(source.id).__dict__,
                "text": "Erling ruled out with an injury",
            }
        )

        processor.process(document, source)

        self.assertEqual(sink.general["resolution"].player_id, player_id)
        self.assertIsNone(sink.injury["resolution"].player_id)


def _source_and_subscription(provider: SocialProvider):
    source_id = uuid4()
    source = SocialSource(
        id=source_id,
        provider=provider,
        external_source_id="did:plc:club" if provider is SocialProvider.BLUESKY else "club-feed",
        display_handle="club.test",
        canonical_url="https://club.test",
        source_category=SocialSourceCategory.OFFICIAL_CLUB,
        trust_weight=1.0,
        enabled=True,
        policy_status=SocialPolicyStatus.APPROVED,
        terms_reviewed_at=NOW,
        retention_days=30,
        approved_by="editor",
        approved_at=NOW,
        metadata={},
    )
    subscription = SocialSubscription(
        id=uuid4(),
        source_id=source_id,
        provider=provider,
        mode=(
            SocialSubscriptionMode.AUTHOR_FEED
            if provider is SocialProvider.BLUESKY
            else SocialSubscriptionMode.RSS_FEED
        ),
        configuration=(
            {"did": "did:plc:club"}
            if provider is SocialProvider.BLUESKY
            else {"url": "https://club.test/feed.xml"}
        ),
        polling_interval=timedelta(minutes=5),
    )
    return source, subscription


def _document(source_id: UUID) -> SocialDocument:
    return SocialDocument(
        provider=SocialProvider.BLUESKY,
        external_id="at://did:plc:club/app.bsky.feed.post/abc",
        source_id=source_id,
        document_kind=SocialDocumentKind.POST,
        author_external_id="did:plc:club",
        text="Player ruled out with injury",
        published_at=NOW,
        canonical_url="https://bsky.app/profile/club.test/post/abc",
    )
