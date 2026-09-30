from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.ingestion.social import (
    PollResult,
    SocialDocument,
    SocialDocumentKind,
    SocialProvider,
    TransientProviderError,
)
from scripts.probe_social_ingestion import main


class SocialIngestionScriptTests(unittest.TestCase):
    @patch("scripts.probe_social_ingestion.BlueskyConnector")
    def test_bluesky_uses_production_connector_and_prints_documents(
        self, connector_type
    ) -> None:
        connector_type.return_value.poll = AsyncMock(
            return_value=PollResult(
                documents=(
                    SocialDocument(
                        provider=SocialProvider.BLUESKY,
                        external_id="at://did:plc:club/app.bsky.feed.post/abc",
                        source_id=uuid4(),
                        document_kind=SocialDocumentKind.POST,
                        author_external_id="did:plc:club",
                        text="Player returned to full training.",
                        published_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
                        canonical_url="https://bsky.app/profile/club.test/post/abc",
                    ),
                ),
                next_cursor={"cursor": "next-page"},
            )
        )
        output = StringIO()

        with redirect_stdout(output):
            result = main(["bluesky", "did:plc:club", "--limit", "10"])

        self.assertEqual(result, 0)
        connector_type.assert_called_once_with(page_size=10)
        self.assertIn("Found 1 normalized documents", output.getvalue())
        self.assertIn("Player returned to full training", output.getvalue())
        self.assertIn('"cursor": "next-page"', output.getvalue())

    @patch("scripts.probe_social_ingestion.RssConnector")
    def test_reports_provider_errors_without_traceback(self, connector_type) -> None:
        connector_type.return_value.poll = AsyncMock(
            side_effect=TransientProviderError("publisher unavailable")
        )
        error_output = StringIO()

        with redirect_stderr(error_output):
            result = main(["rss", "https://club.test/feed.xml"])

        self.assertEqual(result, 1)
        self.assertIn(
            "Social ingestion test failed: publisher unavailable",
            error_output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
