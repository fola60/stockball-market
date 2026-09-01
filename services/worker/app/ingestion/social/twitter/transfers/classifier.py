from __future__ import annotations

import re
from typing import Protocol

from ..models import TwitterSourceAccount
from .models import (
    TransferClassification,
    TransferContext,
    TransferMovement,
    TransferSignal,
    TransferStage,
    TransferTerms,
)


class TransferClassifier(Protocol):
    def classify(
        self,
        text: str,
        source: TwitterSourceAccount,
        context: TransferContext,
    ) -> TransferSignal: ...


_STAGE_RULES: tuple[tuple[TransferStage, float, dict[str, str]], ...] = (
    (
        TransferStage.DENIED,
        0.94,
        {
            "denied_reports": r"\bden(?:y|ies|ied|ying) (?:the )?(?:transfer )?reports?\b",
            "no_truth": r"\bno truth (?:in|to) (?:the )?(?:transfer )?(?:report|rumou?r)s?\b",
            "not_for_sale": r"\bnot for sale\b",
            "will_not_leave": r"\bwill not (?:leave|depart)\b",
        },
    ),
    (
        TransferStage.FAILED,
        0.94,
        {
            "deal_collapsed": (
                r"\b(?:deal|move|transfer)(?: for [^.]{1,80})? (?:has )?collapsed\b"
            ),
            "deal_off": r"\b(?:deal|move|transfer) (?:is |is now )?off\b",
            "talks_broke_down": r"\btalks (?:have )?brok(?:e|en) down\b",
            "failed_medical": r"\bfailed (?:his |her |the )?medical\b",
            "bid_rejected": r"\bbid (?:has been |was )?rejected\b",
            "withdrew": r"\bwithdr(?:ew|awn) (?:from )?(?:the )?(?:deal|talks|race)\b",
        },
    ),
    (
        TransferStage.CONFIRMED,
        0.98,
        {
            "officially_signed": r"\bofficially (?:signs?|signed|joins?|joined)\b",
            "has_signed": r"\bhas signed (?:for|with|a new contract)\b",
            "completed_transfer": r"\b(?:completes?|completed) (?:a |the )?(?:transfer|move)\b",
            "club_announcement": r"\b(?:club|we) (?:is|are) (?:delighted|pleased) to announce\b",
            "contract_extended": r"\b(?:signs?|signed) (?:a )?new contract\b",
        },
    ),
    (
        TransferStage.MEDICAL,
        0.93,
        {
            "medical_booked": r"\bmedical (?:is )?(?:booked|scheduled)\b",
            "undergoing_medical": r"\bundergo(?:es|ing) (?:a )?medical\b",
            "medical_completed": r"\b(?:passed|completed) (?:his |her |the )?medical\b",
            "set_for_medical": r"\bset (?:to undergo|for) (?:a )?medical\b",
        },
    ),
    (
        TransferStage.AGREEMENT,
        0.91,
        {
            "agreement_reached": r"\bagreement (?:has been |is )?reached\b",
            "deal_agreed": r"\bdeal agreed\b",
            "terms_agreed": r"\b(?:personal )?terms (?:have been |are )?agreed\b",
            "verbal_agreement": r"\bverbal agreement\b",
            "agreed_to_join": r"\bagreed to (?:join|sign)\b",
        },
    ),
    (
        TransferStage.NEGOTIATION,
        0.82,
        {
            "in_talks": r"\bin talks\b",
            "talks_ongoing": r"\btalks (?:are )?(?:ongoing|continue|continuing)\b",
            "negotiations": r"\bnegotiat(?:e|es|ed|ing|ion|ions)\b",
            "discussing_terms": r"\bdiscuss(?:es|ed|ing)? (?:personal )?terms\b",
        },
    ),
    (
        TransferStage.BID,
        0.86,
        {
            "bid_submitted": r"\b(?:bid|offer) (?:has been |was )?(?:submitted|made|received)\b",
            "made_bid": r"\b(?:made|lodged|submit(?:s|ted)?) (?:a |an )?(?:bid|offer)\b",
            "formal_offer": r"\bformal offer\b",
        },
    ),
    (
        TransferStage.RUMOUR,
        0.66,
        {
            "linked_with": r"\blinked with (?:a )?(?:move|transfer)\b",
            "interested_in": r"\binterested in (?:signing )?\b",
            "transfer_target": r"\btransfer target\b",
            "considering_move": r"\bconsidering (?:a )?(?:move|bid|offer)\b",
            "monitoring": r"\bmonitoring (?:the )?(?:player|situation)\b",
            "set_sights": r"\bset (?:their |its )?sights on\b",
        },
    ),
)

_NEGATED_POSITIVE = re.compile(
    r"\b(?:has not|have not|not|never|no)\s+"
    r"(?:agreed|signed|submitted|made|lodged|bid|offer|negotiating|in talks|interested)\b"
    r"|\bno (?:agreement|deal|bid|offer|negotiations?|talks)\b",
    re.IGNORECASE,
)
_UNCERTAINTY = re.compile(
    r"\b(?:reportedly|rumou?red|unconfirmed|could|may|might|possible|possibly|"
    r"considering|expected to|set to)\b",
    re.IGNORECASE,
)
_CONTRACT_EXTENSION = re.compile(
    r"\b(?:contract extension|extend(?:s|ed|ing)? (?:his |her |their )?contract|"
    r"new contract|renew(?:s|ed|ing)? (?:his |her |their )?(?:deal|contract))\b",
    re.IGNORECASE,
)
_LOAN = re.compile(
    r"\b(?:on loan|loan (?:deal|move|agreement)|season-long loan|loan with "
    r"(?:an |a )?option|borrowed)\b",
    re.IGNORECASE,
)
_PERMANENT = re.compile(
    r"\b(?:permanent(?:ly)?|full transfer|outright (?:deal|transfer)|"
    r"obligation to buy)\b",
    re.IGNORECASE,
)
_DEPARTURE = re.compile(
    r"\b(?:leave|leaves|leaving|depart|departs|departure|exit|outgoing|"
    r"move away|sold|sell)\b",
    re.IGNORECASE,
)
_ARRIVAL = re.compile(
    r"\b(?:join|joins|joined|joining|sign|signs|signed|signing|arrival|"
    r"incoming|buy|target)\b",
    re.IGNORECASE,
)


class RuleBasedTransferClassifier:
    """Deterministic transfer classifier with explicit source and resolution gates."""

    def classify(
        self,
        text: str,
        source: TwitterSourceAccount,
        context: TransferContext,
    ) -> TransferSignal:
        normalized = " ".join(text.split())
        matched_rules: list[str] = []
        stage: TransferStage | None = None
        base_confidence = 0.0

        for candidate_stage, candidate_confidence, rules in _STAGE_RULES:
            matches = _matches(rules, normalized)
            if matches:
                stage = candidate_stage
                base_confidence = candidate_confidence
                matched_rules.extend(matches)
                break

        positive_negated = bool(_NEGATED_POSITIVE.search(normalized))
        if positive_negated and stage not in {TransferStage.DENIED, TransferStage.FAILED}:
            stage = None
            base_confidence = 0.0
            matched_rules.append("negated_positive_transfer")

        uncertain = bool(_UNCERTAINTY.search(normalized))
        if uncertain:
            matched_rules.append("uncertainty")

        terms = _terms(normalized)
        movement = _movement(normalized, terms)
        source_weight = max(0.0, min(float(source.trust_weight), 1.0))
        confidence = base_confidence * source_weight
        if uncertain and stage not in {TransferStage.DENIED, TransferStage.FAILED}:
            confidence *= 0.75

        aggregate_only = source.account_kind.is_aggregate_only
        if aggregate_only:
            confidence = min(confidence, 0.35)

        classification = TransferClassification(
            stage=stage,
            terms=terms,
            movement=movement,
            source_kind=source.account_kind,
            source_trust_weight=round(source_weight, 4),
            base_confidence=base_confidence,
            confidence=round(max(0.0, min(confidence, 1.0)), 4),
            aggregate_only=aggregate_only,
            negated=positive_negated,
            uncertain=uncertain,
            matched_rules=tuple(matched_rules),
        )
        return TransferSignal(
            classification=classification,
            player_resolution=context.player_resolution,
            origin_team=context.origin_team,
            destination_team=context.destination_team,
        )


def _matches(rules: dict[str, str], text: str) -> list[str]:
    return [name for name, pattern in rules.items() if re.search(pattern, text, re.IGNORECASE)]


def _terms(text: str) -> TransferTerms:
    if _CONTRACT_EXTENSION.search(text):
        return TransferTerms.CONTRACT_EXTENSION
    if _LOAN.search(text):
        return TransferTerms.LOAN
    if _PERMANENT.search(text):
        return TransferTerms.PERMANENT
    return TransferTerms.UNKNOWN


def _movement(text: str, terms: TransferTerms) -> TransferMovement:
    if terms is TransferTerms.CONTRACT_EXTENSION:
        return TransferMovement.RETENTION
    if _DEPARTURE.search(text):
        return TransferMovement.DEPARTURE
    if _ARRIVAL.search(text):
        return TransferMovement.ARRIVAL
    return TransferMovement.UNKNOWN
