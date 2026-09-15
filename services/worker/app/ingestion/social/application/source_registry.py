from __future__ import annotations

from collections.abc import Iterable

from ..domain import PolicyDisabled, SocialProvider, SocialSource, SocialSubscription
from ..ports import SocialConnector


class SourceRegistry:
    """Provider lookup and the single policy gate used before network access."""

    def __init__(self, connectors: Iterable[SocialConnector] = ()) -> None:
        self._connectors: dict[SocialProvider, SocialConnector] = {}
        for connector in connectors:
            self.register(connector)

    def register(self, connector: SocialConnector) -> None:
        if connector.provider in self._connectors:
            raise ValueError(f"connector already registered for {connector.provider.value}")
        self._connectors[connector.provider] = connector

    def connector_for(
        self,
        subscription: SocialSubscription,
        source: SocialSource,
    ) -> SocialConnector:
        if not subscription.enabled:
            raise PolicyDisabled("social subscription is disabled")
        if subscription.source_id != source.id:
            raise PolicyDisabled("social subscription does not belong to its source")
        if subscription.provider is not source.provider:
            raise PolicyDisabled("social subscription and source providers do not match")
        if not source.is_eligible:
            raise PolicyDisabled(
                f"social source policy is {source.policy_status.value.lower()} or disabled"
            )
        connector = self._connectors.get(subscription.provider)
        if connector is None:
            raise PolicyDisabled(f"no connector is enabled for {subscription.provider.value}")
        return connector

