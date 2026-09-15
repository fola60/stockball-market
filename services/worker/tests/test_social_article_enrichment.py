from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.ingestion.social import (
    ArticleEnrichmentCandidate,
    ArticleFetcher,
    ArticleFetchSkipped,
    SocialArticleEnrichmentService,
    SocialIngestionResult,
    SocialProvider,
    extract_article_text,
)
from app.jobs import (
    IngestSocialSourceJobHandler,
    IngestSocialSourceJobPayload,
    WorkerJob,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


class ArticleExtractionTests(unittest.TestCase):
    def test_extracts_main_article_and_discards_page_chrome(self) -> None:
        extraction = extract_article_text(
            b"""
            <html><body><nav>Transfer rumours and navigation</nav><article>
              <h1>Team update</h1>
              <p>Bruno trained with Manchester United on Friday after recovering from injury.</p>
              <aside><p>Buy a subscription to read more stories.</p></aside>
              <p>The manager said he is available for Saturday and is expected to start.</p>
              <p>That decision will be made after the final training session later today.</p>
            </article></body></html>
            """
        )

        self.assertIsNotNone(extraction)
        assert extraction is not None
        self.assertEqual(extraction.method, "article_element")
        self.assertIn("Bruno trained", extraction.text)
        self.assertNotIn("Buy a subscription", extraction.text)
        self.assertNotIn("Transfer rumours", extraction.text)

    def test_supports_json_ld_article_body(self) -> None:
        extraction = extract_article_text(
            b"""
            <script type="application/ld+json">
              {"@type":"NewsArticle","articleBody":"Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update. Player update."}
            </script>
            """
        )

        self.assertIsNotNone(extraction)
        assert extraction is not None
        self.assertEqual(extraction.method, "json_ld_article_body")


class ArticleFetcherTests(unittest.TestCase):
    def test_rejects_unapproved_host_before_request(self) -> None:
        fetcher = ArticleFetcher(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        )

        with self.assertRaises(ArticleFetchSkipped):
            fetcher.fetch(
                "https://unexpected.test/story",
                allowed_hosts=("publisher.test",),
                max_response_bytes=1000,
            )

    def test_rejects_redirect_to_unapproved_host(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://unexpected.test/story"})

        fetcher = ArticleFetcher(transport=httpx.MockTransport(handler))

        with self.assertRaises(ArticleFetchSkipped):
            fetcher.fetch(
                "https://publisher.test/story",
                allowed_hosts=("publisher.test",),
                max_response_bytes=1000,
            )


class InMemoryEnrichmentRepository:
    def __init__(self, candidates: list[ArticleEnrichmentCandidate]) -> None:
        self.candidates = candidates
        self.completed: list[tuple] = []
        self.skipped: list[tuple] = []
        self.failed: list[tuple] = []

    def claim_article_enrichments(self, *, limit: int):
        return self.candidates[:limit]

    def complete_article_enrichment(self, document_id, **kwargs):
        self.completed.append((document_id, kwargs))

    def skip_article_enrichment(self, document_id, reason):
        self.skipped.append((document_id, reason))

    def fail_article_enrichment(self, document_id, reason):
        self.failed.append((document_id, reason))


class ArticleEnrichmentServiceTests(unittest.TestCase):
    def test_enriches_extractable_page_and_skips_non_article(self) -> None:
        good_id, short_id = uuid4(), uuid4()
        repository = InMemoryEnrichmentRepository(
            [
                ArticleEnrichmentCandidate(
                    good_id, "https://publisher.test/good", ("publisher.test",)
                ),
                ArticleEnrichmentCandidate(
                    short_id, "https://publisher.test/short", ("publisher.test",)
                ),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                "<article><p>" + "A detailed player and team update. " * 12 + "</p></article>"
                if request.url.path == "/good"
                else "<main><p>Brief notice.</p></main>"
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/html"})

        result = SocialArticleEnrichmentService(
            repository, ArticleFetcher(transport=httpx.MockTransport(handler))
        ).enrich_pending(limit=10)

        self.assertEqual((result.claimed, result.enriched, result.skipped, result.failed), (2, 1, 1, 0))
        self.assertEqual(repository.completed[0][0], good_id)
        self.assertEqual(repository.skipped[0][0], short_id)


class ImmediateIngestionProcessingTests(unittest.TestCase):
    def test_new_documents_are_enriched_for_the_ingested_subscription(self) -> None:
        subscription_id = uuid4()
        document_id = uuid4()

        class IngestionService:
            async def ingest(self, requested_subscription_id):
                return SocialIngestionResult(
                    requested_subscription_id,
                    provider=SocialProvider.RSS,
                    fetched_documents=1,
                    inserted_documents=1,
                    duplicate_documents=0,
                    next_eligible_poll_at=NOW,
                )

        class Repository(InMemoryEnrichmentRepository):
            enrichment_subscription_id = None
            processing_subscription_id = None

            def claim_article_enrichments(self, *, limit, subscription_id=None):
                self.enrichment_subscription_id = subscription_id
                return self.candidates[:limit]

            def list_player_candidates(self):
                return []

            def claim_documents(self, *, limit, subscription_id=None):
                self.processing_subscription_id = subscription_id
                return []

        repository = Repository(
            [
                ArticleEnrichmentCandidate(
                    document_id,
                    "https://publisher.test/story",
                    ("publisher.test",),
                )
            ]
        )
        body = "<article><p>" + "Detailed football article content. " * 12 + "</p></article>"
        fetcher = ArticleFetcher(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, text=body, headers={"content-type": "text/html"}
                )
            )
        )
        handler = IngestSocialSourceJobHandler(
            IngestionService(),  # type: ignore[arg-type]
            repository=repository,  # type: ignore[arg-type]
            article_fetcher=fetcher,
        )

        result = handler.handle(
            WorkerJob.ingest_social_source(
                IngestSocialSourceJobPayload(subscription_id=subscription_id)
            )
        )

        self.assertEqual(result.metrics["immediate_articles_enriched"], 1)
        self.assertEqual(repository.enrichment_subscription_id, subscription_id)
        self.assertEqual(repository.processing_subscription_id, subscription_id)


if __name__ == "__main__":
    unittest.main()
