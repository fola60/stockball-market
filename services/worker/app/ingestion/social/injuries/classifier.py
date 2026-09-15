from __future__ import annotations

from ..domain import SocialSource, SocialSourceCategory
from ..twitter.classifier import RuleBasedInjuryClassifier
from ..twitter.models import InjuryClassification, SourceAccountKind, TwitterSourceAccount


class SocialInjuryClassifier:
    """Provider-neutral facade over the characterized deterministic V1 classifier."""

    version = "rules-v1"

    def __init__(self) -> None:
        self._classifier = RuleBasedInjuryClassifier()

    def classify(self, text: str, source: SocialSource) -> InjuryClassification:
        return self._classifier.classify(text, _legacy_source(source))


def _legacy_source(source: SocialSource) -> TwitterSourceAccount:
    kind = {
        SocialSourceCategory.OFFICIAL_CLUB: SourceAccountKind.OFFICIAL_CLUB,
        SocialSourceCategory.OFFICIAL_LEAGUE: SourceAccountKind.OFFICIAL_LEAGUE,
        SocialSourceCategory.PLAYER: SourceAccountKind.PLAYER_OWNED,
        SocialSourceCategory.JOURNALIST: SourceAccountKind.CURATED_JOURNALIST,
        SocialSourceCategory.NEWS_ORGANISATION: SourceAccountKind.CURATED_JOURNALIST,
        SocialSourceCategory.COMMUNITY: SourceAccountKind.FAN,
    }[source.source_category]
    return TwitterSourceAccount(
        id=source.id,
        twitter_user_id=source.external_source_id,
        username=source.display_handle or source.external_source_id,
        display_name=source.display_handle or source.external_source_id,
        account_kind=kind,
        trust_weight=source.trust_weight,
        enabled=source.enabled,
        manually_reviewed_at=source.terms_reviewed_at,
        reviewed_by=source.approved_by,
        review_notes="provider-neutral source policy review",
        metadata=source.metadata,
    )

