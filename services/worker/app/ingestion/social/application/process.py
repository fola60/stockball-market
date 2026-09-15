from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import UUID

from ..domain import SocialDocument, SocialSource


class SocialDocumentProcessor(Protocol):
    def process(self, document: SocialDocument, source: SocialSource) -> bool:
        """Process one document and return whether it changed derived evidence."""
        ...


class ProcessingRepository(Protocol):
    def claim_documents(
        self, *, limit: int, subscription_id: UUID | None = None
    ) -> Sequence[tuple[SocialDocument, SocialSource]]: ...

    def complete_document(self, document_id: UUID) -> None: ...

    def fail_document(self, document_id: UUID, reason: str) -> None: ...


@dataclass(frozen=True)
class SocialProcessingResult:
    claimed: int
    processed: int
    evidence_updates: int
    failed: int


class SocialProcessingService:
    """Provider-neutral asynchronous boundary for resolution and classification."""

    def __init__(self, repository: ProcessingRepository, processor: SocialDocumentProcessor) -> None:
        self._repository = repository
        self._processor = processor

    def process_pending(
        self,
        *,
        limit: int = 100,
        subscription_id: UUID | None = None,
    ) -> SocialProcessingResult:
        if limit <= 0:
            raise ValueError("processing limit must be positive")
        claimed = (
            self._repository.claim_documents(limit=limit)
            if subscription_id is None
            else self._repository.claim_documents(
                limit=limit, subscription_id=subscription_id
            )
        )
        processed = evidence_updates = failed = 0
        for document, source in claimed:
            document_id = _document_uuid(document)
            try:
                evidence_updates += int(self._processor.process(document, source))
                self._repository.complete_document(document_id)
                processed += 1
            except Exception as error:
                self._repository.fail_document(document_id, type(error).__name__)
                failed += 1
        return SocialProcessingResult(len(claimed), processed, evidence_updates, failed)


def _document_uuid(document: SocialDocument) -> UUID:
    value = document.metadata.get("document_id")
    if value is None:
        raise ValueError("claimed social document is missing metadata.document_id")
    return UUID(str(value))
