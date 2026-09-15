from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import UUID

from .client import ArticleFetcher, ArticleFetchSkipped, ArticleFetchTransient
from .extractor import extract_article_text


@dataclass(frozen=True)
class ArticleEnrichmentCandidate:
    document_id: UUID
    canonical_url: str
    allowed_hosts: tuple[str, ...]
    max_response_bytes: int = 1_500_000


class ArticleEnrichmentRepository(Protocol):
    def claim_article_enrichments(
        self, *, limit: int, subscription_id: UUID | None = None
    ) -> Sequence[ArticleEnrichmentCandidate]: ...

    def complete_article_enrichment(
        self,
        document_id: UUID,
        *,
        article_text: str,
        final_url: str,
        http_status: int,
        extraction_method: str,
    ) -> None: ...

    def skip_article_enrichment(self, document_id: UUID, reason: str) -> None: ...

    def fail_article_enrichment(self, document_id: UUID, reason: str) -> None: ...


@dataclass(frozen=True)
class SocialArticleEnrichmentResult:
    claimed: int
    enriched: int
    skipped: int
    failed: int


class SocialArticleEnrichmentService:
    def __init__(
        self,
        repository: ArticleEnrichmentRepository,
        fetcher: ArticleFetcher | None = None,
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher or ArticleFetcher()

    def enrich_pending(
        self,
        *,
        limit: int = 20,
        subscription_id: UUID | None = None,
    ) -> SocialArticleEnrichmentResult:
        if limit <= 0:
            raise ValueError("article enrichment limit must be positive")
        candidates = (
            self._repository.claim_article_enrichments(limit=limit)
            if subscription_id is None
            else self._repository.claim_article_enrichments(
                limit=limit, subscription_id=subscription_id
            )
        )
        enriched = skipped = failed = 0
        for candidate in candidates:
            try:
                response = self._fetcher.fetch(
                    candidate.canonical_url,
                    allowed_hosts=candidate.allowed_hosts,
                    max_response_bytes=candidate.max_response_bytes,
                )
                extraction = extract_article_text(response.content)
                if extraction is None:
                    self._repository.skip_article_enrichment(
                        candidate.document_id, "no substantial article body found"
                    )
                    skipped += 1
                    continue
                self._repository.complete_article_enrichment(
                    candidate.document_id,
                    article_text=extraction.text,
                    final_url=response.final_url,
                    http_status=response.status_code,
                    extraction_method=extraction.method,
                )
                enriched += 1
            except ArticleFetchSkipped as error:
                self._repository.skip_article_enrichment(candidate.document_id, str(error))
                skipped += 1
            except ArticleFetchTransient as error:
                self._repository.fail_article_enrichment(candidate.document_id, str(error))
                failed += 1
            except Exception as error:
                self._repository.fail_article_enrichment(
                    candidate.document_id, f"{type(error).__name__}: {error}"
                )
                failed += 1
        return SocialArticleEnrichmentResult(len(candidates), enriched, skipped, failed)
